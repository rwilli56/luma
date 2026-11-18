"""User-driven title discovery, installed-provider search and cached playback."""
import hashlib
import json
import time
import xbmc
import xbmcaddon
import xbmcgui
from . import config, providers
from .catalog import Catalog
from .media import flatten, source_rank
from .torbox import TorBox
from .trakt import Trakt
from . import filtering, preferences as prefs


def provider_settings():
    backends = providers.installed()
    selected = xbmcgui.Dialog().select('Search providers', [
        '{} · {}'.format(b['label'], b.get('version', 'not installed or disabled')) for b in backends] + ['Installation help'])
    if 0 <= selected < len(backends) and backends[selected]['available']:
        xbmcaddon.Addon(backends[selected]['addon_id']).openSettings()
    elif selected >= 0:
        xbmcgui.Dialog().textviewer('Install a provider',
            'Install CocoScrapers from its author’s Kodi repository:\nhttps://cocojoe2411.github.io/\n\n'
            'Or install POV from kodifitzwell’s repository:\nhttps://kodifitzwell.github.io/repo/\n\n'
            'Current Magneto uses POV’s providers. Installing POV is sufficient. '
            'Enable your preferred torrent providers in that add-on’s settings. '
            'Luma uses its own TorBox key; no debrid account needs to be added to the provider add-on.\n\n'
            'Choose which installed backends Luma uses under Accounts and playback settings → Search.')


def choose_title():
    kind = xbmcgui.Dialog().select('Search', ['Movies', 'TV series'])
    if kind < 0:
        return None
    query = xbmcgui.Dialog().input('Search movies' if kind == 0 else 'Search TV series').strip()
    if not query:
        return None
    db = config.store()
    if prefs.get('search_history'):
        history_key = 'search_history:' + ('movie' if kind == 0 else 'show')
        prior = db.get(history_key, [])
        db.put(history_key, [query] + [v for v in prior if v != query][:29])
    catalog = Catalog(db, Trakt(db, config.setting('trakt_client_id')))
    results = catalog.search(query, 'movie' if kind == 0 else 'show')
    if not results:
        xbmcgui.Dialog().ok('Search', 'No titles found. Try a shorter title or a different spelling.')
        return None
    index = xbmcgui.Dialog().select('Choose the correct title', ['{} ({})'.format(r['title'], r.get('year') or '?') for r in results])
    if index < 0:
        return None
    title = results[index]
    if kind == 0:
        return catalog.media(title)
    episodes = catalog.episodes(title)
    seasons = sorted({e['season'] for e in episodes if e['season'] != 0 or not prefs.get('hide_specials')})
    index = xbmcgui.Dialog().select(title['title'], ['Specials' if s == 0 else 'Season {}'.format(s) for s in seasons])
    if index < 0:
        return None
    episodes = sorted(catalog.season(title, seasons[index], episodes), key=lambda e: e['number'])
    if not episodes:
        xbmcgui.Dialog().ok('Search', 'No aired episodes were found for this season.')
        return None
    index = xbmcgui.Dialog().select('Choose an episode', ['E{:02d} · {}'.format(e['number'], e.get('title', '')) for e in episodes])
    return catalog.media(title, episodes[index]) if index >= 0 else None


def remember(db, transfer, selected, metadata):
    """Keep original filename keys so later library refreshes preserve resume IDs."""
    items = flatten([transfer], 'torrents')
    prior = [i for i in db.get('library_torrents', [])
             if not any(str(s['transfer_id']) == str(transfer['id']) for s in i.get('sources', []))]
    db.put('library_torrents', prior + items)
    mapping = {k: metadata[k] for k in ('title', 'year', 'overview', 'episode_title', 'trakt', 'premiered') if k in metadata}
    db.identify(selected['key'], mapping)
    show_ids = metadata.get('trakt', {}).get('show_ids')
    if metadata['type'] == 'episode' and show_ids:
        db.identify('show:' + selected['show_key'], {'title': metadata['title'], 'year': metadata.get('year'), 'ids': show_ids})
    selected = dict(selected, **mapping)
    db.put('ui_revision', time.time())
    db.put('request_refresh', True)
    return selected


def episode_files(items, media):
    if media['type'] != 'episode':
        return [i for i in items if i['type'] == 'movie']
    return [i for i in items if i['type'] == 'episode' and i['season'] == media['season'] and i['episode'] == media['episode']]


def find_sources(media):
    # Construct before doing provider work so a missing key fails immediately.
    torbox = TorBox(config.setting('torbox_key'))
    filters = filtering.options()
    db = config.store()
    if xbmc.Player().isPlaying():
        raise ValueError('Stop playback before searching providers.')
    backends = [b for b in providers.installed() if b['available'] and config.setting('provider_' + b['key']) != 'false']
    if not backends:
        provider_settings()
        return None
    dialog, monitor = xbmcgui.DialogProgress(), xbmc.Monitor()
    session = None
    cache_key = 'source_cache:' + hashlib.sha256(json.dumps([media.get('trakt'), media['title'], media.get('year'),
        media.get('season'), media.get('episode'), [(b['key'], b.get('version'), b.get('settings_revision')) for b in backends], prefs.get('scrape_packs')], sort_keys=True).encode()).hexdigest()
    found = db.get(cache_key, max_age=900) if prefs.get('source_cache') else None
    failures = []
    try:
        dialog.create('Finding sources', 'Loading your enabled providers…')
        if found is None:
            tasks, failures = providers.load(backends)
            if not prefs.get('scrape_packs'):
                tasks = [t for t in tasks if len(t) == 2]
            if not tasks:
                raise ValueError('No providers loaded. Open Search provider settings and enable torrent providers. ' +
                                 ('Could not load: ' + ', '.join(failures) if failures else ''))
            session = providers.ScrapeSession(tasks, media, timeout=prefs.get('scrape_timeout'), workers=prefs.get('scrape_workers'))
            found = {}
            while True:
                for result in session.poll():
                    found.setdefault(result['hash'], result)
                if dialog.iscanceled() or monitor.abortRequested() or xbmc.Player().isPlaying():
                    return None
                if session.finished:
                    break
                if session.expired:
                    session.stop.set()
                dialog.update(int(80 * session.completed / session.total),
                              '{} sources · {} / {} providers{}'.format(len(found), session.completed, session.total,
                              '\nFinishing active requests…' if session.expired else ''))
                if monitor.waitForAbort(.1):
                    return None
            session.stop.set()
            if found and prefs.get('source_cache'):
                db.put(cache_key, found)
        if not found:
            raise ValueError('No torrent sources found. Check enabled providers and their settings; try again later.')
        dialog.update(85, 'Checking {} unique torrents with TorBox…'.format(len(found)))
        hits = {}
        # Bound cache checks for very broad titles on the Streamer's hardware.
        ranked = filtering.apply(found.values(), media['type'], filters, torrent_results=True)[:1000]
        if not ranked:
            raise ValueError('No sources match your Sort & Filter settings.')
        hashes = [s['hash'] for s in ranked]
        for start in range(0, len(hashes), 100):
            if dialog.iscanceled() or monitor.abortRequested() or xbmc.Player().isPlaying():
                return None
            hits.update(torbox.cached(hashes[start:start + 100]))
        sources = [dict(found[h], size=hits[h].get('size') or found[h]['size']) for h in found if h in hits]
    finally:
        if session:
            session.stop.set()
        dialog.close()
    db.put('search_status', '{} unique sources · {} cached · {} failed providers'.format(len(found), len(sources), (session.failed if session else 0) + len(failures)))
    if not sources:
        raise ValueError('Found {} torrents, but none are cached on TorBox. Try another provider or add a link to download it first.'.format(len(found)))
    sources = filtering.apply(sources, media['type'], filters, torrent_results=True)
    if not sources:
        raise ValueError('No cached sources match your Sort & Filter settings.')
    labels = [xbmcgui.ListItem(label='{} · {} · {} · {:.1f} GB · cached'.format(
        s['traits']['resolution'] or '?', s['traits']['hdr'], s['traits']['audio'], s['size'] / 1e9),
        label2=s['name'] + ' · ' + s['provider']) for s in sources]
    index = 0 if prefs.get('movie_playstyle' if media['type'] == 'movie' else 'episode_playstyle') == 'auto' else xbmcgui.Dialog().select('TorBox cached sources · preferred formats first', labels, useDetails=True)
    if index < 0:
        return None
    if xbmc.Player().isPlaying():
        return None
    created = torbox.add(sources[index]['magnet'], cached_only=True)
    transfer_id = created.get('torrent_id') if isinstance(created, dict) else None
    if transfer_id is None:
        raise ValueError('TorBox has not supplied a playable transfer yet. Check its dashboard and refresh your library.')
    dialog = xbmcgui.DialogProgress()
    try:
        dialog.create('Preparing playback', 'Waiting for the cached file list…')
        deadline = time.monotonic() + 25
        while True:
            if dialog.iscanceled() or monitor.abortRequested() or xbmc.Player().isPlaying():
                return None
            transfer = torbox.torrent(transfer_id)
            if transfer.get('download_finished') is True and transfer.get('download_present') is True:
                break
            if time.monotonic() >= deadline:
                raise ValueError('The transfer is not ready yet. Refresh your TorBox library in a moment.')
            if monitor.waitForAbort(1):
                return None
        items = episode_files(flatten([transfer], 'torrents'), media)
        items = [i for i in items if filtering.apply(i['sources'], media['type'], filters)]
    finally:
        dialog.close()
    if not items:
        raise ValueError('No matching video file was found. For series, the filename must identify the exact season and episode.')
    # Never guess the largest file when a movie/pack contains several videos.
    index = 0 if len(items) == 1 else xbmcgui.Dialog().select('Choose the video file', [i['sources'][0]['name'] for i in items])
    if index < 0:
        return None
    return remember(db, transfer, items[index], media)
