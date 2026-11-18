"""Verify a public repository exactly as Kodi fetches its index and packages."""
import argparse
import ast
import hashlib
import io
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import zipfile


def fetch(url):
    if urlsplit(url).scheme != 'https':
        raise ValueError('Repository URLs must use HTTPS.')
    with urlopen(Request(url, headers={'User-Agent': 'Luma-Repository-Verification/0.1'}), timeout=20) as response:
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('Unexpectedly large repository artifact.')
    return data


def verify(base_url):
    base_url = base_url.rstrip('/')
    index = fetch(base_url + '/addons.xml')
    if hashlib.md5(index).hexdigest() != fetch(base_url + '/addons.xml.md5').decode('ascii').strip():
        raise ValueError('Repository index checksum mismatch.')
    entries = ET.fromstring(index)
    if entries.tag != 'addons':
        raise ValueError('Missing addons index.')
    for addon in entries:
        addon_id, version = addon.attrib['id'], addon.attrib['version']
        if not re.fullmatch(r'[a-z0-9._-]+', addon_id) or not re.fullmatch(r'[0-9.]+', version):
            raise ValueError('Unexpected add-on identity.')
        filename = '{}-{}.zip'.format(addon_id, version)
        url = base_url + '/' + addon_id + '/' + filename
        data = fetch(url)
        if hashlib.sha256(data).hexdigest() != fetch(url + '.sha256').decode('ascii').strip():
            raise ValueError('Package SHA256 mismatch.')
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if archive.testzip():
                raise ValueError('Package failed ZIP integrity check.')
            manifest = ET.fromstring(archive.read(addon_id + '/addon.xml'))
            if manifest.attrib['id'] != addon_id or manifest.attrib['version'] != version:
                raise ValueError('Package version differs from index.')
            for name in archive.namelist():
                if name.startswith('/') or '..' in name.split('/'):
                    raise ValueError('Unsafe package path.')
                if name.endswith('.py'):
                    ast.parse(archive.read(name), filename=name, feature_version=(3, 8))
            if addon_id == 'repository.luma':
                if manifest.findtext('./extension/dir/info') != base_url + '/addons.xml':
                    raise ValueError('Repository package points at a different index.')
                if fetch(base_url + '/' + filename) != data:
                    raise ValueError('Bootstrap ZIP differs from indexed repository package.')
        print('{} {}: ZIP, manifest, SHA256 and source syntax verified'.format(addon_id, version))
    print('Live Kodi repository verified: ' + base_url + '/')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    verify(parser.parse_args().base_url)
