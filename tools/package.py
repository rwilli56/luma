"""Create a deterministic Kodi install ZIP containing only the add-on."""
from pathlib import Path
import hashlib
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def build():
    addon = ROOT / 'plugin.video.luma'
    metadata = ET.parse(addon / 'addon.xml').getroot().attrib
    output = ROOT / 'dist' / '{}-{}.zip'.format(metadata['id'], metadata['version'])
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(addon.rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix in ('.pyc', '.pyo'):
                continue
            name = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 17, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text('{}  {}\n'.format(checksum, output.name), encoding='utf-8')
    print('{} ({} bytes)'.format(output, output.stat().st_size))
    print('SHA256 ' + checksum)


if __name__ == '__main__':
    build()
