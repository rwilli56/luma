"""Offline layout preview from Home.xml with fictional fixture titles.

This is not a Kodi screenshot. Kodi runtime rendering remains a device test.
"""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SKIN = ROOT / 'plugin.video.luma/resources/skins/Default'
FONTS = {'font10': 17, 'font12': 20, 'font13': 24, 'font20': 29, 'font30': 35, 'font45': 49}
WINDOW = {'hero_title': 'The Quiet Coast', 'hero_detail': 'Pick up where you left off.',
          'library_status': 'TorBox library ready', 'trakt_status': 'Connected · synced'}
ROWS = {
    '200': [('The Quiet Coast', 'S01 E04 · 18 min left', 'T', 'READY TO PLAY', 202),
            ('Orbit', 'Movie · 42 min left', 'O', 'READY TO PLAY', 139),
            ('Wild Trails', 'S02 E01 · 26 min left', 'W', 'EMBY · READY', 98)],
    '300': [('Northern Lights', 'S03 E02', 'N', 'READY TO PLAY', 0),
            ('The Long Weekend', 'S01 E06', 'T', 'READY TO PLAY', 0),
            ('Small Hours', 'S02 E03', 'S', 'ADD TO TORBOX', 0)],
    '400': [('The Quiet Coast', 'Season 1', 'T', '', 0), ('Northern Lights', 'Season 3', 'N', '', 0),
            ('Wild Trails', 'Season 2', 'W', '', 0), ('The Long Weekend', 'Season 1', 'T', '', 0),
            ('Small Hours', 'Season 2', 'S', '', 0)]}


def font(name):
    for path in ('C:/Windows/Fonts/segoeui.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if Path(path).is_file():
            return ImageFont.truetype(path, FONTS.get(name, 24))
    return ImageFont.load_default()


def resolve(text, item):
    text = text or ''
    text = re.sub(r'\$INFO\[Window.Property\(([^)]+)\)\]', lambda m: WINDOW.get(m[1], ''), text)
    text = re.sub(r'\$INFO\[ListItem.Property\(([^)]+)\)\]', lambda m: str(item.get(m[1], '')), text)
    text = text.replace('$INFO[ListItem.Label]', item.get('title', ''))
    return '' if text.startswith('$INFO[') else text


def color(value):
    value = (value or 'FFF1EFE9').strip()
    return '#' + value[-6:]


def draw_control(canvas, node, offset=(0, 0), item=None):
    item = item or {}
    def val(tag, default='0'):
        return resolve(node.findtext(tag, default), item)
    if node.findtext('visible') and not item.get('has_progress'):
        return
    x, y = int(val('left') or 0) + offset[0], int(val('top') or 0) + offset[1]
    w, h = int(val('width') or 0), int(val('height') or 0)
    kind = node.attrib['type']
    if kind == 'image':
        texture = val('texture')
        if not texture or not (SKIN / 'media' / texture).is_file() or w <= 0:
            return
        image = Image.open(SKIN / 'media' / texture).convert('RGBA').resize((w, h))
        canvas.alpha_composite(image, (x, y))
    elif kind in ('label', 'button', 'textbox'):
        draw = ImageDraw.Draw(canvas)
        text = val('label')
        chosen = font(val('font', 'font13'))
        if kind == 'button':
            if node.attrib.get('id') == '100':
                draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill='#8BD5BD')
                fill = '#10201C'
            else:
                fill = color(val('textcolor', 'FFB9C5C2'))
            tw = draw.textlength(text, font=chosen)
            draw.text((x + (w - tw) / 2, y + (h - chosen.size) / 2 - 2), text, font=chosen, fill=fill)
        else:
            while text and draw.textlength(text, font=chosen) > w:
                text = text[:-2].rstrip('…') + '…'
            if val('align', '') == 'right':
                x += w - draw.textlength(text, font=chosen)
            draw.text((x, y + (h - chosen.size) / 2 - 3 if kind != 'textbox' else y), text, font=chosen, fill=color(val('textcolor', 'FFF1EFE9')))
    elif kind == 'list':
        for index, row in enumerate(ROWS[node.attrib['id']]):
            data = dict(zip(('title', 'subtitle', 'initial', 'availability', 'progress_width'), row))
            data['has_progress'] = bool(data['progress_width'])
            for control in node.findall('itemlayout/control'):
                draw_control(canvas, control, (x + index * 348, y), data)


def main():
    canvas = Image.new('RGBA', (1920, 1080))
    for node in ET.parse(SKIN / '1080i/Home.xml').findall('./controls/control'):
        draw_control(canvas, node)
    output = ROOT / 'docs' / 'home-layout-preview.png'
    output.parent.mkdir(exist_ok=True)
    canvas.convert('RGB').save(output)
    print(output)


if __name__ == '__main__':
    main()
