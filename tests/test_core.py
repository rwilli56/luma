import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin.video.luma'))
from resources.lib.media import flatten, identity, merge_library, parse_name, source_rank, traits
from resources.lib.store import Store
from resources.lib.library import home_rows, match_media, refresh_library
from resources.lib.net import ApiError, Http
from resources.lib.torbox import TorBox
from resources.lib.trakt import Trakt, media_from_trakt, queue_progress
from resources.lib.emby import Emby, queue_emby


def episode(number=1):
    item = parse_name('Example.Show.S01E{:02d}.2160p.HDR10+.EAC3.mkv'.format(number))
    item['sources'] = [{'kind': 'torrents', 'transfer_id': 1, 'file_id': number, 'ready': True,
                        'name': 'test.mkv', 'size': 1e9, 'traits': traits('2160p HDR10+ EAC3')}]
    return item


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'test.db'))

    def tearDown(self):
        self.temp.cleanup()

    def library(self, *items):
        self.db.put('library_torrents', list(items))


class MediaTests(unittest.TestCase):
    def test_episode_and_quality_not_range(self):
        item = episode()
        self.assertEqual((item['title'], item['season'], item['episode']), ('Example Show', 1, 1))
        self.assertFalse(item['ambiguous'])

    def test_pack_parent_fallback(self):
        self.assertEqual(parse_name('S02E03.mkv', 'Example.Show.Season.2')['title'], 'Example Show')

    def test_quality_variants_share_identity(self):
        self.assertEqual(parse_name('Film.2024.1080p.mkv')['key'], parse_name('Film.2024.2160p.HDR.mkv')['key'])

    def test_reboots_do_not_share_identity(self):
        self.assertNotEqual(identity('Film', 1984), identity('Film', 2024))

    def test_multi_episode_is_not_guessed(self):
        for name in ('Show.S01E01E02.mkv', 'Show.S01E01-E02.mkv', 'Show.S01E01-02.mkv'):
            with self.subTest(name=name):
                self.assertTrue(parse_name(name)['ambiguous'])

    def test_samples_and_nonvideo_filtered(self):
        transfer = {'id': 1, 'name': 'Show', 'download_finished': True, 'download_present': True,
                    'files': [{'id': i, 'name': name} for i, name in enumerate(
                        ('Show.S01E01.2160p.mkv', 'sample.mkv', 'cover.jpg', 'Show.S01E02E03.mkv'))]}
        self.assertEqual(len(flatten([transfer], 'torrents')), 1)

    def test_download_state_is_not_readiness(self):
        result = flatten([{'id': 1, 'download_state': 'completed', 'files': [{'id': 2, 'name': 'Film.mkv'}]}], 'torrents')
        self.assertFalse(result[0]['sources'][0]['ready'])

    def test_rank_samsung_hdr10plus_over_dv(self):
        dv, plus = {'traits': traits('2160p DV AAC')}, {'traits': traits('2160p HDR10+ EAC3')}
        self.assertGreater(source_rank(plus), source_rank(dv))

    def test_dv_hdr10_hybrid_has_fallback_hint(self):
        self.assertFalse(traits('2160p DV HDR10')['dv_only'])

    def test_common_audio_before_lossless(self):
        common, lossless = {'traits': traits('1080p AAC')}, {'traits': traits('2160p TrueHD')}
        self.assertGreater(source_rank(common), source_rank(lossless))
        self.assertGreater(source_rank(lossless, lossless=True), source_rank(common, lossless=True))


class HistoryTests(StoreCase):
    def test_progress_survives_new_store(self):
        media = episode()
        self.db.save_progress(media, 100, 1000)
        other = Store(self.db.path)
        self.assertEqual(other.history()[0]['position'], 100)
        self.assertNotIn('sources', other.history()[0])

    def test_signed_urls_not_persisted(self):
        media = dict(episode(), url='https://cdn.test/?token=private')
        self.db.save_progress(media, 100, 1000)
        self.assertNotIn('private', json.dumps(self.db.history()))

    def test_outbox_ack_cannot_delete_newer_event(self):
        self.db.enqueue('a', {'percent': 10})
        old = self.db.pending()[0]
        self.db.enqueue('a', {'percent': 20})
        self.db.acknowledge('a', old['version'])
        self.assertEqual(json.loads(self.db.pending()[0]['value'])['percent'], 20)

    def test_next_up_after_completed_episode(self):
        first, second = episode(1), episode(2)
        self.library(first, second)
        self.db.save_progress(first, 1000, 1000, True)
        rows = home_rows(self.db)
        self.assertEqual(rows['next'][0]['key'], second['key'])
        self.assertEqual(len(rows['shows']), 1)
        self.assertEqual(rows['continue'], [])

    def test_unfinished_episode_suppresses_next_up(self):
        first, second = episode(1), episode(2)
        self.library(first, second)
        self.db.save_progress(first, 500, 1000)
        self.assertEqual(home_rows(self.db)['next'], [])

    def test_offline_next_up_does_not_skip_gaps(self):
        first, third = episode(1), episode(3)
        self.library(first, third)
        self.db.save_progress(first, 1000, 1000, True)
        self.assertEqual(home_rows(self.db)['next'], [])

    def test_completed_local_not_resurrected_by_old_trakt_resume(self):
        media = episode()
        self.library(media)
        self.db.save_progress(media, 1000, 1000, True, updated=200)
        self.db.put('trakt_snapshot', {'continue': [dict(media, position=200, duration=1000, updated=100)]})
        self.assertEqual(home_rows(self.db)['continue'], [])

    def test_recent_series_are_not_limited_to_twenty(self):
        for i in range(35):
            media = parse_name('Series{}.S01E01.mkv'.format(i))
            self.db.save_progress(media, 500, 1000)
        self.assertEqual(len(home_rows(self.db)['shows']), 35)

    def test_partial_library_failure_keeps_saved_data(self):
        self.library(episode())
        client = Mock()
        client.library.side_effect = [ApiError('TorBox'), []]
        self.assertEqual(len(refresh_library(self.db, client)), 1)
        self.assertEqual(len(self.db.get('library_torrents')), 1)

    def test_ambiguous_title_match_rejected(self):
        remote = episode()
        choices = [dict(remote, year=2000), dict(remote, year=2020)]
        self.assertIsNone(match_media(remote, choices))


class ApiTests(unittest.TestCase):
    def test_get_retries_transient_failure(self):
        opener = Mock(side_effect=[URLError('offline'), io.BytesIO(b'{"ok":true}')])
        self.assertEqual(Http('https://test', 'Test', opener=opener, sleeper=lambda _: None).request('GET', '/x'), {'ok': True})
        self.assertEqual(opener.call_count, 2)

    def test_post_not_retried(self):
        opener = Mock(side_effect=URLError('offline'))
        with self.assertRaises(ApiError):
            Http('https://test', 'Test', opener=opener).request('POST', '/x', body={})
        self.assertEqual(opener.call_count, 1)

    def test_error_does_not_expose_token(self):
        opener = Mock(side_effect=HTTPError('https://x?token=secret', 401, 'secret', {}, None))
        with self.assertRaises(ApiError) as caught:
            Http('https://test', 'Test', opener=opener).request('GET', '/x', params={'token': 'secret'})
        self.assertNotIn('secret', str(caught.exception))

    def test_torbox_resolve_queries_correct_ids(self):
        http = Mock()
        http.request.return_value = {'success': True, 'data': 'https://cdn.test/video.mkv'}
        client = TorBox('private', http=http)
        self.assertTrue(client.resolve({'kind': 'webdl', 'transfer_id': 1, 'file_id': 2}).startswith('https://'))
        self.assertEqual(http.request.call_args.kwargs['params']['web_id'], 1)
        self.assertEqual(http.request.call_args.kwargs['params']['redirect'], 'false')

    def test_torbox_insecure_resolve_rejected(self):
        http = Mock()
        http.request.return_value = {'success': True, 'data': 'http://cdn.test/video'}
        with self.assertRaises(ApiError):
            TorBox('key', http=http).resolve({'kind': 'torrents', 'transfer_id': 1, 'file_id': 2})

    def test_add_magnet_uses_multipart(self):
        http = Mock()
        http.request.return_value = {'success': True, 'data': {}}
        TorBox('key', http=http).add('magnet:?xt=urn:btih:abc')
        self.assertIn('magnet', http.request.call_args.kwargs['form'])

    def test_invalid_links_rejected(self):
        with self.assertRaises(ValueError):
            TorBox('key', http=Mock()).add('file:///etc/passwd')


class TraktTests(StoreCase):
    def test_only_identified_media_is_queued(self):
        queue_progress(self.db, episode(), 10, 1000, False)
        self.assertEqual(self.db.pending(), [])

    def test_completion_survives_partial_rewatch(self):
        media = dict(episode(), trakt={'ids': {'trakt': 1}})
        queue_progress(self.db, media, 1000, 1000, True)
        queue_progress(self.db, media, 100, 1000, False)
        self.assertEqual(len(self.db.pending()), 2)

    def test_successful_sync_removes_only_sent_event(self):
        media = dict(episode(), trakt={'ids': {'trakt': 1}})
        queue_progress(self.db, media, 1000, 1000, True)
        self.db.put('trakt_tokens', {'access_token': 'token', 'created_at': time.time(), 'expires_in': 10000})
        client = Trakt(self.db, 'id', http=Mock())
        client.flush()
        self.assertEqual(self.db.pending(), [])
        self.assertEqual(client.http.request.call_args_list[0].args[1], '/sync/history')

    def test_completed_playback_clears_remote_resume(self):
        media = dict(episode(), trakt={'ids': {'trakt': 1}})
        queue_progress(self.db, media, 1000, 1000, True)
        self.db.put('trakt_tokens', {'access_token': 'token', 'created_at': time.time(), 'expires_in': 10000})
        client = Trakt(self.db, 'id', http=Mock())
        client.http.request.side_effect = [{}, [{'id': 42, 'episode': {'ids': {'trakt': 1}}}], {}]
        client.flush()
        self.assertEqual(client.http.request.call_args.args[:2], ('DELETE', '/sync/playback/42'))
        self.assertEqual(self.db.pending(), [])

    def test_resume_cleanup_retry_does_not_repeat_history_write(self):
        media = dict(episode(), trakt={'ids': {'trakt': 1}})
        queue_progress(self.db, media, 1000, 1000, True)
        self.db.put('trakt_tokens', {'access_token': 'token', 'created_at': time.time(), 'expires_in': 10000})
        client = Trakt(self.db, 'id', http=Mock())
        client.http.request.side_effect = [{}, ApiError('Trakt', 503)]
        with self.assertRaises(ApiError):
            client.flush()
        self.assertTrue(json.loads(self.db.pending()[0]['value'])['history_sent'])
        client.http.request.reset_mock()
        client.http.request.side_effect = None
        client.http.request.return_value = []
        client.flush()
        self.assertEqual(client.http.request.call_count, 1)
        self.assertEqual(client.http.request.call_args.args[0], 'GET')

    def test_failed_sync_keeps_outbox(self):
        media = dict(episode(), trakt={'ids': {'trakt': 1}})
        queue_progress(self.db, media, 100, 1000, False)
        self.db.put('trakt_tokens', {'access_token': 'token', 'created_at': time.time(), 'expires_in': 10000})
        client = Trakt(self.db, 'id', http=Mock())
        client.http.request.side_effect = ApiError('Trakt', 503)
        with self.assertRaises(ApiError):
            client.flush()
        self.assertEqual(len(self.db.pending()), 1)

    def test_rotating_refresh_token_replaced(self):
        self.db.put('trakt_tokens', {'access_token': 'old', 'refresh_token': 'old-refresh', 'created_at': 0, 'expires_in': 1})
        auth = Mock()
        auth.request.return_value = {'access_token': 'new', 'refresh_token': 'new-refresh', 'created_at': time.time(), 'expires_in': 6000}
        client = Trakt(self.db, 'id', auth=auth)
        self.assertEqual(client._token(), 'new')
        self.assertEqual(self.db.get('trakt_tokens')['refresh_token'], 'new-refresh')

    def test_device_auth_no_bundled_secret(self):
        auth = Mock()
        auth.request.return_value = {'access_token': 'new'}
        Trakt(self.db, 'id', auth=auth).device_token('code')
        self.assertEqual(auth.request.call_args.kwargs['body'], {'client_id': 'id', 'code': 'code'})

    def test_null_next_episode_is_handled(self):
        self.db.put('trakt_lists', {'continue': [], 'shows': [{'show': {'title': 'Show', 'year': 2020, 'ids': {'trakt': 1}}}]})
        self.db.put('trakt_tokens', {'access_token': 'token', 'created_at': time.time(), 'expires_in': 10000})
        http = Mock()
        http.request.return_value = {'next_episode': None}
        snapshot = Trakt(self.db, 'id', http=http).snapshot()
        self.assertEqual(snapshot['next'], [])
        self.assertEqual(len(snapshot['shows']), 1)


class EmbyTests(StoreCase):
    def client(self):
        return Emby('http://192.168.1.10:8096', 'key', 'user123', http=Mock())

    def test_static_original_file_stream(self):
        url = self.client().resolve({'item_id': '1', 'media_source_id': '2'})
        query = parse_qs(urlsplit(url).query)
        self.assertEqual(query['Static'], ['true'])
        self.assertEqual(query['MediaSourceId'], ['2'])
        self.assertIn('PlaySessionId', query)

    def test_emby_user_changes_identity(self):
        a = self.client()
        b = Emby('http://192.168.1.10:8096', 'key', 'other', http=Mock())
        self.assertNotEqual(a.server_id, b.server_id)

    def test_emby_resume_joins_home(self):
        item = self.client().media({'Id': '1', 'Name': 'Episode 1', 'SeriesName': 'Show', 'Type': 'Episode',
            'SeriesId': 's1', 'ParentIndexNumber': 1, 'IndexNumber': 1, 'RunTimeTicks': 10000000000,
            'UserData': {'PlaybackPositionTicks': 5000000000, 'LastPlayedDate': '2026-11-17T10:00:00Z'}})
        self.db.put('library_emby', [item])
        self.assertEqual(home_rows(self.db)['continue'][0]['position'], 500)

    def test_emby_outbox_does_not_go_to_trakt(self):
        media = dict(episode(), emby={'id': '1', 'server_id': self.client().server_id})
        queue_emby(self.db, media, 10, False)
        http = Mock()
        Trakt(self.db, 'id', http=http).flush()
        http.request.assert_not_called()
        self.client().flush(self.db)
        self.assertEqual(self.db.pending(), [])

    def test_emby_url_credentials_rejected(self):
        with self.assertRaises(ValueError):
            Emby('http://user:password@server', 'token', 'id')


class PackageTests(unittest.TestCase):
    def test_manifests_parse_and_assets_exist(self):
        addon = ROOT / 'plugin.video.luma'
        manifest = ET.parse(addon / 'addon.xml')
        self.assertEqual(manifest.getroot().attrib['id'], addon.name)
        for element in manifest.findall('.//assets/*'):
            self.assertTrue((addon / element.text).is_file())
        ET.parse(addon / 'resources/settings.xml')

    def test_home_navigation_targets_exist(self):
        root = ET.parse(ROOT / 'plugin.video.luma/resources/skins/Default/1080i/Home.xml')
        ids = {e.attrib['id'] for e in root.findall('.//control[@id]')}
        for tag in ('onup', 'ondown', 'onleft', 'onright'):
            for e in root.findall('.//' + tag):
                self.assertIn(e.text, ids)


if __name__ == '__main__':
    unittest.main()
