"""Find abbreviated releases without weakening exact episode matching."""
import ast
import importlib.util
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1] / 'addons/plugin.video.webshare.available'
spec = importlib.util.spec_from_file_location('source_matching', ROOT / 'matching.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
TITLES = ['Pán prstenů: Prsteny moci', 'The Lord of the Rings: The Rings of Power',
          'El señor de los anillos: Los anillos de poder', 'Властелинът на пръстените']
RELEASE = 'The Rings of Power S03E04 Gundabad (2026) CZ.avi'


class SourceTitleTests(unittest.TestCase):
    def test_canonical_short_forms_get_search_slots_before_other_translations(self):
        aliases, queries = m.episode_source_titles(TITLES)
        self.assertEqual(queries, TITLES[:2] + ['Prsteny moci', 'The Rings of Power'])
        self.assertTrue(all(title in aliases for title in TITLES))
        self.assertTrue(m.valid_source({'name': RELEASE, 'ident': 'correct'}, aliases, 'episode', 2022, 3, 4))

    def test_other_shows_seasons_episodes_and_packs_are_still_rejected(self):
        aliases, _ = m.episode_source_titles(TITLES)
        wrong = [RELEASE.replace('S03E04', code) for code in
                 ('S03E05', 'S02E04', 'S03E040', 'S03E04E05', 'S03E04-E05', 'S03E04-S03E05')]
        wrong += ['Power S03E04.1080p.mkv', 'The Lord of the Rings S03E04.mkv',
                  'The Rings of Power Aftershow S03E04.mkv',
                  'The Rings of Power S03E04 sample.mkv', RELEASE + '.zip']
        for name in wrong:
            with self.subTest(name=name):
                self.assertFalse(m.valid_source({'name': name, 'ident': 'wrong'}, aliases, 'episode', 2022, 3, 4))

    def test_generic_single_word_and_numbered_suffixes_are_not_added(self):
        for title in ('Franchise: Discovery', 'Franchise: The Series',
                      'Franchise: New Series', 'Franchise: Season Three 3', ': The Rings of Power'):
            with self.subTest(title=title):
                aliases, queries = m.episode_source_titles([title])
                self.assertEqual(aliases, [title])
                self.assertEqual(queries, [title])

    def test_punctuation_duplicates_do_not_consume_the_request_budget(self):
        aliases, queries = m.episode_source_titles([TITLES[0], TITLES[0].lower(), TITLES[1]])
        self.assertEqual(queries, TITLES[:2] + ['Prsteny moci', 'The Rings of Power'])
        self.assertEqual(len(aliases), 4)

    def test_real_resolver_deduplicates_short_title_results_and_rejects_noise(self):
        source = ast.parse((ROOT / 'family.py').read_text(encoding='utf8'))
        function = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == 'find_sources')
        requests, properties = [], {}
        accepted = [{'ident': 'correct-1', 'name': RELEASE, 'size': 1763516420},
                    {'ident': 'correct-2', 'name': RELEASE, 'size': 1763516420}]
        noise = [{'ident': f'unrelated-{i}', 'name': f'Unrelated Show {i} S03E04.mkv'} for i in range(100)]
        def search(query, token, limit):
            requests.append(query)
            self.assertEqual(limit, 100)
            if query == 'The Rings of Power S03E04':
                return accepted + [dict(accepted[0]), {'ident': 'wrong-episode', 'name': RELEASE.replace('S03E04', 'S03E05')}] + noise
            return noise
        core = types.SimpleNamespace(
            read_cache_entry=Mock(return_value=None), write_cache_entry=Mock(),
            get_webshare_token=lambda: 'test-only', webshare_search=search)
        scope = {'core': core, 'json': json, 'episode_source_titles': m.episode_source_titles,
                 'valid_source': m.valid_source, 'attributes': m.attributes, 'rank_source': m.rank_source,
                 'media_key': lambda *args: ':'.join(map(str, args)),
                 'HOME': types.SimpleNamespace(setProperty=properties.__setitem__)}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROOT / 'family.py'), 'exec'), scope)
        record = {'item': {'kind': 'episode', 'tmdb_id': 84773, 'season': 3, 'episode': 4},
                  'meta': {'title': 'Gundabad', 'show_title': TITLES[0],
                           'original_show_title': TITLES[1], 'show_titles': TITLES, 'year': 2022}}
        self.assertEqual(scope['find_sources'](record), accepted)
        self.assertEqual(requests, [name + ' S03E04' for name in TITLES[:2] + ['Prsteny moci', 'The Rings of Power']])
        self.assertNotIn('Gundabad', ' '.join(requests))
        self.assertTrue(core.read_cache_entry.call_args.args[1].startswith('family_sources_v3_'))
        diagnostic = json.loads(properties['Family.LastSources'])
        self.assertTrue(diagnostic['strict_episode'])
        self.assertEqual(diagnostic['accepted'], 2)


if __name__ == '__main__':
    unittest.main()
