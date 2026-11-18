"""Maintenance commands; reset operations are serialized by the idle service."""
import time
import xbmc
import xbmcgui
from . import config, preferences as prefs
from .torbox import TorBox


def maintenance(db, name):
    if name == 'wipe':
        db.reset()
        addon = config.addon()
        for key, value in prefs.DEFAULTS.items():
            addon.setSetting(key, str(value).lower() if isinstance(value, bool) else str(value))
    elif name == 'rebuild_trakt':
        db.clear_cache(('catalog:', 'catalog_detail:', 'trakt_snapshot', 'trakt_lists', 'show_progress_', 'episode:', 'catalog_episodes:'))
    elif name == 'flush_activities':
        db.clear_cache(('trakt_lists', 'show_progress_', 'catalog:'))
    else:
        raise ValueError('Unknown maintenance operation.')
    db.put('request_sync', True)
    db.put('ui_revision', time.time())


def run(name):
    from .app import connect_trakt, home, navigate, notify, settings_menu
    db = config.store()
    if name in ('dashboard', 'home'):
        home()
    elif name in ('settings', 'status'):
        if name == 'settings':
            config.addon().openSettings()
        else:
            from .display import configure
            _, status = configure(False)
            xbmcgui.Dialog().textviewer('Luma · status', '\n\n'.join([status, db.get('library_status', 'TorBox not connected'),
                db.get('trakt_status', 'Trakt not connected'), db.get('emby_status', 'Emby not connected'), db.get('search_status', 'No provider search yet')]))
    elif name == 'connect_trakt':
        if xbmc.Player().isPlaying():
            raise ValueError('Stop playback before connecting an account.')
        connect_trakt(db)
    elif name in ('providers', 'provider_settings'):
        from .search import provider_settings
        provider_settings()
    elif name == 'provider_updates':
        xbmc.executebuiltin('UpdateAddonRepos')
        notify('Kodi is checking installed repositories for updates.')
    elif name in ('clear_cache', 'clear_sources', 'clear_searches'):
        prefixes = {'clear_cache': ('catalog:', 'catalog_detail:', 'catalog_episodes:'), 'clear_sources': ('source_cache:',), 'clear_searches': ('search_history:',)}[name]
        db.clear_cache(prefixes)
        notify('Cleared. Watch history and account settings are preserved.')
    elif name in ('sync', 'flush_activities', 'rebuild_trakt'):
        if name != 'sync':
            db.put('request_maintenance', name)
        db.put('request_sync', True)
        notify('Trakt sync requested. It runs while playback is idle.')
    elif name == 'wipe':
        if xbmcgui.Dialog().yesno('Wipe Luma data?', 'Remove Luma account credentials, preferences, local watch history, title mappings and unsent updates? Server libraries and server history are kept.'):
            db.put('request_maintenance', 'wipe')
            notify('Luma will reset when playback is idle. Reopen it afterward.')
    elif name == 'add_link':
        link = xbmcgui.Dialog().input('Add a magnet or file link to TorBox')
        if link:
            TorBox(config.setting('torbox_key')).add(link)
            db.put('request_refresh', True)
            notify('Added to TorBox. Refresh after the transfer is ready.')
    elif name in ('torbox_files', 'emby_files'):
        navigate('library' if name == 'torbox_files' else 'emby')
    elif name in ('downloads', 'torbox_account'):
        if xbmc.Player().isPlaying():
            raise ValueError('Stop playback before querying your account.')
        api = TorBox(config.setting('torbox_key'), should_defer=xbmc.Player().isPlaying)
        if name == 'torbox_account':
            account = api._call('GET', 'user/me')
            if not isinstance(account, dict):
                raise ValueError('TorBox returned no account details.')
            fields = [('Name', 'name'), ('Plan', 'plan'), ('Premium expires', 'premium_expires_at'), ('Total downloaded', 'total_downloaded')]
            text = '\n'.join('{}: {}'.format(label, account.get(key, 'Not supplied')) for label, key in fields)
        else:
            transfers = [(kind, t) for kind in ('torrents', 'webdl') for t in api.library(kind)]
            text = '\n\n'.join('{}\n{} · {}'.format(t.get('name', 'Untitled'), kind, t.get('download_state', 'unknown')) for kind, t in transfers) or 'No TorBox transfers.'
        xbmcgui.Dialog().textviewer('TorBox account' if name == 'torbox_account' else 'Download Manager · TorBox', text)
    elif name == 'window_tests':
        selected = xbmcgui.Dialog().select('Window Tests', ['Home Dashboard', 'Source chooser preview', 'Progress window preview', 'Download Manager'])
        if selected == 0:
            home()
        elif selected == 1:
            xbmcgui.Dialog().select('Source chooser preview', [xbmcgui.ListItem(label='2160 · HDR10+ · E-AC-3 · cached', label2='Interface preview — no video is requested')], useDetails=True)
        elif selected == 2:
            dialog = xbmcgui.DialogProgress()
            dialog.create('Progress preview', 'Interface preview — no network requests')
            try:
                dialog.update(50, 'Press Cancel to close')
                monitor = xbmc.Monitor()
                for _ in range(50):
                    if dialog.iscanceled() or monitor.waitForAbort(.1):
                        break
            finally:
                dialog.close()
        elif selected == 3:
            run('downloads')
    else:
        raise ValueError('Unknown tool.')
