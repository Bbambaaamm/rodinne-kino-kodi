"""Shared Android storage can copy content while denying metadata changes."""
import ast
import errno
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / 'addons/script.michal.family.repair'


class PortableBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.user = self.root / 'userdata'
        self.profile = self.user / 'addon_data/script.michal.family.repair'
        self.profile.mkdir(parents=True)
        self.keymaps = self.user / 'keymaps'
        self.keymaps.mkdir()
        self.skin = self.root / 'skin'
        self.skin.mkdir()
        tree = ast.parse((SOURCE / 'maintenance.py').read_text(encoding='utf8'))
        helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name in ('copy_tree', 'write_json', 'read_json')]
        env = {'os': os, 'shutil': shutil, 'tempfile': tempfile, 'json': json}
        exec(compile(ast.Module(body=helpers, type_ignores=[]), 'maintenance.py', 'exec'), env)
        self.m = types.SimpleNamespace(PROFILE=str(self.profile), USER=str(self.user),
            HOME_PATH=str(self.root), PROVIDER='plugin.video.webshare.available',
            local_path=os.path.normpath, **{name: env[name] for name in ('copy_tree', 'write_json', 'read_json')})
        with patch.dict(sys.modules, {'maintenance': self.m, 'xbmcaddon': types.SimpleNamespace(),
                'xbmcgui': types.SimpleNamespace(),
                'xbmcvfs': types.SimpleNamespace(translatePath=lambda _: str(self.skin))}):
            spec = importlib.util.spec_from_file_location('tested_backup', SOURCE / 'default.py')
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)

    def metadata_denied(self):
        return patch('shutil.copystat', side_effect=PermissionError(errno.EACCES, 'Permission denied'))

    def test_empty_keymaps_directory_is_backed_up_when_metadata_is_denied(self):
        with self.metadata_denied() as metadata:
            result = self.module.backup()
        self.assertTrue((Path(result['path']) / 'userdata/keymaps').is_dir())
        metadata.assert_not_called()
        self.assertEqual(self.m.read_json(self.profile / 'baseline.json'), result)

    def test_nested_content_and_standalone_player_survive_without_metadata(self):
        (self.keymaps / 'remote.xml').write_bytes(b'<keymap/>')
        nested = self.skin / '1080i'
        nested.mkdir()
        (nested / 'Home.xml').write_bytes(b'<window/>')
        player = self.user / 'addon_data/plugin.video.themoviedb.helper/reconfigured_players/family.webshare.json'
        player.parent.mkdir(parents=True)
        player.write_bytes(b'{"previous":true}')
        cache = self.keymaps / '__pycache__'
        cache.mkdir()
        (cache / 'cached.pyc').write_bytes(b'cache')
        with self.metadata_denied():
            result = self.module.backup()
        saved = Path(result['path'])
        self.assertEqual((saved / 'userdata/keymaps/remote.xml').read_bytes(), b'<keymap/>')
        self.assertEqual((saved / 'skin.arctic.fuse.3/1080i/Home.xml').read_bytes(), b'<window/>')
        self.assertEqual((saved / player.relative_to(self.root)).read_bytes(), b'{"previous":true}')
        self.assertFalse((saved / 'userdata/keymaps/__pycache__').exists())

    def test_completed_baseline_is_reused(self):
        (self.keymaps / 'remote.xml').write_bytes(b'original')
        result = self.module.backup()
        (self.keymaps / 'remote.xml').write_bytes(b'updated')
        self.assertEqual(self.module.backup(), result)
        self.assertEqual((Path(result['path']) / 'userdata/keymaps/remote.xml').read_bytes(), b'original')

    def test_real_content_access_denial_aborts_without_committing_baseline(self):
        (self.keymaps / 'remote.xml').write_bytes(b'original')
        with patch('shutil.copyfile', side_effect=PermissionError(errno.EACCES, 'Permission denied')):
            with self.assertRaises(PermissionError):
                self.module.backup()
        self.assertFalse((self.profile / 'baseline.json').exists())
        self.assertEqual((self.keymaps / 'remote.xml').read_bytes(), b'original')
        result = self.module.backup()
        self.assertEqual((Path(result['path']) / 'userdata/keymaps/remote.xml').read_bytes(), b'original')

    def test_failed_backup_can_retry_when_clock_has_not_advanced(self):
        (self.keymaps / 'remote.xml').write_bytes(b'original')
        fixed = types.SimpleNamespace(
            now=lambda: types.SimpleNamespace(strftime=lambda _: '20261123-192730-476919'))
        with patch.object(self.module, 'datetime', fixed):
            with patch('shutil.copyfile', side_effect=PermissionError(errno.EACCES, 'Permission denied')):
                with self.assertRaises(PermissionError):
                    self.module.backup()
            result = self.module.backup()
        self.assertTrue(Path(result['path']).name.endswith('-1'))
        self.assertEqual((Path(result['path']) / 'userdata/keymaps/remote.xml').read_bytes(), b'original')

    def test_restore_tree_merges_content_without_changing_metadata(self):
        source = self.root / 'restore'
        source.mkdir()
        (source / 'remote.xml').write_bytes(b'previous')
        (self.keymaps / 'remote.xml').write_bytes(b'changed')
        (self.keymaps / 'unrelated.xml').write_bytes(b'keep')
        with self.metadata_denied():
            self.m.copy_tree(str(source), str(self.keymaps))
        self.assertEqual((self.keymaps / 'remote.xml').read_bytes(), b'previous')
        self.assertEqual((self.keymaps / 'unrelated.xml').read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
