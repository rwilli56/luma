"""Selected-source validation. Bulk checks never open CDN streams."""
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from . import episodes
from .media import flatten
from .net import ApiError, TORBOX_ACCOUNT_CODES
from .providers import infohash


class SourceUnavailable(ValueError):
    pass


class SelectionCancelled(Exception):
    pass


def account_failure(exc):
    return isinstance(exc, ApiError) and (exc.status in (401, 403, 429) or exc.code in TORBOX_ACCOUNT_CODES)


class LinkUnavailable(SourceUnavailable):
    def __init__(self, status=0):
        self.status = status
        super().__init__('The selected TorBox playback link is unavailable. Choose another source.')


class SecureRedirects(HTTPRedirectHandler):
    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme.lower() != 'https':
            raise LinkUnavailable()
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def probe_link(url, opener=None):
    """Read at most one byte and close, even when a CDN ignores Range."""
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or '|' in url:
        raise LinkUnavailable()
    request = Request(url, headers={'Range': 'bytes=0-0', 'Accept-Encoding': 'identity', 'User-Agent': 'Luma-Kodi/0.4.0'}, method='GET')
    try:
        opener = opener or build_opener(SecureRedirects()).open
        with opener(request, timeout=5) as response:
            status = response.status
            final = urlsplit(response.geturl())
            content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
            if status not in (200, 206) or final.scheme != 'https':
                raise LinkUnavailable(status)
            if content_type.startswith('text/') or content_type in ('application/json', 'application/problem+json'):
                raise LinkUnavailable(status)
            if not response.read(1):
                raise LinkUnavailable(status)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise LinkUnavailable(status) from None
    except (URLError, OSError, socket.timeout, TimeoutError, ValueError):
        raise LinkUnavailable() from None


def prepare(api, candidate, stopped=lambda: False, wait=lambda seconds: False, clock=time.monotonic):
    """Recheck only the chosen hash and wait for its original files to be ready."""
    if stopped():
        raise SelectionCancelled()
    hash_value = infohash(candidate.get('hash'))
    if not hash_value or hash_value not in api.cached([hash_value]):
        raise SourceUnavailable('This torrent is no longer cached on TorBox. Choose another source.')
    if stopped():
        raise SelectionCancelled()
    transfer_id = candidate.get('transfer_id')
    if transfer_id is None:
        created = api.add(candidate['magnet'], cached_only=True)
        transfer_id = created.get('torrent_id') if isinstance(created, dict) else None
    if transfer_id is None:
        raise SourceUnavailable('TorBox did not return a playable transfer. Check the account or choose another source.')
    deadline = clock() + 25
    while True:
        if stopped():
            raise SelectionCancelled()
        try:
            transfer = api.torrent(transfer_id)
        except ApiError as exc:
            if exc.status != 404 or clock() >= deadline:
                raise
            transfer = {}
        remote_hash = infohash(transfer.get('hash'))
        if transfer.get('hash') and remote_hash != hash_value:
            raise SourceUnavailable('TorBox returned a different torrent. Choose another source.')
        if transfer.get('download_finished') is True and transfer.get('download_present') is True:
            return transfer
        if clock() >= deadline:
            raise SourceUnavailable('The selected transfer is not ready. Refresh your library or choose another source.')
        if wait(1):
            raise SelectionCancelled()


def candidates(transfer, media, manual=False):
    items = flatten([transfer], 'torrents')
    if media['type'] != 'episode':
        return [i for i in items if i['type'] == 'movie' and not episodes.is_extra(i['sources'][0]['path'], media['title'])]
    test = episodes.manual_candidate if manual else episodes.matches
    return [i for i in items if not episodes.is_extra(i['sources'][0]['path'], media['title'])
            and test(i['sources'][0]['path'], media, transfer.get('name', ''))]


def resolve_selected(api, source, media, check_link=True, probe=None):
    """Refresh stale file records, then generate and optionally check one CDN URL."""
    if source['kind'] == 'torrents' and not 0 <= time.time() - source.get('verified_at', 0) <= 15:
        transfer = api.torrent(source['transfer_id'])
        expected_hash = infohash(source.get('hash'))
        actual_hash = infohash(transfer.get('hash'))
        if expected_hash and transfer.get('hash') and expected_hash != actual_hash:
            raise SourceUnavailable('The selected torrent changed. Refresh your library.')
        if actual_hash:
            source['hash'] = actual_hash
        possible = candidates(transfer, media)
        selected = next((i for i in possible if str(i['sources'][0]['file_id']) == str(source['file_id'])), None)
        if not selected and source.get('manual_episode') == [media.get('season'), media.get('episode')]:
            manual = candidates(transfer, media, manual=True)
            selected = next((i for i in manual if str(i['sources'][0]['file_id']) == str(source['file_id'])
                             and i['sources'][0]['path'] == source.get('path')), None)
        if not selected or not selected['sources'][0]['ready']:
            raise SourceUnavailable('The selected file is missing, incomplete or no longer matches this episode.')
    url = api.resolve(source)
    if check_link:
        probe = probe or probe_link
        try:
            probe(url)
        except LinkUnavailable as exc:
            if exc.status not in (401, 403, 404, 410):
                raise
            # Refresh an expired/invalidated CDN URL once, without caching either URL.
            url = api.resolve(source)
            probe(url)
    return url
