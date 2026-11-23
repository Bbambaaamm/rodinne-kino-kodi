"""Every visible media card must have an exact Webshare match."""
import ast
import importlib.util
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1] / 'addons/plugin.video.webshare.available'


def load(name):
    spec = importlib.util.spec_from_file_location('availability_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


matching = load('matching')
paging = load('paging')
searching = load('searching')


class AvailabilityEverywhereTests(unittest.TestCase):
    def strict_function(self, meta, responses):
        tree = ast.parse((ROOT / 'core.py').read_text(encoding='utf8'))
        node = next(row for row in tree.body if isinstance(row, ast.FunctionDef) and row.name == 'strict_availability')
        requests = []

        def webshare(query, token, limit=20):
            requests.append((query, limit))
            return responses.get(query, [])

        env = {'fetch_meta': lambda kind, item: meta, 'webshare_search': webshare}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'core.py', 'exec'), env)
        def strict(*args):
            with patch.dict(sys.modules, {'matching': matching}):
                return env['strict_availability'](*args)
        return strict, requests

    def test_all_list_types_require_webshare_confirmation(self):
        values = [
            {'personal': False, 'source': 'popular'},
            {'personal': False, 'source': 'genre_35'},
            {'personal': False, 'source': 'provider_8'},
            {'personal': False, 'source': 'upcoming'},
            {'personal': True, 'source': 'watchlist'},
            {'personal': True, 'source': 'collection'},
        ]
        self.assertTrue(all(paging.needs_availability(value) for value in values))

    def test_search_keeps_people_and_only_confirmed_media(self):
        rows = [
            {'media_type': 'person', 'id': 1, 'name': 'Herec'},
            {'media_type': 'movie', 'id': 2, 'title': 'Dostupný', 'release_date': '2020-01-01'},
            {'media_type': 'tv', 'id': 3, 'name': 'Nedostupný', 'first_air_date': '2021-01-01'},
        ]
        core = types.SimpleNamespace(
            get_webshare_token=lambda: 'test-token',
            check_availability=lambda kind, item, token: {'state': 'AVAILABLE' if item['tmdb_id'] == 2 else 'NOT_AVAILABLE'},
        )
        result = searching.available(core, rows)
        self.assertEqual([(row['media_type'], row['id']) for row in result], [('person', 1), ('movie', 2)])

    def test_rings_short_title_finds_exact_episode_and_rejects_noise(self):
        release = {'ident': 'correct', 'name': 'The Rings of Power S03E04 Gundabad (2026) CZ.avi'}
        noise = {'ident': 'noise', 'name': 'Prolhane.krasky.S03E04.Vrana.k.vrane.seda.avi'}
        meta = {
            'show_title': 'Pán prstenů: Prsteny moci',
            'original_show_title': 'The Lord of the Rings: The Rings of Power',
            'show_titles': ['Pán prstenů: Prsteny moci', 'The Lord of the Rings: The Rings of Power'],
        }
        strict, requests = self.strict_function(meta, {
            'Prsteny moci S03E04': [noise],
            'The Rings of Power S03E04': [noise, release],
        })
        item = {'kind': 'episode', 'tmdb_id': 84773, 'show_title': meta['original_show_title'],
                'season': 3, 'episode': 4}
        result = strict('episode', item, 'test-token')
        self.assertEqual(result['state'], 'AVAILABLE')
        self.assertEqual(result['candidate']['ident'], 'correct')
        self.assertEqual(requests[:2], [('Prsteny moci S03E04', 100), ('The Rings of Power S03E04', 100)])

    def test_stale_local_completion_does_not_hide_trakt_next_episode(self):
        tree = ast.parse((ROOT / 'paging.py').read_text(encoding='utf8'))
        nodes = [row for row in tree.body if isinstance(row, ast.FunctionDef)
                 and row.name in ('recently_completed', 'process')]
        env = {'needs_availability': lambda value: True, 'time': time,
               'identity': lambda f,item: f.media_key(item['kind'],item['tmdb_id'],item.get('season'),item.get('episode'))}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'paging.py', 'exec'), env)
        item = {'kind': 'episode', 'tmdb_id': 918, 'season': 1, 'episode': 10}
        core = types.SimpleNamespace(
            check_availability=lambda *args: {'state': 'AVAILABLE'},
            fetch_meta=lambda *args: {'title': 'I Hate a Mystery'},
        )
        family = types.SimpleNamespace(core=core, media_key=lambda *args: ':'.join(map(str, args)))
        value = {'source': 'next'}
        ident = 'episode:918:1:10'
        stale = {ident: {'completed': True, 'updated': time.time() - 3600}}
        fresh = {ident: {'completed': True, 'updated': time.time()}}
        self.assertIsNotNone(env['process'](family, value, item, set(), 'token', stale)[1])
        self.assertIsNone(env['process'](family, value, item, set(), 'token', fresh)[1])

    def test_fast_display_uses_the_same_completion_grace_period(self):
        now = time.time()
        self.assertFalse(paging.recently_completed({'completed': True, 'updated': now-3600}, now))
        self.assertTrue(paging.recently_completed({'completed': True, 'updated': now-60}, now))
        self.assertFalse(paging.recently_completed({'completed': False, 'updated': now}, now))


if __name__ == '__main__':
    unittest.main()
