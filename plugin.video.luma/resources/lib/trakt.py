"""Device OAuth, identification, and an offline sync queue. No bundled app secrets."""
import datetime
import json
import time
from urllib.parse import urlsplit
from .media import identity, normalized
from .net import ApiError, Http


class SyncDeferred(Exception):
    """Playback started while a batch was in progress."""


def timestamp(value):
    if not value:
        return 0
    try:
        return datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError):
        return 0


def utc(value):
    return datetime.datetime.fromtimestamp(value, datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def media_from_trakt(obj, show=None):
    title = (show or obj)['title']
    year = (show or obj).get('year')
    season, episode = obj.get('season'), obj.get('number') if show else None
    return {'key': identity(title, year, season, episode), 'title': title, 'year': year,
            'season': season, 'episode': episode, 'type': 'episode' if show else 'movie',
            'show_key': identity(title, year) if show else '',
            'episode_title': obj.get('title') if show else '', 'overview': obj.get('overview', ''),
            'premiered': (obj.get('first_aired') or '')[:10] if show else '',
            'trakt': {'ids': obj['ids'], 'show_ids': show['ids'] if show else {},
                      'images': (show or obj).get('images', {})}}


class Trakt:
    def __init__(self, db, client_id, client_secret='', http=None, auth=None, should_defer=None, allow_refresh=True):
        self.db, self.client_id, self.client_secret = db, client_id.strip(), client_secret.strip()
        self.http = http or Http('https://api.trakt.tv', 'Trakt', {'trakt-api-version': '2', 'trakt-api-key': self.client_id})
        self.auth = auth or Http('https://auth.trakt.tv', 'Trakt login', {'trakt-api-version': '2', 'trakt-api-key': self.client_id})
        self.should_defer = should_defer or (lambda: False)
        self.allow_refresh = allow_refresh

    @property
    def connected(self):
        return bool(self.client_id and self.db.get('trakt_tokens', {}).get('access_token'))

    def credentials(self):
        value = {'client_id': self.client_id}
        if self.client_secret:
            value['client_secret'] = self.client_secret
        return value

    def device_code(self):
        if not self.client_id:
            raise ValueError('Add your Trakt application Client ID in Luma settings first.')
        try:
            data = self.auth.request('POST', '/oauth/device/code', body={'client_id': self.client_id})
        except ApiError as exc:
            if exc.status in (400, 401, 403) or exc.code == 'invalid_client':
                raise ValueError('Trakt rejected this application Client ID. Enter the Client ID from your Trakt API app, not an activation code or website URL.') from None
            raise
        if not isinstance(data, dict):
            raise ValueError('Trakt returned an invalid activation response. Try connecting again.')
        url = data.get('verification_url') or data.get('verification_uri')
        if (not all(isinstance(data.get(k), str) and data[k] for k in ('device_code', 'user_code'))
                or not isinstance(url, str) or urlsplit(url).scheme != 'https' or not urlsplit(url).hostname
                or not all(type(data.get(k)) is int and data[k] > 0 for k in ('expires_in', 'interval'))):
            raise ValueError('Trakt returned incomplete activation details. Check your application Client ID and retry.')
        return dict(data, verification_url=url)

    def device_token(self, code):
        token = self.auth.request('POST', '/oauth/device/token', body=dict(self.credentials(), code=code))
        return self.save_token(token)

    def save_token(self, token):
        if (not isinstance(token, dict)
                or not all(isinstance(token.get(k), str) and token[k] for k in ('access_token', 'refresh_token'))
                or type(token.get('expires_in')) is not int or token['expires_in'] <= 0
                or type(token.get('created_at')) is not int or token['created_at'] < 0):
            raise ValueError('Trakt returned an incomplete sign-in token. Your existing connection has been kept. Try connecting again.')
        safe = {k: token[k] for k in ('access_token', 'refresh_token', 'expires_in', 'created_at', 'scope', 'token_type') if k in token}
        self.db.put('trakt_tokens', safe)
        return safe

    def _token(self, force=False):
        token = self.db.get('trakt_tokens', {})
        if not token.get('access_token'):
            raise ValueError('Connect Trakt from Luma settings.')
        if force or time.time() >= token.get('created_at', 0) + token.get('expires_in', 0) - 120:
            # Only the background service owns token refresh and authenticated API calls.
            if not self.allow_refresh:
                self.db.put('request_sync', True)
                raise ValueError('Trakt is refreshing its session. Try again after the idle sync finishes.')
            try:
                refreshed = self.auth.request('POST', '/oauth/token', body=dict(self.credentials(),
                    grant_type='refresh_token', refresh_token=token['refresh_token']))
            except ApiError as exc:
                if exc.status == 400:
                    raise ValueError('Please reconnect Trakt from Luma settings.') from None
                raise
            token = self.save_token(refreshed)
        return token['access_token']

    def call(self, method, path, params=None, body=None, authenticated=True):
        if self.should_defer():
            raise SyncDeferred()
        headers = {'Authorization': 'Bearer ' + self._token()} if authenticated else {}
        try:
            return self.http.request(method, path, params=params, body=body, headers=headers)
        except ApiError as exc:
            if exc.status == 401 and authenticated:
                return self.http.request(method, path, params=params, body=body,
                                         headers={'Authorization': 'Bearer ' + self._token(force=True)})
            raise

    def search(self, title, media_type):
        return self.call('GET', '/search/' + media_type,
                         params={'query': title, 'limit': 20, 'extended': 'full'}, authenticated=False)

    def paged(self, path, params=None):
        results, page = [], 1
        while True:
            batch = self.call('GET', path, params=dict(params or {}, page=page, limit=100))
            if not isinstance(batch, list):
                raise ApiError('Trakt')
            results.extend(batch)
            if len(batch) < 100:
                return results
            page += 1
            if page > 100:
                raise ValueError('Trakt result exceeds 10,000 items.')

    def flush(self):
        for event in self.db.pending():
            value = json.loads(event['value'])
            if value.get('backend') == 'emby':
                continue
            if value.get('completed'):
                media_type = 'episodes' if value['type'] == 'episode' else 'movies'
                if not value.get('history_sent'):
                    response = self.call('POST', '/sync/history', body={media_type: [
                        {'ids': value['ids'], 'watched_at': value['watched_at']}]})
                    if isinstance(response, dict) and any(response.get('not_found', {}).values()):
                        continue
                    value['history_sent'] = True
                    self.db.advance(event['key'], event['version'], value)
                # History insertion alone need not clear another client's paused record.
                paused = self.call('GET', '/sync/playback/' + media_type)
                if isinstance(paused, list):
                    singular = 'episode' if media_type == 'episodes' else 'movie'
                    for record in paused:
                        ids = record.get(singular, {}).get('ids', {})
                        if any(ids.get(key) is not None and str(ids[key]) == str(identifier) for key, identifier in value['ids'].items()):
                            try:
                                self.call('DELETE', '/sync/playback/{}'.format(int(record['id'])))
                            except ApiError as exc:
                                if exc.status != 404:
                                    raise
            else:
                media_type = 'episode' if value['type'] == 'episode' else 'movie'
                self.call('POST', '/scrobble/pause', body={media_type: {'ids': value['ids']},
                                                       'progress': value['percent']})
            self.db.acknowledge(event['key'], event['version'])

    def snapshot(self, progress_budget=8):
        """Pull lists in one sync; spread show-progress requests across service ticks."""
        from . import preferences as prefs
        if self.db.get('trakt_lists', max_age=600) is None:
            watching = []
            for record in self.paged('/sync/playback', {'extended': 'full'}):
                show = record.get('show')
                obj = record.get('episode') or record.get('movie')
                if not obj or record.get('progress', 0) >= prefs.get('watched_percent'):
                    continue
                item = media_from_trakt(obj, show)
                duration = (obj.get('runtime') or 45 if show else obj.get('runtime') or 120) * 60
                watching.append(dict(item, duration=duration, position=duration * record.get('progress', 0) / 100,
                                     updated=timestamp(record.get('paused_at')), completed=False))
            shows = self.paged('/sync/watched/shows', {'extended': 'full'})
            shows.sort(key=lambda s: s.get('last_watched_at', ''), reverse=True)
            self.db.put('trakt_lists', {'continue': watching, 'shows': shows})
        lists = self.db.get('trakt_lists', {})
        shows = lists.get('shows', [])
        next_items, series = [], []
        budget = progress_budget
        for entry in shows:
            show = entry['show']
            show_id = show['ids']['trakt']
            cache_key = 'show_progress_' + str(show_id)
            cached = self.db.get(cache_key)
            if budget and (cached is None or time.time() - cached['fetched'] > 3600 or cached.get('watched') != entry.get('last_watched_at')):
                data = self.call('GET', '/shows/{}/progress/watched'.format(show_id),
                                 params={'hidden': 'false', 'specials': 'false'})
                cached = {'data': data, 'fetched': time.time(), 'watched': entry.get('last_watched_at')}
                self.db.put(cache_key, cached)
                budget -= 1
            series.append({'key': identity(show['title'], show.get('year')), 'title': show['title'],
                           'year': show.get('year'), 'type': 'tvshow', 'show_key': identity(show['title'], show.get('year')),
                           'updated': timestamp(entry.get('last_watched_at')), 'trakt': {'show_ids': show['ids'],
                           'images': show.get('images', {})}})
            episode = (cached or {}).get('data', {}).get('next_episode')
            if episode:
                next_items.append(dict(media_from_trakt(episode, show), updated=timestamp(entry.get('last_watched_at'))))
        snapshot = {'continue': lists.get('continue', []), 'shows': series, 'next': next_items, 'updated': time.time()}
        self.db.put('trakt_snapshot', snapshot)
        return snapshot


def queue_progress(db, media, position, duration, completed, watched_at=None):
    from . import preferences as prefs
    if not prefs.get('trakt_scrobble'):
        return
    ids = media.get('trakt', {}).get('ids')
    if not ids or duration <= 0:
        return
    # A completion must survive a subsequent partial rewatch of the same item.
    event_key = media['key'] + (':watched' if completed else ':resume')
    if completed:
        for event in db.pending():
            if event['key'] == media['key'] + ':resume':
                db.acknowledge(event['key'], event['version'])
    db.enqueue(event_key, {'ids': ids, 'type': media['type'], 'completed': completed,
                          'percent': min(100, 100 * position / duration), 'watched_at': utc(watched_at or time.time())})
