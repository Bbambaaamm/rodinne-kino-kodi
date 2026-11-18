"""Windows Kodi runs without long-path opt-in, including inside ZIP extraction."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from xml.etree import ElementTree as ET
import zipfile


SOURCE = Path(__file__).resolve().parents[1] / 'addons/script.michal.family.repair/maintenance.py'


@unittest.skipUnless(os.name == 'nt', 'Windows filesystem regression')
class WindowsDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        tree = ast.parse(SOURCE.read_text(encoding='utf8'))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ('local_path', 'packaged_provider_version', 'install_provider')]
        self.env = {'os': os, 'shutil': shutil, 'hashlib': hashlib, 'zipfile': zipfile, 'ET': ET}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), self.env)

    def test_long_path_normalizes_mixed_archive_separators(self):
        relative = 'long-folder/' * 22 + 'settings.json'
        target = self.env['local_path'](str(self.root) + '/' + relative)
        self.assertTrue(target.startswith('\\\\?\\'))
        self.assertNotIn('/', target)
        self.assertGreater(len(target), 260)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'w') as output:
            output.write('complete')
        with open(target) as source:
            self.assertEqual(source.read(), 'complete')
        self.assertEqual(self.env['local_path'](target), target)

    def test_provider_delivery_works_with_nested_files_and_extended_root(self):
        provider = 'plugin.video.webshare.available'
        folder = self.root / 'bundle/resources'
        folder.mkdir(parents=True)
        package = folder / 'provider-0.9.14.zip'
        contents = {'addon.xml': '<addon id="' + provider + '" version="0.9.14"/>',
                    'LICENSE': 'MIT', 'resources/nested/template.xml': '<window/>'}
        with zipfile.ZipFile(package, 'w') as archive:
            for path, data in contents.items():
                archive.writestr(provider + '/' + path, data)
        manifest = {'provider_version': '0.9.14', 'provider_sha256': hashlib.sha256(package.read_bytes()).hexdigest(),
                    'provider_files': list(contents)}
        self.env.update(PATH=str(self.root / 'bundle'), HOME_PATH=self.env['local_path'](str(self.root / 'home')),
            PROFILE=str(self.root / 'profile'), PROVIDER=provider,
            read_json=lambda path: manifest if path.endswith('manifest.json') else {})
        self.env['install_provider'](register=False)
        target = self.env['local_path'](str(self.root / 'home/addons') + '/' + provider + '/resources/nested/template.xml')
        with open(target) as source:
            self.assertEqual(source.read(), '<window/>')


if __name__ == '__main__':
    unittest.main()
