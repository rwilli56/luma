"""Offline preview from Luma-Sources.xml; this is not a Kodi screenshot."""
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw
import preview_ui as preview

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin.video.luma'))
from resources.lib.media import traits
from resources.lib import source_info, filtering, preferences


def main():
    names = ['The.Quiet.Coast.2025.2160p.WEB-DL.HDR10+.HEVC.DDP5.1.Atmos',
             'The.Quiet.Coast.2025.2160p.BluRay.REMUX.DV.HDR10.TrueHD.7.1.Atmos',
             'The.Quiet.Coast.2025.2160p.WEB-DL.HDR.HEVC.DDP5.1',
             'The.Quiet.Coast.2025.1080p.BluRay.DTS-HD.MA.5.1.H264',
             'The.Quiet.Coast.2025.1080p.WEB-DL.SDR.H264.AAC2.0',
             'The.Quiet.Coast.2025.720p.WEBRip.H264.AAC2.0']
    sources, rows = [], []
    for index, name in enumerate(names):
        sources.append(dict(name=name, traits=traits(name), size=[18.4, 71.2, 14.8, 12.1, 5.6, 2.4][index] * 1e9,
                            size_origin='TorBox cache total'))
    for index, source in enumerate(filtering.apply(sources, 'movie', preferences.DEFAULTS, torrent_results=True)):
        rows.append(dict(source_number='{:02d}'.format(index + 1), source_formats=source_info.format_label(source),
            source_release=source['name'], source_size=source_info.sizes(source, 'torrents'), source_status='TORBOX · CACHED',
            source_package='TORRENT', source_provider='CocoScrapers / Example · POV / Example', source_mapping=''))
    preview.WINDOW = dict(source_heading='CHOOSE A SOURCE', source_title='The Quiet Coast (2025)',
        source_count='6 cached torrents · preferred formats first', source_note='Torrent totals shown · file details checked after selection')
    original = preview.resolve
    def resolve(value, item):
        value = re.sub(r'\$INFO\[Container\(500\).ListItem.Property\(([^)]+)\)\]', lambda m: str(rows[0].get(m[1], '')), value or '')
        return original(value, item)
    preview.resolve = resolve
    canvas = Image.new('RGBA', (1920, 1080))
    draw = ImageDraw.Draw(canvas)
    def render(node, offset=(0, 0), item=None):
        if node.attrib['type'] != 'textbox':
            preview.draw_control(canvas, node, offset, item)
            return
        chosen = preview.font(node.findtext('font'))
        width = int(node.findtext('width'))
        value = resolve(node.findtext('label'), item or {})
        lines, line = [], ''
        for char in value:
            if draw.textlength(line + char, font=chosen) > width:
                lines.append(line)
                line = ''
            line += char
        if line:
            lines.append(line)
        height = int(node.findtext('height'))
        lines = lines[:max(1, height // (chosen.size + 5))]
        draw.multiline_text((int(node.findtext('left')), int(node.findtext('top'))), '\n'.join(lines),
                            font=chosen, fill=preview.color(node.findtext('textcolor')), spacing=5)
    for node in ET.parse(preview.SKIN / '1080i/Luma-Sources.xml').findall('./controls/control'):
        if node.attrib['type'] == 'list':
            for index, row in enumerate(rows):
                for child in node.findall(('focusedlayout' if index == 0 else 'itemlayout') + '/control'):
                    render(child, (64, 234 + index * 100), row)
        else:
            render(node)
    output = ROOT / 'docs/source-picker-preview.png'
    canvas.convert('RGB').save(output)
    print(output)


if __name__ == '__main__':
    main()
