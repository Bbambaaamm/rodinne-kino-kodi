"""Install the upstream components needed by the portable family setup."""
import hashlib
import io
import os
import re
import stat
import tempfile
import time
from pathlib import PurePosixPath
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

import xbmc
import xbmcgui

import maintenance


SKIN = 'skin.arctic.fuse.3'
JURIAL_REPO = 'repository.jurialmunkey'
YAWSP = 'plugin.video.yawsp'
TRAKT = 'script.trakt'
UPSTREAM_ZIPS = {
    JURIAL_REPO: (
        'https://jurialmunkey.github.io/repository.jurialmunkey/repository.jurialmunkey-3.6.zip',
        '298de6380d823e0879541e308fa78a6f0a21b6f399204150dbaf7f942e1b728d',
        'repository.jurialmunkey',
    ),
    YAWSP: (
        'https://raw.githubusercontent.com/Webshare/Web/9b635adc5503ecb0230008025fc81348454faa62/plugin.video.yawsp-master.zip',
        '8189ceaa8d3021482956b60d107b405201a0a5001facd3035cbe011ad238d596',
        'plugin.video.yawsp-master',
    ),
}


def addon_details(addon):
    try:
        return maintenance.rpc('Addons.GetAddonDetails', {
            'addonid': addon, 'properties': ['enabled', 'version'],
        })['addon']
    except RuntimeError:
        return {}


def wait_for(check, timeout):
    monitor = xbmc.Monitor()
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() >= deadline or monitor.waitForAbort(0.5):
            return None


def enable_installed(addon):
    details = addon_details(addon)
    if not details:
        return False
    if not details.get('enabled'):
        maintenance.rpc('Addons.SetAddonEnabled', {'addonid': addon, 'enabled': True})
        if not wait_for(lambda: addon_details(addon).get('enabled'), 10):
            raise RuntimeError('Kodi nedokázalo zapnout doplněk ' + addon + '.')
    return True


def notify(text):
    xbmcgui.Dialog().notification('Rodinné kino', text, time=4500, sound=False)


def install_upstream_zip(addon):
    if enable_installed(addon):
        return
    url, checksum, prefix = UPSTREAM_ZIPS[addon]
    notify('Stahuji ' + addon)
    try:
        request = Request(url, headers={'User-Agent': 'Rodinne-kino-Kodi'})
        with urlopen(request, timeout=20) as response:
            data = response.read(512 * 1024 + 1)
    except OSError as error:
        raise RuntimeError('Stažení doplňku ' + addon + ' selhalo. Zkontroluj připojení a spusť instalaci znovu.') from error
    if hashlib.sha256(data).hexdigest() != checksum:
        raise RuntimeError('Zdrojový ZIP se změnil. Ověř aktuální vydání doplňku ' + addon + '.')

    addons = os.path.join(maintenance.HOME_PATH, 'addons')
    target = os.path.join(addons, addon)
    if os.path.lexists(target):
        raise RuntimeError('Kodi má složku doplňku ' + addon + ', ale doplněk nenašlo. Restartuj Kodi a zkus to znovu.')
    with tempfile.TemporaryDirectory(prefix='.family-install-', dir=addons) as staging:
        try:
            with ZipFile(io.BytesIO(data)) as archive:
                manifest = ET.fromstring(archive.read(prefix + '/addon.xml'))
                if manifest.get('id') != addon:
                    raise RuntimeError('Zdrojový ZIP obsahuje jiný doplněk než ' + addon + '.')
                for entry in archive.infolist():
                    path = PurePosixPath(entry.filename)
                    if (not path.parts or path.parts[0] != prefix or '..' in path.parts
                            or '\\' in entry.filename or ':' in entry.filename
                            or stat.S_ISLNK(entry.external_attr >> 16)):
                        raise RuntimeError('Neočekávaná cesta ve zdrojovém ZIPu doplňku ' + addon + '.')
                archive.extractall(staging)
        except (BadZipFile, ET.ParseError, KeyError) as error:
            raise RuntimeError('Zdrojový ZIP doplňku ' + addon + ' nelze přečíst.') from error
        os.rename(os.path.join(staging, prefix), target)
        xbmc.executebuiltin('UpdateLocalAddons', True)
        if not wait_for(lambda: addon_details(addon), 15):
            # Keep the previous profile usable and allow the next run to retry.
            os.rename(target, os.path.join(staging, prefix))
            xbmc.executebuiltin('UpdateLocalAddons', True)
            raise RuntimeError('Kodi nenalezlo nainstalovaný doplněk ' + addon + '.')
    enable_installed(addon)


def available(addon):
    result = maintenance.rpc('Addons.GetAddons', {'installed': False, 'enabled': 'all'})
    return any(item['addonid'] == addon for item in result.get('addons', []))


def install_from_repo(addon):
    if enable_installed(addon):
        return
    if not available(addon):
        notify('Načítám repozitáře Kodi…')
        xbmc.executebuiltin('UpdateAddonRepos')
        if not wait_for(lambda: available(addon), 45):
            raise RuntimeError('Repozitáře Kodi zatím nenabízejí ' + addon + '. Zkontroluj připojení a instalaci spusť znovu.')
    notify('Připravuji ' + addon)
    xbmc.executebuiltin('InstallAddon(' + addon + ')', True)
    if not enable_installed(addon):
        raise RuntimeError('Kodi nedokončilo instalaci ' + addon + '. Při opakování potvrď jeho instalaci v Kodi.')


def prepare():
    maintenance.setup_preflight()
    previous_skin = xbmc.getSkinDir()
    path = os.path.join(maintenance.PROFILE, 'changes.json')
    changes = maintenance.read_json(path)
    if previous_skin != SKIN:
        changes.setdefault('previous_skin', previous_skin)
        maintenance.write_json(path, changes)
    if not addon_details(SKIN):
        maintenance.set_setting('addons.updatemode', 1, changes)
        install_upstream_zip(JURIAL_REPO)
        install_from_repo(SKIN)
    else:
        enable_installed(SKIN)
    if not addon_details(YAWSP):
        for dependency in ('script.module.requests', 'script.module.unidecode'):
            install_from_repo(dependency)
    install_upstream_zip(YAWSP)
    install_from_repo(TRAKT)
    install_from_repo('resource.language.cs_cz')
    helper = addon_details('plugin.video.themoviedb.helper')
    version = helper.get('version', '')
    if tuple(int(part) for part in re.findall(r'\d+', version)[:2]) >= (6, 22):
        install_from_repo('script.module.tmdbhelper.sync.trakt')
    maintenance.setup_preflight()
    if xbmc.getSkinDir() != SKIN:
        notify('Potvrď změnu vzhledu na Arctic Fuse 3.')
        if not maintenance.rpc('Settings.SetSettingValue', {'setting': 'lookandfeel.skin', 'value': SKIN}):
            raise RuntimeError('Kodi nedokázalo přepnout na Arctic Fuse 3.')
        # Kodi activates the skin before asking whether to keep it. The native
        # confirmation is processed before this blocking GUI action returns.
        xbmc.executebuiltin('ActivateWindow(Home)', True)
        if not wait_for(lambda: xbmc.getSkinDir() == SKIN and
                        not xbmc.getCondVisibility('Window.IsActive(yesnodialog)'), 20):
            raise RuntimeError('Potvrď Arctic Fuse 3 jako aktivní vzhled a znovu spusť instalaci.')


def install(backup_function):
    lock = 'Family.Setup.InProgress'
    if maintenance.HOME.getProperty(lock):
        return
    maintenance.HOME.setProperty(lock, 'true')
    try:
        prepare()
        progress = xbmcgui.DialogProgressBG()
        progress.create('Rodinné kino', 'Nastavuji nabídky a ovládání…')
        try:
            maintenance.apply(backup_function)
        finally:
            progress.close()
        changes = maintenance.read_json(os.path.join(maintenance.PROFILE, 'changes.json'))
        maintenance.set_setting('locale.language', 'resource.language.cs_cz', changes)
        xbmc.executebuiltin('ActivateWindow(Home)')
        notify('Hotovo. Trakt a Webshare připojíš v nabídce Moje → Servis.')
    finally:
        maintenance.HOME.clearProperty(lock)
