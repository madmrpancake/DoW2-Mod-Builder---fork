# Mod Builder: Save Editor (.sv) Decision Log

Each line is a decision point, what you chose, and the result.

| # | Decision asked | Your answer | Outcome |
|---|----------------|-------------|---------|
| 1 | Apply the change so `.sv` saves are listed? | Yes | `app.py` now accepts `.sav` and `.sv` (`SAVE_EXTS`, `_list_saves`). |
| 2 | Refer to the app as "Mod Builder"? | Yes | Naming adopted. |
| 3 | Add a Relic Chunky reader/writer? (none existed in the app) | Yes, proceed | Chunk walker built; format found to be Relic Chunky v3. |
| 4 | Search game-dir text files for when the save format changed? | Yes, text only first | Nothing found; all files dated 9/20/2026. |
| 5 | Search Mod Builder's own `CHANGELOG.md`? | Yes, then pause | Only note: Retribution saves "not byte-verified" (line 376). |
| 6 | Search binaries next; are we hex-reading them? | Asked for clarification | I used string extraction and regex, not disassembly. |
| 7 | Which disassembly tools would be needed? | Curiosity only | Ghidra or capstone/pefile if ever needed; nothing installed. |
| 8 | Inspect `campaign_description.lua` and `save_game_postfix` in the archives? | Yes | Postfixes `_xp2` and `_xp2_ork`; campaign Lua is in `000_campaign.sga`. |
| 9 | Decode the Lua blob? | Yes | Partly decoded; hero XP found in the Space Marines save only. |
| 10 | Build option 1: read-only hero/XP viewer? | Yes | `engine\chunkysave.py`, API wiring and a UI panel added. |
| 11 | Move the work into a git repo on a feature branch? | Yes; do not track `workspace/`, `knowledge/`, `gamedata/` | `main` = originals; `feature/sv-save-support` = our changes. |
| 12 | Are we caught up on "Read-only first"? | (this question) | Mostly: names and XP for Space Marines only. No gear, no Orks/Imperial Guard heroes, nothing verified in game. |
| 13 | Start with the Orks save (heroes and gear)? | Yes | Found the real hero data in the campaign chunk `SCEN/APPD/CAMP/CAMS`, not the Lua blob. Orks (4 heroes), Imperial Guard (4) and Space Marines (4) all list now. Gear sits next to each hero but is unmapped. |
| 14 | Show gear in the viewer (labelled unverified), or verify the layout against the game first? | Show it, labelled unverified | Gear listed per hero from the campaign chunk. Heroes often show only 1-4 items (no weapons for some), so the list is partial. |
| 15 | Which XP is right for Cyrus: 50.0 (campaign chunk) or 49.5 (old Lua value)? All 4 Space Marines values differ by 0.5 | **Pending (needs your check in game)** | |
| 16 | Investigate why gear lists are partial, or wait for an in-game comparison? | You asked how the on-screen "Existing Campaigns" map to the saves | Found them: the 21 campaigns are Steam Cloud files `...\Steam\userdata\1479867\56400\remote\campaign_<Race>_<n>.sav` (about 4 KB each). They are not the 3 `.sv` files. Same record layout as the `CAMS` chunk. |
| 17 | Point the Save Editor at the Steam Cloud folder and read these `.sav` files? | Yes (also add a README step) | Save Editor now lists the 21 cloud `campaign_*.sav` files (read-only) next to the `.sv` files. README documents the folder. |
| 18 | Do the cloud saves' XP and gear match the game? (You also told me the three `.sv` files were copied from another computer for testing; they are not your campaigns.) | Yes, proceed | Partial check using your screenshot: all 5 visible entries show "Level 1", and the XP read from each file maps to level 1 (level 2 needs 150 XP). Not yet checked: exact XP and gear, which need a hero screen in game. |

## Mapping in-game campaigns to files

The game's "Select a Campaign > Existing Campaigns" list does not read the `.sv` files. It reads Steam Cloud campaign files:

`C:\Program Files (x86)\Steam\userdata\<steam-id>\56400\remote\campaign_<Race>_<n>.sav`

(`56400` is the Retribution app id. `<steam-id>` is your account folder, here `1479867`. Use the `userdata` subfolder that has a `56400\remote` folder with campaign files.)

How to match an on-screen entry to a file:
1. **Race:** the entry's title is the race in the file name ("Space Marines" -> `campaign_Space Marines_*.sav`).
2. **Date:** the date on the entry is the file's last-modified time, to within a second or so. "Sun Jun 07 08:50:46 2026" -> `campaign_Space Marines_0.sav`, modified 6/7/2026 8:51 AM.
3. **Order:** the game lists them alphabetically by race, then by `<n>`. `<n>` is the order the campaigns were created for that race, so `_0` is the oldest.
4. **Count:** the number of `campaign_*.sav` files should equal the "of N" total (21 here).

Worked example (screenshot, entries 16-20 of 21):

| On screen | File |
|---|---|
| Space Marines, Jun 07 08:50:46 | `campaign_Space Marines_0.sav` |
| Space Marines, Jun 16 17:51:35 | `campaign_Space Marines_1.sav` |
| Space Marines, Sep 13 07:55:49 | `campaign_Space Marines_2.sav` |
| Tyranids, Jun 07 15:32:32 | `campaign_Tyranids_0.sav` |
| Tyranids, Jun 08 07:38:50 | `campaign_Tyranids_1.sav` |

The `.sv` files in `Documents\My Games\Dawn of War II - Retribution\Saved Games` are separate mid-mission snapshots. Each embeds a copy of the campaign record (chunk `SCEN/APPD/CAMP/CAMS`).

## Open items
- Confirm the XP values in game (Orks 183.9 / 133.9 / 90.9 / 32.8; Space Marines 224.7 / 180.7 / 147.7 / 50.0).
- Confirm the UI panel renders.
- Gear list looks partial (e.g. Mekboy shows only a stikkbomb); needs checking against the game.
- Map gear to heroes.
- Add a `CHANGELOG.md` entry.
- Decide on a remote and push.
