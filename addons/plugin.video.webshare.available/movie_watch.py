"""Read-only Trakt movie status, downloaded outside Kodi list rendering."""
import hashlib
import json
import os
import queue
import threading
import time
from datetime import datetime


CACHE = 'family-movie-watch.json'
STATUS = 'Family.MovieWatch.Status'
OWNER = 'Family.MovieWatch.Owner'
PROGRESS = 'family.movie.progress'
WATCHED = 'family.movie.watched'


def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (AttributeError, ValueError):
        return 0


def movie_id(value):
    value = str(value or '')
    return value if value.isascii() and value.isdecimal() and int(value) > 0 else ''


def progress_percent(value):
    try:
        return max(1, min(99, round(float(value)))) if 0 < float(value) < 100 else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def index_trakt(core, path, watched):
    indexed = {}
    seen = set()
    for page in range(1, 1001):
        rows, pagination = core.trakt_page(path, {'page': page, 'limit': 250})
        if not isinstance(rows, list):
            raise ValueError('Expected a Trakt movie list')
        if not rows:
            return indexed
        signature = tuple((row.get('movie') or {}).get('ids', {}).get('trakt') for row in rows)
        if signature in seen:
            if not pagination and not watched:
                return indexed  # Older playback endpoints return their entire result on every page.
            raise RuntimeError('Trakt repeated a watched page')
        seen.add(signature)
        for row in rows:
            ident = movie_id(((row.get('movie') or {}).get('ids') or {}).get('tmdb'))
            if not ident:
                continue
            value = int(row.get('plays') or 0) if watched else progress_percent(row.get('progress'))
            when = timestamp(row.get('last_watched_at' if watched else 'paused_at'))
            if value > 0 and when >= indexed.get(ident, (0, 0))[1]:
                indexed[ident] = value, when
        if pagination.get('page-count', 0) and page >= pagination['page-count']:
            return indexed
    raise RuntimeError('Trakt movie pagination did not finish')


class MovieStatus:
    def __init__(self, family):
        path = os.path.join(family.PROFILE, CACHE)
        data = family.core.read_json(path, {}) or {}
        owner = family.HOME.getProperty(OWNER)
        if owner and data.get('owner') != owner:
            data = {}
        self.watched = data.get('watched', {})
        self.playback = data.get('playback', {})
        self.local = family.local_progress()

    def state(self, ident):
        ident = movie_id(ident)
        plays, last_watched = self.watched.get(ident, (0, 0))
        progress, paused = self.playback.get(ident, (0, 0))
        local = self.local.get(f'movie:{ident}:None:None') or {}
        if local and (not progress or float(local.get('updated') or 0) >= paused):
            position = float(local.get('position') or 0)
            duration = float(local.get('duration') or 0)
            paused = float(local.get('updated') or 0)
            progress = progress_percent(position * 100 / duration) if not local.get('completed') and position >= 15 and duration > 0 else 0
        if last_watched and last_watched >= paused:
            progress = 0
        return plays, progress

    def decorate(self, item, ident, native=True):
        plays, progress = self.state(ident)
        if progress:
            item.setProperty(PROGRESS, str(progress))
        elif plays:
            item.setProperty(WATCHED, 'true')
            if native:
                item.getVideoInfoTag().setPlaycount(plays)


class MovieWatchSync:
    def __init__(self, family):
        self.family = family
        self.path = os.path.join(family.PROFILE, CACHE)
        self.revision = family.HOME.getProperty('Family.Paging.Revision')
        self.next_sync = time.monotonic() + 1
        self.pending = False
        self.results = queue.Queue(maxsize=1)
        self.closed = threading.Event()

    def download(self):
        f = self.family
        old = f.core.read_json(self.path, {}) or {}
        owner = old.get('owner', '')
        try:
            _, token = f.auth()
            owner = hashlib.sha256(token.encode('utf-8')).hexdigest()
            activities = f.core.trakt_request('/sync/last_activities').get('movies') or {}
            current = old if old.get('owner') == owner else {}
            watched_at = activities.get('watched_at') or ''
            paused_at = activities.get('paused_at') or ''
            watched = current.get('watched') if current.get('watched_at') == watched_at else None
            playback = current.get('playback') if current.get('paused_at') == paused_at else None
            if watched is None:
                watched = index_trakt(f.core, '/sync/watched/movies', True)
            if playback is None:
                playback = index_trakt(f.core, '/sync/playback/movies', False)
            # A profile switch during a paged fetch must not mix two accounts.
            if not any(row['access_token'] == token for row in f.core.trakt_token_candidates()):
                raise RuntimeError('Trakt session changed while refreshing')
            data = {'owner': owner, 'watched_at': watched_at, 'paused_at': paused_at,
                    'watched': watched, 'playback': playback}
            if not self.closed.is_set() and data != old:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                temporary = self.path + '.new'
                with open(temporary, 'w', encoding='utf-8') as target:
                    json.dump(data, target, separators=(',', ':'))
                os.replace(temporary, self.path)
            self.results.put((owner, {'state': 'ready', 'watched': len(watched), 'in_progress': len(playback)}))
        except (OSError, ValueError, RuntimeError, AttributeError, TypeError, KeyError) as error:
            self.results.put((owner, {'state': 'retry', 'reason': type(error).__name__}))

    def tick(self, idle):
        now = time.monotonic()
        f = self.family
        if self.pending:
            try:
                owner, status = self.results.get_nowait()
            except queue.Empty:
                pass
            else:
                self.pending = False
                f.HOME.setProperty(OWNER, owner)
                f.HOME.setProperty(STATUS, json.dumps(status))
                self.next_sync = now + (180 if status['state'] == 'ready' else 60)
        revision = f.HOME.getProperty('Family.Paging.Revision')
        if revision != self.revision:
            self.revision = revision
            self.next_sync = min(self.next_sync, now + 12)
        if idle and not self.pending and now >= self.next_sync:
            self.pending = True
            threading.Thread(target=self.download, daemon=True).start()

    def close(self):
        self.closed.set()
