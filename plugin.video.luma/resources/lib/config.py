import os
import xbmcaddon
import xbmcvfs
from .store import Store

ADDON_ID = 'plugin.video.luma'


def addon():
    return xbmcaddon.Addon(ADDON_ID)


def setting(key):
    return addon().getSetting(key)


def profile():
    path = xbmcvfs.translatePath(addon().getAddonInfo('profile'))
    os.makedirs(path, exist_ok=True)
    return path


def store():
    return Store(os.path.join(profile(), 'luma.db'))
