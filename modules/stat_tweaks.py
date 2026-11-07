"""Stat Tweaks module — bulk numeric adjustments applied to chosen entities.

Inverted workflow vs Generic Overrides: define the adjustment once
(+3 / x1.5 / =40), then assign any number of weapons/armour pieces to it
(drag & drop in the UI).

Config:
    {"tweaks": [
        {"stat": "weapon_damage", "op": "add", "value": 3,
         "targets": ["weapons/weapon/campaign/npc/race_marine/sm_plasma_cannon.rbf", ...]}
    ]}

Every stat below was verified against extracted game data.
Values are clamped to the stat's minimum; results recorded per file in the
manifest like every other module.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

GAMES = ["dow2cr", "retribution"]

# stat key -> definition. `root` limits the file tree, `path` is the indexed
# node path inside the file, `where` optionally filters files by a field value.
STATS = {
    "weapon_damage": {
        "title": "Weapon damage", "unit": "hp/hit",
        "root": "weapons/weapon", "path": "weapon_bag/damage_hp",
        "kind": "float", "min": 0.0,
    },
    "weapon_cooldown": {
        "title": "Weapon cooldown", "unit": "s (lower = faster)",
        "root": "weapons/weapon", "path": "weapon_bag/cooldown",
        "kind": "float", "min": 0.0,
    },
    "weapon_range": {
        "title": "Weapon max range", "unit": "m",
        "root": "weapons/weapon", "path": "weapon_bag/range/max",
        "kind": "float", "min": 1.0,
    },
    "weapon_penetration": {
        "title": "Armour penetration", "unit": "",
        "root": "weapons/weapon", "path": "weapon_bag/armour_penetration",
        "kind": "int", "min": 0,
    },
    "weapon_moving_accuracy": {
        "title": "Moving accuracy multiplier", "unit": "x",
        "root": "weapons/weapon", "path": "weapon_bag/moving/accuracy_multiplier",
        "kind": "float", "min": 0.0,
    },
    "armour_defence": {
        "title": "Armour defence", "unit": "",
        "root": "wargear/wargear", "path": "wargear/defence",
        "kind": "int", "min": 0,
        "where": ("wargear/type", "armour"),
    },
}
OPS = {"add": "+", "mul": "×", "set": "="}

SCHEMA = {
    "module": "stat_tweaks",
    "title": "Stat Tweaks (bulk)",
    "target_file": "simulation/attrib/{weapons,wargear}/**",
    "note": "Define an adjustment once, then drag the weapons or armour it "
            "should apply to onto it.",
    "options": {
        "tweaks": {
            "title": "Adjustments",
            "description": "Each adjustment applies one operation to one stat "
                           "across every entity assigned to it.",
            "type": "stat_tweaks",
            "stats": {k: {kk: vv for kk, vv in v.items() if kk != "where"}
                      for k, v in STATS.items()},
            "default": [],
        },
    },
}

WARNINGS: list[str] = []


def list_targets(src, stat: str) -> list[dict]:
    """All entities that carry this stat, with current values (for the UI)."""
    sdef = STATS[stat]
    out = []
    for vp in src.attrib_paths(sdef["root"]):
        try:
            t = src.attrib_tree(vp)
        except Exception:
            continue
        if "where" in sdef:
            wpath, wval = sdef["where"]
            n = rbf.find_indexed(t, wpath)
            if n is None or n.value != wval:
                continue
        node = rbf.find_indexed(t, sdef["path"])
        if node is None or node.type not in (rbf.FLOAT, rbf.INT):
            continue
        parts = vp.split("/")
        group = "campaign" if "campaign" in parts else ("pvp" if "pvp" in parts else parts[2] if len(parts) > 2 else "")
        out.append({"path": vp, "name": parts[-1].removesuffix(".rbf"),
                    "value": round(node.value, 3), "group": group,
                    "campaign": ("xp1" if "/xp1/" in vp.lower() else
                                 "space_marines" if group == "campaign" else None)})
    return out


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    tweaks = cfg.get("tweaks", []) or []
    if not isinstance(tweaks, list) or not all(isinstance(t, dict) for t in tweaks):
        raise ValueError("stat_tweaks: 'tweaks' must be a list of "
                         "{stat, op, value, targets} entries")
    changes: list[dict] = []
    # group work per file so one file with several tweaks is written once
    per_file: dict[str, list[tuple[dict, dict]]] = {}
    for tw in tweaks:
        if tw.get("stat") not in STATS:
            raise ValueError(f"stat_tweaks: unknown stat {tw.get('stat')!r}")
        if tw.get("op") not in OPS:
            raise ValueError(f"stat_tweaks: unknown op {tw.get('op')!r}")
        for target in tw.get("targets", []):
            per_file.setdefault(target.replace("\\", "/"), []).append((tw, STATS[tw["stat"]]))

    for rel, work in sorted(per_file.items()):
        try:
            tree = src.attrib_tree(rel)
        except (KeyError, FileNotFoundError):
            raise ValueError(f"stat_tweaks: target not found: {rel}")
        touched = False
        for tw, sdef in work:
            node = rbf.find_indexed(tree, sdef["path"])
            if node is None:
                WARNINGS.append(f"{rel}: stat path {sdef['path']} missing (skipped)")
                continue
            old = node.value
            v = float(tw["value"])
            new = old + v if tw["op"] == "add" else old * v if tw["op"] == "mul" else v
            new = max(sdef["min"], new)
            if sdef["kind"] == "int":
                new = int(new + 0.5)   # half-up, matches the UI preview
            else:
                new = round(float(new), 4)
            if new == old:
                continue
            node.value = new
            touched = True
            changes.append({"file": src.attrib_label(rel),
                            "path": sdef["path"],
                            "old": old, "new": new,
                            "tweak": f"{sdef['title']} {OPS[tw['op']]}{tw['value']}"})
        if touched:
            src.write_attrib(rel, tree, out_data)
    return changes
