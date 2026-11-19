# -*- coding: utf-8 -*-
import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from capture_pixels import has_menu_detail
import skin_input

ID = 'script.michal.family.repair'
STREAMING_HUB = '1104'
STREAMING_LABEL = 'Streamovací služby'
STREAMING_TEMPLATES = (
    'shortcuts/generator/data/setup/widgets_row.xml',
    'shortcuts/generator/data/parts/widgets_combined.xmltemplate',
    'shortcuts/generator/data/parts/widgets_selector.xmltemplate',
    '1080i/Includes_Layouts.xml',
    '1080i/Includes_Lists.xml',
    'shortcuts/generator/data/setup/widgets_include_row.xml',
)

def local_path(path):
    if os.name != 'nt':
        return path
    path = os.path.abspath(os.path.normpath(path))
    if path.startswith('\\\\?\\'):
        return path
    if path.startswith('\\\\'):
        return '\\\\?\\UNC\\' + path[2:]
    return '\\\\?\\' + path

def copy_tree(source, target):
    """Copy content without changing timestamps or permissions on shared storage."""
    os.makedirs(target, exist_ok=True)
    with os.scandir(source) as entries:
        for entry in entries:
            if entry.name == '__pycache__' or entry.name.endswith('.pyc'):
                continue
            destination = os.path.join(target, entry.name)
            if entry.is_dir():
                copy_tree(entry.path, destination)
            else:
                shutil.copyfile(entry.path, destination)

ADDON = xbmcaddon.Addon(ID)
VERSION = ADDON.getAddonInfo('version')
PATH = local_path(xbmcvfs.translatePath(ADDON.getAddonInfo('path')))
PROFILE = local_path(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')))
USER = local_path(xbmcvfs.translatePath('special://profile/'))
HOME_PATH = local_path(xbmcvfs.translatePath('special://home/'))
HOME = xbmcgui.Window(10000)
PROVIDER = 'plugin.video.webshare.available'

def status(stage, **data):
    HOME.setProperty('FamilyRepair.Status', json.dumps({'stage': stage, **data}, ensure_ascii=True))

def read_json(path, fallback=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {} if fallback is None else fallback

def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=os.path.dirname(path),
                                         prefix=os.path.basename(path) + '.', delete=False) as f:
            temporary = f.name
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.isfile(temporary):
            os.remove(temporary)

def packaged_provider_version():
    return read_json(os.path.join(PATH, 'resources', 'manifest.json')).get('provider_version', '0.9.13')

def rpc(method, params=None):
    data = {'jsonrpc': '2.0', 'id': 1, 'method': method}
    if params is not None:
        data['params'] = params
    value = json.loads(xbmc.executeJSONRPC(json.dumps(data)))
    if 'error' in value:
        raise RuntimeError(method + ': ' + value['error']['message'])
    return value.get('result')

def set_setting(key, value, manifest):
    old = rpc('Settings.GetSettingValue', {'setting': key})['value']
    manifest.setdefault('kodi_settings', {}).setdefault(key, old)
    write_json(os.path.join(PROFILE, 'changes.json'), manifest)
    if old != value and not rpc('Settings.SetSettingValue', {'setting': key, 'value': value}):
        raise RuntimeError('Setting refused: ' + key)

def provider_module(name='family'):
    folder = xbmcvfs.translatePath(xbmcaddon.Addon(PROVIDER).getAddonInfo('path'))
    if folder not in sys.path:
        sys.path.insert(0, folder)
    return __import__(name)

def register_provider():
    xbmc.executebuiltin('UpdateLocalAddons')
    for _ in range(60):
        try:
            result = rpc('Addons.GetAddonDetails', {'addonid': PROVIDER, 'properties': ['version', 'enabled']})['addon']
            if result.get('version') == packaged_provider_version():
                if not result.get('enabled'):
                    rpc('Addons.SetAddonEnabled', {'addonid': PROVIDER, 'enabled': True})
                else:
                    return
        except RuntimeError:
            pass
        xbmc.sleep(250)
    raise RuntimeError('Provider registration did not finish')

def install_provider(register=True):
    manifest = read_json(os.path.join(PATH, 'resources', 'manifest.json'))
    package = os.path.join(PATH, 'resources', 'provider-' + packaged_provider_version() + '.zip')
    expected = manifest['provider_sha256']
    with open(package, 'rb') as f:
        if hashlib.sha256(f.read()).hexdigest() != expected:
            raise RuntimeError('Provider checksum mismatch')
    root = os.path.realpath(os.path.join(HOME_PATH, 'addons'))
    allowed = os.path.join(root, PROVIDER) + os.sep
    with zipfile.ZipFile(package) as archive:
        metadata = ET.fromstring(archive.read(PROVIDER + '/addon.xml'))
        if metadata.get('id') != PROVIDER or metadata.get('version') != packaged_provider_version():
            raise RuntimeError('Provider metadata mismatch')
        for entry in archive.infolist():
            target = os.path.realpath(os.path.join(root, entry.filename))
            if not target.startswith(allowed):
                raise RuntimeError('Unexpected provider archive path')
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            target = local_path(os.path.join(root, entry.filename))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            temporary = target + '.family-new'
            try:
                with archive.open(entry) as source, open(temporary, 'wb') as destination:
                    shutil.copyfileobj(source, destination)
                os.replace(temporary, target)
            finally:
                if os.path.isfile(temporary):
                    os.remove(temporary)
    previous = read_json(os.path.join(PROFILE, 'changes.json')).get('provider_files', [])
    for name in set(previous) - set(manifest['provider_files']):
        target = os.path.realpath(os.path.join(root, PROVIDER, name))
        if not target.startswith(allowed):
            raise RuntimeError('Unexpected previous provider path')
        if os.path.isfile(target):
            os.remove(target)
    if register:
        register_provider()


def stage(backup_function):
    baseline = backup_function()
    if not os.path.isdir(baseline['path']):
        raise RuntimeError('Local backup is not available')
    install_provider(register=False)
    changes = read_json(os.path.join(PROFILE, 'changes.json'))
    changes['pending_version'] = VERSION
    write_json(os.path.join(PROFILE, 'changes.json'), changes)
    status('staged_restart_required', version=VERSION, provider=packaged_provider_version(), credentials_exported=False)


def metadata_patch():
    if video_active() or HOME.getProperty('Family.Card.Active'):
        raise RuntimeError('Close title dialogs and playback before applying metadata patch')
    install_provider(register=True)
    changes = read_json(os.path.join(PROFILE, 'changes.json'))
    changes['version'] = VERSION
    changes['metadata_offscreen_patch'] = time.time()
    write_json(os.path.join(PROFILE, 'changes.json'), changes)
    status('metadata_patch_applied', version=VERSION, provider=packaged_provider_version(), credentials_exported=False)


def ui_patch():
    if video_active() or HOME.getProperty('Family.Card.Active'):
        raise RuntimeError('Close title dialogs and playback before applying browser update')
    HOME.setProperty('Family.Service.Stop', 'true')
    for _ in range(40):
        if not HOME.getProperty('Family.Service.Heartbeat'):break
        xbmc.sleep(150)
    else:raise RuntimeError('The previous service did not stop cleanly')
    try:
        install_provider(register=True)
        updated = ratings_skin_patch()
        updated = movie_progress_skin_patch() or updated
    finally:
        HOME.clearProperty('Family.Service.Stop')
        xbmc.executebuiltin('RunScript(special://home/addons/script.michal.family.repair/service.py)')
    changes = read_json(os.path.join(PROFILE, 'changes.json'))
    changes['version'] = VERSION
    changes['single_window_browser'] = time.time()
    updated=search_patch() or updated
    updated=input_skin_patch() or updated
    updated=paging_patch() or updated
    if updated:
        xbmc.executebuiltin('ReloadSkin()')
    write_json(os.path.join(PROFILE, 'changes.json'), changes)
    status('family_ui_applied', version=VERSION, provider=packaged_provider_version(), provider_sha256=read_json(os.path.join(PATH,'resources','manifest.json'))['provider_sha256'], credentials_exported=False)


def finalize():
    for aid, version in ((ID, VERSION), (PROVIDER, packaged_provider_version())):
        addon = rpc('Addons.GetAddonDetails', {'addonid': aid, 'properties': ['version', 'enabled']})['addon']
        if addon.get('version') != version or not addon.get('enabled'):
            raise RuntimeError('Restart has not loaded the staged version')
    if time.time() - float(HOME.getProperty('Family.Service.Heartbeat') or 0) > 5:
        raise RuntimeError('Restarted service is not running')
    changes = read_json(os.path.join(PROFILE, 'changes.json'))
    changes.pop('pending_version', None)
    changes['version'] = VERSION
    changes['applied'] = time.time()
    write_json(os.path.join(PROFILE, 'changes.json'), changes)
    HOME.setProperty('Family.Enabled', 'true')
    status('applied', version=VERSION, provider=packaged_provider_version(), backup=changes.get('backup'), credentials_exported=False)


def video_active():
    return any(row.get('type') == 'video' for row in rpc('Player.GetActivePlayers'))

def translation():
    # Skin strings live under language/, independently of user account data.
    folder = xbmcvfs.translatePath('special://skin/language/resource.language.cs_cz/')
    os.makedirs(folder, exist_ok=True)
    source = os.path.join(PATH, 'resources', 'skin-czech.po')
    destination = os.path.join(folder, 'strings.po')
    if os.path.isfile(source):
        with open(source, encoding='utf-8') as f:
            new = f.read()
        existing = ''
        if os.path.isfile(destination):
            with open(destination, encoding='utf-8') as f:
                existing = f.read()
        if existing == new:
            # Recover upstream strings if an earlier revision installed only
            # the small overlay. The complete baseline is local to the box.
            baseline = read_json(os.path.join(PROFILE, 'baseline.json')).get('path', '')
            old = os.path.join(baseline, 'skin.arctic.fuse.3', 'language', 'resource.language.cs_cz', 'strings.po')
            if os.path.isfile(old):
                with open(old, encoding='utf-8') as f:
                    existing = f.read()
        merged = existing or new.split('msgctxt', 1)[0]
        blocks = re.findall(r'msgctxt "#\d+".*?(?=\nmsgctxt |\Z)', new, re.S)
        for block in blocks:
            number = re.search(r'msgctxt "#(\d+)"', block).group(1)
            pattern = r'msgctxt "#' + number + r'".*?(?=\nmsgctxt |\Z)'
            if re.search(pattern, merged, re.S):
                merged = re.sub(pattern, lambda _: block.rstrip() + '\n', merged, flags=re.S)
            else:
                merged = merged.rstrip() + '\n\n' + block.rstrip() + '\n'
        if existing != merged or not os.path.isfile(destination):
            with open(destination, 'w', encoding='utf-8') as f:
                f.write(merged)
            return True
    return False


def search_navigation(xml):
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(xml, parser=parser)
    item = root.find("./include[@name='Home_ControlList_Item_MultiSearch']")
    modern = item is not None
    if item is None:
        item = root.find("./include[@name='Home_ControlList_Item_1105']")
    if item is None:
        raise RuntimeError('Search navigation item is missing')
    definition = item.find("./include[@content='Home_ControlList_Item']")
    label = definition.find("./param[@name='label']") if definition is not None else None
    action = definition.find("./param[@name='action']") if definition is not None else None
    if label is None or action is None:
        raise RuntimeError('Search navigation label or action is missing')
    target = ('RunPlugin(plugin://' + PROVIDER + '/?action=search&entry=hub&landing=1)'
              if modern else 'ReplaceWindow(1105)')
    if label.text == 'Hledání' and action.text == target:
        return xml
    label.text = 'Hledání'
    action.text = target
    return ET.tostring(root, encoding='unicode') + '\n'


def search_skin_backup():
    version = xbmcaddon.Addon('skin.arctic.fuse.3').getAddonInfo('version')
    return os.path.join(PROFILE, 'search-layout-before', version)


def ratings_skin_text(original):
    marker = '<!-- Rodinné kino: ČSFD -->'
    anchor = '<!-- Total Episodes (Service Disabled) -->'
    if marker in original:
        return original
    meta = ET.fromstring(original).find("./include[@name='Info_Meta']/definition")
    if meta is None or original.count(anchor) != 1 or len(meta.findall(".//include[@content='Info_Meta_Ratings']")) < 2:
        raise RuntimeError('Arctic Fuse ratings row is unavailable')
    item = '$PARAM[container]$PARAM[listitem].'
    home = 'Window(Home).Property(Family.CSFD.'
    matches = ' | '.join(
        f'[!String.IsEmpty({item}{field}) + String.IsEqual({item}{field},{home}{name}))]'
        for field, name in (('UniqueID(tmdb)', 'TMDb'), ('Property(tmdb_id)', 'TMDb'),
                            ('UniqueID(imdb)', 'IMDb'), ('Property(imdb_id)', 'IMDb'))
    )
    visible = (f'!String.IsEmpty({home}Score)) + String.IsEqual({item}DBType,{home}Type))'
               f' + [{matches}]')
    include = f'''{marker}
                    <include content="Info_Meta_Object">
                        <param name="icon_w">0</param>
                        <param name="label">$INFO[{home}Score),ČSFD , %]</param>
                        <param name="visible">{visible}</param>
                        <param name="colordiffuse">$PARAM[colordiffuse]</param>
                    </include>

                    {anchor}'''
    updated = original.replace(anchor, include, 1)
    ET.fromstring(updated)
    return updated


def ratings_skin_patch():
    if xbmc.getSkinDir() != 'skin.arctic.fuse.3':
        return False
    name = 'Includes_Info.xml'
    path = xbmcvfs.translatePath('special://skin/1080i/' + name)
    with open(path, encoding='utf-8') as source:
        original = source.read()
    updated = ratings_skin_text(original)
    if updated == original:
        return False
    backup = search_skin_backup()
    os.makedirs(backup, exist_ok=True)
    previous = os.path.join(backup, name)
    if not os.path.isfile(previous):
        shutil.copyfile(path, previous)
    temporary = path + '.family-new'
    with open(temporary, 'w', encoding='utf-8') as target:
        target.write(updated)
    os.replace(temporary, path)
    return True


def movie_progress_skin_text(original):
    marker = '<!-- Rodinné kino: průběh filmu -->'
    names = ('Poster', 'Landscape', 'Square', 'Flyer', 'MediaList', 'Card', 'Placard')
    prop = 'ListItem.Property(family.movie.progress)'
    line = f'''                {marker}
                <control type="group">
                    <visible>!String.IsEmpty({prop}) + !Skin.HasSetting(Indicator.DisableProgress)</visible>
                    <control type="progress">
                        <left>8</left><right>8</right><bottom>8</bottom><height>4</height>
                        <texturebg colordiffuse="shadow_hard">progress/progress-nib.png</texturebg>
                        <include content="Texture_Progress_Mid">
                            <param name="colordiffuse">main_logo</param>
                        </include>
                        <info>{prop}</info>
                    </control>
                </control>
'''
    result = original
    for name in names:
        start = result.find(f'    <include name="Layout_{name}">')
        if start < 0:
            if name in ('Poster', 'Landscape'):
                raise RuntimeError('Film artwork layout is unavailable')
            continue
        end = result.find('\n    </include>', start)
        if end < 0:
            raise RuntimeError('Film artwork layout is incomplete')
        part = result[start:end]
        if marker in part:
            continue
        offset = part.rfind('\n            </control>')
        if offset >= 0:
            result = result[:start + offset + 1] + line + result[start + offset + 1:]
        elif name in ('Poster', 'Landscape'):
            raise RuntimeError('Film artwork container is unavailable')
    ET.fromstring(result)
    return result


def movie_progress_skin_patch():
    if xbmc.getSkinDir() != 'skin.arctic.fuse.3':
        return False
    name = 'Includes_Layouts.xml'
    path = xbmcvfs.translatePath('special://skin/1080i/' + name)
    with open(path, encoding='utf-8') as source:
        original = source.read()
    updated = movie_progress_skin_text(original)
    if updated == original:
        return False
    backup = search_skin_backup()
    os.makedirs(backup, exist_ok=True)
    previous = os.path.join(backup, name)
    if not os.path.isfile(previous):
        shutil.copyfile(path, previous)
    temporary = path + '.family-new'
    with open(temporary, 'w', encoding='utf-8') as target:
        target.write(updated)
    os.replace(temporary, path)
    return True


def search_patch():
    if xbmc.getSkinDir() != 'skin.arctic.fuse.3':
        return False
    with open(os.path.join(PATH,'resources','search-host.xml'),encoding='utf-8') as f:
        patched=f.read()
    ET.fromstring(patched)
    files = {
        'Custom_1105_Search.xml': lambda _: patched,
        'Includes_Home.xml': search_navigation,
    }
    changes = []
    for name, transform in files.items():
        path = xbmcvfs.translatePath('special://skin/1080i/' + name)
        with open(path, encoding='utf-8') as f:
            original = f.read()
        updated = transform(original)
        if updated != original:
            changes.append((name, path, updated))
    if not changes:
        return False
    backup = search_skin_backup()
    os.makedirs(backup, exist_ok=True)
    for name, path, _ in changes:
        previous = os.path.join(backup, name)
        if not os.path.isfile(previous):
            shutil.copyfile(path, previous)
    for _, path, updated in changes:
        temporary = path + '.family-new'
        with open(temporary, 'w', encoding='utf-8') as f:
            f.write(updated)
        os.replace(temporary, path)
    return True


def input_skin_patch():
    if xbmc.getSkinDir() != 'skin.arctic.fuse.3':
        return False
    transforms = {
        'Includes_Home.xml': skin_input.home,
        'Includes_Hubs.xml': skin_input.hubs,
        'Dialog_DialogKeyboard.xml': skin_input.keyboard,
    }
    changes = []
    for name, transform in transforms.items():
        path = xbmcvfs.translatePath('special://skin/1080i/' + name)
        with open(path, encoding='utf-8') as source:
            original = source.read()
        updated = transform(original)
        if updated != original:
            changes.append((name, path, updated))
    if not changes:
        return False
    backup = search_skin_backup()
    os.makedirs(backup, exist_ok=True)
    for name, path, _ in changes:
        previous = os.path.join(backup, name)
        if not os.path.isfile(previous):
            shutil.copyfile(path, previous)
    for _, path, updated in changes:
        temporary = path + '.family-new'
        with open(temporary, 'w', encoding='utf-8') as target:
            target.write(updated)
        os.replace(temporary, path)
    return True


def search_entry():
    if HOME.getProperty('Family.Search.Active') or video_active():
        return
    now=time.time()
    try:opened=float(HOME.getProperty('Family.SearchOpening') or 0)
    except ValueError:opened=0
    if now-opened<3:return
    HOME.setProperty('Family.SearchOpening',str(now))
    restore=HOME.getProperty('Family.Search.Restore') or HOME.getProperty('Family.Search.PlaybackReturn')
    HOME.clearProperty('Family.Search.Restore')
    xbmc.executebuiltin('RunPlugin(plugin://' + PROVIDER + '/?action=search' + ('&restore=' + restore if restore else '&landing=1') + ')')

def paging_patch():
    paging=provider_module('paging');layout=read_json(os.path.join(PATH,'resources','layout.json'))
    root=os.path.join(USER,'addon_data','script.skinvariables','nodes','skin.arctic.fuse.3');changed=False
    backuproot=os.path.join(PROFILE,'paging-layout-before')
    for node in layout['nodes']:
        if not re.fullmatch(r'(?:home|110[123])(?:widgets|submenu)',node):continue
        filename='skinvariables-shortcut-'+node+'.json';path=os.path.join(root,filename);rows=read_json(path,[]);updated=False
        for entry in rows:
            expanded=paging.decorate_path(entry.get('path',''))
            if not expanded:continue
            if entry.get('path')!=expanded:entry['path']=expanded;updated=True
            if 'widget_limit' in entry and entry['widget_limit']!='0':entry['widget_limit']='0';updated=True
        if updated:
            backupfile=os.path.join(backuproot,filename)
            if not os.path.isfile(backupfile):
                os.makedirs(backuproot,exist_ok=True);shutil.copyfile(path,backupfile)
            write_json(path,rows);HOME.clearProperty('SkinVariables.ShortcutsNode.skin.arctic.fuse.3-'+filename);changed=True
    if changed:
        HOME.setProperty('SkinVariables.ShortcutsNode.Reload',str(time.time()));rebuild_layout()
    return changed


def select_family():
    # Bypass Kodi's PlayMedia/bookmark prompt for our own title cards only.
    # Dialogs keep native Select, including the playback confirmation dialog.
    wid = xbmcgui.getCurrentWindowId()
    if xbmcgui.getCurrentWindowDialogId() not in (0, 9999) or wid not in (10000, 10025, 11101, 11102, 11103, 11104):
        xbmc.executebuiltin('Action(Select)')
        return
    cid = xbmcgui.Window(wid).getFocusId()
    if wid == 11104 and cid == 601:
        row = xbmc.getInfoLabel('Container(601).ListItem.Property(widget_id)')
        for kind, target in (('movie', '502'), ('tv', '503')):
            if row == target:
                provider_module('autopaging').focus_streaming_row(provider_module(), kind)
                return
        if row == '501':
            xbmc.executebuiltin('SetFocus(501)')
            return
    if wid == 11104 and cid == 501 and select_streaming_service():
        return
    if not (501 <= cid <= 550 or cid == 311 or (wid == 10025 and cid >= 50)):
        xbmc.executebuiltin('Action(Select)')
        return
    prefix = 'Container(301).ListItem.' if cid == 311 else 'ListItem.'
    if xbmc.getInfoLabel(prefix+'Property(family.action)') == 'accounts':
        xbmc.executebuiltin('RunScript(script.michal.family.repair,accounts)')
        return
    if xbmc.getInfoLabel(prefix+'Property(family.action)')=='list_more':
        key=xbmc.getInfoLabel(prefix+'Property(family.paging.key)')
        try:
            paging=provider_module('paging');value=paging.from_key(key)
        except ValueError:return
        HOME.setProperty('Family.Paging.Force',paging.key(value));return
    kind = xbmc.getInfoLabel(prefix + 'Property(family.kind)')
    ident = xbmc.getInfoLabel(prefix + 'Property(family.tmdb_id)')
    if kind not in ('movie', 'tv', 'episode') or not ident.isdigit() or int(ident) <= 0:
        xbmc.executebuiltin('Action(Select)')
        return
    params = {'action': 'card', 'kind': kind, 'tmdb_id': int(ident)}
    if kind == 'episode':
        season = xbmc.getInfoLabel(prefix + 'Season')
        episode = xbmc.getInfoLabel(prefix + 'Episode')
        if not season.isdigit() or not episode.isdigit() or int(episode) <= 0:
            xbmc.executebuiltin('Action(Select)')
            return
        params.update(season=int(season), episode=int(episode))
    xbmc.executebuiltin('RunPlugin(plugin://' + PROVIDER + '/?' + urlencode(params) + ')')

def select_streaming_service(request=''):
    prefix = 'Family.Streaming.'
    if request:
        name, movie, tv = request.split('|', 2)
        providers = {'movie':movie,'tv':tv}
    else:
        if xbmc.getInfoLabel('ListItem.Property(family.streaming.card)') != 'true':
            return False
        name = xbmc.getInfoLabel('ListItem.Label')
        providers = {kind:xbmc.getInfoLabel('ListItem.Property(family.streaming.'+kind+')') for kind in ('movie','tv')}
    valid = [kind for kind, value in providers.items()
             if value.isascii() and value.isdigit() and len(value) <= 8 and int(value) > 0]
    if not valid:
        return False
    if HOME.getProperty(prefix+'pending') and HOME.getProperty(prefix+'service')==name:
        return True
    selected = xbmc.getInfoLabel('Container(501).CurrentItem')
    if request and name!=xbmc.getInfoLabel('ListItem.Label'):
        for index in range(int(xbmc.getInfoLabel('Container(501).NumItems') or 0)):
            if xbmc.getInfoLabel('Container(501).ListItemAbsolute({}).Label'.format(index))==name:
                selected=str(index+1)
                break
    HOME.setProperty(prefix + 'return_index', str(max(0, int(selected or 1) - 1)))
    HOME.clearProperty(prefix + 'pending')
    HOME.clearProperty(prefix + 'restore')
    for kind, ident in providers.items():
        HOME.clearProperty(prefix + 'ready.' + kind)
        if kind in valid:
            HOME.setProperty('Family.Paging.Count.list_' + kind + '_provider_' + ident,'10')
            HOME.setProperty(prefix + 'count.' + kind,'10')
            HOME.setProperty(prefix + 'provider.' + kind, ident)
            HOME.setProperty(prefix + 'fresh.' + kind, 'true')
        else:
            HOME.clearProperty(prefix + 'count.' + kind)
            HOME.clearProperty(prefix + 'provider.' + kind)
            HOME.clearProperty(prefix + 'fresh.' + kind)
    HOME.setProperty(prefix + 'service', name)
    HOME.setProperty(prefix + 'pending', valid[0])
    return True


def back_to_streaming_services():
    prefix = 'Family.Streaming.'
    selected = int(HOME.getProperty(prefix + 'return_index') or 0)
    name = HOME.getProperty(prefix + 'service')
    count = int(xbmc.getInfoLabel('Container(501).NumItems') or 0)
    for index in range(count):
        if xbmc.getInfoLabel('Container(501).ListItemAbsolute({}).Label'.format(index)) == name:
            selected = index
            break
    clear_streaming_selection()
    xbmc.executebuiltin('SetFocus(601,0,absolute)')
    HOME.setProperty(prefix + 'restore', str(selected))

def clear_streaming_selection():
    for field in ('pending','service','return_index','request','restore','back'):
        HOME.clearProperty('Family.Streaming.'+field)
    for kind in ('movie','tv'):
        for field in ('provider','count','fresh','ready','retry'):
            HOME.clearProperty('Family.Streaming.'+field+'.'+kind)

def streaming_input():
    prefix='Family.Streaming.'
    if HOME.getProperty(prefix+'back'):
        HOME.clearProperty(prefix+'back')
        if HOME.getProperty(prefix+'request') and not HOME.getProperty(prefix+'service'):
            HOME.clearProperty(prefix+'request')
        else:
            back()
        return
    request=HOME.getProperty(prefix+'request')
    if request:
        HOME.clearProperty(prefix+'request')
        if request.count('|')==2 and xbmc.getInfoLabel('System.CurrentControlID')=='501':
            select_streaming_service(request)
    for kind in ('movie','tv'):
        retry=prefix+'retry.'+kind
        if HOME.getProperty(retry):
            HOME.clearProperty(retry)
            HOME.setProperty(prefix+'reload.'+kind,str(time.time()))


def write_keymap():
    keymaps = os.path.join(USER, 'keymaps')
    os.makedirs(keymaps, exist_ok=True)
    filename = os.path.join(keymaps, 'zz-michal-family.xml')
    content = '''<?xml version="1.0" encoding="UTF-8"?>
<keymap>
 <global><keyboard><backspace>RunScript(script.michal.family.repair,back)</backspace><escape>RunScript(script.michal.family.repair,back)</escape><browser_back>RunScript(script.michal.family.repair,back)</browser_back></keyboard><remote><back>RunScript(script.michal.family.repair,back)</back></remote></global>
 <FullscreenVideo><keyboard><backspace>RunScript(script.michal.family.repair,back_playback)</backspace><escape>RunScript(script.michal.family.repair,back_playback)</escape><browser_back>RunScript(script.michal.family.repair,back_playback)</browser_back></keyboard><remote><back>RunScript(script.michal.family.repair,back_playback)</back></remote></FullscreenVideo>
 <Home><keyboard><backspace>RunScript(script.michal.family.repair,back)</backspace><escape>RunScript(script.michal.family.repair,back)</escape></keyboard><remote><back>RunScript(script.michal.family.repair,back)</back></remote></Home>
 <selectdialog><keyboard><backspace>Back</backspace><escape>Back</escape></keyboard><remote><back>Back</back></remote></selectdialog>
 <virtualkeyboard><keyboard><backspace>Backspace</backspace><escape>Back</escape></keyboard><remote><back>Back</back></remote></virtualkeyboard>
 <progressdialog><keyboard><backspace>Back</backspace><escape>Back</escape></keyboard><remote><back>Back</back></remote></progressdialog>
 <yesnodialog><keyboard><backspace>Back</backspace><escape>Back</escape></keyboard><remote><back>Back</back></remote></yesnodialog>
 <okdialog><keyboard><backspace>Back</backspace><escape>Back</escape></keyboard><remote><back>Back</back></remote></okdialog>
 <contextmenu><keyboard><backspace>Back</backspace><escape>Back</escape></keyboard><remote><back>Back</back></remote></contextmenu>
</keymap>'''
    root = ET.fromstring(content)
    for name in ('Home', 'window11101', 'window11102', 'window11103', 'window11104', 'Videos'):
        node = root.find(name)
        if node is None:
            node = ET.SubElement(root, name)
        for device, keys in (('keyboard', ('return', 'enter')), ('remote', ('select',))):
            device_node = node.find(device)
            if device_node is None:
                device_node = ET.SubElement(node, device)
            for key in keys:
                ET.SubElement(device_node, key).text = 'Select' if name=='window11104' else 'RunScript(script.michal.family.repair,select_family)'
        if name=='window11104':
            for device, keys in (('keyboard',('backspace','escape','browser_back')),('remote',('back',))):
                for key in keys:
                    ET.SubElement(node.find(device),key).text='SetProperty(Family.Streaming.back,1,Home)'
    ET.ElementTree(root).write(filename, encoding='utf-8', xml_declaration=True)
    xbmc.executebuiltin('Action(reloadkeymaps)')

def streaming_template_path(name):
    return xbmcvfs.translatePath('special://skin/' + name)


def streaming_template_backup(name):
    version = xbmcaddon.Addon('skin.arctic.fuse.3').getAddonInfo('version')
    return os.path.join(PROFILE, 'streaming-templates-before', version, os.path.basename(name))


def skin_include(xml, name):
    pattern = r'(?ms)^    <include name="' + re.escape(name) + r'">.*?^    </include>'
    match = re.search(pattern, xml)
    if match is None:
        raise RuntimeError('Skin include is missing: ' + name)
    return match.group()


def streaming_poster_layout(original, backup):
    stock = skin_include(original, 'Layout_Poster')
    if 'family.streaming.card' in stock:
        with open(backup, encoding='utf-8') as source:
            clean = skin_include(source.read(), 'Layout_Poster')
        original = original.replace(stock, clean, 1)
        stock = clean
    poster = stock.replace('name="Layout_Poster"', 'name="Layout_Streaming_Service_Poster"', 1)
    start = poster.index('                    <include content="Object_Layout_Image_Icon">')
    end = poster.index('                    </include>', start) + len('                    </include>')
    service_art = """                    <control type="image">
                        <texture colordiffuse="FF171B26" border="20">common/box.png</texture>
                    </control>
                    <control type="image">
                        <left>21</left><top>30</top><width>175</width><height>175</height>
                        <aspectratio>keep</aspectratio>
                        <texture background="true">$INFO[ListItem.Art(thumb)]</texture>
                    </control>
                    <control type="label">
                        <left>10</left><top>233</top><width>197</width><height>46</height>
                        <align>center</align><aligny>center</aligny>
                        <font>font_mini_bold</font><textcolor>FFFFFFFF</textcolor>
                        <label>$INFO[ListItem.Label]</label>
                    </control>"""
    poster = poster[:start] + service_art + poster[end:]
    if 'Layout_Streaming_Service_Poster' in original:
        existing = skin_include(original, 'Layout_Streaming_Service_Poster')
        return original.replace(existing, poster, 1)
    return original.replace(stock, stock + '\n' + poster, 1)


def streaming_poster_row(original):
    if 'List_Streaming_Service_Row' in original:
        return original
    stock = skin_include(original, 'List_Poster_Row')
    row = stock.replace('name="List_Poster_Row"', 'name="List_Streaming_Service_Row"', 1)
    row = row.replace('>Layout_Poster</param>', '>Layout_Streaming_Service_Poster</param>', 1)
    if 'Layout_Streaming_Service_Poster' not in row:
        raise RuntimeError('The native poster row has changed')
    return original.replace(stock, stock + '\n' + row, 1)


def streaming_poster_rule(original):
    if 'List_Streaming_Service_Row' in original:
        return original
    marker = '<rules name="widget_include">'
    rule = """
        <rule>
            <condition>{item_guid}==michal-streaming-providers</condition>
            <value>List_Streaming_Service_Row</value>
        </rule>"""
    if original.count(marker) != 1:
        raise RuntimeError('The skin widget styles have changed')
    return original.replace(marker, marker + rule, 1)


def patch_streaming_templates():
    # Kodi refreshes only visible or focusable rows. The two catalogue rows
    # must be able to load before the user can switch to their selectors.
    active = '!String.IsEmpty(Window(Home).Property(Family.Streaming.service))'
    open_directory = 'ActivateWindow({widget_target},{widget_path},return)'
    services = {'michal-streaming-movies':'movie','michal-streaming-series':'tv'}
    selected = 'String.IsEqual(Container(601).ListItem.Property(guid),{widget_guid})'
    has_items = '[!Integer.IsEqual(Container({widget_id}).NumItems,0) | Container({widget_id}).IsUpdating]'
    row_kind = {guid:'Window(Home).Property(Family.Streaming.provider.'+kind+')' for guid,kind in services.items()}
    row_ready = {guid:'Window(Home).Property(Family.Streaming.ready.'+kind+')' for guid,kind in services.items()}
    rules = ET.Element('contents')
    for name, values, fallback in (
        ('family_catalogue_focus', {guid:active for guid in services}, 'false'),
        ('family_catalogue_selector', {guid:'!String.IsEmpty('+prop+')' for guid,prop in row_kind.items()}, has_items),
        ('family_catalogue_ready', {guid:'!String.IsEmpty('+prop+')' for guid,prop in row_ready.items()}, 'true'),
        ('family_catalogue_busy', {guid:active+' + String.IsEmpty('+prop+')' for guid,prop in row_ready.items()}, 'false'),
        ('family_catalogue_embedded', {guid:'true' for guid in services}, 'false'),
        ('family_selector_action', {guid:'SetFocus({widget_id})' for guid in (*services,'michal-streaming-providers')}, open_directory),
    ):
        node = ET.SubElement(rules, 'rules', name=name)
        for condition, result in [('{item_guid}==' + guid, value) for guid,value in values.items()] + [('True', fallback)]:
            rule = ET.SubElement(node, 'rule')
            ET.SubElement(rule, 'condition').text = condition
            ET.SubElement(rule, 'value').text = result
    extra = '\n'.join(ET.tostring(rule, encoding='unicode') for rule in rules)
    busy_visible = selected + ' + {family_catalogue_busy}'
    busy = (
        '\n<include content="Widget_Busy" condition="{family_catalogue_embedded}">'
        '<param name="visible">' + busy_visible + '</param>'
        '<param name="include">List_Poster_Row</param>'
        '<top>510</top><left>view_pad</left><visible>' + busy_visible + '</visible></include>'
    )
    transforms = (
        [('</contents>', extra + '\n</contents>')],
        [('<param name="autoscroll">', '<param name="allowhiddenfocus">{family_catalogue_focus}</param>\n    <param name="autoscroll">'),
         ('<param name="visible">'+selected+'</param>\n</include>',
          '<param name="visible">'+selected+' + {family_catalogue_ready}</param>\n</include>'+busy)],
        [(open_directory, '{family_selector_action}'),
         (has_items[1:-1], '{family_catalogue_selector}')],
    )
    markers=('family_catalogue_embedded','family_catalogue_embedded','family_catalogue_selector')
    changes = []
    for index, name in enumerate(STREAMING_TEMPLATES):
        path = streaming_template_path(name)
        with open(path, encoding='utf-8') as source:
            original = source.read()
        updated = original
        if name.endswith('Includes_Layouts.xml'):
            updated = streaming_poster_layout(original, streaming_template_backup(name))
        elif name.endswith('Includes_Lists.xml'):
            updated = streaming_poster_row(original)
        elif name.endswith('widgets_include_row.xml'):
            updated = streaming_poster_rule(original)
        elif markers[index] not in original:
            if 'family_catalogue_' in original:
                with open(streaming_template_backup(name),encoding='utf-8') as backup_source:
                    updated=backup_source.read()
            for before, after in transforms[index]:
                if updated.count(before) != 1:
                    raise RuntimeError('Streaming template layout changed: ' + name)
                updated = updated.replace(before, after)
        if updated == original:
            continue
        ET.fromstring('<root>'+updated+'</root>' if index==1 else updated)
        changes.append((name, path, updated))
    for name, path, updated in changes:
        backup = streaming_template_backup(name)
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        if not os.path.isfile(backup):
            shutil.copyfile(path, backup)
        temporary = path + '.family-new'
        with open(temporary, 'w', encoding='utf-8') as target:
            target.write(updated)
        os.replace(temporary, path)
    return bool(changes)


def streaming_config():
    folder = os.path.join(USER, 'addon_data', 'script.skinvariables', 'nodes', 'skin.arctic.fuse.3')
    name = 'skinvariables-shortcut-hubs.json'
    hubs_file = os.path.join(folder, name)
    widgets_file = os.path.join(folder, 'skinvariables-shortcut-' + STREAMING_HUB + 'widgets.json')
    fallback = xbmcvfs.translatePath('special://skin/shortcuts/' + name)
    hubs = read_json(hubs_file if os.path.isfile(hubs_file) else fallback, [])
    if not isinstance(hubs, list) or not hubs:
        raise RuntimeError('Nabídky Arctic Fuse 3 nejsou dostupné. Otevři nejdřív jeho hlavní obrazovku.')
    hub = next((entry for entry in hubs if entry.get('window') == STREAMING_HUB), None)
    if hub is None or (str(hub.get('disabled', '')).lower() != 'true' and hub.get('label') != STREAMING_LABEL):
        raise RuntimeError('Arctic Fuse 3 už používá pozici 4 pro jinou nabídku. Nejdřív ji vypni nebo přesuň.')
    widgets = read_json(widgets_file, [])
    if not isinstance(widgets, list):
        raise RuntimeError('Položky nabídky streamovacích služeb se nepodařilo načíst.')
    return hubs_file, widgets_file, hubs, hub, widgets


def configure_streaming_hub(manifest):
    hubs_file, widgets_file, hubs, hub, widgets = streaming_config()
    patch_streaming_templates()
    backup = os.path.join(PROFILE, 'streaming-hub-before')
    os.makedirs(backup, exist_ok=True)
    for filename in (hubs_file, widgets_file):
        previous = os.path.join(backup, os.path.basename(filename))
        if os.path.isfile(filename) and not os.path.isfile(previous):
            shutil.copyfile(filename, previous)
    url = 'plugin://' + PROVIDER + '/?action=streaming&view=cards'
    hub.update(label=STREAMING_LABEL, icon='special://skin/extras/icons/livetv.png',
               path='SetFocus(601)', target='', disabled='')
    widget_paths = [('michal-streaming-providers', 'Katalogy v ČR · přehrávání přes Webshare', url)]
    for kind, suffix, title in (('movie', 'movies', 'Filmy'), ('tv', 'series', 'Seriály')):
        path = ('plugin://' + PROVIDER + '/?action=streaming_catalogue&kind=' + kind
                + '&provider=$INFO[Window(Home).Property(Family.Streaming.provider.' + kind + ')]'
                + '&count=$INFO[Window(Home).Property(Family.Streaming.count.' + kind + ')]'
                + '&reload=$INFO[Window(Home).Property(Family.Streaming.reload.' + kind + ')]')
        widget_paths.append(('michal-streaming-' + suffix,
                             title + '$INFO[Window(Home).Property(Family.Streaming.service), · ]', path))
    owned = [{'guid': guid, 'label': label, 'path': path, 'icon': '', 'target': 'videos',
              'widget_limit': '0', 'widget_sortby': 'default', 'widget_style': 'Poster'}
             for guid, label, path in widget_paths]
    owned_guids = {node['guid'] for node in owned}
    widgets = owned + [row for row in widgets if row.get('guid') not in owned_guids]
    for filename, value in ((hubs_file, hubs), (widgets_file, widgets)):
        if read_json(filename, []) != value:
            write_json(filename, value)
            HOME.clearProperty('SkinVariables.ShortcutsNode.skin.arctic.fuse.3-' + os.path.basename(filename))
    for key, value in (('Type', 'Custom'), ('Mode', 'Combined')):
        setting = 'HomeSwitcher.' + STREAMING_HUB + '.' + key
        old = xbmc.getInfoLabel('Skin.String(' + setting + ')')
        manifest.setdefault('skin_strings', {}).setdefault(setting, old)
        if old != value:
            xbmc.executebuiltin('Skin.SetString(' + setting + ',' + value + ')')
    write_json(os.path.join(PROFILE, 'changes.json'), manifest)
    HOME.setProperty('SkinVariables.ShortcutsNode.Reload', str(time.time()))


def streaming_hub_patch():
    if video_active() or HOME.getProperty('Family.Card.Active'):
        raise RuntimeError('Close playback and title cards before the streaming hub update')
    if xbmc.getSkinDir() != 'skin.arctic.fuse.3':
        raise RuntimeError('Arctic Fuse 3 is not active')
    configure_streaming_hub(read_json(os.path.join(PROFILE, 'changes.json')))
    rebuild_layout()
    write_keymap()
    clear_streaming_selection()
    xbmc.executebuiltin('ReloadSkin()')
    status('streaming_hub_applied', window=11104, label=STREAMING_LABEL)


def configure_family_hubs():
    folder = os.path.join(USER, 'addon_data', 'script.skinvariables', 'nodes', 'skin.arctic.fuse.3')
    name = 'skinvariables-shortcut-hubs.json'
    target = os.path.join(folder, name)
    fallback = xbmcvfs.translatePath('special://skin/shortcuts/' + name)
    hubs = read_json(target if os.path.isfile(target) else fallback, [])
    if not isinstance(hubs, list) or not hubs:
        raise RuntimeError('Nabídky Arctic Fuse 3 nejsou dostupné.')
    for window, label, icon in (('1101', 'Filmy', 'shapes.png'),
                                ('1102', 'Seriály', 'shapes.png'), ('1103', 'Moje', 'trakt.png')):
        hub = next((row for row in hubs if str(row.get('window')) == window), None)
        if hub is None:
            hub = {'window': window, 'slot': window[-2:], 'guid': 'family-hub-' + window}
            hubs.append(hub)
        hub.update(label=label, disabled='', path='SetFocus(601)', target='',
                   icon='special://skin/extras/icons/' + icon)
    write_json(target, hubs)
    HOME.clearProperty('SkinVariables.ShortcutsNode.skin.arctic.fuse.3-' + name)


def configure_layout(manifest):
    src = os.path.join(PATH, 'resources', 'layout.json')
    layout = read_json(src)
    for key in layout['strings']:
        manifest.setdefault('skin_strings', {}).setdefault(key, xbmc.getInfoLabel('Skin.String(' + key + ')'))
    for key in layout['bools']:
        manifest.setdefault('skin_bools', {}).setdefault(key, bool(xbmc.getCondVisibility('Skin.HasSetting(' + key + ')')))
    write_json(os.path.join(PROFILE, 'changes.json'), manifest)
    root = os.path.join(USER, 'addon_data', 'script.skinvariables', 'nodes', 'skin.arctic.fuse.3')
    for node, entries in layout['nodes'].items():
        write_json(os.path.join(root, 'skinvariables-shortcut-' + node + '.json'), entries)
        HOME.clearProperty('SkinVariables.ShortcutsNode.skin.arctic.fuse.3-skinvariables-shortcut-' + node + '.json')
    for key, value in layout['strings'].items():
        old = xbmc.getInfoLabel('Skin.String(' + key + ')')
        manifest.setdefault('skin_strings', {}).setdefault(key, old)
        xbmc.executebuiltin('Skin.SetString(' + key + ',"' + str(value).replace('"', '') + '")')
    for key, value in layout['bools'].items():
        old = xbmc.getCondVisibility('Skin.HasSetting(' + key + ')')
        manifest.setdefault('skin_bools', {}).setdefault(key, bool(old))
        xbmc.executebuiltin(('Skin.SetBool' if value else 'Skin.Reset') + '(' + key + ')')
    HOME.setProperty('SkinVariables.ShortcutsNode.Reload', str(time.time()))
    configure_family_hubs()
    configure_streaming_hub(manifest)
    rebuild_layout()


def rebuild_layout():
    last = xbmc.getInfoLabel('Skin.String(Shortcuts.RebuildDateTime)')
    token = str(time.time())
    HOME.clearProperty('Family.TemplateDone')
    command = ('RunScript(script.skinvariables,"run_executebuiltin='
        'route=action=buildtemplate&no_reload=True&force=True&background=False&lastbuildtime=' + last +
        '||route=action=buildtemplate&no_reload=True&background=False&lastbuildtime=' + last +
        '||SetProperty(Family.TemplateDone,' + token + ',Home)")')
    xbmc.executebuiltin(command)
    for _ in range(240):
        if HOME.getProperty('Family.TemplateDone') == token:
            return
        xbmc.sleep(500)
    raise RuntimeError('Skin layout generation timed out')

def configure_player(manifest):
    tmdb = xbmcaddon.Addon('plugin.video.themoviedb.helper')
    for key, value in [('default_player_movies', 'family.webshare.json play_movie'), ('default_player_episodes', 'family.webshare.json play_episode')]:
        manifest.setdefault('tmdb_settings', {}).setdefault(key, tmdb.getSetting(key))
        write_json(os.path.join(PROFILE, 'changes.json'), manifest)
        tmdb.setSetting(key, value)
    folder = os.path.join(USER, 'addon_data', 'plugin.video.themoviedb.helper', 'reconfigured_players')
    os.makedirs(folder, exist_ok=True)
    player = {'name': 'Rodinné kino', 'plugin': PROVIDER, 'priority': 5, 'is_resolvable': 'false',
              'assert': {'play_movie': ['tmdb'], 'search_movie': ['tmdb'], 'play_episode': ['tmdb', 'season', 'episode'], 'search_episode': ['tmdb', 'season', 'episode']}}
    movie = 'executebuiltin://RunPlugin(plugin://' + PROVIDER + '/?action=card&kind=movie&tmdb_id={tmdb})'
    episode = 'executebuiltin://RunPlugin(plugin://' + PROVIDER + '/?action=card&kind=episode&tmdb_id={tmdb}&season={season}&episode={episode})'
    player.update(play_movie=movie, search_movie=movie, play_episode=episode, search_episode=episode)
    write_json(os.path.join(folder, 'family.webshare.json'), player)
    trakt = xbmcaddon.Addon('script.trakt')
    for key, value in (('rate_movie', 'false'), ('rate_episode', 'false'), ('rate_rerate', 'false'), ('last_reminder', '-1')):
        manifest.setdefault('trakt_settings', {}).setdefault(key, trakt.getSetting(key))
        write_json(os.path.join(PROFILE, 'changes.json'), manifest)
        trakt.setSetting(key, value)

def setup_preflight():
    app = rpc('Application.GetProperties', {'properties': ['version']})
    if app['version']['major'] < 21:
        raise RuntimeError('Rodinné kino vyžaduje alespoň Kodi 21 Omega.')
    if video_active() or HOME.getProperty('Family.Card.Active'):
        raise RuntimeError('Zavři přehrávání a otevřené karty filmů před instalací.')

def setup_requirements():
    setup_preflight()
    if xbmc.getSkinDir() != 'skin.arctic.fuse.3':
        raise RuntimeError('Arctic Fuse 3 není aktivní. Potvrď změnu vzhledu a spusť instalaci znovu.')
    missing = []
    for aid in ('skin.arctic.fuse.3', 'plugin.video.themoviedb.helper', 'plugin.video.yawsp', 'script.skinvariables', 'script.trakt'):
        try:
            info = rpc('Addons.GetAddonDetails', {'addonid': aid, 'properties': ['enabled']})['addon']
        except RuntimeError:
            info = {}
        if not info.get('enabled'):
            missing.append(aid)
    if missing:
        raise RuntimeError('Nainstaluj a zapni tyto doplňky podle návodu:\n' + '\n'.join(missing))
    streaming_config()


def apply(backup_function, restart_service=True):
    setup_requirements()
    HOME.clearProperty('FamilyRepair.Error')
    status('backup')
    baseline = backup_function()
    if not os.path.isdir(baseline['path']):
        raise RuntimeError('Local backup is not available')
    manifest_path = os.path.join(PROFILE, 'changes.json')
    changes = read_json(manifest_path)
    changes.setdefault('backup', baseline['path'])
    changes.pop('rolled_back', None)
    write_json(manifest_path, changes)
    HOME.setProperty('Family.Service.Stop', 'true')
    for _ in range(30):
        if not HOME.getProperty('Family.Service.Heartbeat'):
            break
        xbmc.sleep(200)
    status('install_provider')
    install_provider()
    set_setting('general.addonupdates', 0, changes)
    set_setting('filelists.showparentdiritems', False, changes)
    set_setting('locale.audiolanguage', 'Czech', changes)
    set_setting('videoplayer.preferdefaultflag', False, changes)
    configure_player(changes)
    translation()
    search_patch()
    input_skin_patch()
    ratings_skin_patch()
    movie_progress_skin_patch()
    write_keymap()
    status('layout')
    configure_layout(changes)
    changes['version'] = VERSION
    package = read_json(os.path.join(PATH, 'resources', 'manifest.json'))
    changes['provider_version'] = packaged_provider_version()
    changes['provider_sha256'] = package['provider_sha256']
    changes['provider_files'] = package['provider_files']
    changes['skin_version'] = xbmcaddon.Addon('skin.arctic.fuse.3').getAddonInfo('version')
    changes['applied'] = time.time()
    write_json(manifest_path, changes)
    HOME.setProperty('Family.Enabled', 'true')
    HOME.clearProperty('Family.Service.Stop')
    xbmc.executebuiltin('ReloadSkin()')
    if restart_service:
        xbmc.executebuiltin('RunScript(special://home/addons/script.michal.family.repair/service.py)')
    status('applied', version=VERSION, provider=packaged_provider_version(), backup=baseline['path'], credentials_exported=False)

def back_playback():
    if not video_active():
        xbmc.executebuiltin('Action(Back)')
        return
    if HOME.getProperty('Family.PauseMenu'):
        xbmc.executebuiltin('Action(Back)')
        return
    HOME.setProperty('Family.PauseMenu', 'true')
    data = rpc('Player.GetProperties', {'playerid': 1, 'properties': ['speed']}) or {}
    was_playing = data.get('speed', 1) != 0
    if was_playing:
        rpc('Player.PlayPause', {'playerid': 1, 'play': False})
    try:
        choice = xbmcgui.Dialog().select('Přehrávání je pozastavené', ['Pokračovat ve videu', 'Ukončit přehrávání'], preselect=0)
        if choice == 1:
            rpc('Player.Stop', {'playerid': 1})
        elif video_active():
            if was_playing or choice == 0:
                rpc('Player.PlayPause', {'playerid': 1, 'play': True})
    finally:
        HOME.clearProperty('Family.PauseMenu')

def back():
    HOME.setProperty('Family.CancelGeneration', str(time.time()))
    dialog = xbmcgui.getCurrentWindowDialogId()
    if dialog not in (0, 9999):
        xbmc.executebuiltin('Action(Back)')
        return
    wid = xbmcgui.getCurrentWindowId()
    cid = int(xbmc.getInfoLabel('System.CurrentControlID') or 0)
    if wid in (11101,11102,11103,11104) and cid==300:
        clear_streaming_selection()
        xbmc.executebuiltin('ActivateWindow(Home)')
    elif wid == 11104 and HOME.getProperty('Family.Streaming.service'):
        back_to_streaming_services()
    elif wid == 10000 and cid == 300:
        if video_active():
            back_playback()
        else:
            # Repeated Back must never look like a crash or exit the cinema.
            now = time.time()
            if now - float(HOME.getProperty('Family.RootHintAt') or 0) > 4:
                HOME.setProperty('Family.RootHintAt', str(now))
                xbmcgui.Dialog().notification('Rodinné kino', 'Jsi v hlavní nabídce. Tlačítko Domů otevře Android TV.', time=2500, sound=False)
    elif wid == 11105:
        xbmc.executebuiltin('ActivateWindow(Home)')
    else:
        xbmc.executebuiltin('Action(Back)')

def service(updater=None):
    changes = read_json(os.path.join(PROFILE, 'changes.json'))
    if not changes.get('applied') or changes.get('rolled_back'):
        return
    existing = HOME.getProperty('Family.Service.Heartbeat')
    if existing and time.time() - float(existing) < 5:
        return
    token = str(time.time())
    HOME.setProperty('Family.Service.Lock', token)
    HOME.setProperty('Family.Service.Heartbeat', str(time.time()))
    xbmc.sleep(150)
    if HOME.getProperty('Family.Service.Lock') != token:
        return
    tracking = provider_module('tracking')
    player = tracking.ResumePlayer()
    family = provider_module()
    pager = provider_module('autopaging').Pager(family)
    ratings = provider_module('csfd').Ratings(family)
    movie_watch = provider_module('movie_watch').MovieWatchSync(family)
    HOME.setProperty('Family.Service.Version', VERSION)
    monitor = xbmc.Monitor()
    from accounts import offer_setup
    last = 0
    try:
        while (not monitor.abortRequested() and not HOME.getProperty('Family.Service.Stop')
               and HOME.getProperty('Family.Service.Lock') == token):
            HOME.setProperty('Family.Service.Heartbeat', str(time.time()))
            player.tick()
            current = xbmcgui.getCurrentWindowId()
            browsing = (current in (10000, 10025, 11101, 11102, 11103, 11104)
                        and xbmcgui.getCurrentWindowDialogId() in (0, 9999)
                        and not player.isPlaying() and not HOME.getProperty('Family.Card.Active'))
            if updater and updater.ready(browsing and current != 10025):
                return
            movie_watch.tick(browsing)
            try:
                ratings.tick(browsing)
            except (RuntimeError, ValueError, TypeError):
                HOME.setProperty('Family.CSFD.Status', 'local_error')
            if browsing:
                offer_setup()
                try:
                    if current==11104:
                        streaming_input()
                        pager.streaming_tick()
                    elif current in (10000,11101,11102,11103) and any(
                        HOME.getProperty('Family.Streaming.'+key) for key in ('service','restore','request','back')
                    ):
                        clear_streaming_selection()
                    pager.tick(current)
                except Exception as exc:HOME.setProperty('Family.Paging.ServiceError',type(exc).__name__)
            if current in (10000, 11101, 11102, 11103, 11104):
                HOME.setProperty('Family.LastHub', str(current))
            if (time.time() - last > 60 and browsing and xbmc.getGlobalIdleTime() >= 15
                    and not (updater and updater.pending())):
                last = time.time()
                updated = False
                errors = {}
                for patch in (translation, search_patch, input_skin_patch, paging_patch, ratings_skin_patch, movie_progress_skin_patch):
                    HOME.setProperty('Family.Service.Maintenance', patch.__name__)
                    try:
                        updated = patch() or updated
                    except (OSError, RuntimeError, ValueError, ET.ParseError) as exc:
                        errors[patch.__name__] = type(exc).__name__
                HOME.clearProperty('Family.Service.Maintenance')
                try:
                    if patch_streaming_templates():
                        rebuild_layout()
                        updated = True
                except (OSError, RuntimeError, ValueError, ET.ParseError) as exc:
                    errors['streaming_templates'] = type(exc).__name__
                HOME.setProperty('Family.Service.MaintenanceErrors', json.dumps(errors))
                if updated:
                    HOME.setProperty('Family.TranslationUpdated', 'true')
                    if xbmcgui.getCurrentWindowId() in (10000, 11101, 11102, 11103, 11104) and xbmcgui.getCurrentWindowDialogId() in (0, 9999):
                        xbmc.executebuiltin('ReloadSkin()')
            if monitor.waitForAbort(0.08 if current==11104 else 0.25):
                break
    finally:
        pager.close()
        ratings.close()
        movie_watch.close()
        if HOME.getProperty('Family.Service.Lock') == token:
            HOME.clearProperty('Family.Service.Heartbeat')
            HOME.clearProperty('Family.Service.Maintenance')

def atlas_settings():
    addon = xbmcaddon.Addon(PROVIDER)
    setting = 'atlas_api_key'
    dialog = xbmcgui.Dialog()
    options = ['Zadat nebo vyměnit klíč Atlasu']
    if addon.getSettingString(setting):
        options.append('Odebrat klíč Atlasu')
    choice = dialog.select('ČSFD – stav: ' + {
        'needs_key': 'čeká na klíč', 'ready': 'připraveno', 'cached': 'hodnocení uloženo',
        'updated': 'aktualizováno', 'atlas_access_401': 'Atlas odmítl klíč',
        'atlas_access_403': 'Atlas odmítl přístup k ČSFD', 'atlas_limit': 'vyčerpán limit Atlasu',
        'atlas_unavailable': 'Atlas neodpovídá', 'no_imdb_id': 'titul nemá ID IMDb',
    }.get(HOME.getProperty('Family.CSFD.Status'), 'ověřuji'), options)
    if choice == 0:
        key = dialog.input('API klíč Atlasu', type=xbmcgui.INPUT_ALPHANUM, option=xbmcgui.ALPHANUM_HIDE_INPUT).strip()
        if key:
            addon.setSettingString(setting, key)
    elif choice == 1:
        addon.setSettingString(setting, '')


def menu(backup_function=None):
    changes = read_json(os.path.join(PROFILE, 'changes.json'))
    setup_label = 'Nainstalovat Rodinné kino včetně vzhledu'
    if not changes.get('applied') or changes.get('rolled_back'):
        from bootstrap import dismiss_skin_wizard
        dismiss_skin_wizard()
        if backup_function and xbmcgui.Dialog().yesno('Rodinné kino',
                'Nainstalovat vzhled Arctic Fuse 3, potřebné doplňky a nabídky Rodinného kina? Kodi může vyžádat potvrzení instalace a změny vzhledu.'):
            from bootstrap import install
            install(backup_function)
        return
    options = ['Kontrola rodinného kina', 'Předvolby: český zvuk a 1080p', 'Otevřít přihlášení Trakt', 'Otevřít přihlášení Webshare', 'Zobrazit umístění zálohy', 'Obnovit původní sestavu', 'Přejít na Android TV', setup_label, 'Hodnocení ČSFD – Atlas', 'Dokončit přihlášení účtů', 'Zavřít']
    choice = xbmcgui.Dialog().select('Servis rodinného kina', options)
    if choice == 0:
        verify()
        xbmcgui.Dialog().ok('Kontrola rodinného kina', HOME.getProperty('FamilyRepair.Summary'))
    elif choice == 1:
        xbmcgui.Dialog().ok('Předvolby přehrávání', 'Správný titul a díl → český zvuk → 1080p.\n4K je samostatná volba v nabídce kvality.')
    elif choice == 2:
        try:account = xbmcaddon.Addon('script.module.tmdbhelper.sync.trakt')
        except RuntimeError:account = xbmcaddon.Addon('plugin.video.themoviedb.helper')
        account.openSettings()
    elif choice == 3:
        from accounts import connect_webshare
        connect_webshare()
    elif choice == 4:
        xbmcgui.Dialog().ok('Záloha zůstává na krabičce', read_json(os.path.join(PROFILE, 'baseline.json')).get('path', 'Záloha není dostupná.'))
    elif choice == 5:
        if xbmcgui.Dialog().yesno('Obnovit původní sestavu?', 'Obnoví se původní doplněk, layout a ovládání. Přihlášení zůstane zachované.', defaultbutton=xbmcgui.DLG_YESNO_NO_BTN):
            rollback()
    elif choice == 6:
        xbmc.executebuiltin('Minimize')
    elif choice == 7 and backup_function:
        if xbmcgui.Dialog().yesno(setup_label + '?',
                                  'Instalátor doplní chybějící součásti, vytvoří místní zálohu a nastaví nabídky, ovládání a přehrávač.',
                                  defaultbutton=xbmcgui.DLG_YESNO_NO_BTN):
            from bootstrap import install
            install(backup_function)
    elif choice == 8:
        atlas_settings()
    elif choice == 9:
        from accounts import guide
        guide()

def verify():
    checks = []
    for aid in (PROVIDER, 'skin.arctic.fuse.3', 'plugin.video.themoviedb.helper', 'plugin.video.yawsp', 'script.trakt'):
        data = rpc('Addons.GetAddonDetails', {'addonid': aid, 'properties': ['version', 'enabled']})['addon']
        checks.append({'check': aid, 'pass': data['enabled'], 'version': data['version']})
    checks.append({'check': 'parent folder hidden', 'pass': not rpc('Settings.GetSettingValue', {'setting': 'filelists.showparentdiritems'})['value']})
    checks.append({'check': 'service running', 'pass': time.time() - float(HOME.getProperty('Family.Service.Heartbeat') or 0) < 5})
    checks.append({'check': 'Czech preferred audio', 'pass': rpc('Settings.GetSettingValue', {'setting': 'locale.audiolanguage'})['value'] == 'Czech'})
    checks.append({'check': 'language before file default', 'pass': not rpc('Settings.GetSettingValue', {'setting': 'videoplayer.preferdefaultflag'})['value']})
    family = provider_module()
    checks.append({'check': 'Trakt integration client available', 'pass': bool(family.core.trakt_client_id())})
    checks.append({'check': 'Trakt credentials available', 'pass': bool(family.core.trakt_token_candidates())})
    checks.append({'check': 'Webshare credentials available', 'pass': bool(xbmcaddon.Addon('plugin.video.yawsp').getSetting('token'))})
    hubs = read_json(os.path.join(USER, 'addon_data', 'script.skinvariables', 'nodes',
                                 'skin.arctic.fuse.3', 'skinvariables-shortcut-hubs.json'), [])
    for window, title in (('1101', 'Filmy'), ('1102', 'Seriály'), ('1103', 'Moje')):
        checks.append({'check': 'navigation ' + window, 'pass': any(
            str(row.get('window')) == window and row.get('label') == title
            and str(row.get('disabled', '')).lower() != 'true' for row in hubs)})
    from urllib.error import URLError
    original = family.core.trakt_request
    try:
        for name, exception, expected in [('expired authentication', RuntimeError('Trakt HTTP 401'), 'Přihlášení'), ('network outage', URLError('network unavailable'), 'Služba')]:
            def unavailable(*args, _error=exception, **kwargs):
                raise _error
            family.core.trakt_request = unavailable
            try:
                family.family_source('movie', 'collection', True)
                passed = False
            except Exception as exc:
                passed = family.classify_error(exc)[0].startswith(expected)
            checks.append({'check': 'controlled transport fault: ' + name, 'pass': passed})
        family.core.trakt_request = lambda *args, **kwargs: []
        checks.append({'check': 'controlled transport: truly empty collection', 'pass': family.family_source('movie', 'collection', True) == []})
    finally:
        family.core.trakt_request = original
    folder = os.path.join(USER, 'addon_data', 'script.skinvariables', 'nodes', 'skin.arctic.fuse.3')
    for filename in ('skinvariables-shortcut-1101widgets.json', 'skinvariables-shortcut-1102widgets.json', 'skinvariables-shortcut-1103widgets.json'):
        rows = read_json(os.path.join(folder, filename), [])
        checks.append({'check': filename, 'pass': bool(rows) and all(PROVIDER in row.get('path', '') for row in rows)})
    bindings=[]
    for node in ('homewidgets','1101widgets','1102widgets','1103widgets'):
        for row in read_json(os.path.join(folder,'skinvariables-shortcut-'+node+'.json'),[]):
            path=row.get('path','')
            if path.startswith('plugin://'+PROVIDER+'/') and any('action='+action in path for action in ('list','personal')):
                bindings.append('infinite=1' in path and 'Family.Paging.Count.' in path and str(row.get('widget_limit'))=='0')
    checks.append({'check':'automatic list continuation configured','pass':bool(bindings) and all(bindings),'bindings':len(bindings)})
    data = {'checks': checks, 'pass': all(row['pass'] for row in checks)}
    HOME.setProperty('FamilyRepair.Verification', json.dumps(data))
    HOME.setProperty('FamilyRepair.Summary', '{} kontrol, {} chyb.'.format(len(checks), sum(not x['pass'] for x in checks)))
    status('verified', **data)


def diagnostics():
    # Inspect crash evidence locally. Export only known component names, event
    # categories and Python file/line numbers, never raw log lines or URLs.
    events = []
    folder = xbmcvfs.translatePath('special://logpath/')
    for name in ('kodi.old.log', 'kodi.log'):
        filename = os.path.join(folder, name)
        if not os.path.isfile(filename):
            continue
        with open(filename, 'rb') as f:
            f.seek(max(0, os.path.getsize(filename) - 600000))
            lines = f.read().decode('utf-8', 'replace').splitlines()
        rows = []
        for line in lines:
            tags = []
            for tag, pattern in (
                ('native-crash', r'(?i)SIGSEGV|SIGABRT|segmentation|fatal signal|crash'),
                ('video-open', r'CVideoPlayer::Open|Creating InputStream|Creating Demuxer'),
                ('video-stop', r'CVideoPlayer::Close|CVideoPlayer::OnExit|CVideoPlayer::Process\(\) - exit'),
                ('codec-h264', r'(?i)amc-h264|video/avc|ff-h264'),
                ('codec-hevc', r'(?i)amc-hevc|amc-h265|video/hevc|ff-hevc'),
                ('codec-error', r'(?i)(?:error|failed|exception).*(?:MediaCodec|decoder)|(?:MediaCodec|decoder).*(?:error|failed|exception)'),
                ('python-error', r'Error Type:|AttributeError|TypeError|RuntimeError|PythonToCppException'),
                ('plugin-resolve-error', r'(?i)error.*(?:GetPluginResult|CPluginDirectory)|(?:GetPluginResult|CPluginDirectory).*error'),
            ):
                if re.search(pattern, line):
                    tags.append(tag)
            fileline = re.search(r'File "[^"]*[/\\]([\w.-]+\.py)", line (\d+)', line)
            if fileline:
                tags.append('python-location:' + fileline[1] + ':' + fileline[2])
            if tags:
                rows.append({'time': line[:23] if re.match(r'\d{4}-\d\d-\d\d', line) else '', 'tags': tags})
        events.append({'log': name, 'events': rows[-65:]})
    HOME.setProperty('FamilyRepair.Diagnostics', json.dumps(events))
    trace=read_json(os.path.join(USER,'addon_data',PROVIDER,'family-ui-trace.json'))
    if trace.get('arguments_recorded') is False:
        HOME.setProperty('FamilyRepair.UITrace',json.dumps(trace))
    status('diagnostics_done', logs=len(events), raw_logs_exported=False)


def cloudcheck():
    family = provider_module()
    data = json.loads(HOME.getProperty('Family.PlaybackContext') or '{}')
    item = data.get('record', {}).get('item') or {}
    if item.get('kind') not in ('movie', 'episode'):
        raise RuntimeError('No controlled playback context')
    rows = family.core.trakt_request('/sync/playback/' + ('movies' if item['kind'] == 'movie' else 'episodes'), {'extended': 'full', 'limit': 100})
    result = {'kind': item['kind'], 'tmdb_id': item['tmdb_id'], 'season': item.get('season'), 'episode': item.get('episode'), 'found': False}
    saved = family.local_progress().get(family.media_key(item['kind'], item['tmdb_id'], item.get('season'), item.get('episode')), {})
    result['local_position'] = saved.get('position', 0)
    result['duration'] = saved.get('duration', 0)
    for row in rows:
        media = row.get('movie') if item['kind'] == 'movie' else row.get('show')
        if (media or {}).get('ids', {}).get('tmdb') != item['tmdb_id']:
            continue
        ep = row.get('episode') or {}
        if item['kind'] == 'episode' and (ep.get('season'), ep.get('number')) != (item['season'], item['episode']):
            continue
        position = float(row.get('progress') or 0) * float(saved.get('duration') or 0) / 100
        result.update(found=True, cloud_position=round(position, 2), progress=row.get('progress'), agrees_with_local=abs(position - float(saved.get('position') or 0)) < 20)
        break
    HOME.setProperty('FamilyRepair.CloudProgress', json.dumps(result))
    status('cloud_checked', **result)

def capture(request=''):
    # User explicitly authorized Kodi UI screenshots. Account/settings screens
    # and playback frames are excluded from this fixed capture path.
    wid = xbmcgui.getCurrentWindowId()
    dialog = xbmcgui.getCurrentWindowDialogId()
    card = bool(HOME.getProperty('Family.Card.Active'))
    if dialog in (10103, 10109, 10140, 10142, 10143) or (dialog not in (0, 9999) and not card):
        raise RuntimeError('Capture excludes account, keyboard and settings dialogs')
    if rpc('Player.GetActivePlayers') or (wid not in (10000, 11101, 11102, 11103, 11104, 11105) and not card):
        raise RuntimeError('Capture requires idle family UI')
    if request and not re.fullmatch(r'[a-f0-9]{1,32}',request):
        raise ValueError('Invalid screenshot request identifier')
    if xbmc.getCondVisibility('System.IsInScreenSaver'):
        raise RuntimeError('Capture requires an awake Kodi screen')
    token=request or format(time.time_ns(),'x')
    filename = xbmcvfs.translatePath('special://temp/michal-family-ui-'+token+'.png')
    selected = xbmc.getInfoLabel('ListItem.Label') if wid==11104 else ''
    window = xbmcgui.Window(dialog if dialog not in (0, 9999) else wid)
    marker = xbmcgui.ControlImage(
        max(0, window.getWidth() - 6), max(0, window.getHeight() - 6), 4, 4,
        'special://skin/extras/icons/search.png', colorDiffuse='20FFFFFF',
    )
    def check_context():
        if (xbmcgui.getCurrentWindowId() != wid or xbmcgui.getCurrentWindowDialogId() != dialog
                or rpc('Player.GetActivePlayers') or xbmc.getCondVisibility('System.IsInScreenSaver')
                or (wid == 11104 and xbmc.getInfoLabel('ListItem.Label') != selected)):
            raise RuntimeError('Kodi left the selected menu during screenshot capture')

    status('capture_running',request=token)
    HOME.clearProperty('FamilyRepair.ImageInfo')
    window.addControl(marker)
    try:
        # Keep the GUI frame dirty while Kodi's synchronous capture reads it.
        # The control is non-focusable and only exists during the request.
        marker.setAnimations([('conditional', 'effect=fade start=10 end=100 time=120 pulse=true condition=true')])
        for attempt in range(1, 6):
            xbmc.sleep(200 if attempt == 1 else 90)
            check_context()
            xbmc.executebuiltin('TakeScreenshot("' + filename + '",sync)', True)
            if os.path.isfile(filename):
                with open(filename, 'rb') as f:
                    data = f.read()
                os.remove(filename)
                if has_menu_detail(data):
                    check_context()
                    break
        else:
            raise RuntimeError('Kodi did not return a visible menu frame')
    finally:
        try:
            if os.path.isfile(filename):
                os.remove(filename)
        finally:
            window.removeControl(marker)
    encoded = base64.b64encode(data).decode('ascii')
    chunks = [encoded[i:i+45000] for i in range(0, len(encoded), 45000)]
    for index, chunk in enumerate(chunks):
        HOME.setProperty('FamilyRepair.Image.' + str(index), chunk)
    HOME.setProperty('FamilyRepair.ImageInfo', json.dumps({
        'chunks': len(chunks), 'sha256': hashlib.sha256(data).hexdigest(), 'window': wid,
        'request': token, 'selected': selected, 'captured_at': time.time(), 'attempts': attempt,
    }))
    status('capture_done', request=token, chunks=len(chunks))

def rollback():
    changes = read_json(os.path.join(PROFILE, 'changes.json'))
    baseline = changes.get('backup')
    if not baseline or not os.path.isdir(baseline):
        raise RuntimeError('Rollback backup is missing')
    HOME.setProperty('Family.Service.Stop', 'true')
    changes['rolled_back'] = True
    write_json(os.path.join(PROFILE, 'changes.json'), changes)
    src = os.path.join(baseline, 'addons', PROVIDER)
    dst = os.path.join(HOME_PATH, 'addons', PROVIDER)
    if os.path.isdir(src):
        # Remove only files installed by this package which had no baseline copy.
        installed = read_json(os.path.join(PATH, 'resources', 'manifest.json')).get('provider_files', [])
        for relative in installed:
            original = os.path.join(src, relative)
            target = os.path.realpath(os.path.join(dst, relative))
            if not target.startswith(os.path.realpath(dst) + os.sep):
                raise RuntimeError('Rollback path is outside the provider')
            if not os.path.isfile(original) and os.path.isfile(target):
                os.remove(target)
        copy_tree(src, dst)
    elif os.path.isfile(os.path.join(dst, 'addon.xml')):
        rpc('Addons.SetAddonEnabled', {'addonid': PROVIDER, 'enabled': False})
    original_nodes = os.path.join(baseline, 'userdata', 'addon_data', 'script.skinvariables', 'nodes', 'skin.arctic.fuse.3')
    nodes_dir = os.path.join(USER, 'addon_data', 'script.skinvariables', 'nodes', 'skin.arctic.fuse.3')
    layout = read_json(os.path.join(PATH, 'resources', 'layout.json'))
    for node in (*layout.get('nodes', {}), 'hubs', STREAMING_HUB + 'widgets'):
        name = 'skinvariables-shortcut-' + node + '.json'
        original = os.path.join(original_nodes, name)
        target = os.path.join(nodes_dir, name)
        if os.path.isfile(original):
            os.makedirs(nodes_dir, exist_ok=True)
            shutil.copyfile(original, target)
        elif os.path.isfile(target):
            os.remove(target)
        HOME.clearProperty('SkinVariables.ShortcutsNode.skin.arctic.fuse.3-' + name)
    for key, value in changes.get('kodi_settings', {}).items():
        rpc('Settings.SetSettingValue', {'setting': key, 'value': value})
    tmdb = xbmcaddon.Addon('plugin.video.themoviedb.helper')
    for key, value in changes.get('tmdb_settings', {}).items():
        tmdb.setSetting(key, value)
    trakt = xbmcaddon.Addon('script.trakt')
    for key, value in changes.get('trakt_settings', {}).items():
        trakt.setSetting(key, value)
    for key, value in changes.get('skin_strings', {}).items():
        xbmc.executebuiltin('Skin.SetString(' + key + ',"' + str(value).replace('"', '') + '")')
    for key, value in changes.get('skin_bools', {}).items():
        xbmc.executebuiltin(('Skin.SetBool' if value else 'Skin.Reset') + '(' + key + ')')
    keymap = os.path.join(USER, 'keymaps', 'zz-michal-family.xml')
    old_keymap = os.path.join(baseline, 'userdata', 'keymaps', 'zz-michal-family.xml')
    if os.path.isfile(old_keymap):
        shutil.copyfile(old_keymap, keymap)
    elif os.path.isfile(keymap):
        os.remove(keymap)
    translated = xbmcvfs.translatePath('special://skin/language/resource.language.cs_cz/strings.po')
    old_translation = os.path.join(baseline, 'skin.arctic.fuse.3', 'language', 'resource.language.cs_cz', 'strings.po')
    if os.path.isfile(old_translation):
        os.makedirs(os.path.dirname(translated), exist_ok=True)
        shutil.copyfile(old_translation, translated)
    elif os.path.isfile(translated):
        os.remove(translated)
    for name in ('Custom_1105_Search.xml', 'Includes_Home.xml', 'Includes_Info.xml', 'Includes_Layouts.xml'):
        old_search = os.path.join(search_skin_backup(), name)
        if not os.path.isfile(old_search) and name == 'Custom_1105_Search.xml':
            old_search = os.path.join(baseline, 'skin.arctic.fuse.3', '1080i', name)
        if os.path.isfile(old_search):
            shutil.copyfile(old_search, xbmcvfs.translatePath('special://skin/1080i/' + name))
    for name in STREAMING_TEMPLATES:
        old_template = streaming_template_backup(name)
        if os.path.isfile(old_template):
            shutil.copyfile(old_template, streaming_template_path(name))
    family_player = os.path.join(USER, 'addon_data', 'plugin.video.themoviedb.helper', 'reconfigured_players', 'family.webshare.json')
    old_family_player = os.path.join(baseline, 'userdata', 'addon_data', 'plugin.video.themoviedb.helper', 'reconfigured_players', 'family.webshare.json')
    if os.path.isfile(old_family_player):
        shutil.copyfile(old_family_player, family_player)
    elif os.path.isfile(family_player):
        os.remove(family_player)
    HOME.clearProperty('Family.Enabled')
    HOME.setProperty('SkinVariables.ShortcutsNode.Reload', str(time.time()))
    rebuild_layout()
    xbmc.executebuiltin('Action(reloadkeymaps)')
    xbmc.executebuiltin('UpdateLocalAddons')
    previous_skin = changes.get('previous_skin')
    if previous_skin and previous_skin != xbmc.getSkinDir():
        if not rpc('Settings.SetSettingValue', {'setting': 'lookandfeel.skin', 'value': previous_skin}):
            raise RuntimeError('Původní nastavení bylo obnoveno. Vyber původní vzhled v nastavení Kodi.')
    else:
        xbmc.executebuiltin('ReloadSkin()')
    status('rolled_back')
