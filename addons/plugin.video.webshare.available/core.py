# -*- coding: utf-8 -*-
import sys
import os
import re
import json
import time
import ssl
import hashlib
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urlencode, parse_qs, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from xml.etree import ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs


# ---------------------------------------------------------------------------
# Basic configuration
# ---------------------------------------------------------------------------

ADDON = xbmcaddon.Addon("plugin.video.webshare.available")
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_NAME = ADDON.getAddonInfo("name")

HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 and str(sys.argv[1]).lstrip("-").isdigit() else -1
BASE_URL = sys.argv[0] if len(sys.argv) > 0 else "plugin://{}/".format(ADDON_ID)
PARAMS = parse_qs(sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith("?") else "")

TMDB_HELPER_ID = "plugin.video.themoviedb.helper"
TRAKT_SYNC_ID = "script.module.tmdbhelper.sync.trakt"
YAWSP_ID = "plugin.video.yawsp"
SKIN_ID = "skin.arctic.fuse.3"

TRAKT_API = "https://api.trakt.tv"
TMDB_API = "https://api.themoviedb.org/3"
WEBSHARE_API = "https://webshare.cz/api"
WEBSHARE_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36'

PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
CACHE_ROOT = os.path.join(PROFILE, "cache")
BACKUP_DIR = os.path.join(PROFILE, "arctic_backups")

SOURCE_TTL = 2 * 60 * 60
EPISODE_SOURCE_TTL = 60 * 60
LIST_TTL = 2 * 60 * 60
AVAIL_TTL = 6 * 60 * 60
META_TTL = 7 * 24 * 60 * 60

MAX_WIDGET_ITEMS = 15
MAX_SOURCE_ITEMS = 36
SOURCE_BATCH = 12
MAX_WORKERS = 4

POSTER_BASE = "https://image.tmdb.org/t/p/w500"
BACKDROP_BASE = "https://image.tmdb.org/t/p/w780"
STILL_BASE = "https://image.tmdb.org/t/p/w780"

VIDEO_EXTS = (".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".m2ts", ".wmv", ".webm")
BAD_TERMS = (
    "trailer", "teaser", "sample", "making of", "makingof", "featurette",
    "behind the scenes", "behindthescenes", "interview", "soundtrack",
)
RELEASE_TERMS = (
    "2160p", "1080p", "720p", "480p", "bluray", "blu ray", "web dl", "webdl",
    "webrip", "brrip", "dvdrip", "hdtv", "hdrip", "remux", "x264", "x265",
    "h264", "h265", "hevc", "av1", "uhd", "hdr", "dv",
)
ROMAN_SEQUEL = {"i","ii","iii","iv","v","vi","vii","viii","ix","x"}
SEQUEL_WORDS = {"part","chapter","volume","vol","episode","ep"}

MOVIE_SOURCES = [
    ("recommendations", "Pro tebe"),
    ("watchlist", "Watchlist"),
    ("trending", "Trendy"),
    ("popular", "Populární"),
    ("now_playing", "V kinech"),
    ("top_rated", "Top hodnocené"),
]

TV_SOURCES = [
    ("next", "Další epizody", "episode"),
    ("playback", "Rozkoukané epizody", "episode"),
    ("recommendations", "Pro tebe", "tv"),
    ("watchlist", "Watchlist", "tv"),
    ("trending", "Trendy", "tv"),
    ("popular", "Populární", "tv"),
    ("airing_today", "Dnes vysílané", "tv"),
]


# ---------------------------------------------------------------------------
# File/cache helpers
# ---------------------------------------------------------------------------

def log(msg, level=xbmc.LOGINFO):
    xbmc.log("[{}] {}".format(ADDON_NAME, msg), level)

def notify(msg, icon=xbmcgui.NOTIFICATION_INFO, ms=4000):
    xbmcgui.Dialog().notification(ADDON_NAME, msg, icon, ms)

def now():
    return int(time.time())

def ensure_dirs():
    for path in (
        PROFILE,
        CACHE_ROOT,
        os.path.join(CACHE_ROOT, "source"),
        os.path.join(CACHE_ROOT, "list"),
        os.path.join(CACHE_ROOT, "availability"),
        os.path.join(CACHE_ROOT, "meta"),
        BACKUP_DIR,
    ):
        if not xbmcvfs.exists(path):
            xbmcvfs.mkdirs(path)

def read_text(path):
    if not xbmcvfs.exists(path):
        return None
    f = xbmcvfs.File(path)
    try:
        return f.read()
    finally:
        f.close()

def write_text(path, content):
    parent = os.path.dirname(path)
    if parent and not xbmcvfs.exists(parent):
        xbmcvfs.mkdirs(parent)
    f = xbmcvfs.File(path, "w")
    try:
        f.write(content)
    finally:
        f.close()

def read_json(path, default=None):
    raw = read_text(path)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default

def write_json(path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))

def safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value))

def hashed_name(value):
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()

def cache_path(category, key):
    return os.path.join(CACHE_ROOT, category, safe_name(key) + ".json")

def avail_path(key):
    return os.path.join(CACHE_ROOT, "availability", hashed_name(key) + ".json")

def read_cache_entry(category, key, ttl):
    path = cache_path(category, key)
    data = read_json(path, None)
    if not isinstance(data, dict):
        return None
    if now() - int(data.get("ts") or 0) >= ttl:
        return None
    return data.get("data")

def write_cache_entry(category, key, data):
    write_json(cache_path(category, key), {"ts": now(), "data": data})

def read_availability(key):
    data = read_json(avail_path(key), None)
    if not isinstance(data, dict):
        return None
    if now() - int(data.get("ts") or 0) >= AVAIL_TTL:
        return None
    return data.get("data")

def write_availability(key, data):
    write_json(avail_path(key), {"ts": now(), "data": data})

def clear_cache():
    if xbmcvfs.exists(CACHE_ROOT):
        xbmcvfs.rmdir(CACHE_ROOT, force=True)
    ensure_dirs()

def qurl(action, **kwargs):
    args = {"action": action}
    args.update({k: v for k, v in kwargs.items() if v is not None})
    return "{}?{}".format(BASE_URL, urlencode(args))


# ---------------------------------------------------------------------------
# HTTP and credentials
# ---------------------------------------------------------------------------

def addon_source_file(addon_id, relative):
    addon = xbmcaddon.Addon(addon_id)
    base = addon.getAddonInfo("path").rstrip("/\\")
    return base + "/" + relative.lstrip("/")

def parse_public_key(path, variable):
    txt = read_text(path) or ""
    m = re.search(r"(?m)^\s*{}\s*=\s*['\"]([^'\"]+)['\"]".format(re.escape(variable)), txt)
    return m.group(1) if m else ""

def http_json(url, headers=None, timeout=25, pagination=None):
    req = Request(url, headers=headers or {})
    ctx = ssl.create_default_context()
    try:
        with urlopen(req, timeout=timeout, context=ctx) as resp:
            if pagination is not None:
                for name in ('page', 'page-count', 'item-count', 'limit'):
                    value = resp.headers.get('X-Pagination-' + name, '')
                    if str(value).isdigit():pagination[name] = int(value)
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw), resp.getcode()
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except Exception:
            body = {"raw": raw[:500]}
        return body, exc.code

def xml_post(url, fields, timeout=20):
    body = urlencode(fields).encode("utf-8")
    headers = {
        "User-Agent": WEBSHARE_USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://webshare.cz",
    }
    req = Request(url, data=body, headers=headers)
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read()
    return ET.fromstring(raw)

def parse_token_blob(raw):
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except Exception:
        return None
    if not isinstance(obj, dict) or not obj.get("access_token"):
        return None
    return obj

def trakt_client_id():
    # TMDbHelper 6.20.x moved Trakt into its own sync provider. Support both
    # layouts without copying credentials into this add-on or its package.
    for addon_id, relative in (
        (TRAKT_SYNC_ID, "resources/lib/tmdbhelper_sync_trakt/api/keys.py"),
        (TMDB_HELPER_ID, "resources/tmdbhelper/lib/api/api_keys/trakt.py"),
    ):
        try:
            value = parse_public_key(addon_source_file(addon_id, relative), "CLIENT_ID")
        except (RuntimeError, OSError):
            continue
        if value:
            return value
    return ""

def trakt_token_candidates():
    values = []
    # The new owner's persisted token takes precedence over an old session
    # property or legacy setting that may survive migration/token renewal.
    for addon_id, setting in ((TRAKT_SYNC_ID, "token"),):
        try:
            values.append(xbmcaddon.Addon(addon_id).getSetting(setting))
        except RuntimeError:
            pass
    values.append(xbmcgui.Window(10000).getProperty("TraktUserToken"))
    try:
        values.append(xbmcaddon.Addon(TMDB_HELPER_ID).getSetting("trakt_token"))
    except RuntimeError:
        pass
    candidates = []
    for raw in values:
        obj = parse_token_blob(raw)
        if obj and not any(row["access_token"] == obj["access_token"] for row in candidates):
            candidates.append(obj)
    return candidates

def tmdb_api_key():
    try:
        path = addon_source_file(
            TMDB_HELPER_ID,
            "resources/tmdbhelper/lib/api/api_keys/tmdb.py",
        )
        return parse_public_key(path, "API_KEY")
    except Exception:
        return ""

def trakt_headers(client_id, access_token):
    return {
        "trakt-api-version": "2",
        "trakt-api-key": client_id,
        "Authorization": "Bearer " + access_token,
        "Content-Type": "application/json",
        "User-Agent": "Kodi Webshare Available",
    }

def get_trakt_auth():
    candidates = trakt_token_candidates()
    if not candidates:
        raise RuntimeError("Trakt nemá dostupný token. Ověř přihlášení v Servisu.")

    client_id = trakt_client_id()
    if not client_id:
        raise RuntimeError("TRAKT_CLIENT_UNAVAILABLE")

    for obj in candidates:
        token = obj.get("access_token")
        _, status = http_json(
            TRAKT_API + "/sync/last_activities",
            headers=trakt_headers(client_id, token),
            timeout=15,
        )
        if status == 200:
            return client_id, token

    raise RuntimeError("Trakt odmítl token. Ověř přihlášení v Servisu.")

def get_webshare_token():
    try:
        addon = xbmcaddon.Addon(YAWSP_ID)
    except Exception:
        raise RuntimeError("YAWSP není nainstalovaný nebo aktivní.")
    token = addon.getSetting("token") or ""
    if not token:
        raise RuntimeError("YAWSP nemá Webshare token. Otevři YAWSP a ověř přihlášení.")
    return token


def refresh_webshare_token():
    """Renew YAWSP's expired token with its existing saved credentials."""
    import importlib.util

    addon = xbmcaddon.Addon(YAWSP_ID)
    username = addon.getSetting('wsuser')
    password = addon.getSetting('wspass')
    if not username or not password:
        raise RuntimeError('Webshare credentials are missing')
    salt_response = xml_post(WEBSHARE_API + '/salt/',
                             {'username_or_email': username}, timeout=12)
    if salt_response.findtext('status') != 'OK' or not salt_response.findtext('salt'):
        raise RuntimeError('Webshare salt request failed')
    crypt_path = os.path.join(addon.getAddonInfo('path'), 'md5crypt.py')
    spec = importlib.util.spec_from_file_location('family_yawsp_md5crypt', crypt_path)
    if spec is None or spec.loader is None:
        raise RuntimeError('YAWSP password digest is unavailable')
    crypt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(crypt)
    digest_part = crypt.md5crypt(password.encode('utf-8'),
                                 salt_response.findtext('salt').encode('utf-8'))
    if isinstance(digest_part, str):
        digest_part = digest_part.encode('utf-8')
    encrypted = hashlib.sha1(digest_part).hexdigest()
    digest = hashlib.md5((username + ':Webshare:' + encrypted).encode('utf-8')).hexdigest()
    response = xml_post(WEBSHARE_API + '/login/', {
        'username_or_email': username, 'password': encrypted,
        'digest': digest, 'keep_logged_in': 1,
    }, timeout=12)
    token = response.findtext('token') if response.findtext('status') == 'OK' else None
    if not token:
        raise RuntimeError('Webshare login failed')
    addon.setSetting('token', token)
    return token


# ---------------------------------------------------------------------------
# Source list helpers
# ---------------------------------------------------------------------------

def year_from_date(s):
    try:
        return int(str(s)[:4])
    except Exception:
        return 0

def trakt_request(path, params=None):
    client_id, token = get_trakt_auth()
    url = TRAKT_API + path
    if params:
        url += "?" + urlencode(params)
    data, status = http_json(url, headers=trakt_headers(client_id, token), timeout=25)
    if status != 200:
        raise RuntimeError("Trakt HTTP {} pro {}".format(status, path))
    return data or []

def trakt_page(path, params=None):
    client_id, token = get_trakt_auth()
    address = TRAKT_API + path + ('?' + urlencode(params) if params else '')
    pagination = {}
    data, status = http_json(address, headers=trakt_headers(client_id, token), timeout=25, pagination=pagination)
    if status != 200:raise RuntimeError('Trakt HTTP {}'.format(status))
    return data or [], pagination

def tmdb_request(path, params=None):
    key = tmdb_api_key()
    if not key:
        raise RuntimeError("Nelze načíst TMDb API key z TMDb Helperu.")
    q = {"api_key": key, "language": "cs-CZ"}
    if params:
        q.update(params)
    url = TMDB_API + path + "?" + urlencode(q)
    data, status = http_json(url, timeout=25)
    if status != 200:
        raise RuntimeError("TMDb HTTP {} pro {}".format(status, path))
    return data or {}

def normalise_trakt_media(row, kind):
    obj = row.get("movie" if kind == "movie" else "show", row)
    ids = obj.get("ids") or {}
    title = obj.get("title") or obj.get("name") or ""
    premiered = obj.get("released") or obj.get("first_aired") or obj.get("first_air_date") or ""
    return {
        "kind": kind,
        "title": title,
        "year": int(obj.get("year") or year_from_date(premiered)),
        "tmdb_id": ids.get("tmdb"),
        "imdb_id": ids.get("imdb"),
        "trakt_id": ids.get("trakt"),
        "trakt_slug": ids.get("slug"),
        "premiered": premiered,
    }

def normalise_tmdb_media(obj, kind):
    if kind == "movie":
        title = obj.get("title") or obj.get("original_title") or ""
        date = obj.get("release_date") or ""
    else:
        title = obj.get("name") or obj.get("original_name") or ""
        date = obj.get("first_air_date") or ""
    return {
        "kind": kind,
        "title": title,
        "year": year_from_date(date),
        "tmdb_id": obj.get("id"),
        "imdb_id": None,
        "trakt_id": None,
        "trakt_slug": None,
        "premiered": date,
    }

def fetch_source(kind, source, force=False):
    key = "{}_{}".format(kind, source)
    ttl = EPISODE_SOURCE_TTL if kind == "episode" else SOURCE_TTL
    if not force:
        cached = read_cache_entry("source", key, ttl)
        if cached is not None:
            return cached

    if kind in ("movie", "tv"):
        if source == "recommendations":
            path = "/recommendations/movies" if kind == "movie" else "/recommendations/shows"
            rows = trakt_request(path, {"limit": MAX_SOURCE_ITEMS})
            items = [normalise_trakt_media(x, kind) for x in rows]

        elif source == "watchlist":
            path = "/sync/watchlist/movies" if kind == "movie" else "/sync/watchlist/shows"
            rows = trakt_request(path, {"extended": "full", "limit": MAX_SOURCE_ITEMS})
            items = [normalise_trakt_media(x, kind) for x in rows]

        else:
            endpoints = {
                ("movie", "trending"): "/trending/movie/week",
                ("movie", "popular"): "/movie/popular",
                ("movie", "now_playing"): "/movie/now_playing",
                ("movie", "top_rated"): "/movie/top_rated",
                ("tv", "trending"): "/trending/tv/week",
                ("tv", "popular"): "/tv/popular",
                ("tv", "airing_today"): "/tv/airing_today",
            }
            endpoint = endpoints.get((kind, source))
            if not endpoint:
                raise RuntimeError("Neznámý zdroj {} / {}".format(kind, source))
            payload = tmdb_request(endpoint, {"page": 1, "region": "CZ"})
            items = [normalise_tmdb_media(x, kind) for x in (payload.get("results") or [])]

    elif kind == "episode":
        if source == "playback":
            rows = trakt_request("/sync/playback/episodes", {"extended": "full", "limit": MAX_SOURCE_ITEMS})
            items = []
            for row in rows:
                ep = row.get("episode") or {}
                show = row.get("show") or {}
                ids = show.get("ids") or {}
                if not show or not ep:
                    continue
                items.append({
                    "kind": "episode",
                    "show_title": show.get("title") or "",
                    "show_year": int(show.get("year") or 0),
                    "tmdb_id": ids.get("tmdb"),
                    "imdb_id": ids.get("imdb"),
                    "trakt_id": ids.get("trakt"),
                    "trakt_slug": ids.get("slug"),
                    "season": int(ep.get("season") or 0),
                    "episode": int(ep.get("number") or 0),
                    "episode_title": ep.get("title") or "",
                    "premiered": ep.get("first_aired") or "",
                    "progress": float(row.get("progress") or 0),
                    "paused_at": row.get("paused_at") or "",
                })

        elif source == "next":
            watched = trakt_request("/sync/watched/shows", {"extended": "full", "limit": MAX_SOURCE_ITEMS})
            watched.sort(key=lambda x: x.get("last_watched_at") or "", reverse=True)
            watched = watched[:24]

            def get_next(row):
                show = row.get("show") or {}
                ids = show.get("ids") or {}
                slug = ids.get("slug") or ids.get("trakt")
                if not slug:
                    return None
                client_id, token = get_trakt_auth()
                path = "/shows/{}/progress/watched".format(quote(str(slug), safe=""))
                params = {
                    "hidden": "false",
                    "specials": "false",
                    "count_specials": "false",
                    "extended": "full",
                }
                url = TRAKT_API + path + "?" + urlencode(params)
                data, status = http_json(url, headers=trakt_headers(client_id, token), timeout=25)
                if status != 200 or not isinstance(data, dict):
                    return None
                ep = data.get("next_episode") or {}
                if not ep:
                    return None
                first_aired = ep.get("first_aired") or ""
                if first_aired:
                    try:
                        aired_dt = datetime.fromisoformat(first_aired.replace("Z", "+00:00"))
                        if aired_dt > datetime.now(timezone.utc):
                            return None
                    except Exception:
                        pass
                return {
                    "kind": "episode",
                    "show_title": show.get("title") or "",
                    "show_year": int(show.get("year") or 0),
                    "tmdb_id": ids.get("tmdb"),
                    "imdb_id": ids.get("imdb"),
                    "trakt_id": ids.get("trakt"),
                    "trakt_slug": ids.get("slug"),
                    "season": int(ep.get("season") or 0),
                    "episode": int(ep.get("number") or 0),
                    "episode_title": ep.get("title") or "",
                    "premiered": first_aired,
                    "last_watched_at": row.get("last_watched_at") or "",
                }

            items = []
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futures = [pool.submit(get_next, row) for row in watched]
                for f in as_completed(futures):
                    try:
                        item = f.result()
                    except Exception:
                        item = None
                    if item:
                        items.append(item)
            items.sort(key=lambda x: x.get("last_watched_at") or "", reverse=True)

        else:
            raise RuntimeError("Neznámý epizodní zdroj {}".format(source))

    else:
        raise RuntimeError("Neznámý typ {}".format(kind))

    items = [x for x in items if x and (x.get("title") or x.get("show_title"))][:MAX_SOURCE_ITEMS]
    write_cache_entry("source", key, items)
    return items


# ---------------------------------------------------------------------------
# TMDb metadata
# ---------------------------------------------------------------------------

def fetch_meta(kind, item):
    if kind == "episode":
        key = "episode_{}_{}_{}".format(item.get("tmdb_id"), item.get("season"), item.get("episode"))
    else:
        key = "{}_{}".format(kind, item.get("tmdb_id"))

    cached = read_cache_entry("meta", key, META_TTL)
    if cached is not None:
        return cached

    tmdb_id = item.get("tmdb_id")
    if not tmdb_id:
        return {}

    if kind == "movie":
        payload = tmdb_request(
            "/movie/{}".format(tmdb_id),
            {"append_to_response": "alternative_titles"}
        )
        alt = (payload.get("alternative_titles") or {}).get("titles") or []
        title = payload.get("title") or item.get("title") or ""
        original = payload.get("original_title") or title
        date = payload.get("release_date") or item.get("premiered") or ""
        poster = payload.get("poster_path") or ""
        backdrop = payload.get("backdrop_path") or ""

    elif kind == "tv":
        payload = tmdb_request(
            "/tv/{}".format(tmdb_id),
            {"append_to_response": "alternative_titles"}
        )
        alt = (payload.get("alternative_titles") or {}).get("results") or []
        title = payload.get("name") or item.get("title") or ""
        original = payload.get("original_name") or title
        date = payload.get("first_air_date") or item.get("premiered") or ""
        poster = payload.get("poster_path") or ""
        backdrop = payload.get("backdrop_path") or ""

    else:
        show_item = {
            "tmdb_id": tmdb_id,
            "title": item.get("show_title") or "",
            "year": item.get("show_year") or 0,
        }
        show_meta = fetch_meta("tv", show_item)
        payload = tmdb_request(
            "/tv/{}/season/{}/episode/{}".format(
                tmdb_id, item.get("season"), item.get("episode")
            )
        )
        result = {
            "title": payload.get("name") or item.get("episode_title") or "",
            "show_title": show_meta.get("title") or item.get("show_title") or "",
            "original_show_title": show_meta.get("original_title") or item.get("show_title") or "",
            "show_titles": show_meta.get("titles") or [item.get("show_title") or ""],
            "season": int(item.get("season") or 0),
            "episode": int(item.get("episode") or 0),
            "plot": payload.get("overview") or "",
            "premiered": payload.get("air_date") or str(item.get("premiered") or "")[:10],
            "runtime": int(payload.get("runtime") or 0),
            "rating": float(payload.get("vote_average") or 0),
            "votes": int(payload.get("vote_count") or 0),
            "still_path": payload.get("still_path") or "",
            "poster_path": show_meta.get("poster_path") or "",
            "backdrop_path": show_meta.get("backdrop_path") or "",
        }
        write_cache_entry("meta", key, result)
        return result

    titles = []
    for value in (item.get("title"), title, original):
        if value and value not in titles:
            titles.append(value)

    alt = sorted(alt, key=lambda x: 0 if x.get("iso_3166_1") == "CZ" else 1)
    for obj in alt:
        value = obj.get("title")
        if value and value not in titles:
            titles.append(value)
        if len(titles) >= 10:
            break

    result = {
        "title": title,
        "original_title": original,
        "titles": titles,
        "year": year_from_date(date) or int(item.get("year") or 0),
        "premiered": date,
        "plot": payload.get("overview") or "",
        "runtime": int(payload.get("runtime") or (payload.get("episode_run_time") or [0])[0] or 0),
        "rating": float(payload.get("vote_average") or 0),
        "votes": int(payload.get("vote_count") or 0),
        "genres": [x.get("name") for x in (payload.get("genres") or []) if x.get("name")],
        "poster_path": poster,
        "backdrop_path": backdrop,
    }
    write_cache_entry("meta", key, result)
    return result


# ---------------------------------------------------------------------------
# Webshare matching
# ---------------------------------------------------------------------------

def deaccent(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch))

def norm(s):
    s = deaccent(s).lower()
    s = re.sub(r"[._\-\[\]\(\)\{\}:;,+'!]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tokens(s):
    return re.findall(r"[a-z0-9]+", norm(s))

def find_subsequence(haystack, needle):
    if not needle or len(needle) > len(haystack):
        return -1
    for i in range(len(haystack) - len(needle) + 1):
        if haystack[i:i+len(needle)] == needle:
            return i
    return -1

def sequel_conflict(candidate_title, expected_title):
    ct = tokens(candidate_title)
    et = tokens(expected_title)
    pos = find_subsequence(ct, et)
    if pos < 0:
        return None
    extras = ct[:pos] + ct[pos + len(et):]
    expected_set = set(et)

    for t in extras:
        if t.isdigit():
            n = int(t)
            if 1900 <= n <= 2099:
                continue
            if t not in expected_set:
                return t
        if t in ROMAN_SEQUEL and t not in expected_set:
            return t

    for idx, t in enumerate(extras):
        if t in SEQUEL_WORDS:
            return t
        if idx > 0 and extras[idx-1] in SEQUEL_WORDS:
            return t
    return None

def title_similarity(expected_titles, candidate_title):
    best = 0.0
    best_title = ""
    nc = norm(candidate_title)
    for title in [x for x in expected_titles if x]:
        nt = norm(title)
        if not nt:
            continue
        if nc == nt:
            sim = 1.0
        elif nt in nc or nc in nt:
            sim = 0.94
        else:
            ratio = SequenceMatcher(None, nt, nc).ratio()
            te = set(nt.split())
            tc = set(nc.split())
            overlap = len(te & tc) / float(len(te)) if te else 0.0
            sim = max(ratio, overlap * 0.92)
        if sim > best:
            best = sim
            best_title = title
    return best, best_title

def webshare_search(query, token, limit=20):
    xml = xml_post(
        WEBSHARE_API + "/search/",
        {
            "what": query,
            "category": "video",
            "sort": "rating",
            "limit": int(limit),
            "offset": 0,
            "wst": token,
            "maybe_removed": "true",
        },
    )
    status = xml.findtext("status") or ""
    if status != "OK":
        raise RuntimeError("Webshare search: {}".format(status or "UNKNOWN"))

    out = []
    for node in xml.iter("file"):
        def val(name):
            n = node.find(name)
            return (n.text or "") if n is not None else ""
        try:
            size = int(val("size"))
        except Exception:
            size = None
        out.append({"name": val("name"), "ident": val("ident"), "size": size})
    return out

def base_file_score(candidate):
    name = candidate.get("name") or ""
    score = 0
    reasons = []
    if any(name.lower().endswith(ext) for ext in VIDEO_EXTS):
        score += 5
        reasons.append("video")
    else:
        score -= 40
        reasons.append("not-video")
    low = norm(name)
    for bad in BAD_TERMS:
        if bad in low:
            score -= 70
            reasons.append("bad:{}".format(bad))
            break
    size = candidate.get("size")
    if size is not None:
        if size >= 300 * 1024**2:
            score += 5
            reasons.append("size")
        elif size < 150 * 1024**2:
            score -= 25
            reasons.append("tiny")
    return score, reasons

def movie_title_part(filename, year):
    base = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", filename or "")
    if year:
        m = re.search(r"(?<!\d){}(?!\d)".format(re.escape(str(year))), base)
        if m:
            return base[:m.start()]
    low = norm(base)
    cut = len(low)
    for term in RELEASE_TERMS:
        pos = low.find(term)
        if pos >= 0:
            cut = min(cut, pos)
    return low[:cut]

def score_movie(candidate, titles_list, year):
    score, reasons = base_file_score(candidate)
    name = candidate.get("name") or ""

    years = [int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", name)]
    if year:
        if year in years:
            score += 30
            reasons.append("year")
        elif years:
            score -= 55
            reasons.append("wrong-year")
        else:
            reasons.append("no-year")

    part = movie_title_part(name, year)
    sim, best_title = title_similarity(titles_list, part)
    score += int(round(sim * 55))
    reasons.append("title:{:.0f}%".format(sim * 100))

    if best_title:
        marker = sequel_conflict(part, best_title)
        if marker:
            score -= 80
            reasons.append("sequel-conflict:{}".format(marker))
    return max(-100, min(100, score)), reasons

EP_PATTERNS = (
    re.compile(r"(?i)s0*(\d{1,2})[\s._-]*e0*(\d{1,3})"),
    re.compile(r"(?i)(?<!\d)(\d{1,2})x0*(\d{1,3})(?!\d)"),
    re.compile(r"(?i)season[\s._-]*(\d{1,2})[\s._-]*episode[\s._-]*(\d{1,3})"),
)
SEASON_PATTERNS = (
    re.compile(r"(?i)s0*(\d{1,2})(?![\s._-]*e\d)"),
    re.compile(r"(?i)season[\s._-]*(\d{1,2})"),
)

def episode_markers(filename):
    found = []
    for rx in EP_PATTERNS:
        for m in rx.finditer(filename or ""):
            try:
                found.append((int(m.group(1)), int(m.group(2)), m.start()))
            except Exception:
                pass
    return found

def episodic_title_part(filename):
    base = re.sub(r"\.[A-Za-z0-9]{2,5}$", "", filename or "")
    starts = []
    for rx in EP_PATTERNS + SEASON_PATTERNS:
        m = rx.search(base)
        if m:
            starts.append(m.start())
    if starts:
        return base[:min(starts)]
    low = norm(base)
    cut = len(low)
    for term in RELEASE_TERMS:
        pos = low.find(term)
        if pos >= 0:
            cut = min(cut, pos)
    return low[:cut]

def has_series_marker(filename):
    if episode_markers(filename):
        return True
    return any(rx.search(filename or "") for rx in SEASON_PATTERNS)

def score_tv(candidate, titles_list, show_year):
    score, reasons = base_file_score(candidate)
    name = candidate.get("name") or ""
    if has_series_marker(name):
        score += 30
        reasons.append("series-marker")
    else:
        score -= 30
        reasons.append("no-series-marker")

    part = episodic_title_part(name)
    sim, best_title = title_similarity(titles_list, part)
    score += int(round(sim * 55))
    reasons.append("title:{:.0f}%".format(sim * 100))

    years = [int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", name)]
    if show_year and years:
        if show_year in years:
            score += 10
            reasons.append("year")
        else:
            score -= 25
            reasons.append("wrong-year")

    if best_title:
        marker = sequel_conflict(part, best_title)
        if marker:
            score -= 80
            reasons.append("sequel-conflict:{}".format(marker))
    return max(-100, min(100, score)), reasons

def score_episode(candidate, titles_list, season, episode):
    score, reasons = base_file_score(candidate)
    name = candidate.get("name") or ""
    markers = episode_markers(name)
    if markers:
        if any(s == season and e == episode for s, e, _ in markers):
            score += 45
            reasons.append("exact-episode")
        else:
            score -= 80
            reasons.append("wrong-episode")
    else:
        score -= 45
        reasons.append("no-episode-marker")

    part = episodic_title_part(name)
    sim, best_title = title_similarity(titles_list, part)
    score += int(round(sim * 55))
    reasons.append("title:{:.0f}%".format(sim * 100))

    if best_title:
        marker = sequel_conflict(part, best_title)
        if marker:
            score -= 80
            reasons.append("sequel-conflict:{}".format(marker))
    return max(-100, min(100, score)), reasons

def best_candidate(candidates, scorer, *args):
    best = None
    best_score = -999
    best_reasons = []
    for candidate in candidates:
        score, reasons = scorer(candidate, *args)
        if score > best_score:
            best, best_score, best_reasons = candidate, score, reasons
    return best, best_score, best_reasons

def availability_key(kind, item):
    if kind == "episode":
        return "episode:{}:{}:{}".format(item.get("tmdb_id"), item.get("season"), item.get("episode"))
    return "{}:{}".format(kind, item.get("tmdb_id") or "{}:{}".format(item.get("title"), item.get("year")))

def check_availability(kind, item, token, force=False):
    key = availability_key(kind, item)
    if not force:
        cached = read_availability(key)
        if cached is not None:
            return cached

    if kind == "movie":
        title = item.get("title") or ""
        year = int(item.get("year") or 0)
        candidates = webshare_search("{} {}".format(title, year).strip(), token)
        best, score, reasons = best_candidate(candidates, score_movie, [title], year)
        if score < 85:
            meta = fetch_meta("movie", item)
            titles_list = meta.get("titles") or [title]
            for alt in titles_list[:5]:
                query = "{} {}".format(alt, year).strip()
                candidates = webshare_search(query, token)
                cand, sc, rs = best_candidate(candidates, score_movie, titles_list, year)
                if sc > score:
                    best, score, reasons = cand, sc, rs
                if score >= 85:
                    break
        threshold = 85

    elif kind == "tv":
        title = item.get("title") or ""
        show_year = int(item.get("year") or 0)
        candidates = webshare_search(title, token)
        best, score, reasons = best_candidate(candidates, score_tv, [title], show_year)
        if score < 80:
            meta = fetch_meta("tv", item)
            titles_list = meta.get("titles") or [title]
            for alt in titles_list[:5]:
                candidates = webshare_search(alt, token)
                cand, sc, rs = best_candidate(candidates, score_tv, titles_list, show_year)
                if sc > score:
                    best, score, reasons = cand, sc, rs
                if score >= 80:
                    break
        threshold = 80

    else:
        show_title = item.get("show_title") or ""
        season = int(item.get("season") or 0)
        episode = int(item.get("episode") or 0)
        code = "S{:02d}E{:02d}".format(season, episode)
        candidates = webshare_search("{} {}".format(show_title, code), token)
        best, score, reasons = best_candidate(candidates, score_episode, [show_title], season, episode)
        if score < 85:
            meta = fetch_meta("episode", item)
            titles_list = meta.get("show_titles") or [show_title]
            for alt in titles_list[:5]:
                candidates = webshare_search("{} {}".format(alt, code), token)
                cand, sc, rs = best_candidate(candidates, score_episode, titles_list, season, episode)
                if sc > score:
                    best, score, reasons = cand, sc, rs
                if score >= 85:
                    break
        threshold = 85

    result = {
        "state": "AVAILABLE" if score >= threshold else ("UNCERTAIN" if score >= threshold - 15 else "NOT_AVAILABLE"),
        "score": int(score if score != -999 else 0),
        "candidate": best or {},
        "reasons": reasons,
    }
    write_availability(key, result)
    return result


# ---------------------------------------------------------------------------
# Building filtered lists
# ---------------------------------------------------------------------------

def list_key(kind, source):
    return "{}_{}".format(kind, source)

def lock_prop(kind, source):
    return "WebshareAvailable.Building.{}.{}".format(kind, source)

def build_list(kind, source, force=False, manual=False):
    key = list_key(kind, source)
    if not force:
        cached = read_cache_entry("list", key, LIST_TTL)
        if cached is not None:
            return cached

    home = xbmcgui.Window(10000)
    prop = lock_prop(kind, source)
    existing = home.getProperty(prop)
    if existing and not force:
        try:
            age = time.time() - float(existing)
        except Exception:
            age = 999
        if age < 120:
            for _ in range(80):
                xbmc.Monitor().waitForAbort(0.5)
                cached = read_cache_entry("list", key, LIST_TTL)
                if cached is not None:
                    return cached

    home.setProperty(prop, str(time.time()))
    progress = None
    try:
        source_items = fetch_source(kind, source, force=force)
        token = get_webshare_token()
        output = []
        failures = []

        if manual:
            progress = xbmcgui.DialogProgress()
            progress.create(ADDON_NAME, "Filtruji {} / {}…".format(kind, source))

        for start in range(0, min(len(source_items), MAX_SOURCE_ITEMS), SOURCE_BATCH):
            batch = source_items[start:start + SOURCE_BATCH]
            if progress:
                progress.update(
                    min(95, int(start * 100 / max(1, len(source_items)))),
                    "Kontroluji {}–{} z {}…".format(start + 1, start + len(batch), len(source_items))
                )
                if progress.iscanceled():
                    break

            results = {}
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                future_map = {
                    pool.submit(check_availability, kind, item, token, force): idx
                    for idx, item in enumerate(batch)
                }
                for f in as_completed(future_map):
                    idx = future_map[f]
                    try:
                        results[idx] = f.result()
                    except Exception as exc:
                        log("availability {} {}: {}".format(kind, source, exc), xbmc.LOGWARNING)
                        failures.append(type(exc).__name__)
                        results[idx] = {"state": "ERROR", "score": 0, "candidate": {}, "reasons": [str(exc)]}

            for idx, item in enumerate(batch):
                status = results.get(idx) or {}
                if status.get("state") != "AVAILABLE":
                    continue
                meta = fetch_meta(kind, item)
                # Movie Watchlist: keep released items only when we know the date.
                if kind == "movie" and source == "watchlist":
                    premiered = meta.get("premiered") or item.get("premiered") or ""
                    if premiered and premiered[:10] > datetime.now().strftime("%Y-%m-%d"):
                        continue
                output.append({"item": item, "meta": meta, "availability": status})
                if len(output) >= MAX_WIDGET_ITEMS:
                    break

            if len(output) >= MAX_WIDGET_ITEMS:
                break

        if not output and failures:
            raise RuntimeError('network availability lookup failed')
        write_cache_entry("list", key, output)
        if progress:
            progress.update(100, "Hotovo: {} položek".format(len(output)))
            xbmc.Monitor().waitForAbort(0.3)
        return output
    finally:
        if progress:
            progress.close()
        home.clearProperty(prop)


# ---------------------------------------------------------------------------
# Kodi list rendering
# ---------------------------------------------------------------------------

def artwork(meta):
    art = {}
    poster = meta.get("poster_path") or ""
    backdrop = meta.get("backdrop_path") or ""
    still = meta.get("still_path") or ""
    if poster:
        art["poster"] = POSTER_BASE + poster
        art["thumb"] = POSTER_BASE + poster
        art["icon"] = POSTER_BASE + poster
    if backdrop:
        art["fanart"] = BACKDROP_BASE + backdrop
        art["landscape"] = BACKDROP_BASE + backdrop
    if still:
        art["thumb"] = STILL_BASE + still
        art["icon"] = STILL_BASE + still
    return art

def add_movie(rec):
    item = rec.get("item") or {}
    meta = rec.get("meta") or {}
    avail = rec.get("availability") or {}

    tmdb_id = item.get("tmdb_id")
    title = meta.get("title") or item.get("title") or ""
    path = "plugin://plugin.video.themoviedb.helper/?info=play&tmdb_id={}&tmdb_type=movie".format(tmdb_id)

    li = xbmcgui.ListItem(label=title, path=path)
    li.setInfo("video", {
        "title": title,
        "originaltitle": meta.get("original_title") or item.get("title") or "",
        "year": int(meta.get("year") or item.get("year") or 0),
        "plot": meta.get("plot") or "",
        "duration": int(meta.get("runtime") or 0) * 60,
        "rating": float(meta.get("rating") or 0),
        "votes": str(meta.get("votes") or 0),
        "genre": " / ".join(meta.get("genres") or []),
        "mediatype": "movie",
    })
    li.setArt(artwork(meta))
    li.setProperty("IsPlayable", "true")
    li.setProperty("webshare.available", "true")
    li.setProperty("webshare.score", str(avail.get("score") or 0))
    candidate = avail.get("candidate") or {}
    if candidate.get("name"):
        li.setProperty("webshare.file", candidate["name"])
    try:
        ids = {"tmdb": str(tmdb_id)}
        if item.get("imdb_id"):
            ids["imdb"] = str(item.get("imdb_id"))
        li.setUniqueIDs(ids, "tmdb")
    except Exception:
        pass
    xbmcplugin.addDirectoryItem(HANDLE, path, li, isFolder=False)

def add_tv(rec):
    item = rec.get("item") or {}
    meta = rec.get("meta") or {}
    avail = rec.get("availability") or {}

    tmdb_id = item.get("tmdb_id")
    title = meta.get("title") or item.get("title") or ""
    path = "plugin://plugin.video.themoviedb.helper/?info=details&tmdb_id={}&tmdb_type=tv".format(tmdb_id)

    li = xbmcgui.ListItem(label=title, path=path)
    li.setInfo("video", {
        "title": title,
        "originaltitle": meta.get("original_title") or item.get("title") or "",
        "year": int(meta.get("year") or item.get("year") or 0),
        "plot": meta.get("plot") or "",
        "rating": float(meta.get("rating") or 0),
        "votes": str(meta.get("votes") or 0),
        "genre": " / ".join(meta.get("genres") or []),
        "mediatype": "tvshow",
    })
    li.setArt(artwork(meta))
    li.setProperty("webshare.available", "true")
    li.setProperty("webshare.score", str(avail.get("score") or 0))
    candidate = avail.get("candidate") or {}
    if candidate.get("name"):
        li.setProperty("webshare.file", candidate["name"])
    try:
        ids = {"tmdb": str(tmdb_id)}
        if item.get("imdb_id"):
            ids["imdb"] = str(item.get("imdb_id"))
        li.setUniqueIDs(ids, "tmdb")
    except Exception:
        pass
    xbmcplugin.addDirectoryItem(HANDLE, path, li, isFolder=True)

def add_episode(rec):
    item = rec.get("item") or {}
    meta = rec.get("meta") or {}
    avail = rec.get("availability") or {}

    tmdb_id = item.get("tmdb_id")
    season = int(item.get("season") or 0)
    episode = int(item.get("episode") or 0)
    show_title = meta.get("show_title") or item.get("show_title") or ""
    ep_title = meta.get("title") or item.get("episode_title") or "S{:02d}E{:02d}".format(season, episode)
    label = "{} – S{:02d}E{:02d} – {}".format(show_title, season, episode, ep_title)

    path = (
        "plugin://plugin.video.themoviedb.helper/"
        "?info=play&tmdb_type=tv&tmdb_id={}&season={}&episode={}"
    ).format(tmdb_id, season, episode)

    li = xbmcgui.ListItem(label=label, path=path)
    li.setInfo("video", {
        "title": ep_title,
        "tvshowtitle": show_title,
        "season": season,
        "episode": episode,
        "plot": meta.get("plot") or "",
        "premiered": meta.get("premiered") or str(item.get("premiered") or "")[:10],
        "duration": int(meta.get("runtime") or 0) * 60,
        "rating": float(meta.get("rating") or 0),
        "votes": str(meta.get("votes") or 0),
        "mediatype": "episode",
    })
    li.setArt(artwork(meta))
    li.setProperty("IsPlayable", "true")
    li.setProperty("webshare.available", "true")
    li.setProperty("webshare.score", str(avail.get("score") or 0))
    candidate = avail.get("candidate") or {}
    if candidate.get("name"):
        li.setProperty("webshare.file", candidate["name"])
    xbmcplugin.addDirectoryItem(HANDLE, path, li, isFolder=False)

def render_list(kind, source):
    try:
        data = build_list(kind, source)
    except Exception as exc:
        log(str(exc), xbmc.LOGERROR)
        notify(str(exc), xbmcgui.NOTIFICATION_ERROR, 7000)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False, cacheToDisc=False)
        return

    labels = dict(MOVIE_SOURCES)
    labels.update({k: v for k, v, _ in TV_SOURCES})
    xbmcplugin.setPluginCategory(HANDLE, "{} – Webshare".format(labels.get(source, source)))
    xbmcplugin.setContent(HANDLE, "episodes" if kind == "episode" else ("tvshows" if kind == "tv" else "movies"))

    for rec in data:
        if kind == "movie":
            add_movie(rec)
        elif kind == "tv":
            add_tv(rec)
        else:
            add_episode(rec)

    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


# ---------------------------------------------------------------------------
# Provider browser
# ---------------------------------------------------------------------------

def add_folder(label, url, icon="DefaultVideo.png"):
    li = xbmcgui.ListItem(label=label)
    li.setArt({"icon": icon, "thumb": icon})
    xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=True)

def add_action(label, url):
    li = xbmcgui.ListItem(label=label)
    li.setArt({"icon": "DefaultAddonProgram.png", "thumb": "DefaultAddonProgram.png"})
    xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)

def root():
    xbmcplugin.setContent(HANDLE, "files")
    add_folder("Filmy – pouze dostupné na Webshare", qurl("section", section="movies"))
    add_folder("Seriály a epizody – pouze dostupné na Webshare", qurl("section", section="tv"))
    add_action("Nastavit Arctic Fuse 3: všechny Filmy + Seriály", qurl("install_arctic_all"))
    add_action("Opravit stabilní GUID stávajících Webshare widgetů", qurl("repair_arctic_guids"))
    add_action("Obnovit poslední Arctic Fuse zálohu", qurl("restore_arctic"))
    add_action("Vymazat a obnovit Webshare cache", qurl("refresh_all"))
    add_action("Informace", qurl("info"))
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)

def section(section_name):
    xbmcplugin.setContent(HANDLE, "files")
    if section_name == "movies":
        for source, label in MOVIE_SOURCES:
            add_folder(label, qurl("list", kind="movie", source=source))
    else:
        for source, label, kind in TV_SOURCES:
            add_folder(label, qurl("list", kind=kind, source=source))
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


# ---------------------------------------------------------------------------
# Arctic Fuse patch / backup
# ---------------------------------------------------------------------------

def skin_node_path(name):
    return xbmcvfs.translatePath(
        "special://profile/addon_data/script.skinvariables/nodes/{}/skinvariables-shortcut-{}.json".format(
            SKIN_ID, name
        )
    )

def spotlight_values(window):
    return {
        "label": xbmc.getInfoLabel("Skin.String(HomeSwitcher.{}.Spotlight.Label)".format(window)) or "",
        "path": xbmc.getInfoLabel("Skin.String(HomeSwitcher.{}.Spotlight.Path)".format(window)) or "",
        "target": xbmc.getInfoLabel("Skin.String(HomeSwitcher.{}.Spotlight.Target)".format(window)) or "",
        "limit": xbmc.getInfoLabel("Skin.String(HomeSwitcher.{}.Spotlight.Limit)".format(window)) or "",
    }

def backup_arctic():
    ensure_dirs()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = os.path.join(BACKUP_DIR, stamp)
    xbmcvfs.mkdirs(folder)

    for node in ("1101widgets", "1102widgets"):
        src = skin_node_path(node)
        content = read_text(src)
        if content is not None:
            write_text(os.path.join(folder, node + ".json"), content)

    write_json(os.path.join(folder, "spotlights.json"), {
        "1101": spotlight_values("1101"),
        "1102": spotlight_values("1102"),
    })
    return folder

def latest_backup():
    if not xbmcvfs.exists(BACKUP_DIR):
        return None
    dirs, _ = xbmcvfs.listdir(BACKUP_DIR)
    dirs = sorted([x.rstrip("/") for x in dirs if x], reverse=True)
    return os.path.join(BACKUP_DIR, dirs[0]) if dirs else None

def set_skin_string(key, value):
    if value:
        xbmc.executebuiltin("Skin.SetString({},{})".format(key, value))
    else:
        xbmc.executebuiltin("Skin.Reset({})".format(key))

def restore_arctic():
    folder = latest_backup()
    if not folder:
        xbmcgui.Dialog().ok(ADDON_NAME, "Není k dispozici žádná záloha.")
        return

    if not xbmcgui.Dialog().yesno(ADDON_NAME, "Obnovit poslední zálohu Arctic Fuse 3?"):
        return

    for node in ("1101widgets", "1102widgets"):
        content = read_text(os.path.join(folder, node + ".json"))
        if content is not None:
            write_text(skin_node_path(node), content)

    spots = read_json(os.path.join(folder, "spotlights.json"), {}) or {}
    for window in ("1101", "1102"):
        vals = spots.get(window) or {}
        for name in ("Label", "Path", "Target", "Limit"):
            set_skin_string(
                "HomeSwitcher.{}.Spotlight.{}".format(window, name),
                vals.get(name.lower()) or ""
            )

    force_skin_rebuild(("1101widgets", "1102widgets"))
    notify("Arctic Fuse 3 byl obnoven ze zálohy.")
    xbmc.executebuiltin("ReloadSkin()")

def provider_path(kind, source):
    return "plugin://{}/?action=list&kind={}&source={}".format(ADDON_ID, kind, source)

def patch_widgets(node_name, specs):
    path = skin_node_path(node_name)
    current = read_json(path, []) or []
    if not isinstance(current, list):
        current = []

    # Preserve visual/custom widget fields by patching known rows in place.
    used = set()
    result = []
    for spec in specs:
        match = None
        for idx, item in enumerate(current):
            if idx in used or not isinstance(item, dict):
                continue
            old_label = (item.get("label") or "").lower()
            old_path = item.get("path") or ""
            needles = [x.lower() for x in spec["match_labels"]]
            if any(n == old_label or n in old_label for n in needles):
                match = (idx, item)
                break
            if spec.get("match_path") and spec["match_path"] in old_path:
                match = (idx, item)
                break

        if match:
            idx, item = match
            used.add(idx)
            item = dict(item)
        else:
            item = {
                "icon": "",
                "target": "videos",
                "widget_limit": str(MAX_WIDGET_ITEMS),
                "widget_sortby": "default",
            }

        item["label"] = spec["label"]
        item["path"] = spec["path"]
        item["target"] = "videos"
        item["widget_limit"] = str(MAX_WIDGET_ITEMS)
        item["guid"] = spec["guid"]
        result.append(item)

    write_json(path, result)

def set_spotlight(window, label, path):
    set_skin_string("HomeSwitcher.{}.Spotlight.Label".format(window), label)
    set_skin_string("HomeSwitcher.{}.Spotlight.Path".format(window), path)
    set_skin_string("HomeSwitcher.{}.Spotlight.Target".format(window), "videos")
    set_skin_string("HomeSwitcher.{}.Spotlight.Limit".format(window), str(MAX_WIDGET_ITEMS))
    set_skin_string("HomeSwitcher.{}.Spotlight.SortMethod".format(window), "default")

def force_skin_rebuild(nodes):
    home = xbmcgui.Window(10000)
    home.setProperty("SkinVariables.ShortcutsNode.Reload", str(time.time()))
    for node in nodes:
        home.clearProperty(
            "SkinVariables.ShortcutsNode.{}-skinvariables-shortcut-{}.json".format(SKIN_ID, node)
        )
    xbmc.executebuiltin(
        'RunScript(script.skinvariables,"run_executebuiltin=special://skin/shortcuts/skinvariables-build-templates.json",use_rules)'
    )
    xbmc.Monitor().waitForAbort(1.5)


def repair_arctic_guids():
    """Repair existing Webshare widget rows in place by assigning deterministic GUIDs."""
    if xbmc.getSkinDir() != SKIN_ID:
        xbmcgui.Dialog().ok(ADDON_NAME, "Aktivní vzhled není Arctic Fuse 3.")
        return

    if not xbmcgui.Dialog().yesno(
        ADDON_NAME,
        "Opravit stabilní GUID u stávajících Webshare widgetů?\n\n"
        "Toto je oprava pro Combined režim, aby se widgety správně párovaly se selector položkou.\n"
        "Před změnou se vytvoří záloha."
    ):
        return

    backup_arctic()

    movie_specs = [
        {"guid": "webshare-movie-recommendations", "label": "Pro tebe – Webshare", "path": provider_path("movie", "recommendations"), "match_labels": ["pro tebe"], "match_path": "trakt_recommendations"},
        {"guid": "webshare-movie-watchlist", "label": "Watchlist – Webshare", "path": provider_path("movie", "watchlist"), "match_labels": ["watchlist"], "match_path": "trakt_watchlist"},
        {"guid": "webshare-movie-trending", "label": "Trendy – Webshare", "path": provider_path("movie", "trending"), "match_labels": ["trendy"], "match_path": "trending_week"},
        {"guid": "webshare-movie-popular", "label": "Populární – Webshare", "path": provider_path("movie", "popular"), "match_labels": ["populární", "popular"], "match_path": "info=popular"},
        {"guid": "webshare-movie-now-playing", "label": "V kinech – Webshare", "path": provider_path("movie", "now_playing"), "match_labels": ["v kinech"], "match_path": "now_playing"},
        {"guid": "webshare-movie-top-rated", "label": "Top hodnocené – Webshare", "path": provider_path("movie", "top_rated"), "match_labels": ["top hodnocené", "top rated"], "match_path": "top_rated"},
    ]

    tv_specs = [
        {"guid": "webshare-tv-next", "label": "Další epizody – Webshare", "path": provider_path("episode", "next"), "match_labels": ["další epizody", "your next episodes"], "match_path": "trakt_nextepisodes"},
        {"guid": "webshare-tv-playback", "label": "Rozkoukané epizody – Webshare", "path": provider_path("episode", "playback"), "match_labels": ["rozkoukané", "in-progress", "in progress"], "match_path": "trakt_inprogress"},
        {"guid": "webshare-tv-recommendations", "label": "Pro tebe – Webshare", "path": provider_path("tv", "recommendations"), "match_labels": ["pro tebe"], "match_path": "trakt_recommendations"},
        {"guid": "webshare-tv-watchlist", "label": "Watchlist – Webshare", "path": provider_path("tv", "watchlist"), "match_labels": ["watchlist"], "match_path": "trakt_watchlist"},
        {"guid": "webshare-tv-trending", "label": "Trendy – Webshare", "path": provider_path("tv", "trending"), "match_labels": ["trendy"], "match_path": "trending_week"},
        {"guid": "webshare-tv-popular", "label": "Populární – Webshare", "path": provider_path("tv", "popular"), "match_labels": ["populární", "popular"], "match_path": "info=popular"},
        {"guid": "webshare-tv-airing-today", "label": "Dnes vysílané – Webshare", "path": provider_path("tv", "airing_today"), "match_labels": ["dnes vysílané", "airing today"], "match_path": "airing_today"},
    ]

    patch_widgets("1101widgets", movie_specs)
    patch_widgets("1102widgets", tv_specs)
    force_skin_rebuild(("1101widgets", "1102widgets"))
    notify("Stabilní GUID opraveny. Reloaduji skin.", ms=5000)
    xbmc.executebuiltin("ReloadSkin()")


def install_arctic_all():
    if xbmc.getSkinDir() != SKIN_ID:
        xbmcgui.Dialog().ok(ADDON_NAME, "Aktivní vzhled není Arctic Fuse 3.")
        return

    if not xbmcgui.Dialog().yesno(
        ADDON_NAME,
        "Přepojit všechny widgety Filmy a Seriály na Webshare filtr?\n\n"
        "Filmy: Pro tebe, Watchlist, Trendy, Populární, V kinech, Top hodnocené.\n\n"
        "Seriály: Další epizody, Rozkoukané epizody, Pro tebe, Watchlist, Trendy, Populární, Dnes vysílané.\n\n"
        "Před změnou se vytvoří záloha."
    ):
        return

    backup_arctic()

    movie_specs = [
        {"guid": "webshare-movie-recommendations", "label": "Pro tebe – Webshare", "path": provider_path("movie", "recommendations"), "match_labels": ["pro tebe"], "match_path": "trakt_recommendations"},
        {"guid": "webshare-movie-watchlist", "label": "Watchlist – Webshare", "path": provider_path("movie", "watchlist"), "match_labels": ["watchlist"], "match_path": "trakt_watchlist"},
        {"guid": "webshare-movie-trending", "label": "Trendy – Webshare", "path": provider_path("movie", "trending"), "match_labels": ["trendy"], "match_path": "trending_week"},
        {"guid": "webshare-movie-popular", "label": "Populární – Webshare", "path": provider_path("movie", "popular"), "match_labels": ["populární", "popular"], "match_path": "info=popular"},
        {"guid": "webshare-movie-now-playing", "label": "V kinech – Webshare", "path": provider_path("movie", "now_playing"), "match_labels": ["v kinech"], "match_path": "now_playing"},
        {"guid": "webshare-movie-top-rated", "label": "Top hodnocené – Webshare", "path": provider_path("movie", "top_rated"), "match_labels": ["top hodnocené", "top rated"], "match_path": "top_rated"},
    ]

    tv_specs = [
        {"guid": "webshare-tv-next", "label": "Další epizody – Webshare", "path": provider_path("episode", "next"), "match_labels": ["další epizody", "your next episodes"], "match_path": "trakt_nextepisodes"},
        {"guid": "webshare-tv-playback", "label": "Rozkoukané epizody – Webshare", "path": provider_path("episode", "playback"), "match_labels": ["rozkoukané", "in-progress", "in progress"], "match_path": "trakt_inprogress"},
        {"guid": "webshare-tv-recommendations", "label": "Pro tebe – Webshare", "path": provider_path("tv", "recommendations"), "match_labels": ["pro tebe"], "match_path": "trakt_recommendations"},
        {"guid": "webshare-tv-watchlist", "label": "Watchlist – Webshare", "path": provider_path("tv", "watchlist"), "match_labels": ["watchlist"], "match_path": "trakt_watchlist"},
        {"guid": "webshare-tv-trending", "label": "Trendy – Webshare", "path": provider_path("tv", "trending"), "match_labels": ["trendy"], "match_path": "trending_week"},
        {"guid": "webshare-tv-popular", "label": "Populární – Webshare", "path": provider_path("tv", "popular"), "match_labels": ["populární", "popular"], "match_path": "info=popular"},
        {"guid": "webshare-tv-airing-today", "label": "Dnes vysílané – Webshare", "path": provider_path("tv", "airing_today"), "match_labels": ["dnes vysílané", "airing today"], "match_path": "airing_today"},
    ]

    patch_widgets("1101widgets", movie_specs)
    patch_widgets("1102widgets", tv_specs)

    set_spotlight("1101", "Pro tebe – Webshare", provider_path("movie", "recommendations"))
    set_spotlight("1102", "Pro tebe – Webshare", provider_path("tv", "recommendations"))

    # Prewarm the two Spotlight lists. Other rows build on first selection and then use cache.
    try:
        progress = xbmcgui.DialogProgress()
        progress.create(ADDON_NAME, "Připravuji filmový Spotlight…")
        build_list("movie", "recommendations", force=True, manual=False)
        progress.update(50, "Připravuji seriálový Spotlight…")
        build_list("tv", "recommendations", force=True, manual=False)
        progress.update(100, "Hotovo")
        xbmc.Monitor().waitForAbort(0.3)
        progress.close()
    except Exception as exc:
        try:
            progress.close()
        except Exception:
            pass
        log("Prewarm: {}".format(exc), xbmc.LOGWARNING)

    force_skin_rebuild(("1101widgets", "1102widgets"))
    notify("Filmy i Seriály jsou přepojené na Webshare filtr.", ms=6000)
    xbmc.executebuiltin("ReloadSkin()")


# ---------------------------------------------------------------------------
# Maintenance / info
# ---------------------------------------------------------------------------

def refresh_all():
    if not xbmcgui.Dialog().yesno(
        ADDON_NAME,
        "Vymazat cache dostupnosti a nechat seznamy vytvořit znovu?"
    ):
        return
    clear_cache()
    notify("Cache vymazána. Seznamy se obnoví při otevření.")

def info_dialog():
    msg = (
        "Webshare Available 0.2.0\n\n"
        "FILMY\n"
        "• všechny widgety v sekci Filmy lze filtrovat přes Webshare\n\n"
        "SERIÁLY\n"
        "• seriálové seznamy zobrazí jen seriály, u kterých byl nalezen odpovídající epizodní/season video soubor\n"
        "• Další epizody a Rozkoukané epizody ověřují konkrétní SxxEyy\n\n"
        "Přehrávání jde přes TMDb Helper → YAWSP.\n\n"
        "Pozn.: po otevření detailu seriálu používá vnitřní seznam sezón/epizod TMDb Helper; tento provider filtruje widgety a naše epizodní seznamy."
    )
    xbmcgui.Dialog().ok(ADDON_NAME, msg)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def route():
    action = (PARAMS.get("action") or [""])[0]

    # Backward compatibility with 0.1.0 widget path
    if action == "recommendations_movies":
        render_list("movie", "recommendations")
        return

    if action == "list":
        kind = (PARAMS.get("kind") or ["movie"])[0]
        source = (PARAMS.get("source") or ["recommendations"])[0]
        render_list(kind, source)
    elif action == "section":
        section((PARAMS.get("section") or ["movies"])[0])
    elif action == "install_arctic_all":
        install_arctic_all()
        if HANDLE >= 0:
            xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
    elif action == "repair_arctic_guids":
        repair_arctic_guids()
        if HANDLE >= 0:
            xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
    elif action == "restore_arctic":
        restore_arctic()
        if HANDLE >= 0:
            xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
    elif action == "refresh_all":
        refresh_all()
        if HANDLE >= 0:
            xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
    elif action == "info":
        info_dialog()
        if HANDLE >= 0:
            xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
    else:
        root()


if __name__ == "__main__":
    ensure_dirs()
    route()
