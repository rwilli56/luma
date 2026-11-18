"""Device-login state transitions with fake time and Kodi UI doubles."""
from contextlib import ExitStack
import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin.video.luma'))
from resources.lib.net import ApiError, Http
from resources.lib.store import Store
from resources.lib.trakt import Trakt


def device(**changes):
    data = {'device_code': 'private-device-code', 'user_code': 'TESTCODE', 'verification_url': 'https://trakt.tv/activate', 'interval': 5, 'expires_in': 600}
    return dict(data, **changes)


def token(**changes):
    return dict({'access_token': 'private-access', 'refresh_token': 'private-refresh',
                 'created_at': int(time.time()), 'expires_in': 604800}, **changes)


class TraktResponseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'auth.db'))

    def tearDown(self):
        self.temp.cleanup()

    def test_oauth_host_and_headers_match_official_contract(self):
        client = Trakt(self.db, ' client-id ')
        self.assertEqual(client.auth.base, 'https://auth.trakt.tv')
        self.assertEqual(client.auth.headers['trakt-api-key'], 'client-id')
        self.assertEqual(client.auth.headers['trakt-api-version'], '2')

    def test_device_response_validated_before_display(self):
        auth = Mock()
        client = Trakt(self.db, 'client', auth=auth)
        for bad in ({}, [], device(interval=0), device(expires_in='600'), device(verification_url='http://wrong.test')):
            auth.request.return_value = bad
            with self.subTest(shape=type(bad).__name__), self.assertRaises(ValueError):
                client.device_code()
        auth.request.return_value = device()
        self.assertEqual(client.device_code()['user_code'], 'TESTCODE')

    def test_invalid_token_never_replaces_existing_connection(self):
        original = token()
        self.db.put('trakt_tokens', original)
        auth = Mock()
        auth.request.return_value = {'access_token': 'incomplete'}
        with self.assertRaisesRegex(ValueError, 'existing connection'):
            Trakt(self.db, 'client', auth=auth).device_token('code')
        self.assertEqual(self.db.get('trakt_tokens'), original)

    def test_rejected_application_id_gets_setup_error_before_polling(self):
        auth = Mock()
        auth.request.side_effect = ApiError('Trakt', 401)
        with self.assertRaisesRegex(ValueError, 'application Client ID'):
            Trakt(self.db, 'wrong-client', auth=auth).device_code()

    def test_http_oauth_error_keeps_only_known_identifier(self):
        opener = Mock(side_effect=HTTPError('https://auth.trakt.tv/oauth/device/token', 400, 'Bad', {},
                     io.BytesIO(b'{"error":"invalid_client","error_description":"private-access-value"}')))
        with self.assertRaises(ApiError) as caught:
            Http('https://auth.trakt.tv', 'Trakt', opener=opener).request('POST', '/oauth/device/token', body={})
        self.assertEqual(caught.exception.code, 'invalid_client')
        self.assertNotIn('private', str(caught.exception))
        self.assertNotIn('private', str(vars(caught.exception)))


class Progress:
    def __init__(self):
        self.created, self.closed, self.cancelled = False, False, False

    def create(self, *args):
        self.created = True

    def iscanceled(self):
        return self.cancelled

    def close(self):
        if not self.created:
            raise AssertionError('Must not close a dialog that has not been created')
        self.closed = True


class LoginUiTests(unittest.TestCase):
    def setUp(self):
        import test_kodi_handoff
        self.app = test_kodi_handoff.app
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'ui.db'))
        self.client = Mock()
        self.client.device_code.return_value = device()
        self.client.device_token.side_effect = [ApiError('Trakt', 400), token()]
        self.progress, self.dialog, self.addon = Progress(), Mock(), Mock()
        self.monitor = Mock()
        self.monitor.abortRequested.return_value = False
        self.monitor.waitForAbort.side_effect = self.advance
        self.now = 0
        self.client_id = 'client-id'

    def advance(self, seconds):
        self.now += seconds
        return False

    def tearDown(self):
        self.temp.cleanup()

    def connect(self):
        app = self.app
        with ExitStack() as stack:
            stack.enter_context(patch.object(app.config, 'setting', side_effect=lambda key: self.client_id if key == 'trakt_client_id' else ''))
            stack.enter_context(patch.object(app.config, 'addon', return_value=self.addon))
            stack.enter_context(patch.object(app.xbmcgui, 'Dialog', return_value=self.dialog))
            progress_factory = stack.enter_context(patch.object(app.xbmcgui, 'DialogProgress', return_value=self.progress, create=True))
            stack.enter_context(patch.object(app.xbmc, 'Monitor', return_value=self.monitor))
            stack.enter_context(patch.object(app.time, 'monotonic', side_effect=lambda: self.now))
            stack.enter_context(patch.object(app, 'Trakt', return_value=self.client))
            stack.enter_context(patch.object(app, 'notify'))
            app.connect_trakt(self.db)
            return progress_factory

    def test_missing_client_id_explains_setup_and_does_not_start_a_dialog(self):
        self.client_id = ''
        self.dialog.yesno.return_value = False
        factory = self.connect()
        self.dialog.yesno.assert_called_once()
        self.client.device_code.assert_not_called()
        factory.assert_not_called()
        self.assertIsNone(self.db.get('auth_pending'))

    def test_missing_client_id_can_be_entered_without_leaving_connect_flow(self):
        self.client_id = ''
        self.dialog.yesno.return_value = True
        self.dialog.input.return_value = 'new-client-id'
        self.connect()
        self.addon.setSetting.assert_called_once_with('trakt_client_id', 'new-client-id')
        self.assertTrue(self.db.get('request_sync'))

    def test_pending_then_success_waits_requested_interval_and_cleans_up(self):
        self.connect()
        self.assertEqual(self.now, 10)
        self.assertEqual(self.client.device_token.call_count, 2)
        self.assertTrue(self.progress.closed)
        self.assertFalse(self.db.get('auth_pending'))
        self.assertTrue(self.db.get('request_sync'))

    def test_failure_before_dialog_creation_does_not_mask_the_error(self):
        self.client.device_code.side_effect = ValueError('Invalid activation response')
        with self.assertRaisesRegex(ValueError, 'Invalid activation'):
            self.connect()
        self.assertFalse(self.progress.closed)
        self.assertFalse(self.db.get('auth_pending'))

    def test_cancel_does_not_poll_or_replace_tokens(self):
        self.db.put('trakt_tokens', token())
        self.progress.cancelled = True
        self.connect()
        self.client.device_token.assert_not_called()
        self.assertEqual(self.db.get('trakt_tokens')['access_token'], 'private-access')
        self.assertFalse(self.db.get('auth_pending'))

    def test_expiry_stops_before_next_poll(self):
        self.client.device_code.return_value = device(expires_in=2)
        self.connect()
        self.assertEqual(self.now, 2)
        self.client.device_token.assert_not_called()
        self.assertFalse(self.db.get('auth_pending'))

    def test_rate_limit_slows_polling(self):
        self.client.device_token.side_effect = [ApiError('Trakt', 429, 7), token()]
        self.connect()
        self.assertEqual(self.now, 15)

    def test_declined_or_invalid_client_stops_instead_of_polling_until_expiry(self):
        for error in (ApiError('Trakt', 418), ApiError('Trakt', 400, code='invalid_client')):
            self.client.device_token.reset_mock(side_effect=True)
            self.client.device_token.side_effect = error
            with self.subTest(status=error.status), self.assertRaises(ValueError):
                self.connect()
            self.assertEqual(self.client.device_token.call_count, 1)
            self.assertFalse(self.db.get('auth_pending'))


if __name__ == '__main__':
    unittest.main()
