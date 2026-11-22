"""Small, repeatable Arctic Fuse 3 input fixes for touch and passwords."""
import re
from xml.etree import ElementTree as ET


ANDROID_NAVIGATION = '''
    <!-- Rodinne kino: Android touch navigation -->
    <include name="Family_Android_Touch_Navigation">
        <definition>
            <control type="button"><left>145</left><top>130</top><width>145</width><height>85</height><label /><texturenofocus /><texturefocus /><onclick>ReplaceWindow(Home)</onclick></control>
            <control type="button"><left>290</left><top>130</top><width>135</width><height>85</height><label /><texturenofocus /><texturefocus /><onclick>ReplaceWindow(1101)</onclick></control>
            <control type="button"><left>425</left><top>130</top><width>140</width><height>85</height><label /><texturenofocus /><texturefocus /><onclick>ReplaceWindow(1102)</onclick></control>
            <control type="button"><left>565</left><top>130</top><width>135</width><height>85</height><label /><texturenofocus /><texturefocus /><onclick>ReplaceWindow(1103)</onclick></control>
            <control type="button"><left>700</left><top>130</top><width>330</width><height>85</height><label /><texturenofocus /><texturefocus /><onclick>ReplaceWindow(1104)</onclick></control>
            <control type="button"><left>1570</left><top>130</top><width>110</width><height>85</height><label /><texturenofocus /><texturefocus /><onclick>ActivateWindow(Settings)</onclick></control>
        </definition>
    </include>
'''
TOUCH_INCLUDE = ('\n            <include content="Family_Android_Touch_Navigation" '
                 'condition="System.Platform.Android + !Skin.HasSetting(HomeSwitcher.Vertical)" />\n')


def home(original):
    old = '<visible>!String.IsEmpty(Window(Home).Property(HomeSwitcher.IsVisible))</visible>'
    new = ('<visible>System.Platform.Android | '
           '!String.IsEmpty(Window(Home).Property(HomeSwitcher.IsVisible))</visible>')
    if old in original:
        updated = original.replace(old, new, 1)
    elif new in original:
        updated = original
    else:
        raise RuntimeError('Arctic Fuse home switcher changed')
    settings_start = updated.find('    <include name="Home_Settings_Button">')
    if settings_start >= 0:
        settings_end = updated.find('    </include>', settings_start)
        if settings_end < 0:
            raise RuntimeError('Arctic Fuse settings control incomplete')
        section = updated[settings_start:settings_end]
        section = section.replace('<param name="window">1170</param>',
                                  '<param name="window">Settings</param>', 1)
        updated = updated[:settings_start] + section + updated[settings_end:]
    icon_start = updated.find('    <include name="Home_Grouplist_Icon">')
    if icon_start >= 0:
        icon_end = updated.find('    </include>', icon_start)
        if icon_end < 0:
            raise RuntimeError('Arctic Fuse menu icon incomplete')
        section = updated[icon_start:icon_end]
        section = section.replace('<control type="button" id="$PARAM[id]">',
            '<control type="button" id="$PARAM[id]">'
            '<width>80</width><height>80</height>', 1) if '<width>80</width><height>80</height>' not in section else section
        updated = updated[:icon_start] + section + updated[icon_end:]
    ET.fromstring(updated)
    return updated


def hubs(original):
    if '<include name="Family_Android_Touch_Navigation">' in original:
        start = original.find('<include name="Family_Android_Touch_Navigation">')
        end = original.find('</include>', start)
        if end < 0:
            raise RuntimeError('Android touch navigation incomplete')
        end += len('</include>')
        navigation = ANDROID_NAVIGATION[ANDROID_NAVIGATION.find(
            '<include name="Family_Android_Touch_Navigation">'):].strip()
        updated = original[:start] + navigation + original[end:]
    else:
        updated = original
        for name in ('Hub_Window', 'Hub_Prefab_Window'):
            start = updated.find('    <include name="' + name + '">')
            if start < 0:
                raise RuntimeError('Arctic Fuse hub include missing: ' + name)
            end = updated.find('\n    </include>', start)
            if end < 0:
                raise RuntimeError('Arctic Fuse hub include incomplete: ' + name)
            anchor = updated.rfind('\n        </definition>', start, end)
            if anchor < 0:
                raise RuntimeError('Arctic Fuse hub definition missing: ' + name)
            updated = updated[:anchor] + TOUCH_INCLUDE + updated[anchor:]
        end = updated.rfind('</includes>')
        if end < 0:
            raise RuntimeError('Arctic Fuse hub root missing')
        updated = updated[:end] + ANDROID_NAVIGATION + updated[end:]
    ET.fromstring(updated)
    return updated


def keyboard(original):
    if '<param name="id">310</param>' in original:
        ET.fromstring(original)
        return original
    start = original.find('    <include name="DialogKeyboard_Items">')
    if start < 0:
        raise RuntimeError('Arctic Fuse keyboard actions missing')
    anchor = original.find('            <include content="Button_Dialog">', start)
    end = original.find('\n    </include>', start)
    if anchor < 0 or end < 0 or anchor >= end:
        raise RuntimeError('Arctic Fuse keyboard actions changed')
    button = '''            <include content="Button_Dialog">
                <param name="id">310</param>
                <param name="groupid">9310</param>
                <param name="icon">special://skin/extras/icons/eye.png</param>
            </include>
'''
    updated = original[:anchor] + button + original[anchor:]
    ET.fromstring(updated)
    return updated


def confirmation(original):
    """Use Kodi's real choice buttons for remote keys and full-size touch targets."""
    marker = 'Rodinne kino: native confirmation navigation v2'
    if marker in original:
        ET.fromstring(original)
        return original
    root = ET.fromstring(original)
    dialog = root.find("./include[@name='DialogConfirm']")
    items = root.find("./include[@name='DialogConfirm_Items']/definition")
    if dialog is None or items is None:
        raise RuntimeError('Arctic Fuse confirmation dialog missing')
    hidden = [node for node in dialog.findall("include[@content='Object_Hidden_Button']")
              if node.findtext("param[@name='id']") in ('10', '11', '12')]
    choices = items.findall("include[@content='Button_Dialog']")
    upstream = (len(hidden) == 3 and len(list(items)) == 3
                and [node.findtext("param[@name='id']") for node in choices] == ['9011', '9010', '9012'])
    previous = ('Rodinne kino: native confirmation controls' in original and not hidden
                and [node.get('id') for node in items.findall('control')] == ['11', '10', '12'])
    panels = [node for node in dialog.iter('include')
              if node.get('content') == 'Part_Button_Grouplist'
              and node.findtext("param[@name='items']") == 'DialogConfirm_Items']
    if not (upstream or previous) or len(panels) != 1:
        raise RuntimeError('Arctic Fuse confirmation buttons changed')
    for node in hidden:
        dialog.remove(node)
    # A grouplist rewrites children's navigation when it attaches them. Keep
    # the three native buttons in a plain group so their explicit routes are
    # retained, including after the first skin load on Kodi 21 / Android.
    panel = panels[0]
    parent = next(node for node in dialog.iter() if panel in list(node))
    position = list(parent).index(panel)
    parent.remove(panel)
    group = ET.Element('control', type='group', id='9000')
    ET.SubElement(group, 'include').text = 'Size_Group_Panel_Right'
    ET.SubElement(group, 'include').text = 'Part_Panel'
    padded = ET.SubElement(group, 'control', type='group')
    ET.SubElement(padded, 'include').text = 'Size_Grouplist_Pad'
    ET.SubElement(padded, 'defaultcontrol', always='true').text = '10'
    ET.SubElement(padded, 'include').text = 'DialogConfirm_Items'
    parent.insert(position, group)
    items.clear()
    items.append(ET.Comment(marker))
    # Kodi sets labels, visibility, focus and click results on 10/11/12 itself.
    # Proxy buttons 9010/9011 cannot reliably retain that state across a reload.
    for index, (control_id, previous, following) in enumerate(((11, 12, 10), (10, 11, 12), (12, 10, 11))):
        button = ET.SubElement(items, 'control', type='button', id=str(control_id))
        for name, value in (('left', '0'), ('top', str(index * 110)),
                            ('width', '100%'), ('height', '90'), ('font', 'font_main'),
                            ('align', 'center'), ('aligny', 'center'), ('textoffsetx', '12'),
                            ('textcolor', 'dialog_fg_100'), ('focusedcolor', 'FF111114')):
            ET.SubElement(button, name).text = value
        ET.SubElement(button, 'label')
        for name, color in (('texturenofocus', '20FFFFFF'), ('texturefocus', 'FFFFFFFF')):
            ET.SubElement(button, name, border='40', colordiffuse=color).text = 'common/menu.png'
        for direction, first, second in (('onup', previous, following), ('onleft', previous, following),
                                          ('ondown', following, previous), ('onright', following, previous)):
            available = lambda cid: f'[Control.IsVisible({cid}) + Control.IsEnabled({cid})]'
            ET.SubElement(button, direction, condition=available(first)).text = str(first)
            ET.SubElement(button, direction, condition='!' + available(first) + ' + ' + available(second)).text = str(second)
            ET.SubElement(button, direction, condition='!' + available(first) + ' + !' + available(second)).text = str(control_id)
    ET.indent(root, space='    ')
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode') + '\n'


def categories(original):
    """Make the visible next-category labels respond to Android taps."""
    start = original.find('    <include name="Categories_Selector_OverlayList">')
    end = original.find('    </include>', start)
    if start < 0 or end < 0:
        raise RuntimeError('Arctic Fuse category overlay missing')
    end += len('    </include>')
    overlay = original[start:end]
    if '<!-- Rodinne kino: touch categories -->' in overlay:
        ET.fromstring(original)
        return original
    for offset in (1, 2, 3):
        pattern = (r'<control type="label">(?:(?!</control>).)*?'
                   r'<label>\$INFO\[Container\(\$PARAM\[id\]\)\.'
                   r'ListItem\(' + str(offset) + r'\)\.Label\]</label>'
                   r'(?:(?!</control>).)*?</control>')
        match = re.search(pattern, overlay, re.DOTALL)
        if not match:
            raise RuntimeError('Arctic Fuse category label missing: ' + str(offset))
        button = match.group(0).replace('<control type="label">',
            '<control type="button"><texturenofocus /><texturefocus />'
            '<onclick>Control.Move($PARAM[id],' + str(offset) + ')</onclick>', 1)
        overlay = overlay[:match.start()] + button + overlay[match.end():]
    updated = (original[:start] + overlay.replace('<definition>',
        '<definition>\n            <!-- Rodinne kino: touch categories -->', 1) + original[end:])
    ET.fromstring(updated)
    return updated


def streaming_hub(original):
    """The streaming hub uses a different template than film and series hubs."""
    if '<include content="Family_Android_Touch_Navigation"' in original:
        ET.fromstring(original)
        return original
    anchor = '    </controls>'
    if '<include content="Hub_Configurable_Window">' not in original or anchor not in original:
        raise RuntimeError('Arctic Fuse streaming hub structure changed')
    updated = original.replace(anchor,
        '        <include content="Family_Android_Touch_Navigation" '
        'condition="System.Platform.Android + !Skin.HasSetting(HomeSwitcher.Vertical)" />\n'
        + anchor, 1)
    ET.fromstring(updated)
    return updated


def settings(original):
    """Keep a visible touch exit on the settings landing page."""
    if '<!-- Rodinne kino: settings touch back -->' in original:
        ET.fromstring(original)
        return original
    if '<include content="Settings_Dialog"' not in original:
        raise RuntimeError('Arctic Fuse settings landing changed')
    anchor = '    </controls>\n</window>'
    if anchor not in original:
        raise RuntimeError('Arctic Fuse settings window incomplete')
    button = '''        <!-- Rodinne kino: settings touch back -->
        <control type="button" id="9301">
            <left>1170</left><top>40</top><width>190</width><height>85</height>
            <label>Zpět</label><font>font_main</font><textcolor>main_fg_100</textcolor>
            <align>center</align><texturenofocus /><texturefocus />
            <onclick>ActivateWindow(Home)</onclick>
        </control>
'''
    updated = original.replace(anchor, button + anchor, 1)
    ET.fromstring(updated)
    return updated
