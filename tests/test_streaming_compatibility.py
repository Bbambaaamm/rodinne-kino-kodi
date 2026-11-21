"""Keep Arctic Fuse's own hub visibility and content when embedding catalogues."""
import ast
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET


SOURCE = Path(__file__).resolve().parents[1] / 'addons/script.michal.family.repair/maintenance.py'
tree = ast.parse(SOURCE.read_text(encoding='utf8'))
nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'streaming_combined_text']
env = {'ET': ET}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), env)
transform = env['streaming_combined_text']
SELECTED = 'String.IsEqual(Container(601).ListItem.Property(guid),{widget_guid})'


def widget(visible, content=False):
    return ('<include content="Hub_Combined_Widget"><param name="autoscroll">false</param>'
            '<param name="visible">' + visible + '</param>'
            + ('<param name="include_content">{widget_content_include}</param>' if content else '')
            + '</include>')


class StreamingCompatibilityTests(unittest.TestCase):
    def test_legacy_widget_keeps_selection_and_adds_ready_and_busy_states(self):
        result = transform(widget(SELECTED), SELECTED)
        root = ET.fromstring('<root>' + result + '</root>')
        self.assertEqual(root.findtext("include/param[@name='visible']"), SELECTED + ' + {family_catalogue_ready}')
        self.assertIsNotNone(root.find("include/param[@name='allowhiddenfocus']"))
        self.assertEqual(len(root.findall("include[@content='Widget_Busy']")), 1)

    def test_new_widget_keeps_hub_visibility_and_extra_content(self):
        native = SELECTED + ' + [{widget_hub_visible}]'
        result = transform(widget(native, content=True), SELECTED)
        root = ET.fromstring('<root>' + result + '</root>')
        self.assertEqual(root.findtext("include/param[@name='visible']"), native + ' + {family_catalogue_ready}')
        self.assertEqual(root.findtext("include/param[@name='include_content']"), '{widget_content_include}')
        self.assertEqual(root.findtext("include[@content='Widget_Busy']/param[@name='visible']"), native + ' + {family_catalogue_busy}')

    def test_unknown_visibility_still_fails_before_writing(self):
        with self.assertRaisesRegex(RuntimeError, 'layout changed'):
            transform(widget('unknown'), SELECTED)


if __name__ == '__main__':
    unittest.main()
