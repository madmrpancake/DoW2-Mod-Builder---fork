"""Loot Rarity Mix — reading wargear from the game (scan, census, stats, tuning)."""
from __future__ import annotations
from pathlib import Path

from .common import (rbf, QUALITIES, TYPES, UNUSED_SOURCES, UNUSED_LABELS,
                     WG_PREFIXES, LEVEL_CAP, campaign_of, classify_unused)
from .rules import zero_stat

# unused items the last scan() left out because they carry no stats at all
SKIPPED_NO_STATS: list[str] = []


def scan(src, types=None, include_unused=True, grades=None) -> list[dict]:
    """Every droppable wargear item with its grade, level and current pools.

    include_unused may be a bool (all buckets / none) or a set of bucket names
    from UNUSED_SOURCES, in which case an item with no pool is kept only when
    its bucket is enabled.
    """
    types = set(types or TYPES)
    if isinstance(include_unused, bool):
        wanted_src = set(UNUSED_SOURCES) if include_unused else set()
    else:
        wanted_src = {s for s in include_unused if s in UNUSED_SOURCES}
    wanted_grades = set(QUALITIES) if grades is None else \
        {q for q in grades if q in QUALITIES}
    out = []
    SKIPPED_NO_STATS.clear()
    for vp in src.attrib_paths(WG_PREFIXES[src.game]):
        try:
            tree = src.attrib_tree(vp)
        except Exception:
            continue
        bag = tree.children[0] if tree.children else None
        if bag is None:
            continue
        q = rbf.find(bag, "quality")
        ty = rbf.find(bag, "type")
        lv = rbf.find(bag, "level")
        db = rbf.find(bag, "dropped_by")
        if q is None or ty is None or db is None:
            continue
        if q.value not in QUALITIES or ty.value not in types:
            continue
        pools = {c.value for c in db.children if c.type == rbf.STRING} - {"none"}
        level = int(lv.value) if lv is not None else 0
        bucket = None
        if not pools:
            nm = rbf.find(bag, "name")
            ic = rbf.find_indexed(tree, "wargear/ui/icon_name")
            bucket = classify_unused(vp, level,
                                     bool(nm is not None and nm.value),
                                     bool(ic is not None and ic.value))
            if bucket not in wanted_src or q.value not in wanted_grades:
                continue
            if zero_stat(bag):              # placeholder: nothing to give a hero
                SKIPPED_NO_STATS.append(vp)
                continue
        ig = rbf.find(bag, "ignore_level_requirement_when_dropping")
        un = rbf.find(bag, "unique")
        vc = rbf.find(bag, "valid_campaigns")
        out.append({"path": vp, "quality": q.value, "type": ty.value,
                    "level": level, "source": bucket,
                    "pools": pools, "any_level": bool(ig.value) if ig else False,
                    "unique": bool(un.value) if un is not None else True,
                    "camps": sorted(c.value for c in vc.children
                                    if c.type == rbf.STRING) if vc is not None else []})
    return out


def item_stats(src, vpath: str) -> dict:
    """The numbers the game shows for one wargear item.

    Armour and accessories carry their own defence; a weapon item points at the
    weapon blueprint that holds damage, range and cooldown, so follow it.
    """
    out = {"path": vpath, "stats": [], "icon": None, "weapons": []}
    try:
        tree = src.attrib_tree(vpath)
    except Exception as e:
        out["error"] = f"could not read {vpath}: {type(e).__name__}"
        return out
    g = lambda ip: (rbf.find_indexed(tree, ip).value
                    if rbf.find_indexed(tree, ip) is not None else None)
    ic = rbf.find_indexed(tree, "wargear/ui/icon_name")
    out["icon"] = ic.value if ic is not None and ic.value else None
    for label, ip, unit in (("Defence", "wargear/defence", ""),
                            ("Requires level",
                             "wargear/requirements/required_leveling/level_threshold", "")):
        v = g(ip)
        if v:
            out["stats"].append({"label": label, "value": v, "unit": unit})
    # weapon blueprints referenced by this item
    for path, n in rbf.walk(tree):
        if n.key == "weapon" and n.type == rbf.STRING and n.value:
            wvp = n.value.replace("\\", "/") + ".rbf"
            try:
                wt = src.attrib_tree(wvp)
            except Exception:
                continue
            wg = lambda ip: (rbf.find_indexed(wt, ip).value
                             if rbf.find_indexed(wt, ip) is not None else None)
            dmg, cd = wg("weapon_bag/damage_hp"), wg("weapon_bag/cooldown")
            rows = []
            for label, ip, unit in (("Damage", "weapon_bag/damage_hp", ""),
                                    ("Range", "weapon_bag/range/max", "m"),
                                    ("Cooldown", "weapon_bag/cooldown", "s"),
                                    ("Armour penetration",
                                     "weapon_bag/armour_penetration", ""),
                                    ("Accuracy moving",
                                     "weapon_bag/moving/accuracy_multiplier", "x")):
                v = wg(ip)
                if v:
                    rows.append({"label": label, "value": round(float(v), 3),
                                 "unit": unit})
            if dmg and cd:                    # the figure the game's tooltip shows
                rows.insert(1, {"label": "Damage per second",
                                "value": round(float(dmg) / float(cd), 1), "unit": ""})
            if rows:
                out["weapons"].append({"id": wvp.split("/")[-1][:-4], "stats": rows})
    return out


def unused_census(src, types=None) -> dict:
    """Every item with no drop pool, grouped by bucket — for the UI list."""
    types = set(types or TYPES)
    buckets = {k: [] for k in UNUSED_SOURCES}
    for vp in src.attrib_paths(WG_PREFIXES[src.game]):
        try:
            tree = src.attrib_tree(vp)
        except Exception:
            continue
        bag = tree.children[0] if tree.children else None
        if bag is None:
            continue
        q = rbf.find(bag, "quality")
        ty = rbf.find(bag, "type")
        db = rbf.find(bag, "dropped_by")
        if q is None or ty is None or db is None:
            continue
        if q.value not in QUALITIES or ty.value not in types:
            continue
        if {c.value for c in db.children if c.type == rbf.STRING} - {"none"}:
            continue
        lv = rbf.find(bag, "level")
        level = int(lv.value) if lv is not None else 0
        nm = rbf.find(bag, "name")
        ic = rbf.find_indexed(tree, "wargear/ui/icon_name")
        b = classify_unused(vp, level, bool(nm is not None and nm.value),
                            bool(ic is not None and ic.value))
        gv = lambda ip: (rbf.find_indexed(tree, ip).value
                         if rbf.find_indexed(tree, ip) is not None else None)
        buckets[b].append({"path": vp, "id": vp.split("/")[-1][:-4],
                           "campaign": campaign_of(vp),
                           # the ids the game itself prints in the item tooltip
                           "stat_ids": [int(n.value) for pth, n in rbf.walk(tree)
                                        if pth.endswith("basic_statistics_strings/statistic")
                                        and isinstance(n.value, (int, float)) and n.value],
                           "bonus_ids": [int(n.value) for pth, n in rbf.walk(tree)
                                         if pth.endswith("bonus_statistics_strings/statistic")
                                         and isinstance(n.value, (int, float)) and n.value],
                           "desc_id": gv("wargear/description_strings/description"),
                           "defence": gv("wargear/defence"),
                           "req_level": gv("wargear/requirements/required_leveling/level_threshold"),
                           "quality": q.value, "type": ty.value, "level": level,
                           "name_id": int(nm.value) if nm is not None
                                      and isinstance(nm.value, (int, float)) else None})
    for v in buckets.values():
        v.sort(key=lambda i: (i["quality"], -i["level"], i["id"]))
    grades = {k: {q: sum(1 for i in v if i["quality"] == q) for q in QUALITIES}
              for k, v in buckets.items()}
    return {"sources": UNUSED_SOURCES, "labels": UNUSED_LABELS, "buckets": buckets,
            "qualities": QUALITIES, "grades": grades,
            "counts": {k: len(v) for k, v in buckets.items()}}


def _type_weights(src) -> dict:
    """wargear_type_drop_probabilities — how the game picks the item type."""
    try:
        t = src.attrib_tree("tuning/tuning_info.rbf")
        n = rbf.find_indexed(t, "wargear/wargear_type_drop_probabilities")
        return {c.key: float(c.value) for c in (n.children if n else [])
                if isinstance(c.value, (int, float))}
    except Exception:
        return {}


def _level_window(src, out_data: Path) -> tuple:
    """The window in force for this build — reads whatever another module
    (Better Loot / Loot Quality) has already written this run."""
    try:
        t = src.attrib_tree("tuning/tuning_info.rbf")
        lo = rbf.find_indexed(t, "wargear/wargear_drop_level_minimum_offset")
        hi = rbf.find_indexed(t, "wargear/wargear_drop_level_maximum_offset")
        return (int(lo.value) if lo else -2, int(hi.value) if hi else 2)
    except Exception:
        return (-2, 2)
