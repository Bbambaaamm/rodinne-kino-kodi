"""Regression coverage for the Trakt handoff at Kodi's resolver boundary."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


SOURCE = Path(__file__).resolve().parents[1] / 'addons/plugin.video.webshare.available'


class Window:
    def __init__(self):
        self.properties = {}

    def getProperty(self, name):
        return self.properties.get(name, '')

    def setProperty(self, name, value):
        self.properties[name] = value

    def clearProperty(self, name):
        self.properties.pop(name, None)


class PlaybackTraktIdentityTests(unittest.TestCase):
    def setUp(self):
        self.home = Window()
        self.resolve = Mock()
        item = Mock()
        item.getVideoInfoTag.return_value = SimpleNamespace(
            getMediaType=lambda: 'movie', getTitle=lambda: '')
        env = {
            'HOME': self.home, 'json': json, 'HANDLE': 42,
            'xbmcplugin': SimpleNamespace(setResolvedUrl=self.resolve),
            'metadata_item': Mock(return_value=item),
            'time': SimpleNamespace(time=lambda: 100),
        }
        for file, names in (
            ('tracking.py', {'TRAKT_IDS', 'MOVIE_TRAKT_IDS',
                             'clear_movie_trakt_ids', 'publish_movie_trakt_ids'}),
            ('family.py', {'deliver_resolved'}),
        ):
            path = SOURCE / file
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            selected = [node for node in tree.body if (
                isinstance(node, ast.FunctionDef) and node.name in names
                or isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id in names for target in node.targets))]
            exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), env)
        self.deliver = env['deliver_resolved']

    def delivery(self, kind, ident):
        self.deliver({'record': {'item': {'kind': kind, 'tmdb_id': ident}},
                      'link': 'https://example.invalid/video'})

    def test_each_movie_id_is_available_when_kodi_starts_the_stream(self):
        handed_to_trakt = []
        self.resolve.side_effect = lambda *_: handed_to_trakt.append(
            json.loads(self.home.getProperty('script.trakt.ids')))
        self.delivery('movie', 1830)
        self.delivery('movie', 550)
        self.assertEqual(handed_to_trakt, [{'tmdb': 1830}, {'tmdb': 550}])

    def test_episode_never_inherits_the_previous_movie_id(self):
        self.delivery('movie', 1830)
        self.resolve.side_effect = lambda *_: self.assertEqual(
            self.home.getProperty('script.trakt.ids'), '')
        self.delivery('episode', 918)

    def test_episode_leaves_another_addons_ids_alone(self):
        self.delivery('movie', 1830)
        other_ids = json.dumps({'imdb': 'tt0068098'})
        self.home.setProperty('script.trakt.ids', other_ids)
        self.delivery('episode', 918)
        self.assertEqual(self.home.getProperty('script.trakt.ids'), other_ids)

    def test_failed_resolve_removes_the_movie_hint(self):
        self.resolve.side_effect = RuntimeError('Kodi rejected the result')
        with self.assertRaises(RuntimeError):
            self.delivery('movie', 1830)
        self.assertEqual(self.home.getProperty('script.trakt.ids'), '')
        self.assertEqual(self.home.getProperty('Family.ManagedStartAt'), '')
