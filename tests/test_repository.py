import contextlib
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_repository import build


class RepositoryTests(unittest.TestCase):
    def test_generated_repo_urls_zips_and_checksums(self):
        with tempfile.TemporaryDirectory() as temporary:
            with contextlib.redirect_stdout(io.StringIO()):
                output = build('https://example.test/luma', Path(temporary))
            index = (output / 'addons.xml').read_bytes()
            root = ET.fromstring(index)
            self.assertEqual({e.attrib['id'] for e in root}, {'plugin.video.luma', 'repository.luma'})
            self.assertEqual((output / 'addons.xml.md5').read_text(), hashlib.md5(index).hexdigest())
            repo = root.find("./addon[@id='repository.luma']")
            self.assertEqual(repo.attrib['version'], '0.1.1')
            self.assertEqual(repo.find("./requires/import[@addon='xbmc.addon']").attrib['version'], '12.0.0')
            # Kodi filters repository dirs by its internal xbmc.addon API version.
            # A single shared catalog needs no version gate at all.
            self.assertEqual(repo.find('./extension/dir').attrib, {})
            self.assertEqual(repo.findtext("./extension/dir/info"), 'https://example.test/luma/addons.xml')
            self.assertEqual(repo.findtext("./extension/dir/datadir"), 'https://example.test/luma/')
            for addon in root:
                addon_id, version = addon.attrib['id'], addon.attrib['version']
                path = output / addon_id / '{}-{}.zip'.format(addon_id, version)
                self.assertEqual(path.with_suffix('.zip.sha256').read_text(), hashlib.sha256(path.read_bytes()).hexdigest())
                with zipfile.ZipFile(path) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertIn(addon_id + '/addon.xml', archive.namelist())
                    self.assertTrue(all(not name.startswith('/') and '..' not in name.split('/') for name in archive.namelist()))
                    self.assertFalse(any('__pycache__' in name or name.endswith('.pyc') for name in archive.namelist()))
                    if addon_id == 'repository.luma':
                        self.assertNotIn(b'{{BASE_URL}}', archive.read(addon_id + '/addon.xml'))
            self.assertTrue((output / 'repository.luma-0.1.1.zip').is_file())
            self.assertIn('repository.luma-0.1.1.zip', (output / 'index.html').read_text())

    def test_unsafe_base_urls_rejected(self):
        for url in ('http://example.com', 'https://user:password@example.com', 'https://example.com?token=x', 'https://example.com/#bad'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                build(url)


if __name__ == '__main__':
    unittest.main()
