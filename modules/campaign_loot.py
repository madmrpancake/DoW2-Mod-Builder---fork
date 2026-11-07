"""Campaign Loot module — configuration schema + deterministic transform.

Operates on: simulation/attrib/tuning/tuning_info.rbf  (section tuning_bag/wargear)

Every option maps 1:1 onto discovered game data (knowledge/systems.json).
The transform takes the ORIGINAL rbf tree + a config dict and returns the
modified tree plus a change manifest; it never mutates files in place.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

AFFECTED_FILE = "simulation/attrib/tuning/tuning_info.rbf"
GAMES = ["dow2cr", "retribution"]   # same tuning_bag/wargear section in both

# Enemy classes whose per-kill drop chance is a *chance* (0..1). boss classes
# are already 1.0 in vanilla; multiplying them is harmless but pointless.
DROP_CLASSES = ["chaff", "mini_boss", "swarm", "boss", "planet_boss"]

SCHEMA = {
    "module": "campaign_loot",
    "title": "Better Loot",
    "target_file": AFFECTED_FILE,
    "options": {
        "drop_chance_multiplier": {
            "title": "Loot quantity multiplier",
            "description": "Multiplies the per-kill wargear drop chance for "
                           "normal enemies (chaff/swarm/mini-boss). Capped at 1.0 (100%).",
            "type": "float", "default": 1.0, "min": 0.0, "max": 35.0,
            "game_path": "wargear/wargear_drop_probabilities/{class}",
            "vanilla": {"chaff": 0.03, "swarm": 0.01, "mini_boss": 0.04,
                        "boss": 1.0, "planet_boss": 1.0},
        },
        "drop_chance_overrides": {
            "title": "Per-class drop chance overrides",
            "description": "Explicit chance (0..1) per enemy class; wins over the multiplier.",
            "type": "map[float]", "default": {}, "keys": DROP_CLASSES,
            "game_path": "wargear/wargear_drop_probabilities/{class}",
        },
        "type_weight_overrides": {
            "title": "Item-type weighting",
            "description": "Relative weights of dropped item types "
                           "(armour/weapon/accessory/...). Raise accessory or lower "
                           "consumable weights to reduce low-value drops.",
            "type": "map[float]", "default": {},
            "keys": ["armour", "accessory", "commander_accessory", "weapon",
                     "consumable", "expendable", "explosives", "medical",
                     "stratagems", "ammo"],
            "game_path": "wargear/wargear_type_drop_probabilities/{type}",
            "vanilla": {"armour": 2.2, "accessory": 0.4, "commander_accessory": 0.4,
                        "weapon": 2.0, "consumable": 0.5, "expendable": 0.5,
                        "explosives": 1.0, "medical": 1.2, "stratagems": 0.3, "ammo": 1.0},
        },
        "drop_level_min_offset": {
            "title": "Drop level window (below player level)",
            "description": "How far below the hero level dropped items may roll. Vanilla -2.",
            "type": "int", "default": -2, "min": -30, "max": 0,
            "game_path": "wargear/wargear_drop_level_minimum_offset",
        },
        "drop_level_max_offset": {
            "title": "Drop level window (above player level)",
            "description": "How far above the hero level dropped items may roll. Vanilla +2.",
            "type": "int", "default": 2, "min": 0, "max": 30,
            "game_path": "wargear/wargear_drop_level_maximum_offset",
        },
    },
}


def apply(src, out_data, cfg) -> list[dict]:
    """Read pristine tree from the game archives via GameSource, transform,
    stage into the mod output. Works for BOTH games (classic RBF / rb2)."""
    tree = src.attrib_tree("tuning/tuning_info.rbf")
    changes = transform(tree, cfg)
    if changes:
        src.write_attrib("tuning/tuning_info.rbf", tree, out_data)
        label = src.attrib_label("tuning/tuning_info.rbf")
        for c in changes:
            c["file"] = label
    return changes


WARNINGS: list[str] = []


def transform(tree: "rbf.RbfNode", config: dict) -> list[dict]:
    """Apply config to a loaded tuning_info tree. Returns change manifest."""
    global WARNINGS
    WARNINGS = []
    changes: list[dict] = []
    wg = rbf.find(tree, "wargear")
    if wg is None:
        raise ValueError("tuning_info: wargear section not found")

    def set_num(node, new, path):
        old = node.value
        new = round(float(new), 6) if node.type == rbf.FLOAT else int(new)
        if node.type == rbf.FLOAT:
            node.value = float(new)
        else:
            node.value = int(new)
        if old != node.value:
            changes.append({"path": path, "old": old, "new": node.value})

    mult = float(config.get("drop_chance_multiplier", 1.0))
    overrides = config.get("drop_chance_overrides", {}) or {}
    if not isinstance(overrides, dict) \
            or not isinstance(config.get("type_weight_overrides") or {}, dict):
        raise ValueError("campaign_loot: the override options must be mappings "
                         "of name -> value")
    probs = rbf.find(wg, "wargear_drop_probabilities")
    for c in probs.children:
        if c.key in overrides:
            set_num(c, min(1.0, max(0.0, float(overrides[c.key]))),
                    f"wargear/wargear_drop_probabilities/{c.key}")
        elif mult != 1.0 and c.key in ("chaff", "swarm", "mini_boss"):
            set_num(c, min(1.0, c.value * mult),
                    f"wargear/wargear_drop_probabilities/{c.key}")

    for k in sorted(set(overrides) - {c.key for c in probs.children}):
        WARNINGS.append(f"drop_chance_overrides: unknown enemy class {k!r} (skipped)")

    tw = config.get("type_weight_overrides", {}) or {}
    if tw:
        weights = rbf.find(wg, "wargear_type_drop_probabilities")
        for c in weights.children:
            if c.key in tw:
                set_num(c, max(0.0, float(tw[c.key])),
                        f"wargear/wargear_type_drop_probabilities/{c.key}")
        for k in sorted(set(tw) - {c.key for c in weights.children}):
            WARNINGS.append(f"type_weight_overrides: unknown type {k!r} (skipped)")

    for opt, key in (("drop_level_min_offset", "wargear_drop_level_minimum_offset"),
                     ("drop_level_max_offset", "wargear_drop_level_maximum_offset")):
        if opt in config:
            node = rbf.find(wg, key)
            set_num(node, int(config[opt]), f"wargear/{key}")

    return changes
