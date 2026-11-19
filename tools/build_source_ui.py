"""Build Luma's native Kodi source picker using its existing textures."""
import xml.etree.ElementTree as ET
from build_ui import child, control, label, image, SKIN


def build():
    window = ET.Element('window')
    child(window, 'defaultcontrol', '500', always='true')
    coords = child(window, 'coordinates')
    child(coords, 'system', '1')
    child(coords, 'posx', '0')
    child(coords, 'posy', '0')
    controls = child(window, 'controls')
    image(controls, 'background.png', 0, 0, 1920, 1080)
    image(controls, 'teal.png', 64, 48, 5, 30)
    label(controls, 'L U M A', 88, 36, 260, 54, font='font30_title')
    label(controls, '$INFO[Window.Property(source_heading)]', 360, 49, 1000, 32, 'FF8BD5BD', 'font12')
    label(controls, '$INFO[Window.Property(source_title)]', 64, 110, 1770, 55, font='font30_title', scroll='true')
    label(controls, '$INFO[Window.Property(source_count)]', 66, 177, 1300, 32, 'FFA5B2B0', 'font12')
    listing = control(controls, 'list', 64, 234, 1260, 700, id=500, orientation='vertical', scrolltime=100,
                      preloaditems=1, onleft=501, onright=501, onup=500, ondown=500)
    for tag, focused in [('itemlayout', False), ('focusedlayout', True)]:
        row = child(listing, tag, width='1260', height='100')
        image(row, 'focus.png' if focused else 'card.png', 0, 2, 1248, 94)
        label(row, '$INFO[ListItem.Property(source_number)]', 16, 21, 54, 42, 'FF8BD5BD', 'font20_title')
        label(row, '$INFO[ListItem.Property(source_formats)]', 82, 6, 1140, 30, font='font13')
        label(row, '$INFO[ListItem.Property(source_release)]', 82, 37, 1140, 28, 'FFB9C5C2', 'font12', scroll='true' if focused else 'false')
        label(row, '$INFO[ListItem.Property(source_status)]', 82, 67, 208, 22, 'FF8BD5BD', 'font10')
        label(row, '$INFO[ListItem.Property(source_package)]', 302, 67, 180, 22, 'FFB9C5C2', 'font10')
        label(row, '$INFO[ListItem.Property(source_size)]', 478, 67, 730, 22, 'FFB9C5C2', 'font10', align='right')
    image(controls, 'card.png', 1360, 234, 496, 578)
    label(controls, 'SELECTED RELEASE', 1384, 254, 440, 32, 'FF8BD5BD', 'font12')
    control(controls, 'textbox', 1384, 303, 444, 136, label='$INFO[Container(500).ListItem.Property(source_release)]',
            font='font13', textcolor='FFF1EFE9')
    label(controls, '$INFO[Container(500).ListItem.Property(source_provider)]', 1384, 453, 440, 32, 'FFA5B2B0', 'font12', scroll='true')
    control(controls, 'textbox', 1384, 504, 444, 100, label='$INFO[Container(500).ListItem.Property(source_formats)]',
            font='font13', textcolor='FFF1EFE9')
    control(controls, 'textbox', 1384, 621, 444, 64, label='$INFO[Container(500).ListItem.Property(source_size)]',
            font='font12', textcolor='FF8BD5BD')
    control(controls, 'textbox', 1384, 705, 444, 80, label='$INFO[Container(500).ListItem.Property(source_mapping)]',
            font='font12', textcolor='FFA5B2B0')
    for cid, title, x in [(501, 'Source information', 1360), (502, 'Cancel', 1622)]:
        control(controls, 'button', x, 843, 234, 58, id=cid, label=title, font='font12', align='center', aligny='center',
                textcolor='FFB9C5C2', focusedcolor='FF10201C', texturefocus='button-focus.png', texturenofocus='card.png',
                onleft=500 if cid == 501 else 501, onright=502 if cid == 501 else 500, onup=500, ondown=500)
    label(controls, '$INFO[Window.Property(source_note)]', 66, 960, 1720, 30, 'FFA5B2B0', 'font12')
    label(controls, 'Select to play   ·   Long-press / Info for full details   ·   Back to cancel', 66, 1005, 1720, 30, 'FF758983', 'font12')
    ET.indent(window, space='  ')
    output = SKIN / '1080i/Luma-Sources.xml'
    ET.ElementTree(window).write(output, encoding='utf-8', xml_declaration=True)
    print(output)


if __name__ == '__main__':
    build()
