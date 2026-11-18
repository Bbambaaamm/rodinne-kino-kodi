"""Czech subscription catalogues powered by JustWatch through TMDb."""

from concurrent.futures import ThreadPoolExecutor


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
