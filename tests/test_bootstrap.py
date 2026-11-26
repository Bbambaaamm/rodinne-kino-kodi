"""Regressions for installing on an empty or partially configured Kodi profile."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile


SOURCE = Path(__file__).resolve().parents[1] / 'addons/script.michal.family.repair/bootstrap.py'


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'addons').mkdir()
        self.installed = {}
        self.settings = {}
        self.skin = 'skin.estuary'
        self.properties = {}
        self.home = types.SimpleNamespace(
            getProperty=lambda key: self.properties.get(key, ''),
            setProperty=lambda key, value: self.properties.__setitem__(key, value),
            clearProperty=lambda key: self.properties.pop(key, None),
        )
        self.maintenance = types.SimpleNamespace(
            HOME_PATH=str(self.root), PROFILE=str(self.root), USER=str(self.root / 'userdata'), HOME=self.home,
            rpc=Mock(side_effect=self.rpc), read_json=self.read_json,
            write_json=lambda path, data: Path(path).write_text(json.dumps(data)),
            set_setting=Mock(), setup_preflight=Mock(), apply=Mock(), confirmation_skin_patch=Mock(),
        )
        self.xbmc = types.SimpleNamespace(
            getSkinDir=lambda: self.skin, getCondVisibility=lambda _: False,
            executebuiltin=Mock(side_effect=self.builtin),
            Monitor=lambda: types.SimpleNamespace(waitForAbort=lambda _: True),
        )
        self.dialog = Mock()
        modules = {'maintenance': self.maintenance, 'xbmc': self.xbmc,
                   'xbmcgui': types.SimpleNamespace(Dialog=lambda: self.dialog,
                                                   getCurrentWindowDialogId=lambda: 9999)}
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('tested_bootstrap', SOURCE)
            self.setup = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.setup)
        self.setup.install_repository = Mock()
        self.accounts = types.SimpleNamespace(guide=Mock())
        self.account_modules = patch.dict(sys.modules, {'accounts': self.accounts})
        self.account_modules.start()
        self.addCleanup(self.account_modules.stop)

    def read_json(self, path):
        return json.loads(Path(path).read_text()) if Path(path).exists() else {}

    def rpc(self, method, params):
        addon = params.get('addonid')
        if method == 'Addons.GetAddonDetails':
            if addon not in self.installed:
                raise RuntimeError('Not installed')
            return {'addon': dict(self.installed[addon])}
        if method == 'Addons.SetAddonEnabled':
            self.installed[addon]['enabled'] = params['enabled']
            return 'OK'
        if method == 'Addons.GetAddons':
            return {'addons': [{'addonid': 'script.trakt'}]}
        if method == 'Settings.SetSettingValue':
            self.settings[params['setting']] = params['value']
            self.skin = params['value']
            return True
        if method == 'Settings.GetSettingValue':
            return {'value': self.settings.get(params['setting'], self.skin)}
        raise AssertionError(method)

    def builtin(self, command, wait=False):
        if command == 'UpdateLocalAddons':
            for path in (self.root / 'addons').glob('*/addon.xml'):
                self.installed[path.parent.name] = {'enabled': False, 'version': '1.0.0'}
        if command == 'InstallAddon(script.trakt)':
            self.installed['script.trakt'] = {'enabled': True, 'version': '3.9.0'}

    def archive(self, name='repository.jurialmunkey/addon.xml', addon=None):
        buffer = io.BytesIO()
        with ZipFile(buffer, 'w') as archive:
            archive.writestr(name, '<addon id="' + (addon or self.setup.JURIAL_REPO) + '"/>')
        data = buffer.getvalue()
        self.setup.UPSTREAM_ZIPS[self.setup.JURIAL_REPO] = (
            'https://example.org/addon.zip', hashlib.sha256(data).hexdigest(), 'repository.jurialmunkey')
        return data

    def test_existing_disabled_component_is_enabled_without_download(self):
        self.installed[self.setup.JURIAL_REPO] = {'enabled': False}
        with patch.object(self.setup, 'urlopen') as download:
            self.setup.install_upstream_zip(self.setup.JURIAL_REPO)
        download.assert_not_called()
        self.assertTrue(self.installed[self.setup.JURIAL_REPO]['enabled'])

    def test_upstream_component_registers_and_enables(self):
        data = self.archive()
        with patch.object(self.setup, 'urlopen', return_value=io.BytesIO(data)):
            self.setup.install_upstream_zip(self.setup.JURIAL_REPO)
        self.assertTrue(self.installed[self.setup.JURIAL_REPO]['enabled'])

    def test_changed_download_is_rejected_before_writing(self):
        self.archive()
        with patch.object(self.setup, 'urlopen', return_value=io.BytesIO(b'changed')):
            with self.assertRaises(RuntimeError):
                self.setup.install_upstream_zip(self.setup.JURIAL_REPO)
        self.assertEqual(list((self.root / 'addons').iterdir()), [])

    def test_wrong_addon_is_rejected_before_writing(self):
        data = self.archive(addon='other.addon')
        with patch.object(self.setup, 'urlopen', return_value=io.BytesIO(data)):
            with self.assertRaises(RuntimeError):
                self.setup.install_upstream_zip(self.setup.JURIAL_REPO)
        self.assertEqual(list((self.root / 'addons').iterdir()), [])

    def test_archive_traversal_is_rejected(self):
        data = self.archive()
        buffer = io.BytesIO(data)
        with ZipFile(buffer, 'a') as archive:
            archive.writestr('repository.jurialmunkey/../../outside.txt', 'invalid')
        data = buffer.getvalue()
        url, _, prefix = self.setup.UPSTREAM_ZIPS[self.setup.JURIAL_REPO]
        self.setup.UPSTREAM_ZIPS[self.setup.JURIAL_REPO] = url, hashlib.sha256(data).hexdigest(), prefix
        with patch.object(self.setup, 'urlopen', return_value=io.BytesIO(data)):
            with self.assertRaises(RuntimeError):
                self.setup.install_upstream_zip(self.setup.JURIAL_REPO)
        self.assertFalse((self.root / 'outside.txt').exists())

    def test_unregistered_folder_is_preserved(self):
        folder = self.root / 'addons' / self.setup.JURIAL_REPO
        folder.mkdir()
        (folder / 'previous.txt').write_text('preserved')
        data = self.archive()
        with patch.object(self.setup, 'urlopen', return_value=io.BytesIO(data)):
            with self.assertRaises(RuntimeError):
                self.setup.install_upstream_zip(self.setup.JURIAL_REPO)
        self.assertEqual((folder / 'previous.txt').read_text(), 'preserved')

    def test_failed_registration_allows_retry(self):
        data = self.archive()
        self.xbmc.executebuiltin.side_effect = None
        with patch.object(self.setup, 'urlopen', return_value=io.BytesIO(data)):
            with self.assertRaises(RuntimeError):
                self.setup.install_upstream_zip(self.setup.JURIAL_REPO)
        self.assertEqual(list((self.root / 'addons').iterdir()), [])

    def test_native_repository_installer_completes(self):
        self.setup.install_from_repo('script.trakt')
        self.assertTrue(self.installed['script.trakt']['enabled'])
        self.xbmc.executebuiltin.assert_called_with('InstallAddon(script.trakt)')

    def test_native_install_waits_for_confirmation_and_skin_registration(self):
        skin = self.setup.SKIN
        self.setup.available = Mock(return_value=True)
        elapsed = [0]
        def wait(seconds):
            elapsed[0] += seconds
            # The user confirms at 6s, and Kodi publishes the add-on only
            # after its dependencies have finished downloading.
            if elapsed[0] == 21:
                self.installed[skin] = {'enabled': False, 'version': '3.5.10'}
            return False
        self.xbmc.Monitor = lambda: types.SimpleNamespace(waitForAbort=wait)
        with patch.object(self.setup.time, 'monotonic', side_effect=lambda: elapsed[0]):
            self.setup.install_from_repo(skin)
        self.assertGreaterEqual(elapsed[0], 21)
        self.assertTrue(self.installed[skin]['enabled'])
        self.xbmc.executebuiltin.assert_called_once_with('InstallAddon(' + skin + ')')

    def test_native_install_that_never_registers_has_a_bounded_wait(self):
        self.setup.available = Mock(return_value=True)
        elapsed = [0]
        self.xbmc.Monitor = lambda: types.SimpleNamespace(
            waitForAbort=lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds) or False)
        with patch.object(self.setup.time, 'monotonic', side_effect=lambda: elapsed[0]):
            with self.assertRaisesRegex(RuntimeError, 'Arctic Fuse 3'):
                self.setup.install_from_repo(self.setup.SKIN)
        self.assertEqual(elapsed[0], self.setup.REPOSITORY_INSTALL_TIMEOUT)

    def test_slow_native_download_can_finish_after_registration_deadline(self):
        skin = self.setup.SKIN
        self.setup.available = Mock(return_value=True)
        elapsed = [0]
        complete_at = self.setup.REPOSITORY_INSTALL_TIMEOUT + 10
        self.xbmc.getCondVisibility = lambda condition: (
            condition == 'Window.IsVisible(progressdialog)' and elapsed[0] < complete_at)

        def wait(seconds):
            elapsed[0] += seconds
            if elapsed[0] == complete_at:
                self.installed[skin] = {'enabled': True, 'version': '3.5.10'}
            return False

        self.xbmc.Monitor = lambda: types.SimpleNamespace(waitForAbort=wait)
        with patch.object(self.setup.time, 'monotonic', side_effect=lambda: elapsed[0]):
            self.setup.install_from_repo(skin)
        self.assertEqual(elapsed[0], complete_at)

    def test_declined_native_install_stops_with_retry_message(self):
        self.xbmc.executebuiltin.side_effect = None
        with self.assertRaises(RuntimeError):
            self.setup.install_from_repo('script.trakt')

    def test_fresh_prepare_installs_all_components_and_switches_skin(self):
        catalog_ready = False

        def wait_for_catalog(addon):
            nonlocal catalog_ready
            self.assertEqual(addon, 'script.module.requests')
            catalog_ready = True

        def install(addon):
            self.installed[addon] = {'enabled': True, 'version': '1.0.0'}
            if addon == self.setup.SKIN:
                self.assertTrue(catalog_ready)
                self.installed[addon]['version'] = '3.5.4'
                self.installed['plugin.video.themoviedb.helper'] = {'version': '6.22.4', 'enabled': True}
        def confirm_preview():
            self.assertEqual(self.properties['Family.Setup.SkinPreview'], 'true')

        with patch.object(self.setup, 'install_from_repo', side_effect=install) as repo:
            with patch.object(self.setup, 'install_upstream_zip', side_effect=install):
                with patch.object(self.setup, 'wait_for_repository_addon', side_effect=wait_for_catalog):
                    with patch.object(self.setup, 'wait_for_skin_confirmation', side_effect=confirm_preview) as confirmation:
                        self.setup.prepare()
        confirmation.assert_called_once()
        self.assertNotIn('Family.Setup.SkinPreview', self.properties)
        self.maintenance.confirmation_skin_patch.assert_called_once_with()
        self.assertEqual(self.skin, self.setup.SKIN)
        self.assertIn('resource.language.cs_cz', [call.args[0] for call in repo.call_args_list])
        self.assertIn('script.module.tmdbhelper.sync.trakt', self.installed)
        self.assertEqual(self.read_json(self.root / 'changes.json')['previous_skin'], 'skin.estuary')

    def test_preflight_failure_prevents_install(self):
        self.maintenance.setup_preflight.side_effect = RuntimeError('Video is active')
        with patch.object(self.setup, 'install_upstream_zip') as install:
            with self.assertRaises(RuntimeError):
                self.setup.prepare()
        install.assert_not_called()

    def test_install_failure_releases_lock_for_retry(self):
        with patch.object(self.setup, 'prepare', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                self.setup.install(Mock())
        self.assertFalse(self.home.getProperty('Family.Setup.InProgress'))
        self.maintenance.apply.assert_not_called()

    def test_install_success_applies_current_setup_and_czech_language(self):
        self.setup.xbmcgui.DialogProgressBG = Mock()
        backup = Mock()
        with patch.object(self.setup, 'prepare'):
            self.setup.install(backup)
        self.maintenance.apply.assert_called_once_with(backup)
        self.maintenance.set_setting.assert_called_once_with('locale.language', 'resource.language.cs_cz', {})
        self.assertFalse(self.home.getProperty('Family.Setup.InProgress'))
        self.setup.xbmcgui.DialogProgressBG.return_value.close.assert_called_once()
        self.accounts.guide.assert_called_once()

    def test_existing_skin_does_not_trigger_download_or_language_switch_during_prepare(self):
        self.skin = self.setup.SKIN
        self.installed[self.setup.SKIN] = {'enabled': True, 'version': '3.5.4'}
        self.installed[self.setup.YAWSP] = {'enabled': True, 'version': '0.3.0'}
        with patch.object(self.setup, 'install_from_repo'):
            with patch.object(self.setup, 'urlopen') as download:
                self.setup.prepare()
        download.assert_not_called()
        self.assertEqual(self.settings, {})

    def test_old_skin_refreshes_repositories_and_waits_before_setting_up_menus(self):
        self.installed[self.setup.SKIN] = {'enabled': True, 'version': '3.3.8'}
        original = self.builtin
        def update(command, wait=False):
            if command == 'UpdateAddonRepos':
                self.installed[self.setup.SKIN]['version'] = '3.5.6'
            original(command, wait)
        self.xbmc.executebuiltin.side_effect = update
        with patch.object(self.setup, 'install_upstream_zip'):
            self.setup.ensure_current_skin({})
        self.assertIn('UpdateAddonRepos', [call.args[0] for call in self.xbmc.executebuiltin.call_args_list])
        self.maintenance.set_setting.assert_any_call('general.addonupdates', 0, {})

    def test_unavailable_skin_update_stops_before_modifying_family_layout(self):
        self.installed[self.setup.SKIN] = {'enabled': True, 'version': '3.3.8'}
        with patch.object(self.setup, 'install_upstream_zip'):
            with self.assertRaisesRegex(RuntimeError, '3.5.4'):
                self.setup.ensure_current_skin({})
        self.maintenance.apply.assert_not_called()

    def test_skin_confirmation_waits_for_late_dialog(self):
        clock = [0.0]
        def wait(seconds):
            clock[0] += seconds
            return False
        self.xbmc.Monitor = lambda: types.SimpleNamespace(waitForAbort=wait)
        self.skin = self.setup.SKIN
        self.xbmc.getCondVisibility = lambda _: 0.5 < clock[0] < 3
        with patch.object(self.setup.time, 'monotonic', side_effect=lambda: clock[0]):
            self.setup.wait_for_skin_confirmation()
        self.assertGreaterEqual(clock[0], 3)

    def test_rejected_skin_confirmation_stops_installation(self):
        clock = [0.0]
        def wait(seconds):
            clock[0] += seconds
            if clock[0] >= 2:
                self.skin = 'skin.estuary'
            return False
        self.skin = self.setup.SKIN
        self.xbmc.Monitor = lambda: types.SimpleNamespace(waitForAbort=wait)
        self.xbmc.getCondVisibility = lambda _: clock[0] < 2
        with patch.object(self.setup.time, 'monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(RuntimeError):
                self.setup.wait_for_skin_confirmation()

    def test_confirmation_covered_by_progress_dialog_is_still_pending(self):
        clock = [0.0]
        def wait(seconds):
            clock[0] += seconds
            return False
        self.skin = self.setup.SKIN
        self.xbmc.Monitor = lambda: types.SimpleNamespace(waitForAbort=wait)
        self.xbmc.getCondVisibility = lambda condition: (condition == 'Window.IsVisible(yesnodialog)'
                                                        and .5 < clock[0] < 4)
        self.setup.xbmcgui.getCurrentWindowDialogId = lambda: 10138 if clock[0] < 5 else 9999
        with patch.object(self.setup.time, 'monotonic', side_effect=lambda: clock[0]):
            self.setup.wait_for_skin_confirmation()
        self.assertGreaterEqual(clock[0], 7)

    def test_missing_confirmation_never_counts_as_user_approval(self):
        self.skin = self.setup.SKIN
        with self.assertRaises(RuntimeError):
            self.setup.wait_for_skin_confirmation()

    def test_setup_wizard_alarm_is_cancelled_without_dismissing_confirmation(self):
        self.skin = self.setup.SKIN
        self.xbmc.getCondVisibility = lambda condition: condition == 'Window.IsVisible(11130)'
        self.setup.dismiss_skin_wizard()
        commands = [call.args[0] for call in self.xbmc.executebuiltin.call_args_list]
        self.assertIn('CancelAlarm(setupwizardopen,true)', commands)
        self.assertIn('Dialog.Close(11130,true)', commands)
        self.assertFalse(any('10100' in command or 'SendClick' in command for command in commands))

    def test_empty_native_skin_dialog_gets_focus_on_no_without_approval(self):
        self.setup.xbmcgui.getCurrentWindowDialogId = lambda: 10100
        self.xbmc.getCondVisibility = lambda _: True
        self.xbmc.getInfoLabel = lambda _: ''
        window = Mock()
        self.setup.xbmcgui.Window = Mock(return_value=window)
        self.assertTrue(self.setup.focus_skin_confirmation())
        self.setup.xbmcgui.Window.assert_called_once_with(10100)
        window.setFocusId.assert_called_once_with(10)
        self.xbmc.executebuiltin.assert_not_called()

    def test_existing_user_selection_is_never_replaced(self):
        self.setup.xbmcgui.getCurrentWindowDialogId = lambda: 10100
        self.xbmc.getCondVisibility = lambda _: True
        self.setup.xbmcgui.Window = Mock()
        for focused in ('10', '11', '12', '61'):
            with self.subTest(focused=focused):
                self.xbmc.getInfoLabel = lambda _: focused
                self.assertTrue(self.setup.focus_skin_confirmation())
        self.setup.xbmcgui.Window.assert_not_called()

    def test_focus_repair_waits_for_the_actual_topmost_confirmation(self):
        self.setup.xbmcgui.Window = Mock()
        self.setup.xbmcgui.getCurrentWindowDialogId = lambda: 10138
        self.xbmc.getCondVisibility = lambda _: True
        self.assertFalse(self.setup.focus_skin_confirmation())
        self.setup.xbmcgui.getCurrentWindowDialogId = lambda: 10100
        self.xbmc.getCondVisibility = lambda _: False
        self.assertFalse(self.setup.focus_skin_confirmation())
        self.setup.xbmcgui.Window.assert_not_called()

    def test_focus_is_only_initialized_once_while_waiting_for_user(self):
        clock = [0.0]
        self.skin = self.setup.SKIN
        self.xbmc.Monitor = lambda: types.SimpleNamespace(
            waitForAbort=lambda seconds: clock.__setitem__(0, clock[0] + seconds) or False)
        self.xbmc.getCondVisibility = lambda condition: condition == 'Window.IsVisible(yesnodialog)' and clock[0] < 3
        with patch.object(self.setup, 'focus_skin_confirmation', return_value=True) as focus:
            with patch.object(self.setup.time, 'monotonic', side_effect=lambda: clock[0]):
                self.setup.wait_for_skin_confirmation()
        focus.assert_called_once_with()
        self.assertGreaterEqual(clock[0], 5)


if __name__ == '__main__':
    unittest.main()
