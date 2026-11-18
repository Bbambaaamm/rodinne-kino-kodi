"""Idle updates, failed upgrades, and recovery across service restarts."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve().parents[1] / 'addons/script.michal.family.repair/updates.py'


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.profile = self.root / 'profile'
        self.profile.mkdir()
        self.bundle = self.root / 'bundle'
        self.user = self.root / 'userdata'
        self.skin = self.root / 'skin'
        self.provider = self.root / 'addons/plugin.video.webshare.available'
        self.properties = {}
        self.home = types.SimpleNamespace(
            getProperty=lambda key: self.properties.get(key, ''),
            setProperty=lambda key, value: self.properties.__setitem__(key, value),
            clearProperty=lambda key: self.properties.pop(key, None),
        )
        self.versions = {'skin.arctic.fuse.3': '3.5.4', 'plugin.video.webshare.available': '0.9.13'}
        self.players = []
        self.window = 10000
        self.dialog = 9999
        self.idle = 20
        self.skin_id = 'skin.arctic.fuse.3'
        self.setting_values = {'general.addonupdates': 0, 'filelists.showparentdiritems': False, 'locale.audiolanguage': 'Czech',
                               'videoplayer.preferdefaultflag': False}
        self.changes_path = self.profile / 'changes.json'
        self.original_changes = {'version': '1.7.0', 'applied': 1234, 'skin_version': '3.5.4'}
        self.write(self.changes_path, self.original_changes)
        self.write(self.bundle / 'resources/layout.json', {'nodes': {'homewidgets': []},
                                                           'strings': {}, 'bools': {}})
        self.package = {'provider_version': '0.9.14', 'provider_sha256': 'new-checksum',
                        'provider_files': ['addon.xml', 'core.py', 'new_module.py']}
        self.write(self.bundle / 'resources/manifest.json', self.package)
        self.provider.mkdir(parents=True)
        (self.provider / 'core.py').write_text('previous working source')
        (self.provider / 'addon.xml').write_text('<addon version="0.9.13"/>')
        (self.skin / '1080i').mkdir(parents=True)
        (self.skin / '1080i/Includes_Home.xml').write_text('<previous/>')
        self.addon = Mock()
        self.addon.getSetting.return_value = 'previous'
        self.m = types.SimpleNamespace(
            PROFILE=str(self.profile), PATH=str(self.bundle), HOME_PATH=str(self.root), USER=str(self.user),
            PROVIDER='plugin.video.webshare.available', VERSION='1.8.0', HOME=self.home,
            STREAMING_HUB='1104', STREAMING_TEMPLATES=('widgets.xml',), rpc=Mock(side_effect=self.rpc),
            read_json=self.read, write_json=self.write, packaged_provider_version=lambda: '0.9.14',
            local_path=os.path.normpath,
            search_skin_backup=lambda: str(self.profile / 'search-before/3.5.4'),
            streaming_template_backup=lambda _: str(self.profile / 'templates-before/3.5.4/widgets.xml'),
            streaming_template_path=lambda name: str(self.skin / name),
            apply=Mock(side_effect=self.apply),
        )
        self.xbmc = types.SimpleNamespace(
            getSkinDir=lambda: self.skin_id, getInfoLabel=lambda _: '', getCondVisibility=lambda _: False,
            getGlobalIdleTime=lambda: self.idle, executebuiltin=Mock(),
        )
        self.gui = types.SimpleNamespace(
            getCurrentWindowId=lambda: self.window, getCurrentWindowDialogId=lambda: self.dialog,
            Dialog=Mock(),
        )
        modules = {'maintenance': self.m, 'xbmc': self.xbmc, 'xbmcgui': self.gui,
                   'xbmcaddon': types.SimpleNamespace(Addon=lambda _: self.addon),
                   'xbmcvfs': types.SimpleNamespace(translatePath=lambda _: str(self.skin))}
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('tested_updates', SOURCE)
            self.updates = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.updates)
        self.updater = self.updates.Updater()

    def write(self, path, data):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf8')

    def read(self, path):
        path = Path(path)
        return json.loads(path.read_text(encoding='utf8')) if path.exists() else {}

    def rpc(self, method, params=None):
        if method == 'Addons.GetAddonDetails':
            return {'addon': {'version': self.versions[params['addonid']]}}
        if method == 'Player.GetActivePlayers':
            return self.players
        if method == 'Settings.GetSettingValue':
            return {'value': self.setting_values[params['setting']]}
        if method == 'Settings.SetSettingValue':
            self.setting_values[params['setting']] = params['value']
            return True
        raise AssertionError(method)

    def apply(self, backup, restart_service=True):
        self.write(self.changes_path, {'version': '1.8.0', 'applied': time.time(),
            'provider_sha256': 'new-checksum', 'provider_version': '0.9.14', 'skin_version': '3.5.4'})
        self.versions[self.m.PROVIDER] = '0.9.14'

    def mark_current(self):
        self.apply(None)

    def test_new_profile_waits_for_explicit_first_install(self):
        self.write(self.changes_path, {})
        self.assertFalse(self.updater.pending())

    def test_rolled_back_setup_is_not_reinstalled(self):
        self.write(self.changes_path, {**self.original_changes, 'rolled_back': True})
        self.assertFalse(self.updater.pending())

    def test_current_release_does_not_reapply(self):
        self.mark_current()
        self.assertFalse(self.updater.pending())

    def test_release_upgrade_is_pending(self):
        self.assertTrue(self.updater.pending())
        self.assertEqual(self.updater.target['version'], '1.8.0')

    def test_upstream_skin_upgrade_is_pending(self):
        self.mark_current()
        self.versions['skin.arctic.fuse.3'] = '3.6.0'
        self.assertTrue(self.updater.pending())

    def test_provider_left_on_previous_release_is_repaired(self):
        self.mark_current()
        self.versions[self.m.PROVIDER] = '0.9.13'
        self.assertTrue(self.updater.pending())

    def test_active_video_is_deferred_even_when_user_is_idle(self):
        self.players = [{'playerid': 1, 'type': 'video'}]
        self.assertFalse(self.updater.ready())

    def test_music_is_deferred(self):
        self.players = [{'playerid': 0, 'type': 'audio'}]
        self.assertFalse(self.updater.ready())

    def test_open_dialog_is_deferred(self):
        self.dialog = 10100
        self.assertFalse(self.updater.ready())

    def test_user_navigation_is_deferred(self):
        self.idle = 14
        self.assertFalse(self.updater.ready())

    def test_movie_card_is_deferred(self):
        self.properties['Family.Card.Active'] = 'true'
        self.assertFalse(self.updater.ready())

    def test_another_install_is_deferred(self):
        self.properties['Family.Setup.InProgress'] = 'manual'
        self.assertFalse(self.updater.ready())

    def test_selected_other_skin_is_respected(self):
        self.skin_id = 'skin.estuary'
        self.assertFalse(self.updater.ready())

    def test_successful_update_commits_once_and_restarts_service(self):
        backup = Mock()
        self.assertTrue(self.updater.apply(backup))
        self.m.apply.assert_called_once_with(backup, restart_service=False)
        self.assertEqual(self.read(self.updater.state_path)['status'], 'applied')
        self.assertFalse(self.updates.Updater().pending())
        self.xbmc.executebuiltin.assert_called_with(
            'RunScript(special://home/addons/script.michal.family.repair/service.py)')
        self.assertFalse(self.properties.get('Family.Setup.InProgress'))

    def test_partial_failure_restores_previous_files_and_manifest(self):
        def broken(*args, **kwargs):
            (self.provider / 'core.py').write_text('incomplete update')
            (self.provider / 'new_module.py').write_text('new file')
            (self.skin / '1080i/Includes_Home.xml').write_text('<incomplete/>')
            self.setting_values['locale.audiolanguage'] = 'English'
            self.write(self.changes_path, {'version': 'unfinished'})
            raise RuntimeError('Interrupted layout generation')
        self.m.apply.side_effect = broken
        self.assertFalse(self.updater.apply(Mock()))
        self.assertEqual((self.provider / 'core.py').read_text(), 'previous working source')
        self.assertFalse((self.provider / 'new_module.py').exists())
        self.assertEqual((self.skin / '1080i/Includes_Home.xml').read_text(), '<previous/>')
        self.assertEqual(self.read(self.changes_path), self.original_changes)
        self.assertEqual(self.setting_values['locale.audiolanguage'], 'Czech')
        state = self.read(self.updater.state_path)
        self.assertEqual(state['status'], 'error')
        self.assertTrue(state['restored'])
        self.assertFalse(self.updates.Updater().ready())
        self.assertFalse(self.properties.get('Family.Setup.InProgress'))

    def test_failure_before_backup_keeps_previous_state(self):
        with patch.object(self.updates.Snapshot, 'capture', side_effect=OSError('disk unavailable')):
            self.assertFalse(self.updater.apply(Mock()))
        self.m.apply.assert_not_called()
        self.assertEqual(self.read(self.changes_path), self.original_changes)
        self.assertFalse(self.properties.get('Family.Setup.InProgress'))

    def test_snapshot_and_restore_work_when_shared_storage_denies_metadata(self):
        import errno
        with patch('shutil.copystat', side_effect=PermissionError(errno.EACCES, 'Permission denied')) as metadata:
            snapshot = self.updates.Snapshot()
            snapshot.capture()
            (self.provider / 'core.py').write_text('changed source')
            snapshot.restore()
        self.assertEqual((self.provider / 'core.py').read_text(), 'previous working source')
        metadata.assert_not_called()


if __name__ == '__main__':
    unittest.main()
