"""Small HTTPS transport. Never include URLs, bodies or credentials in errors."""
import json
import socket
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ApiError(Exception):
    def __init__(self, service, status=0, retry_after=0):
        self.status = status
        self.retry_after = retry_after
        messages = {401: 'Please reconnect your account.', 403: 'Access denied. Check your account and API permissions.',
                    429: 'Rate limit reached. Please try again later.'}
        super().__init__('{}: {}'.format(service, messages.get(status, 'Request failed. Please try again.')))


def multipart(fields):
    boundary = 'luma-' + uuid.uuid4().hex
    parts = []
    for key, value in fields.items():
        parts.append('--{}\r\nContent-Disposition: form-data; name="{}"\r\n\r\n{}\r\n'.format(boundary, key, value))
    parts.append('--{}--\r\n'.format(boundary))
    return ''.join(parts).encode('utf-8'), 'multipart/form-data; boundary=' + boundary


class Http:
    def __init__(self, base, service, headers=None, timeout=12, opener=urlopen, sleeper=time.sleep):
        self.base, self.service = base.rstrip('/'), service
        self.headers = headers or {}
        self.timeout, self.opener, self.sleeper = timeout, opener, sleeper

    def request(self, method, path, params=None, body=None, form=None, headers=None):
        url = self.base + '/' + path.lstrip('/')
        if params:
            url += '?' + urlencode(params, doseq=True)
        request_headers = {'Accept': 'application/json', 'User-Agent': 'Luma-Kodi/0.3.0'}
        request_headers.update(self.headers)
        request_headers.update(headers or {})
        data = None
        if form is not None:
            data, request_headers['Content-Type'] = multipart(form)
        elif body is not None:
            data = json.dumps(body).encode('utf-8')
            request_headers['Content-Type'] = 'application/json'
        # Only safe GET requests are retried. Mutations may already have succeeded.
        attempts = 2 if method == 'GET' else 1
        for attempt in range(attempts):
            try:
                req = Request(url, data=data, headers=request_headers, method=method)
                with self.opener(req, timeout=self.timeout) as response:
                    raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise ApiError(self.service)
                return json.loads(raw.decode('utf-8')) if raw else {}
            except HTTPError as exc:
                try:
                    retry = min(3600, max(1, int(exc.headers.get('Retry-After', '30'))))
                except (TypeError, ValueError):
                    retry = 30
                exc.close()
                if exc.code in (502, 503, 504) and attempt + 1 < attempts:
                    self.sleeper(0.3)
                    continue
                raise ApiError(self.service, exc.code, retry) from None
            except (URLError, socket.timeout, TimeoutError, OSError):
                if attempt + 1 < attempts:
                    self.sleeper(0.3)
                    continue
                raise ApiError(self.service) from None
            except (ValueError, UnicodeError):
                raise ApiError(self.service) from None
