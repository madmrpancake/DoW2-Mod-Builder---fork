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
| 14 | Show gear in the viewer (labelled unverified), or verify the layout against the game first? | **Pending** | |
| 15 | Which XP is right for Cyrus: 50.0 (campaign chunk) or 49.5 (old Lua value)? All 4 Space Marines values differ by 0.5 | **Pending (needs your check in game)** | |

## Open items
- Confirm the XP values in game (Orks 183.9 / 133.9 / 90.9 / 32.8; Space Marines 224.7 / 180.7 / 147.7 / 50.0).
- Confirm the UI panel renders.
- Map gear to heroes.
- Add a `CHANGELOG.md` entry.
- Decide on a remote and push.
