# What's changed

Plain English, newest first. The app reads this file and shows it when you click
the version badge, so keep the shape below: `## <version> — <date>`, then
`### Added` / `### Changed` / `### Fixed` / `### Known` with one bullet each.

## 1.2.6 — 23 September 2026

### Fixed
- **Late in a campaign, a high-rarity mod could stop dropping gear, or drop
  the same item over and over.** Every rare, epic and legendary in the game is
  flagged unique, and the game never drops a unique item you already have. The
  base game's repeatable loot is the white "improved" gear. With commons set to
  0%, nothing repeatable was left except one unfinished armour (Master Crafted
  Power Armor). So once you'd collected the good items, that was all that dropped.
  The build now warns when a tier has no repeatable loot, and the new
  **Allow duplicates** option fixes it.
- **Unfinished placeholder items could end up in drop pools.** Better Loot's
  "open pools" pulled in items that have no pool, no icon and no stats. Items
  with no pool now come in only if they look finished (named, with an icon),
  the same test the revive option already used. Unused items with no stats at
  all are always left out of Loot Rarity Mix.
- **An enemy tier could be left with nothing to drop, silently.** Asking for a
  grade the game has no items of at your level (legendaries below level 20 in
  DoW2/CR, say) left that tier empty. The build now makes that grade ignore the
  level window and tells you in the build log.
- **Missed targets were only explained in the preview.** The same notes now
  appear in the build log, and a level where nothing can drop is reported
  loudly instead of being skipped.
- **The Better Loot + Loot Rarity Mix note was vague.** It now gives the
  numbers, e.g. "Better Loot opened 1104 drop pools; Loot Rarity Mix then
  removed 718 of them", broken down by grade.
- **A harmless "_with_loot_quality" unknown-option warning** appeared in every
  build that used both loot modules. Gone.

### Added
- **Allow duplicates** (Loot Rarity Mix): clears the unique flag on the grades
  you pick (epic and legendary by default) for every item left in an enemy drop
  pool, so good gear keeps dropping after you have it.
- **Chaos Rising gear in the base campaign** (Loot Rarity Mix, DoW2/CR only,
  experimental): every legendary, and 128 epics, are flagged Chaos Rising only,
  so they can never drop in the original campaign. Ticking a grade allows the
  ones left in enemy pools there too.
- **Legendaries only** preset: one button sets every tier to legendary,
  ignores the level window, brings in the shelved legendaries, allows
  duplicates and, in DoW2/CR, allows them in the base campaign. Nothing is
  saved until you press Save.
- **Per-campaign mix.** For DoW2/CR the preview and the build log show the grade
  mix for the Dawn of War II and Chaos Rising campaigns separately. They warn
  when a row asks for a grade that can't drop in one of them.
- **Builder version in every mod.** Exported mods carry `builder_version` and
  `build` in `modconfig.json` and a line in `README.txt`, and the build manifest
  records both. A report about a mod can now be matched to the version that
  made it.

### Changed
- Loot Rarity Mix's code is split into `modules/lootmix/` (scan, planner,
  report, game rules). The split alone changes nothing a build produces.
- "Unfinished" unused items are marked not recommended.

### Known
- **Allow duplicates and base-campaign legendaries are verified in the files
  the build writes, not yet in a long play session.** In particular, it's not
  yet confirmed whether the game also remembers items that dropped earlier in
  a campaign.
- 25 epics and 13 legendaries also carry an `exclusive` flag whose effect is
  unknown; the builder leaves it alone.

## 1.2.5 — 22 September 2026

### Fixed
- **The builder shipped with one particular machine's game folder as its
  fallback path.** If it could not find your installation it quietly assumed
  a drive and folder that almost certainly are not yours. The fallback is now
  the standard Steam location, and nobody's personal folder layout goes out
  with the download.
- **Finding your installation is far more reliable.** The builder now asks
  Steam where its libraries are — reading the library list Steam itself keeps
  — instead of only checking a handful of likely folder names. Libraries on
  any drive, under any folder name, are found on the first run. The old
  guesswork remains as a backstop for people who installed outside Steam.

- **Unused items could be added to a drop pool and still never drop.** Items
  the game ships with no pool are marked "dropped by: none". The builder added
  the enemy tiers you asked for but left that marker sitting there, producing a
  combination the game itself never uses anywhere — 57 items in a single test
  build. The marker is now removed when an item becomes droppable, and put back
  if an item ends up dropping from nobody.
- **A third of the unused items could never be picked at all.** 119 of them
  have no level set, and the planner only ever considered levels 1 to 30, so
  they were counted, reported, and then silently ignored. They are now treated
  as droppable at any level — which is what an item with no level should be —
  and the game's own any-level flag is set so it actually happens.
- **Mission Rewards only ever changed Chaos Rising.** The base Dawn of War II
  campaign's mission files live in a different game archive, and the builder
  was not reading it — so it saw 1 of the 84 mission files instead of all of
  them, and the original campaign's rewards were left untouched no matter what
  you set. It now covers both campaigns: 62 base missions and 22 Chaos Rising
  ones. Anyone who built a rewards mod before should rebuild it.
- **A mod could build differently depending on the order its settings were
  written in.** Modules that touch the same thing were run in whatever order
  the mod file happened to list them, so Better Loot and Loot Rarity Mix — both
  of which decide which enemies drop which items — could produce different
  results from identical settings. The build order is now fixed, with the
  rarity mix running last so its percentages are the final word, and the build
  log says when both are on.
- **Difficulty settings for the other game produced eighteen warnings.** Each
  game only has its own campaigns, so settings aimed at the other one are now
  skipped with a single line instead of one warning per missing entry.
- **The preview ignored your unused-item setting.** It always modelled the full
  set whatever you had chosen, so the percentages it showed could not be the
  ones you got. It now models exactly what the build will do.

### Added
- **Unused items are chosen by kind, not all-or-nothing.** They are not alike,
  so they are now split into shelved gear that is simply missing a pool,
  items with no level, unfinished entries missing a name or icon, the game's
  own "unused" folder, and enemy loadout gear. Tick whichever you want.
- **Grades can be narrowed too.** On top of choosing the kinds, tick only the
  grades you want from them — Epic and Legendary alone brings in the good
  shelved gear without flooding the pools with white items. Gear that already
  drops is untouched either way.
- **Settings that quietly overrode each other now say so.** Some modules
  change the same value — Better Loot and Loot Rarity Mix both decide drop
  pools, Mass Scaling and Stat Tweaks both change item defence — and whichever
  ran last simply won, with nothing to tell you. The build now names every
  setting that was overridden, which module won it, and what it applies to.
- **The activity log highlights problems.** Errors and warnings are coloured
  and marked, with a count and a "warnings & errors only" filter, so a real
  problem no longer scrolls past in a wall of routine lines.
- **Updating actually takes effect now.** The builder has no window of its own,
  so an older copy keeps running in the background and keeps the port. The
  launcher saw "already running from this folder" and simply reopened the page
  — serving the OLD code, which looked exactly like an update that did nothing.
  It now compares what is running against the files on disk and restarts it when
  they differ, and says plainly what to do if the old copy will not close.
- **A stale copy now says so.** If the app is still running from before an
  update, anything new answered "unknown action" with no explanation. It now
  says which version and build is running and to close and restart it — and
  every build carries a short fingerprint beside the version, so two builds of
  the same version can be told apart.
- **An item the builder cannot read now says so** instead of showing an empty
  stat panel.
- **The log can be exported.** One button saves the whole log file — not just
  the visible tail — for keeping with a mod or sending on when reporting a
  problem.
- **Click an item to see what it actually is.** A panel opens with the item's
  picture and its real numbers, read from your own game files — defence and
  required level for armour, and for weapons the damage, damage per second,
  range, cooldown, penetration and accuracy on the move, including every weapon
  the item grants. There is a button through to the Data Browser for the full
  picture. Hovering still gives the game's own description text.
- **Text no longer runs out of its box.** The key-mapping screen was the worst
  of it: long ability names were cut off mid-word and a conflict warning could
  run several screens wide, pushing the whole page sideways. Names now wrap,
  the columns are wider, warnings wrap properly, and full attribute paths in
  the Data Browser are readable rather than trimmed.
- **Which campaign everything belongs to is now shown.** Unused items and
  stat-tweak targets carry a Dawn of War II / Chaos Rising badge (or "both"),
  each kind of unused item says how it splits between the two, and the
  difficulty and pacing settings name the base campaign in full rather than
  the ambiguous "DoW2".
- **The item list shows real in-game names and icons**, laid out like the save
  editor's gear picker — icon, name, grade badge, level, type and tag — with
  the full details on hover. Items the game never named are listed by their
  internal id, and the list says how many that is.
- **"Show the items"** lists exactly what each kind brings in — grade, name,
  type and level — so you can see what you are turning on before you build it.
  The count appears next to each tick box.
- The build log now reports how many items each kind contributed.

### Changed
- The old all-or-nothing setting is retired. Existing mods still build, keep
  their previous behaviour, and say in the build log what to switch to.

## 1.2.4 — 19 September 2026

### Fixed
- **Extra squad members added the wrong number of troops, and could leave a
  squad unkillable.** A squad's size is the total of its entries, and a single
  entry can already stand for several troops — so adding members by copying an
  entry copied its count as well. Asking for two more gave Terminator Tarkus
  six, taking that squad from four models to ten. Worse, the squad then claimed
  more members than the game ever put on the field, so the member counter read
  wrong and the squad could not be finished off, because the game was still
  waiting on troops that were never there. Sizes are now set exactly: two more
  means two more, on every squad.
- A warning now appears if you ask for a squad larger than any the game itself
  ships (12 models), since past that the same mismatch can return.

### Changed
- **Clearer wording on Extra members.** Base squad sizes are not all alike —
  most hero squads are three, but Tarkus and Terminator Tarkus are four — so
  the help now tells you to check the current size and add the difference.

## 1.2.3 — 19 September 2026

### Fixed
- **"Trait points per level-up" never did anything.** It changed the game's
  auto-allocation table — the one that hands out points for you — and every
  campaign squad in both games has auto-allocation switched off (all 50 in
  Dawn of War II / Chaos Rising, all 231 in Retribution), so the game never
  read it. Doubling it changed nothing in game, with no error to explain why.
  Mod configs still carrying the old setting now say plainly that it was
  ignored, and point at its replacement.

### Added
- **Attribute points per level-up**, in XP Tuning — the real thing: the points
  you spend on Health, Melee, Ranged and Will each time a hero levels. Vanilla
  is 2 per level in Dawn of War II and Chaos Rising, 1 in Retribution.
- **Starting attribute points**, the one-off pool a hero begins with (vanilla 5
  in Dawn of War II and Chaos Rising, none in Retribution).
- Both leave untouched any level the campaign never reaches — Retribution's
  campaign stops at level 10 — and warn you if you raise the figure far enough
  that heroes are handed more points than they can actually spend, since each
  hero also caps how much a single attribute can hold.

### Known
- **Fielding more than 4 squads on a mission is possible after all.** Earlier
  versions of this file said it was not. The 4-slot squad screen really is
  built into the game and cannot be changed, but which squads a mission
  actually spawns is decided in a script file, and that script can be told to
  ignore your picks and send everyone. The builder does not offer this yet.

## 1.2.2 — 19 September 2026

### Fixed
- **Building right after launch (or from a fresh extract) could fail with a
  "No such file... gamedata\\DOW2.module" error.** The base game file is copied
  from your install in the background at startup, and a build started before
  that finished hit a missing file. Builds now make sure that file is in place
  first (copying it on demand), and if the game can't be found you get a clear
  "set the game path in Settings" message instead of a cryptic error.
- **Unit Stats overrides were silently ignored at build time.** The editor
  saved them wrapped in a second `squads` layer, so builds matched nothing —
  and a mod with only Unit Stats changes then failed with "failed to fetch".
  The editor now saves the correct shape, and builds still accept configs
  saved by earlier versions, so existing mods just start working.
- **"Action failed: failed to fetch" when a build had nothing to build.** A
  config that produced zero changes (or builder files updated mid-run) killed
  the request instead of reporting the problem. The real message now reaches
  the toast, the two remaining unguarded endpoints answer properly, and a
  genuinely dead connection gets a plain-language message instead of the raw
  browser error.
- **Bad config keys are no longer ignored silently.** Every module now warns
  about unknown options and misplaced keys (listing the valid ones), a module
  whose settings produced no changes says so, an unknown module name in a
  config names the available modules, and Unit Stats spots the common
  double-`squads` nesting mistake and explains the fix. Malformed shapes (a
  list where a mapping belongs, and the like) fail with a clear message
  instead of a crash.
- **The version dialog showed only the first line of each note.** Wrapped
  bullets in this file now display in full, including past versions'.

### Added
- **Clearer help text in Unit Stats.** Extra members ADDS members (+2 turns a
  3-man squad into 5, it is not the total), and member Health is per model —
  never a shared pool; the in-game squad bar just shows members added
  together.
- **Terminator armour warning in Expanded Wargear.** Do not give Tarkus
  terminator armour before the final Idranel mission — that mission re-equips
  him into terminator armour, and the game hits a fatal error if he is
  already wearing one.

## 1.2.1 — 26 August 2026

### Changed
- **The launcher opens the builder in its own app window again** — a clean
  window with no tabs or address bar, using Chrome (or Edge) in app mode.
  If neither browser is found it falls back to a normal tab, and
  `"window": "tab"` in settings.json forces the old behaviour.

## 1.2 — 26 August 2026

### Fixed
- **Taunt, Battle Cry and hundreds of other abilities were missing from the
  Controls tab and never left W/A/S/D.** The bindings-file parser required a
  line to end at its closing quote, so every binding with a trailing
  `-- comment` — the entire single-player ability block — was invisible. The
  tab now lists all 773 DoW2/CR bindings (previously 172), and a full audit
  confirms only one line in the whole file is non-binding structure.

### Changed
- **The WASD preset is now computed from your own game's bindings file** at
  the moment you use it, instead of being a fixed list. On DoW2/CR that means
  99 remaps (previously 13) — every displaced binding, campaign hero
  abilities included, moved to a key that's free in its own context, verified
  to leave zero W/A/S/D conflicts. Taunt and Battle Cry land on Z. On
  Retribution the same engine covers its own bindings file — including the
  161 xp2-only ability keys the DoW2/CR file has never heard of — the first
  time you open the Controls tab there.
- Conflict checking is judged per context, the way the game resolves keys —
  vanilla shares single letters across dozens of units by design. The
  section-aware check immediately caught (and fixed) one clash in the old
  hand-picked preset.
- Applying bindings skips commands your file doesn't have (reported as
  skipped) instead of failing the whole apply — needed when settings move
  between the two games.
- First run now snapshots Retribution's key defaults too, and the Ability
  Hotkeys module (literal letters baked into ability files) offers every
  letter actually observed in either game, including Retribution's W and D.

## 1.10 — 17 August 2026

Everything since the first release, rolled into one. This is the version to be
on; earlier 1.x builds were stepping stones.

### Added
- **Save Editor tab.** Reads your campaign saves and edits hero level and XP
  (level follows the game's own XP table), the four attributes, unspent
  points, whether a hero has joined, the full wargear inventory with a
  searchable gear picker, your commander's name, the star-map day and planet,
  mission history, territory, and story flags. Every write backs the original
  up into `Saved Games\PA_backups` first and the result is read back before
  it's accepted — a save the editor can't reproduce byte-for-byte is shown
  read-only rather than edited on a guess.
- **Loot Rarity Mix module.** Set what percentage of drops from each enemy
  tier — trash mobs, swarms, mini-bosses, bosses, planet bosses — should be
  each grade (common, rare, epic, legendary). A preview button reads your own
  game files and shows the mix your settings would actually produce at levels
  5–30 next to the vanilla numbers, before anything is built. Grades can
  ignore the drop level window (the game has no legendaries below level 15),
  and targets the item pool can't reach are reported, not silently missed.
- **Corruption module (Chaos Rising).** Scale every corruption gain and every
  redemption separately — 0x gain makes the force incorruptible. The scaling
  sits at the one function every change passes through, so corrupting and
  redeeming wargear are covered too. Per-event points and the mitigation
  thresholds are editable; the "lost for good at 24" rule is kept.
- **Accessory Slots module (both games).** Set every hero's starting
  accessory slots or add to each hero's own count; capped at the three
  positions the squad screen can display.
- **The Data Browser covers Retribution** — all 10,785 of its entities with
  the full reference graph, exactly as for DoW2/Chaos Rising, and switching
  game switches the index live. The Retribution wargear catalog (1,266 items)
  also switches the Save Editor's gear picker on for Retribution saves.
- **A build hold screen.** Pressing Build brings up a panel with a live
  countdown, a progress bar, and the exact change being written. It stays up
  until the finished change list is actually on the card, and the estimate
  learns your machine: first builds are estimated from the modules enabled,
  rebuilds from that mod's own last real duration.
- A changelog inside the app (click the version badge), colour swatches on
  the loot grade columns taken from the game's own colour table, and example
  mods including Rarity Mix and Purity.

### Changed
- **Packing large mods is roughly ten times faster** (compression across CPU
  cores), the archives are built straight from the build output with no
  staging copy, and the packer counts files as it goes so big mods never look
  frozen.
- Finished builds appear immediately: each build writes a small summary so
  the page never re-reads multi-megabyte manifests, module schemas are cached
  until a module file changes, and only one build can run at a time.
- First run prepares everything from your own installation in the background
  — game paths, campaign scripts, key defaults, item-name tables for both
  games — and options that need those files fetch them on demand instead of
  failing if a build starts first.
- The page uses fonts already on your PC; the builder makes no network
  requests of any kind.

### Fixed
- Building while the configuration window was open quietly used the last
  saved version — it now asks. A stale port no longer shows an empty page —
  the launcher reuses or takes over the old copy, or moves ports, and reports
  problems in a dialog and in `workspace\logs\launcher.log`.
- A build failure ("cannot find the path specified") when packing from a
  deeply nested folder; long paths are handled throughout.
- The Retribution entity index previously couldn't read that game's newer
  file format at all; a loadout written against a wrong hero id was silently
  ignored (it now errors with the valid ids); unit-stat configs with keys at
  the wrong nesting level were silently ignored (they now warn); a hand-edited
  settings file missing a game path no longer breaks every page request.
- Every option of all 21 modules is exercised against the real game files of
  both games by an automated sweep before release; all pass.

### Known
- Retribution campaign saves have not been byte-verified — if yours isn't
  understood, the Save Editor shows it read-only rather than guessing.
- The respec option is experimental and still needs an in-game check.
- All-squads-deploy is not offered. (This entry said it was impossible. That
  was wrong, and is corrected in 1.2.3 — the squad-selection screen really is
  fixed at 4, but a mission's spawn list is script-side and can be told to
  ignore your picks. It is still not offered here.)

## 1.0.0 — 16 August 2026

### Added
- First release: non-destructive visual mod builder for Dawn of War II + Chaos Rising and Retribution, with 18 tuning modules, a data browser, controls editing, themes, and export/import of mod configurations.
