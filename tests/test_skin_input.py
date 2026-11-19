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
CATEGORIES = '''<includes>
    <include name="Categories_Selector_OverlayList">
        <definition>
            <control type="grouplist">
                <control type="label"><label>Selected</label></control>
                <control type="label"><label>$INFO[Container($PARAM[id]).ListItem(1).Label]</label></control>
                <control type="label"><label>$INFO[Container($PARAM[id]).ListItem(2).Label]</label></control>
                <control type="label"><label>$INFO[Container($PARAM[id]).ListItem(3).Label]</label></control>
            </control>
        </definition>
    </include>
</includes>'''
STREAMING = '''<window id="1104"><controls>
        <include content="Hub_Configurable_Window"><param name="window">1104</param></include>
    </controls></window>'''
SETTINGS = '''<window><controls>
        <include content="Settings_Dialog" />
    </controls>
</window>'''


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
            'ReplaceWindow(1103)', 'ReplaceWindow(1104)', 'ActivateWindow(Settings)'])
        self.assertEqual(buttons[3].findtext('left'), '565')
        self.assertEqual(buttons[-1].findtext('left'), '1570')
        self.assertEqual(skin_input.hubs(result), result)

    def test_existing_navigation_gear_opens_settings(self):
        old = skin_input.hubs(HUBS).replace('ActivateWindow(Settings)',
                                                'ActivateWindow(1170)')
        result = skin_input.hubs(old)
        self.assertIn('ActivateWindow(Settings)', result)
        self.assertNotIn('ActivateWindow(1170)', result)

    def test_streaming_hub_has_its_own_touch_navigation(self):
        result = skin_input.streaming_hub(STREAMING)
        root = ET.fromstring(result)
        self.assertEqual(root.find('./controls/include[2]').get('content'),
                         'Family_Android_Touch_Navigation')
        self.assertEqual(skin_input.streaming_hub(result), result)

    def test_settings_has_visible_touch_exit(self):
        result = skin_input.settings(SETTINGS)
        button = ET.fromstring(result).find('./controls/control[@id="9301"]')
        self.assertEqual(button.findtext('label'), 'Zpět')
        self.assertEqual(button.findtext('onclick'), 'ActivateWindow(Home)')
        self.assertEqual(skin_input.settings(result), result)

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

    def test_visible_category_labels_can_select_next_widgets_by_touch(self):
        result = skin_input.categories(CATEGORIES)
        root = ET.fromstring(result)
        controls = root.findall("./include[@name='Categories_Selector_OverlayList']/definition/control/control")
        self.assertEqual([control.get('type') for control in controls],
                         ['label', 'button', 'button', 'button'])
        self.assertEqual([control.findtext('onclick') for control in controls[1:]], [
            'Control.Move($PARAM[id],1)', 'Control.Move($PARAM[id],2)',
            'Control.Move($PARAM[id],3)'])
        self.assertEqual(skin_input.categories(result), result)

    def test_changed_upstream_structure_fails_before_writing(self):
        for transform in (skin_input.home, skin_input.hubs, skin_input.keyboard,
                          skin_input.categories, skin_input.streaming_hub,
                          skin_input.settings):
            with self.subTest(transform=transform.__name__):
                with self.assertRaises(RuntimeError):
                    transform('<includes />')


if __name__ == '__main__':
    unittest.main()
