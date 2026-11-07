# Proelium Artifex — DoW2 Mod Builder

A visual, non-destructive mod builder for **Warhammer 40,000: Dawn of War II /
Chaos Rising (Anniversary Edition)** and **Dawn of War II — Retribution**.

Build campaign mods with sliders and character sheets instead of hex editors:
loot rates and the exact rarity mix per enemy tier, global damage/armour
scaling, per-hero RPG stat sheets
with level-up growth curves, difficulty redefinition, ability tuning, mission
timers and deployments, enemy & boss tuning, Last Stand tuning, key remapping
(WASD included), and more — 21 modules in total, plus a full game-data browser
and a campaign **save editor**.

**Your game files are never modified.** Mods are built as separate archives,
installed additively next to the game, and removed cleanly. Remove the launch
options and the game is 100% vanilla.

## Getting started

1. Install **Python 3** if you don't have it (one-time):
   * open a terminal and run `winget install Python.Python.3.12`,
     or download it from https://www.python.org/downloads/windows/
     (tick "Add python.exe to PATH").
2. Double-click **`DOW2 Mod Builder.pyw`** — the builder opens in its own
   app window (Chrome or Edge, no tabs or address bar), or in a normal
   browser tab if neither is installed, at `http://localhost:8420`. Prefer a
   plain tab? Add `"window": "tab"` to `settings.json`.
   * First run auto-detects your Steam installs and prepares its knowledge
     from **your own game files** (one-time, ~30s). This happens in the
     background — the page is usable straight away.
3. Click the **?** button for a guided tour, then **Create Mod**.
4. After building + installing a mod, set the game's Steam launch options:
   `-modname YourModName -dev`

## If it doesn't start

The launcher writes everything it does to `workspace\logs\launcher.log`, and
shows a dialog if startup fails. Common cases are handled automatically:

* **"already running"** — a copy is open already; the launcher opens that
  window instead of starting a second one.
* **browser shows an empty page / connection error** — usually something else
  (often a previous copy that didn't close cleanly) is holding port 8420. The
  launcher detects this and moves to the next free port; if a stale browser
  tab still points at the old address, use the address printed in
  `launcher.log`.
* **nothing happens at all** — Python probably isn't installed or isn't
  associated with `.pyw`. Open a terminal in this folder and run
  `python app.py`, which shows any error directly.

## Save editor

The **Save Editor** tab reads your campaign saves from
`Documents\My Games\...\Saved Games` and edits:

* **Force Commander** — rename him, and optionally rename the save file to match.
* **Heroes** — level/XP, the four attributes, unspent points, recruited or not.
* **Campaign** — the star-map day, current planet, the per-type mission counters
  and kill totals.
* **Missions played** — day, mission length, objectives and score for every
  mission in the log.
* **Territory** — who holds each zone on each planet, since which day, and the
  wargear a zone's mission pays out.
* **Inventory** — add or remove any item in the game, through a searchable
  picker with type, quality, hero, campaign and level filters.
* **Story flags** — the named values the campaign scripts read back.

Close the game before writing: it keeps the campaign in memory and saves over
your file when you next finish a mission.

### Where Steam Cloud saves are read from

Retribution keeps the campaigns listed under **Existing Campaigns** in Steam
Cloud, not in `Saved Games`. To list them, the Save Editor looks in
`<Steam>\userdata\<account id>\56400\remote\` for `campaign_<Race>_<n>.sav`
(`56400` is the Retribution app id). Every Steam library folder is checked, and
if several accounts have saves, the one with the most campaigns is used.
`<n>` counts that race's campaigns from oldest (`_0`), and each file's modified
time is the date the game shows on the campaign.

These files are shown **read-only** (heroes, XP and partial gear for now). To
use a different folder, set `steam_cloud_path` for the game in `settings.json`
under `games` > `retribution`.

Safety: every write first copies the original into `Saved Games\PA_backups`,
and the new file is read back before it is accepted — if it doesn't parse, your
original is restored automatically. A save whose layout this build cannot
reproduce byte-for-byte is shown read-only rather than edited on a guess. If a
save's campaign block isn't one this build recognises, only that part is hidden
— heroes and inventory still edit normally.

## Loot rarity mix

**Better Loot** sets how often things drop; **Loot Rarity Mix** sets what grade
they are. Give each enemy tier — trash mobs, swarms, mini-bosses, bosses, planet
bosses — a target percentage per grade (common/rare/epic/legendary), and the builder
reshapes the game's drop pools to match. The preview button reads your own game
files and shows the mix your settings would produce at levels 5 to 30, next to
the vanilla numbers, before anything is built.

Those four are all the grades the game has — common, rare, epic and legendary,
the same in both games, with epic being the blue one. Columns are labelled by
grade rather than colour, because the colour depends where you look: the game's
`message_colours` table (the only rarity colour table in its data, and the one
DOW2.exe names) prints common white, rare green, epic blue and legendary
magenta, while the drop beam on the ground and the inventory frame are separate
art per grade and can read differently. Yellow pickups are consumables — a
category rather than a rarity step — and how often they appear is the item-type
weighting in Better Loot.

The game holds no legendary items below level 15 and no epics below 5, so a
grade can also be told to ignore the drop level window if you want legendaries
early. Ambitious targets that the item pool can't reach are reported per tier
and per level rather than silently missed, and a tier that would otherwise drop
nothing at some level has its grade set to ignore the window automatically.

Two game rules matter for "better loot" and the panel handles both:

- **Unique items.** Every rare, epic and legendary is flagged unique, and the
  game never drops one you already have. The base game's repeatable loot is the
  white "improved" gear, so a mix with commons at 0% runs dry late in a
  campaign. Tick **Allow duplicates** to clear the flag on the grades you pick.
- **Campaign flags.** In DoW2/CR every legendary is flagged for Chaos Rising
  only, so none can drop in the original campaign. **Chaos Rising gear in the
  base campaign** (experimental) lifts that for the items left in enemy pools.
  The preview shows the mix for each campaign separately.

**Legendaries only** is a one-click preset that sets all of the above.

## Sharing mods

**Export** on any mod card produces a ready-to-publish zip (built mod +
install README + the `modconfig.json` recipe). **Import** accepts a recipe or
a full exported zip from anyone else using the builder.

## Folder map

    app.py            the builder (pure Python stdlib — no dependencies)
    ui/               single-file web UI (4 themes)
    engine/           reverse-engineered format libraries (SGA/RBF/rb2/DDS...)
    modules/          the 20 mod modules
    modules/lootmix/  Loot Rarity Mix internals (scan, planner, report, game rules)
    config/           your mod recipes (the source of truth)
    gamedata/         generated from YOUR game install on first run
    knowledge/        catalogs & research notes (regenerable)
    workspace/build/  built mod output

## Security & transparency

Everything in this package is **plain, readable source code** — Python (no
dependencies beyond Python itself), and one HTML file.
Nothing is compiled or obfuscated. The app runs a local web server bound to
**127.0.0.1 only** (never reachable from the network), makes **no internet
connections**, collects **no telemetry**, and writes only inside its own
folder, the game folder (mod installs, removable), and Documents\My Games
(key bindings, removable). The launcher's only download offer is official
Python via Microsoft's winget — and only if you choose it from the menu.
Audit it yourself: every file opens in a text editor.

## Credits

Reverse engineering, engine, and UI by **Proelium Artifex** —
https://proeliumartifex.com — built with the PA mod-tooling stack.
Not affiliated with Relic Entertainment or Games Workshop. Requires your own
legally owned copy of the game; no game content is redistributed.
