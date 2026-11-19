"""Presentation of release hints and measured file sizes; no network calls."""
import re
from .media import byte_size


def text(value):
    # External filenames cannot inject Kodi formatting into the picker.
    return re.sub(r'[\x00-\x1f\x7f]', ' ', str(value or '')).replace('[', '(').replace(']', ')')


def size_label(size):
    size = byte_size(size)
    if not size:
        return 'Size unknown'
    if size >= 1e9:
        return '{:.2f} GB'.format(size / 1e9)
    if size >= 1e6:
        return '{:.1f} MB'.format(size / 1e6)
    return '{:.1f} KB'.format(size / 1000) if size >= 1000 else '{} bytes'.format(int(size))


def format_label(source):
    hint = source['traits']
    resolution = hint.get('resolution', 0)
    quality = '{}{}'.format(resolution, hint.get('scan', '')) if resolution else 'Resolution unknown'
    if resolution == 2160:
        quality = '4K / ' + quality
    hdr = hint.get('hdr_formats') or ([hint['hdr']] if hint['hdr'] != 'SDR / unknown' else ['HDR/SDR unknown'])
    audio = hint.get('audio_formats') or [hint['audio']]
    return ' · '.join(text(v) for v in [quality, hint.get('codec'), ' + '.join(hdr), ' / '.join(audio),
        ' / '.join(hint.get('channel_layouts') or [hint.get('channels', '')]), 'Atmos' if hint.get('atmos') else '', hint.get('bit_depth'), hint.get('release_type')] if v)


def sizes(source, stage):
    if stage == 'files':
        return size_label(source.get('size')) + ' · file'
    origin = source.get('size_origin', 'Provider estimate')
    total = size_label(source.get('size'))
    total += ' · torrent total' + (' (estimate)' if origin == 'Provider estimate' else '')
    if source.get('file_size'):
        return size_label(source['file_size']) + ' file · ' + total
    return total


def package_label(source, stage):
    if stage == 'files':
        return 'ORIGINAL FILE'
    return {'season': 'SEASON PACK', 'show': 'SHOW PACK'}.get(source.get('package'), 'TORRENT')


def mapping(source):
    context = source.get('search_context') or {}
    canonical, query = context.get('canonical', {}), context.get('source', {})
    if canonical.get('type') == 'episode' and all(type(data.get(key)) is int for data in (canonical, query) for key in ('season', 'episode')):
        return 'Metadata S{:02d} E{:02d} → source S{:02d} E{:02d}'.format(canonical['season'], canonical['episode'], query['season'], query['episode'])
    return ''


def details(source, stage):
    hint = source['traits']
    rows = [('Release' if stage == 'torrents' else 'File', source.get('path') or source['name']),
            ('Formats', format_label(source)), ('Size', sizes(source, stage)),
            ('Size supplied by', source.get('size_origin') or ('Emby library' if source.get('kind') == 'emby' else 'TorBox file' if stage == 'files' else 'Provider estimate')),
            ('Service', 'Emby' if source.get('kind') == 'emby' else 'TorBox'),
            ('Provider', source.get('provider') or ('Emby library' if source.get('kind') == 'emby' else 'TorBox library'))]
    if stage == 'files' and source.get('transfer_name'):
        rows.append(('Torrent', source['transfer_name']))
    if stage == 'files' and source.get('torrent_size'):
        rows.append(('Torrent total', size_label(source['torrent_size'])))
    if source.get('hash'):
        rows.append(('Torrent hash', source['hash']))
    if mapping(source):
        rows.append(('Episode numbering', mapping(source)))
    if byte_size(source.get('size')):
        rows.append(('File bytes' if stage == 'files' else 'Torrent bytes', '{:,.0f}'.format(byte_size(source['size']))))
    origins = hint.get('origins') or {}
    rows.append(('Format hints from', ', '.join('{}: {}'.format(k.replace('_', ' '), v) for k, v in origins.items()) or 'Saved filename/provider hints'))
    note = ('Torrent availability was checked. The matching video file and its size are checked after selection. '
            'A pack total is not the episode size.') if stage == 'torrents' else 'This size belongs to the listed file.'
    return '\n\n'.join('{}\n{}'.format(label, text(value)) for label, value in rows) + '\n\n' + note + '\n\nVideo/audio badges are hints, not a stream probe. Kodi reads the actual tracks during playback.'


def title(media):
    if media.get('type') == 'episode':
        return '{} · S{:02d} E{:02d}'.format(text(media['title']), media['season'], media['episode'])
    return '{}{}'.format(text(media['title']), ' ({})'.format(media['year']) if media.get('year') else '')
