"""Generate the native Kodi window and small reusable textures. Dev-only Pillow."""
from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / 'plugin.video.luma' / 'resources'
SKIN = RES / 'skins' / 'Default'


def child(parent, tag, text=None, **attrs):
    node = ET.SubElement(parent, tag, attrs)
    if text is not None:
        node.text = str(text)
    return node


def control(parent, kind, x, y, w, h, **props):
    attrs = {'type': kind}
    if 'id' in props:
        attrs['id'] = str(props.pop('id'))
    node = child(parent, 'control', **attrs)
    for key, value in dict(left=x, top=y, width=w, height=h, **props).items():
        child(node, key, value)
    return node


def label(parent, text, x, y, w, h=32, color='FFF1EFE9', font='font13', **props):
    return control(parent, 'label', x, y, w, h, label=text, textcolor=color, font=font, **props)


def image(parent, tex, x, y, w, h, **props):
    return control(parent, 'image', x, y, w, h, texture=tex, **props)


def card(parent, focused):
    image(parent, 'focus.png' if focused else 'card.png', 0, 0, 316, 174)
    image(parent, 'still.png', 6, 6, 304, 106)
    label(parent, '$INFO[ListItem.Property(initial)]', 20, 13, 270, 85, 'FF49776F', 'font45')
    image(parent, '$INFO[ListItem.Art(thumb)]', 6, 6, 304, 106, aspectratio='scale')
    image(parent, 'scrim.png', 6, 6, 304, 106)
    label(parent, '$INFO[ListItem.Property(availability)]', 16, 76, 284, 30, 'FFD4EEE6', 'font10')
    label(parent, '$INFO[ListItem.Label]', 14, 116, 286, 27, font='font13')
    label(parent, '$INFO[ListItem.Property(subtitle)]', 14, 144, 286, 23, 'FFA5B2B0', 'font10')
    image(parent, 'teal.png', 7, 109, '$INFO[ListItem.Property(progress_width)]', 3,
          visible='String.IsEqual(ListItem.Property(has_progress),true)')


def build():
    window = ET.Element('window')
    child(window, 'defaultcontrol', '100', always='true')
    coords = child(window, 'coordinates')
    child(coords, 'system', '1')
    child(coords, 'posx', '0')
    child(coords, 'posy', '0')
    controls = child(window, 'controls')
    image(controls, 'background.png', 0, 0, 1920, 1080)
    image(controls, 'teal.png', 82, 54, 5, 32)
    label(controls, 'L U M A', 105, 42, 390, 60, font='font30_title')
    label(controls, 'YOUR LIBRARY, IN A NEW LIGHT', 82, 150, 1000, 32, 'FF82BEB0', 'font12')
    control(controls, 'textbox', 80, 195, 1600, 112, label='$INFO[Window.Property(hero_title)]',
            font='font45', textcolor='FFF1EFE9')
    label(controls, '$INFO[Window.Property(hero_detail)]', 84, 302, 1400, 32, 'FFA5B2B0')
    buttons = [(100, 'TorBox library', 900, 230), (101, 'Add a link', 1150, 205),
               (102, 'Refresh', 1375, 180), (103, 'Settings', 1575, 220)]
    for index, (cid, text, x, width) in enumerate(buttons):
        control(controls, 'button', x, 45, width, 58, id=cid, label=text, font='font13',
                textcolor='FFB9C5C2', focusedcolor='FF10201C', texturefocus='button-focus.png',
                texturenofocus='clear.png', align='center', aligny='center',
                onleft=buttons[index - 1][0], onright=buttons[(index + 1) % 4][0], onup=400, ondown=200)
    for cid, title, y, up, down in [(200, 'Continue watching', 350, 100, 300),
                                  (300, 'Next up', 580, 200, 400),
                                  (400, 'Recently watched series', 810, 300, 100)]:
        label(controls, title, 84, y - 3, 1300, 40, font='font20_title')
        control(controls, 'button', 1595, y - 5, 200, 42, id=cid + 1, label='See all  >',
                font='font12', textcolor='FF8FABA4', focusedcolor='FF12251F',
                texturefocus='button-focus.png', texturenofocus='clear.png', align='center',
                onleft=cid, onright=cid, onup=up, ondown=cid)
        node = control(controls, 'list', 84, y + 50, 1740, 178, id=cid, orientation='horizontal',
                       scrolltime=120, preloaditems=1, onup=up, ondown=down, onleft=cid + 1, onright=cid + 1)
        for tag, focused in [('itemlayout', False), ('focusedlayout', True)]:
            layout = child(node, tag, width='348', height='178')
            card(layout, focused)
    label(controls, '$INFO[Window.Property(library_status)]', 84, 1042, 1100, 24, 'FF758983', 'font10')
    label(controls, '$INFO[Window.Property(trakt_status)]', 1190, 1042, 610, 24, 'FF758983', 'font10', align='right')
    output = SKIN / '1080i' / 'Luma-Home.xml'
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(window, space='  ')
    ET.ElementTree(window).write(output, encoding='utf-8', xml_declaration=True)


def assets():
    media = SKIN / 'media'
    media.mkdir(parents=True, exist_ok=True)
    for name, color in [('teal', '#8BD5BD'), ('clear', (0, 0, 0, 0))]:
        Image.new('RGBA', (8, 8), color).save(media / (name + '.png'))
    for name, color, outline in [('card', '#172120', '#22312E'), ('focus', '#1D2F2A', '#8BD5BD'), ('button-focus', '#8BD5BD', None)]:
        im = Image.new('RGBA', (316, 174) if name != 'button-focus' else (230, 58))
        ImageDraw.Draw(im).rounded_rectangle((1, 1, im.width - 2, im.height - 2), radius=8, fill=color, outline=outline, width=2)
        im.save(media / (name + '.png'))
    im = Image.new('RGB', (608, 212))
    pixels = im.load()
    for y in range(im.height):
        for x in range(im.width):
            light = max(0, 1 - ((x - 480) ** 2 / 180000 + (y - 20) ** 2 / 80000))
            pixels[x, y] = (int(18 + 12 * light), int(30 + 28 * light), int(28 + 23 * light))
    im.save(media / 'still.png')
    scrim = Image.new('RGBA', (8, 106))
    draw = ImageDraw.Draw(scrim)
    for y in range(106):
        draw.line((0, y, 8, y), fill=(5, 13, 11, int(150 * (y / 106) ** 2)))
    scrim.save(media / 'scrim.png')
    background = Image.new('RGB', (960, 540))
    p = background.load()
    for y in range(540):
        for x in range(960):
            light = max(0, 1 - ((x - 860) ** 2 / 260000 + (y - 55) ** 2 / 70000)) ** 2
            p[x, y] = (int(11 + light * 5), int(17 + light * 17), int(17 + light * 12))
    background.save(media / 'background.png')
    background.resize((1920, 1080)).save(RES / 'fanart.png')
    icon = Image.new('RGB', (512, 512), '#101C19')
    d = ImageDraw.Draw(icon)
    d.rounded_rectangle((44, 44, 468, 468), 90, outline='#36564B', width=3)
    d.line((180, 155, 180, 355, 340, 355), fill='#8BD5BD', width=24)
    d.ellipse((310, 145, 338, 173), fill='#F1EFE9')
    icon.save(RES / 'icon.png')


if __name__ == '__main__':
    build()
    assets()
