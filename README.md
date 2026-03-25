# HackArena3.0-ApiWrapper-Python

## Release Notes

- Breaking change: `BotContext.raw` removed from the public API.
- Breaking change: `BotContext.track_data` removed from the public API.
- Added `--official` mode: reads `HA3_WRAPPER_BACKEND_ENDPOINT` and `HA3_WRAPPER_TEAM_TOKEN`, streams with `x-ha3-game-token`, and fails fast on missing values or conflicting `--sandbox_id`.
- Updated `--official` startup flow: wrapper now calls `PrepareOfficialJoin`, preloads `TrackData` before opening stream, and fails fast on `map_id` mismatch.
