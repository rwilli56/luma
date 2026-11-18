"""Cached catalog and personal menus. Never fetch sources while browsing."""
import datetime
import hashlib
import json
from urllib.parse import quote
from . import preferences as prefs
from .catalog import Catalog
from .media import identity
from .net import ApiError


def segment(value):
    return quote(str(value), safe='')


def save_object(db, obj):
    kind = obj.get('catalog_type', 'movie')
    identifier = obj.get('ids', {}).get('trakt') or obj.get('ids', {}).get('imdb') or obj.get('id')
    value = '{}:{}:{}'.format(kind, identifier, obj.get('number', ''))
    if kind == 'episode':
        value += ':' + str(obj.get('show', {}).get('ids', {})) + ':' + str(obj.get('season'))
    key = hashlib.sha256(value.encode('utf-8')).hexdigest()[:24]
    db.put('menu_object:' + key, obj)
    return key


def get_object(db, key):
    obj = db.get('menu_object:' + key)
    if not obj:
        raise ValueError('This menu item expired. Open its parent menu again.')
    return obj


def title_object(obj, kind):
    return dict(obj, catalog='trakt', catalog_type=kind)


class Explorer:
    def __init__(self, db, trakt, catalog=None):
        self.db, self.trakt = db, trakt
        self.catalog = catalog or Catalog(db, trakt)

    def fetch(self, path, params=None, auth=False):
        if not self.trakt.client_id:
            raise ValueError('This menu needs a Trakt application Client ID. Add it in Settings → Accounts. Popular, Genres, Years and title search also work without it.')
        if auth and not self.trakt.connected:
            raise ValueError('Connect Trakt in Settings → Accounts to open your personal lists.')
        key = 'catalog:' + hashlib.sha256(json.dumps([path, params or {}, auth], sort_keys=True).encode()).hexdigest()
        data = self.db.get(key, max_age=prefs.get('catalog_ttl') * 60)
        if data is None:
            data = self.trakt.call('GET', path, params=params, authenticated=auth)
            if not isinstance(data, (list, dict)):
                raise ApiError('Trakt')
            self.db.put(key, data)
        return data

    def genres(self, kind):
        if self.trakt.client_id:
            return self.fetch('/genres/' + ('movies' if kind == 'movie' else 'shows'))
        names = ['Action', 'Adventure', 'Animation', 'Comedy', 'Crime', 'Documentary', 'Drama', 'Family', 'Fantasy', 'History', 'Horror', 'Mystery', 'Romance', 'Sci-Fi', 'Thriller', 'War', 'Western']
        return [{'name': n, 'slug': n} for n in names]

    def normalize(self, rows, kind):
        result, seen = [], set()
        for row in rows:
            if kind == 'show' and row.get('episode') and row.get('show'):
                obj = dict(row['episode'], show=title_object(row['show'], 'show'), catalog_type='episode', catalog='trakt')
            else:
                obj = row.get(kind, row)
                if not isinstance(obj, dict) or 'title' not in obj or not obj.get('ids'):
                    continue
                obj = title_object(obj, kind)
            key = json.dumps([obj['catalog_type'], obj.get('ids'), obj.get('show', {}).get('ids')], sort_keys=True)
            if key not in seen:
                seen.add(key)
                result.append(obj)
        return result

    def page(self, kind, category, page=1, value=None, obj=None):
        if page < 1 or page > 500:
            raise ValueError('Page is outside the supported range.')
        plural = 'movies' if kind == 'movie' else 'shows'
        limit = prefs.get('page_size')
        params = dict(page=page, limit=limit, extended='full')
        today = datetime.date.today()
        auth, local_page = False, False
        if not self.trakt.client_id and category in ('popular', 'genre', 'year'):
            meta_type = 'movie' if kind == 'movie' else 'series'
            endpoint = 'year' if category == 'year' else 'top'
            extras = ['skip=' + str((page - 1) * limit)]
            if value:
                extras.append('genre=' + segment(value))
            path = 'catalog/{}/{}/{}.json'.format(meta_type, endpoint, '&'.join(extras))
            key = 'catalog:cinemeta:' + hashlib.sha256(path.encode()).hexdigest()
            data = self.db.get(key, max_age=prefs.get('catalog_ttl') * 60)
            if data is None:
                data = self.catalog.get(path)
                self.db.put(key, data)
            rows = []
            raw = data.get('metas', [])
            for r in raw[:limit]:
                imdb = r.get('imdb_id') or r.get('id', '')
                if not imdb.startswith('tt'):
                    continue
                year = str(r.get('releaseInfo') or '')[:4]
                if category == 'year' and year != str(value):
                    continue
                rows.append(dict(title=r['name'], year=int(year) if year.isdigit() else None,
                                 ids={'imdb': imdb}, catalog_type=kind, catalog='cinemeta'))
            return rows, len(raw) >= limit
        if category in ('popular', 'trending', 'anticipated', 'boxoffice'):
            path = '/' + plural + '/' + category
        elif category in ('popular_recent', 'trending_recent'):
            path = '/' + plural + '/' + category.split('_')[0]
            params['years'] = '{}-{}'.format(today.year - 1, today.year)
        elif category in ('played', 'watched', 'collected'):
            path = '/' + plural + '/' + category + '/weekly'
        elif category == 'recommended':
            path, auth, local_page = '/recommendations/' + plural, True, True
            params = {'limit': 100, 'extended': 'full'}
        elif category == 'updated':
            path = '/' + plural + '/updates/' + (today - datetime.timedelta(days=7)).isoformat()
        elif category in ('genre', 'year', 'network'):
            path = '/' + plural + '/popular'
            params[{'genre': 'genres', 'year': 'years', 'network': 'networks'}[category]] = value
        elif category == 'new':
            path = '/calendars/all/shows/new/{}/14'.format((today - datetime.timedelta(days=14)).isoformat())
            params, local_page = {'extended': 'full'}, True
        elif category in ('collection', 'watchlist'):
            path, auth, local_page = '/sync/' + category + '/' + plural, True, category == 'collection'
            if local_page:
                params = {'extended': 'full'}
        elif category == 'history':
            path, auth = '/sync/history/episodes', True
            if kind == 'movie':
                path, local_page, params = '/sync/watched/movies', True, {'extended': 'full'}
        elif category in ('upcoming', 'recent_episodes'):
            start = today if category == 'upcoming' else today - datetime.timedelta(days=14)
            path, auth, local_page = '/calendars/my/shows/{}/14'.format(start.isoformat()), True, True
            params = {'extended': 'full'}
        elif category == 'unfinished':
            collection = self.fetch('/sync/collection/shows', {'extended': 'full'}, auth=True)
            watched = self.fetch('/sync/watched/shows', auth=True)
            plays = {r['show']['ids']['trakt']: {(s['number'], e['number']) for s in r.get('seasons', []) for e in s.get('episodes', []) if e.get('plays', 0)} for r in watched}
            rows = []
            for r in collection:
                collected = {(s['number'], e['number']) for s in r.get('seasons', []) for e in s.get('episodes', [])}
                if collected - plays.get(r['show']['ids']['trakt'], set()):
                    rows.append(r)
            rows = self.normalize(rows, kind)
            return rows[(page - 1) * limit:page * limit], len(rows) > page * limit
        elif category in ('lists_trending', 'lists_popular', 'own_lists', 'liked_lists'):
            if category.startswith('lists_'):
                path = '/lists/' + category.split('_')[1] + '/' + kind
            elif category == 'own_lists':
                path, auth, local_page = '/users/me/lists', True, True
                params = {}
            else:
                path, auth = '/users/likes/lists', True
            data = self.fetch(path, params, auth)
            rows = []
            for r in data:
                item = r.get('list', r)
                owner = 'me' if category == 'own_lists' else item.get('user', {}).get('ids', {}).get('slug')
                rows.append(dict(item, catalog_type='list', media_kind=kind, list_owner=owner, personal=auth))
            return (rows[(page - 1) * limit:page * limit], len(rows) > page * limit) if local_page else (rows, len(rows) >= limit)
        elif category == 'list_items':
            path = '/lists/{}/items/{}'.format(segment(obj['ids']['trakt']), kind)
            if obj.get('personal'):
                auth = True
                path = '/users/{}/lists/{}/items/{}'.format(segment(obj.get('list_owner') or 'me'), segment(obj['ids']['trakt']), kind)
        elif category == 'actor_credits':
            path = '/people/{}/{}'.format(segment(value), plural)
            data = self.fetch(path, {'extended': 'full'})
            rows = self.normalize(data.get('cast', []), kind)
            return rows[(page - 1) * limit:page * limit], len(rows) > page * limit
        elif category == 'query':
            path = '/search/' + kind
            params['query'] = value
            if not self.trakt.client_id:
                rows = self.catalog.search(value, kind)
                return rows[(page - 1) * limit:page * limit], len(rows) > page * limit
        else:
            raise ValueError('Unknown catalog menu.')
        data = self.fetch(path, params, auth)
        rows = self.normalize(data, kind)
        if category == 'history' and kind == 'movie':
            data = sorted(data, key=lambda r: r.get('last_watched_at', ''), reverse=True)
            rows = self.normalize(data, kind)
        if category == 'new':
            rows = [title_object(r['show'], 'show') for r in data if r.get('show')]
            rows = self.normalize(rows, 'show')
        if category == 'recent_episodes':
            rows.reverse()
        if local_page:
            return rows[(page - 1) * limit:page * limit], len(rows) > page * limit
        return rows, len(data) >= limit and category != 'boxoffice'
