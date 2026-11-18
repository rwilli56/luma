# Custom searches and alternate episode numbering

Luma 0.5.0 adds **Custom search filters…** to the long-press menu on movies, series, season folders and episodes. The optional Home Dashboard opens the same editor when you long-press a focused card.

## Bake Off: metadata season 17, source season 10

1. Open the intended *The Great British Bake Off* catalog entry and browse its seasons.
2. Long-press **Season 17**, then choose **Custom search filters…**.
3. Change **Search season · metadata 17** to **10**.
4. Choose **Save filters** and open an episode from season 17.

Alternatively, long-press an episode, choose **This season · 17**, edit the search season, then **Save filters** or **Save and find sources now**. An episode such as metadata `S17E03` searches providers and validates the selected pack file as `S10E03`. Its display metadata, Trakt episode IDs, resume and watched history remain `S17E03`. Other metadata seasons keep their own numbering. Episode numbers change only if you explicitly set an offset or episode-specific value.

Different providers can associate the same name or IMDb ID with different catalog entries. Check the returned release names. If changing the season alone still finds the wrong catalog, set the **Search year** and title appropriate to that source catalog, use an explicit provider IMDb ID, or enable **Use title-only provider searches**. Provider implementations determine how they use these hints. Luma does not assume that every source uses the same numbering or apply an automatic show-wide Bake Off offset.

## Available filters

| Filter | Scope and effect |
| --- | --- |
| Search title / year | Movie, whole show, season or episode; provider hints only |
| Search season | One metadata season or episode; changes provider queries and actual-file matching |
| Source episode offset | Season or episode; adds a signed offset to the metadata episode number |
| Search episode | One episode; takes precedence over the offset |
| Use title-only provider searches | Clears provider-facing catalog IDs while preserving display/tracking IDs |
| Provider IMDb ID | Replaces provider-facing IDs with this IMDb ID when title-only mode is off |
| Required release phrases | Every phrase must appear in the release name |
| Excluded release phrases | Any matching phrase removes that release |

Separate release phrases with commas. Matching is literal and case-insensitive; dots, underscores, hyphens and spaces are equivalent. `HDR10+` keeps its plus sign. These phrases are release-name hints; Luma's global format/size preferences and actual pack-file validation still apply.

Show settings are inherited by seasons; episode settings take precedence over both. Whole-show settings cover title, year, provider IDs and release phrases. Numbering edits require a season or episode scope. A show row also offers **Choose a metadata season…** when the season folder is not available. Season/episode zero is supported for specials.

**Save filters** commits the draft. **Reset this scope to inherited defaults** clears only the draft for that scope; choose Save to apply it. Back cancels unsaved edits. Clearing a numeric/text field removes that scope's override and restores inheritance. Clearing the required/excluded phrase list saves an empty list, allowing a child scope to disable inherited phrases.

## Persistence and playback

Overrides are local SQLite data, keyed by the specific catalog identity and metadata coordinates. A strong TMDb/Trakt identity takes precedence over potentially shared IMDb/TVDB IDs, so split catalog entries do not automatically inherit each other's rules. Ordinary cache clears retain overrides; **Wipe Addon Data** removes them.

Search cache keys include the effective overrides. Before using providers during ordinary playback, Luma can reuse a ready matching torrent already in its TorBox library snapshot. Availability and actual files are still checked before playback; this does not create an uncached download. An explicit **Save and find sources now** searches installed providers.

A confirmed file binding retains both its canonical episode and source-numbering context. Library refreshes and later filter resets therefore preserve playback of that confirmed file. Changing the active numbering filters prevents reusing an incompatible source for the new search. Resetting filters does not erase confirmed file bindings.

Editing filters performs no network requests. Provider searching remains unavailable during playback. This feature does not add decoding, remuxing or transcoding; native Kodi playback and frame-rate matching continue to handle the original stream.

## Upstream review

Reviewed official upstream sources on November 18, 2026:

- [Umbrella's episode mapping module](https://github.com/umbrellaplug/umbrellaplug.github.io/blob/master/omega/plugin.video.umbrella/resources/lib/modules/episode_mapping.py) explicitly distinguishes Bake Off's original/combined and 2017 split entries. Its mapping associates split seasons 1–10 with combined seasons 8–17, keeps catalog metadata separate from scrape coordinates, and uses source coordinates for pack resolution. Shared IMDb/TVDB IDs alone are insufficient to distinguish those entries. Luma follows that separation with explicit user-scoped mappings in either direction.
- [Umbrella's source pipeline](https://github.com/umbrellaplug/umbrellaplug.github.io/blob/master/omega/plugin.video.umbrella/resources/lib/modules/sources.py) and [source preferences](https://github.com/umbrellaplug/umbrellaplug.github.io/blob/master/omega/plugin.video.umbrella/resources/lib/modules/source_preferences.py) carry source context and scope saved preferences by catalog/season.
- [POV 6.11.03 from its author's repository](https://kodifitzwell.github.io/repo/plugin.video.pov/plugin.video.pov-6.11.03.zip): `resources/lib/modules/dialogs.py` provides custom title/year/season/episode searches; `sources.py` carries those custom values alongside metadata, and `debrid.py` uses custom season/episode values during pack-file resolution. Luma adds persistent show/season/episode scopes, release phrases and a remote-friendly editor around that principle.

Luma's implementation is original code. Upstream add-on code and review snapshots are not bundled in its installation package. Automated fixtures cover scoped mappings, provider queries, wrong-episode rejection, cached-source reuse, library refreshes, preserved Trakt IDs and editor cancellation. Native Kodi remote behavior and real provider/account results still require device validation.
