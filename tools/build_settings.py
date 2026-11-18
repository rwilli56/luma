"""Generate Kodi 21 settings and labels from the runtime preference definitions."""
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / 'plugin.video.luma/resources'
spec = importlib.util.spec_from_file_location('luma_preferences', RES / 'lib/preferences.py')
prefs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prefs)


def build():
    strings = []
    def label(value):
        if isinstance(value, int):
            return str(value)
        number = str(32200 + len(strings))
        strings.append((number, value))
        return number
    root = ET.Element('settings', version='1')
    section = ET.SubElement(root, 'section', id='plugin.video.luma')
    for cid, title, rows in prefs.SCHEMA:
        category = ET.SubElement(section, 'category', id=cid, label=label(title))
        group = ET.SubElement(category, 'group', id='1')
        for row in rows:
            sid, title, kind, default, help_text = row[:5]
            node = ET.SubElement(group, 'setting', id=sid, type={'enum': 'string', 'bool': 'boolean', 'int': 'integer', 'str': 'string', 'secret': 'string'}.get(kind, kind),
                                 label=label(title), help=label(help_text))
            ET.SubElement(node, 'level').text = '2' if sid == 'trakt_client_secret' else '0'
            if kind == 'action':
                ET.SubElement(node, 'data').text = 'RunPlugin(plugin://plugin.video.luma/?action=tool&name={})'.format(default)
                ctrl = ET.SubElement(node, 'control', type='button', format='action')
                ET.SubElement(ctrl, 'close').text = 'true'
            else:
                ET.SubElement(node, 'default').text = str(default).lower() if isinstance(default, bool) else str(default)
                if kind == 'bool':
                    ET.SubElement(node, 'control', type='toggle')
                elif kind == 'int':
                    constraints = ET.SubElement(node, 'constraints')
                    for name, value in zip(('minimum', 'maximum', 'step'), row[5]):
                        ET.SubElement(constraints, name).text = str(value)
                    ctrl = ET.SubElement(node, 'control', type='slider', format='integer')
                    ET.SubElement(ctrl, 'popup').text = 'false'
                elif kind == 'enum':
                    options = ET.SubElement(ET.SubElement(node, 'constraints'), 'options')
                    for value, text in row[5]:
                        ET.SubElement(options, 'option', label=label(text)).text = value
                    ET.SubElement(node, 'control', type='spinner', format='string')
                else:
                    ET.SubElement(ET.SubElement(node, 'constraints'), 'allowempty').text = 'true'
                    ctrl = ET.SubElement(node, 'control', type='edit', format='string')
                    if kind == 'secret':
                        ET.SubElement(ctrl, 'hidden').text = 'true'
    ET.indent(root, space='  ')
    (RES / 'settings.xml').write_bytes(ET.tostring(root, encoding='utf-8', xml_declaration=True))
    path = RES / 'language/resource.language.en_gb/strings.po'
    base = path.read_text(encoding='utf-8').split('# Generated preferences')[0].rstrip()
    generated = '\n\n# Generated preferences — tools/build_settings.py\n'
    for number, text in strings:
        generated += '\nmsgctxt "#{}"\nmsgid {}\nmsgstr ""\n'.format(number, json.dumps(text, ensure_ascii=False))
    path.write_text(base + generated, encoding='utf-8')


if __name__ == '__main__':
    build()
