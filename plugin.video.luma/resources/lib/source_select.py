"""Native full-screen, remote-controlled source/file picker."""
import xbmc
import xbmcgui
from . import config, source_info


class SourceWindow(xbmcgui.WindowXML):
    def __init__(self, *args, **kwargs):
        self.sources = kwargs.pop('sources')
        self.media = kwargs.pop('media')
        self.stage = kwargs.pop('stage')
        super().__init__(*args, **kwargs)
        self.closed, self.initialized, self.initialization_error = False, False, None
        self.selection = -1

    def onInit(self):
        if self.initialized:
            return
        try:
            self.setProperty('source_title', source_info.title(self.media))
            self.setProperty('source_heading', 'CHOOSE A VIDEO FILE' if self.stage == 'files' else 'CHOOSE A SOURCE')
            self.setProperty('source_count', '{} {} · preferred formats first'.format(len(self.sources), 'files' if self.stage == 'files' else 'cached torrents'))
            self.setProperty('source_note', 'File sizes from the library · format badges are hints' if self.stage == 'files' else 'Torrent totals shown · file details checked after selection')
            items = []
            for number, source in enumerate(self.sources, 1):
                item = xbmcgui.ListItem(label=source_info.text(source['name']))
                values = {'number': '{:02d}'.format(number), 'formats': source_info.format_label(source),
                          'release': source_info.text(source.get('path') or source['name']),
                          'status': ('EMBY · READY' if source.get('kind') == 'emby' else 'TORBOX · READY' if self.stage == 'files' else 'TORBOX · CACHED'),
                          'package': source_info.package_label(source, self.stage),
                          'size': source_info.sizes(source, self.stage),
                          'provider': source_info.text(source.get('provider') or ('Emby library' if source.get('kind') == 'emby' else 'TorBox library'))}
                values['mapping'] = source_info.mapping(source)
                for key, value in values.items():
                    item.setProperty('source_' + key, value)
                items.append(item)
            listing = self.getControl(500)
            listing.reset()
            listing.addItems(items)
            listing.selectItem(0)
            self.setFocusId(500)
            self.initialized = True
        except Exception as exc:
            self.initialization_error = type(exc).__name__
            self.finish()
            xbmc.log('Luma: source picker initialization failed ({})'.format(self.initialization_error), xbmc.LOGERROR)

    def finish(self, selection=-1):
        self.selection, self.closed = selection, True
        self.close()

    def show_info(self):
        position = self.getControl(500).getSelectedPosition()
        if 0 <= position < len(self.sources):
            xbmcgui.Dialog().textviewer('Source information', source_info.details(self.sources[position], self.stage))

    def onClick(self, control_id):
        if control_id == 500:
            position = self.getControl(500).getSelectedPosition()
            if 0 <= position < len(self.sources):
                self.finish(position)
        elif control_id == 501:
            self.show_info()
        elif control_id == 502:
            self.finish()

    def onAction(self, action):
        if action.getId() in (9, 10, 92, 216):
            self.finish()
        elif action.getId() in (11, 117):
            self.show_info()


def choose(sources, media, stage='torrents'):
    if not sources or xbmc.Player().isPlaying():
        return -1
    def fallback():
        items = [xbmcgui.ListItem(label=source_info.format_label(s) + ' · ' + source_info.sizes(s, stage),
                                  label2=source_info.text(s['name'])) for s in sources]
        return xbmcgui.Dialog().select('Choose source' if stage == 'torrents' else 'Choose video file', items, useDetails=True)
    try:
        window = SourceWindow('Luma-Sources.xml', config.addon().getAddonInfo('path'), 'Default', '1080i',
                              sources=sources, media=media, stage=stage)
    except RuntimeError:
        return fallback()
    monitor = xbmc.Monitor()
    try:
        window.show()
        while not window.closed and not monitor.abortRequested():
            if xbmc.Player().isPlaying():
                return -1
            monitor.waitForAbort(.1)
        if monitor.abortRequested() or xbmc.Player().isPlaying():
            return -1
        if window.initialization_error:
            # Keep selection usable with skins that cannot load the custom window.
            return fallback()
        return window.selection
    finally:
        window.close()
