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
from .trakt import Trakt, queue_progress

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
        item.setProperty('IsPlayable', 'false' if folder else 'true')
        if not folder:
            item.addContextMenuItems([('Identify on Trakt', 'RunPlugin({})'.format(route('identify', key=media['key'])))])
        target = route('series', key=media.get('show_key', media['key'])) if folder else route('play', key=media['key'])
        directory.append((target, item, folder))
    xbmcplugin.addDirectoryItems(handle, directory, len(directory))
    xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
    if not entries:
        notify('No items yet. Add a link or refresh your TorBox library.')


def find_media(db, key):
    for entries in home_rows(db).values():
        for item in entries:
            if item['key'] == key:
                return item
    for item in library(db):
        if item['key'] == key:
            return item
    raise ValueError('This item is no longer available. Refresh your library.')


def play(handle, key):
    db = config.store()
    media = find_media(db, key)
    sources = [s for s in media.get('sources', []) if s['ready']]
    if not sources:
        raise ValueError('This episode or movie is not ready in your TorBox library. Add its link, then refresh.')
    allow_dv = config.setting('allow_dv') == 'true'
    lossless = config.setting('prefer_lossless') == 'true'
    sources.sort(key=lambda s: source_rank(s, allow_dv, lossless), reverse=True)
    if len(sources) > 1:
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
    if history:
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
    # No metadata calls, probing, transcoding or local HTTP proxy here.
    url = (Emby(config.setting('emby_url'), config.setting('emby_key'), config.setting('emby_user')).resolve(source)
           if source['kind'] == 'emby' else TorBox(config.setting('torbox_key')).resolve(source))
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
    trakt = Trakt(db, config.setting('trakt_client_id'), config.setting('trakt_client_secret'))
    db.put('auth_pending', True)
    dialog = xbmcgui.DialogProgress()
    try:
        code = trakt.device_code()
        dialog.create('Connect Trakt', '{}\nCode: {}'.format(code['verification_url'], code['user_code']))
        deadline = time.monotonic() + code['expires_in']
        interval = max(5, code['interval'])
        monitor = xbmc.Monitor()
        while time.monotonic() < deadline and not dialog.iscanceled() and not monitor.abortRequested():
            for _ in range(interval):
                if monitor.waitForAbort(1) or dialog.iscanceled():
                    return
            try:
                trakt.device_token(code['device_code'])
                db.put('trakt_status', 'Connected · syncing your history')
                db.put('request_sync', True)
                notify('Trakt connected')
                return
            except ApiError as exc:
                if exc.status == 400:
                    continue
                if exc.status == 429:
                    interval = max(interval + 5, exc.retry_after)
                    continue
                raise
        notify('Trakt connection cancelled or expired')
    finally:
        dialog.close()
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


def settings_menu():
    selected = xbmcgui.Dialog().select('Luma', ['Accounts and playback settings', 'Connect Trakt', 'Sync now', 'Playback and connection status'])
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
        xbmcgui.Dialog().textviewer('Luma · status', '{}\n\n{}\n\n{}\n\n{}\n\nProgress is saved locally every 10 seconds during playback.'.format(
            display_status, db.get('library_status', 'TorBox not connected'), db.get('trakt_status', 'Trakt not connected'), db.get('emby_status', 'Emby not connected')))


def home():
    from .ui import show_home
    while True:
        selection = show_home()
        if not selection:
            return
        action, media = selection
        if action == 'settings':
            settings_menu()
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
    action = params.get('action', 'home')
    try:
        if action == 'play':
            play(handle, params['key'])
        elif action == 'identify':
            identify(params['key'])
        elif action == 'home':
            if handle >= 0:
                xbmcplugin.endOfDirectory(handle, cacheToDisc=False)
            home()
        else:
            browse(handle, action, params)
    except (ApiError, ValueError) as exc:
        if action == 'play':
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        xbmcgui.Dialog().ok('Luma', str(exc))
    except Exception:
        if action == 'play':
            xbmcplugin.setResolvedUrl(handle, False, xbmcgui.ListItem())
        # Kodi debug logs are frequently shared; never log raw API exceptions.
        xbmc.log('Luma: operation failed in {}'.format(action), xbmc.LOGERROR)
        xbmcgui.Dialog().ok('Luma', 'Unable to complete this action. Refresh your library and try again.')
