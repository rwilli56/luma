"""Navigation, settings and catalog contracts without live account requests."""
import importlib
import json
from pathlib import Path
import re
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin.video.luma'))
from resources.lib import menus, preferences as prefs, filtering
from resources.lib.catalog import Catalog, visible_episodes
from resources.lib.explore import Explorer, get_object, save_object
from resources.lib.media import parse_name, traits
from resources.lib.store import Store
from resources.lib.trakt import Trakt, queue_progress


def title(number=1):
    return {'title': 'Film {}'.format(number), 'year': 2024, 'ids': {'trakt': number, 'imdb': 'tt{:07d}'.format(number)}}


class MenuTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'test.db'))
        self.trakt = Mock(client_id='client', connected=True)
        self.explorer = Explorer(self.db, self.trakt)

    def tearDown(self):
        self.temp.cleanup()

    def test_seren_main_and_discovery_inventory(self):
        self.assertEqual([s[0] for s in menus.ROOT[:7]], ['Discover Movies', 'Discover TV Shows', 'My Movies', 'My Shows', 'My Files', 'Search', 'Tools'])
        for kind in ('movie', 'show'):
            options = dict(menus.discovery(kind))
            for label in ('Most Popular', 'Recommended For You', 'Trending', 'Most Played', 'Most Watched', 'Most Collected', 'Most Anticipated', 'Genres', 'Years', 'By Actor', 'Search'):
                self.assertIn(label, options)
        self.assertIn('Box Office Top 10', dict(menus.discovery('movie')))
        self.assertIn('New TV Shows', dict(menus.discovery('show')))
        self.assertIn('Networks', dict(menus.discovery('show')))
        self.assertEqual(len(menus.MY_MOVIES), 6)
        self.assertEqual(len(menus.MY_SHOWS), 11)

    def test_chart_shapes_cache_and_pagination(self):
        self.trakt.call.return_value = [{'movie': title(n), 'watchers': 100} for n in range(20)]
        rows, more = self.explorer.page('movie', 'trending')
        self.assertTrue(more)
        self.assertEqual(rows[0]['catalog_type'], 'movie')
        self.assertEqual(self.trakt.call.call_args.args[1], '/movies/trending')
        self.explorer.page('movie', 'trending')
        self.assertEqual(self.trakt.call.call_count, 1)
        self.explorer.page('movie', 'trending', 2)
        self.assertEqual(self.trakt.call.call_args.kwargs['params']['page'], 2)

    def test_recent_filter_and_weekly_chart_endpoints(self):
        self.trakt.call.return_value = []
        self.explorer.page('show', 'popular_recent')
        self.assertIn('years', self.trakt.call.call_args.kwargs['params'])
        self.explorer.page('movie', 'played')
        self.assertEqual(self.trakt.call.call_args.args[1], '/movies/played/weekly')

    def test_all_discovery_catalog_entries_have_endpoints(self):
        self.trakt.call.return_value = []
        special = {'genres', 'years', 'networks', 'actor', 'query'}
        for kind in ('movie', 'show'):
            for _, key in menus.discovery(kind):
                if key not in special:
                    with self.subTest(kind=kind, key=key):
                        self.explorer.page(kind, key)

    def test_personal_lists_require_login_even_if_cached(self):
        self.trakt.call.return_value = []
        self.explorer.page('movie', 'watchlist')
        self.trakt.connected = False
        with self.assertRaisesRegex(ValueError, 'Connect Trakt'):
            self.explorer.page('movie', 'watchlist')

    def test_watchlist_uses_server_pagination_and_collection_local_pagination(self):
        self.trakt.call.return_value = [{'movie': title(n)} for n in range(25)]
        rows, more = self.explorer.page('movie', 'collection')
        self.assertEqual(len(rows), 20)
        self.assertTrue(more)
        rows, more = self.explorer.page('movie', 'collection', 2)
        self.assertEqual(len(rows), 5)
        self.assertFalse(more)
        self.explorer.page('show', 'watchlist', 2)
        self.assertEqual(self.trakt.call.call_args.kwargs['params']['page'], 2)

    def test_private_own_list_uses_authenticated_owner_route(self):
        self.trakt.call.return_value = [{'name': 'Private', 'ids': {'trakt': 5}}]
        lists, _ = self.explorer.page('movie', 'own_lists')
        self.trakt.call.return_value = [{'movie': title()}]
        items, _ = self.explorer.page('movie', 'list_items', obj=lists[0])
        self.assertEqual(self.trakt.call.call_args.args[1], '/users/me/lists/5/items/movie')
        self.assertTrue(self.trakt.call.call_args.kwargs['authenticated'])
        self.assertEqual(items[0]['title'], 'Film 1')

    def test_public_lists_filter_type_and_use_singular_item_route(self):
        self.trakt.call.return_value = []
        self.explorer.page('show', 'lists_trending')
        self.assertEqual(self.trakt.call.call_args.args[1], '/lists/trending/show')
        self.explorer.page('show', 'list_items', obj={'ids': {'trakt': 2}})
        self.assertEqual(self.trakt.call.call_args.args[1], '/lists/2/items/show')

    def test_calendar_episode_retains_show_and_episode_ids(self):
        self.trakt.call.return_value = [{'show': title(), 'episode': {'title': 'Pilot', 'season': 1, 'number': 1, 'ids': {'trakt': 33}}}]
        rows, _ = self.explorer.page('show', 'upcoming')
        media = Catalog.media(rows[0]['show'], rows[0])
        self.assertEqual(media['trakt']['ids']['trakt'], 33)
        self.assertEqual(media['trakt']['show_ids']['trakt'], 1)

    def test_unfinished_collection_compares_individual_episodes(self):
        collection = [{'show': title(), 'seasons': [{'number': 1, 'episodes': [{'number': 1}, {'number': 2}]}]}]
        watched = [{'show': title(), 'seasons': [{'number': 1, 'episodes': [{'number': 1, 'plays': 1}]}]}]
        self.trakt.call.side_effect = [collection, watched]
        rows, _ = self.explorer.page('show', 'unfinished')
        self.assertEqual(len(rows), 1)

    def test_actor_credits_deduplicate_and_keep_media_type(self):
        self.trakt.call.return_value = {'cast': [{'movie': title()}, {'movie': title()}]}
        rows, _ = self.explorer.page('movie', 'actor_credits', value=42)
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.trakt.call.call_args.args[1], '/people/42/movies')

    def test_cinemeta_fallback_does_not_claim_other_charts_are_popular(self):
        self.trakt.client_id = ''
        http = Mock()
        http.request.return_value = {'metas': [{'id': 'tt1234567', 'name': 'Film', 'releaseInfo': '2024'}]}
        explorer = Explorer(self.db, self.trakt, Catalog(self.db, http=http))
        rows, _ = explorer.page('movie', 'popular')
        self.assertEqual(rows[0]['catalog'], 'cinemeta')
        with self.assertRaisesRegex(ValueError, 'Client ID'):
            explorer.page('movie', 'trending')

    def test_cinemeta_year_mismatches_are_filtered_without_changing_page_offsets(self):
        self.trakt.client_id = ''
        http = Mock()
        http.request.return_value = {'metas': [{'id': 'tt1234567', 'name': 'Wrong year', 'releaseInfo': '2025'},
                                              {'id': 'tt1234568', 'name': 'Correct year', 'releaseInfo': '2024'}] * 12}
        explorer = Explorer(self.db, self.trakt, Catalog(self.db, http=http))
        rows, more = explorer.page('movie', 'year', value='2024')
        self.assertEqual(len(rows), 10)
        self.assertTrue(more)
        self.assertTrue(all(r['year'] == 2024 for r in rows))
        explorer.page('movie', 'year', 2, value='2024')
        self.assertIn('skip=20', http.request.call_args.args[1])

    def test_conflicting_identified_titles_are_never_reused(self):
        from resources.lib.library import match_media
        local = dict(parse_name('Film.2024.mkv'), trakt={'ids': {'trakt': 1}})
        remote = dict(local, trakt={'ids': {'trakt': 2}})
        self.assertIsNone(match_media(remote, [local]))

    def test_cache_maintenance_preserves_progress_and_unsent_updates(self):
        media = parse_name('Film.2024.mkv')
        self.db.save_progress(media, 50, 100)
        self.db.enqueue('pending', {'ids': {'trakt': 1}})
        self.db.put('catalog:test', [1])
        self.db.put('source_cache:test', [2])
        self.db.clear_cache(('catalog:',))
        self.assertIsNone(self.db.get('catalog:test'))
        self.assertEqual(self.db.get('source_cache:test'), [2])
        self.assertEqual(len(self.db.history()), 1)
        self.assertEqual(len(self.db.pending()), 1)

    def test_foreground_token_refresh_is_deferred_to_service(self):
        self.db.put('trakt_tokens', {'access_token': 'private', 'refresh_token': 'private', 'created_at': 0, 'expires_in': 1})
        auth = Mock()
        trakt = Trakt(self.db, 'client', auth=auth, allow_refresh=False)
        with self.assertRaisesRegex(ValueError, 'refreshing'):
            trakt.call('GET', '/sync/watched/movies')
        auth.request.assert_not_called()
        self.assertTrue(self.db.get('request_sync'))

    def test_disabled_trakt_progress_does_not_enqueue_updates(self):
        media = dict(parse_name('Film.2024.mkv'), trakt={'ids': {'trakt': 1}})
        with patch.object(prefs, 'get', return_value=False):
            queue_progress(self.db, media, 50, 100, False)
        self.assertEqual(self.db.pending(), [])


class SettingsTests(unittest.TestCase):
    def test_generated_settings_cover_runtime_defaults_and_actions(self):
        root = ET.parse(ROOT / 'plugin.video.luma/resources/settings.xml')
        settings = {s.get('id'): s for s in root.findall('.//setting')}
        self.assertEqual(set(settings), {s[0] for _, _, rows in prefs.SCHEMA for s in rows})
        po = (ROOT / 'plugin.video.luma/resources/language/resource.language.en_gb/strings.po').read_text('utf8')
        ids = re.findall(r'msgctxt "#(\d+)"', po)
        self.assertEqual(len(ids), len(set(ids)))
        for node in root.findall('.//*[@label]') + root.findall('.//*[@help]'):
            for attr in ('label', 'help'):
                if node.get(attr):
                    self.assertIn(node.get(attr), ids)
        self.assertEqual(settings['startup'].findtext('default'), 'menu')
        for key in ('torbox_key', 'trakt_client_secret', 'emby_key'):
            self.assertEqual(settings[key].findtext('./control/hidden'), 'true')

    def test_integer_preferences_clamp_and_invalid_enums_use_defaults(self):
        from resources.lib import config
        with patch.object(config, 'setting', return_value='999'):
            self.assertEqual(prefs.get('scrape_workers'), 4)
            self.assertEqual(prefs.get('startup'), 'menu')
        with patch.object(config, 'setting', return_value='nonsense'):
            self.assertEqual(prefs.get('page_size'), 20)

    def test_unaired_visibility_can_be_changed_without_stale_cache(self):
        items = [{'first_aired': '2024-01-01T00:00:00Z'}, {'first_aired': '2099-01-01T00:00:00Z'}]
        with patch.object(prefs, 'get', return_value=True):
            self.assertEqual(len(visible_episodes(items)), 1)
        with patch.object(prefs, 'get', return_value=False):
            self.assertEqual(len(visible_episodes(items)), 2)

    def test_source_filters_keep_packs_until_individual_file_size_is_known(self):
        settings = dict(prefs.DEFAULTS, episode_size=2)
        source = dict(name='Show.S01.2160p.HDR10+', size=30e9, traits=traits('2160p HDR10+'))
        self.assertEqual(filtering.apply([source], 'episode', settings, torrent_results=True), [source])
        self.assertEqual(filtering.apply([source], 'episode', settings), [])

    def test_source_filters_and_compatibility_order(self):
        settings = dict(prefs.DEFAULTS, min_resolution='1080', exclude_dv=True, exclude_cam=True)
        names = ['Film.720p.AAC', 'Film.2160p.DV.AAC', 'Film.2160p.CAM.AAC', 'Film.2160p.HDR10+.EAC3', 'Film.2160p.HDR10.TrueHD']
        sources = [dict(name=n, traits=traits(n), size=10e9) for n in names]
        result = filtering.apply(sources, 'movie', settings)
        self.assertEqual([s['name'] for s in result], names[3:])


class KodiMenuTests(unittest.TestCase):
    def setUp(self):
        import test_kodi_handoff
        self.kodi = test_kodi_handoff
        self.directory = importlib.import_module('resources.lib.directory')
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'ui.db'))

    def tearDown(self):
        self.temp.cleanup()

    def render(self, params):
        mod = self.directory
        with patch.object(mod.config, 'store', return_value=self.db), patch.object(mod.config, 'setting', return_value=''), \
             patch.object(mod.xbmcplugin, 'setContent', create=True), \
             patch.object(mod.xbmcplugin, 'endOfDirectory', create=True), \
             patch.object(mod.xbmcplugin, 'addDirectoryItems', create=True) as items:
            mod.render(10, params)
            return items.call_args.args[1]

    def test_root_all_folders_and_dashboard_tool(self):
        rows = self.render({})
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(r[2] for r in rows[:-1]))
        self.assertIn('action=tool', rows[-1][0])
        self.assertIn('name=dashboard', rows[-1][0])

    def test_discovery_directories_do_not_request_sources(self):
        with patch.object(self.directory.Explorer, 'page', side_effect=AssertionError('No network in menu headings')):
            rows = self.render({'name': 'discover_shows'})
        self.assertIn('Networks', [r[1].label for r in rows])

    def test_search_history_reuses_query_without_prompt(self):
        self.db.put('search_history:movie', ['Example'])
        with patch.object(prefs, 'get', side_effect=lambda k: True if k == 'search_history' else prefs.DEFAULTS[k]):
            rows = self.render({'name': 'search_history', 'kind': 'movie'})
        self.assertEqual([r[1].label for r in rows], ['New search…', 'Example'])
        self.assertIn('value=Example', rows[1][0])

    def test_movie_menu_item_is_playable_and_ids_are_retained(self):
        with patch.object(self.directory.Explorer, 'page', return_value=([dict(title(), catalog_type='movie', catalog='trakt')], False)):
            rows = self.render({'name': 'catalog', 'kind': 'movie', 'category': 'popular'})
        self.assertEqual(rows[0][1].properties['IsPlayable'], 'true')
        self.assertIn('action=catalog_play', rows[0][0])
        from urllib.parse import parse_qs, urlsplit
        key = parse_qs(urlsplit(rows[0][0]).query)['key'][0]
        self.assertEqual(self.directory.playback_media(self.db, key)['trakt']['ids']['trakt'], 1)

    def test_default_launch_uses_main_menu_and_can_restore_dashboard(self):
        app = self.kodi.app
        for startup in ('menu', 'dashboard'):
            with self.subTest(startup=startup), patch.object(app.config, 'setting', return_value=startup), \
                 patch.object(app.sys, 'argv', ['plugin://plugin.video.luma/', '10', '']), \
                 patch.object(self.directory, 'render') as render, patch.object(app, 'home') as home, \
                 patch.object(app.xbmcplugin, 'endOfDirectory', create=True):
                app.run()
                self.assertEqual(render.called, startup == 'menu')
                self.assertEqual(home.called, startup == 'dashboard')

    def test_declining_wipe_preserves_all_data(self):
        toolbox = importlib.import_module('resources.lib.toolbox')
        self.db.put('keep', True)
        dialog = Mock()
        dialog.yesno.return_value = False
        with patch.object(toolbox.config, 'store', return_value=self.db), patch.object(toolbox.xbmcgui, 'Dialog', return_value=dialog):
            toolbox.run('wipe')
        self.assertTrue(self.db.get('keep'))
        self.assertIsNone(self.db.get('request_maintenance'))

    def test_explicit_reset_operates_only_on_local_temp_store_and_preferences(self):
        toolbox = importlib.import_module('resources.lib.toolbox')
        media = parse_name('Film.2024.mkv')
        self.db.save_progress(media, 50, 100)
        self.db.enqueue('pending', {'ids': {'trakt': 1}})
        addon = Mock()
        with patch.object(toolbox.config, 'addon', return_value=addon):
            toolbox.maintenance(self.db, 'wipe')
        self.assertEqual(self.db.history(), [])
        self.assertEqual(self.db.pending(), [])
        addon.setSetting.assert_any_call('startup', 'menu')
        addon.setSetting.assert_any_call('torbox_key', '')


if __name__ == '__main__':
    unittest.main()
