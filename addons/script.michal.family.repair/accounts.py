"""Finish account setup locally, without exporting or copying credentials."""
import hashlib
import importlib.util
import json
import os
import queue
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
import maintenance as m


STATE = os.path.join(m.PROFILE, 'accounts.json')
HOME_LISTS = (('movie', 'playback'), ('episode', 'playback'), ('episode', 'next'),
              ('movie', 'recommendations'), ('tv', 'recommendations'))
next_offer = 0


def setting(addon, name):
    try:
        return xbmcaddon.Addon(addon).getSetting(name)
    except RuntimeError:
        return ''


def has_token(raw):
    try:
        return bool(json.loads(raw or '{}').get('access_token'))
    except (ValueError, AttributeError):
        return False


def account_state():
    return {'webshare': bool(setting('plugin.video.yawsp', 'token')),
            'lists': any(has_token(raw) for raw in (
                setting('script.module.tmdbhelper.sync.trakt', 'token'),
                setting('plugin.video.themoviedb.helper', 'trakt_token'),
                m.HOME.getProperty('TraktUserToken'))),
            'watched': has_token(setting('script.trakt', 'authorization'))}


def invalidate_lists():
    stamp = str(time.time())
    m.HOME.setProperty('Family.Accounts.Changed', stamp)
    m.HOME.setProperty('Family.Paging.Revision', stamp)
    m.HOME.clearProperty('Family.TraktValidated')
    for kind, source in HOME_LISTS:
        base = 'Family.Paging.Display.'
        key = 'list_' + kind + '_' + source
        m.HOME.setProperty('Family.Paging.Count.' + key, '20')
        m.HOME.clearProperty(base + 'Error.' + key)
        m.HOME.setProperty(base + 'Wanted.' + key, '20')
        m.HOME.setProperty(base + 'Version.' + key, stamp)


def api(action, values):
    request = Request('https://webshare.cz/api/' + action + '/',
                      data=urlencode(values).encode('utf8'),
                      headers={'Content-Type': 'application/x-www-form-urlencoded',
                               'User-Agent': 'Kodi Rodinne kino'})
    with urlopen(request, timeout=12) as response:
        result = ET.fromstring(response.read())
    if result.findtext('status') != 'OK':
        raise RuntimeError('Webshare odmítlo přihlášení. Zkontroluj jméno a heslo.')
    return result


def webshare_login(username, password):
    salt = api('salt', {'username_or_email': username}).findtext('salt')
    if not salt:
        raise RuntimeError('Webshare nevrátilo údaje pro přihlášení.')
    addon = xbmcaddon.Addon('plugin.video.yawsp')
    source = m.local_path(xbmcvfs.translatePath(addon.getAddonInfo('path')))
    spec = importlib.util.spec_from_file_location('family_ws_crypt', os.path.join(source, 'md5crypt.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    encrypted = module.md5crypt(password.encode('utf8'), salt.encode('utf8'))
    if isinstance(encrypted, str):
        encrypted = encrypted.encode('utf8')
    encrypted = hashlib.sha1(encrypted).hexdigest()
    digest = hashlib.md5((username + ':Webshare:' + encrypted).encode('utf8')).hexdigest()
    result = api('login', {'username_or_email': username, 'password': encrypted,
                           'digest': digest, 'keep_logged_in': 1})
    token = result.findtext('token')
    if not token:
        raise RuntimeError('Webshare nevrátilo potvrzení přihlášení.')
    return token


def webshare_credentials(addon):
    # Literal headings also work immediately after installation, before Kodi
    # has loaded another add-on's settings translations into its cache.
    keyboard = xbmc.Keyboard(addon.getSetting('wsuser'),
                             'Webshare – uživatelské jméno nebo e-mail')
    keyboard.doModal()
    if not keyboard.isConfirmed():
        return None
    username = keyboard.getText().strip()
    if not username:
        xbmcgui.Dialog().ok('Webshare', 'Zadej uživatelské jméno nebo e-mail.')
        return None
    keyboard = xbmc.Keyboard('', 'Webshare – heslo', True)
    keyboard.doModal()
    if not keyboard.isConfirmed():
        return None
    password = keyboard.getText()
    if not password:
        xbmcgui.Dialog().ok('Webshare', 'Zadej heslo ke svému účtu Webshare.')
        return None
    return username, password


def connect_webshare(prompt=True):
    addon = xbmcaddon.Addon('plugin.video.yawsp')
    if prompt:
        credentials = webshare_credentials(addon)
        if credentials is None:
            return
        username, password = credentials
    else:
        username, password = addon.getSetting('wsuser'), addon.getSetting('wspass')
    if not username or not password:
        return
    results = queue.Queue(1)
    def run():
        try:
            results.put((True, webshare_login(username, password)))
        except Exception:
            results.put((False, None))
    threading.Thread(target=run, daemon=True).start()
    dialog = xbmcgui.DialogProgress()
    dialog.create('Připojení Webshare', 'Ověřuji přihlášení…')
    monitor = xbmc.Monitor()
    deadline = time.monotonic() + 35
    try:
        while time.monotonic() < deadline and not dialog.iscanceled():
            try:
                ok, token = results.get_nowait()
                if ok:
                    if prompt:
                        addon.setSetting('wsuser', username)
                        addon.setSetting('wspass', password)
                    addon.setSetting('token', token)
                    invalidate_lists()
                    if prompt:
                        xbmcgui.Dialog().notification('Webshare', 'Přihlášení bylo dokončeno.')
                else:
                    xbmcgui.Dialog().ok('Webshare', 'Přihlášení se nepodařilo. Ověř jméno, heslo a připojení k internetu.')
                return
            except queue.Empty:
                if monitor.waitForAbort(.1):
                    return
    finally:
        dialog.close()


def connect_trakt(watched=False):
    addon = 'script.trakt' if watched else 'script.module.tmdbhelper.sync.trakt'
    try:
        xbmcaddon.Addon(addon)
    except RuntimeError:
        xbmcaddon.Addon('plugin.video.themoviedb.helper').openSettings()
        return
    action = 'auth_info' if watched else 'authenticate'
    xbmc.executebuiltin('RunScript(' + addon + ',action=' + action + ')')
    monitor = xbmc.Monitor()
    started = time.monotonic()
    seen_dialog = False
    while time.monotonic() - started < 300:
        if account_state()['watched' if watched else 'lists']:
            invalidate_lists()
            return
        visible = xbmcgui.getCurrentWindowDialogId() not in (0, 9999)
        seen_dialog = seen_dialog or visible
        if not visible and (seen_dialog or time.monotonic() - started > 12):
            return
        if monitor.waitForAbort(.2):
            return


def guide():
    if m.HOME.getProperty('Family.Accounts.Active'):
        return
    m.HOME.setProperty('Family.Accounts.Active', 'true')
    previous = m.HOME.getProperty('Family.Accounts.Changed')
    try:
        if (not account_state()['webshare'] and setting('plugin.video.yawsp', 'wsuser')
                and setting('plugin.video.yawsp', 'wspass')):
            connect_webshare(prompt=False)
        while True:
            state = account_state()
            m.write_json(STATE, {'prompted': True, 'complete': all(state.values()), **state})
            rows = [label + ('  ·  připojeno' if state[key] else '  ·  připojit') for key, label in (
                ('webshare', 'Webshare – přehrávání'), ('lists', 'Trakt – osobní seznamy'),
                ('watched', 'Trakt – ukládání zhlédnutí'))]
            rows.append('Dokončit' if all(state.values()) else 'Dokončit přihlášení později')
            choice = xbmcgui.Dialog().select('Dokončení Rodinného kina', rows,
                preselect=next((i for i, key in enumerate(('webshare', 'lists', 'watched')) if not state[key]), 3))
            if choice == 0:
                connect_webshare()
            elif choice in (1, 2):
                if state['watched' if choice == 2 else 'lists']:
                    xbmcgui.Dialog().ok('Trakt', 'Toto připojení už je nastavené.')
                else:
                    connect_trakt(choice == 2)
            else:
                break
    finally:
        m.HOME.clearProperty('Family.Accounts.Active')
        if m.HOME.getProperty('Family.Accounts.Changed') != previous:
            xbmc.executebuiltin('ReloadSkin()')


def offer_setup():
    global next_offer
    if time.monotonic() < next_offer:
        return
    next_offer = time.monotonic() + 5
    if (m.HOME.getProperty('Family.Setup.InProgress') or m.HOME.getProperty('Family.Accounts.Active')
            or m.read_json(STATE).get('prompted') or xbmc.getGlobalIdleTime() < 15):
        return
    state = account_state()
    m.write_json(STATE, {'prompted': True, 'complete': all(state.values()), **state})
    if not all(state.values()):
        xbmc.executebuiltin('RunScript(script.michal.family.repair,accounts)')
