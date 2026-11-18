"""Trakt requires local image caching. Small, bounded, idle-only downloads."""
import hashlib
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def image_url(media):
    images = media.get('trakt', {}).get('images', {})
    for kind in ('thumb', 'fanart', 'poster'):
        values = images.get(kind) or []
        if isinstance(values, list) and values and isinstance(values[0], str):
            url = values[0]
            url = url if url.startswith('https://') else 'https://' + url
            parsed = urlsplit(url)
            if parsed.scheme == 'https' and (parsed.hostname or '').endswith('.trakt.tv'):
                return url
    return ''


def cached_path(db, media, cached=None):
    url = image_url(media)
    key = 'art:' + hashlib.sha256(url.encode()).hexdigest()
    path = (cached.get(key, '') if cached is not None else db.get(key, '')) if url else ''
    return path if path and os.path.isfile(path) else ''


def refresh(db, profile, items, budget=6, should_defer=None):
    directory = os.path.join(profile, 'artwork')
    os.makedirs(directory, exist_ok=True)
    for item in items:
        if budget <= 0 or (should_defer and should_defer()):
            break
        url = image_url(item)
        if not url or cached_path(db, item):
            continue
        key = hashlib.sha256(url.encode()).hexdigest()
        path = os.path.join(directory, key + '.webp')
        budget -= 1
        try:
            with urlopen(Request(url, headers={'User-Agent': 'Luma-Kodi/0.1.0'}), timeout=6) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024 or not data.startswith(b'RIFF') or data[8:12] != b'WEBP':
                continue
            with open(path + '.part', 'wb') as output:
                output.write(data)
            os.replace(path + '.part', path)
            db.put('art:' + key, path)
        except OSError:
            continue
    files = sorted((os.path.join(directory, f) for f in os.listdir(directory) if f.endswith('.webp')), key=os.path.getmtime)
    total = sum(os.path.getsize(f) for f in files)
    for path in files:
        if total <= 50 * 1024 * 1024:
            break
        total -= os.path.getsize(path)
        os.remove(path)
