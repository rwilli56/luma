"""Adapters for separately installed CocoScrapers and Magneto/POV modules.

No provider code or service credentials are bundled or sent to a scraper.
"""
import base64
import copy
import importlib
import json
import os
import queue
import re
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
from .media import EPISODE, parse_name, traits

BACKENDS = (
    ('coco', 'CocoScrapers', 'script.module.cocoscrapers', 'cocoscrapers'),
    ('pov', 'Magneto / POV', 'plugin.video.pov', 'pov'),
)


def installed():
    import xbmc
    import xbmcaddon
    import xbmcvfs
    result = []
    for key, label, addon_id, module in BACKENDS:
        item = dict(key=key, label=label, addon_id=addon_id, module=module, available=False)
        try:
            response = json.loads(xbmc.executeJSONRPC(json.dumps({
                'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.GetAddonDetails',
                'params': {'addonid': addon_id, 'properties': ['enabled']}})))
            if response.get('result', {}).get('addon', {}).get('enabled') is True:
                addon = xbmcaddon.Addon(addon_id)
                item.update(available=True, version=addon.getAddonInfo('version'),
                            path=xbmcvfs.translatePath(addon.getAddonInfo('path')))
                try:
                    settings = os.stat(os.path.join(xbmcvfs.translatePath(addon.getAddonInfo('profile')), 'settings.xml'))
                    item['settings_revision'] = [settings.st_mtime_ns, settings.st_size]
                except OSError:
                    item['settings_revision'] = None
        except Exception:
            pass
        result.append(item)
    return result


def load(backends):
    tasks, failures = [], []
    for backend in backends:
        try:
            path = os.path.join(backend['path'], 'lib')
            if path not in sys.path:
                sys.path.insert(0, path)
            module = importlib.import_module(backend['module'])
            # ret_all stays False: respect the provider's own enabled switches.
            for name, factory in module.sources():
                tasks.append((backend['label'] + ' / ' + name, factory))
                if getattr(factory, 'pack_capable', False) and hasattr(factory, 'sources_packs'):
                    tasks.append((backend['label'] + ' / ' + name + ' (packs)', factory, 'sources_packs'))
        except Exception:
            failures.append(backend['label'])
    return tasks, failures


def query_data(media, timeout):
    episode = media['type'] == 'episode'
    metadata = media.get('trakt', {})
    ids = metadata.get('show_ids' if episode else 'ids', {})
    data = {'title': (media.get('episode_title') or '') if episode else media['title'],
            'year': str(media.get('year') or ''), 'imdb': ids.get('imdb') or '',
            'tmdb': str(ids.get('tmdb') or ''), 'tvdb': str(ids.get('tvdb') or ''),
            'aliases': [], 'timeout': max(1, int(timeout))}
    if episode:
        data.update(tvshowtitle=media['title'], season=str(media['season']), episode=str(media['episode']),
                    premiered=media.get('premiered', ''))
    return data


def infohash(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.lower().startswith('magnet:'):
        values = parse_qs(urlsplit(value).query).get('xt', [])
        value = next((v[9:] for v in values if v.lower().startswith('urn:btih:')), '')
    if re.fullmatch(r'[a-fA-F0-9]{40}', value):
        return value.lower()
    if re.fullmatch(r'[A-Za-z2-7]{32}', value):
        return base64.b32decode(value.upper()).hex()
    return None


def normalize(result, provider, media):
    if not isinstance(result, dict) or result.get('source', '').lower() != 'torrent':
        return None
    hash_value, url_hash = infohash(result.get('hash')), infohash(result.get('url'))
    if hash_value and url_hash and hash_value != url_hash:
        return None
    hash_value = hash_value or url_hash
    name = result.get('name')
    if not hash_value or not isinstance(name, str) or not name.strip():
        return None
    parsed = parse_name(name + '.mkv')
    if parsed['ambiguous']:
        return None
    if media['type'] == 'episode':
        if EPISODE.search(name.replace('_', ' ')) and (parsed['season'], parsed['episode']) != (media['season'], media['episode']):
            return None
        # Packs are allowed, but a different explicitly named season is not.
        season = re.search(r'(?i)(?:\bS|\bSeason[ ._-]*)(\d{1,2})(?:\b|E)', name.replace('_', ' '))
        if season and int(season.group(1)) != media['season']:
            return None
    elif parsed['type'] == 'episode' or (parsed['year'] and media.get('year') and parsed['year'] != media['year']):
        return None
    try:
        # Both interfaces report numeric size in GiB, rather than bytes.
        size = max(0, float(result.get('size') or 0)) * 1024 ** 3
    except (ValueError, TypeError):
        size = 0
    return {'hash': hash_value, 'magnet': 'magnet:?xt=urn:btih:' + hash_value,
            'name': name[:1000], 'provider': provider, 'size': size,
            'traits': traits(name + ' ' + str(result.get('quality', '')))}


class ScrapeSession:
    """Small daemon worker pool. Only this object's owner updates Kodi UI/SQLite.

    Deadline/cancellation stops dispatching new tasks. Third-party requests
    already in progress cannot be forcibly interrupted by Python.
    """
    def __init__(self, tasks, media, timeout=20, workers=4):
        self.media, self.deadline = copy.deepcopy(media), time.monotonic() + timeout
        self.stop = threading.Event()
        self.pending, self.results = queue.Queue(), queue.Queue()
        self.total, self.completed, self.failed = len(tasks), 0, 0
        for task in tasks:
            self.pending.put(task)
        self.threads = [threading.Thread(target=self._worker, daemon=True) for _ in range(min(workers, len(tasks)))]
        for thread in self.threads:
            thread.start()

    def _worker(self):
        while not self.stop.is_set() and time.monotonic() < self.deadline:
            try:
                task = self.pending.get_nowait()
                label, factory = task[:2]
                method = task[2] if len(task) > 2 else 'sources'
            except queue.Empty:
                return
            items, failed = [], False
            try:
                remaining = max(1, int(self.deadline - time.monotonic()))
                scraper = factory()
                if hasattr(scraper, 'timeout'):
                    scraper.timeout = remaining
                if method == 'sources_packs' and self.media['type'] != 'episode':
                    raw = []
                else:
                    raw = getattr(scraper, method)(query_data(self.media, remaining), {}) or []
                for item in raw[:2000]:
                    value = normalize(item, label, self.media)
                    if value:
                        items.append(value)
            except Exception:
                failed = True
            self.results.put((items, failed))

    def poll(self):
        items = []
        while True:
            try:
                batch, failed = self.results.get_nowait()
            except queue.Empty:
                break
            items.extend(batch)
            self.completed += 1
            self.failed += int(failed)
        return items

    @property
    def finished(self):
        return self.completed == self.total or (not any(t.is_alive() for t in self.threads) and self.results.empty())

    @property
    def expired(self):
        return time.monotonic() >= self.deadline
