"""Filename hints are for local grouping. Trakt identification is always explicit."""
import hashlib
import os
import re

VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.m4v', '.mov', '.avi', '.ts', '.m2ts', '.webm'}
EPISODE = re.compile(r'(?i)(?:\bS(\d{1,2})[ ._-]*E(\d{1,3})\b|\b(\d{1,2})x(\d{2,3})\b)')
QUALITY = re.compile(r'(?i)\b(?:2160p|1080p|720p|480p|4k|uhd|bluray|blu-ray|b[dr]rip|web[ ._-]?(?:dl|rip)|hdtv|remux|x26[45]|h[ .]?26[45]|hevc|av1|hdr10\+?|hdr10plus|hdr|sdr|dv|dovi|dolby[ ._-]?vision|aac|dts|truehd|atmos|ddp|eac3|ac3)\b')


def normalized(text):
    return re.sub(r'[^\w]+', ' ', text.casefold(), flags=re.UNICODE).strip()


def identity(title, year=None, season=None, episode=None):
    value = '{}|{}|{}|{}'.format(normalized(title), year or '', season if season is not None else '', episode if episode is not None else '')
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]


def parse_name(filename, parent=''):
    stem = os.path.splitext(filename.replace('\\', '/').rsplit('/', 1)[-1])[0]
    text = stem.replace('.', ' ').replace('_', ' ')
    # S01E01E02 and episode ranges cannot safely be represented by one resume point.
    ambiguous = bool(re.search(r'(?i)S\d{1,2}E\d{1,3}(?:E\d{1,3}\b|\s*-\s*E?\d{1,3}\b)', text))
    match = EPISODE.search(text)
    season = episode = None
    if match:
        season, episode = int(match.group(1) or match.group(3)), int(match.group(2) or match.group(4))
        title = text[:match.start()].strip(' -[]()')
        if not title:
            title = re.split(r'(?i)\b(?:S\d{1,2}|Season)\b', parent.replace('.', ' '))[0].strip(' -[]()')
    else:
        quality = QUALITY.search(text)
        title = text[:quality.start()] if quality else text
    year_match = re.search(r'\b((?:19|20)\d{2})\b', title)
    year = int(year_match.group(1)) if year_match else None
    if year_match:
        title = title[:year_match.start()]
    title = title.strip(' -[]()') or stem
    return {'key': identity(title, year, season, episode), 'title': title, 'year': year,
            'season': season, 'episode': episode, 'type': 'episode' if match else 'movie',
            'show_key': identity(title, year) if match else '', 'ambiguous': ambiguous}


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


def flatten(transfers, kind):
    result = []
    for transfer in transfers:
        ready = transfer.get('download_finished') is True and transfer.get('download_present') is True
        for file in transfer.get('files') or []:
            name = file.get('short_name') or file.get('name') or ''
            if os.path.splitext(name)[1].lower() not in VIDEO_EXTENSIONS or re.search(r'(?i)(?:^|[ ._/-])sample(?:[ ._/-]|$)', name):
                continue
            media = parse_name(name, transfer.get('name', ''))
            if media['ambiguous']:
                continue
            source = {'kind': kind, 'transfer_id': transfer['id'], 'file_id': file['id'],
                      'name': name, 'size': file.get('size', 0), 'ready': ready,
                      'traits': traits(name), 'state': transfer.get('download_state', 'unknown')}
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
