import contextlib
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_repository import build
from verify_repository import verify_listing


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            value = dict(attrs).get('href')
            if value:
                self.links.append(value)


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

    def test_file_manager_listing_contains_repository_control_files(self):
        # Kodi's CFile::Open trusts a cached HTTP directory listing. A checksum
        # omitted from index.html is rejected as nonexistent before any HTTP GET.
        # Reproduce the File manager -> install ZIP -> open repository sequence.
        with tempfile.TemporaryDirectory() as temporary:
            with contextlib.redirect_stdout(io.StringIO()):
                output = build('https://example.test/luma', Path(temporary))
            listing = Links()
            listing.feed((output / 'index.html').read_text())
            verify_listing('https://example.test/luma', (output / 'index.html').read_text(), ET.parse(output / 'addons.xml').getroot())
            base = 'https://example.test/luma/'
            cached_paths = {urljoin(base, link) for link in listing.links}
            repo = ET.parse(output / 'addons.xml').find("./addon[@id='repository.luma']")
            for tag in ('info', 'checksum'):
                target = repo.findtext('./extension/dir/' + tag)
                self.assertIn(target, cached_paths, 'Kodi cache would reject ' + target)
            self.assertIn(base + 'repository.luma-0.1.1.zip', cached_paths)

    def test_incomplete_listing_fails_even_if_xml_is_valid(self):
        entries = ET.fromstring('''<addons><addon><extension point="xbmc.addon.repository"><dir>
            <info>https://example.test/luma/addons.xml</info>
            <checksum>https://example.test/luma/addons.xml.md5</checksum>
            </dir></extension></addon></addons>''')
        with self.assertRaisesRegex(ValueError, 'unlisted.*addons.xml.md5'):
            verify_listing('https://example.test/luma', '<a href="addons.xml">addons.xml</a>', entries)

    def test_friendly_link_labels_are_not_kodi_directory_entries(self):
        entries = ET.fromstring('''<addons><addon><extension point="xbmc.addon.repository"><dir>
            <info>https://example.test/luma/addons.xml</info>
            <checksum>https://example.test/luma/addons.xml.md5</checksum>
            </dir></extension></addon></addons>''')
        page = '<a href="addons.xml">addons.xml</a> · <a href="addons.xml.md5">Index checksum</a>'
        with self.assertRaisesRegex(ValueError, 'unlisted.*addons.xml.md5'):
            verify_listing('https://example.test/luma', page, entries)

    def test_unsafe_base_urls_rejected(self):
        for url in ('http://example.com', 'https://user:password@example.com', 'https://example.com?token=x', 'https://example.com/#bad'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                build(url)


if __name__ == '__main__':
    unittest.main()
