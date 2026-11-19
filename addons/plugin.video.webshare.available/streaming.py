"""Czech subscription catalogues powered by JustWatch through TMDb."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import uuid
from urllib.request import Request, urlopen


REGION = 'CZ'
ATTRIBUTION = 'Dostupnost v ČR · data JustWatch'
PROVIDER_CACHE = 'streaming_providers_cz_v2'
PROVIDER_TTL = 6 * 3600
SERVICES = (
    ('Netflix', ('Netflix',)),
    ('Prime Video', ('Amazon Prime Video', 'Prime Video')),
    ('Disney+', ('Disney Plus', 'Disney+')),
    ('HBO Max', ('HBO Max', 'Max')),
    ('Apple TV', ('Apple TV', 'Apple TV+', 'Apple TV Plus')),
    ('SkyShowtime', ('SkyShowtime',)),
    ('Oneplay', ('Oneplay',)),
)

POSTER_LIMIT = 4
POSTER_BYTES = 1024 * 1024
POSTER_CACHE_ITEMS = 96


def poster_file(core, path):
    if not path or not path.startswith('/') or '..' in path:
        return ''
    name = hashlib.sha256(path.encode('utf-8')).hexdigest() + '.jpg'
    return os.path.join(core.CACHE_ROOT, 'streaming-posters', name)


def cached_poster(core, path):
    filename = poster_file(core, path)
    return filename if filename and os.path.isfile(filename) and os.path.getsize(filename) > 0 else ''


def prefetch_posters(core, records, cancel=None):
    """Warm a few visible cards while a service tile is focused."""
    folder = os.path.join(core.CACHE_ROOT, 'streaming-posters')
    os.makedirs(folder, exist_ok=True)
    for record in records[:POSTER_LIMIT]:
        if cancel and cancel.is_set():
            break
        path = record.get('meta', {}).get('poster_path') or ''
        filename = poster_file(core, path)
        if not filename or cached_poster(core, path):
            continue
        temporary = filename + '.' + uuid.uuid4().hex + '.new'
        try:
            address = core.POSTER_BASE + path
            with urlopen(Request(address, headers={'User-Agent': 'Kodi Rodinne kino'}), timeout=3) as response:
                data = response.read(POSTER_BYTES + 1)
            if len(data) > POSTER_BYTES or not data.startswith(b'\xff\xd8\xff'):
                continue
            if cancel and cancel.is_set():
                break
            with open(temporary, 'wb') as stream:
                stream.write(data)
            os.replace(temporary, filename)
        except (OSError, ValueError):
            pass
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
    try:
        names = sorted((os.path.join(folder, name) for name in os.listdir(folder)
                        if name.endswith('.jpg')), key=os.path.getmtime, reverse=True)
        for filename in names[POSTER_CACHE_ITEMS:]:
            os.remove(filename)
    except OSError:
        pass


def providers(core):
    cached = core.read_cache_entry('list', PROVIDER_CACHE, PROVIDER_TTL)
    if cached is not None:
        return cached
    kinds = ('movie', 'tv')
    def request(kind):
        data = core.tmdb_request('/watch/providers/' + kind, {'watch_region': REGION})
        return {row['provider_name'].casefold(): row for row in data.get('results', [])}

    with ThreadPoolExecutor(max_workers=2) as pool:
        sources = dict(zip(kinds, pool.map(request, kinds)))
    picked = []
    for label, aliases in SERVICES:
        ids = {}
        logo = ''
        for kind, available in sources.items():
            for alias in aliases:
                row = available.get(alias.casefold(), {})
                ident = row.get('provider_id')
                if isinstance(ident, int) and ident > 0:
                    ids[kind] = ident
                    logo = logo or row.get('logo_path') or ''
                    break
        if ids:
            picked.append({'label': label, 'ids': ids, 'logo': logo})
    if picked:
        core.write_cache_entry('list', PROVIDER_CACHE, picked)
    return picked


def cached_name(core, kind, ident):
    entries = core.read_cache_entry('list', PROVIDER_CACHE, 24 * 3600) or []
    return next((entry['label'] for entry in entries if entry['ids'].get(kind) == ident), '')
