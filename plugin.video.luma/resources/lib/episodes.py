"""Conservative episode/file matching; paths supply season context, never dates.

These routines identify coordinates, not alternate episode numbering schemes.
"""
import datetime
import re
from urllib.parse import unquote

LEFT, RIGHT = r'(?<![a-z0-9])', r'(?![0-9])'
FULL = re.compile(r'(?<!\d)(?:s(\d{1,4})[ ._-]*e(?:p(?:isode)?)?[ ._-]*(\d{1,4})|'
                  r'(\d{1,2})x(\d{1,4})|season[ ._-]*(\d{1,4})[ ._-]*episode[ ._-]*(\d{1,4}))' + RIGHT, re.I)
EP_ONLY = re.compile(LEFT + r'(?:episode|ep|e)[ ._-]*(\d{1,4})' + RIGHT, re.I)
SEASON = re.compile(LEFT + r'(?:seasons?|s)[ ._-]*(\d{1,4})(?!\d)', re.I)
SEASON_RANGE = re.compile(LEFT + r'(?:seasons?|s)[ ._-]*(\d{1,4})\s*[-–]\s*(?:seasons?|s)?[ ._-]*(\d{1,4})(?!\d)', re.I)
AIRDATE = re.compile(r'(?<!\d)((?:19|20)\d{2})[ ._-](\d{2})[ ._-](\d{2})(?!\d)')
EXTRAS = re.compile(r'(?i)(?:^|[ ._\-/])(?:samples?|trailers?|extras?|featurettes?|bonus|bloopers|deleted[ ._-]*scenes|behind[ ._-]*the[ ._-]*scenes|interviews?)(?:$|[ ._\-/])')


def path_parts(path):
    return unquote(str(path or '')).replace('\\', '/').split('/')


def seasons(text):
    text = unquote(text or '').replace('_', ' ')
    values = {int(m.group(1)) for m in SEASON.finditer(text)}
    for match in SEASON_RANGE.finditer(text):
        start, end = map(int, match.groups())
        if 0 <= end - start <= 99:
            values.update(range(start, end + 1))
    # Also recognize seasons in 2x03 notation.
    for match in FULL.finditer(text):
        if match.group(3):
            values.add(int(match.group(3)))
    return values


def _coordinates(match):
    groups = match.groups()
    return next((int(groups[i]), int(groups[i + 1])) for i in (0, 2, 4) if groups[i] is not None)


def inspect(path, parent=''):
    parts = path_parts(path)
    filename = parts[-1].replace('_', ' ')
    full = list(FULL.finditer(filename))
    coordinates = {_coordinates(m) for m in full}
    single = list(EP_ONLY.finditer(filename)) if not full else []
    ambiguous = len(coordinates) > 1 or len({int(m.group(1)) for m in single}) > 1
    marker = full[0] if full else single[0] if single else None
    if marker:
        tail = filename[marker.end():]
        # Reject combined/ranged files, including S01E01E02, 1x01-02 and EP01 & 02.
        ambiguous |= bool(re.match(r'(?:[ ._]*e(?:p(?:isode)?)?[ ._-]*\d+|[ ._]*[-–&+][ ._]*(?:e(?:p(?:isode)?)?[ ._-]*)?\d+)(?![a-z0-9])', tail, re.I))
    contexts = ['/'.join(parts[:-1]), parent]
    scopes = [seasons(c) for c in contexts if seasons(c)]
    context = set.intersection(*scopes) if scopes else set()
    conflict = bool(scopes and not context)
    season, episode = next(iter(coordinates)) if len(coordinates) == 1 else (None, None)
    if season is not None and scopes and any(season not in scope for scope in scopes):
        conflict = True
    if not full and len(context) == 1:
        if single:
            season, episode = next(iter(context)), int(single[0].group(1))
        else:
            # A bare number is usable only in an explicitly single-season folder.
            bare = re.match(r'^\s*(\d{1,3})(?=[ ._-]|$)', filename)
            if bare:
                season, episode = next(iter(context)), int(bare.group(1))
                marker = bare
    dates = []
    for match in AIRDATE.finditer(filename):
        try:
            dates.append(datetime.date(*map(int, match.groups())).isoformat())
        except ValueError:
            pass
    return {'season': season, 'episode': episode, 'ambiguous': bool(ambiguous), 'conflict': conflict,
            'explicit': bool(full), 'episode_only': int(single[0].group(1)) if single else None,
            'dates': dates, 'context': context, 'offset': marker.start() if marker else None}


def matches(path, media, parent=''):
    info = inspect(path, parent)
    if info['ambiguous'] or info['conflict']:
        return False
    requested = (media.get('season'), media.get('episode'))
    if info['season'] is not None:
        return (info['season'], info['episode']) == requested
    # A dated parent folder never substitutes for a filename's air date.
    premiered = media.get('premiered', '')[:10]
    try:
        datetime.date.fromisoformat(premiered)
    except (ValueError, TypeError):
        return False
    if info['episode_only'] is not None and info['episode_only'] != media.get('episode'):
        return False
    if info['context'] and media.get('season') not in info['context']:
        return False
    return bool(info['dates']) and set(info['dates']) == {premiered}


def manual_candidate(path, media, parent=''):
    info = inspect(path, parent)
    if info['ambiguous'] or info['conflict'] or info['explicit'] or info['dates']:
        return False
    if info['season'] is not None:
        return (info['season'], info['episode']) == (media.get('season'), media.get('episode'))
    if info['episode_only'] is not None and info['episode_only'] != media.get('episode'):
        return False
    return not info['context'] or media.get('season') in info['context']


def is_extra(path, title=''):
    parts = path_parts(path)
    title_words = re.sub(r'[^a-z0-9]+', '.', title.lower()).strip('.')
    title_words = re.sub(r'\.(?:19|20)\d{2}$', '', title_words)
    for component in parts:
        text = re.sub(r'[^a-z0-9]+', '.', component.lower()).strip('.')
        # Keep actual titles such as Extras and Trailer Park Boys.
        if title_words and (text == title_words or text.startswith(title_words + '.')):
            text = text[len(title_words):].lstrip('.')
        if EXTRAS.search(text):
            return True
    return False


def is_disc_segment(path):
    return any(part.casefold() in ('bdmv', 'video_ts') for part in path_parts(path)[:-1])


def parent_title(path, parent):
    candidates = [parent] + [part for part in path_parts(path)[:-1] if part]
    for candidate in candidates:
        text = candidate.replace('.', ' ').replace('_', ' ')
        text = re.split(r'(?i)(?<![a-z0-9])(?:s\d+|seasons?\b|complete\b|2160p|1080p|720p)', text)[0].strip(' -[]()/')
        if text:
            return text
    return ''


def package(name, declared=None):
    if declared in ('show', 'season'):
        return declared
    if re.search(r'(?i)\bcomplete[ ._-]*(?:series|show)\b', name) or len(seasons(name)) > 1:
        return 'show'
    if seasons(name) and not FULL.search(name):
        return 'season'
    return None
