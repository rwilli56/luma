from urllib.parse import urlsplit
from .net import ApiError, Http


class TorBox:
    def __init__(self, key, http=None, should_defer=None):
        if not key:
            raise ValueError('Add your TorBox API key in Luma settings.')
        self.key = key
        self.http = http or Http('https://api.torbox.app/v1/api', 'TorBox', {'Authorization': 'Bearer ' + key})
        self.should_defer = should_defer or (lambda: False)

    def _call(self, method, path, **kwargs):
        if self.should_defer():
            from .trakt import SyncDeferred
            raise SyncDeferred()
        response = self.http.request(method, path, **kwargs)
        if not isinstance(response, dict) or response.get('success') is not True:
            raise ApiError('TorBox')
        return response.get('data')

    def library(self, kind):
        if kind not in ('torrents', 'webdl'):
            raise ValueError('Unsupported library type.')
        items, offset = [], 0
        while True:
            page = self._call('GET', kind + '/mylist', params={'offset': offset, 'limit': 100}) or []
            if not isinstance(page, list):
                raise ApiError('TorBox')
            items.extend(page)
            if len(page) < 100:
                return items
            offset += len(page)
            if offset >= 10000:
                raise ValueError('TorBox library exceeds 10,000 transfers. Please narrow your library.')

    def resolve(self, source):
        kind = source['kind']
        if kind not in ('torrents', 'webdl'):
            raise ValueError('Unsupported source.')
        id_key = 'torrent_id' if kind == 'torrents' else 'web_id'
        url = self._call('GET', kind + '/requestdl', params={
            'token': self.key, id_key: source['transfer_id'], 'file_id': source['file_id'], 'redirect': 'false'})
        if not isinstance(url, str) or urlsplit(url).scheme != 'https' or not urlsplit(url).hostname:
            raise ApiError('TorBox')
        return url

    def cached(self, hashes):
        """Return only explicit cache hits, in bounded batches."""
        hits = {}
        hashes = list(dict.fromkeys(hashes))
        for start in range(0, len(hashes), 100):
            batch = hashes[start:start + 100]
            data = self._call('GET', 'torrents/checkcached', params={'hash': batch, 'format': 'object'})
            if isinstance(data, dict):
                rows = [(key, value) for key, value in data.items() if isinstance(value, dict)]
            elif isinstance(data, list):
                rows = [(value.get('hash', ''), value) for value in data if isinstance(value, dict)]
            else:
                raise ApiError('TorBox')
            for key, value in rows:
                key = key.lower()
                if key in batch and value and value.get('cached') is not False:
                    hits[key] = value
        return hits

    def torrent(self, transfer_id):
        data = self._call('GET', 'torrents/mylist', params={'id': transfer_id, 'bypass_cache': 'true'})
        if isinstance(data, list):
            data = next((item for item in data if str(item.get('id')) == str(transfer_id)), None)
        if not isinstance(data, dict) or str(data.get('id')) != str(transfer_id):
            raise ApiError('TorBox')
        return data

    def add(self, link, cached_only=False):
        link = link.strip()
        parsed = urlsplit(link)
        if parsed.scheme.lower() == 'magnet' and 'xt=urn:btih:' in link.lower():
            form = {'magnet': link, 'seed': '1', 'allow_zip': 'false'}
            if cached_only:
                form['add_only_if_cached'] = 'true'
            return self._call('POST', 'torrents/createtorrent', form=form)
        if parsed.scheme.lower() in ('http', 'https') and parsed.hostname:
            return self._call('POST', 'webdl/createwebdownload', form={'link': link})
        raise ValueError('Enter a magnet link or an HTTP(S) file link.')
