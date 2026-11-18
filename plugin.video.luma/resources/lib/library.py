from .media import flatten, merge_library, normalized


def refresh_library(db, torbox):
    # Commit each library separately; a web-download outage cannot hide torrents.
    failures = []
    for kind in ('torrents', 'webdl'):
        try:
            items = flatten(torbox.library(kind), kind)
            db.put('library_' + kind, items)
        except Exception as exc:
            from .trakt import SyncDeferred
            if isinstance(exc, SyncDeferred):
                raise
            failures.append(str(exc))
    if len(failures) == 2:
        raise ValueError(failures[0])
    return failures


def library(db):
    items = merge_library(db.get('library_torrents', []) + db.get('library_webdl', []))
    mappings = db.mappings()
    episodes = db.cache_prefix('episode:')
    for item in items:
        item.update(mappings.get(item['key'], {}))
        if item.get('show_key'):
            key = item['show_key']
            show = mappings.get('show:' + key)
            if show:
                item['trakt'] = dict(item.get('trakt', {}), show_ids=show['ids'], images=show.get('images', {}))
                item['title'] = show['title']
                item['year'] = show.get('year')
                # Episode IDs are required before syncing; show IDs alone are insufficient.
                episode = episodes.get('episode:{}:{}:{}'.format(show['ids'].get('trakt'), item['season'], item['episode']))
                if episode:
                    item['trakt']['ids'] = episode['ids']
                    item['episode_title'] = episode.get('title', '')
    return items + db.get('library_emby', [])


def match_media(remote, items):
    candidates = []
    for item in items:
        if item['type'] != remote['type'] or item.get('season') != remote.get('season') or item.get('episode') != remote.get('episode'):
            continue
        local_ids, remote_ids = item.get('trakt', {}), remote.get('trakt', {})
        if local_ids.get('ids', {}).get('trakt') and local_ids.get('ids', {}).get('trakt') == remote_ids.get('ids', {}).get('trakt'):
            return item
        # Exact normalized titles only. Conflicting known years are never merged.
        if normalized(item['title']) == normalized(remote['title']) and not (item.get('year') and remote.get('year') and item['year'] != remote['year']):
            candidates.append(item)
    return candidates[0] if len(candidates) == 1 else None


def home_rows(db):
    items = library(db)
    by_key = {item['key']: item for item in items}
    local = db.history()
    known = {i['key']: i for i in local}
    for item in items:
        if item.get('emby') and (item.get('position', 0) or item.get('completed')):
            prior = known.get(item['key'])
            if prior is None or item.get('updated', 0) > prior.get('updated', 0):
                known[item['key']] = item
    local = sorted(known.values(), key=lambda i: i.get('updated', 0), reverse=True)
    remote = db.get('trakt_snapshot', {})
    combined = {item['key']: dict(item, **{'sources': by_key.get(item['key'], {}).get('sources', [])}) for item in local}
    for item in remote.get('continue', []):
        match = match_media(item, items)
        resolved = dict(item)
        if match:
            resolved.update(key=match['key'], sources=match['sources'], show_key=match.get('show_key', ''))
        old = combined.get(resolved['key'])
        if old is None or old.get('updated', 0) < resolved['updated']:
            combined[resolved['key']] = resolved
    continue_items = sorted([item for item in combined.values() if not item.get('completed') and item.get('position', 0) >= 10],
                            key=lambda item: item.get('updated', 0), reverse=True)
    series = {}
    for item in local:
        if item['type'] == 'episode' and item['show_key'] not in series:
            series[item['show_key']] = dict(item, key=item['show_key'], type='tvshow')
    for item in remote.get('shows', []):
        # Match mapped display names even when local filenames had a different year.
        same = next((s for s in series.values() if normalized(s['title']) == normalized(item['title'])
                     and not (s.get('year') and item.get('year') and s['year'] != item['year'])), None)
        candidates = {i['show_key'] for i in items if i['type'] == 'episode' and normalized(i['title']) == normalized(item['title'])
                      and not (i.get('year') and item.get('year') and i['year'] != item['year'])}
        key = same['show_key'] if same else (next(iter(candidates)) if len(candidates) == 1 else item['key'])
        if same is None or same.get('updated', 0) < item['updated']:
            series[key] = dict(item, show_key=key)
    next_items = []
    active_shows = {i['show_key'] for i in continue_items if i.get('show_key')}
    for item in remote.get('next', []):
        match = match_media(item, items)
        entry = dict(item)
        if match:
            entry.update(key=match['key'], sources=match['sources'], show_key=match['show_key'])
        state = combined.get(entry['key'])
        newer_local = next((i for i in local if i.get('show_key') == entry.get('show_key')), None)
        already_passed = newer_local and newer_local.get('completed') and newer_local.get('updated', 0) > entry.get('updated', 0) and (newer_local['season'], newer_local['episode']) >= (entry['season'], entry['episode'])
        if entry.get('show_key') not in active_shows and not (state and state.get('completed')) and not already_passed:
            next_items.append(entry)
    # Offline fallback advances only to the consecutive episode already in the library.
    represented = {normalized(i['title']) for i in next_items}
    for show_key, show in series.items():
        if show_key in active_shows or normalized(show['title']) in represented:
            continue
        last = next((i for i in local if i.get('show_key') == show_key), None)
        if last and last.get('completed'):
            candidate = next((i for i in items if i.get('show_key') == show_key and i.get('season') == last['season']
                              and i.get('episode') == last['episode'] + 1), None)
            if candidate and not combined.get(candidate['key'], {}).get('completed'):
                next_items.append(dict(candidate, updated=last['updated']))
    from .artwork import cached_path
    artwork = db.cache_prefix('art:')
    rows = {'continue': continue_items, 'next': sorted(next_items, key=lambda i: i.get('updated', 0), reverse=True),
            'shows': sorted(series.values(), key=lambda i: i.get('updated', 0), reverse=True)}
    for row in rows.values():
        for item in row:
            item['art'] = cached_path(db, item, artwork)
    return rows
