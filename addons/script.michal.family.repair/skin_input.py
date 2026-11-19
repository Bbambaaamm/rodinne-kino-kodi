"""Small, repeatable Arctic Fuse 3 input fixes for touch and passwords."""
from xml.etree import ElementTree as ET


ANDROID_NAVIGATION = '''
    <!-- Rodinne kino: Android touch navigation -->
    <include name="Family_Android_Touch_Navigation">
        <definition>
            <control type="button"><left>145</left><top>130</top><width>175</width><height>85</height><label /><texturenofocus /><texturefocus /><onclick>ReplaceWindow(Home)</onclick></control>
            <control type="button"><left>325</left><top>130</top><width>140</width><height>85</height><label /><texturenofocus /><texturefocus /><onclick>ReplaceWindow(1101)</onclick></control>
            <control type="button"><left>485</left><top>130</top><width>145</width><height>85</height><label /><texturenofocus /><texturefocus /><onclick>ReplaceWindow(1102)</onclick></control>
            <control type="button"><left>655</left><top>130</top><width>135</width><height>85</height><label /><texturenofocus /><texturefocus /><onclick>ReplaceWindow(1103)</onclick></control>
            <control type="button"><left>800</left><top>130</top><width>315</width><height>85</height><label /><texturenofocus /><texturefocus /><onclick>ReplaceWindow(1104)</onclick></control>
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
    ET.fromstring(updated)
    return updated


def hubs(original):
    if '<include name="Family_Android_Touch_Navigation">' in original:
        ET.fromstring(original)
        return original
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
