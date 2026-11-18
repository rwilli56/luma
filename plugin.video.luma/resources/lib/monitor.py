"""Kodi service: cheap playback checkpoints; network work happens while idle."""
import time
import xbmc
from . import config
from .library import library, refresh_library
from .net import ApiError
from .torbox import TorBox
from .trakt import SyncDeferred, Trakt, queue_progress
from .emby import Emby, queue_emby
from . import preferences as prefs

class PlaybackTracker(xbmc.Player):
    def __init__(self, db):
        super().__init__()
        self.db, self.current = db, None
        self.position = self.duration = 0
        self.last_checkpoint = 0

    def onAVStarted(self):
        self.finish()
        try:
            key = self.getVideoInfoTag().getUniqueID('luma')
            pending = self.db.get('pending_playback', {})
            # This tag is attached only by our resolver. Never track another add-on.
            if key and key == pending.get('media', {}).get('key') and time.time() - pending.get('created', 0) < 180:
                self.current = pending['media']
                self.position, self.duration = 0, 0
                self.checkpoint()
        except (RuntimeError, AttributeError):
            self.current = None

    def checkpoint(self):
        if not self.current:
            return
        try:
            self.position, self.duration = self.getTime(), self.getTotalTime()
            if self.duration > 0:
                completed = self.position / self.duration >= prefs.get('watched_percent') / 100
                self.db.save_progress(self.current, self.position, self.duration, completed)
                self.last_checkpoint = time.monotonic()
        except RuntimeError:
            pass

    def finish(self, ended=False):
        if self.current and self.duration > 0:
            completed = ended or self.position / self.duration >= prefs.get('watched_percent') / 100
            position = self.duration if ended else self.position
            updated = time.time()
            self.db.save_progress(self.current, position, self.duration, completed, updated=updated)
            queue_progress(self.db, self.current, position, self.duration, completed, watched_at=updated)
            queue_emby(self.db, self.current, position, completed)
            if self.current.get('trakt', {}).get('ids'):
                self.db.put('queued_history:' + self.current['key'], updated)
            self.db.put('ui_revision', time.time())
            self.db.put('request_sync', True)
        self.current = None

    def onPlayBackPaused(self):
        self.checkpoint()
        if self.current and self.duration:
            queue_progress(self.db, self.current, self.position, self.duration, self.position / self.duration >= prefs.get('watched_percent') / 100)

    def onPlayBackStopped(self):
        self.finish()

    def onPlayBackEnded(self):
        self.finish(ended=True)

    def onPlayBackError(self):
        self.finish()


def sync(db):
    trakt = Trakt(db, config.setting('trakt_client_id'), config.setting('trakt_client_secret'), should_defer=xbmc.Player().isPlaying)
    if not trakt.connected or db.get('auth_pending', False, max_age=900):
        return
    if prefs.get('trakt_scrobble'):
        trakt.flush()
    # Resolve IDs only for explicitly identified series; no filename guesses are synced.
    budget = 8
    history = {h['key']: h for h in db.history()}
    for item in library(db):
        ids = item.get('trakt', {}).get('show_ids', {})
        if item['type'] != 'episode' or not ids.get('trakt') or item.get('trakt', {}).get('ids'):
            continue
        if budget <= 0 or xbmc.Player().isPlaying():
            break
        episode = trakt.call('GET', '/shows/{}/seasons/{}/episodes/{}'.format(ids['trakt'], item['season'], item['episode']),
                             params={'extended': 'full'})
        db.put('episode:{}:{}:{}'.format(ids['trakt'], item['season'], item['episode']), episode)
        budget -= 1
    trakt.snapshot()
    # Previously offline/unidentified history can now be queued once episode IDs exist.
    for item in library(db):
        prior = history.get(item['key'])
        marker = 'queued_history:' + item['key']
        if prior and item.get('trakt', {}).get('ids') and db.get(marker, 0) < prior['updated']:
            queue_progress(db, item, prior['position'], prior['duration'], prior['completed'], watched_at=prior['updated'])
            db.put(marker, prior['updated'])
    db.put('trakt_status', 'Connected · synced')


def run():
    db = config.store()
    monitor, player = xbmc.Monitor(), PlaybackTracker(db)
    next_library = next_sync = 0
    while not monitor.abortRequested():
        now = time.monotonic()
        if player.isPlaying():
            if player.current and now - player.last_checkpoint >= 10:
                player.checkpoint()
        else:
            maintenance = db.get('request_maintenance')
            if maintenance:
                from .toolbox import maintenance as maintain
                try:
                    maintain(db, maintenance)
                except Exception:
                    db.put('library_status', 'Maintenance did not finish. Reopen Luma and review settings.')
                db.put('request_maintenance', None)
                next_library = next_sync = 0
            if now >= next_library or db.get('request_refresh', False):
                db.put('request_refresh', False)
                try:
                    if config.setting('torbox_key'):
                        failures = refresh_library(db, TorBox(config.setting('torbox_key'), should_defer=player.isPlaying))
                        db.put('library_status', 'Some downloads unavailable; showing saved library' if failures else 'TorBox library ready')
                except SyncDeferred:
                    db.put('request_refresh', True)
                except (ApiError, ValueError) as exc:
                    db.put('library_status', str(exc))
                db.put('ui_revision', time.time())
                if config.setting('emby_url'):
                    try:
                        emby = Emby(config.setting('emby_url'), config.setting('emby_key'), config.setting('emby_user'), should_defer=player.isPlaying)
                        emby.flush(db)
                        db.put('library_emby', emby.library())
                        db.put('emby_status', 'Emby library ready')
                    except SyncDeferred:
                        db.put('request_refresh', True)
                    except (ApiError, ValueError):
                        db.put('emby_status', 'Emby unavailable. Check the server and account settings.')
                else:
                    db.put('library_emby', [])
                db.put('ui_revision', time.time())
                next_library = now + prefs.get('library_interval') * 60
            if now >= next_sync or db.get('request_sync', False):
                db.put('request_sync', False)
                try:
                    sync(db)
                    next_sync = now + 60
                except SyncDeferred:
                    db.put('request_sync', True)
                except (ApiError, ValueError) as exc:
                    db.put('trakt_status', str(exc))
                    next_sync = now + max(60, getattr(exc, 'retry_after', 0))
                except Exception:
                    # Do not serialize an exception that might contain personal data.
                    db.put('trakt_status', 'Sync paused; local progress is safe')
                    next_sync = now + 300
                if not player.isPlaying():
                    from .artwork import refresh
                    from .library import home_rows
                    try:
                        rows = home_rows(db)
                        refresh(db, config.profile(), library(db) + rows['continue'] + rows['next'] + rows['shows'], should_defer=player.isPlaying)
                    except Exception:
                        pass
                db.put('ui_revision', time.time())
        monitor.waitForAbort(1)
    player.checkpoint()
    player.finish()
