import os
import time
import xbmc
import xbmcgui
from . import config
from .library import home_rows
from .media import episode_label


def list_item(media):
    item = xbmcgui.ListItem(label=media['title'])
    item.setProperty('subtitle', media.get('subtitle') or episode_label(media))
    item.setProperty('initial', media['title'][:1].upper())
    duration = media.get('duration', 0)
    progress = 100 * media.get('position', 0) / duration if duration else 0
    item.setProperty('progress', str(min(100, int(progress))))
    item.setProperty('progress_width', str(max(1, int(302 * progress / 100))))
    item.setProperty('has_progress', 'true' if progress else '')
    sources = media.get('sources', [])
    ready = any(s['ready'] for s in sources)
    item.setProperty('availability', '' if media.get('type') == 'tvshow' else ('EMBY · READY' if media.get('emby') else ('READY TO PLAY' if ready else 'ADD TO TORBOX')))
    item.setArt({'thumb': media.get('art', '')})
    return item


class Home(xbmcgui.WindowXML):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = config.store()
        self.selection = None
        self.closed = False
        self.initialized = False
        self.rows = {}
        self.revision = None

    def onInit(self):
        self.initialized = True
        self.populate()

    def populate(self):
        rows = home_rows(self.db)
        self.rows = {200: rows['continue'][:20], 300: rows['next'][:20], 400: rows['shows'][:20]}
        for control_id, media in self.rows.items():
            control = self.getControl(control_id)
            selected = max(0, control.getSelectedPosition())
            control.reset()
            if media:
                control.addItems([list_item(i) for i in media])
                control.selectItem(min(selected, len(media) - 1))
            else:
                labels = {200: ('Your evening starts here', 'Resume points appear after you start watching.'),
                          300: ('One more episode', 'Watch a series or connect Trakt to see what is next.'),
                          400: ('Keep your favourites close', 'Recently watched series will collect here.')}
                placeholder = xbmcgui.ListItem(label=labels[control_id][0])
                placeholder.setProperty('subtitle', labels[control_id][1])
                placeholder.setProperty('initial', 'L')
                control.addItem(placeholder)
        self.setProperty('library_status', self.db.get('library_status', 'Connect TorBox in Settings to get started.'))
        self.setProperty('trakt_status', self.db.get('trakt_status', 'Trakt optional · local progress active'))
        self.setProperty('hero_title', rows['continue'][0]['title'] if rows['continue'] else 'A little less searching.\nA little more cinema.')
        self.setProperty('hero_detail', 'Pick up where you left off.' if rows['continue'] else 'Your library, your place, your next episode.')
        self.revision = self.db.get('ui_revision')

    def onAction(self, action):
        if action.getId() in (9, 10, 92, 216):
            self.closed = True
            self.close()

    def onClick(self, control_id):
        if control_id in self.rows:
            position = self.getControl(control_id).getSelectedPosition()
            if self.rows[control_id] and 0 <= position < len(self.rows[control_id]):
                self.selection = ('media', self.rows[control_id][position])
            else:
                self.selection = ('settings', None)
        else:
            actions = {100: 'library', 101: 'add', 102: 'refresh', 103: 'settings',
                       201: 'continue', 301: 'next', 401: 'shows'}
            if control_id not in actions:
                return
            self.selection = (actions[control_id], None)
        self.closed = True
        self.close()


def show_home():
    home = Home('Home.xml', config.addon().getAddonInfo('path'), 'Default', '1080i')
    monitor = xbmc.Monitor()
    home.show()
    # Keep UI updates on this Python thread; the service never touches window controls.
    while not home.closed and not monitor.abortRequested():
        if home.initialized and home.db.get('ui_revision') != home.revision:
            home.populate()
        monitor.waitForAbort(.5)
    selection = home.selection
    home.close()
    del home
    return selection
