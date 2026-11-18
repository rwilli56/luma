# Source checks, season packs and Trakt sign-in

## Review and implementation

Reviewed Umbrella **6.8.02** in its official Kodi 21 source on November 18, 2026:

- [TorBox adapter](https://github.com/umbrellaplug/umbrellaplug.github.io/blob/master/omega/plugin.video.umbrella/resources/lib/debrid/torbox.py): cache checking, selected-magnet recheck, transfer file listing, supported-video filtering and episode resolution.
- [Source pipeline](https://github.com/umbrellaplug/umbrellaplug.github.io/blob/master/omega/plugin.video.umbrella/resources/lib/modules/sources.py): matching cache results by hash and distinguishing pack results.
- [File matching utilities](https://github.com/umbrellaplug/umbrellaplug.github.io/blob/master/omega/plugin.video.umbrella/resources/lib/modules/source_utils.py): season/episode patterns, air-date handling and extra-file filtering.
- [TorBox cloud scraper](https://github.com/umbrellaplug/umbrellaplug.github.io/blob/master/omega/plugin.video.umbrella/resources/lib/cloud_scrapers/tb_cloud.py): explicit season conflicts, full folders as browse choices and individual-file size handling.

Luma 0.4.0 applies these ideas with original code. It does not redistribute or import Umbrella code. TorBox's [official torrent API](https://github.com/TorBox-App/torbox-sdk-py/blob/main/documentation/services/TorrentsService.md) remains the service contract.

## What is checked

1. Provider magnets must have a valid, consistent BitTorrent v1 hash. Equivalent uppercase/base32 hashes normalize to one identity. Known package type and season ranges are retained.
2. Bulk cache checks remain bounded at 100 hashes per request. Unknown/negative/mismatched records cannot become cache hits. No CDN links are opened during bulk checking.
3. Immediately after choosing a torrent, Luma rechecks that hash, requests cached-only creation, waits for both completion/presence flags and verifies the returned transfer hash when supplied. Cache status is not a promise that the desired episode is present.
4. The requested episode is matched against actual TorBox files. File IDs, full paths and parent-folder context are retained. Samples, trailers, extras, bonus files and Blu-ray/DVD stream-directory segments are filtered out.
5. The selected torrent file is checked against fresh transfer metadata, unless its manifest was just checked during the same handoff (15-second window). A missing, incomplete, changed or wrong-episode torrent file cannot be resolved as the requested episode.
6. A fresh TorBox CDN link is requested. By default a separate client sends `Range: bytes=0-0`, reads at most one body byte, then closes the response even if Range is ignored. This detects HTTP errors, empty responses and common HTML/JSON error pages. Redirects must stay on HTTPS. TorBox API authorization headers are never attached to the probe.
7. An expired/invalidated CDN link returning 401/403/404/410 is renewed once. Further failures can try another filtered source. A failed hash is excluded from the replacement search in that playback attempt. Account/API permission and rate-limit errors stop retries.

**Playback → Check the selected TorBox playback link** controls the probe. Its socket/request timeout is five seconds; redirects/DNS/connect attempts can add time. **Try another source when preparation or resolution fails** bounds preparation to three selections per search and resolution to three attempts per playback invocation. A replacement search can perform its own bounded preparation. Cancellation does not start a video or a new uncached download. Once Kodi has started the stream, decoder errors and mid-stream network failures remain Kodi's responsibility.

There is no proxy, transcoding, codec probe or background stream sampling. Kodi still receives the original URL and uses its native demuxer, hardware decoding, buffering and refresh-rate matching. A successful one-byte request does not prove sustained 4K bandwidth, seeking, HDR compatibility or that the stream will remain available. Signed CDN URLs are never stored in the database or history. Emby retains its existing original-file playback path.

## Episode matching

| File/folder form | Behaviour |
| --- | --- |
| `Show.S02E03.mkv`, `Show.2x03.mkv`, `Show.S02.EP03.mkv` | Exact season/episode match with number boundaries |
| `Show.Season.2.Episode.3.mkv` | Exact match |
| `Season 2/E03.mkv`, `Season 2/EP.03.mkv`, `Season 2/03 - Title.mkv` | Match only with unambiguous single-season context |
| `Show.S01-S03/Season 2/E03.mkv` | Keep the nested season; complete-pack ranges cannot force the first season onto every file |
| `Show.2024.11.18.mkv` | Match the requested episode's validated air date in the filename |
| `2024.11.18/Unidentified.mkv` | A parent-folder date cannot establish episode identity |
| `S02E030` when requesting episode 3 | Rejected |
| A filename or folder explicitly identifying another season/episode/date | Rejected, including from the manual fallback |
| `S02E03E04`, `S02E03-E04`, `2x03-04` | Combined files are excluded from automatic episode tracking |
| Unrecognized filename in a suitable pack | Optional manual file selection followed by explicit confirmation of the requested episode |

Pack totals are not compared with per-episode size limits; the individual file is checked after listing the pack. File-level quality hints take precedence over folder quality, so an explicitly 1080p/SDR file is not labeled 4K/HDR solely because its parent is named that way.

Manual/daily-file identification is bound to transfer ID, file ID and full path, plus the torrent hash when available. It survives a library refresh without applying the same episode metadata to an identically named file in another pack. Ordinary filename keys retain their existing grouping/resume identity. Already-present pack episodes can be reused through the normal library match. Filename changes can invalidate a manual binding and require confirmation again.

Absolute-number anime/DVD numbering does not have an automatic metadata-numbering translation. Ambiguous combined files, unknown air dates and disc structures are not guessed into a playable episode. Manual confirmation cannot override a detected conflicting episode/date or turn a combined file into two independent resume points.

## Connect Trakt

Luma needs its own configured **Trakt application Client ID**. A user account or eight-character activation code is not an application ID. With no saved Client ID, Connect Trakt now explains the requirement and offers to accept the ID before starting device authentication. Cancelling that step leaves the existing state alone.

1. Register an application through [Trakt's developer portal](https://developer.trakt.tv/docs/create-an-app), following its current requirements.
2. Copy its Client ID into **Tools → Open Settings Menu → Accounts**, or enter it when Connect Trakt prompts.
3. Start Connect Trakt. Open the displayed HTTPS verification URL on another device, enter the activation code, and approve the application.
4. Wait for Luma to report connection, then let idle sync populate personal history and Next Up.

The OAuth host remains **auth.trakt.tv**, as required by [Trakt's official OAuth contract](https://github.com/trakt/trakt-api/blob/master/projects/api/src/contracts/oauth/index.ts); metadata uses **api.trakt.tv**. The required API headers are also supplied to device login. New applications leave the optional legacy Client Secret field blank unless their registration explicitly requires it.

Device-code responses and tokens are validated before display/storage. Incomplete tokens cannot overwrite a working connection. Polling respects pending status, interval changes, rate limits, expiry and cancellation; invalid application IDs and denied/used codes get actionable messages. A dialog is closed only if it was created, and the background auth guard is cleared even on failure. Errors retain only recognized OAuth identifiers, not raw response bodies, secrets or token descriptions. Refresh-token rotation remains owned by the idle service.

Automated tests cover these transitions and source/file fixtures. Live authorization requires the user's registered application and approval; live TorBox/CDN and Google TV playback remain separate device/account validation.
