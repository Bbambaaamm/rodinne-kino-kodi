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
            HOME_PATH=str(self.root), PROFILE=str(self.root), HOME=self.home,
            rpc=Mock(side_effect=self.rpc), read_json=self.read_json,
            write_json=lambda path, data: Path(path).write_text(json.dumps(data)),
            set_setting=Mock(), setup_preflight=Mock(), apply=Mock(),
        )
        self.xbmc = types.SimpleNamespace(
            getSkinDir=lambda: self.skin, getCondVisibility=lambda _: False,
            executebuiltin=Mock(side_effect=self.builtin),
            Monitor=lambda: types.SimpleNamespace(waitForAbort=lambda _: True),
        )
        self.dialog = Mock()
        modules = {'maintenance': self.maintenance, 'xbmc': self.xbmc,
                   'xbmcgui': types.SimpleNamespace(Dialog=lambda: self.dialog)}
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('tested_bootstrap', SOURCE)
            self.setup = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.setup)

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
        self.xbmc.executebuiltin.assert_called_with('InstallAddon(script.trakt)', True)

    def test_declined_native_install_stops_with_retry_message(self):
        self.xbmc.executebuiltin.side_effect = None
        with self.assertRaises(RuntimeError):
            self.setup.install_from_repo('script.trakt')

    def test_fresh_prepare_installs_all_components_and_switches_skin(self):
        def install(addon):
            self.installed[addon] = {'enabled': True, 'version': '1.0.0'}
            if addon == self.setup.SKIN:
                self.installed['plugin.video.themoviedb.helper'] = {'version': '6.22.4', 'enabled': True}
        with patch.object(self.setup, 'install_from_repo', side_effect=install) as repo:
            with patch.object(self.setup, 'install_upstream_zip', side_effect=install):
                self.setup.prepare()
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

    def test_existing_skin_does_not_trigger_download_or_language_switch_during_prepare(self):
        self.skin = self.setup.SKIN
        self.installed[self.setup.SKIN] = {'enabled': True, 'version': '3.4.15'}
        self.installed[self.setup.YAWSP] = {'enabled': True, 'version': '0.3.0'}
        with patch.object(self.setup, 'install_from_repo'):
            with patch.object(self.setup, 'urlopen') as download:
                self.setup.prepare()
        download.assert_not_called()
        self.assertEqual(self.settings, {})


if __name__ == '__main__':
    unittest.main()
