"""Kodi directories for the main menu, catalogs, seasons and personal lists."""
import datetime
import xbmc
import xbmcgui
import xbmcplugin
from . import config, menus, preferences as prefs
from .catalog import Catalog
from .explore import Explorer, get_object, save_object, title_object
from .library import home_rows, match_media
from .trakt import Trakt
from .custom_search import attach as custom_context, show_context


def client(db):
    return Trakt(db, config.setting('trakt_client_id'), config.setting('trakt_client_secret'),
                 should_defer=xbmc.Player().isPlaying, allow_refresh=False)


def render(handle, params):
    from .app import route
    db = config.store()
    name, kind = params.get('name', 'root'), params.get('kind', 'movie')
    if kind not in ('movie', 'show'):
        raise ValueError('Unknown media type.')
    page, value = int(params.get('page', '1')), params.get('value')
    entries, content = [], 'files'
    explorer = Explorer(db, client(db))

    def add(label, action='menu', folder=True, description='', context_media=None, context_season=None, **args):
        item = xbmcgui.ListItem(label=label)
        if description:
            item.getVideoInfoTag().setPlot(description)
        if context_media:
            custom_context(item, context_media, context_season, db)
        entries.append((route(action, **args), item, folder))

    def rows(items, more=False):
        nonlocal content
        content = 'tvshows' if kind == 'show' else 'movies'
        watched = [i for i in db.history() if i.get('completed')]
        for obj in items:
            obj_kind = obj.get('catalog_type', kind)
            key = save_object(db, obj)
            if obj_kind == 'list':
                add(obj.get('name', 'List'), name='catalog', category='list_items', kind=kind, key=key)
                continue
            if obj_kind == 'show':
                add('{} ({})'.format(obj['title'], obj.get('year') or '?'), name='seasons', key=key, kind='show', description=obj.get('overview', ''), context_media=show_context(obj))
                continue
            media = Catalog.media(obj['show'], obj) if obj_kind == 'episode' else Catalog.media(obj)
            if prefs.get('hide_watched') and name in ('catalog', 'episodes') and params.get('category') != 'history' and match_media(media, watched):
                continue
            label = '{} · S{:02d} E{:02d} · {}'.format(media['title'], media['season'], media['episode'], media.get('episode_title') or '') if obj_kind == 'episode' else '{} ({})'.format(media['title'], media.get('year') or '?')
            item = xbmcgui.ListItem(label=label)
            item.setProperty('IsPlayable', 'true')
            custom_context(item, media, db=db)
            tag = item.getVideoInfoTag()
            tag.setTitle(media.get('episode_title') or media['title'])
            tag.setMediaType('episode' if obj_kind == 'episode' else 'movie')
            tag.setPlot(media.get('overview', ''))
            if media.get('year'):
                tag.setYear(media['year'])
            if obj_kind == 'episode':
                tag.setTvShowTitle(media['title']); tag.setSeason(media['season']); tag.setEpisode(media['episode'])
            entries.append((route('catalog_play', key=key), item, False))
        if more:
            args = dict(params, page=page + 1)
            args.pop('action', None)
            add('Next page →', **args)

    def local(items):
        from .app import decorate
        nonlocal content
        content = 'videos'
        for media in items:
            if media['type'] == 'tvshow':
                ids = media.get('trakt', {}).get('show_ids', {})
                if ids:
                    obj = dict(title=media['title'], year=media.get('year'), ids=ids, catalog_type='show',
                               catalog='trakt' if ids.get('trakt') else 'cinemeta')
                    add(media['title'], name='seasons', kind='show', key=save_object(db, obj), context_media=show_context(obj))
                else:
                    add(media['title'], action='series', key=media['show_key'], context_media=media)
            else:
                item = decorate(media)
                item.setProperty('IsPlayable', 'true')
                custom_context(item, media, db=db)
                entries.append((route('play', key=media['key']), item, False))

    if name == 'root':
        for label, target in menus.ROOT:
            add(label, action='tool' if target == 'dashboard' else 'menu', folder=target != 'dashboard', name=target)
    elif name.startswith('discover_'):
        kind = 'movie' if name == 'discover_movies' else 'show'
        for label, target in menus.discovery(kind):
            node = target if target in ('genres', 'years', 'networks', 'actor') else 'search_history' if target == 'query' else 'catalog'
            add(label, name=node, kind=kind, category=target)
    elif name in ('my_movies', 'my_shows'):
        kind = 'movie' if name == 'my_movies' else 'show'
        for label, category in menus.MY_MOVIES if kind == 'movie' else menus.MY_SHOWS:
            add(label, name='local' if category in ('continue', 'next', 'recent') else 'catalog', category=category, kind=kind)
    elif name == 'local':
        category = params.get('category', 'continue')
        items = home_rows(db)[{'continue': 'continue', 'next': 'next', 'recent': 'shows'}[category]]
        local([i for i in items if (i['type'] == 'movie') == (kind == 'movie')])
    elif name == 'files':
        add('TorBox', action='library')
        add('Emby', action='emby')
        add('Add a magnet or file link', action='tool', folder=False, name='add_link')
        add('Download Manager', action='tool', folder=False, name='downloads')
    elif name == 'search':
        for label, target, media_kind in [('Search Movies', 'search_history', 'movie'), ('Search Shows', 'search_history', 'show'),
                                           ('Search Movies By Actor', 'actor', 'movie'), ('Search Shows By Actor', 'actor', 'show')]:
            add(label, name=target, kind=media_kind)
    elif name in ('search_history', 'actor'):
        if name == 'search_history' and prefs.get('search_history'):
            add('New search…', name='catalog', kind=kind, category='query')
            for query in db.get('search_history:' + kind, []):
                add(query, name='catalog', kind=kind, category='query', value=query)
        else:
            if not value:
                value = xbmcgui.Dialog().input('Search by actor' if name == 'actor' else 'Search title').strip()
            if value:
                if name == 'actor':
                    people = explorer.fetch('/search/person', {'query': value, 'limit': prefs.get('page_size')})
                    for person in people:
                        obj = person['person']
                        add(obj['name'], name='catalog', kind=kind, category='actor_credits', value=obj['ids']['trakt'])
                else:
                    found, more = explorer.page(kind, 'query', page, value)
                    params = dict(params, value=value)
                    rows(found, more)
    elif name in ('genres', 'networks', 'years'):
        if name == 'years':
            options = [{'name': str(y), 'slug': str(y)} for y in range(datetime.date.today().year + 1, 1899, -1)]
        elif name == 'genres':
            options = explorer.genres(kind)
        else:
            options = explorer.fetch('/networks')
            options = [{'name': n, 'slug': n} if isinstance(n, str) else dict(n, slug=n['name']) for n in options]
        for option in options:
            add(option['name'], name='catalog', kind=kind, category={'genres': 'genre', 'years': 'year', 'networks': 'network'}[name], value=option['slug'])
    elif name == 'seasons':
        show = get_object(db, params['key'])
        episodes = explorer.catalog.episodes(show)
        content = 'seasons'
        for season in sorted({e['season'] for e in episodes}):
            if season == 0 and prefs.get('hide_specials'):
                continue
            add('Specials' if season == 0 else 'Season {}'.format(season), name='episodes', kind='show', key=params['key'], season=season,
                context_media=show_context(show), context_season=season)
    elif name == 'episodes':
        show = get_object(db, params['key'])
        episodes = explorer.catalog.season(show, int(params['season']), explorer.catalog.episodes(show))
        rows([dict(e, show=show, catalog_type='episode', catalog=show['catalog']) for e in episodes])
        content = 'episodes'
    elif name == 'catalog':
        category = params.get('category', 'popular')
        if category == 'query' and not value:
            value = xbmcgui.Dialog().input('Search movies' if kind == 'movie' else 'Search shows').strip()
        if category == 'query' and value and prefs.get('search_history'):
            prior = db.get('search_history:' + kind, [])
            db.put('search_history:' + kind, [value] + [v for v in prior if v != value][:29])
        if category != 'query' or value:
            if category == 'history' and not explorer.trakt.connected:
                local([i for i in db.history() if i.get('completed') and (i['type'] == 'movie') == (kind == 'movie')])
            else:
                found, more = explorer.page(kind, category, page, value, get_object(db, params['key']) if params.get('key') else None)
                # Keep typed queries when following pagination.
                if value:
                    params = dict(params, value=value)
                rows(found, more)
    elif name in ('tools', 'providers', 'trakt_tools', 'services'):
        options = menus.TOOLS if name == 'tools' else menus.PROVIDERS if name == 'providers' else menus.TRAKT_TOOLS if name == 'trakt_tools' else [('TorBox account', 'torbox_account'), ('TorBox files', 'torbox_files'), ('Emby library', 'emby_files')]
        if name == 'tools' and prefs.get('window_tests'):
            options = options + [('Window Tests', 'window_tests')]
        for label, target in options:
            folder = target in ('providers', 'services', 'trakt_tools')
            add(label, action='menu' if folder else 'tool', folder=folder, name=target)
    else:
        raise ValueError('Unknown menu.')
    xbmcplugin.setContent(handle, content)
    xbmcplugin.addDirectoryItems(handle, entries, len(entries))
    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)


def playback_media(db, key):
    obj = get_object(db, key)
    if obj.get('catalog_type') == 'episode':
        return Catalog.media(obj['show'], obj)
    if obj.get('catalog_type') == 'movie':
        return Catalog.media(obj)
    raise ValueError('Choose an episode or movie before playback.')
