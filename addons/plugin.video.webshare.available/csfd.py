"""Atlas ratings for the focused title, refreshed by the family service."""
import json
import queue
import re
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from browser import CSFD_PERCENTAGES


SETTING = 'atlas_api_key'
ENDPOINT = 'https://aomdb.streamstr.stream/api/v1/titles/'
SCORE_TTL = 7 * 86400
MISSING_TTL = 24 * 3600
CACHE_TTL = 30 * 86400
POLL_INTERVAL = .4
FOCUS_DELAY = .6
FIELDS = (
    'ListItem.DBType', 'ListItem.UniqueID(tmdb)', 'ListItem.Property(tmdb_id)',
    'ListItem.UniqueID(imdb)', 'ListItem.Property(imdb_id)',
)
FIELDS_QUERY = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'XBMC.GetInfoLabels', 'params': {'labels': FIELDS}})


def imdb_id(value):
    return value if isinstance(value, str) and re.fullmatch(r'tt[0-9]{7,12}', value) else ''


def selected_title(labels):
    kind, native_tmdb, addon_tmdb, native_imdb, addon_imdb = (labels.get(key, '') for key in FIELDS)
    tmdb = next((value for value in (native_tmdb, addon_tmdb) if re.fullmatch(r'[1-9][0-9]{0,11}', value)), '')
    imdb = imdb_id(native_imdb) or imdb_id(addon_imdb)
    if kind in ('movie', 'tvshow') and (tmdb or imdb):
        return kind, tmdb, imdb
    return None


def atlas_score(body, ident, kind):
    if body.get('success') is not True or body.get('imdb_id') != ident:
        raise ValueError('Unexpected Atlas title')
    if (kind == 'movie' and body.get('title_type') != 'movie'
            or kind == 'tvshow' and body.get('title_type') not in ('tvSeries', 'tvMiniSeries')):
        raise ValueError('Unexpected Atlas media type')
    entry = body.get('csfd')
    if not entry:
        return None
    source = urlsplit(entry.get('url') or '')
    if (entry.get('imdb_id') != ident or entry.get('is_series') is not (kind == 'tvshow')
            or source.scheme != 'https' or source.hostname not in ('www.csfd.cz', 'csfd.cz', 'www.csfd.sk', 'csfd.sk')
            or not re.fullmatch(r'/film/[0-9]+(?:-[^/]+)?(?:/prehled)?/?', source.path)):
        raise ValueError('Unexpected ČSFD title')
    value = re.fullmatch(r'([0-9]{1,3})\s*%', str(entry.get('rating') or ''))
    return int(value[1]) if value and int(value[1]) <= 100 else None


def fetch_score(key, ident, kind):
    request = Request(f'{ENDPOINT}{ident}?language=cs-CZ&include_csfd=true', headers={
        'Accept': 'application/json', 'User-Agent': 'RodinneKino-Kodi/1.0',
    })
    request.add_unredirected_header('X-API-Key', key)
    with urlopen(request, timeout=5) as response:
        return atlas_score(json.loads(response.read(2_000_000)), ident, kind)


def cache_identity(title):
    kind, tmdb, imdb = title
    return kind + '_' + (tmdb or imdb)


class Ratings:
    def __init__(self, family):
        self.family = family
        self.results = queue.Queue(maxsize=1)
        self.pending = False
        self.active = None
        self.active_since = 0
        self.poll_at = 0
        self.retry_at = 0
        self.key = None
        self.key_check_at = 0
        self.memory = {}
        self.published = None

    def publish(self, title, score):
        desired = (title, score) if title and score is not None else (None, None)
        if desired == self.published:
            return
        self.published = desired
        home = self.family.HOME
        home.clearProperty('Family.CSFD.Score')
        if desired[0]:
            for field, value in zip(('Type', 'TMDb', 'IMDb'), title):
                home.setProperty('Family.CSFD.' + field, value)
            home.setProperty('Family.CSFD.Score', str(score))

    def close(self):
        self.publish(None, None)

    def load(self, key, title):
        core = self.family.core
        kind, tmdb, ident = title
        cache_key = cache_identity(title)
        saved = core.read_cache_entry('csfd', cache_key, CACHE_TTL)
        now = time.time()
        if saved and (not ident or saved.get('imdb') == ident):
            ident = saved.get('imdb') or ident
            if saved.get('refresh_at', 0) > now or not key:
                return saved, 'cached', 0
        else:
            saved = None
        if not key:
            return None, 'needs_key', 0
        score = None
        try:
            if not ident and tmdb:
                source = 'movie' if kind == 'movie' else 'tv'
                ident = imdb_id(core.tmdb_request(f'/{source}/{tmdb}/external_ids').get('imdb_id'))
            if ident:
                score = fetch_score(key, ident, kind)
        except HTTPError as error:
            if error.code in (401, 403):
                return saved, 'atlas_access_' + str(error.code), 900
            if error.code == 429:
                retry = error.headers.get('Retry-After') or ''
                return saved, 'atlas_limit', max(60, int(retry)) if retry.isdecimal() else 300
            if error.code != 404:
                return saved, 'atlas_unavailable', 60
        except (OSError, RuntimeError, ValueError, TypeError, AttributeError):
            return saved, 'atlas_unavailable', 60
        result = {'score': score, 'imdb': ident, 'refresh_at': now + (MISSING_TTL if score is None else SCORE_TTL)}
        core.write_cache_entry('csfd', cache_key, result)
        return result, 'updated' if ident else 'no_imdb_id', 0

    def tick(self, enabled):
        now = time.monotonic()
        if now < self.poll_at:
            return
        self.poll_at = now + POLL_INTERVAL
        if now >= self.key_check_at:
            self.key_check_at = now + 5
            key = self.family.ADDON.getSettingString(SETTING).strip()
            if key != self.key:
                self.key = key
                self.memory.clear()
                self.retry_at = 0
                self.family.HOME.setProperty('Family.CSFD.Status', 'ready' if key else 'needs_key')
        if self.pending:
            try:
                key, title, value, status, delay = self.results.get_nowait()
            except queue.Empty:
                pass
            else:
                self.pending = False
                if key == self.key:
                    if len(self.memory) >= 500:
                        self.memory.pop(next(iter(self.memory)))
                    current = time.time()
                    expiry = current + delay if delay else min(current + MISSING_TTL, value['refresh_at'])
                    self.memory[title] = (value, expiry)
                    self.retry_at = now + delay
                    self.family.HOME.setProperty('Family.CSFD.Status', status)
        labels = json.loads(self.family.xbmc.executeJSONRPC(FIELDS_QUERY)).get('result', {}) if enabled else {}
        title = selected_title(labels)
        if title != self.active:
            self.active = title
            self.active_since = now
        if not title:
            self.publish(None, None)
            return
        kind, tmdb, _ = title
        pilot = CSFD_PERCENTAGES.get(('movie' if kind == 'movie' else 'tv', int(tmdb or 0)))
        value, refresh_at = self.memory.get(title, (None, 0))
        score = value.get('score') if value is not None else None
        self.publish(title, pilot if score is None else score)
        if self.key and not self.pending and now >= self.retry_at and now - self.active_since >= FOCUS_DELAY and time.time() >= refresh_at:
            self.pending = True

            def run(key=self.key, target=title, previous=value):
                try:
                    result, status, delay = self.load(key, target)
                except (OSError, RuntimeError, ValueError, TypeError, AttributeError):
                    result, status, delay = previous, 'atlas_unavailable', 60
                self.results.put((key, target, result, status, delay))

            threading.Thread(target=run, daemon=True).start()
