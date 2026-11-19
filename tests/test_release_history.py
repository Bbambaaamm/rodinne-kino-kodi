"""Published version choices retain the exact archives required for rollback."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile


class ReleaseHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = Path(__file__).resolve().parents[1] / 'build.py'
        spec = importlib.util.spec_from_file_location('tested_release_build', source)
        self.b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.b)
        self.b.ROOT = self.root
        self.b.DIST = self.root / 'dist'

    def archive(self, version, metadata_version=None):
        path = self.b.DIST / self.b.INSTALLER / f'{self.b.INSTALLER}-{version}.zip'
        path.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(path, 'w') as archive:
            archive.writestr(self.b.INSTALLER + '/addon.xml',
                f'<addon id="{self.b.INSTALLER}" version="{metadata_version or version}"/>')
            archive.writestr(self.b.INSTALLER + '/default.py', '# preserved ' + version)
        return path

    def test_three_latest_releases_use_numeric_order(self):
        for version in ('1.8.2', '1.8.3', '1.8.4', '1.8.9', '1.8.10'):
            self.archive(version)
        self.assertEqual([row[0] for row in self.b.installer_history('1.8.10')],
                         ['1.8.10', '1.8.9', '1.8.4'])

    def test_future_archives_do_not_leak_into_an_older_release(self):
        for version in ('1.8.3', '1.8.4', '1.8.5', '1.8.6'):
            self.archive(version)
        self.assertEqual([row[0] for row in self.b.installer_history('1.8.5')],
                         ['1.8.5', '1.8.4', '1.8.3'])

    def test_missing_current_archive_is_rejected(self):
        self.archive('1.8.4')
        with self.assertRaises(ValueError):
            self.b.installer_history('1.8.5')

    def test_mislabeled_old_archive_is_rejected(self):
        self.archive('1.8.4', metadata_version='1.8.3')
        with self.assertRaises(ValueError):
            self.b.installer_history('1.8.4')

    def test_public_source_copies_current_and_two_previous_archives_unchanged(self):
        versions = ('1.8.2', '1.8.3', '1.8.4', '1.8.5')
        originals = {version: self.archive(version).read_bytes() for version in versions}
        repo = self.b.DIST / self.b.REPOSITORY / (self.b.REPOSITORY + '-1.0.0.zip')
        repo.parent.mkdir(parents=True)
        repo.write_bytes(b'unchanged repository')
        self.b.write_install_source(ET.fromstring('<addon version="1.0.0"/>'), '1.8.5')
        page = (self.root / 'docs/index.html').read_text(encoding='utf8')
        for version in ('1.8.5', '1.8.4', '1.8.3'):
            name = f'{self.b.INSTALLER}-{version}.zip'
            self.assertIn(f'href="{name}">{name}</a>', page)
            self.assertEqual((self.root / 'docs' / name).read_bytes(), originals[version])
        self.assertNotIn(f'{self.b.INSTALLER}-1.8.2.zip', page)


if __name__ == '__main__':
    unittest.main()
