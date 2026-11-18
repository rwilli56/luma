"""Title metadata only. Stream sources always come from installed providers."""
import datetime
import re
from urllib.parse import quote
from .media import identity
from .net import Http
from .trakt import media_from_trakt


class Catalog:
    def __init__(self, db, trakt=None, http=None):
        self.db, self.trakt = db, trakt
        self.http = http or Http('https://v3-cinemeta.strem.io', 'Cinemeta')

    def search(self, query, kind):
        if self.trakt and self.trakt.client_id:
            return [dict(r[kind], catalog_type=kind, catalog='trakt') for r in self.trakt.search(query, kind) if kind in r]
        media_type = 'series' if kind == 'show' else 'movie'
        data = self.http.request('GET', 'catalog/{}/top/search={}.json'.format(media_type, quote(query, safe='')))
        result = []
        for item in data.get('metas', [])[:30]:
            imdb = item.get('imdb_id') or item.get('id', '')
            if not re.fullmatch(r'tt\d+', imdb):
                continue
            year = re.match(r'\d{4}', str(item.get('releaseInfo', '')))
            result.append({'title': item['name'], 'year': int(year.group()) if year else None,
                           'ids': {'imdb': imdb}, 'catalog_type': kind, 'catalog': 'cinemeta'})
        return result

    def episodes(self, show):
        cache_key = 'catalog_episodes:' + str(show['ids'].get('trakt') or show['ids'].get('imdb'))
        cached = self.db.get(cache_key, max_age=3600)
        if cached is not None:
            return cached
        result = []
        if show.get('catalog') == 'trakt':
            seasons = self.trakt.call('GET', '/shows/{}/seasons'.format(show['ids']['trakt']), authenticated=False)
            # Fetch episode details for a season only when it is opened.
            return [{'season': s['number'], 'trakt_season': True} for s in seasons if s.get('number', 0) >= 0]
        data = self.http.request('GET', 'meta/series/{}.json'.format(show['ids']['imdb']))
        now = datetime.datetime.now(datetime.timezone.utc)
        for item in data.get('meta', {}).get('videos', []):
            season, number = item.get('season'), item.get('episode', item.get('number'))
            if not isinstance(season, int) or not isinstance(number, int):
                continue
            aired = item.get('released') or item.get('firstAired', '')
            try:
                if datetime.datetime.fromisoformat(aired.replace('Z', '+00:00')) > now:
                    continue
            except (ValueError, TypeError):
                continue
            imdb = item.get('imdb_id', '')
            result.append({'season': season, 'number': number, 'title': item.get('name', ''), 'first_aired': aired,
                           'ids': {'imdb': imdb} if re.fullmatch(r'tt\d+', imdb) else {}})
        self.db.put(cache_key, result)
        return result

    def season(self, show, number, episodes):
        if show.get('catalog') != 'trakt':
            return [e for e in episodes if e['season'] == number]
        items = self.trakt.call('GET', '/shows/{}/seasons/{}'.format(show['ids']['trakt'], number),
                                params={'extended': 'full'}, authenticated=False)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return [dict(e, season=number) for e in items if e.get('first_aired') and e['first_aired'] <= now]

    @staticmethod
    def media(title, episode=None):
        if title.get('catalog') == 'trakt':
            media = media_from_trakt(episode or title, title if episode else None)
        else:
            season, number = (episode['season'], episode['number']) if episode else (None, None)
            media = {'key': identity(title['title'], title.get('year'), season, number),
                     'title': title['title'], 'year': title.get('year'), 'type': 'episode' if episode else 'movie',
                     'season': season, 'episode': number, 'show_key': identity(title['title'], title.get('year')) if episode else '',
                     'episode_title': episode.get('title', '') if episode else '',
                     'trakt': {'ids': episode['ids'] if episode else title['ids'], 'show_ids': title['ids'] if episode else {}}}
        if episode:
            media['premiered'] = (episode.get('first_aired') or '')[:10]
        return media
