"""Entry point for the Kodi setup menu and its skin and remote actions."""
import os
import shutil
import sys
from datetime import datetime

import xbmcaddon
import xbmcgui
import xbmcvfs

import maintenance


def backup():
    profile = maintenance.PROFILE
    pointer = os.path.join(profile, 'baseline.json')
    saved = maintenance.read_json(pointer)
    if os.path.isdir(saved.get('path', '')):
        return saved

    destination = os.path.join(profile, 'backups', datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    os.makedirs(destination)
    user = maintenance.USER
    saved_paths = (
        ('userdata/keymaps', os.path.join(user, 'keymaps')),
        ('userdata/addon_data/script.skinvariables/nodes/skin.arctic.fuse.3',
         os.path.join(user, 'addon_data', 'script.skinvariables', 'nodes', 'skin.arctic.fuse.3')),
        ('userdata/addon_data/plugin.video.themoviedb.helper/reconfigured_players/family.webshare.json',
         os.path.join(user, 'addon_data', 'plugin.video.themoviedb.helper', 'reconfigured_players', 'family.webshare.json')),
        ('addons/' + maintenance.PROVIDER, os.path.join(maintenance.HOME_PATH, 'addons', maintenance.PROVIDER)),
        ('skin.arctic.fuse.3', maintenance.local_path(xbmcvfs.translatePath('special://skin/'))),
    )
    for relative, source in saved_paths:
        target = maintenance.local_path(os.path.join(destination, relative))
        if os.path.isdir(source):
            maintenance.copy_tree(source, target)
        elif os.path.isfile(source):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(source, target)
    result = {'path': destination}
    maintenance.write_json(pointer, result)
    return result


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'menu'
    actions = {
        'menu': lambda: maintenance.menu(backup),
        'back': maintenance.back,
        'back_playback': maintenance.back_playback,
        'select_family': maintenance.select_family,
        'search_entry': maintenance.search_entry,
        'capture': lambda: maintenance.capture(sys.argv[2] if len(sys.argv) > 2 else ''),
    }
    if mode not in actions:
        return
    try:
        actions[mode]()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        maintenance.status('error', error=type(error).__name__)
        if mode == 'menu':
            maintenance.HOME.setProperty('FamilyRepair.Error', str(error))
            maintenance.HOME.clearProperty('Family.Service.Stop')
            xbmcgui.Dialog().ok(xbmcaddon.Addon().getAddonInfo('name'), str(error))


if __name__ == '__main__':
    main()
