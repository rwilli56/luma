"""Consistent filename-based source preferences for search and library playback."""
import re
from . import preferences as prefs
from .media import EPISODE, source_rank


def options():
    keys = ('min_resolution', 'max_resolution', 'movie_size', 'episode_size', 'exclude_cam', 'exclude_dv',
            'exclude_av1', 'source_sort', 'allow_dv', 'prefer_lossless')
    result = {key: prefs.get(key) for key in keys}
    if int(result['min_resolution']) > int(result['max_resolution']):
        raise ValueError('Minimum resolution exceeds Maximum resolution. Check Sort & Filter settings.')
    return result


def apply(sources, media_type, settings=None, torrent_results=False):
    settings = settings or options()
    result = []
    for source in sources:
        hint, name = source['traits'], source.get('name', '')
        resolution = hint['resolution']
        if resolution < int(settings['min_resolution']) or resolution > int(settings['max_resolution']):
            continue
        if settings['exclude_cam'] and re.search(r'(?i)(?:^|[ ._\-])(?:cam|hdcam|telesync|hdts|hdtc)(?:$|[ ._\-])', name):
            continue
        if settings['exclude_dv'] and hint['dv_only'] or settings['exclude_av1'] and hint['codec'] == 'AV1':
            continue
        size_limit = settings['movie_size' if media_type == 'movie' else 'episode_size']
        pack = torrent_results and media_type == 'episode' and not EPISODE.search(name.replace('_', ' '))
        if size_limit and not pack and source.get('size', 0) > size_limit * 1e9:
            continue
        result.append(source)
    def rank(source):
        base = source_rank(source, settings['allow_dv'], settings['prefer_lossless'])
        size = source.get('size', 0)
        if settings['source_sort'] == 'small':
            return base[:2] + (-size,) + base[2:]
        if settings['source_sort'] == 'large':
            return base[:2] + (size,) + base[2:]
        return base
    return sorted(result, key=rank, reverse=True)
