"""Contract tests with Kodi API doubles. These do not emulate the Kodi player."""
import importlib
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin.video.luma'))


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


xbmc = types.ModuleType('xbmc')
xbmc.Player, xbmc.executebuiltin, xbmc.log, xbmc.LOGERROR = Player, Mock(), Mock(), 3
gui = types.ModuleType('xbmcgui')
gui.ListItem, gui.Dialog = ListItem, Mock()
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


class KodiHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(str(Path(self.temp.name) / 'test.db'))
        self.media = parse_name('Show.S01E01.2160p.HDR10.mkv')
        self.media['sources'] = [{'kind': 'torrents', 'transfer_id': 1, 'file_id': 2, 'ready': True,
            'name': 'video.mkv', 'size': 10, 'traits': traits('2160p HDR10 AAC')}]
        self.db.put('library_torrents', [self.media])
        plugin.setResolvedUrl.reset_mock()

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


if __name__ == '__main__':
    unittest.main()
