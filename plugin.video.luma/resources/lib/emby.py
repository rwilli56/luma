"""Optional local Emby library. Static original-file playback; no transcoding."""
import hashlib
import json
import re
import uuid
import time
from urllib.parse import urlencode, urlsplit
from .media import traits
from .net import Http
from .trakt import timestamp, utc


class Emby:
    def __init__(self, server, token, user_id, http=None, should_defer=None):
        server = server.strip().rstrip('/')
        parsed = urlsplit(server)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('Enter an Emby server URL such as http://192.168.1.10:8096.')
        if not token or not re.fullmatch(r'[a-zA-Z0-9-]+', user_id):
            raise ValueError('Enter an Emby API key and user ID in Luma settings.')
        self.base = server if server.endswith('/emby') else server + '/emby'
        self.token, self.user_id = token, user_id
        self.server_id = hashlib.sha256((self.base + '|' + user_id).encode()).hexdigest()[:12]
        self.should_defer = should_defer or (lambda: False)
        self.http = http or Http(self.base, 'Emby', {'X-Emby-Token': token,
            'X-Emby-Authorization': 'Emby Client="Luma", Device="Kodi", DeviceId="Luma-Kodi", Version="0.1.0"'})

    def media(self, item):
        episode = item['Type'] == 'Episode'
        provider = item.get('ProviderIds') or {}
        ids = {key.lower(): value for key, value in provider.items() if key.lower() in ('tmdb', 'imdb', 'tvdb')}
        key = 'emby:{}:{}'.format(self.server_id, item['Id'])
        sources = item.get('MediaSources') or [{'Id': item['Id'], 'Name': item['Name'], 'Size': item.get('Size', 0)}]
        result = {'key': key, 'title': item.get('SeriesName', item['Name']) if episode else item['Name'],
                  'year': item.get('ProductionYear'), 'season': item.get('ParentIndexNumber') if episode else None,
                  'episode': item.get('IndexNumber') if episode else None, 'type': 'episode' if episode else 'movie',
                  'show_key': 'emby:{}:{}'.format(self.server_id, item.get('SeriesId')) if episode else '',
                  'episode_title': item['Name'] if episode else '', 'overview': item.get('Overview', ''),
                  'emby': {'id': item['Id'], 'server_id': self.server_id}, 'trakt': {'ids': ids}, 'sources': []}
        for source in sources:
            name = source.get('Path') or source.get('Name') or item['Name']
            hint = traits(name)
            video = next((s for s in source.get('MediaStreams', []) if s.get('Type') == 'Video'), {})
            if video.get('Height'):
                hint['resolution'] = video['Height']
            result['sources'].append({'kind': 'emby', 'item_id': item['Id'], 'media_source_id': source['Id'],
                                      'name': source.get('Name') or item['Name'], 'size': source.get('Size') or 0,
                                      'ready': True, 'traits': hint})
        user = item.get('UserData') or {}
        result.update(position=user.get('PlaybackPositionTicks', 0) / 10000000,
                      duration=item.get('RunTimeTicks', 0) / 10000000, completed=user.get('Played', False),
                      updated=timestamp(user.get('LastPlayedDate')))
        return result

    def library(self):
        offset, items = 0, []
        while True:
            if self.should_defer():
                from .trakt import SyncDeferred
                raise SyncDeferred()
            response = self.http.request('GET', '/Users/{}/Items'.format(self.user_id), params={
                'Recursive': 'true', 'IncludeItemTypes': 'Movie,Episode', 'StartIndex': offset, 'Limit': 100,
                'Fields': 'MediaSources,MediaStreams,ProviderIds,Overview', 'EnableUserData': 'true'})
            batch = response.get('Items', [])
            items.extend(self.media(item) for item in batch)
            offset += len(batch)
            if not batch or offset >= response.get('TotalRecordCount', offset):
                return items
            if offset >= 10000:
                raise ValueError('Emby library exceeds 10,000 videos.')

    def resolve(self, source):
        session = uuid.uuid4().hex
        return self.base + '/Videos/{}/stream?'.format(source['item_id']) + urlencode({
            'Static': 'true', 'MediaSourceId': source['media_source_id'], 'PlaySessionId': session,
            'api_key': self.token})

    def flush(self, db):
        for event in db.pending():
            if self.should_defer():
                from .trakt import SyncDeferred
                raise SyncDeferred()
            value = json.loads(event['value'])
            if value.get('backend') != 'emby' or value['server_id'] != self.server_id:
                continue
            self.http.request('POST', '/Users/{}/Items/{}/UserData'.format(self.user_id, value['id']),
                              body={'PlaybackPositionTicks': value['ticks'], 'Played': value['completed'],
                                    'LastPlayedDate': value['watched_at']})
            db.acknowledge(event['key'], event['version'])


def queue_emby(db, media, position, completed):
    if media.get('emby'):
        db.enqueue(media['key'] + ':emby', dict(media['emby'], backend='emby',
                   ticks=0 if completed else int(position * 10000000), completed=completed, watched_at=utc(time.time())))
