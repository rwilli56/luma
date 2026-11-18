"""Provider/API contracts and discovery-to-library identity tests; no live scrapes."""
import base64
import importlib
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin.video.luma'))
from resources.lib import providers
from resources.lib.catalog import Catalog
from resources.lib.library import library, refresh_library
from resources.lib.media import parse_name
from resources.lib.net import ApiError
from resources.lib.store import Store
from resources.lib.torbox import TorBox

HASH = '0123456789abcdef0123456789abcdef01234567'


def movie():
    return {'title': 'Example Film', 'year': 2024, 'type': 'movie', 'trakt': {'ids': {'imdb': 'tt1234567'}}}


def result(name='Example.Film.2024.2160p.HDR10+.EAC3', hash_value=HASH):
    return {'source': 'torrent', 'name': name, 'hash': hash_value,
            'url': 'magnet:?xt=urn:btih:' + hash_value, 'size': '12.5'}


class ProviderTests(unittest.TestCase):
    def test_hash_formats_and_malformed_links(self):
        encoded = base64.b32encode(bytes.fromhex(HASH)).decode()
        self.assertEqual(providers.infohash('magnet:?xt=urn:btih:' + encoded), HASH)
        self.assertEqual(providers.infohash(HASH.upper()), HASH)
        for invalid in ('file:///tmp/a', 'https://host/' + HASH, 'magnet:?xt=urn:btmh:' + HASH, 'a' * 39):
            self.assertIsNone(providers.infohash(invalid))

    def test_only_valid_torrents_pass_and_tracker_urls_are_discarded(self):
        source = result()
        source['url'] += '&tr=https://private.test/token'
        normalized = providers.normalize(source, 'Coco / example', movie())
        self.assertEqual(normalized['magnet'], 'magnet:?xt=urn:btih:' + HASH)
        self.assertEqual(normalized['size'], 12.5 * 1024 ** 3)
        self.assertEqual(normalized['traits']['hdr'], 'HDR10+')
        for changes in ({'source': 'hoster'}, {'hash': 'bad', 'url': 'https://a.test'}, {'url': 'magnet:?xt=urn:btih:' + 'a' * 40}):
            self.assertIsNone(providers.normalize(dict(source, **changes), 'test', movie()))

    def test_conflicting_years_and_movie_episodes_rejected(self):
        for name in ('Example.Film.1999.2160p', 'Example.Film.S01E01.2160p'):
            self.assertIsNone(providers.normalize(result(name), 'test', movie()))

    def test_episode_and_pack_validation(self):
        media = dict(movie(), type='episode', season=2, episode=3)
        for name in ('Example.S02E03.2160p', 'Example.Season.2.2160p', 'Example.S02.2160p'):
            self.assertIsNotNone(providers.normalize(result(name), 'test', media), name)
        for name in ('Example.S02E04.2160p', 'Example.S01.2160p', 'Example.S02E03E04.2160p'):
            self.assertIsNone(providers.normalize(result(name), 'test', media), name)

    def test_episode_query_uses_show_imdb_and_episode_title(self):
        media = dict(movie(), type='episode', season=2, episode=3, episode_title='Pilot',
                     premiered='2024-01-01', trakt={'ids': {'imdb': 'tt9999999'}, 'show_ids': {'imdb': 'tt1234567'}})
        data = providers.query_data(media, 12)
        self.assertEqual((data['title'], data['tvshowtitle'], data['imdb']), ('Pilot', 'Example Film', 'tt1234567'))
        self.assertEqual((data['season'], data['episode'], data['premiered']), ('2', '3', '2024-01-01'))
        self.assertNotIn('torbox_key', data)

    def test_loader_respects_upstream_switches_and_isolates_failure(self):
        module = Mock()
        module.sources.return_value = [('example', Mock(pack_capable=False))]
        with patch.object(providers.importlib, 'import_module', side_effect=[ImportError(), module]):
            tasks, failures = providers.load([dict(label='Coco', module='cocoscrapers', path='/addons/coco'),
                                               dict(label='POV', module='pov', path='/addons/pov')])
        self.assertEqual(failures, ['Coco'])
        self.assertEqual(tasks[0][0], 'POV / example')
        module.sources.assert_called_once_with()

    def test_workers_use_current_contract_and_isolate_bad_provider(self):
        seen = []

        class Good:
            def sources(self, data, host_dict):
                seen.append((data, host_dict))
                return [result()]

        class Bad:
            def sources(self, data, host_dict):
                raise RuntimeError('a raw secret URL must never escape')

        session = providers.ScrapeSession([('good', Good), ('bad', Bad)], movie())
        for thread in session.threads:
            thread.join(1)
        self.assertFalse(session.finished)  # queued final results must still be drained
        items = session.poll()
        self.assertEqual(len(items), 1)
        self.assertEqual((session.completed, session.failed), (2, 1))
        self.assertTrue(session.finished)
        self.assertEqual(seen[0][1], {})

    def test_cancel_stops_dispatch_and_pool_is_bounded(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        class Slow:
            def sources(self, data, host_dict):
                calls.append(1)
                entered.set()
                release.wait(1)
                return []

        session = providers.ScrapeSession([('slow', Slow)] * 15, movie(), workers=2)
        self.assertTrue(entered.wait(1))
        session.stop.set()
        release.set()
        for thread in session.threads:
            thread.join(1)
        self.assertLessEqual(len(calls), 2)
        session.poll()
        self.assertTrue(session.finished)


class SearchStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'search.db'))

    def tearDown(self):
        self.temp.cleanup()

    def test_cinemeta_search_encodes_query_and_maps_imdb(self):
        http = Mock()
        http.request.return_value = {'metas': [{'id': 'tt1234567', 'name': 'Example', 'releaseInfo': '2024–2025'},
                                                {'id': 'invalid', 'name': 'Unknown'}]}
        rows = Catalog(self.db, http=http).search('a/b & c', 'movie')
        self.assertEqual(rows[0]['ids'], {'imdb': 'tt1234567'})
        self.assertEqual(rows[0]['year'], 2024)
        self.assertEqual(len(rows), 1)
        self.assertIn('search=a%2Fb%20%26%20c.json', http.request.call_args.args[1])

    def test_cinemeta_episodes_exclude_future_and_do_not_invent_episode_ids(self):
        http = Mock()
        http.request.return_value = {'meta': {'videos': [
            {'season': 1, 'episode': 1, 'name': 'Pilot', 'released': '2024-01-01T00:00:00.000Z', 'id': 'tt1234567:1:1'},
            {'season': 1, 'episode': 2, 'released': '2099-01-01T00:00:00.000Z'}]}}
        catalog = Catalog(self.db, http=http)
        show = dict(title='Example', year=2024, ids={'imdb': 'tt1234567'}, catalog='cinemeta')
        episodes = catalog.episodes(show)
        media = catalog.media(show, episodes[0])
        self.assertEqual(len(episodes), 1)
        self.assertEqual(media['trakt']['ids'], {})
        self.assertEqual(media['trakt']['show_ids'], {'imdb': 'tt1234567'})
        self.assertEqual(media['premiered'], '2024-01-01')
        catalog.episodes(show)
        self.assertEqual(http.request.call_count, 1)

    def test_trakt_catalog_supplies_exact_episode_ids(self):
        trakt = Mock(client_id='client')
        trakt.search.return_value = [{'show': {'title': 'Example', 'year': 2024, 'ids': {'trakt': 1, 'imdb': 'tt1234567'}}}]
        catalog = Catalog(self.db, trakt)
        show = catalog.search('Example', 'show')[0]
        episode = {'season': 1, 'number': 2, 'title': 'Part 2', 'ids': {'trakt': 2}, 'first_aired': '2024-01-01T00:00:00Z'}
        media = catalog.media(show, episode)
        self.assertEqual(media['trakt']['ids'], {'trakt': 2})
        self.assertEqual(media['trakt']['show_ids']['imdb'], 'tt1234567')

    def test_selected_pack_file_keeps_metadata_and_resume_after_refresh(self):
        # Reuse the native Kodi doubles installed by the handoff tests.
        import test_kodi_handoff
        search = importlib.import_module('resources.lib.search')
        transfer = {'id': 8, 'download_finished': True, 'download_present': True, 'files': [
            {'id': 10, 'name': 'Example.S01E01.mkv'}, {'id': 11, 'name': 'Example.S01E02.mkv'},
            {'id': 12, 'name': 'sample.mkv'}]}
        from resources.lib.media import flatten
        items = flatten([transfer], 'torrents')
        media = dict(movie(), title='Correct Show', type='episode', season=1, episode=2,
                     trakt={'ids': {'trakt': 22}, 'show_ids': {'trakt': 5}})
        matching = search.episode_files(items, media)
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]['sources'][0]['file_id'], 11)
        selected = search.remember(self.db, transfer, matching[0], media)
        self.db.save_progress(selected, 120, 900)
        client = Mock()
        client.library.side_effect = [[transfer], []]
        refresh_library(self.db, client)
        refreshed = next(i for i in library(self.db) if i['key'] == selected['key'])
        self.assertEqual(refreshed['title'], 'Correct Show')
        self.assertEqual(refreshed['trakt']['ids']['trakt'], 22)
        first = next(i for i in library(self.db) if i['episode'] == 1)
        self.assertEqual(first['title'], 'Correct Show')
        self.assertEqual(first['trakt']['show_ids'], {'trakt': 5})
        self.assertEqual(self.db.history()[0]['key'], selected['key'])
        self.assertNotIn('magnet:', str(self.db.history()))

    def test_show_mapping_with_only_imdb_is_safe(self):
        import test_kodi_handoff
        search = importlib.import_module('resources.lib.search')
        from resources.lib.media import flatten
        transfer = {'id': 8, 'download_finished': True, 'download_present': True,
                    'files': [{'id': 10, 'name': 'Example.S01E01.mkv'}]}
        media = dict(movie(), type='episode', season=1, episode=1, trakt={'ids': {}, 'show_ids': {'imdb': 'tt1234567'}})
        selected = search.remember(self.db, transfer, flatten([transfer], 'torrents')[0], media)
        self.assertEqual(library(self.db)[0]['key'], selected['key'])
        self.assertEqual(library(self.db)[0]['trakt']['show_ids'], {'imdb': 'tt1234567'})


class TorBoxSearchTests(unittest.TestCase):
    def test_cache_shapes_exclude_misses_and_batch_at_100(self):
        hashes = ['{:040x}'.format(i) for i in range(205)]
        http = Mock()
        http.request.side_effect = [
            {'success': True, 'data': {hashes[0]: {'name': 'test', 'size': 20}, hashes[1]: {}, hashes[2]: {'cached': False}}},
            {'success': True, 'data': [{'hash': hashes[101], 'size': 5}]}, {'success': True, 'data': {}}]
        hits = TorBox('secret', http).cached(hashes)
        self.assertEqual(set(hits), {hashes[0], hashes[101]})
        self.assertEqual([len(c.kwargs['params']['hash']) for c in http.request.call_args_list], [100, 100, 5])

    def test_cache_failure_does_not_become_a_hit(self):
        http = Mock()
        http.request.return_value = {'success': False, 'data': {HASH: {'size': 5}}}
        with self.assertRaises(ApiError):
            TorBox('secret', http).cached([HASH])

    def test_cached_only_creation_and_exact_transfer_lookup(self):
        http = Mock()
        http.request.side_effect = [{'success': True, 'data': {'torrent_id': 9}},
                                     {'success': True, 'data': [{'id': 1}, {'id': 9}]}]
        torbox = TorBox('secret', http)
        created = torbox.add('magnet:?xt=urn:btih:' + HASH, cached_only=True)
        self.assertEqual(created['torrent_id'], 9)
        self.assertEqual(http.request.call_args.kwargs['form']['add_only_if_cached'], 'true')
        self.assertEqual(torbox.torrent(9), {'id': 9})
        self.assertEqual(http.request.call_args.kwargs['params'], {'id': 9, 'bypass_cache': 'true'})


class SearchPlaybackTests(unittest.TestCase):
    def setUp(self):
        import test_kodi_handoff
        self.kodi = test_kodi_handoff
        self.search = importlib.import_module('resources.lib.search')
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'play.db'))
        self.progress = Mock()
        self.progress.iscanceled.return_value = False
        self.monitor = Mock()
        self.monitor.abortRequested.return_value = False
        self.monitor.waitForAbort.return_value = False
        self.dialog = Mock()
        self.dialog.select.return_value = 0
        self.client = Mock()
        self.client.cached.return_value = {HASH: {'size': 12e9}}
        self.client.add.return_value = {'torrent_id': 8}
        self.client.torrent.return_value = {'id': 8, 'download_finished': True, 'download_present': True,
                                          'files': [{'id': 4, 'name': result()['name'] + '.mkv', 'size': 12e9}]}
        self.queries = []
        queries = self.queries

        class Source:
            def sources(self, data, host_dict):
                queries.append(data)
                return [result()]

        self.source = Source

    def tearDown(self):
        self.temp.cleanup()

    def discover(self):
        search = self.search
        settings = lambda k: 'secret' if k == 'torbox_key' else 'true' if k.startswith('provider_') else 'false'
        with patch.object(search.config, 'store', return_value=self.db), patch.object(search.config, 'setting', side_effect=settings), \
             patch.object(search.xbmcgui, 'DialogProgress', return_value=self.progress, create=True), \
             patch.object(search.xbmcgui, 'Dialog', return_value=self.dialog), \
             patch.object(search.xbmc, 'Monitor', return_value=self.monitor), \
             patch.object(search.providers, 'installed', return_value=[dict(key='coco', available=True)]), \
             patch.object(search.providers, 'load', return_value=([('one', self.source), ('duplicate', self.source)], [])), \
             patch.object(search, 'TorBox', return_value=self.client):
            return search.find_sources(movie())

    def test_duplicate_search_to_native_player_without_stored_cdn_urls(self):
        selected = self.discover()
        self.assertEqual(self.client.cached.call_count, 2)
        self.assertTrue(all(c.args == ([HASH],) for c in self.client.cached.call_args_list))
        self.client.add.assert_called_once_with('magnet:?xt=urn:btih:' + HASH, cached_only=True)
        self.assertNotIn('secret', str(self.queries))
        app = self.kodi.app
        with patch.object(app.config, 'store', return_value=self.db), patch.object(app.config, 'setting', return_value='secret'), \
             patch.object(app, 'resolve_selected', side_effect=lambda api, source, media, check_link=True: api.resolve(source)), patch.object(app, 'TorBox') as client:
            client.return_value.resolve.return_value = 'https://cdn.test/fresh-signed-url'
            app.play(10, selected['key'])
        self.assertTrue(self.kodi.plugin.setResolvedUrl.call_args.args[1])
        item = self.kodi.plugin.setResolvedUrl.call_args.args[2]
        self.assertEqual(item.path, 'https://cdn.test/fresh-signed-url')
        self.assertEqual(item.tag.ids['imdb'], 'tt1234567')
        self.assertNotIn('cdn.test', str(self.db.get('pending_playback')))

    def test_source_selection_cancel_does_not_add_torrent(self):
        self.dialog.select.return_value = -1
        self.assertIsNone(self.discover())
        self.client.add.assert_not_called()

    def test_no_cache_hits_does_not_add_torrent(self):
        self.client.cached.return_value = {}
        with self.assertRaisesRegex(ValueError, 'none are cached'):
            self.discover()
        self.client.add.assert_not_called()

    def test_progress_cancel_does_not_check_cache_or_add(self):
        self.progress.iscanceled.return_value = True
        self.assertIsNone(self.discover())
        self.client.cached.assert_not_called()
        self.client.add.assert_not_called()

    def test_provider_cache_reuses_metadata_but_rechecks_torbox(self):
        from resources.lib import preferences as prefs
        with patch.object(prefs, 'get', side_effect=lambda k: prefs.DEFAULTS[k]):
            self.discover()
            self.assertEqual(len(self.queries), 2)
            self.discover()
        self.assertEqual(len(self.queries), 2)
        self.assertEqual(self.client.cached.call_count, 4)

    def test_automatic_source_selection_avoids_source_dialog(self):
        from resources.lib import preferences as prefs
        with patch.object(prefs, 'get', side_effect=lambda k: 'auto' if k == 'movie_playstyle' else prefs.DEFAULTS[k]):
            self.assertIsNotNone(self.discover())
        self.dialog.select.assert_not_called()

    def test_irregular_pack_file_requires_confirmation_before_binding(self):
        from resources.lib import preferences as prefs
        self.client.torrent.return_value = {'id': 8, 'download_finished': True, 'download_present': True,
            'name': 'Example.Show.Complete.Series', 'files': [{'id': 4, 'name': 'Unidentified.mkv', 'size': 1e9}]}
        self.client.cached.return_value = {HASH: {'size': 1e9}}
        # Exercise the same UI flow as discovery, with an episode rather than a movie.
        original = globals()['movie']
        media = dict(original(), type='episode', season=2, episode=3)
        self.dialog.yesno.return_value = False
        with patch.dict(globals(), movie=lambda: media), \
             patch.object(prefs, 'get', side_effect=lambda k: prefs.DEFAULTS[k]):
            self.assertIsNone(self.discover())
        self.assertEqual(self.db.mappings(), {})


if __name__ == '__main__':
    unittest.main()
