"""Torrent/file validation contracts. No real CDN or account requests."""
import importlib
import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin.video.luma'))
from resources.lib import episodes, resolution
from resources.lib.library import library, refresh_library
from resources.lib.media import file_traits, flatten, parse_name, traits
from resources.lib.net import ApiError
from resources.lib.providers import normalize
from resources.lib.store import Store
from resources.lib.torbox import TorBox

HASH = '0123456789abcdef0123456789abcdef01234567'


def episode(season=2, number=3):
    return dict(parse_name('Example.Show.S{:02d}E{:02d}.mkv'.format(season, number)),
                premiered='2024-11-18', trakt={'ids': {'trakt': 33}, 'show_ids': {'imdb': 'tt1234567'}})


def transfer(*names, title='Example.Show.S02.Complete.2160p.HDR10+.EAC3'):
    return {'id': 8, 'hash': HASH, 'name': title, 'download_finished': True, 'download_present': True,
            'files': [{'id': i + 1, 'name': n, 'short_name': n.replace('\\', '/').rsplit('/', 1)[-1], 'size': 1e9} for i, n in enumerate(names)]}


class EpisodeMatchingTests(unittest.TestCase):
    def test_exact_common_forms_and_season_scoped_numbers(self):
        paths = ['Example.S02E03.mkv', 'Example.2x03.mkv', 'Example.S02.EP03.mkv',
                 'Example.Season.2.Episode.3.mkv', 'Season 2/E03.mkv', 'Season 02/EP.03 - Title.mkv',
                 'Season 2/03 - Title.mkv', 'Season%202/Episode%2003.mkv']
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(episodes.matches(path, episode(), 'Example.Show.S02.Complete'))
                self.assertEqual((parse_name(path, 'Example.Show.S02.Complete')['season'], parse_name(path, 'Example.Show.S02.Complete')['episode']), (2, 3))

    def test_wrong_and_combined_episodes_never_auto_match(self):
        paths = ['Example.S02E030.mkv', 'Example.S03E03.mkv', 'Example.S02E04.mkv',
                 'Example.S02E03E04.mkv', 'Example.S02E03-E04.mkv', 'Example.2x03-04.mkv',
                 'Season 2/E03 & 04.mkv', 'Season 1/E03.mkv', 'Season 2/30.mkv']
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse(episodes.matches(path, episode(), 'Example.Show.Complete.Series'))

    def test_episode_only_requires_single_season_context(self):
        self.assertFalse(episodes.matches('E03.mkv', episode(), 'Example.Complete.Series'))
        self.assertFalse(episodes.matches('03.mkv', episode(), 'Example.S01-S03'))
        self.assertTrue(episodes.manual_candidate('E03.mkv', episode(), 'Example.Complete.Series'))
        self.assertFalse(episodes.manual_candidate('E04.mkv', episode(), 'Example.Complete.Series'))

    def test_resolution_dimensions_are_not_episode_numbers(self):
        self.assertIsNone(episodes.inspect('Film.1920x1080.mkv')['season'])
        self.assertEqual(parse_name('Film.1920x1080.mkv')['type'], 'movie')
        self.assertTrue(episodes.matches('ExampleShowS02E03.mkv', episode()))

    def test_dates_use_basename_and_exact_airdate(self):
        self.assertTrue(episodes.matches('Example.2024.11.18.mkv', episode()))
        self.assertFalse(episodes.matches('2024.11.18/Example.2024.11.17.mkv', episode()))
        self.assertFalse(episodes.matches('2024.11.18/Unidentified.mkv', episode()))
        self.assertFalse(episodes.matches('Example.S03E03.2024.11.18.mkv', episode()))
        self.assertFalse(episodes.matches('Example.2024.11.18.mkv', dict(episode(), premiered='2024-02-30')))

    def test_multiseason_packs_keep_the_requested_season(self):
        self.assertEqual(episodes.seasons('Example.S01-S03.2160p'), {1, 2, 3})
        self.assertTrue(episodes.matches('Season 2/E03.mkv', episode(), 'Example.S01-S03'))
        raw = {'source': 'torrent', 'hash': HASH, 'name': 'Example.S01-S03.Complete.2160p', 'package': 'show', 'size': 20}
        self.assertIsNotNone(normalize(raw, 'test', episode()))
        self.assertIsNone(normalize(raw, 'test', episode(4, 3)))

    def test_declared_pack_ranges_are_candidates_but_combined_files_are_not(self):
        raw = {'source': 'torrent', 'hash': HASH, 'name': 'Example.S02E01-E10.2160p', 'package': 'season'}
        self.assertIsNotNone(normalize(raw, 'test', episode()))
        self.assertIsNone(normalize(dict(raw, package=None), 'test', episode()))
        self.assertEqual(resolution.candidates(transfer('Example.S02E03E04.mkv'), episode()), [])

    def test_extras_do_not_hide_actual_show_titles(self):
        self.assertTrue(episodes.is_extra('Show/Extras/Show.S02E03.mkv', 'Show'))
        self.assertTrue(episodes.is_extra('Show.S02E03.Sample.mkv', 'Show'))
        self.assertFalse(episodes.is_extra('Extras/Season 2/Extras.S02E03.mkv', 'Extras'))
        self.assertFalse(episodes.is_extra('Trailer.Park.Boys.S02E03.mkv', 'Trailer Park Boys'))

    def test_full_paths_survive_short_names_and_parent_quality_is_only_fallback(self):
        items = flatten([transfer('Season 1/E03.mkv', 'Season 2/E03.mkv', 'Season 2/Extras/E03.mkv',
                                  'Season 2/Example.S02E03.1080p.SDR.AAC.mkv')], 'torrents')
        self.assertEqual(len(items), 2)  # the season-1 file conflicts with the season-2 transfer
        self.assertEqual(items[0]['type'], 'episode')
        self.assertEqual(items[0]['sources'][0]['path'], 'Season 2/E03.mkv')
        self.assertEqual(items[0]['sources'][0]['traits']['resolution'], 2160)
        hint = items[1]['sources'][0]['traits']
        self.assertEqual((hint['resolution'], hint['hdr'], hint['audio']), (1080, 'SDR / unknown', 'AAC'))

    def test_disc_segments_are_excluded_without_excluding_standalone_m2ts(self):
        pack = transfer('BDMV/STREAM/00003.m2ts', 'Example.S02E03.m2ts')
        items = flatten([pack], 'torrents')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['sources'][0]['name'], 'Example.S02E03.m2ts')


class SourceValidationTests(unittest.TestCase):
    def test_cache_recheck_prevents_creation_on_a_stale_hit(self):
        api = Mock()
        api.cached.return_value = {}
        with self.assertRaises(resolution.SourceUnavailable):
            resolution.prepare(api, {'hash': HASH, 'magnet': 'magnet:?xt=urn:btih:' + HASH})
        api.add.assert_not_called()

    def test_cancel_after_cache_check_prevents_creation(self):
        api = Mock()
        api.cached.return_value = {HASH: {}}
        with self.assertRaises(resolution.SelectionCancelled):
            resolution.prepare(api, {'hash': HASH}, stopped=Mock(side_effect=[False, True]))
        api.add.assert_not_called()

    def test_transfer_hash_must_match_and_only_ready_flags_allow_play(self):
        api = Mock()
        api.cached.return_value = {HASH: {}}
        api.add.return_value = {'torrent_id': 8}
        api.torrent.return_value = dict(transfer('Example.S02E03.mkv'), hash='a' * 40)
        with self.assertRaises(resolution.SourceUnavailable):
            resolution.prepare(api, {'hash': HASH, 'magnet': 'magnet:?xt=urn:btih:' + HASH})
        api.torrent.return_value = dict(transfer('Example.S02E03.mkv'), download_present=False, download_state='cached')
        with self.assertRaises(resolution.SourceUnavailable):
            resolution.prepare(api, {'hash': HASH, 'magnet': 'magnet:?xt=urn:btih:' + HASH}, clock=Mock(side_effect=[0, 26]))

    def test_case_and_hash_conflicts_in_cache_responses(self):
        http = Mock()
        http.request.return_value = {'success': True, 'data': {HASH.upper(): {'hash': HASH, 'size': 5}, 'a' * 40: {'hash': 'b' * 40, 'size': 5}}}
        self.assertEqual(set(TorBox('key', http).cached([HASH.upper(), HASH, 'a' * 40])), {HASH})
        self.assertEqual(http.request.call_args.kwargs['params']['hash'], [HASH, 'a' * 40])

    def test_account_limit_codes_stop_failover_without_reflecting_response_details(self):
        http = Mock()
        http.request.return_value = {'success': False, 'error': 'ACTIVE_LIMIT', 'detail': 'private account detail'}
        with self.assertRaises(ApiError) as caught:
            TorBox('key', http).cached([HASH])
        self.assertTrue(resolution.account_failure(caught.exception))
        self.assertNotIn('private', str(caught.exception))

    def test_stale_file_must_still_match_before_requesting_a_link(self):
        api = Mock()
        source = flatten([transfer('Example.S02E03.mkv')], 'torrents')[0]['sources'][0]
        api.torrent.return_value = transfer('Example.S02E04.mkv')
        with self.assertRaises(resolution.SourceUnavailable):
            resolution.resolve_selected(api, source, episode(), check_link=False)
        api.resolve.assert_not_called()

    def test_expired_selected_url_is_refreshed_once(self):
        api = Mock()
        source = dict(flatten([transfer('Example.S02E03.mkv')], 'torrents')[0]['sources'][0], verified_at=time.time())
        api.resolve.side_effect = ['https://cdn.test/old', 'https://cdn.test/new']
        probe = Mock(side_effect=[resolution.LinkUnavailable(403), None])
        self.assertEqual(resolution.resolve_selected(api, source, episode(), probe=probe), 'https://cdn.test/new')
        self.assertEqual(probe.call_count, 2)
        api.torrent.assert_not_called()

    def test_probe_reads_only_one_byte_and_has_no_api_credentials(self):
        response = Mock(status=200)
        response.geturl.return_value = 'https://cdn.test/file'
        response.headers = {'Content-Type': 'application/octet-stream', 'Content-Length': str(80 * 1024 ** 3)}
        response.read.return_value = b'x'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        opener = Mock(return_value=response)
        resolution.probe_link('https://cdn.test/signed', opener)
        response.read.assert_called_once_with(1)
        request = opener.call_args.args[0]
        self.assertEqual(request.get_header('Range'), 'bytes=0-0')
        self.assertIsNone(request.get_header('Authorization'))
        self.assertEqual(opener.call_args.kwargs['timeout'], 5)
        response.__exit__.assert_called_once()

    def test_probe_rejects_html_and_downgrades_and_redacts_http_errors(self):
        response = Mock(status=200)
        response.geturl.return_value = 'https://cdn.test/error'
        response.headers = {'Content-Type': 'text/html'}
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        with self.assertRaises(resolution.LinkUnavailable):
            resolution.probe_link('https://cdn.test/error', Mock(return_value=response))
        response.read.assert_not_called()
        opener = Mock(side_effect=HTTPError('https://cdn.test/private-signature', 403, 'Forbidden', {}, io.BytesIO(b'private')))
        with self.assertRaises(resolution.LinkUnavailable) as caught:
            resolution.probe_link('https://cdn.test/error', opener)
        self.assertEqual(caught.exception.status, 403)
        self.assertNotIn('private', str(caught.exception))
        with self.assertRaises(resolution.LinkUnavailable):
            resolution.SecureRedirects().redirect_request(Mock(), Mock(), 302, '', {}, 'http://cdn.test/insecure')


class PackIdentityTests(unittest.TestCase):
    def test_manual_file_binding_survives_refresh_without_renaming_other_packs(self):
        import test_kodi_handoff
        search = importlib.import_module('resources.lib.search')
        with tempfile.TemporaryDirectory() as folder:
            db = Store(str(Path(folder) / 'test.db'))
            first = transfer('Unidentified.mkv', title='Example.Show.Complete.Series')
            other = dict(transfer('Unidentified.mkv', title='Other.Show.Complete.Series'), id=9)
            selected = search.remember(db, first, flatten([first], 'torrents')[0], episode(), manual=True)
            db.save_progress(selected, 90, 1000)
            client = Mock()
            client.library.side_effect = [[first, other], []]
            refresh_library(db, client)
            items = library(db)
            matched = next(i for i in items if i['key'] == selected['key'])
            self.assertEqual((matched['type'], matched['season'], matched['episode']), ('episode', 2, 3))
            self.assertEqual(matched['sources'][0]['manual_episode'], [2, 3])
            self.assertEqual(next(i for i in items if i['sources'][0]['transfer_id'] == 9)['type'], 'movie')
            self.assertEqual(db.history()[0]['key'], selected['key'])
            api = Mock()
            api.torrent.return_value = first
            api.resolve.return_value = 'https://cdn.test/file'
            self.assertEqual(resolution.resolve_selected(api, matched['sources'][0], episode(), check_link=False), 'https://cdn.test/file')

    def test_dated_file_is_bound_to_selected_episode_ids(self):
        import test_kodi_handoff
        search = importlib.import_module('resources.lib.search')
        with tempfile.TemporaryDirectory() as folder:
            db = Store(str(Path(folder) / 'test.db'))
            pack = transfer('Example.2024.11.18.mkv', title='Example.Show.Complete.Series')
            matching = resolution.candidates(pack, episode())
            self.assertEqual(len(matching), 1)
            selected = search.remember(db, pack, matching[0], episode())
            item = library(db)[0]
            self.assertEqual(item['key'], selected['key'])
            self.assertEqual(item['trakt']['ids'], {'trakt': 33})
            self.assertEqual(item['type'], 'episode')


if __name__ == '__main__':
    unittest.main()
