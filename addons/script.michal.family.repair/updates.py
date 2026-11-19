"""Apply installed releases at idle and recover the last working local setup."""
import os
import shutil
import time
from datetime import datetime

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

import maintenance as m


IDLE_SECONDS = 15
HUBS = (10000, 11101, 11102, 11103, 11104)


def addon_version(addon):
    try:
        return m.rpc('Addons.GetAddonDetails', {
            'addonid': addon, 'properties': ['version'],
        })['addon']['version']
    except RuntimeError:
        return ''


class Snapshot:
    def __init__(self):
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.path = os.path.join(m.PROFILE, 'update-backups', stamp)
        self.files = []
        self.settings = {}

    def capture(self):
        os.makedirs(self.path)
        layout = m.read_json(os.path.join(m.PATH, 'resources', 'layout.json'))
        package = m.read_json(os.path.join(m.PATH, 'resources', 'manifest.json'))
        provider = os.path.join(m.HOME_PATH, 'addons', m.PROVIDER)
        paths = {os.path.join(provider, name) for name in package['provider_files']}
        skin = xbmcvfs.translatePath('special://skin/')
        for folder in (provider, os.path.join(skin, '1080i'), m.search_skin_backup(),
                       os.path.dirname(m.streaming_template_backup(m.STREAMING_TEMPLATES[0]))):
            for root, dirs, names in os.walk(folder):
                dirs[:] = [name for name in dirs if name != '__pycache__']
                paths.update(os.path.join(root, name) for name in names)
        paths.update(m.streaming_template_path(name) for name in m.STREAMING_TEMPLATES)
        paths.update(m.streaming_template_backup(name) for name in m.STREAMING_TEMPLATES)
        for name in ('Custom_1105_Search.xml', 'Includes_Home.xml', 'Includes_Hubs.xml',
                     'Dialog_DialogKeyboard.xml', 'Includes_Info.xml', 'Includes_Layouts.xml'):
            paths.add(os.path.join(m.search_skin_backup(), name))
        nodes = os.path.join(m.USER, 'addon_data', 'script.skinvariables', 'nodes', 'skin.arctic.fuse.3')
        paths.update(os.path.join(nodes, 'skinvariables-shortcut-' + name + '.json')
                     for name in (*layout['nodes'], 'hubs', m.STREAMING_HUB + 'widgets'))
        paths.update((os.path.join(m.USER, 'keymaps', 'zz-michal-family.xml'),
                      os.path.join(skin, 'language', 'resource.language.cs_cz', 'strings.po'),
                      os.path.join(m.PROFILE, 'changes.json'),
                      os.path.join(m.USER, 'addon_data', 'plugin.video.themoviedb.helper',
                                   'reconfigured_players', 'family.webshare.json')))
        for index, target in enumerate(sorted({m.local_path(path) for path in paths})):
            saved = os.path.join(self.path, str(index))
            exists = os.path.isfile(target)
            if exists:
                shutil.copyfile(target, saved)
            self.files.append({'target': target, 'saved': saved, 'exists': exists})
        self.settings['kodi'] = {key: m.rpc('Settings.GetSettingValue', {'setting': key})['value']
                                 for key in ('general.addonupdates', 'filelists.showparentdiritems', 'locale.audiolanguage',
                                             'videoplayer.preferdefaultflag')}
        self.settings['tmdb'] = {key: xbmcaddon.Addon('plugin.video.themoviedb.helper').getSetting(key)
                                 for key in ('default_player_movies', 'default_player_episodes')}
        self.settings['trakt'] = {key: xbmcaddon.Addon('script.trakt').getSetting(key)
                                  for key in ('rate_movie', 'rate_episode', 'rate_rerate', 'last_reminder')}
        strings = (*layout['strings'], 'HomeSwitcher.1104.Type', 'HomeSwitcher.1104.Mode')
        self.settings['strings'] = {key: xbmc.getInfoLabel('Skin.String(' + key + ')') for key in strings}
        self.settings['bools'] = {key: bool(xbmc.getCondVisibility('Skin.HasSetting(' + key + ')'))
                                  for key in layout['bools']}
        m.write_json(os.path.join(self.path, 'snapshot.json'), {'files': self.files, 'settings': self.settings})

    def restore(self):
        for entry in self.files:
            target = entry['target']
            if entry['exists']:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                temporary = target + '.family-restore'
                shutil.copyfile(entry['saved'], temporary)
                os.replace(temporary, target)
            elif os.path.isfile(target):
                os.remove(target)
        for key, value in self.settings['kodi'].items():
            m.rpc('Settings.SetSettingValue', {'setting': key, 'value': value})
        for group, addon in (('tmdb', 'plugin.video.themoviedb.helper'), ('trakt', 'script.trakt')):
            for key, value in self.settings[group].items():
                xbmcaddon.Addon(addon).setSetting(key, value)
        for key, value in self.settings['strings'].items():
            xbmc.executebuiltin('Skin.SetString(' + key + ',"' + value.replace('"', '') + '")')
        for key, value in self.settings['bools'].items():
            xbmc.executebuiltin(('Skin.SetBool' if value else 'Skin.Reset') + '(' + key + ')')
        m.HOME.setProperty('SkinVariables.ShortcutsNode.Reload', str(time.time()))
        xbmc.executebuiltin('UpdateLocalAddons')
        xbmc.executebuiltin('Action(reloadkeymaps)')
        xbmc.executebuiltin('ReloadSkin()')


class Updater:
    def __init__(self):
        self.next_check = 0
        self.target = None
        self.state_path = os.path.join(m.PROFILE, 'update-state.json')

    def pending(self):
        if time.monotonic() < self.next_check:
            return bool(self.target)
        self.next_check = time.monotonic() + 5
        changes = m.read_json(os.path.join(m.PROFILE, 'changes.json'))
        self.target = None
        if not changes.get('applied') or changes.get('rolled_back'):
            return False
        package = m.read_json(os.path.join(m.PATH, 'resources', 'manifest.json'))
        target = {'version': m.VERSION, 'provider': m.packaged_provider_version(),
                  'provider_sha256': package['provider_sha256'],
                  'skin_version': addon_version('skin.arctic.fuse.3')}
        if (changes.get('version') != target['version']
                or changes.get('provider_sha256') != target['provider_sha256']
                or changes.get('skin_version') != target['skin_version']
                or addon_version(m.PROVIDER) != target['provider']):
            self.target = target
            m.HOME.setProperty('Family.Update.Pending', m.VERSION)
            m.HOME.setProperty('Family.Update.State', 'waiting_for_idle')
        else:
            m.HOME.clearProperty('Family.Update.Pending')
        return bool(self.target)

    def ready(self, browsing=None):
        if not self.pending():
            return False
        saved = m.read_json(self.state_path)
        if saved.get('target') == self.target and saved.get('retry_after', 0) > time.time():
            return False
        if browsing is None:
            browsing = (xbmcgui.getCurrentWindowId() in HUBS
                        and xbmcgui.getCurrentWindowDialogId() in (0, 9999))
        return (browsing and xbmc.getSkinDir() == 'skin.arctic.fuse.3'
                and not m.HOME.getProperty('Family.Setup.InProgress')
                and not m.HOME.getProperty('Family.Card.Active')
                and not m.HOME.getProperty('Family.PauseMenu')
                and not m.rpc('Player.GetActivePlayers')
                and xbmc.getGlobalIdleTime() >= IDLE_SECONDS)

    def apply(self, backup_function):
        if not self.ready():
            return False
        snapshot = Snapshot()
        m.HOME.setProperty('Family.Setup.InProgress', 'update')
        m.HOME.setProperty('Family.Update.State', 'applying')
        captured = False
        try:
            snapshot.capture()
            captured = True
            m.apply(backup_function, restart_service=False)
            m.write_json(self.state_path, {'target': self.target, 'status': 'applied',
                                          'applied': time.time(), 'backup': snapshot.path})
            m.HOME.clearProperty('Family.Update.Pending')
            m.HOME.setProperty('Family.Update.State', 'applied')
            xbmcgui.Dialog().notification('Rodinné kino', 'Vzhled a filmový doplněk byly aktualizovány.',
                                           time=4500, sound=False)
            return True
        except Exception as error:
            restored = False
            if captured:
                try:
                    snapshot.restore()
                    restored = True
                except Exception:
                    m.HOME.setProperty('Family.Update.State', 'restore_failed')
            previous = m.read_json(self.state_path)
            attempts = previous.get('attempts', 0) + 1 if previous.get('target') == self.target else 1
            m.write_json(self.state_path, {'target': self.target, 'status': 'error',
                'error': type(error).__name__, 'attempts': attempts, 'restored': restored,
                'retry_after': time.time() + min(900, 60 * 2 ** min(attempts - 1, 4)), 'backup': snapshot.path})
            m.HOME.setProperty('Family.Update.State', 'retry_pending' if restored or not captured else 'restore_failed')
            if attempts == 1:
                xbmcgui.Dialog().notification('Rodinné kino', 'Aktualizaci se nepodařilo dokončit. Zkusím ji znovu.',
                                               time=5000, sound=False)
            return False
        finally:
            m.HOME.clearProperty('Family.Service.Stop')
            m.HOME.clearProperty('Family.Setup.InProgress')
            xbmc.executebuiltin('RunScript(special://home/addons/script.michal.family.repair/service.py)')
