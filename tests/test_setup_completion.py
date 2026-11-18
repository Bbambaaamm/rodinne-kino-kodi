"""First installation must expose navigation and guide missing account logins."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1] / 'addons'
SETUP = ROOT / 'script.michal.family.repair'
PROVIDER = ROOT / 'plugin.video.webshare.available'


class SetupCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.properties = {}
        self.settings = {}
        self.home = types.SimpleNamespace(
            getProperty=lambda key: self.properties.get(key, ''),
            setProperty=lambda key, value: self.properties.__setitem__(key, value),
            clearProperty=lambda key: self.properties.pop(key, None))
        def addon(name):
            return types.SimpleNamespace(getSetting=lambda key: self.settings.get(name, {}).get(key, ''),
                setSetting=lambda key, value: self.settings.setdefault(name, {}).__setitem__(key, value),
                openSettings=Mock(), getAddonInfo=lambda _: str(self.root))
        self.m = types.SimpleNamespace(PROFILE=str(self.root), USER=str(self.root), HOME=self.home,
            read_json=lambda path, fallback=None: json.loads(Path(path).read_text()) if Path(path).exists() else (fallback or {}),
            write_json=lambda path, data: Path(path).write_text(json.dumps(data)), local_path=os.path.normpath)
        self.xbmc = types.SimpleNamespace(executebuiltin=Mock(), getGlobalIdleTime=lambda: 20,
            Monitor=lambda: types.SimpleNamespace(waitForAbort=lambda _: False))
        self.dialog = Mock()
        self.gui = types.SimpleNamespace(Dialog=lambda: self.dialog, DialogProgress=Mock(),
                                         getCurrentWindowDialogId=lambda: 9999)
        self.addon_api = types.SimpleNamespace(Addon=addon)
        self.vfs = types.SimpleNamespace(translatePath=lambda path: path)
        with patch.dict(sys.modules, {'maintenance': self.m, 'xbmc': self.xbmc, 'xbmcgui': self.gui,
                                     'xbmcaddon': self.addon_api, 'xbmcvfs': self.vfs}):
            spec = importlib.util.spec_from_file_location('tested_accounts', SETUP / 'accounts.py')
            self.a = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.a)

    def connect(self):
        self.settings = {'plugin.video.yawsp': {'token': 'fixture-webshare'},
            'script.module.tmdbhelper.sync.trakt': {'token': '{"access_token":"fixture-lists"}'},
            'script.trakt': {'authorization': '{"access_token":"fixture-watched"}'}}

    def test_scrobbler_login_does_not_claim_personal_lists_are_connected(self):
        self.settings = {'script.trakt': {'authorization': '{"access_token":"fixture-watched"}'}}
        self.assertEqual(self.a.account_state(), {'webshare': False, 'lists': False, 'watched': True})

    def test_invalid_token_is_not_treated_as_connected(self):
        self.settings = {'script.module.tmdbhelper.sync.trakt': {'token': '[]'},
                         'script.trakt': {'authorization': 'broken'}}
        self.assertFalse(self.a.account_state()['lists'])
        self.assertFalse(self.a.account_state()['watched'])

    def test_idle_existing_install_gets_one_account_guide(self):
        self.a.offer_setup()
        self.a.next_offer = 0
        self.a.offer_setup()
        self.xbmc.executebuiltin.assert_called_once_with('RunScript(script.michal.family.repair,accounts)')
        self.assertFalse(self.m.read_json(self.a.STATE)['complete'])

    def test_busy_install_does_not_interrupt_user(self):
        self.properties['Family.Setup.InProgress'] = 'true'
        self.a.offer_setup()
        self.xbmc.executebuiltin.assert_not_called()
        self.assertFalse(Path(self.a.STATE).exists())

    def test_connected_accounts_do_not_show_guide(self):
        self.connect()
        self.a.offer_setup()
        self.xbmc.executebuiltin.assert_not_called()
        self.assertTrue(self.m.read_json(self.a.STATE)['complete'])

    def test_postponement_remains_incomplete_without_repeat_prompt(self):
        self.dialog.select.return_value = 3
        self.a.guide()
        self.a.offer_setup()
        self.assertFalse(self.m.read_json(self.a.STATE)['complete'])
        self.assertFalse(self.properties.get('Family.Accounts.Active'))
        self.xbmc.executebuiltin.assert_not_called()

    def test_completed_guide_saves_only_status_booleans(self):
        self.connect()
        self.dialog.select.return_value = 3
        self.a.guide()
        saved = Path(self.a.STATE).read_text()
        self.assertTrue(json.loads(saved)['complete'])
        self.assertNotIn('fixture-', saved)

    def test_login_invalidates_errors_and_requests_lists_again(self):
        key = 'Family.Paging.Display.Error.list_movie_playback'
        self.properties[key] = 'true'
        self.a.invalidate_lists()
        self.assertNotIn(key, self.properties)
        self.assertEqual(self.properties['Family.Paging.Display.Wanted.list_movie_playback'], '10')

    def test_webshare_login_uses_upstream_hashing_and_keeps_plain_password_out_of_request(self):
        crypt = types.SimpleNamespace(md5crypt=lambda *_: 'fixture-encrypted')
        spec = types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda _: None))
        results = [ET.fromstring('<response><status>OK</status><salt>fixture</salt></response>'),
                   ET.fromstring('<response><status>OK</status><token>fixture-token</token></response>')]
        with patch.object(self.a, 'api', side_effect=results) as api, \
                patch.object(self.a.importlib.util, 'spec_from_file_location', return_value=spec), \
                patch.object(self.a.importlib.util, 'module_from_spec', return_value=crypt):
            self.assertEqual(self.a.webshare_login('fixture-user', 'private-password'), 'fixture-token')
        self.assertEqual([call.args[0] for call in api.call_args_list], ['salt', 'login'])
        self.assertNotIn('private-password', repr(api.call_args_list))

    def test_webshare_success_requires_a_returned_token(self):
        with patch.object(self.a, 'api', return_value=ET.fromstring('<response><status>OK</status></response>')):
            with self.assertRaises(RuntimeError):
                self.a.webshare_login('fixture-user', 'private-password')

    def test_already_entered_webshare_credentials_finish_login_without_reopening_settings(self):
        self.settings = {'plugin.video.yawsp': {'wsuser': 'fixture-user', 'wspass': 'private-password'}}
        self.dialog.select.return_value = 3
        self.gui.DialogProgress.return_value.iscanceled.return_value = False
        with patch.object(self.a, 'webshare_login', return_value='fixture-token'):
            self.a.guide()
        self.assertEqual(self.settings['plugin.video.yawsp']['token'], 'fixture-token')
        self.assertTrue(self.m.read_json(self.a.STATE)['webshare'])
        self.assertNotIn('private-password', Path(self.a.STATE).read_text())

    def test_spotlight_account_card_opens_guide_without_trying_to_play_it(self):
        tree = ast.parse((SETUP / 'maintenance.py').read_text(encoding='utf8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'select_family']
        self.xbmc.getInfoLabel = lambda _: 'accounts'
        gui = types.SimpleNamespace(getCurrentWindowId=lambda: 10000, getCurrentWindowDialogId=lambda: 9999,
                                   Window=lambda _: types.SimpleNamespace(getFocusId=lambda: 311))
        env = {'xbmc': self.xbmc, 'xbmcgui': gui}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'maintenance.py', 'exec'), env)
        env['select_family']()
        self.xbmc.executebuiltin.assert_called_once_with('RunScript(script.michal.family.repair,accounts)')

    def test_hub_definition_enables_family_sections_without_replacing_other_hubs(self):
        folder = self.root / 'addon_data/script.skinvariables/nodes/skin.arctic.fuse.3'
        folder.mkdir(parents=True)
        path = folder / 'skinvariables-shortcut-hubs.json'
        before = [{'window': str(1100+i), 'disabled': 'True', 'guid': 'existing-' + str(i)} for i in (1, 2, 3)]
        before += [{'window': '1109', 'label': 'Unrelated', 'disabled': ''}]
        path.write_text(json.dumps(before))
        tree = ast.parse((SETUP / 'maintenance.py').read_text(encoding='utf8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'configure_family_hubs']
        env = vars(self.m).copy()
        env.update(os=os, xbmcvfs=self.vfs)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'maintenance.py', 'exec'), env)
        env['configure_family_hubs']()
        after = json.loads(path.read_text())
        self.assertEqual([(row['label'], row['disabled']) for row in after[:3]],
                         [('Filmy', ''), ('Seriály', ''), ('Moje', '')])
        self.assertEqual(after[0]['guid'], 'existing-1')
        self.assertEqual(after[-1], before[-1])

    def test_missing_accounts_are_identified_without_network_calls(self):
        tree = ast.parse((PROVIDER / 'family.py').read_text(encoding='utf8'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'missing_list_account']
        core = types.SimpleNamespace(trakt_token_candidates=lambda: [],
            get_webshare_token=Mock(side_effect=RuntimeError('missing token')))
        env = {'core': core}
        paging = types.SimpleNamespace(needs_availability=lambda value: not value['personal'])
        with patch.dict(sys.modules, {'paging': paging}):
            exec(compile(ast.Module(body=nodes, type_ignores=[]), 'family.py', 'exec'), env)
            self.assertEqual(env['missing_list_account']({'source': 'playback', 'personal': False}), 'Trakt')
            self.assertEqual(env['missing_list_account']({'source': 'popular', 'personal': False}), 'Webshare')
            core.trakt_token_candidates = lambda: [{'access_token': 'fixture'}]
            self.assertEqual(env['missing_list_account']({'source': 'history', 'personal': True}), '')


if __name__ == '__main__':
    unittest.main()
