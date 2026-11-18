"""Explicit search overrides. Catalog identities and tracking are never edited."""
import hashlib
import json
import re
from .media import normalized

FIELDS = {'title', 'year', 'season', 'episode', 'episode_offset', 'imdb', 'title_only', 'include', 'exclude'}


def ids(media):
    data = media.get('trakt', {})
    return data.get('ids' if media['type'] == 'movie' else 'show_ids', {})


def identity(media):
    values = ids(media)
    # Never alias split catalogs through an IMDb/TVDB ID shared by both shows.
    for name in ('tmdb', 'trakt', 'tvdb', 'imdb'):
        if values.get(name):
            return [name, str(values[name]), media.get('year') if name in ('imdb', 'tvdb') else None]
    return ['title', normalized(media['title']), media.get('year')]


def scope_key(media, scope):
    if scope not in ('show', 'season', 'episode', 'movie'):
        raise ValueError('Unknown search-filter scope.')
    if (media['type'] == 'movie') != (scope == 'movie'):
        raise ValueError('Search-filter scope does not match this media type.')
    coordinate = []
    if scope in ('season', 'episode'):
        if type(media.get('season')) is not int:
            raise ValueError('Choose the metadata season to customize.')
        coordinate.append(media['season'])
    if scope == 'episode':
        if type(media.get('episode')) is not int:
            raise ValueError('Choose a specific metadata episode to customize.')
        coordinate.append(media['episode'])
    return hashlib.sha256(json.dumps([scope, identity(media), coordinate], sort_keys=True).encode()).hexdigest()


def validate(rules, scope):
    if not isinstance(rules, dict) or set(rules) - FIELDS:
        raise ValueError('Invalid custom search filters.')
    result = {}
    for key, value in rules.items():
        if key in ('title', 'imdb'):
            if not isinstance(value, str) or len(value) > 250 or any(ord(c) < 32 for c in value):
                raise ValueError('Search text is invalid or too long.')
            value = value.strip()
            if not value:
                continue
            if key == 'imdb' and not re.fullmatch(r'tt\d{5,16}', value):
                raise ValueError('Enter an IMDb ID such as tt1877368, without a URL.')
        elif key in ('season', 'episode', 'episode_offset', 'year'):
            if type(value) is not int:
                raise ValueError('Search numbering must be a whole number.')
            low, high = (-9999, 9999) if key == 'episode_offset' else (1870, 2100) if key == 'year' else (0, 9999)
            if not low <= value <= high:
                raise ValueError('Search number is outside the supported range.')
            if key in ('season', 'episode', 'episode_offset') and scope in ('show', 'movie'):
                raise ValueError('Numbering overrides must be scoped to a season or episode.')
            if key == 'episode' and scope != 'episode':
                raise ValueError('An exact source episode needs an episode-specific override.')
        elif key == 'title_only':
            if type(value) is not bool:
                raise ValueError('Invalid provider ID preference.')
        else:
            if not isinstance(value, list) or len(value) > 16:
                raise ValueError('Use at most 16 release-name phrases per filter.')
            if any(not isinstance(v, str) or len(v) > 80 or any(ord(c) < 32 for c in v) for v in value):
                raise ValueError('Release-name phrases are invalid or too long.')
            value = list(dict.fromkeys(v.strip() for v in value if v.strip()))
        result[key] = value
    return result


def saved(db, media, scope):
    return db.search_override(scope_key(media, scope))


def save(db, media, scope, rules):
    db.save_search_override(scope_key(media, scope), validate(rules, scope))


def effective(db, media):
    scopes = ['movie'] if media['type'] == 'movie' else ['show']
    if media['type'] != 'movie' and type(media.get('season')) is int:
        scopes.append('season')
        if media['type'] == 'episode' and type(media.get('episode')) is int:
            scopes.append('episode')
    result = {}
    for scope in scopes:
        result.update(validate(saved(db, media, scope), scope))
    return result


def query_media(media, rules):
    result = dict(media)
    for key in ('title', 'year', 'season', 'episode'):
        if key in rules:
            result[key] = rules[key]
    if media['type'] == 'episode' and 'episode' not in rules:
        result['episode'] = media['episode'] + rules.get('episode_offset', 0)
    if media['type'] == 'episode' and not 0 <= result['episode'] <= 9999:
        raise ValueError('The custom episode offset produces an invalid source episode. Edit the season filters.')
    data = dict(media.get('trakt', {}))
    id_key = 'ids' if media['type'] == 'movie' else 'show_ids'
    if rules.get('title_only'):
        data[id_key] = {}
    elif rules.get('imdb'):
        data[id_key] = {'imdb': rules['imdb']}
    result['trakt'] = data
    # Source title is explicit; do not add broad aliases that undo that choice.
    return result


def _words(text):
    return re.sub(r'[\s._-]+', ' ', text.casefold()).strip()


def release_matches(name, rules):
    text = _words(name)
    return all(_words(v) in text for v in rules.get('include', [])) and not any(_words(v) in text for v in rules.get('exclude', []))


def snapshot(canonical, query):
    return {'canonical': {k: canonical.get(k) for k in ('type', 'title', 'year', 'season', 'episode')},
            'canonical_ids': dict(ids(canonical)),
            'source': {k: query.get(k) for k in ('title', 'year', 'season', 'episode')}}


def matching_media(media, context):
    """Replay a selected file's mapping even after the saved search rules change."""
    if not context:
        return media
    canonical, source = context.get('canonical', {}), context.get('source', {})
    if any(canonical.get(k) != media.get(k) for k in ('type', 'season', 'episode')):
        raise ValueError('This saved source mapping belongs to a different episode. Search again.')
    old_ids, current_ids = context.get('canonical_ids', {}), ids(media)
    shared = {k for k in old_ids.keys() & current_ids.keys() & {'tmdb', 'trakt', 'tvdb', 'imdb'} if old_ids[k] and current_ids[k]}
    strong = shared & {'tmdb', 'trakt'}
    if any(str(old_ids[k]) != str(current_ids[k]) for k in (strong or shared)):
        raise ValueError('This saved source mapping belongs to a different catalog title. Search again.')
    if not strong and (normalized(canonical.get('title', '')) != normalized(media['title']) or (canonical.get('year') and media.get('year') and canonical['year'] != media['year'])):
        raise ValueError('The title metadata changed. Search again to verify its source numbering.')
    if media['type'] == 'episode' and any(type(source.get(k)) is not int or not 0 <= source[k] <= 9999 for k in ('season', 'episode')):
        raise ValueError('Invalid saved source numbering. Search again.')
    result = dict(media)
    result.update({k: source[k] for k in ('title', 'year', 'season', 'episode') if k in source})
    return result


def source_eligible(source, media, rules):
    if not rules or source['kind'] == 'emby':
        return True
    release = source.get('release_name') or ' '.join([source.get('transfer_name', ''), source.get('name', '')])
    if not release_matches(release, rules):
        return False
    if media['type'] == 'episode' and {'season', 'episode', 'episode_offset'} & rules.keys():
        query = query_media(media, rules)
        if source.get('search_context'):
            try:
                previous = matching_media(media, source['search_context'])
            except ValueError:
                return False
            return (query['season'], query['episode']) == (previous['season'], previous['episode'])
        from . import episodes
        return episodes.matches(source.get('path') or source['name'], query, source.get('transfer_name', ''))
    return True
