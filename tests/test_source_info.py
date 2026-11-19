"""Source UI and reporting regressions; fixtures never probe real media."""
import importlib
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin.video.luma'))
from resources.lib import providers, source_info, filtering, preferences, resolution
from resources.lib.media import traits, file_traits, flatten, byte_size


def file(name='Film.2024.2160p.HDR10+.DDP5.1.Atmos.mkv', size=12e9):
    return flatten([{'id': 8, 'name': 'Film.2024.2160p.HDR10+.TrueHD.7.1', 'size': 60e9,
                     'hash': 'a' * 40, 'download_finished': True, 'download_present': True,
                     'files': [{'id': 3, 'name': name, 'size': size}]}], 'torrents')[0]['sources'][0]


class FileInformationTests(unittest.TestCase):
    def test_hdr_is_not_promoted_and_sdr_is_distinct_from_unknown(self):
        expected = {'HDR': 'HDR (unspecified)', 'HDR10': 'HDR10', 'HDR10+': 'HDR10+', 'HDR10Plus': 'HDR10+',
                    'HDR10.Plus': 'HDR10+', 'HLG': 'HLG', 'SDR': 'SDR', '10bit': 'SDR / unknown'}
        for name, hdr in expected.items():
            with self.subTest(name=name):
                self.assertEqual(traits(name)['hdr'], hdr)
        self.assertEqual(traits('2160p.DV.HDR10+')['hdr_formats'], ['HDR10+', 'DV'])
        self.assertTrue(traits('DV.HDR')['dv_only'])
        self.assertFalse(traits('DV.HDR10')['dv_only'])

    def test_resolution_and_codec_use_tokens_and_support_sd(self):
        for name, result in [('1080p', 1080), ('2160p', 2160), ('720p', 720), ('576i', 576), ('480p', 480), ('4K', 2160), ('8K', 4320)]:
            self.assertEqual(traits(name)['resolution'], result)
        self.assertEqual(traits('Archive1080p.Movie1080.AV100')['resolution'], 0)
        self.assertEqual(traits('AV100')['codec'], '')
        self.assertEqual(traits('AVC')['codec'], 'H.264')
        self.assertIn('1080i', source_info.format_label({'traits': traits('1080i')}))

    def test_audio_variants_channels_and_atmos_are_separate(self):
        for name, audio in [('DTS-HD.MA.5.1', 'DTS-HD MA'), ('DTS-HD.HRA', 'DTS-HD HRA'), ('DTS:X', 'DTS:X'),
                            ('TrueHD.7.1.Atmos', 'TrueHD'), ('DDP5.1', 'E-AC-3'), ('DD+5.1', 'E-AC-3'), ('DD5.1', 'AC-3'), ('DDP2.0', 'E-AC-3'), ('AAC2.0', 'AAC')]:
            with self.subTest(name=name):
                self.assertEqual(traits(name)['audio'], audio)
        hint = traits('TrueHD.7.1.Atmos.AAC.2.0')
        self.assertEqual(hint['audio_formats'], ['TrueHD', 'AAC'])
        self.assertEqual(hint['channels'], '7.1')
        self.assertEqual(hint['channel_layouts'], ['7.1', '2.0'])
        self.assertTrue(hint['atmos'])
        self.assertEqual(traits('DD+5.1')['audio_formats'], ['E-AC-3'])

    def test_file_hints_override_each_parent_group_without_borrowing_atmos(self):
        hint = file_traits('Season.1.2160p.HDR10+.TrueHD.Atmos/Show.S01E01.1080p.SDR.AAC.mkv', 'Show.4K.DV')
        self.assertEqual((hint['resolution'], hint['hdr'], hint['audio']), (1080, 'SDR', 'AAC'))
        self.assertFalse(hint['atmos'])
        self.assertFalse(hint['dv_only'])
        hint = file_traits('2160p.HDR10/Show.S01E01.mkv', 'Show.1080p.SDR')
        self.assertEqual((hint['resolution'], hint['hdr']), (2160, 'HDR10'))
        self.assertEqual(hint['origins']['resolution'], 'folder')
        self.assertEqual(file_traits('Film.8bit.mkv', 'Film.10bit')['bit_depth'], '8-bit')
        hint = file_traits('Film.5.1.mkv', 'Film.TrueHD.7.1.Atmos')
        self.assertEqual((hint['audio'], hint['channels'], hint['atmos']), ('Audio unknown', '5.1', False))

    def test_provider_quality_is_only_a_fallback_not_a_resolution_override(self):
        raw = {'source': 'torrent', 'hash': 'a' * 40, 'name': 'Film.2024.1080p.SDR.AAC', 'quality': '4K', 'size': '12.5'}
        source = providers.normalize(raw, 'test', {'type': 'movie', 'title': 'Film', 'year': 2024})
        self.assertEqual(source['traits']['resolution'], 1080)
        self.assertEqual(source['traits']['hdr'], 'SDR')
        self.assertEqual(source['size'], 12.5 * 1024 ** 3)
        self.assertEqual(source['size_origin'], 'Provider estimate')

    def test_malformed_and_unknown_sizes_never_display_nan_or_zero_gb(self):
        for size in (None, '', -1, True, 'nan', 'inf', math.inf, {}, 2 ** 64):
            self.assertEqual(byte_size(size), 0)
            self.assertEqual(source_info.size_label(size), 'Size unknown')
        self.assertEqual(source_info.size_label('2000000000'), '2.00 GB')

    def test_empty_paths_and_conflicting_short_name_cannot_break_or_change_file_info(self):
        transfer = {'id': 8, 'files': [{'id': 1}, {'id': 2, 'name': ''}, {'id': 3, 'name': 'Film.1080p.SDR.mkv', 'short_name': 'Film.2160p.HDR10+.mkv'}]}
        items = flatten([transfer], 'torrents')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['sources'][0]['name'], 'Film.1080p.SDR.mkv')
        self.assertEqual(items[0]['sources'][0]['traits']['resolution'], 1080)

    def test_pack_total_and_selected_file_are_explicitly_different(self):
        source = file()
        self.assertEqual(source['size'], 12e9)
        self.assertEqual(source['torrent_size'], 60e9)
        self.assertEqual(source_info.sizes(source, 'files'), '12.00 GB · file')
        total = dict(source, size=60e9, package='season', size_origin='TorBox cache total')
        self.assertIn('60.00 GB · torrent total', source_info.sizes(total, 'torrents'))
        self.assertEqual(source_info.package_label(total, 'torrents'), 'SEASON PACK')
        self.assertIn('Torrent total\n60.00 GB', source_info.details(source, 'files'))

    def test_details_keep_full_path_and_distinguish_hints_from_stream_analysis(self):
        source = file('Folder/Film.2160p.DV.HDR10+.TrueHD.7.1.Atmos.mkv')
        report = source_info.details(source, 'files')
        for expected in ('Folder/Film.', 'HDR10+ + DV', 'TrueHD', '7.1', 'Atmos', 'TorBox file', 'not a stream probe'):
            self.assertIn(expected, report)
        self.assertNotIn('[COLOR', source_info.text('[COLOR red]Film[/COLOR]'))

    def test_duplicate_hashes_keep_all_provider_names(self):
        found = {}
        for name in ('POV / B', 'Coco / A', 'POV / B'):
            providers.merge_result(found, {'hash': 'a' * 40, 'provider': name, 'size': 1})
        self.assertEqual(len(found), 1)
        self.assertEqual(found['a' * 40]['providers'], ['Coco / A', 'POV / B'])

    def test_refreshed_manifest_updates_size_hints_and_preserves_canonical_mapping(self):
        source = file()
        source['search_context'] = {'canonical': {'type': 'movie', 'title': 'Film', 'year': 2024},
                                    'canonical_ids': {}, 'source': {'title': 'Film', 'year': 2024}}
        api = Mock()
        api.torrent.return_value = {'id': 8, 'download_finished': True, 'download_present': True,
            'files': [{'id': 3, 'name': 'Film.2024.1080p.SDR.AAC.mkv', 'size': 2e9}]}
        resolution.resolve_selected(api, source, {'title': 'Film', 'type': 'movie', 'year': 2024}, check_link=False)
        self.assertEqual((source['size'], source['traits']['resolution'], source['traits']['hdr']), (2e9, 1080, 'SDR'))
        self.assertEqual(source['hash'], 'a' * 40)
        self.assertIn('search_context', source)
        self.assertEqual(filtering.apply([source], 'movie', dict(preferences.DEFAULTS, min_resolution=2160)), [])

    def test_release_file_disagreement_needs_actual_file_choice(self):
        release = {'traits': traits('2160p.HDR10+.TrueHD')}
        self.assertTrue(resolution.format_conflict(release, file('Film.1080p.SDR.AAC.mkv')))
        self.assertFalse(resolution.format_conflict(release, file('Film.mkv')))
        self.assertTrue(resolution.format_conflict({'traits': traits('1080p')}, file('Film.1080i.mkv')))
        self.assertFalse(resolution.format_conflict({'traits': traits('1080p')}, file('Film.1080.mkv')))

    def test_numbering_report_separates_metadata_and_source_coordinates(self):
        source = file()
        source['search_context'] = {'canonical': {'type': 'episode', 'season': 17, 'episode': 3}, 'source': {'season': 10, 'episode': 3}}
        self.assertIn('Metadata S17 E03 → source S10 E03', source_info.details(source, 'files'))


class SourceWindowTests(unittest.TestCase):
    def setUp(self):
        import test_kodi_handoff
        self.kodi = test_kodi_handoff
        self.ui = importlib.import_module('resources.lib.source_select')
        self.kodi.WindowXML.missing_control = None

    def window(self):
        return self.ui.SourceWindow('Luma-Sources.xml', str(ROOT / 'plugin.video.luma'), 'Default', '1080i',
            sources=[file(), file('Other.mkv')], media={'title': 'Film', 'year': 2024, 'type': 'movie'}, stage='files')

    def test_native_list_renders_numbered_rows_and_returns_exact_file_index(self):
        window = self.window()
        window.onInit()
        self.assertTrue(window.initialized)
        listing = window.getControl(500)
        self.assertEqual(listing.items[0].properties['source_size'], '12.00 GB · file')
        self.assertEqual(listing.items[1].properties['source_number'], '02')
        listing.selectItem(1)
        window.onClick(500)
        self.assertEqual(window.selection, 1)
        self.assertTrue(window.closed)

    def test_long_press_shows_full_information_without_selecting(self):
        window = self.window()
        window.onInit()
        action = Mock()
        action.getId.return_value = 117
        with patch.object(self.ui.xbmcgui, 'Dialog') as dialog:
            window.onAction(action)
        self.assertIn('12.00 GB', dialog.return_value.textviewer.call_args.args[1])
        self.assertFalse(window.closed)
        self.assertEqual(window.selection, -1)

    def test_back_cancels_and_layout_failure_is_recorded(self):
        window = self.window()
        window.onInit()
        action = Mock()
        action.getId.return_value = 92
        window.onAction(action)
        self.assertTrue(window.closed)
        self.assertEqual(window.selection, -1)
        self.kodi.WindowXML.missing_control = 500
        try:
            broken = self.window()
            broken.onInit()
            self.assertTrue(broken.closed)
            self.assertIsNotNone(broken.initialization_error)
        finally:
            self.kodi.WindowXML.missing_control = None

    def test_reactivation_after_info_keeps_selection_and_missing_layout_has_fallback(self):
        window = self.window()
        window.onInit()
        window.getControl(500).selectItem(1)
        window.onInit()
        self.assertEqual(window.getControl(500).getSelectedPosition(), 1)
        with patch.object(self.ui, 'SourceWindow', side_effect=RuntimeError('missing XML')), \
             patch.object(self.ui.xbmcgui, 'Dialog') as dialog:
            dialog.return_value.select.return_value = 1
            self.assertEqual(self.ui.choose([file(), file()], {'title': 'Film'}, stage='files'), 1)


if __name__ == '__main__':
    unittest.main()
