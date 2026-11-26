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
MIN_SKIN = (3, 5, 4)
JURIAL_REPO = 'repository.jurialmunkey'
YAWSP = 'plugin.video.yawsp'
TRAKT = 'script.trakt'
REPOSITORY_INSTALL_TIMEOUT = 180
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


def wait_for(check, timeout, pending=None):
    monitor = xbmc.Monitor()
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() >= deadline and not (pending and pending()):
            return None
        if monitor.waitForAbort(0.5):
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
    install_zip_data(addon, data, prefix, checksum)


def install_repository():
    addon = 'repository.rodinne.kino'
    if enable_installed(addon):
        return
    manifest = maintenance.read_json(os.path.join(maintenance.PATH, 'resources', 'manifest.json'))
    with open(os.path.join(maintenance.PATH, 'resources', 'repository.zip'), 'rb') as source:
        install_zip_data(addon, source.read(), addon, manifest['repository_sha256'])


def install_zip_data(addon, data, prefix, checksum):
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


def wait_for_repository_addon(addon):
    if available(addon):
        return
    notify('Načítám repozitáře Kodi…')
    xbmc.executebuiltin('UpdateAddonRepos')
    if not wait_for(lambda: available(addon), 45):
        raise RuntimeError('Repozitáře Kodi zatím nenabízejí ' + addon + '. Zkontroluj připojení a instalaci spusť znovu.')


def native_install_pending():
    return (xbmc.getCondVisibility('Window.IsVisible(yesnodialog)')
            or xbmc.getCondVisibility('Window.IsVisible(progressdialog)'))


def install_from_repo(addon):
    if enable_installed(addon):
        return
    wait_for_repository_addon(addon)
    name = 'Arctic Fuse 3' if addon == SKIN else addon
    notify('Pokud se Kodi zeptá, potvrď instalaci: ' + name)
    xbmc.executebuiltin('InstallAddon(' + addon + ')')
    # The built-in can return while Kodi is asking for confirmation or
    # installing dependencies. Kodi owns these dialogs and their timeouts.
    if not wait_for(lambda: enable_installed(addon), REPOSITORY_INSTALL_TIMEOUT, native_install_pending):
        raise RuntimeError('Kodi nedokončilo instalaci ' + name + '. '
                           'Při opakování potvrď jeho instalaci v Kodi.')


def focus_skin_confirmation():
    """Repair an unfocused native keep dialog without choosing its result."""
    if (xbmcgui.getCurrentWindowDialogId() != 10100
            or not xbmc.getCondVisibility('Window.IsDialogTopmost(yesnodialog)')):
        return False
    focus = xbmc.getInfoLabel('System.CurrentControlID')
    if focus not in ('', '0', '-1', '-200'):
        return True
    try:
        # HasFocus(10) can already report true while the dialog has no active
        # focused control. Set the native focus explicitly, as Kodi's settings
        # window does when it initiates the skin preview.
        xbmcgui.Window(10100).setFocusId(10)
    except RuntimeError:
        return False  # The new skin has not finished creating its controls.
    return True


def wait_for_skin_confirmation():
    monitor = xbmc.Monitor()
    deadline = time.monotonic() + 45
    settled_since = None
    confirmation_seen = False
    confirmation_focused = False
    while time.monotonic() < deadline:
        confirming = xbmc.getCondVisibility('Window.IsVisible(yesnodialog)')
        confirmation_seen = confirmation_seen or confirming
        selected = maintenance.rpc('Settings.GetSettingValue', {'setting': 'lookandfeel.skin'})['value']
        if confirmation_seen and not confirming and selected != SKIN:
            break
        if xbmc.getSkinDir() == SKIN:
            dismiss_skin_wizard()
            if confirming and not confirmation_focused:
                confirmation_focused = focus_skin_confirmation()
            # A progress dialog can cover the still-visible keep/revert
            # dialog. Never mistake that overlay for the user's confirmation.
            settled = (confirmation_seen and not confirming and selected == SKIN
                       and xbmcgui.getCurrentWindowDialogId() in (0, 9999))
            if settled:
                if settled_since is None:
                    settled_since = time.monotonic()
                if time.monotonic() - settled_since >= 2:
                    return
            else:
                settled_since = None
        elif confirmation_seen and not confirming:
            break
        if monitor.waitForAbort(.1):
            break
    raise RuntimeError('Potvrď Arctic Fuse 3 jako aktivní vzhled a znovu spusť instalaci.')


def dismiss_skin_wizard():
    if xbmc.getSkinDir() != SKIN:
        return
    xbmc.executebuiltin('CancelAlarm(setupwizardopen,true)', True)
    if xbmc.getCondVisibility('Skin.HasSetting(SetupWizard.Pending)'):
        xbmc.executebuiltin('Skin.Reset(SetupWizard.Pending)', True)
    if xbmc.getCondVisibility('Window.IsVisible(11130)'):
        xbmc.executebuiltin('Dialog.Close(11130,true)', True)


def defer_trakt_reminder():
    # A fresh Trakt service otherwise opens its account dialog while Kodi is
    # asking whether to keep the newly loaded skin. Accounts have their own
    # explicit entry in the family service menu after installation.
    path = os.path.join(maintenance.USER, 'addon_data', TRAKT, 'settings.xml')
    if os.path.isfile(path):
        tree = ET.parse(path)
        if tree.find('.//setting[@id="last_reminder"]') is not None:
            return
    else:
        tree = ET.ElementTree(ET.Element('settings', version='2'))
    ET.SubElement(tree.getroot(), 'setting', id='last_reminder').text = '-1'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + '.family-new'
    tree.write(temporary, encoding='utf-8', xml_declaration=True)
    os.replace(temporary, path)


def ensure_current_skin(changes):
    def compatible():
        version = addon_details(SKIN).get('version', '')
        parts = tuple(int(part) for part in re.findall(r'\d+', version)[:3])
        return parts >= MIN_SKIN
    if compatible():
        return
    maintenance.set_setting('general.addonupdates', 0, changes)
    maintenance.set_setting('addons.updatemode', 1, changes)
    install_upstream_zip(JURIAL_REPO)
    notify('Aktualizuji Arctic Fuse 3 a jeho součásti…')
    xbmc.executebuiltin('UpdateAddonRepos')
    if not wait_for(compatible, 180):
        raise RuntimeError('Rodinné kino potřebuje Arctic Fuse 3 alespoň 3.5.4. '
            'V Kodi otevři doplněk Arctic Fuse 3 → Verze, vyber novější vydání a znovu spusť instalátor. '
            'Nastavení nabídek zatím nebylo změněno.')
    dismiss_skin_wizard()


def prepare():
    maintenance.setup_preflight()
    previous_skin = xbmc.getSkinDir()
    path = os.path.join(maintenance.PROFILE, 'changes.json')
    changes = maintenance.read_json(path)
    if previous_skin != SKIN:
        changes.setdefault('previous_skin', previous_skin)
        maintenance.write_json(path, changes)
    install_repository()
    if not addon_details(SKIN):
        maintenance.set_setting('addons.updatemode', 1, changes)
        install_upstream_zip(JURIAL_REPO)
        # The Arctic repository can finish refreshing before Kodi's own
        # repository, which provides required dependencies for the skin.
        if not addon_details('script.module.requests'):
            wait_for_repository_addon('script.module.requests')
        install_from_repo(SKIN)
    else:
        enable_installed(SKIN)
    ensure_current_skin(changes)
    if not addon_details(YAWSP):
        for dependency in ('script.module.requests', 'script.module.unidecode'):
            install_from_repo(dependency)
    install_upstream_zip(YAWSP)
    if not addon_details(TRAKT):
        defer_trakt_reminder()
    install_from_repo(TRAKT)
    install_from_repo('resource.language.cs_cz')
    helper = addon_details('plugin.video.themoviedb.helper')
    version = helper.get('version', '')
    if tuple(int(part) for part in re.findall(r'\d+', version)[:2]) >= (6, 22):
        install_from_repo('script.module.tmdbhelper.sync.trakt')
    maintenance.setup_preflight()
    dismiss_skin_wizard()
    if xbmc.getSkinDir() != SKIN:
        maintenance.confirmation_skin_patch()
        notify('Potvrď změnu vzhledu na Arctic Fuse 3.')
        preview = 'Family.Setup.SkinPreview'
        maintenance.HOME.setProperty(preview, 'true')
        try:
            if not maintenance.rpc('Settings.SetSettingValue', {'setting': 'lookandfeel.skin', 'value': SKIN}):
                raise RuntimeError('Kodi nedokázalo přepnout na Arctic Fuse 3.')
            wait_for_skin_confirmation()
        finally:
            maintenance.HOME.clearProperty(preview)
        xbmc.executebuiltin('ActivateWindow(Home)', True)


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
    finally:
        maintenance.HOME.clearProperty(lock)
    from accounts import guide
    guide()
