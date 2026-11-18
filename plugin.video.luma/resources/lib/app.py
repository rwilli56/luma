import json
import sys
import time
from urllib.parse import parse_qsl, urlencode
import xbmc
import xbmcgui
import xbmcplugin
from . import config
from .library import home_rows, library
from .media import episode_label, source_rank
from .net import ApiError
from .torbox import TorBox
from .emby import Emby
from .display import configure as configure_display
from .trakt import Trakt, SyncDeferred
from . import filtering, preferences as prefs, search_rules
from .resolution import resolve_selected, SourceUnavailable, account_failure

BASE = 'plugin://plugin.video.luma/'


def route(action, **params):
    return BASE + '?' + urlencode(dict(params, action=action))


def notify(message):
    xbmcgui.Dialog().notification('Luma', message, config.addon().getAddonInfo('icon'), 5000)


def navigate(action, **params):
    xbmc.executebuiltin('ActivateWindow(Videos,"{}",return)'.format(route(action, **params)))


def decorate(media, offscreen=True):
    item = xbmcgui.ListItem(label=media['title'] + (' · ' + episode_label(media) if media['type'] == 'episode' else ''), offscreen=offscreen)
    tag = item.getVideoInfoTag()
    tag.setTitle(media.get('episode_title') or media['title'])
    tag.setMediaType(media['type'])
    if media.get('year'):
        tag.setYear(media['year'])
    tag.setPlot(media.get('overview', ''))
    if media['type'] == 'episode':
        tag.setTvShowTitle(media['title'])
        tag.setSeason(media['season'])
        tag.setEpisode(media['episode'])
    ids = dict(media.get('trakt', {}).get('ids', {}), luma=media['key'])
    tag.setUniqueIDs({k: str(v) for k, v in ids.items() if v is not None})
    if media.get('duration'):
        tag.setResumePoint(media.get('position', 0), media['duration'])
    if media.get('art'):
        item.setArt({'thumb': media['art'], 'poster': media['art']})
    return item


def browse(handle, action, params):
    db = config.store()
    rows = home_rows(db)
    if action in ('library', 'emby'):
        entries = sorted([i for i in library(db) if bool(i.get('emby')) == (action == 'emby')], key=lambda i: (i['title'].casefold(), i.get('season') or 0, i.get('episode') or 0))
    elif action == 'series':
        entries = sorted([i for i in library(db) if i.get('show_key') == params.get('key')], key=lambda i: (i['season'], i['episode']))
    else:
        entries = rows.get(action, [])
    xbmcplugin.setContent(handle, 'tvshows' if action == 'shows' else 'videos')
    directory = []
    for media in entries:
        folder = media['type'] == 'tvshow'
        item = decorate(media)
        from .custom_search import attach as custom_context
        custom_context(item, media, db=db)
        item.setProperty('IsPlayable', 'false' if folder else 'true')
        if not folder:
            item.addContextMenuItems([('Find sources', 'RunPlugin({})'.format(route('search', key=media['key']))),
                                      ('Identify on Trakt', 'RunPlugin({})'.format(route('identify', key=media['key'])))])
        target = route('series', key=media.get('show_key', media['key'])) if folder else route('play', key=media['key'])
        directory.append((target, item, folder))
    xbmcplugin.addDirectoryItems(handle, directory, len(directory))
    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
    if not entries:
        notify('No items yet. Add a link or refresh your TorBox library.')


def find_media(db, key):
    prepared = db.get('prepared_media:' + key, max_age=15)
    if prepared:
        return prepared
    for entries in home_rows(db).values():
        for item in entries:
            if item['key'] == key:
                return item
    for item in library(db):
        if item['key'] == key:
            return item
    cached = db.get('catalog_media:' + key)
    if cached:
        return cached
    raise ValueError('This item is no longer available. Refresh your library.')


def play(handle, key):
    db = config.store()
    media = find_media(db, key)
    rules = search_rules.effective(db, media)
    sources = [s for s in media.get('sources', []) if s['ready'] and search_rules.source_eligible(s, media, rules)]
    if not sources:
        from .search import find_sources
        history = next((i for i in home_rows(db)['continue'] if i['key'] == key), None)
        media = find_sources(media, prefer_library=True)
        if not media:
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
            return
        # Preserve an imported resume position when its filename key differs.
        if history:
            db.save_progress(media, history['position'], history['duration'], False, history.get('updated'))
        key = media['key']
        sources = [s for s in media['sources'] if search_rules.source_eligible(s, media, rules)]
    allow_dv = prefs.get('allow_dv')
    sources = filtering.apply(sources, media['type'])
    if not sources:
        raise ValueError('No ready sources match your Sort & Filter settings.')
    if len(sources) > 1 and prefs.get('movie_playstyle' if media['type'] == 'movie' else 'episode_playstyle') == 'select':
        labels = [xbmcgui.ListItem(label='{} · {} · {} · {:.1f} GB'.format(
            s['traits']['resolution'] or '?', s['traits']['hdr'], s['traits']['audio'], s['size'] / 1e9), label2=s['name']) for s in sources]
        selected = xbmcgui.Dialog().select('Choose source · preferred formats first', labels, useDetails=True)
        if selected < 0:
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
            return
        source = sources[selected]
    else:
        source = sources[0]
    if source['traits']['dv_only'] and not allow_dv:
        if not xbmcgui.Dialog().yesno('Dolby Vision source', 'This filename indicates Dolby Vision without an HDR10 fallback. Check compatibility with your display. Play anyway?'):
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
            return
    history = next((i for i in home_rows(db)['continue'] if i['key'] == key), None)
    position = 0
    resume_style = prefs.get('resume_style')
    if history and resume_style == 'resume':
        position = history['position']
    elif history and resume_style == 'ask':
        selected = xbmcgui.Dialog().contextmenu(['Resume from {:02d}:{:02d}'.format(int(history['position']) // 60, int(history['position']) % 60), 'Play from beginning'])
        if selected < 0:
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
            return
        if selected == 0:
            position = history['position']
    ready, display_status = configure_display(config.setting('manage_refresh') != 'false')
    if not ready and display_status != db.get('display_status'):
        notify('Check frame-rate matching in Kodi Player > Videos settings.')
    db.put('display_status', display_status)
    # Only selected files are checked. Kodi still owns demuxing and hardware decode.
    queue = [source] + ([s for s in sources if s is not source] if prefs.get('retry_sources') else [])
    failed, tried, url, last_error = set(), set(), None, None
    for attempt in range(3 if prefs.get('retry_sources') else 1):
        if not queue:
            if source['kind'] == 'emby':
                break
            from .search import find_sources
            next_media = find_sources(media, exclude_hashes=failed, prefer_library=True)
            if not next_media:
                xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
                return
            media, key = next_media, next_media['key']
            queue = list(next_media['sources'])
            if history:
                db.save_progress(media, history['position'], history['duration'], False, history.get('updated'))
        source = queue.pop(0)
        reference = (source['kind'], source['transfer_id'], source['file_id'])
        if reference in tried or (attempt and source['traits']['dv_only'] and not allow_dv):
            continue
        tried.add(reference)
        try:
            url = (Emby(config.setting('emby_url'), config.setting('emby_key'), config.setting('emby_user')).resolve(source)
                   if source['kind'] == 'emby' else resolve_selected(TorBox(config.setting('torbox_key')), source, media, check_link=prefs.get('verify_links')))
            break
        except (SourceUnavailable, ApiError) as exc:
            if account_failure(exc):
                raise
            if getattr(exc, 'status', 0) == 429:
                raise ValueError('TorBox playback requests are rate limited. Try again later.') from None
            last_error = exc
            if source.get('hash'):
                failed.add(source['hash'].lower())
            if attempt < 2 and prefs.get('retry_sources'):
                notify('Source unavailable. Checking another source.')
    if not url:
        raise last_error or SourceUnavailable('No playable source remained. Refresh or try another source.')
    if history and history.get('trakt'):
        media['trakt'] = history['trakt']
    item = decorate(media)
    item.setPath(url)
    item.setProperty('IsPlayable', 'true')
    if position:
        item.setProperty('StartOffset', str(position))
    # Kodi selects its native demuxer and hardware decoder from the actual stream.
    db.put('pending_playback', {'media': {k: v for k, v in media.items() if k != 'sources'}, 'created': time.time()})
    xbmcplugin.setResolvedUrl(handle, True, item)


def connect_trakt(db):
    client_id = config.setting('trakt_client_id').strip()
    if not client_id:
        if not xbmcgui.Dialog().yesno('Set up Trakt',
            'Create your own API application at https://app.trakt.tv/settings/apps, then enter its Client ID. Luma needs that application ID before it can display an activation code.',
            nolabel='Cancel', yeslabel='Enter Client ID'):
            return
        client_id = xbmcgui.Dialog().input('Trakt application Client ID').strip()
        if not client_id:
            return
        config.addon().setSetting('trakt_client_id', client_id)
    trakt = Trakt(db, client_id, config.setting('trakt_client_secret'))
    db.put('auth_pending', True)
    dialog = xbmcgui.DialogProgress()
    created = False
    try:
        code = trakt.device_code()
        dialog.create('Connect Trakt', '{}\nCode: {}'.format(code['verification_url'], code['user_code']))
        created = True
        deadline = time.monotonic() + code['expires_in']
        interval = max(5, code['interval'])
        monitor = xbmc.Monitor()
        while time.monotonic() < deadline and not dialog.iscanceled() and not monitor.abortRequested():
            for _ in range(interval):
                if monitor.waitForAbort(1) or dialog.iscanceled():
                    return
                if time.monotonic() >= deadline or xbmc.Player().isPlaying():
                    notify('Trakt code expired or sign-in stopped. Connect again when playback is idle.')
                    return
            try:
                db.put('auth_pending', True)
                trakt.device_token(code['device_code'])
                db.clear_cache(('catalog:', 'menu_object:', 'catalog_media:', 'trakt_lists', 'trakt_snapshot', 'show_progress_'))
                db.put('trakt_status', 'Connected · syncing your history')
                db.put('request_sync', True)
                notify('Trakt connected')
                return
            except ApiError as exc:
                if exc.code == 'invalid_client':
                    raise ValueError('Trakt rejected the application Client ID. Check Accounts settings and try again.') from None
                if exc.status == 400 and exc.code in ('', 'authorization_pending'):
                    continue
                if exc.status == 429 or exc.code == 'slow_down':
                    interval = max(interval + 5, exc.retry_after)
                    continue
                if exc.status in (404, 409, 410, 418) or exc.code in ('access_denied', 'expired_token', 'invalid_code'):
                    raise ValueError('Trakt activation was declined, expired or already used. Choose Connect Trakt to get a new code.') from None
                raise
        notify('Trakt connection cancelled or expired')
    finally:
        try:
            if created:
                dialog.close()
        finally:
            db.put('auth_pending', False)


def identify(key):
    db = config.store()
    media = find_media(db, key)
    trakt = Trakt(db, config.setting('trakt_client_id'), config.setting('trakt_client_secret'))
    if not trakt.client_id:
        raise ValueError('Add your Trakt Client ID in settings before identifying titles.')
    query = xbmcgui.Dialog().input('Find title on Trakt', defaultt=media['title'])
    if not query:
        return
    media_type = 'show' if media['type'] == 'episode' else 'movie'
    results = trakt.search(query, media_type)
    selected = xbmcgui.Dialog().select('Confirm the correct title', ['{} ({})'.format(r[media_type]['title'], r[media_type].get('year', '?')) for r in results])
    if selected < 0:
        return
    obj = results[selected][media_type]
    if media_type == 'show':
        db.identify('show:' + media['show_key'], obj)
    else:
        db.identify(key, {'title': obj['title'], 'year': obj.get('year'), 'overview': obj.get('overview', ''),
                          'trakt': {'ids': obj['ids'], 'images': obj.get('images', {})}})
    db.put('request_sync', True)
    db.put('ui_revision', time.time())
    notify('Title identified. Trakt sync will run while playback is idle.')


def search(key=None):
    from .search import choose_title, find_sources
    if xbmc.Player().isPlaying():
        raise ValueError('Stop playback before searching providers.')
    media = find_media(config.store(), key) if key else choose_title()
    if media:
        selected = find_sources(media)
        if selected:
            xbmc.executebuiltin('PlayMedia("{}")'.format(route('play', key=selected['key'])))


def settings_menu():
    selected = xbmcgui.Dialog().select('Luma', ['Accounts and playback settings', 'Connect Trakt', 'Sync now', 'Playback and connection status', 'Search provider settings'])
    db = config.store()
    if selected == 0:
        config.addon().openSettings()
        db.put('request_refresh', True)
    elif selected == 1:
        connect_trakt(db)
    elif selected == 2:
        db.put('request_sync', True)
        db.put('trakt_lists', None)
        notify('Sync requested. Luma syncs when playback is idle.')
    elif selected == 3:
        _, display_status = configure_display(False)
        xbmcgui.Dialog().textviewer('Luma · status', '{}\n\n{}\n\n{}\n\n{}\n\n{}\n\nProgress is saved locally every 10 seconds during playback.'.format(
            display_status, db.get('library_status', 'TorBox not connected'), db.get('trakt_status', 'Trakt not connected'), db.get('emby_status', 'Emby not connected'), db.get('search_status', 'No provider search yet')))
    elif selected == 4:
        from .search import provider_settings
        provider_settings()


def home():
    from .ui import show_home
    while True:
        selection = show_home()
        if not selection:
            return
        action, media = selection
        if action == 'settings':
            settings_menu()
        elif action == 'custom_search':
            from .custom_search import edit
            if edit(media) == 'play':
                return
        elif action == 'search':
            search()
            return
        elif action == 'refresh':
            db = config.store()
            db.put('request_refresh', True)
            db.put('request_sync', True)
            notify('Refreshing your library')
        elif action == 'add':
            link = xbmcgui.Dialog().input('Add a magnet or file link to TorBox')
            if link:
                TorBox(config.setting('torbox_key')).add(link)
                config.store().put('request_refresh', True)
                notify('Added to TorBox. Downloading files appear after refresh.')
        elif action == 'media':
            if media['type'] == 'tvshow':
                navigate('series', key=media['show_key'])
            else:
                xbmc.executebuiltin('PlayMedia("{}")'.format(route('play', key=media['key'])))
            return
        elif action == 'library':
            if config.setting('emby_url'):
                selected = xbmcgui.Dialog().select('Your libraries', ['TorBox', 'Emby'])
                if selected < 0:
                    continue
                navigate('emby' if selected == 1 else 'library')
            else:
                navigate('library')
            return
        else:
            navigate(action)
            return


def run():
    params = dict(parse_qsl(sys.argv[2][1:])) if len(sys.argv) > 2 else {}
    handle = int(sys.argv[1]) if len(sys.argv) > 1 else -1
    action = params.get('action', 'menu' if prefs.get('startup') == 'menu' else 'home')
    try:
        if action == 'play':
            play(handle, params['key'])
        elif action == 'catalog_play':
            from .directory import playback_media
            from .library import match_media
            media = playback_media(config.store(), params['key'])
            ready = match_media(media, library(config.store()))
            if ready:
                config.store().identify(ready['key'], {k: media[k] for k in ('title', 'year', 'overview', 'episode_title', 'trakt', 'premiered') if k in media})
                media = dict(media, key=ready['key'], sources=ready['sources'], show_key=ready.get('show_key', ''))
            config.store().put('catalog_media:' + media['key'], media)
            play(handle, media['key'])
        elif action == 'menu':
            from .directory import render
            render(handle, params)
        elif action == 'tool':
            from .toolbox import run as run_tool
            run_tool(params['name'])
        elif action == 'identify':
            identify(params['key'])
        elif action == 'search':
            search(params.get('key'))
        elif action == 'custom_search':
            from .custom_search import run as run_custom_search
            run_custom_search(params['key'])
        elif action == 'home':
            if handle >= 0:
                xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
            home()
        else:
            browse(handle, action, params)
    except SyncDeferred:
        if action in ('play', 'catalog_play'):
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        elif action == 'menu':
            xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
        notify('Metadata requests wait until playback stops.')
    except (ApiError, ValueError) as exc:
        if action in ('play', 'catalog_play'):
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        elif action == 'menu':
            xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
        xbmcgui.Dialog().ok('Luma', str(exc))
    except Exception as exc:
        if action in ('play', 'catalog_play'):
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        elif action == 'menu':
            xbmcplugin.endOfDirectory(handle, succeeded=False, cacheToDisc=False)
        # Kodi debug logs are frequently shared; never log raw API exceptions.
        import traceback
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        xbmc.log('Luma: operation failed in {} ({} at {}:{})'.format(action, type(exc).__name__, frame.name, frame.lineno), xbmc.LOGERROR)
        xbmcgui.Dialog().ok('Luma', 'Unable to complete this action. Refresh your library and try again.')
