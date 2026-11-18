"""Build a static Kodi repository for GitHub Pages. Runtime uses no dependencies."""
import argparse
import copy
import hashlib
import html
import io
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
import zipfile
from package import build as build_addon

ROOT = Path(__file__).resolve().parents[1]


def zip_files(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 17, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def publish_zip(output, addon_id, version, data):
    directory = output / addon_id
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / '{}-{}.zip'.format(addon_id, version)
    target.write_bytes(data)
    target.with_suffix('.zip.sha256').write_text(hashlib.sha256(data).hexdigest(), encoding='ascii')
    return target


def build(base_url, output=None):
    base_url = base_url.rstrip('/')
    parsed = urlsplit(base_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError('Repository base URL must be an HTTPS URL without credentials, query or fragment.')
    if any(char in base_url for char in ('<', '>', '"', "'", '&')):
        raise ValueError('Unsupported character in repository URL.')
    output = Path(output) if output else ROOT / 'dist' / 'repository'
    output.mkdir(parents=True, exist_ok=True)
    # Preserve old release ZIPs during an incremental local build; no recursive deletion.
    build_addon()
    addon_manifest = ET.parse(ROOT / 'plugin.video.luma/addon.xml').getroot()
    addon_id, addon_version = addon_manifest.attrib['id'], addon_manifest.attrib['version']
    plugin_data = (ROOT / 'dist' / '{}-{}.zip'.format(addon_id, addon_version)).read_bytes()
    publish_zip(output, addon_id, addon_version, plugin_data)
    for asset in addon_manifest.findall('.//assets/*'):
        destination = output / addon_id / asset.text
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / addon_id / asset.text, destination)
    repo_text = (ROOT / 'repository.luma/addon.xml.in').read_text(encoding='utf-8').replace('{{BASE_URL}}', base_url)
    repo_manifest = ET.fromstring(repo_text)
    repo_id, repo_version = repo_manifest.attrib['id'], repo_manifest.attrib['version']
    repo_data = zip_files({repo_id + '/addon.xml': repo_text.encode('utf-8'),
                           repo_id + '/icon.png': (ROOT / 'plugin.video.luma/resources/icon.png').read_bytes(),
                           repo_id + '/LICENSE': (ROOT / 'plugin.video.luma/LICENSE').read_bytes()})
    repo_zip = publish_zip(output, repo_id, repo_version, repo_data)
    # Put the bootstrap ZIP at the source root, where Kodi's file browser can find it.
    (output / repo_zip.name).write_bytes(repo_data)
    (output / repo_id / 'icon.png').write_bytes((ROOT / 'plugin.video.luma/resources/icon.png').read_bytes())
    addons = ET.Element('addons')
    addons.append(copy.deepcopy(addon_manifest))
    addons.append(copy.deepcopy(repo_manifest))
    ET.indent(addons, space='  ')
    index = ET.tostring(addons, encoding='utf-8', xml_declaration=True)
    (output / 'addons.xml').write_bytes(index)
    # Kodi's change-detection checksum format; ZIPs separately have SHA-256 files.
    (output / 'addons.xml.md5').write_text(hashlib.md5(index).hexdigest(), encoding='ascii')
    (output / '.nojekyll').touch()
    title = 'Luma for Kodi'
    (output / 'index.html').write_text('''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>body{{margin:8vh auto;max-width:760px;padding:24px;background:#0b1111;color:#f1efe9;font:18px/1.6 system-ui}}a{{color:#8bd5bd}}code{{overflow-wrap:anywhere}}h1{{font-size:48px;letter-spacing:.1em}}.note{{color:#a5b2b0}}</style></head>
<body><h1>LUMA</h1><p>Your library, in a new light.</p>
<p><a href="{repo_zip}">{repo_zip}</a></p>
<p>Add <code>{url}/</code> in Kodi's File manager. Install the repository ZIP, then choose <strong>Install from repository → Luma Repository → Video add-ons → Luma</strong>.</p>
<p class="note">Development alpha · Kodi 21 Omega · TorBox · Optional Trakt and Emby</p>
<p><a href="{plugin}/{plugin}-{version}.zip">{plugin}/{plugin}-{version}.zip</a> · <a href="addons.xml">addons.xml</a> · <a href="addons.xml.md5">addons.xml.md5</a></p>
</body></html>'''.format(title=title, repo_zip=html.escape(repo_zip.name), url=html.escape(base_url), plugin=addon_id, version=addon_version), encoding='utf-8')
    print('Kodi source URL: ' + base_url + '/')
    print('Repository output: ' + str(output))
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True, help='Exact public Pages URL, e.g. https://owner.github.io/luma')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    build(args.base_url, args.output)
