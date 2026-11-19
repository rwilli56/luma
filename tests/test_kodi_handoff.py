"""Contract tests with Kodi API doubles. These do not emulate the Kodi player."""
import importlib
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import Mock, patch

ADDON_PATH = Path(__file__).resolve().parents[1] / 'plugin.video.luma'
sys.path.insert(0, str(ADDON_PATH))


class Tag:
    def __init__(self):
        self.ids = {}

    def setUniqueIDs(self, ids):
        if not all(isinstance(v, str) for v in ids.values()):
            raise TypeError('Kodi requires string IDs')
        self.ids = ids

    def getUniqueID(self, key):
        return self.ids.get(key, '')

    def __getattr__(self, name):
        if name.startswith('set'):
            return lambda *args: None
        raise AttributeError(name)


class ListItem:
    def __init__(self, label='', **kwargs):
        self.label, self.tag, self.properties, self.path = label, Tag(), {}, ''
        self.context_menu = []

    def addContextMenuItems(self, items):
        self.context_menu.extend(items)

    def getVideoInfoTag(self):
        return self.tag

    def setProperty(self, key, value):
        self.properties[key] = value

    def setPath(self, path):
        self.path = path

    def setArt(self, art):
        pass


class Player:
    def __init__(self):
        self.tag, self.native_position, self.native_duration = Tag(), 0, 1000

    def getVideoInfoTag(self):
        return self.tag

    def getTime(self):
        return self.native_position

    def getTotalTime(self):
        return self.native_duration

    def isPlaying(self):
        return False


class ControlList:
    def __init__(self):
        self.items, self.position = [], 0

    def getSelectedPosition(self):
        return self.position

    def reset(self):
        self.items.clear()

    def addItems(self, items):
        self.items.extend(items)

    def addItem(self, item):
        self.items.append(item)

    def selectItem(self, position):
        self.position = position


class WindowXML:
    last_instance = None
    missing_control = None

    def __init__(self, filename, script_path, skin, resolution):
        WindowXML.last_instance = self
        self.filename = filename
        # Model Kodi's active-skin-first lookup. Estuary owns Home.xml.
        if filename == 'Home.xml':
            self.controls = {9000: ControlList()}
        else:
            root = ET.parse(Path(script_path) / 'resources/skins' / skin / resolution / filename)
            self.controls = {int(node.attrib['id']): ControlList() for node in root.findall('.//control[@id]')}
        if WindowXML.missing_control is not None:
            self.controls.pop(WindowXML.missing_control, None)
        self.properties = {}
        self.close_calls = 0

    def getControl(self, control_id):
        if control_id not in self.controls:
            raise RuntimeError('Non-Existent Control {}'.format(control_id))
        return self.controls[control_id]

    def setProperty(self, key, value):
        self.properties[key] = value

    def setFocusId(self, control_id):
        self.focus_id = control_id

    def close(self):
        self.close_calls += 1

    def show(self):
        self.onInit()
        if self.initialized:
            self.onClick(103)


class Monitor:
    def abortRequested(self):
        return False

    def waitForAbort(self, seconds):
        raise AssertionError('Home should already have closed in this fixture')


xbmc = types.ModuleType('xbmc')
xbmc.Player, xbmc.executebuiltin, xbmc.log, xbmc.LOGERROR = Player, Mock(), Mock(), 3
xbmc.Monitor = Monitor
gui = types.ModuleType('xbmcgui')
gui.ListItem, gui.Dialog = ListItem, Mock()
gui.WindowXML = WindowXML
plugin = types.ModuleType('xbmcplugin')
plugin.setResolvedUrl = Mock()
addon = types.ModuleType('xbmcaddon')
addon.Addon = Mock()
vfs = types.ModuleType('xbmcvfs')
sys.modules.update(xbmc=xbmc, xbmcgui=gui, xbmcplugin=plugin, xbmcaddon=addon, xbmcvfs=vfs)
from resources.lib import app
from resources.lib.monitor import PlaybackTracker
from resources.lib.media import parse_name, traits
from resources.lib.store import Store
from resources.lib import ui


class KodiHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'test.db'))
        self.media = parse_name('Show.S01E01.2160p.HDR10.mkv')
        self.media['sources'] = [{'kind': 'torrents', 'transfer_id': 1, 'file_id': 2, 'ready': True,
            'name': 'video.mkv', 'size': 10, 'traits': traits('2160p HDR10 AAC')}]
        self.db.put('library_torrents', [self.media])
        plugin.setResolvedUrl.reset_mock()
        resolver = patch.object(app, 'resolve_selected', side_effect=lambda api, source, media, check_link=True: api.resolve(source))
        self.resolve_mock = resolver.start()
        self.addCleanup(resolver.stop)

    def tearDown(self):
        self.temp.cleanup()

    def test_player_receives_fresh_cdn_url_and_tracking_id(self):
        with patch.object(app.config, 'store', return_value=self.db), patch.object(app.config, 'setting', return_value='key'), patch.object(app, 'TorBox') as torbox:
            torbox.return_value.resolve.return_value = 'https://cdn.test/secret'
            app.play(10, self.media['key'])
        handle, success, item = plugin.setResolvedUrl.call_args.args
        self.assertEqual((handle, success), (10, True))
        self.assertEqual(item.path, 'https://cdn.test/secret')
        self.assertEqual(item.tag.ids['luma'], self.media['key'])
        self.assertNotIn('cdn.test', str(self.db.get('pending_playback')))

    def test_resume_offset_passed_to_native_player(self):
        self.db.save_progress(self.media, 450, 1000)
        gui.Dialog.return_value.contextmenu.return_value = 0
        with patch.object(app.config, 'store', return_value=self.db), patch.object(app.config, 'setting', return_value='key'), patch.object(app, 'TorBox') as torbox:
            torbox.return_value.resolve.return_value = 'https://cdn.test/secret'
            app.play(10, self.media['key'])
        self.assertEqual(plugin.setResolvedUrl.call_args.args[2].properties['StartOffset'], '450.0')

    def test_resume_cancel_does_not_resolve_source(self):
        self.db.save_progress(self.media, 450, 1000)
        gui.Dialog.return_value.contextmenu.return_value = -1
        with patch.object(app.config, 'store', return_value=self.db), patch.object(app.config, 'setting', return_value='key'), patch.object(app, 'TorBox') as torbox:
            app.play(10, self.media['key'])
            torbox.assert_not_called()
        self.assertFalse(plugin.setResolvedUrl.call_args.args[1])

    def test_automatic_resume_uses_saved_offset_without_prompt(self):
        from resources.lib import preferences as prefs
        self.db.save_progress(self.media, 450, 1000)
        gui.Dialog.return_value.contextmenu.reset_mock()
        with patch.object(app.config, 'store', return_value=self.db), patch.object(app.config, 'setting', return_value='key'), \
             patch.object(prefs, 'get', side_effect=lambda k: 'resume' if k == 'resume_style' else prefs.DEFAULTS[k]), patch.object(app, 'TorBox') as torbox:
            torbox.return_value.resolve.return_value = 'https://cdn.test/secret'
            app.play(10, self.media['key'])
        self.assertEqual(plugin.setResolvedUrl.call_args.args[2].properties['StartOffset'], '450.0')
        gui.Dialog.return_value.contextmenu.assert_not_called()

    def test_unavailable_selected_link_falls_back_to_another_ready_copy(self):
        from resources.lib.resolution import SourceUnavailable
        sources = self.media['sources']
        sources.append(dict(sources[0], file_id=3, name='second.mkv'))
        self.db.put('library_torrents', [self.media])
        gui.Dialog.return_value.select.return_value = 0
        self.resolve_mock.side_effect = [SourceUnavailable('stale link'), 'https://cdn.test/second']
        with patch.object(app.config, 'store', return_value=self.db), patch.object(app.config, 'setting', return_value='key'), \
             patch('resources.lib.source_select.choose', return_value=0):
            app.play(10, self.media['key'])
        self.assertEqual(self.resolve_mock.call_count, 2)
        self.assertEqual(plugin.setResolvedUrl.call_args.args[2].path, 'https://cdn.test/second')

    def test_account_error_does_not_try_more_sources(self):
        from resources.lib.net import ApiError
        self.resolve_mock.side_effect = ApiError('TorBox', 401)
        with patch.object(app.config, 'store', return_value=self.db), patch.object(app.config, 'setting', return_value='key'):
            with self.assertRaises(ApiError):
                app.play(10, self.media['key'])
        self.assertEqual(self.resolve_mock.call_count, 1)

    def test_changed_file_metadata_is_filtered_again_before_native_playback(self):
        from resources.lib import preferences
        from resources.lib.resolution import SourceUnavailable
        def resolve(api, source, media, **kwargs):
            source['traits'] = traits('1080p.SDR.AAC')
            return 'https://cdn.test/changed'
        self.resolve_mock.side_effect = resolve
        settings = dict(preferences.DEFAULTS, min_resolution=2160, retry_sources=False)
        with patch.object(app.config, 'store', return_value=self.db), patch.object(app.config, 'setting', return_value='key'), \
             patch.object(preferences, 'get', side_effect=lambda key: settings[key]):
            with self.assertRaises(SourceUnavailable):
                app.play(10, self.media['key'])
        plugin.setResolvedUrl.assert_not_called()

    def test_failed_torrent_hash_is_excluded_from_replacement_search(self):
        from resources.lib import search
        from resources.lib.resolution import SourceUnavailable
        hash_value = 'a' * 40
        self.media['sources'][0]['hash'] = hash_value
        self.db.put('library_torrents', [self.media])
        self.resolve_mock.side_effect = SourceUnavailable('stale link')
        with patch.object(app.config, 'store', return_value=self.db), patch.object(app.config, 'setting', return_value='key'), \
             patch.object(search, 'find_sources', return_value=None) as find:
            app.play(10, self.media['key'])
        self.assertEqual(find.call_args.kwargs['exclude_hashes'], {hash_value})
        self.assertFalse(plugin.setResolvedUrl.call_args.args[1])

    def test_unavailable_resume_survives_new_filename_key(self):
        from resources.lib import search
        imported = dict(self.media, key='remote-key', sources=[], position=450, duration=1000,
                        updated=time.time(), completed=False)
        self.db.put('library_torrents', [])
        self.db.put('trakt_snapshot', {'continue': [imported]})
        def discover(media, **kwargs):
            self.db.put('library_torrents', [self.media])
            return self.media
        gui.Dialog.return_value.contextmenu.return_value = 0
        with patch.object(app.config, 'store', return_value=self.db), patch.object(app.config, 'setting', return_value='key'), \
             patch.object(search, 'find_sources', side_effect=discover), patch.object(app, 'TorBox') as torbox:
            torbox.return_value.resolve.return_value = 'https://cdn.test/secret'
            app.play(10, 'remote-key')
        self.assertEqual(plugin.setResolvedUrl.call_args.args[2].properties['StartOffset'], '450.0')

    def test_tracker_ignores_another_addon(self):
        self.db.put('pending_playback', {'media': self.media, 'created': time.time()})
        player = PlaybackTracker(self.db)
        player.onAVStarted()
        self.assertIsNone(player.current)
        self.assertEqual(self.db.history(), [])

    def test_tracker_records_local_resume_and_completion(self):
        self.db.put('pending_playback', {'media': self.media, 'created': time.time()})
        player = PlaybackTracker(self.db)
        player.tag.ids['luma'] = self.media['key']
        player.onAVStarted()
        player.native_position = 400
        player.checkpoint()
        self.assertEqual(self.db.history()[0]['position'], 400)
        player.onPlayBackEnded()
        self.assertTrue(self.db.history()[0]['completed'])
        self.assertEqual(self.db.history()[0]['position'], 1000)


class HomeLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'ui.db'))
        self.addon = Mock()
        self.addon.getAddonInfo.return_value = str(ADDON_PATH)
        WindowXML.missing_control = None

    def tearDown(self):
        WindowXML.missing_control = None
        self.temp.cleanup()

    def test_home_uses_addon_layout_despite_estuary_home_filename(self):
        with patch.object(ui.config, 'store', return_value=self.db), patch.object(ui.config, 'addon', return_value=self.addon):
            selection = ui.show_home()
        window = WindowXML.last_instance
        self.assertEqual(window.filename, 'Luma-Home.xml')
        self.assertTrue(window.initialized)
        self.assertEqual(selection, ('settings', None))
        for control_id in (200, 300, 400):
            self.assertEqual(len(window.controls[control_id].items), 1)

    def test_missing_layout_control_closes_and_surfaces_failure(self):
        WindowXML.missing_control = 200
        with patch.object(ui.config, 'store', return_value=self.db), patch.object(ui.config, 'addon', return_value=self.addon):
            with self.assertRaisesRegex(RuntimeError, 'home layout'):
                ui.show_home()
        window = WindowXML.last_instance
        self.assertFalse(window.initialized)
        self.assertTrue(window.closed)
        self.assertGreaterEqual(window.close_calls, 1)

    def test_search_button_is_present_and_navigates(self):
        with patch.object(ui.config, 'store', return_value=self.db):
            home = ui.Home('Luma-Home.xml', str(ADDON_PATH), 'Default', '1080i')
        self.assertIn(104, home.controls)
        home.onClick(104)
        self.assertEqual(home.selection, ('search', None))

    def test_context_action_on_dashboard_card_opens_custom_search(self):
        media = parse_name('Show.S17E03.mkv')
        with patch.object(ui.config, 'store', return_value=self.db):
            home = ui.Home('Luma-Home.xml', str(ADDON_PATH), 'Default', '1080i')
        home.getFocusId = Mock(return_value=300)
        home.rows = {300: [media]}
        action = Mock()
        action.getId.return_value = 117
        home.onAction(action)
        self.assertEqual(home.selection, ('custom_search', media))
        self.assertTrue(home.closed)

    def test_dashboard_stays_closed_when_custom_search_starts_playback(self):
        from resources.lib import custom_search
        media = parse_name('Show.S17E03.mkv')
        with patch.object(ui, 'show_home', return_value=('custom_search', media)) as show, \
             patch.object(custom_search, 'edit', return_value='play'):
            app.home()
        show.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
