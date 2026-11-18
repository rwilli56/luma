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
    text = name.lower()
    hdr10 = 'hdr10' in text or 'hdr' in text
    plus = any(value in text for value in ('hdr10+', 'hdr10plus', 'hdr10.plus'))
    dv = bool(re.search(r'\b(?:dv|dovi)\b|dolby[ ._-]?vision', text))
    hdr = 'HDR10+' if plus else ('HDR10' if hdr10 else ('DV' if dv else 'SDR / unknown'))
    audio = next((label for pattern, label in ((r'true[ ._-]?hd', 'TrueHD'), (r'dts', 'DTS'),
                 (r'e[ ._-]?ac[ ._-]?3|ddp|dd\+', 'E-AC-3'), (r'ac[ ._-]?3|dd5', 'AC-3'),
                 (r'aac', 'AAC'), (r'flac', 'FLAC')) if re.search(pattern, text)), 'Audio unknown')
    return {'resolution': 2160 if re.search(r'2160|\b4k\b|\buhd\b', text) else (1080 if '1080' in text else (720 if '720' in text else 0)),
            'hdr': hdr, 'dv_only': dv and not hdr10, 'audio': audio,
            'codec': 'AV1' if 'av1' in text else ('HEVC' if re.search(r'hevc|[xh][ ._-]?265', text) else ('H.264' if re.search(r'[xh][ ._-]?264', text) else ''))}


def source_rank(source, allow_dv=False, lossless=False):
    hint = source['traits']
    # Compatibility first, then resolution and HDR. Never infer a DV base layer.
    compatible = not hint['dv_only'] or allow_dv
    audio = lossless or hint['audio'] not in ('TrueHD', 'DTS')
    return (compatible, audio, hint['resolution'], {'HDR10+': 3, 'HDR10': 2, 'DV': 1}.get(hint['hdr'], 0))


def file_traits(name, parent=''):
    hint, fallback = traits(name), traits(parent)
    for key, empty in (('resolution', 0), ('audio', 'Audio unknown'), ('codec', '')):
        if hint[key] == empty:
            hint[key] = fallback[key]
    if hint['hdr'] == 'SDR / unknown' and not re.search(r'(?i)(?<![a-z])sdr(?![a-z])', name):
        hint['hdr'], hint['dv_only'] = fallback['hdr'], fallback['dv_only']
    return hint


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
            name = file.get('short_name') or episodes.path_parts(path)[-1]
            parent = transfer.get('name') or ''
            if not isinstance(parent, str):
                parent = ''
            if not isinstance(path, str) or not isinstance(name, str):
                continue
            if os.path.splitext(name)[1].lower() not in VIDEO_EXTENSIONS or episodes.is_disc_segment(path) or episodes.is_extra(path, episodes.parent_title('', parent)):
                continue
            media = parse_name(path, parent)
            if media['ambiguous']:
                continue
            try:
                size = float(file.get('size') or 0)
                size = size if math.isfinite(size) and size >= 0 else 0
            except (ValueError, TypeError):
                size = 0
            source = {'kind': kind, 'transfer_id': transfer['id'], 'file_id': file['id'],
                      'name': name, 'size': size, 'ready': ready,
                      'traits': file_traits(name, parent), 'state': transfer.get('download_state', 'unknown'),
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
