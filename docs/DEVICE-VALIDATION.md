# Device acceptance checklist

Status: **pending hardware and live-account testing**. Automated core/contract tests cannot validate Kodi installation, HDMI behavior or decoding performance.

Record Kodi version, Streamer Android/firmware build, S90F firmware, HDMI route, network connection and audio system with each run. Use files you can lawfully access and whose codec, frame rate, HDR metadata and audio tracks are independently known.

## Installation and navigation

- Install the ZIP on Kodi 21; restart Kodi once and confirm Luma's service remains active.
- Open an empty profile: all three home rows and Settings are reachable with only the remote.
- Add TorBox key; refresh; browse a single-file transfer and a season pack. Test a downloading, expired and ready transfer.
- Navigate horizontally through more than five cards, vertically across all rows, to See all, and back. Confirm focused cards are visible and no control traps focus.
- Import more than 20 watched series: home stays bounded; See all retains the rest.
- Open and leave playback; confirm the updated home appears when reopening the add-on.

## Frame-rate and HDR matrix

Set Luma's automatic frame-rate matching on. Before each test, choose a different GUI refresh rate so a successful switch is observable. Verify Kodi's settings show **On start/stop** and **Sync playback to display: Off**. Then verify the actual output with Kodi's player diagnostics and the TV's signal information where available. A multiple of the content frame rate may be selected if the exact rate is not exposed.

| Material | Expected observation | Result |
| --- | --- | --- |
| 23.976 fps SDR | Matching fractional mode or supported exact multiple; GUI mode restored after stop | Pending |
| 24.000 fps SDR | Integer-rate mode distinguished from 23.976 where the OS exposes both | Pending |
| 25 fps SDR | 25/50 Hz mode where supported | Pending |
| 29.97 fps SDR | Fractional 29.97/59.94 Hz mode where supported | Pending |
| 50 fps SDR | 50 Hz where supported | Pending |
| 59.94 and 60 fps SDR | Correct fractional/integer choice where supported | Pending |
| 4K HEVC Main10 HDR10, 23.976 fps | HDR signal plus frame-rate switching, hardware decoder active | Pending |
| 4K HDR10+, 23.976 and 24 fps | Dynamic HDR confirmed on display, no conversion introduced by add-on | Pending |
| 4K HLG | HLG output as supported by the complete playback path | Pending |
| DV-only file | Compatibility notice on this S90F profile; no assumed HDR10 fallback | Pending |
| DV + HDR10 hybrid | Correct fallback and colours verified from actual stream/profile | Pending |

Repeat representative cases from both TorBox and local Emby. Run high-bitrate material for at least 20 minutes, seek repeatedly, and inspect dropped/skipped frames and buffering. Record startup time, decoder name, peak network throughput and any HDMI resync delay. An add-on cannot guarantee HDR10+ preservation or a specific display mode without these measurements.

Disable Luma's automatic frame-rate option, change Kodi's refresh setting manually, play again, and verify Luma leaves it alone. Simulate a failed Settings.SetSettingValue response: playback should continue with a notice that matching needs manual setup.

## Audio and tracking

- AAC stereo, AC-3 5.1, E-AC-3 5.1 and E-AC-3 Atmos where available: verify audio, channel mapping and sync after a seek and a refresh switch.
- With a compatible AVR/soundbar, separately test TrueHD/Atmos and DTS variants. Record actual decode or passthrough behavior; a source-selection preference is not proof of support.
- Stop at 40%, restart Kodi, resume, and verify position within the ten-second checkpoint interval. Choose Play from beginning and Cancel in separate runs.
- Finish an episode, check it leaves Continue watching, and confirm Next up advances once. Pause the next episode and verify it replaces Next up with Continue watching.
- Play a video through another add-on while Luma's service is active: Luma must not record it.

## Live services and recovery

- TorBox: valid key, invalid key, permission error, expired file, multi-file transfer, cache refresh, web download and link creation. Verify seeking and playback after a fresh link resolution.
- Trakt: register an approved app, complete device login, cancel and expire a device code, refresh a token, and verify watched/paused state on the Trakt website. Confirm whether the configured app requires a legacy secret.
- Identify the correct series and a same-name reboot. Unidentified filename-only titles must remain local until identity is confirmed.
- Disconnect internet during playback, stop, reconnect and verify the queued update eventually syncs. Test a Trakt outage while TorBox remains reachable.
- Emby: configure a user, import a library/resume point, play an original file, stop and refresh. Confirm that user's progress updates on the server. Disconnect the server and verify TorBox still plays.
- Start playback while a background refresh is in progress; verify no further batch network calls start and checkpoints continue.

Attach results and redacted logs to the next development pass. Avoid sharing API keys, account tokens, signed playback URLs or private server addresses.
