"""User-driven title discovery, installed-provider search and cached playback."""
import hashlib
import json
import time
import xbmc
import xbmcaddon
import xbmcgui
from . import config, providers
from .catalog import Catalog
from .media import flatten, identity, byte_size
from .torbox import TorBox
from .trakt import Trakt
from .net import ApiError
from . import filtering, preferences as prefs, search_rules
from . import resolution
from .source_select import choose as choose_source


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


def remember(db, transfer, selected, metadata, manual=False):
    """Keep original filename keys so later library refreshes preserve resume IDs."""
    items = flatten([transfer], 'torrents')
    prior = [i for i in db.get('library_torrents', [])
             if not any(str(s['transfer_id']) == str(transfer['id']) for s in i.get('sources', []))]
    db.put('library_torrents', prior + items)
    mapping = {k: metadata[k] for k in ('title', 'year', 'overview', 'episode_title', 'trakt', 'premiered') if k in metadata}
    remapped = selected['type'] != metadata['type'] or manual or any(selected.get(k) != metadata.get(k) for k in ('season', 'episode'))
    if remapped:
        mapping.update(type=metadata['type'], season=metadata.get('season'), episode=metadata.get('episode'),
                       key=metadata.get('key') or identity(metadata['title'], metadata.get('year'), metadata.get('season'), metadata.get('episode')),
                       show_key=identity(metadata['title'], metadata.get('year')) if metadata['type'] == 'episode' else '')
    source = selected['sources'][0]
    manual_episode = [metadata.get('season'), metadata.get('episode')] if manual else None
    db.identify('file:{}:{}:{}'.format(source['kind'], source['transfer_id'], source['file_id']),
                {'path': source.get('path'), 'hash': source.get('hash'), 'media': mapping, 'manual_episode': manual_episode,
                 'search_context': source.get('search_context'), 'release_name': source.get('release_name')})
    # Retain the existing grouping key for ordinary, already-identified filenames.
    if 'key' not in mapping:
        db.identify(selected['key'], mapping)
    show_ids = metadata.get('trakt', {}).get('show_ids')
    if metadata['type'] == 'episode' and show_ids:
        db.identify('show:' + mapping.get('show_key', selected['show_key']), {'title': metadata['title'], 'year': metadata.get('year'), 'ids': show_ids})
    selected = dict(selected, **mapping)
    source['verified_at'] = time.time()
    if manual_episode:
        source['manual_episode'] = manual_episode
    # Put the verified source into the transient handoff; the library binding
    # remains useful after a complete TorBox refresh.
    db.put('prepared_media:' + selected['key'], selected)
    db.put('ui_revision', time.time())
    db.put('request_refresh', True)
    return selected


def episode_files(items, media):
    if media['type'] != 'episode':
        return [i for i in items if i['type'] == 'movie']
    from . import episodes
    return [i for i in items if episodes.matches(i['sources'][0].get('path', i['sources'][0]['name']), media,
                                                i['sources'][0].get('transfer_name', ''))]


def find_sources(media, exclude_hashes=None, prefer_library=False):
    # Construct before doing provider work so a missing key fails immediately.
    torbox = TorBox(config.setting('torbox_key'))
    filters = filtering.options()
    db = config.store()
    rules = search_rules.effective(db, media)
    query = search_rules.query_media(media, rules)
    context = search_rules.snapshot(media, query) if rules else None
    if xbmc.Player().isPlaying():
        raise ValueError('Stop playback before searching providers.')
    local_found = {}
    if prefer_library and rules:
        from .library import library, match_media
        matched = match_media(query, library(db))
        for source in (matched or {}).get('sources', []):
            hash_value = providers.infohash(source.get('hash'))
            name = source.get('release_name') or source.get('transfer_name') or source['name']
            if source['ready'] and source['kind'] == 'torrents' and hash_value and hash_value not in (exclude_hashes or set()) and search_rules.release_matches(name, rules) and filtering.apply([source], media['type'], filters):
                from .episodes import package
                local_found[hash_value] = {'hash': hash_value, 'magnet': 'magnet:?xt=urn:btih:' + hash_value,
                    'name': name, 'provider': 'TorBox library', 'size': source.get('torrent_size', 0),
                    'file_size': source['size'], 'size_scope': 'torrent', 'size_origin': 'TorBox transfer total', 'traits': source['traits'],
                    'transfer_id': source['transfer_id'], 'package': package(name)}
    backends = [] if local_found else [b for b in providers.installed() if b['available'] and config.setting('provider_' + b['key']) != 'false']
    if not backends and not local_found:
        provider_settings()
        return None
    dialog, monitor = xbmcgui.DialogProgress(), xbmc.Monitor()
    session = None
    cache_key = 'source_cache:' + hashlib.sha256(json.dumps(['source-picker-1', rules, media.get('trakt'), media['title'], media.get('year'),
        media.get('season'), media.get('episode'), [(b['key'], b.get('version'), b.get('settings_revision')) for b in backends], prefs.get('scrape_packs')], sort_keys=True).encode()).hexdigest()
    found = local_found or (db.get(cache_key, max_age=900) if prefs.get('source_cache') else None)
    failures = []
    try:
        description = 'Metadata S{:02d} E{:02d} → source S{:02d} E{:02d}'.format(media['season'], media['episode'], query['season'], query['episode']) if media['type'] == 'episode' and context else 'Loading your enabled providers…'
        dialog.create('Finding sources', description)
        if found is None:
            tasks, failures = providers.load(backends)
            if not prefs.get('scrape_packs'):
                tasks = [t for t in tasks if len(t) == 2]
            if not tasks:
                raise ValueError('No providers loaded. Open Search provider settings and enable torrent providers. ' +
                                 ('Could not load: ' + ', '.join(failures) if failures else ''))
            session = providers.ScrapeSession(tasks, query, timeout=prefs.get('scrape_timeout'), workers=prefs.get('scrape_workers'))
            found = {}
            while True:
                for result in session.poll():
                    providers.merge_result(found, result)
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
        ranked = filtering.apply([s for h, s in found.items() if h not in (exclude_hashes or set()) and search_rules.release_matches(s['name'], rules)], media['type'], filters, torrent_results=True)[:1000]
        if not ranked:
            raise ValueError('No sources match your Sort & Filter settings and custom search filters.')
        hashes = [s['hash'] for s in ranked]
        for start in range(0, len(hashes), 100):
            if dialog.iscanceled() or monitor.abortRequested() or xbmc.Player().isPlaying():
                return None
            hits.update(torbox.cached(hashes[start:start + 100]))
        sources = []
        for hash_value in hashes:
            if hash_value not in hits:
                continue
            source = dict(found[hash_value])
            total = byte_size(hits[hash_value].get('size'))
            if total:
                source.update(size=total, size_scope='torrent', size_origin='TorBox cache total')
            if context:
                source['search_context'] = context
            sources.append(source)
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
    automatic = prefs.get('movie_playstyle' if media['type'] == 'movie' else 'episode_playstyle') == 'auto'
    attempts = 0
    while sources and attempts < 3:
        index = 0 if automatic else choose_source(sources, media)
        if index < 0 or xbmc.Player().isPlaying():
            return None
        candidate = sources.pop(index)
        attempts += 1
        dialog = xbmcgui.DialogProgress()
        try:
            dialog.create('Preparing playback', 'Rechecking cache and matching video files…')
            stopped = lambda: dialog.iscanceled() or monitor.abortRequested() or xbmc.Player().isPlaying()
            transfer = resolution.prepare(torbox, candidate, stopped, monitor.waitForAbort)
            items = resolution.candidates(transfer, query)
            manual = False
            if not items and media['type'] == 'episode' and prefs.get('pack_fallback'):
                items = resolution.candidates(transfer, query, manual=True)
                manual = bool(items)
            by_file = {str(i['sources'][0]['file_id']): i for i in items}
            items = [by_file[str(s['file_id'])] for s in filtering.apply([i['sources'][0] for i in items], media['type'], filters)]
            if not items:
                raise resolution.SourceUnavailable('No matching playable file for this episode/movie in that torrent. Choose another source.')
        except resolution.SelectionCancelled:
            return None
        except (resolution.SourceUnavailable, ApiError) as exc:
            if resolution.account_failure(exc):
                raise
            if not prefs.get('retry_sources') or not sources or attempts >= 3:
                raise
            xbmcgui.Dialog().notification('Luma', 'Source unavailable. Trying another.' if automatic else 'Source unavailable. Choose another source.', time=4000)
            continue
        finally:
            dialog.close()
        # Ambiguous names require an explicit file choice, even in automatic mode.
        # Report the actual selected file's size/format, rather than pack metadata.
        if context:
            for item in items:
                item['sources'][0]['search_context'] = context
        changed = resolution.format_conflict(candidate, items[0]['sources'][0]) if len(items) == 1 else False
        file_index = 0 if len(items) == 1 and not manual and (automatic or not changed) else choose_source(
            [i['sources'][0] for i in items], media, stage='files')
        if file_index < 0:
            return None
        if manual and not xbmcgui.Dialog().yesno('Confirm episode file',
            'Play this file as {} S{:02d} E{:02d}?\n{}'.format(media['title'], media['season'], media['episode'], items[file_index]['sources'][0]['path'])):
            return None
        if context:
            items[file_index]['sources'][0]['search_context'] = context
        items[file_index]['sources'][0]['release_name'] = candidate['name']
        return remember(db, transfer, items[file_index], media, manual)
