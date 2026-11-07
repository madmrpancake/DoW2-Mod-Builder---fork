"""Loot Quality module — control the GRADE of what drops, not just how often.

How the game grades loot (verified against game data):
  * every wargear item has quality (common/rare/epic/legendary) and level
  * an item can only drop from the enemy classes listed in its dropped_by
    pool: chaff (regular squads), mini_boss, swarm, boss, mission_reward...
    Vanilla pool census (campaign playable items):
        common:    chaff 125, swarm 66            (regular-kill fodder)
        rare:      chaff 320, mini_boss 116, boss 226, mission_reward 198
        epic:      chaff 21,  mini_boss 72,  boss 137, mission_reward 75
        legendary: chaff 1,   mini_boss 24,  boss 21   (never regular kills)
  * the drop generator then rolls an item whose level is within
    [squad level + min_offset, squad level + max_offset]  (vanilla -2..+2,
    absolute cap 30) — tuning/tuning_info.rbf wargear section.

So two levers:
  1. pool opening — add drop classes to higher-quality items' dropped_by
     (e.g. let epics and legendaries drop from regular kills)
  2. level window — shift the drop level offsets so gear rolls above your
     level instead of around it

Config:
    {"open_pools": {"rare": ["chaff"], "epic": ["chaff","mini_boss"],
                    "legendary": ["mini_boss"]},
     "level_min_offset": -2, "level_max_offset": 2}
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

GAMES = ["dow2cr", "retribution"]

QUALITIES = ["rare", "epic", "legendary"]
POOLS = ["chaff", "mini_boss", "swarm"]
TUNING = "tuning/tuning_info.rbf"
WG_PREFIXES = {"dow2cr": "wargear/wargear/campaign/playable",
               "retribution": "wargear/wargear/xp2/campaign"}

SCHEMA = {
    "module": "loot_quality",
    "title": "Loot Quality (grades)",
    "target_file": "simulation/attrib/tuning/tuning_info.rbf + wargear/**",
    "note": "Vanilla locks legendaries to bosses/mini-bosses and rolls drops "
            "within ±2 levels of your squads. Open the drop pools per quality "
            "and widen the level window to change what grade of loot appears.",
    "options": {
        "open_pools": {
            "title": "Let quality drop from…",
            "description": "Tick an enemy class to ADD it to every item of "
                           "that quality (existing pools are kept). chaff = "
                           "regular squads, swarm = horde kills.",
            "type": "access_matrix", "rows": QUALITIES, "cols": POOLS,
            "row_labels": {"rare": "Rare (green)", "epic": "Epic (blue)",
                           "legendary": "Legendary (purple)"},
            "col_labels": {"chaff": "Regular squads", "mini_boss": "Mini-bosses",
                           "swarm": "Horde kills"},
            "default": {},
        },
        "revive_lost_items": {
            "title": "Revive lost content", "type": "bool", "default": False,
            "description": "Hundreds of finished items ship with NO drop "
                           "pool and can never appear (227 in DoW2/CR incl. "
                           "31 legendaries). This gives them standard pools "
                           "for their quality so they enter the loot game."},
        "level_min_offset": {
            "title": "Drop level window min", "type": "int", "default": -2,
            "min": -10, "max": 10, "vanilla": -2,
            "description": "Lower bound of drop level relative to squad "
                           "level. Raise to 0 to stop under-levelled drops."},
        "level_max_offset": {
            "title": "Drop level window max", "type": "int", "default": 2,
            "min": 0, "max": 15, "vanilla": 2,
            "description": "Upper bound of drop level relative to squad "
                           "level. Raise for above-level gear (absolute cap "
                           "is level 30)."},
    },
}

WARNINGS: list[str] = []


# pools this module opened in the current build: {item vpath: {pool, ...}}
OPENED: dict[str, set] = {}


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS, OPENED
    WARNINGS = []
    OPENED = {}
    changes: list[dict] = []
    open_pools = cfg.get("open_pools", {}) or {}
    if not isinstance(open_pools, dict):
        raise ValueError("loot_quality: 'open_pools' must be a mapping of "
                         "quality -> [pool names]")
    revive = bool(cfg.get("revive_lost_items", False))
    lo = int(cfg.get("level_min_offset", -2))
    hi = int(cfg.get("level_max_offset", 2))
    if lo > hi:
        raise ValueError("loot_quality: level_min_offset > level_max_offset")

    # ---- tuning level window --------------------------------------------
    t = src.attrib_tree(TUNING)
    for key, new in (("wargear/wargear_drop_level_minimum_offset", lo),
                     ("wargear/wargear_drop_level_maximum_offset", hi)):
        n = rbf.find_indexed(t, key)
        if n is None:
            WARNINGS.append(f"tuning: {key} missing")
            continue
        if n.value != new:
            changes.append({"file": src.attrib_label(TUNING), "path": key,
                            "old": n.value, "new": new,
                            "tweak": f"drop level window {lo}..{hi}"})
            n.value = new
    if any(c["file"] == src.attrib_label(TUNING) for c in changes):
        src.write_attrib(TUNING, t, out_data)

    # default pools per quality for revived items
    REVIVE_POOLS = {"common": ["chaff", "swarm"], "rare": ["chaff", "mini_boss"],
                    "epic": ["mini_boss", "boss"], "legendary": ["boss", "mini_boss"]}
    # ---- pool opening ----------------------------------------------------
    for q in sorted(set(open_pools) - set(QUALITIES)):
        WARNINGS.append(f"open_pools: unknown quality {q!r} (skipped) — valid: "
                        + ", ".join(QUALITIES))
    for q, pools in open_pools.items():
        if q in QUALITIES:
            if not isinstance(pools, (list, tuple)):
                raise ValueError(f"loot_quality: open_pools/{q} must be a list "
                                 "of pool names")
            for p in pools:
                if p not in POOLS:
                    WARNINGS.append(f"open_pools/{q}: unknown pool {p!r} "
                                    "(skipped) — valid: " + ", ".join(POOLS))
    wanted = {q: [p for p in pools if p in POOLS]
              for q, pools in open_pools.items() if q in QUALITIES}
    wanted = {q: p for q, p in wanted.items() if p}
    if wanted or revive:
        for vp in src.attrib_paths(WG_PREFIXES[src.game]):
            try:
                it = src.attrib_tree(vp)
            except Exception:
                continue
            bag = it.children[0] if it.children else None
            if bag is None:
                continue
            q = rbf.find(bag, "quality")
            ty = rbf.find(bag, "type")
            if q is None:
                continue
            if ty is not None and ty.value not in ("weapon", "armour",
                                                   "accessory", "commander_accessory"):
                continue
            db = rbf.find(bag, "dropped_by")
            if db is None:
                continue
            have = {c.value for c in db.children if c.type == rbf.STRING} - {"none"}
            add = []
            nm = rbf.find(bag, "name")
            ic = rbf.find_indexed(it, "wargear/ui/icon_name")
            complete = bool(nm is not None and nm.value and ic is not None and ic.value)
            if q.value in wanted and (have or complete):
                # an item with no pool at all only comes in if it looks finished
                # (named + icon), the same test revive uses — otherwise opening
                # epic pools also drags in unfinished placeholders (1.2.6)
                add += [p for p in wanted[q.value] if p not in have]
            if revive and not have and q.value in REVIVE_POOLS:
                # lost item: only revive complete-looking ones (named + icon)
                if complete:
                    add += [p for p in REVIVE_POOLS[q.value] if p not in have and p not in add]
            if not add:
                continue
            for p in add:
                db.children.append(rbf.RbfNode("dropped_by", rbf.STRING, p))
            OPENED[vp] = set(add)          # loot_mix reports what it undoes
            changes.append({"file": src.attrib_label(vp), "path": "dropped_by",
                            "old": sorted(have), "new": sorted(have | set(add)),
                            "tweak": f"{q.value} +{'+'.join(add)}"})
            src.write_attrib(vp, it, out_data)
    return changes
