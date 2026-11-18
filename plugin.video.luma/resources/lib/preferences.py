"""Shared definitions for Kodi settings and their runtime defaults."""

# id, label, type, default, help, constraints/options (optional), dependency (optional)
SCHEMA = [
 ('general', 'General', [
  ('startup', 'Opening screen', 'enum', 'menu', 'Choose the main menu or the visual Home Dashboard.', [('menu', 'Main menu'), ('dashboard', 'Home Dashboard')]),
  ('search_history', 'Save search history', 'bool', False, 'Stores up to 30 searches per type on this device.'),
  ('hide_specials', 'Hide specials', 'bool', True, 'Hide season zero when browsing shows.'),
  ('hide_unaired', 'Hide unaired episodes', 'bool', True, 'Upcoming Episodes always shows future air dates.'),
  ('hide_watched', 'Hide watched movies and episodes', 'bool', False, 'Uses completion already saved on this device when browsing titles and seasons. Personal watched-history menus remain visible.'),
  ('page_size', 'Items per page', 'int', 20, 'Smaller pages reduce menu memory and network work.', (10, 50, 10)),
  ('next_sort', 'Next Up sort order', 'enum', 'recent', 'Sort saved Next Up entries.', [('recent', 'Recently watched'), ('title', 'Title')]),
 ]),
 ('accounts', 'Accounts', [
  ('torbox_key', 32001, 'secret', '', 32011),
  ('trakt_client_id', 32002, 'str', '', 32012),
  ('trakt_client_secret', 32003, 'secret', '', 32013),
  ('connect_trakt', 'Connect Trakt', 'action', 'connect_trakt', 'Authorize using a code on another device.'),
  ('sync_trakt', 'Sync Trakt now', 'action', 'sync', 'Sync while Kodi is idle; local progress stays available offline.'),
  ('trakt_scrobble', 'Send playback progress to Trakt', 'bool', True, 'Disable outbound history and progress updates. Importing history remains available.'),
 ]),
 ('providers', 'Providers', [
  ('provider_coco', 32031, 'bool', True, 32033),
  ('provider_pov', 32032, 'bool', True, 32033),
  ('provider_settings', 'Manage installed providers', 'action', 'providers', 'Open CocoScrapers or POV settings. Their provider switches are respected.'),
  ('provider_updates', 'Check provider repository updates', 'action', 'provider_updates', 'Ask Kodi to refresh its installed add-on repositories.'),
 ]),
 ('scraping', 'Scraping', [
  ('scrape_timeout', 'Provider dispatch timeout (seconds)', 'int', 20, 'Stops starting tasks at this limit. Active third-party requests may finish later.', (5, 60, 5)),
  ('scrape_workers', 'Concurrent provider tasks', 'int', 4, 'Four or fewer is recommended for Google TV Streamer.', (1, 4, 1)),
  ('scrape_packs', 'Search season packs', 'bool', True, 'The requested episode must be identified inside the selected pack.'),
  ('source_cache', 'Cache provider results locally', 'bool', True, 'Reuses torrent metadata for 15 minutes. TorBox availability is checked fresh each time.'),
 ]),
 ('filters', 'Sort & Filter', [
  ('min_resolution', 'Minimum resolution', 'enum', '0', 'Unknown resolution sources remain visible when set to Any.', [('0', 'Any'), ('720', '720p'), ('1080', '1080p'), ('2160', '2160p / 4K')]),
  ('max_resolution', 'Maximum resolution', 'enum', '2160', 'Filters filename resolution hints before choosing a source.', [('720', '720p'), ('1080', '1080p'), ('2160', '2160p / 4K')]),
  ('movie_size', 'Maximum movie file size (GB; 0 = unlimited)', 'int', 0, 'A season-pack size describes the entire torrent, so pack results are not size filtered until a file is selected.', (0, 200, 5)),
  ('episode_size', 'Maximum episode file size (GB; 0 = unlimited)', 'int', 0, 'Unknown sizes remain visible. TorBox provides the final file size.', (0, 100, 1)),
  ('exclude_cam', 'Exclude CAM / telesync releases', 'bool', True, 'Uses release-name hints.'),
  ('exclude_dv', 'Exclude Dolby Vision without HDR10 fallback', 'bool', False, 'Use this to hide those filenames entirely. Off still ranks them below compatible sources.'),
  ('exclude_av1', 'Exclude AV1 sources', 'bool', False, 'Use if your device struggles with a particular AV1 encode.'),
  ('source_sort', 'Source order after compatibility preferences', 'enum', 'quality', 'Compatibility and common-audio preferences always take priority.', [('quality', 'Resolution and HDR'), ('small', 'Smaller files'), ('large', 'Larger files')]),
 ]),
 ('playback', 'Playback', [
  ('movie_playstyle', 'Movie source selection', 'enum', 'select', 'Automatic selects the first preferred cached source.', [('select', 'Choose source'), ('auto', 'Automatic')]),
  ('episode_playstyle', 'Episode source selection', 'enum', 'select', 'Applies to source search and library playback.', [('select', 'Choose source'), ('auto', 'Automatic')]),
  ('resume_style', 'Resume behaviour', 'enum', 'ask', 'Applies when a saved resume point exists.', [('ask', 'Ask'), ('resume', 'Resume automatically'), ('beginning', 'Play from beginning')]),
  ('watched_percent', 'Mark watched at (%)', 'int', 90, 'Controls local completion and outbound Trakt updates.', (70, 99, 1)),
  ('manage_refresh', 32007, 'bool', True, 32017),
  ('allow_dv', 32005, 'bool', False, 32015),
  ('prefer_lossless', 32006, 'bool', False, 32016),
 ]),
 ('emby', 'Emby', [
  ('emby_url', 32021, 'str', '', 32024), ('emby_key', 32022, 'secret', '', 'Use a token with access to the intended Emby user.'),
  ('emby_user', 32023, 'str', '', 32025),
 ]),
 ('shortcuts', 'Shortcuts', [
  ('open_dashboard', 'Open Home Dashboard', 'action', 'dashboard', 'Open the charcoal and teal home screen.'),
  ('open_status', 'Playback and connection status', 'action', 'status', 'Review frame-rate matching and service status.'),
  ('open_downloads', 'Download Manager', 'action', 'downloads', 'Review TorBox transfers. Files download to TorBox, not the Streamer.'),
 ]),
 ('advanced', 'Advanced', [
  ('catalog_ttl', 'Catalog cache lifetime (minutes)', 'int', 10, 'Caches menu metadata. Does not cache signed playback URLs.', (1, 60, 1)),
  ('library_interval', 'Library refresh interval (minutes)', 'int', 5, 'Background network work starts only while playback is idle.', (1, 60, 1)),
  ('window_tests', 'Show Window Tests in Tools', 'bool', False, 'Opens Luma interface previews without resolving a video.'),
  ('clear_cache', 'Clear catalog cache', 'action', 'clear_cache', 'Preserves credentials, progress, mappings and unsent updates.'),
  ('clear_sources', 'Clear local torrent cache', 'action', 'clear_sources', 'Deletes only cached provider results.'),
  ('clear_searches', 'Clear search history', 'action', 'clear_searches', 'Removes saved title and actor queries.'),
 ])
]
DEFAULTS = {s[0]: s[3] for _, _, settings in SCHEMA for s in settings if s[2] != 'action'}


def get(key):
    default = DEFAULTS[key]
    try:
        from . import config
        raw = config.setting(key)
    except ImportError:
        return default
    if isinstance(default, bool):
        return raw.lower() == 'true' if raw.lower() in ('true', 'false') else default
    if isinstance(default, int):
        try:
            value = int(raw)
        except (ValueError, TypeError):
            return default
        row = next(s for _, _, settings in SCHEMA for s in settings if s[0] == key)
        return max(row[5][0], min(row[5][1], value))
    if not raw:
        return default
    row = next(s for _, _, settings in SCHEMA for s in settings if s[0] == key)
    if row[2] == 'enum' and raw not in {v for v, _ in row[5]}:
        return default
    return raw
