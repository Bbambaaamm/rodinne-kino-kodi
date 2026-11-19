"""The portable installer must patch touch navigation and password input safely."""
import importlib.util
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET


SOURCE = (Path(__file__).resolve().parents[1] / 'addons' /
          'script.michal.family.repair' / 'skin_input.py')
spec = importlib.util.spec_from_file_location('tested_skin_input', SOURCE)
skin_input = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skin_input)

HOME = '''<includes><include name="Home_Switcher_Horz"><control type="group">
<visible>!String.IsEmpty(Window(Home).Property(HomeSwitcher.IsVisible))</visible>
</control></include></includes>'''
HUBS = '''<includes>
    <include name="Hub_Window">
        <definition><control type="group" />
        </definition>
    </include>
    <include name="Hub_Prefab_Window">
        <definition><control type="group" />
        </definition>
    </include>
</includes>'''
KEYBOARD = '''<includes>
    <include name="DialogKeyboard_Items">
        <definition>
            <include content="Button_Dialog"><param name="id">309</param></include>
        </definition>
    </include>
</includes>'''


class SkinInputTests(unittest.TestCase):
    def test_touch_buttons_are_in_both_active_hub_windows(self):
        result = skin_input.hubs(HUBS)
        root = ET.fromstring(result)
        for name in ('Hub_Window', 'Hub_Prefab_Window'):
            included = root.find("./include[@name='%s']/definition/include" % name)
            self.assertEqual(included.get('content'), 'Family_Android_Touch_Navigation')
            self.assertEqual(included.get('condition'),
                             'System.Platform.Android + !Skin.HasSetting(HomeSwitcher.Vertical)')
        buttons = root.findall("./include[@name='Family_Android_Touch_Navigation']/definition/control")
        self.assertEqual([button.findtext('onclick') for button in buttons], [
            'ReplaceWindow(Home)', 'ReplaceWindow(1101)', 'ReplaceWindow(1102)',
            'ReplaceWindow(1103)', 'ReplaceWindow(1104)'])
        self.assertEqual(skin_input.hubs(result), result)

    def test_android_keeps_home_switcher_visible(self):
        result = skin_input.home(HOME)
        self.assertIn('System.Platform.Android | !String.IsEmpty', result)
        self.assertEqual(skin_input.home(result), result)

    def test_keyboard_exposes_kodi_password_visibility_control(self):
        result = skin_input.keyboard(KEYBOARD)
        root = ET.fromstring(result)
        actions = root.findall("./include[@name='DialogKeyboard_Items']/definition/include")
        self.assertEqual([action.findtext("param[@name='id']") for action in actions], ['310', '309'])
        self.assertEqual(actions[0].findtext("param[@name='icon']"),
                         'special://skin/extras/icons/eye.png')
        self.assertEqual(skin_input.keyboard(result), result)

    def test_changed_upstream_structure_fails_before_writing(self):
        for transform in (skin_input.home, skin_input.hubs, skin_input.keyboard):
            with self.subTest(transform=transform.__name__):
                with self.assertRaises(RuntimeError):
                    transform('<includes />')


if __name__ == '__main__':
    unittest.main()
