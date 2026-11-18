# Luma for Kodi

An original, lightweight Kodi video add-on built around TorBox and a quiet, TV-friendly home screen. Targets **Kodi 21 Omega**, Google TV Streamer (4K), and a Samsung S90F display.

**Status: 0.1.0 development alpha.** Includes an installable ZIP and automated tests. Live TorBox/Trakt/Emby accounts and a Kodi/Streamer device were not available in this workspace; installation, remote navigation, HDR output, audio and HDMI mode changes need the device checks in [the validation guide](docs/DEVICE-VALIDATION.md).

## Install

For installation and automatic updates through a GitHub-hosted Kodi repository, see [GitHub repository setup](docs/GITHUB-REPOSITORY.md). The Pages workflow derives the installation URL from the destination GitHub repository.

1. Build with `python tools/package.py`, or use `dist/plugin.video.luma-0.1.0.zip` from this workspace.
2. Transfer the ZIP to a folder or network share Kodi can access. In Kodi, enable **Settings → System → Add-ons → Unknown sources**, then choose **Add-ons → Install from zip file**.
3. Open **Video add-ons → Luma → Settings → Accounts and playback settings**. Enter your TorBox API key from your dashboard.
4. Choose **Refresh**. Open **TorBox library** to browse and play your files. New transfers can take time to become ready; refresh after they finish.
5. Add Luma to Kodi favourites for quick access. Its home is an add-on window; it does not replace your Kodi skin or the Google TV launcher.

No third-party Python packages are needed inside Kodi. Python 3.8+ is the code compatibility target; local tests ran under Python 3.13. Estuary is the first skin to validate.

## Included

- TorBox torrent and web-download libraries, with pagination, video-file filtering, season-pack files and multiple quality versions.
- User-added magnet and HTTP(S) file links, submitted to TorBox for downloading.
- Fresh TorBox playback links requested at play time; direct original-file playback through Kodi VideoPlayer.
- Continue watching, Next up, and recently watched series. Home rows show the first 20 entries; **See all** opens the complete saved list.
- Local SQLite resume storage, checkpoints every 10 seconds, and a resume/from-beginning prompt. A normal stop can lose up to the last checkpoint interval. Natural ending or 90% progress marks an item watched.
- Optional Trakt device sign-in, rotating-token refresh, paused progress, watched history, and an offline outbox.
- Optional local Emby browsing, direct original-file streams, imported resume points, and deferred server progress updates.
- A compatibility-first source chooser. The S90F defaults prefer common audio formats and HDR10+/HDR10 over filenames indicating Dolby Vision without an HDR10 fallback. Filename badges are hints; Kodi reads actual stream metadata.

This version has no source scraping, catalog discovery, automatic next-episode playback, external subtitle fetching, Emby Connect discovery, or transcoding. Downloads that are not fully present in TorBox cannot play. `.torrent` uploads, Usenet, disc images and ambiguous multi-episode files are outside this first version. `Show.S01E01.mkv` and `Show.1x01.mkv` are supported filename patterns.

## Frame-rate matching

**Set up Kodi frame-rate matching automatically** is enabled by default in Luma's playback preferences. Immediately before playback, Luma uses Kodi's local JSON-RPC interface to set:

| Kodi setting | Value |
| --- | --- |
| Adjust display refresh rate | On start/stop |
| Sync playback to display | Off |

These are persistent, Kodi-wide settings. Disable Luma's option to manage them manually. Luma reports setup failures and exposes the current settings in **Settings → Playback and connection status**. That display reports configuration, not proof of a physical HDMI mode switch.

Kodi receives the original stream without an invented frame rate. Its native demuxer and display system choose the available HDMI mode. This applies to both TorBox and Emby playback. Refresh switching depends on the modes Android, the TV and any intervening AVR expose; an exact 23.976 Hz output cannot be guaranteed by an add-on.

Kodi documents the difference between refresh switching and changing playback speed in [Player video settings](https://kodi.wiki/view/Settings/Player/Videos). The setting IDs and enum values were checked against [Kodi 21's settings definition](https://github.com/xbmc/xbmc/blob/Omega/system/settings/settings.xml).

## Connect Trakt

1. Create your own application in the [Trakt developer portal](https://developer.trakt.tv/). Follow its current app registration requirements.
2. Enter the application's **Client ID** in Luma's account settings. New device-flow applications start with the optional legacy Client Secret field empty; only use that advanced field if your existing application requires it.
3. Select **Settings → Connect Trakt**. On your phone/computer, open the verification URL shown by Trakt and enter the displayed code.
4. Trakt sync runs while Kodi is idle. It imports paused playback and all watched series, fetching show-progress details in batches of eight so a large history does not trigger one request burst. The first full Next up population may take several idle cycles.
5. For a new filename-only library title, long-press it in the library and select **Identify on Trakt**. Confirm the movie or series. Luma resolves episode IDs in the background. It never submits guessed title matches as watched history.

The login client uses `auth.trakt.tv`; data calls use `api.trakt.tv`. Tokens are saved and replaced on refresh, including rotating refresh tokens. See [Trakt's authentication guide](https://developer.trakt.tv/docs/authentication-oauth). This workspace does not include shared Trakt application credentials.

Local progress remains usable if Trakt is offline. Outbound updates wait in SQLite until sync succeeds. Local timestamps take precedence over older paused records from Trakt. Completion updates and subsequent partial rewatches use separate queue entries. A network failure after Trakt accepts an update but before responding can cause a retry; exactly-once remote history writes cannot be guaranteed.

Next up uses Trakt's aired-episode progress when connected. Offline, Luma advances only to a consecutive episode already in your library, within the same season. It does not guess season boundaries or skip missing episodes. Unfinished episodes belong in Continue watching. A Trakt episode absent from your library remains visible, but you must add its link to TorBox before it can play.

Trakt artwork is downloaded to a local cache before display, with a 2 MB per-image limit and a 50 MB disk budget. Titles without artwork use the built-in initial-card design. The [Trakt image requirements](https://developer.trakt.tv/docs/images) prohibit direct image hotlinking.

## Connect a local Emby server

Under Luma's **Accounts and playback settings → Emby**, enter:

| Field | Example / location |
| --- | --- |
| Server URL | `http://192.168.1.10:8096` or your HTTPS reverse proxy address; optional `/emby` suffix supported |
| API key or user access token | A token created in your Emby server dashboard |
| User ID | The ID of the user whose library/progress you want; available from your server's API browser user-list response or the user detail page URL |

After **Refresh**, the top library button offers **TorBox** or **Emby**. An administrator API key can access more than one user's data, so use the intended user ID. A restricted user token must have access to that same user.

Emby plays the original file over its static stream endpoint. Server progress is written when playback stops and the next idle library refresh runs, normally within five minutes; **Refresh** requests it sooner. Server resume data joins the home rows. This is a basic API-key connector: no server discovery, password sign-in, live-session reporting, Emby Next Up import, or Emby artwork yet. Original files must be decodable by Kodi on your hardware; this connector does not request a transcode to make an incompatible file playable. TorBox and Emby copies may appear separately.

The adapter follows [Emby's REST API](https://dev.emby.media/doc/restapi/index.html) and [static video streaming](https://dev.emby.media/doc/restapi/Video-Streaming.html) interfaces.

## Streamer / Samsung S90F setup

- Keep Kodi's Android **MediaCodec** and **MediaCodec (Surface)** hardware decoding enabled.
- With automatic frame-rate setup enabled, Kodi switches at start/stop. Leave time for the HDMI resync; a brief blank screen is expected. If exposed by your Kodi build, review the resolution/refresh whitelist and include the supported modes you intend to test.
- Set the TV's HDMI input up for its full UHD/HDR bandwidth. Confirm HDR/HDR10+ output using known test material; source names are not sufficient evidence.
- Keep Dolby Vision preference off for this S90F profile. Hybrid files still need testing because filenames do not establish their Dolby Vision profile or base layer.
- For TV speakers, let Kodi decode common formats. With an AVR/soundbar, enable only audio passthrough formats the entire HDMI/eARC path supports. The lossless preference changes ranking; it does not add hardware passthrough support.
- Use wired Ethernet where practical for high-bitrate originals. Do not apply an oversized Kodi RAM cache by default: Luma ships no `advancedsettings.xml` and does not alter buffer allocation.

Google lists [4K up to 60 fps, HDR10/HDR10+/HLG/Dolby Vision, 4 GB RAM and gigabit Ethernet](https://store.google.com/product/google_tv_streamer_specs?hl=en-US) for the Streamer. Samsung lists [HDR10+, HLG and Dolby Atmos](https://www.samsung.com/us/tvs/oled-tv/s90f-55-inch-55-class-oled-tvs90f-qn55s90fafxza-qn55s90fafxza/) for the S90F. Product support does not establish every Kodi/container/profile combination; use the device test matrix.

## Development and validation

```powershell
python -m unittest discover -s tests -v
python -m compileall -q plugin.video.luma
python tools/package.py
```

Tests use captured-shape fixtures and Kodi API doubles; they are not live service or video-decoding tests. The package script writes a deterministic ZIP and SHA-256 file in `dist/`, excluding tests, tools, bytecode and local account data.

To regenerate the skin and assets, install Pillow in your development Python environment, then run:

```powershell
python tools/build_ui.py
python tools/preview_ui.py
```

![Offline home layout preview with fictional titles](docs/home-layout-preview.png)

This preview is rendered from the window XML using development tooling and fictional fixture titles. It is **not a Kodi screenshot**; actual font metrics and focus behavior must be checked in Kodi.

Runtime code is in `plugin.video.luma/resources/lib`: `torbox.py` and `emby.py` are source adapters, `app.py` routes navigation and playback, `display.py` configures native frame-rate matching, `monitor.py` owns playback tracking and background sync, `store.py` persists data, and `ui.py` drives the native window.

Credentials live only in the device's Kodi add-on profile/settings and are not encrypted by this alpha. Luma does not log request URLs, tokens or raw API responses. Kodi's own debug output may include resolved stream URLs; redact them before sharing logs. Playback metadata contains file IDs and local keys, not saved CDN URLs. All background network clients check for playback before starting additional batch requests; a request already in flight may finish after playback starts.

Umbrella, POV and Seren were used as feature references. This implementation does not copy their source or package their providers. MIT license covers Luma's original implementation.
