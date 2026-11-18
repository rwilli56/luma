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

    def add(self, link):
        link = link.strip()
        parsed = urlsplit(link)
        if parsed.scheme.lower() == 'magnet' and 'xt=urn:btih:' in link.lower():
            return self._call('POST', 'torrents/createtorrent', form={'magnet': link, 'seed': '1', 'allow_zip': 'false'})
        if parsed.scheme.lower() in ('http', 'https') and parsed.hostname:
            return self._call('POST', 'webdl/createwebdownload', form={'link': link})
        raise ValueError('Enter a magnet link or an HTTP(S) file link.')
