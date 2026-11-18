"""TV-remote editor for persistent title, numbering and release-name overrides."""
import time
import xbmc
import xbmcgui
from . import config, search_rules
from .media import identity


def ask(heading, value=''):
    keyboard = xbmc.Keyboard(str(value if value is not None else ''), heading)
    keyboard.doModal()
    return keyboard.getText().strip() if keyboard.isConfirmed() else None


def attach(item, media, season=None, db=None):
    """Keep context metadata off RunPlugin's command string."""
    from .app import route
    db = db or config.store()
    key = identity(media['type'] + str(search_rules.identity(media)), None, season if season is not None else media.get('season'), media.get('episode'))
    db.put('search_item:' + key, {'media': media, 'season': season})
    item.addContextMenuItems([('Custom search filters…', 'RunPlugin({})'.format(route('custom_search', key=key)))])


def show_context(obj):
    key = identity(obj['title'], obj.get('year'))
    return {'key': key, 'title': obj['title'], 'year': obj.get('year'), 'type': 'tvshow',
            'season': None, 'episode': None, 'show_key': key, 'trakt': {'show_ids': obj['ids']}}


def edit(media, season_hint=None):
    db = config.store()
    target = dict(media)
    if media['type'] == 'movie':
        scope = 'movie'
    elif season_hint is not None:
        scope, target = 'season', dict(media, type='tvshow', season=int(season_hint), episode=None)
    else:
        scopes = [('season', 'This season · {}'.format(media['season'])), ('episode', 'Only S{:02d} E{:02d}'.format(media['season'], media['episode'])),
                  ('show', 'Whole show · title and release filters')] if media['type'] == 'episode' else [
                  ('show', 'Whole show · title and release filters'), ('choose_season', 'Choose a metadata season…')]
        chosen = xbmcgui.Dialog().select('Apply custom search filters to', [label for _, label in scopes])
        if chosen < 0:
            return False
        scope = scopes[chosen][0]
        if scope == 'choose_season':
            number = ask('Metadata season to customize', media.get('season') or 1)
            if number is None:
                return False
            try:
                number = int(number)
                if not 0 <= number <= 9999:
                    raise ValueError()
            except ValueError:
                raise ValueError('Enter a metadata season from 0 to 9999.') from None
            scope, target = 'season', dict(media, type='tvshow', season=number, episode=None)
        elif scope == 'show':
            target = dict(media, type='tvshow', season=None, episode=None)
        elif scope == 'season':
            target = dict(media, type='tvshow', episode=None)
    draft = dict(search_rules.saved(db, target, scope))
    inherited = {}
    if scope in ('season', 'episode'):
        inherited.update(search_rules.saved(db, target, 'show'))
    if scope == 'episode':
        inherited.update(search_rules.saved(db, target, 'season'))
    while True:
        combined = dict(inherited, **draft)
        query = search_rules.query_media(target, combined)
        fields = [('title', 'Search title', query['title']), ('year', 'Search year', query.get('year') or '')]
        if scope in ('season', 'episode'):
            fields.append(('season', 'Search season · metadata {}'.format(target['season']), query['season']))
            fields.append(('episode_offset', 'Source episode offset', combined.get('episode_offset', 0)))
        if scope == 'episode':
            fields.append(('episode', 'Search episode · metadata {}'.format(target['episode']), query['episode']))
        fields += [('title_only', 'Use title-only provider searches', 'Yes' if combined.get('title_only') else 'No'),
                   ('imdb', 'Provider IMDb ID', combined.get('imdb') or 'Use metadata IDs'),
                   ('include', 'Required release phrases · all must match', ', '.join(combined.get('include', [])) or 'None'),
                   ('exclude', 'Excluded release phrases · any match', ', '.join(combined.get('exclude', [])) or 'None')]
        actions = [('save', 'Save filters')]
        if media['type'] in ('movie', 'episode') and not xbmc.Player().isPlaying():
            actions.append(('search', 'Save and find sources now'))
        actions += [('reset', 'Reset this scope to inherited defaults'), ('help', 'How numbering and provider IDs work')]
        label = 'Custom search · {}{}'.format(media['title'], ' · metadata season {}'.format(target['season']) if scope in ('season', 'episode') else '')
        chosen = xbmcgui.Dialog().select(label, ['{}: {}'.format(text, value) for _, text, value in fields] + [text for _, text in actions])
        if chosen < 0:
            return False
        if chosen >= len(fields):
            action = actions[chosen - len(fields)][0]
            if action == 'help':
                xbmcgui.Dialog().textviewer('Custom search filters',
                    'These settings change provider searches and pack-file matching. The title, episode IDs and numbering used by Trakt/local watch history stay as selected.\n\n'
                    'Example: for metadata season 17, set Search season to 10 for sources using restarted numbering. '
                    'For split catalogs, also check the source title/year and provider IDs. Title-only mode clears provider IDs; an explicit IMDb ID replaces them. '
                    'An IMDb ID shared by two catalog entries is not proof that their season numbering agrees.\n\n'
                    'A season override affects only that metadata season. Episode-specific settings take precedence. '
                    'Use an episode offset only when episode numbers also differ. Whole-show settings cover title and release filters.\n\n'
                    'Separate release phrases with commas. Matching is literal and case-insensitive; dots, underscores, hyphens and spaces are equivalent. '
                    'All required phrases must appear; any excluded phrase removes a result. Global playback filters still apply.\n\n'
                    'Reset changes the draft. Save applies it; Back cancels all unsaved changes. Existing confirmed file mappings remain valid after filters are reset.')
            elif action == 'reset':
                draft = {}
            else:
                search_rules.save(db, target, scope, draft)
                db.put('ui_revision', time.time())
                if action == 'search':
                    from .search import find_sources
                    from .app import route
                    selected = find_sources(media)
                    if selected:
                        xbmc.executebuiltin('PlayMedia("{}")'.format(route('play', key=selected['key'])))
                        return 'play'
                return True
            continue
        key, text, current = fields[chosen]
        if key == 'title_only':
            draft[key] = not combined.get(key, False)
            continue
        value = ask(text, ', '.join(combined.get(key, [])) if key in ('include', 'exclude') else combined.get(key, '') if key == 'imdb' else current)
        if value is None:
            continue
        updated = dict(draft)
        try:
            if key in ('include', 'exclude'):
                updated[key] = [v.strip() for v in value.split(',') if v.strip()]
            elif value == '':
                updated.pop(key, None)
            elif key in ('year', 'season', 'episode', 'episode_offset'):
                updated[key] = int(value)
                if key == 'episode_offset':
                    updated.pop('episode', None)
            else:
                updated[key] = value
            updated = search_rules.validate(updated, scope)
            search_rules.query_media(target, dict(inherited, **updated))
            draft = updated
        except ValueError as exc:
            xbmcgui.Dialog().ok('Custom search filters', str(exc) if str(exc) else 'Enter a valid whole number.')


def run(key):
    context = config.store().get('search_item:' + key)
    if not context:
        raise ValueError('This context menu expired. Open the parent list again.')
    return edit(context['media'], context.get('season'))
