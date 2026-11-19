"""Filename hints are for local grouping. Trakt identification is always explicit."""
import hashlib
import os
import re
import math

VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.m4v', '.mov', '.avi', '.ts', '.m2ts', '.webm'}
EPISODE = re.compile(r'(?i)(?:\bS(\d{1,2})[ ._-]*E(\d{1,3})\b|\b(\d{1,2})x(\d{2,3})\b)')
QUALITY = re.compile(r'(?i)\b(?:2160p|1080p|720p|480p|4k|uhd|bluray|blu-ray|b[dr]rip|web[ ._-]?(?:dl|rip)|hdtv|remux|x26[45]|h[ .]?26[45]|hevc|av1|hdr10\+?|hdr10plus|hdr|sdr|dv|dovi|dolby[ ._-]?vision|aac|dts|truehd|atmos|ddp|eac3|ac3)\b')


def normalized(text):
    return re.sub(r'[^\w]+', ' ', text.casefold(), flags=re.UNICODE).strip()


def identity(title, year=None, season=None, episode=None):
    value = '{}|{}|{}|{}'.format(normalized(title), year or '', season if season is not None else '', episode if episode is not None else '')
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]


def parse_name(filename, parent=''):
    from . import episodes
    path = '/'.join(episodes.path_parts(filename))
    stem = os.path.splitext(path.rsplit('/', 1)[-1])[0]
    text = stem.replace('.', ' ').replace('_', ' ')
    info = episodes.inspect(path, parent)
    ambiguous = info['ambiguous'] or info['conflict']
    season, episode = info['season'], info['episode']
    if season is not None:
        title = text[:info['offset']].strip(' -[]()') if info['offset'] is not None else ''
        if not title:
            title = episodes.parent_title(path, parent)
    else:
        quality = QUALITY.search(text)
        title = text[:quality.start()] if quality else text
    year_match = re.search(r'\b((?:19|20)\d{2})\b', title)
    year = int(year_match.group(1)) if year_match else None
    if year_match:
        title = title[:year_match.start()]
    title = title.strip(' -[]()') or stem
    return {'key': identity(title, year, season, episode), 'title': title, 'year': year,
            'season': season, 'episode': episode, 'type': 'episode' if season is not None else 'movie',
            'show_key': identity(title, year) if season is not None else '', 'ambiguous': ambiguous}


def traits(name):
    """Conservative release-name hints, never a claim about probed stream tracks."""
    text = name.casefold()
    def token(pattern):
        return bool(re.search(r'(?<![a-z0-9])(?:' + pattern + r')(?![a-z0-9])', text))
    plus = token(r'hdr10(?:\+|[ ._-]?plus)')
    hdr10 = plus or token(r'hdr10')
    dv = token(r'dv|dovi|dolby[ ._-]?vision')
    hdr = 'HDR10+' if plus else 'HDR10' if hdr10 else 'HLG' if token('hlg') else 'HDR (unspecified)' if token('hdr') else 'DV' if dv else 'SDR' if token('sdr') else 'SDR / unknown'
    formats = ([hdr] if hdr not in ('SDR / unknown', 'DV') else []) + (['DV'] if dv else [])
    audio = []
    patterns = ((r'true[ ._-]?hd', 'TrueHD'),
                (r'dts[ ._-]?(?:hd[ ._-]?)?ma', 'DTS-HD MA'), (r'dts[ ._-]?hd[ ._-]?hra', 'DTS-HD HRA'),
                (r'dts[ ._:-]?x', 'DTS:X'), (r'dts[ ._-]?hd', 'DTS-HD'), (r'dts', 'DTS'),
                (r'e[ ._-]?ac[ ._-]?3|ddp(?:[ ._-]?[1-8][ .][01])?|dd\+(?:[ ._-]?[1-8][ .][01])?', 'E-AC-3'),
                (r'ac[ ._-]?3|dd(?!\+)(?:[ ._-]?[1-8][ .][01])?', 'AC-3'), (r'aac(?:[1-8][ .][01])?', 'AAC'),
                (r'flac', 'FLAC'), (r'l?pcm', 'PCM'), (r'opus', 'Opus'), (r'mp3', 'MP3'))
    for pattern, label in patterns:
        if token(pattern) and not (label in ('DTS-HD', 'DTS') and any(a.startswith('DTS') for a in audio)):
            audio.append(label)
    channels = list(dict.fromkeys('.'.join(v for v in m.groups() if v) for m in re.finditer(r'(?<!\d)([12567])[ .]([01])(?:[ .]([24]))?(?!\d)', text)))
    resolution = next((value for pattern, value in ((r'4320p?|8k', 4320), (r'2160p?|4k|uhd', 2160),
                      (r'1080[pi]?', 1080), (r'720p?', 720), (r'576[pi]?', 576), (r'480[pi]?', 480)) if token(pattern)), 0)
    scan = re.search(r'(?<![a-z0-9])(?:4320|2160|1080|720|576|480)([pi])(?![a-z0-9])', text)
    return {'resolution': resolution, 'scan': scan.group(1) if scan else '', 'hdr': hdr, 'hdr_formats': formats, 'dv_only': dv and not hdr10,
            'audio': audio[0] if audio else 'Audio unknown', 'audio_formats': audio,
            'atmos': token(r'atmos'), 'channels': channels[0] if channels else '', 'channel_layouts': channels,
            'codec': 'AV1' if token('av1') else 'HEVC' if token(r'hevc|[xh][ ._-]?265') else 'H.264' if token(r'avc|[xh][ ._-]?264') else '',
            'bit_depth': '12-bit' if token(r'12[ ._-]?bit') else '10-bit' if token(r'10[ ._-]?bit') else '8-bit' if token(r'8[ ._-]?bit') else '',
            'release_type': next((label for pattern, label in ((r'remux', 'REMUX'), (r'web[ ._-]?dl', 'WEB-DL'),
                (r'web[ ._-]?rip', 'WEBRip'), (r'blu[ ._-]?ray|b[dr]rip', 'Blu-ray'), (r'hdtv', 'HDTV')) if token(pattern)), '')}


def source_rank(source, allow_dv=False, lossless=False):
    hint = source['traits']
    # Compatibility first, then resolution and HDR. Never infer a DV base layer.
    compatible = not hint['dv_only'] or allow_dv
    audio = lossless or not (hint['audio'] == 'TrueHD' or hint['audio'].startswith('DTS'))
    return (compatible, audio, hint['resolution'], {'HDR10+': 3, 'HDR10': 2, 'DV': 1}.get(hint['hdr'], 0))


def file_traits(name, parent=''):
    from .episodes import path_parts
    parts = path_parts(name)
    hint = traits(parts[-1] if parts else '')
    groups = (('resolution', 'scan'), ('audio', 'audio_formats', 'atmos', 'channels', 'channel_layouts'), ('codec',),
              ('hdr', 'hdr_formats', 'dv_only'), ('bit_depth',), ('release_type',))
    def missing(data, group):
        return data[group[0]] in (0, '', 'Audio unknown', 'SDR / unknown') and not (group[0] == 'audio' and (data['atmos'] or data['channel_layouts']))
    origins = {g[0]: 'filename' for g in groups if not missing(hint, g)}
    for text, origin in [(p, 'folder') for p in reversed(parts[:-1])] + [(parent, 'release')]:
        fallback = traits(text)
        for group in groups:
            if missing(hint, group) and not missing(fallback, group):
                hint.update({key: fallback[key] for key in group})
                origins[group[0]] = origin
    hint['origins'] = origins
    return hint


def byte_size(value, multiplier=1):
    """Unknown/malformed sizes stay unknown rather than becoming NaN/Infinity."""
    if isinstance(value, bool):
        return 0
    try:
        size = float(value) * multiplier
        return size if math.isfinite(size) and 0 < size <= 2 ** 63 - 1 else 0
    except (ValueError, TypeError, OverflowError):
        return 0


def flatten(transfers, kind):
    from . import episodes
    result = []
    for transfer in transfers:
        if not isinstance(transfer, dict) or transfer.get('id') is None:
            continue
        ready = transfer.get('download_finished') is True and transfer.get('download_present') is True
        for file in transfer.get('files') or []:
            if not isinstance(file, dict) or file.get('id') is None:
                continue
            path = file.get('name') or file.get('short_name') or ''
            parent = transfer.get('name') or ''
            if not isinstance(parent, str):
                parent = ''
            if not isinstance(path, str) or not episodes.path_parts(path):
                continue
            # Full path is authoritative; a conflicting short_name is only a label.
            name = episodes.path_parts(path)[-1]
            if os.path.splitext(name)[1].lower() not in VIDEO_EXTENSIONS or episodes.is_disc_segment(path) or episodes.is_extra(path, episodes.parent_title('', parent)):
                continue
            media = parse_name(path, parent)
            if media['ambiguous']:
                continue
            size = byte_size(file.get('size'))
            source = {'kind': kind, 'transfer_id': transfer['id'], 'file_id': file['id'],
                      'name': name, 'size': size, 'ready': ready,
                      'traits': file_traits(path, parent), 'state': transfer.get('download_state', 'unknown'),
                      'size_scope': 'file', 'size_origin': 'TorBox file', 'torrent_size': byte_size(transfer.get('size')),
                      'path': path, 'transfer_name': parent, 'hash': transfer.get('hash', '')}
            media['sources'] = [source]
            result.append(media)
    return result


def merge_library(items):
    grouped = {}
    for item in items:
        if item['key'] in grouped:
            grouped[item['key']]['sources'].extend(item['sources'])
        else:
            grouped[item['key']] = dict(item)
    return list(grouped.values())


def episode_label(item):
    if item.get('season') is not None:
        return 'S{:02d} E{:02d}'.format(item['season'], item['episode'])
    return str(item.get('year') or 'Movie')
