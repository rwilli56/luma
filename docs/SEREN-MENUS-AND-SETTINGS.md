# Seren navigation and settings review

Luma 0.3.0 opens its Kodi directory main menu by default. **General → Opening screen** can restore the visual dashboard. The dashboard remains an entry on the main menu.

The implementation was reviewed against the authors' published sources on November 17, 2026:

- [Seren home, search and tools menus](https://github.com/nixgates/plugin.video.seren/blob/master/resources/lib/gui/homeMenu.py), [movie menus](https://github.com/nixgates/plugin.video.seren/blob/master/resources/lib/gui/movieMenus.py), [show menus](https://github.com/nixgates/plugin.video.seren/blob/master/resources/lib/gui/tvshowMenus.py), and [settings](https://github.com/nixgates/plugin.video.seren/blob/master/resources/settings.xml).
- [Umbrella's Kodi 21 settings](https://github.com/umbrellaplug/umbrellaplug.github.io/blob/master/omega/plugin.video.umbrella/resources/settings.xml).
- [POV and Magneto's official packages](https://kodifitzwell.github.io/repo/), inspected at POV 6.11.03 and Magneto 6.11.01.
- [CocoScrapers' official repository](https://cocojoe2411.github.io/), inspected at module 1.0.45.
- [Trakt's current API contracts](https://github.com/trakt/trakt-api/tree/master/projects/api/src/contracts), including private list routes, typed public lists, calendars, chart filters and pagination.

Source files/packages used for inspection are outside the release ZIP. Luma's code remains an original implementation; the external providers remain separately installed dependencies.

## Menu coverage

| Seren area | Luma equivalent |
| --- | --- |
| Main menu | Discover Movies, Discover TV Shows, My Movies, My Shows, My Files, Search, Tools; Home Dashboard is an additional entry |
| Discovery, both media types | Most Popular; Popular Recent; Recommended For You; Trending; Trending Recent; Most Played; Most Watched; Most Collected; Trending Lists; Popular Lists; Most Anticipated; Recently Updated; Genres; Years; By Actor; Search |
| Movie discovery extras | Box Office Top 10 |
| Show discovery extras | New TV Shows; Networks |
| My Movies | Finish Watching; Collection; Watchlist; My Movie Lists; My Liked Movie Lists; My Watched Movies |
| My Shows | Finish Watching; Collection; Watchlist; Recently Watched; Next Up; Upcoming Episodes; Unfinished Shows in Collection; Recent Episodes; My Show Lists; My Liked Show Lists; My Watched Episodes |
| Search | Movies, shows, movies by actor, shows by actor; optional local title-query history |
| My Files | TorBox, Emby, Add a link, TorBox Download Manager |
| Tools | Provider Tools; Premium Services; Clear Cache; Clear Local Torrent Cache; Clear Search History; Open Settings Menu; Wipe Addon Data; Trakt Sync Tools; Download Manager |
| Provider Tools | Kodi repository update check; settings for installed CocoScrapers / POV packages |
| Premium Services | TorBox account, TorBox files, Emby library |
| Trakt Sync Tools | Flush Activities; Force Sync; Rebuild Trakt Database |
| Developer Window Tests | Optional menu for Luma's actual dashboard, source chooser, progress window and TorBox transfer viewer |

Most discovery charts, actors, networks and lists need your **Trakt application Client ID**. Personal Trakt menus and recommendations additionally need **Connect Trakt**. Luma does not borrow another add-on's application credentials. Popular, genres, years and title search have a Cinemeta fallback without a Trakt key. A missing service requirement is reported instead of substituting a different chart.

Finish Watching, Recently Watched and Next Up use Luma's existing cached Trakt/local home data. Without Trakt, completed local history is also available in watched menus. Collections and watchlists mean the Trakt collections/watchlists; My Files means files already in TorBox/Emby. Upcoming episodes are browsable metadata and are not a promise that a cached source exists.

Unfinished Shows compares collected episode numbers against watched episode numbers. Recently Updated follows Trakt metadata updates, as in Seren; it does not mean a new video release. New TV Shows follows Trakt's recent series-premiere calendar. Lists paginate by media type. Collections and unique watched movies are fetched once then paginated locally; paginated watchlists and history use server pages. API permissions, account restrictions and provider availability can still limit live results.

## Settings decisions

| Reference pattern | Luma implementation |
| --- | --- |
| Seren: separate General, Accounts, Providers, Scraping, Sort & Filter, Playback, Shortcuts, Advanced | The same functional separation, with Emby as its own category and existing credential/setting IDs preserved |
| Seren/POV/Umbrella: explicit navigation preferences | Opening screen, page size, title search history, specials/unaired visibility, local watched filtering, Next Up order |
| Seren/POV/Umbrella: selectable playback and resume styles | Separate movie/episode source selection and Ask / Resume / Beginning choices |
| Seren/Umbrella: source filtering | Resolution bounds, movie/episode size limits, CAM exclusion, optional DV-only/AV1 exclusion; compatibility and audio preference remain ahead of size/quality ordering |
| Seren/POV: scraper controls and local results cache | A configurable 5–60 second dispatch budget, 1–4 worker tasks, pack switch and 15-minute provider-metadata cache; changing a provider settings file invalidates its cache key |
| CocoScrapers: provider ownership and health/settings controls | Open its native settings rather than duplicate its per-provider switches, credentials or health controls in Luma |
| Kodi settings UX | Localized labels, help text, password fields, validated choices, bounded sliders and buttons for operational shortcuts |

All exposed preferences have runtime behavior. Defaults retain four workers, 20-second dispatch, 20-item pages, 4K support, common-audio preference and native Kodi refresh matching. Cache hits still get a fresh TorBox availability check. Pack totals are not compared with per-episode size limits until the individual video is known. Source resolution/HDR/codec/audio remain filename hints, not stream inspection results.

Disabling outbound Trakt progress does not disable importing account history. Settings and tools never store signed CDN URLs. Foreground personal menus use current access tokens; token refresh is left to the idle service to avoid simultaneous refresh-token rotation.

## Deliberate differences

Menu coverage is not complete Seren feature or settings parity. Luma does not implement Seren theme packages, Real-Debrid/Premiumize/AllDebrid clients, arbitrary Seren provider ZIPs, hoster resolution, local video downloads, Smart Play/automatic next-episode playback, pre-scraping, Playing Next or Still Watching dialogs. Settings for those features are not shown. Developer Window Tests cover Luma windows, rather than previewing unsupported Seren windows.

Provider updates go through Kodi's installed repositories. Download Manager is a read-only **TorBox transfer viewer**, not a local download queue. Luma's fixed charcoal/teal dashboard is independent of Kodi's normal directory skin.

Clear Cache preserves watch history, credentials, title mappings and queued updates. Clear Local Torrent Cache only clears cached provider metadata; it does not remove TorBox downloads. Flush Activities invalidates cached list/progress metadata; Rebuild Trakt Database also rebuilds the local snapshot and episode cache. Both preserve resume history and queued updates. Wipe Addon Data explicitly confirms local credential/history/preference removal, then lets the idle service perform it; remote files and remote history are not deleted.

Automated tests exercise menu routes, API response shapes, private-list authentication, cache boundaries and preference behavior. Live API/account checks and Google TV remote navigation remain required in [DEVICE-VALIDATION.md](DEVICE-VALIDATION.md).
