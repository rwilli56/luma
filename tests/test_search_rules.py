"""Alternate source numbering must never become the watched episode identity."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin.video.luma'))
from resources.lib import search_rules, providers, resolution
from resources.lib.media import identity, flatten
from resources.lib.library import library, refresh_library
from resources.lib.store import Store
from resources.lib.trakt import queue_progress

HASH = 'a' * 40


def episode(season=17, number=3):
    title = 'The Great British Bake Off'
    return {'title': title, 'year': 2010, 'season': season, 'episode': number, 'type': 'episode',
            'key': identity(title, 2010, season, number), 'show_key': identity(title, 2010),
            'episode_title': 'Episode {}'.format(number), 'premiered': '2026-10-01',
            'trakt': {'ids': {'trakt': 1700 + number}, 'show_ids': {'tmdb': 34549, 'trakt': 42, 'imdb': 'tt1877368'}}}


def transfer():
    return {'id': 8, 'hash': HASH, 'name': 'The.Great.British.Bake.Off.S10.2160p',
            'download_finished': True, 'download_present': True,
            'files': [{'id': 4, 'name': 'Season 10/The.Great.British.Bake.Off.S10E03.2160p.mkv', 'size': 2e9}]}


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'rules.db'))

    def tearDown(self):
        self.temp.cleanup()

    def test_numbering_alias_is_scoped_to_one_metadata_season(self):
        media = episode()
        search_rules.save(self.db, media, 'season', {'season': 10})
        rules = search_rules.effective(self.db, media)
        query = search_rules.query_media(media, rules)
        self.assertEqual((query['season'], query['episode']), (10, 3))
        self.assertEqual((media['season'], media['episode']), (17, 3))
        self.assertEqual(search_rules.effective(self.db, episode(16)), {})
        self.assertEqual(search_rules.query_media(episode(17, 4), rules)['episode'], 4)

    def test_episode_overrides_take_precedence_and_accept_zero(self):
        media = episode()
        search_rules.save(self.db, media, 'season', {'season': 10, 'episode_offset': 1})
        search_rules.save(self.db, media, 'episode', {'season': 0, 'episode': 0})
        query = search_rules.query_media(media, search_rules.effective(self.db, media))
        self.assertEqual((query['season'], query['episode']), (0, 0))
        other = search_rules.query_media(episode(17, 4), search_rules.effective(self.db, episode(17, 4)))
        self.assertEqual((other['season'], other['episode']), (10, 5))

    def test_shared_imdb_cannot_leak_rules_between_split_catalogs(self):
        original = episode()
        split = dict(original, year=2017, trakt={'ids': {'trakt': 1003}, 'show_ids': {'tmdb': 87012, 'trakt': 43, 'imdb': 'tt1877368'}})
        search_rules.save(self.db, original, 'season', {'season': 10})
        self.assertEqual(search_rules.effective(self.db, split), {})

    def test_year_title_and_provider_ids_do_not_mutate_tracking(self):
        media = episode()
        before = json.dumps(media, sort_keys=True)
        query = search_rules.query_media(media, {'season': 10, 'year': 2017, 'title': 'Alternative title', 'imdb': 'tt1234567'})
        data = providers.query_data(query, 20)
        self.assertEqual((data['tvshowtitle'], data['year'], data['season'], data['imdb']), ('Alternative title', '2017', '10', 'tt1234567'))
        self.assertEqual(data['tmdb'], '')
        self.assertEqual(json.dumps(media, sort_keys=True), before)
        query = search_rules.query_media(media, {'title_only': True})
        self.assertEqual(providers.query_data(query, 20)['imdb'], '')
        self.assertEqual(media['trakt']['show_ids']['imdb'], 'tt1877368')

    def test_release_phrases_are_literal_and_bounded(self):
        rules = search_rules.validate({'include': ['HDR10+', 'WEB-DL'], 'exclude': ['sample', 'HDTV']}, 'season')
        self.assertTrue(search_rules.release_matches('Show.S10E03.HDR10+.WEB.DL', rules))
        self.assertFalse(search_rules.release_matches('Show.S10E03.HDR10.WEB.DL', rules))
        self.assertFalse(search_rules.release_matches('Show.S10E03.HDR10+.WEB.DL.HDTV', rules))
        self.assertFalse(search_rules.release_matches('abc', {'include': ['.*']}))
        with self.assertRaises(ValueError):
            search_rules.validate({'include': ['x'] * 17}, 'season')

    def test_invalid_scopes_and_numbers_cannot_silently_fall_back(self):
        for scope, values in [('show', {'season': 10}), ('season', {'episode': 4}), ('episode', {'season': -1}),
                              ('episode', {'season': True}), ('season', {'imdb': 'https://imdb.com/title/tt1234567'})]:
            with self.subTest(scope=scope, values=values), self.assertRaises(ValueError):
                search_rules.validate(values, scope)
        with self.assertRaises(ValueError):
            search_rules.query_media(episode(), {'episode_offset': -10})

    def test_clear_cache_preserves_rules_and_reset_removes_them(self):
        search_rules.save(self.db, episode(), 'season', {'season': 10})
        self.db.clear_cache(('source_cache:', 'catalog:'))
        self.assertEqual(search_rules.effective(self.db, episode())['season'], 10)
        self.db.reset()
        self.assertEqual(search_rules.effective(self.db, episode()), {})

    def test_snapshot_revalidates_source_numbering_after_filter_reset(self):
        media = episode()
        query = search_rules.query_media(media, {'season': 10})
        snapshot = search_rules.snapshot(media, query)
        restored = search_rules.matching_media(media, snapshot)
        self.assertEqual((restored['season'], restored['episode']), (10, 3))
        with self.assertRaises(ValueError):
            search_rules.matching_media(episode(17, 4), snapshot)
        with self.assertRaises(ValueError):
            search_rules.matching_media(dict(media, trakt={'show_ids': {'tmdb': 87012}}), snapshot)

    def test_display_slug_changes_do_not_break_a_stable_catalog_mapping(self):
        media = episode()
        media['trakt']['show_ids']['slug'] = 'old-slug'
        snapshot = search_rules.snapshot(media, search_rules.query_media(media, {'season': 10}))
        changed = dict(media, trakt=dict(media['trakt'], show_ids=dict(media['trakt']['show_ids'], slug='new-slug')))
        self.assertEqual(search_rules.matching_media(changed, snapshot)['season'], 10)

    def test_ready_source_filters_honor_mapped_coordinates_and_release_words(self):
        media = episode()
        source = flatten([transfer()], 'torrents')[0]['sources'][0]
        rules = {'season': 10, 'include': ['2160p']}
        self.assertTrue(search_rules.source_eligible(source, media, rules))
        self.assertFalse(search_rules.source_eligible(dict(source, path='Show.S17E03.mkv', transfer_name='Show.S17'), media, rules))
        source['search_context'] = search_rules.snapshot(media, search_rules.query_media(media, rules))
        self.assertTrue(search_rules.source_eligible(source, media, rules))
        self.assertFalse(search_rules.source_eligible(source, media, {'season': 11}))


class SearchIntegrationTests(unittest.TestCase):
    def setUp(self):
        import test_kodi_handoff
        self.search = importlib.import_module('resources.lib.search')
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'flow.db'))
        self.api = Mock()
        self.api.cached.return_value = {HASH: {'size': 2e9}}
        self.api.add.return_value = {'torrent_id': 8}
        self.api.torrent.return_value = transfer()
        self.api.resolve.return_value = 'https://cdn.test/file'
        self.dialog = Mock()
        self.dialog.select.return_value = 0
        self.progress = Mock()
        self.progress.iscanceled.return_value = False
        self.monitor = Mock()
        self.monitor.abortRequested.return_value = False
        self.monitor.waitForAbort.return_value = False
        self.queries = []
        seen = self.queries

        class Source:
            def sources(self, data, host_dict):
                seen.append(data)
                return [{'source': 'torrent', 'name': 'The.Great.British.Bake.Off.S10E03.2160p', 'hash': HASH, 'size': 2}]
        self.source = Source

    def tearDown(self):
        self.temp.cleanup()

    def find(self, media=None, prefer_library=False):
        mod = self.search
        with patch.object(mod.config, 'store', return_value=self.db), patch.object(mod.config, 'setting', return_value='key'), \
             patch.object(mod.providers, 'installed', return_value=[{'key': 'coco', 'available': True}]), \
             patch.object(mod.providers, 'load', return_value=([('test', self.source)], [])), \
             patch.object(mod, 'TorBox', return_value=self.api), patch.object(mod.xbmcgui, 'Dialog', return_value=self.dialog), \
             patch.object(mod, 'choose_source', side_effect=lambda *args, **kwargs: self.dialog.select()), \
             patch.object(mod.xbmcgui, 'DialogProgress', return_value=self.progress, create=True), patch.object(mod.xbmc, 'Monitor', return_value=self.monitor):
            return mod.find_sources(media or episode(), prefer_library=prefer_library)

    def test_provider_pack_refresh_resume_and_trakt_keep_canonical_episode(self):
        media = episode()
        search_rules.save(self.db, media, 'season', {'season': 10, 'title_only': True})
        selected = self.find()
        self.assertEqual((self.queries[0]['season'], self.queries[0]['episode']), ('10', '3'))
        self.assertEqual(self.queries[0]['imdb'], '')
        self.assertEqual((selected['season'], selected['episode'], selected['key']), (17, 3, media['key']))
        self.db.save_progress(selected, 120, 1000)
        client = Mock()
        client.library.side_effect = [[transfer()], []]
        refresh_library(self.db, client)
        refreshed = library(self.db)[0]
        self.assertEqual((refreshed['season'], refreshed['episode']), (17, 3))
        search_rules.save(self.db, media, 'season', {})
        self.assertEqual(resolution.resolve_selected(self.api, refreshed['sources'][0], refreshed, check_link=False), 'https://cdn.test/file')
        queue_progress(self.db, refreshed, 120, 1000, False)
        event = json.loads(self.db.pending()[0]['value'])
        self.assertEqual(event['ids'], media['trakt']['ids'])
        self.assertEqual(self.db.history()[0]['season'], 17)
        self.assertNotIn('search_context', self.db.history()[0])

    def test_wrong_source_episode_is_not_accepted_despite_the_season_override(self):
        search_rules.save(self.db, episode(), 'season', {'season': 10})
        bad = transfer()
        bad['files'][0]['name'] = 'Season 10/Show.S10E04.mkv'
        self.api.torrent.return_value = bad
        with self.assertRaises(resolution.SourceUnavailable):
            self.find()

    def test_rule_changes_do_not_reuse_the_previous_provider_cache(self):
        search_rules.save(self.db, episode(), 'season', {'season': 10})
        self.find()
        self.assertEqual(len(self.queries), 1)
        search_rules.save(self.db, episode(), 'season', {'season': 10, 'include': ['2160p']})
        self.find()
        self.assertEqual(len(self.queries), 2)

    def test_mapped_episode_already_in_torbox_reuses_its_transfer_before_scraping(self):
        media = episode(17, 4)
        pack = transfer()
        pack['files'].append({'id': 5, 'name': 'Season 10/The.Great.British.Bake.Off.S10E04.2160p.mkv', 'size': 2e9})
        self.api.torrent.return_value = pack
        self.db.put('library_torrents', flatten([pack], 'torrents'))
        search_rules.save(self.db, media, 'season', {'season': 10})
        selected = self.find(media, prefer_library=True)
        self.assertEqual((selected['season'], selected['episode']), (17, 4))
        self.assertEqual(selected['sources'][0]['file_id'], 5)
        self.assertEqual(self.queries, [])
        self.api.add.assert_not_called()


class EditorTests(unittest.TestCase):
    def setUp(self):
        import test_kodi_handoff
        self.ui = importlib.import_module('resources.lib.custom_search')
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'editor.db'))

    def tearDown(self):
        self.temp.cleanup()

    def test_cancel_after_edit_does_not_commit(self):
        dialog = Mock()
        dialog.select.side_effect = [2, -1]  # season field, then Back
        with patch.object(self.ui.config, 'store', return_value=self.db), patch.object(self.ui.xbmcgui, 'Dialog', return_value=dialog), patch.object(self.ui, 'ask', return_value='10'):
            self.assertFalse(self.ui.edit(episode(), season_hint=17))
        self.assertEqual(search_rules.saved(self.db, episode(), 'season'), {})

    def test_save_commits_only_selected_scope(self):
        dialog = Mock()
        dialog.select.side_effect = [2, 8]  # season field, Save
        with patch.object(self.ui.config, 'store', return_value=self.db), patch.object(self.ui.xbmcgui, 'Dialog', return_value=dialog), patch.object(self.ui, 'ask', return_value='10'):
            self.assertTrue(self.ui.edit(episode(), season_hint=17))
        self.assertEqual(search_rules.saved(self.db, episode(), 'season'), {'season': 10})
        self.assertEqual(search_rules.effective(self.db, episode(16)), {})

    def test_reset_clears_only_this_scope_and_preserves_inherited_rules(self):
        search_rules.save(self.db, episode(), 'show', {'include': ['HDR10+']})
        search_rules.save(self.db, episode(), 'season', {'season': 10})
        dialog = Mock()
        dialog.select.side_effect = [10, 8]  # Reset draft, Save
        with patch.object(self.ui.config, 'store', return_value=self.db), patch.object(self.ui.xbmcgui, 'Dialog', return_value=dialog):
            self.assertTrue(self.ui.edit(episode(), season_hint=17))
        self.assertEqual(search_rules.effective(self.db, episode()), {'include': ['HDR10+']})

    def test_cancelled_keyboard_never_returns_its_edited_text(self):
        keyboard = Mock()
        keyboard.isConfirmed.return_value = False
        keyboard.getText.return_value = '10'
        with patch.object(self.ui.xbmc, 'Keyboard', return_value=keyboard, create=True):
            self.assertIsNone(self.ui.ask('Source season', '17'))
        keyboard.getText.assert_not_called()

    def test_long_press_context_contains_only_an_opaque_reference(self):
        import test_kodi_handoff
        item = test_kodi_handoff.ListItem()
        self.ui.attach(item, episode(), season=17, db=self.db)
        label, command = item.context_menu[0]
        self.assertEqual(label, 'Custom search filters…')
        self.assertIn('action=custom_search', command)
        self.assertNotIn('Bake', command)
        self.assertNotIn('tt1877368', command)


if __name__ == '__main__':
    unittest.main()
