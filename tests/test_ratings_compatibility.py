"""Preserve stock rating rows across Arctic Fuse's 3.5.7 menu change."""
import ast
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET


SOURCE = Path(__file__).resolve().parents[1] / 'addons/script.michal.family.repair/maintenance.py'
tree = ast.parse(SOURCE.read_text(encoding='utf8'))
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'ratings_skin_text']
env = {'ET': ET}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), env)
transform = env['ratings_skin_text']


def layout(contents):
    rows = ''.join(f'<include content="{content}" />' for content in contents)
    return ('<includes><include name="Info_Meta"><definition><control type="grouplist">'
            + rows + '<!-- Total Episodes (Service Disabled) -->'
            + '</control></definition></include></includes>')


class RatingsCompatibilityTests(unittest.TestCase):
    def test_legacy_rows_remain_intact(self):
        original = layout(['Info_Meta_Ratings', 'Info_Meta_Ratings'])
        result = transform(original)
        root = ET.fromstring(result)
        self.assertEqual(len(root.findall(".//include[@content='Info_Meta_Ratings']")), 2)
        self.assertEqual(len(root.findall(".//include[@content='Info_Meta_Object']")), 1)

    def test_generated_movie_show_and_episode_rows_remain_intact(self):
        names = ['skinvariables-ratings' + kind for kind in ('movies', 'tvshows', 'episodes')]
        original = layout(names)
        result = transform(original)
        root = ET.fromstring(result)
        for name in names:
            self.assertEqual(len(root.findall(".//include[@content='" + name + "']")), 1)
        self.assertEqual(len(root.findall(".//include[@content='Info_Meta_Object']")), 1)
        self.assertEqual(transform(result), result)

    def test_unrecognized_ratings_layout_still_fails_before_writing(self):
        with self.assertRaisesRegex(RuntimeError, 'ratings row'):
            transform(layout(['skinvariables-ratingsmovies']))


if __name__ == '__main__':
    unittest.main()
