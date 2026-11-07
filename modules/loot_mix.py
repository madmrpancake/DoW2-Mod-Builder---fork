"""Loot Rarity Mix — set the percentage of each grade that drops per enemy tier.

Why this needs its own module
-----------------------------
The game has no rarity weighting to turn up. Reading tuning/tuning_info.rbf
end to end, the only drop knobs are:

    wargear_drop_probabilities/<class>       chance of ANY drop per kill
                                             (chaff .03, swarm .01, mini_boss
                                             .04, boss 1.0, planet_boss 1.0)
    wargear_type_drop_probabilities/<type>   relative weight per item TYPE
                                             (armour 2.2, weapon 2.0, ...)
    wargear_drop_level_minimum/maximum_offset   level window, vanilla -2..+2

Grade is decided entirely by WHICH ITEMS ARE ELIGIBLE: each item carries
wargear/quality, wargear/level and a wargear/dropped_by pool list, and the
generator can only hand out an item whose pool contains the dead enemy's class
and whose level sits inside the window. So the vanilla mix is just a census of
the pools — for regular kills (chaff): 125 common, 320 rare, 21 epic, 1
legendary, which is why trash mobs shower you with white and green.

The lever, therefore, is pool membership, and it is a precise one: because the
generator picks uniformly among eligible items, making the eligible counts
proportional to your target percentages makes the drops follow those
percentages. Two details matter for that to hold in play:

  * eligibility is a LEVEL WINDOW, not a level, so the mix is solved for the
    whole window a hero of each level sees (vanilla five levels wide) — solving
    per level lets one level's items be swamped by its neighbours';
  * the game rolls an item TYPE first, by the weights above, and only then an
    item, so the solver works per type and leans on the types that hold a scarce
    grade. That is how a target can be met from a handful of items.

The grades and their colours
----------------------------
Four grades, in both games, from each item's wargear/quality: common, rare, epic,
legendary. Epic is the blue one. There is no fifth gear grade — the fifth quality
value in the data, "consumable", covers grenades/medkits/ammo/stratagems, is
drawn yellow, and is a category rather than a rarity step (its share is the
item-type weighting, not a quality weight), so this module leaves those types
alone.

On colour, what is actually verifiable: tuning_info wargear/message_colours ->
common #ffffff, rare #00ff00, epic #007aff, legendary #ff00ff (magenta), and
DOW2.exe refers to that table by name while containing no "rarity" or
"quality_colour" table of its own. That governs the drop/acquire MESSAGE text.
The in-world drop beam and pickup flash are separate art per grade
(art/fx/fx_ambient/wargear/wargear_drop_<grade>.bfx, over greyscale mask
textures art/fx/textures/ui/wargear_<grade>.dds), and the tint inside those .bfx
files has not been decoded, so a grade can legitimately look a different colour
on the ground than in the message line. Columns are therefore labelled by grade
name, not by colour.

What it cannot do
-----------------
It cannot conjure items that do not exist. There are no legendary items below
level 15 and no epics below level 5, so those grades cannot drop early on the
game's own terms. Two ways round it, both the game's own mechanisms: widen the
drop level window (a level-13 hero then reaches the level-15 legendaries), or
tick the grade under "ignore the level window", which sets each item's
ignore_level_requirement_when_dropping flag — the flag vanilla uses to keep
consumables droppable at any level. Every build reports the mix it actually
achieves, per tier and per level.

Config:
    {"targets": {"chaff": {"common": 10, "rare": 40, "epic": 35, "legendary": 15},
                 "mini_boss": {...}, "boss": {...}, "planet_boss": {...},
                 "swarm": {...}},          # a class left out is not touched
     "include_unused_items": true,         # also use items that ship with no pool
     "min_per_bucket": 2,                  # keep at least this much variety
     "types": ["weapon", "armour", "accessory", "commander_accessory"]}
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

GAMES = ["dow2cr", "retribution"]


# Internals live in modules/lootmix/ (split in 1.2.6). Re-exported so callers
# and the dev probes keep using loot_mix.<name>.
from modules.lootmix.common import (  # noqa: E402,F401
    QUALITIES, GRADE_COLOURS, CLASSES, TYPES, WG_PREFIXES, LEVEL_CAP,
    UNUSED_SOURCES, UNUSED_LABELS, CAMPAIGN_LABELS, campaign_of, classify_unused)
from modules.lootmix.scan import (  # noqa: E402,F401
    scan, item_stats, unused_census, _type_weights, _level_window)
from modules.lootmix.planner import (  # noqa: E402,F401
    _mix_of, _allocate, plan, _median_total, vp_not_dropped, _apply_plan)
from modules.lootmix.report import (  # noqa: E402,F401
    project, preview, _ceiling, shortfalls, finalise)
from modules.lootmix.rules import (  # noqa: E402,F401
    ENEMY, DOW2_CAMPAIGNS, in_campaign, campaign_notes, campaign_counts,
    repeatable_notes, zero_stat)
from modules.lootmix import scan as _scan_mod  # noqa: E402



def _grades_from_cfg(cfg: dict) -> set:
    """Which grades of unused item to bring in (all of them unless narrowed)."""
    g = cfg.get("unused_grades")
    if g is None:
        return set(QUALITIES)
    return {q for q in g if q in QUALITIES}


def _sources_from_cfg(cfg: dict) -> set:
    """Accept the new multi-select, and configs written against the old bool."""
    if cfg.get("unused_sources") is not None:
        return {s for s in cfg["unused_sources"] if s in UNUSED_SOURCES}
    if "include_unused_items" in cfg:          # pre-1.2.5 configs
        return set(UNUSED_SOURCES) if cfg.get("include_unused_items") else set()
    return set()



SCHEMA = {
    "module": "loot_mix",
    "title": "Loot Rarity Mix",
    "target_file": "simulation/attrib/wargear/** (dropped_by pools)",
    "note": "Set what PERCENTAGE of drops from each enemy tier should be each "
            "GRADE. The game has exactly four — common, rare, epic, legendary "
            "— in both DoW2/CR and Retribution; epic is the blue one. The dots "
            "show the colour the engine prints each grade's drop message in; "
            "the beam on the ground and the inventory frame are separate art "
            "per grade, so legendary can read red-orange in play even though "
            "its message text is magenta. Yellow pickups are consumables, a "
            "category rather than a grade — their share is the item-type "
            "weighting in Better Loot. Vanilla trash mobs are 27% common, 70% "
            "rare, 5% epic and 0.2% legendary; bosses never drop common at "
            "all. Leave a row blank to leave that tier alone.",
    "presets": {
        "legendaries_only": {
            "label": "Legendaries only",
            "description": "Every enemy tier drops legendaries: legendary 100% in "
                           "every row, legendary ignores the level window, the "
                           "shelved legendaries are brought in, and duplicates are "
                           "allowed so the drops never run dry. In DoW2/CR it also "
                           "allows Chaos Rising legendaries in the base campaign "
                           "(experimental).",
            "values": {
                "targets": {c: {"common": 0, "rare": 0, "epic": 0, "legendary": 100}
                            for c in CLASSES},
                "any_level_grades": ["legendary"],
                "unused_sources": ["shelved", "no_level"],
                "unused_grades": ["legendary"],
                "allow_duplicates": True,
                "duplicate_grades": ["legendary"],
                "base_campaign_grades": [],
            },
            "values_by_game": {"dow2cr": {"base_campaign_grades": ["legendary"]}},
        },
    },
    "options": {
        "targets": {
            "title": "Target mix per enemy tier (%)",
            "description": "Relative shares — they don't have to add up to 100, "
                           "they're normalised. 0 removes that grade from the "
                           "tier entirely. A row of all zeros is ignored.",
            "type": "mix_matrix", "rows": CLASSES, "cols": QUALITIES,
            "row_labels": {"chaff": "Trash mobs (regular squads)",
                           "swarm": "Horde / swarm kills",
                           "mini_boss": "Mini-bosses",
                           "boss": "Bosses",
                           "planet_boss": "Planet bosses"},
            # Columns are named by GRADE, which is unambiguous; the swatch is
            # the colour the engine prints that grade's drop message in
            # (tuning_info wargear/message_colours — the only rarity colour
            # table DOW2.exe refers to). The in-world drop beam and the
            # inventory frame are separate art per grade, so what you see on the
            # ground may read differently from the message text.
            "col_labels": {"common": "Common", "rare": "Rare",
                           "epic": "Epic", "legendary": "Legendary"},
            "col_colours": {"common": "#ffffff", "rare": "#00ff00",
                            "epic": "#007aff", "legendary": "#ff00ff"},
            "col_notes": {"common": "common — white message text",
                          "rare": "rare — green message text",
                          "epic": "epic — blue message text",
                          "legendary": "legendary — magenta message text; the "
                                       "drop beam and inventory frame are "
                                       "separate art and can look red-orange"},
            "vanilla": {"chaff": {"common": 27, "rare": 70, "epic": 5, "legendary": 0},
                        "swarm": {"common": 78, "rare": 20, "epic": 2, "legendary": 0},
                        "mini_boss": {"common": 0, "rare": 55, "epic": 34, "legendary": 11},
                        "boss": {"common": 0, "rare": 59, "epic": 36, "legendary": 5}},
            "default": {},
        },
        "unused_sources": {
            "title": "Bring unused items into the pools",
            "type": "multi", "options": UNUSED_SOURCES, "default": [],
            "option_labels": UNUSED_LABELS, "item_source": "loot_unused",
            "description": "Hundreds of items ship with no drop pool at all. "
                           "They are not all alike, so pick which kinds to use "
                           "— 'Show the items' lists exactly what each one "
                           "brings in. Shelved gear is the safe choice; enemy "
                           "loadout gear and unfinished entries are there if "
                           "you want them. Items with no level set are made "
                           "droppable at any level, since there is no level to "
                           "gate them by. Placeholders with no stats at all "
                           "(no defence, weapon or effect) are always left out.",
        },
        "unused_grades": {
            "title": "…and only these grades of them",
            "type": "multi", "options": QUALITIES, "default": QUALITIES,
            "option_labels": {"common": "Common", "rare": "Rare",
                              "epic": "Epic", "legendary": "Legendary"},
            "description": "Narrows the kinds above to particular grades — tick "
                           "only Epic and Legendary to bring in the good shelved "
                           "gear without flooding the pools with white items. "
                           "Applies only to unused items; gear that already "
                           "drops is untouched.",
        },
        "min_per_bucket": {
            "title": "Minimum variety", "type": "int", "default": 1,
            "min": 0, "max": 20,
            "description": "Never cut a grade below this many eligible items "
                           "per level and type, even if the percentages ask "
                           "for fewer. Guards against every trash drop being "
                           "the same white item.",
        },
        "any_level_grades": {
            "title": "Grades that ignore the level window",
            "type": "multi", "options": QUALITIES, "default": [],
            "description": "The game has no legendary items below level 15 and "
                           "no epics below 5, so those grades simply cannot "
                           "drop early. Ticking a grade here sets each item's "
                           "ignore_level_requirement_when_dropping flag — the "
                           "same flag vanilla uses to make consumables drop at "
                           "any level — so it becomes eligible whatever your "
                           "level. Expect to find gear you can't equip yet: the "
                           "usage requirement is separate and still applies. If a "
                           "row would otherwise drop nothing at some level, the "
                           "build ticks its grade here for you and says so.",
        },
        "allow_duplicates": {
            "title": "Allow duplicates", "type": "bool", "default": False,
            "description": "Every rare, epic and legendary item ships flagged "
                           "unique, and the game never drops a unique item you "
                           "already have. In the base game the repeatable loot is "
                           "the white 'improved' gear, so a mix with commons at 0% "
                           "runs dry late in a campaign: the good items are "
                           "collected and enemies stop dropping gear. Tick this to "
                           "clear the unique flag on the grades below, for every "
                           "item left in an enemy drop pool. Expect duplicates.",
        },
        "duplicate_grades": {
            "title": "…for these grades",
            "type": "multi", "options": ["rare", "epic", "legendary"],
            "default": ["epic", "legendary"],
            "option_labels": {"rare": "Rare", "epic": "Epic", "legendary": "Legendary"},
            "description": "Only used when Allow duplicates is ticked.",
        },
        "base_campaign_grades": {
            "title": "Chaos Rising gear in the base campaign (experimental)",
            "type": "multi", "options": ["epic", "legendary"], "default": [],
            "games": ["dow2cr"],
            "option_labels": {"epic": "Epic", "legendary": "Legendary"},
            "description": "Every legendary in DoW2/CR — and 128 epics — is flagged "
                           "for the Chaos Rising campaign only, so in the Dawn of "
                           "War II campaign none of them can drop whatever the "
                           "percentages say. Ticking a grade also allows its "
                           "Chaos Rising items (those left in an enemy drop pool) "
                           "in the base campaign. Experimental: some carry "
                           "corruption, which the base campaign has no system for.",
        },
        "types": {
            "title": "Item types to shape", "type": "multi", "options": TYPES,
            "default": TYPES,
            "description": "Consumables, ammo and stratagems are left alone.",
        },
    },
}

EXTRA_CONFIG_KEYS = ("include_unused_items",)   # retired; mapped + warned

WARNINGS: list[str] = []



# --------------------------------------------------------------------------
# build


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    changes: list[dict] = []
    targets = {c: m for c, m in (cfg.get("targets") or {}).items()
               if isinstance(m, dict)
               and sum(max(0.0, float(m.get(q, 0) or 0)) for q in QUALITIES) > 0}
    dup_grades = ([q for q in (cfg.get("duplicate_grades") or ["epic", "legendary"])
                   if q in QUALITIES] if cfg.get("allow_duplicates") else [])
    camp_grades = [q for q in (cfg.get("base_campaign_grades") or []) if q in QUALITIES]
    if camp_grades and src.game != "dow2cr":
        WARNINGS.append("'Chaos Rising gear in the base campaign' only applies to "
                        "Dawn of War II / Chaos Rising — ignored for this game.")
        camp_grades = []
    if not targets and not dup_grades and not camp_grades:
        return changes
    types = [t for t in (cfg.get("types") or TYPES) if t in TYPES]
    sources = _sources_from_cfg(cfg)
    if cfg.get("unused_sources") is None and "include_unused_items" in cfg:
        WARNINGS.append(
            "'include_unused_items' is retired — unused items are now chosen by "
            "kind. This build used " + (", ".join(sorted(sources)) if sources
                                        else "none of them") +
            ". Reopen the mod and set 'Bring unused items into the pools'.")
    grades = _grades_from_cfg(cfg)
    if sources and not grades:
        WARNINGS.append("unused items: kinds are ticked but no grades are — "
                        "no unused items were brought in.")
    items = scan(src, types, sources, grades)
    if not items:
        WARNINGS.append("loot_mix: no wargear items found for this game")
        return changes
    if sources:
        got = {}
        for i in items:
            if i.get("source"):
                got[i["source"]] = got.get(i["source"], 0) + 1
        skipped = len(_scan_mod.SKIPPED_NO_STATS)
        WARNINGS.append(
            "unused items brought in: "
            + (", ".join(f"{got.get(k, 0)} {k}" for k in sorted(sources)) or "none")
            + (f"  (grades: {', '.join(sorted(grades))})"
               if grades != set(QUALITIES) else "")
            + (f"; {skipped} left out — placeholders with no stats at all"
               if skipped else ""))
    tw = _type_weights(src)
    win = _level_window(src, out_data)
    if targets:
        p = plan(items, targets, int(cfg.get("min_per_bucket", 1)), tw,
                 [q for q in (cfg.get("any_level_grades") or []) if q in QUALITIES],
                 win)
    else:
        p = {"add": {}, "remove": {}, "keeps": {}, "agnostic": [], "notes": []}
    agnostic = set(p["agnostic"])
    WARNINGS.extend(p["notes"])
    if cfg.get("_with_loot_quality") and targets:
        WARNINGS.append(_better_loot_note(items, p))

    by_path = {i["path"]: i for i in items}
    after = finalise(items, p, duplicate_grades=dup_grades,
                     campaign_grades=camp_grades, game=src.game)
    fin = {i["path"]: i for i in after}
    touched = set(p["add"]) | set(p["remove"])
    # grades told to ignore the level window need the game's own flag set on the
    # items that stay eligible, otherwise the window still gates them
    want_any_level = {vp for vp in p["add"]
                      if by_path[vp]["quality"] in agnostic
                      or by_path[vp].get("source") == "no_level"
                      or not (1 <= by_path[vp]["level"] <= LEVEL_CAP)}
    for i in items:
        if i["quality"] in agnostic and i["pools"] & set(p["keeps"]) \
                and vp_not_dropped(i, p):
            want_any_level.add(i["path"])
    touched |= {vp for vp in want_any_level if not by_path[vp]["any_level"]}
    want_repeat = {vp for vp, i in fin.items() if by_path[vp]["unique"] and not i["unique"]}
    want_camp = {vp for vp, i in fin.items() if i["camps"] != by_path[vp]["camps"]}
    touched |= want_repeat | want_camp
    for vp in sorted(touched):
        it = by_path[vp]
        tree = src.attrib_tree(vp)
        bag = tree.children[0] if tree.children else None
        db = rbf.find(bag, "dropped_by") if bag is not None else None
        if db is None:
            continue
        before = {c.value for c in db.children if c.type == rbf.STRING} - {"none"}
        flag_changed = False
        ig = rbf.find(bag, "ignore_level_requirement_when_dropping")
        if vp in want_any_level and ig is not None and not ig.value:
            ig.value = True
            flag_changed = True
            changes.append({"file": src.attrib_label(vp),
                            "path": "ignore_level_requirement_when_dropping",
                            "old": False, "new": True,
                            "tweak": f"{it['quality']} drops at any level"})
        un = rbf.find(bag, "unique")
        if vp in want_repeat and un is not None and un.value:
            un.value = False
            flag_changed = True
            changes.append({"file": src.attrib_label(vp), "path": "unique",
                            "old": True, "new": False,
                            "tweak": f"{it['quality']} can drop again"})
        vc = rbf.find(bag, "valid_campaigns")
        if vp in want_camp and vc is not None:
            have = [c.value for c in vc.children if c.type == rbf.STRING]
            if "space_marines" not in have:
                key = next((c.key for c in vc.children if c.type == rbf.STRING),
                           "campaign")
                vc.children.append(rbf.RbfNode(key, rbf.STRING, "space_marines"))
                flag_changed = True
                changes.append({"file": src.attrib_label(vp),
                                "path": "valid_campaigns", "old": have,
                                "new": have + ["space_marines"],
                                "tweak": f"{it['quality']} allowed in the base campaign"})
        drop = p["remove"].get(vp, set())
        keep_children = [c for c in db.children
                         if not (c.type == rbf.STRING and c.value in drop)]
        db.children = keep_children
        for cls in sorted(p["add"].get(vp, set())):
            db.children.append(rbf.RbfNode("dropped_by", rbf.STRING, cls))
        # 'none' is the sentinel for "nobody drops this". Vanilla never pairs it
        # with a real pool (0 of 1004 items), so leaving it alongside one is a
        # shape the game never ships — strip it when the item becomes droppable,
        # and put a single one back if it ends up dropping from nobody.
        real = [c for c in db.children
                if c.type == rbf.STRING and c.value not in ("none",)]
        if real:
            db.children = real
        elif not any(c.type == rbf.STRING and c.value == "none"
                     for c in db.children):
            db.children.append(rbf.RbfNode("dropped_by", rbf.STRING, "none"))
        else:
            db.children = [next(c for c in db.children
                                if c.type == rbf.STRING and c.value == "none")]
        after_pools = {c.value for c in db.children if c.type == rbf.STRING} - {"none"}
        if after_pools == before and not flag_changed:
            continue
        if after_pools != before:
            changes.append({"file": src.attrib_label(vp), "path": "dropped_by",
                            "old": sorted(before) or ["(none)"],
                            "new": sorted(after_pools) or ["(none)"],
                            "tweak": f"{it['quality']} L{it['level']} {it['type']}"})
        src.write_attrib(vp, tree, out_data)

    # report what the build actually produces, as the game will roll it
    for i in after:
        if i["path"] in want_any_level:
            i["any_level"] = True
    if dup_grades:
        WARNINGS.append(f"allow duplicates: {len(want_repeat)} item(s) "
                        f"({', '.join(dup_grades)}) can now drop again after you "
                        f"have them")
    if camp_grades:
        WARNINGS.append(f"base campaign (experimental): {len(want_camp)} Chaos "
                        f"Rising item(s) ({', '.join(camp_grades)}) may now drop "
                        f"in the Dawn of War II campaign")
    if targets:
        WARNINGS.extend(shortfalls(items, after, targets, win, tw, agnostic))
    WARNINGS.extend(campaign_notes(after, targets, src.game))
    # only the tiers this mix shapes: an untouched tier is vanilla's own business
    WARNINGS.extend(repeatable_notes(after, sorted(p["keeps"]), win))
    camps = DOW2_CAMPAIGNS if src.game == "dow2cr" else ()
    for cls in p["keeps"]:
        for lv in (10, 20, 30):
            parts = [(None, after)] if not camps else \
                [(c, [i for i in after if in_campaign(i, c)]) for c in camps]
            line = []
            for c, pool in parts:
                m = project(pool, cls, lv, win, tw)
                label = f"{CAMPAIGN_LABELS[c]}: " if c else ""
                line.append(label + (" / ".join(f"{m[q]:g}% {q}" for q in QUALITIES)
                                     + f" ({m['n']} items)" if m["n"]
                                     else "NOTHING can drop (0 items)"))
            WARNINGS.append(f"{cls} at level {lv}: " + "  |  ".join(line))
    rc = campaign_counts(after, src.game)
    if rc:
        WARNINGS.append(rc)
    return changes


def _better_loot_note(items: list[dict], p: dict) -> str:
    """Name what the mix undid of Better Loot's pool openings (it runs first)."""
    lq = sys.modules.get("modules.loot_quality")
    opened = getattr(lq, "OPENED", None) or {}
    grade = {i["path"]: i["quality"] for i in items}
    total = sum(len(v) for v in opened.values())
    gone: dict[str, int] = {}
    for vp, cls in opened.items():
        n = len(set(cls) & p["remove"].get(vp, set()))
        if n:
            gone[grade.get(vp, "other")] = gone.get(grade.get(vp, "other"), 0) + n
    if not total:
        return ("Better Loot is on as well; it opened no drop pools this build, "
                "so there was nothing for the mix to undo.")
    n = sum(gone.values())
    return (f"Better Loot opened {total} drop pools; Loot Rarity Mix then removed "
            f"{n} of them to hit your percentages"
            + (" (" + ", ".join(f"{k} {v}" for k, v in sorted(gone.items())) + ")"
               if n else "")
            + ". The mix is the final word — the lines below are what the game "
              "will roll.")
