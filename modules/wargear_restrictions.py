"""Wargear Restrictions module — remove level gates / broaden hero access.

Operates on: simulation/attrib/wargear/wargear/campaign/playable/** (RBF)

Mechanics (knowledge/systems.json → wargear_items):
- usage level gate  = requirements/required_leveling/level_threshold
- hero restriction  = required_squad_type type_list entries (OR within a list,
  AND between requirement entries). Broadening = adding squad types to
  existing type_lists; we never add new requirement entries (that would
  narrow, not broaden).
- item `level` field is left alone: it drives DROP pools, not usage.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

HERO_SQUAD_TYPES = [
    "force_commander", "fc_terminator", "tactical_marine", "tac_terminator",
    "devastator_marine", "deva_terminator", "assault_marine",
    "assault_terminator", "scout_marine", "tech_marine", "librarian",
    "dreadnought",
]
ITEM_TYPES = ["weapon", "armour", "accessory", "commander_accessory"]

GAMES = ["dow2cr"]

SCHEMA = {
    "module": "wargear_restrictions",
    "title": "Expanded Wargear (restrictions)",
    "target_file": "simulation/attrib/wargear/wargear/campaign/playable/**",
    "options": {
        "remove_level_restrictions": {
            "title": "Remove level restrictions",
            "description": "Sets every campaign item's usage level gate to 1. "
                           "Drop-pool levels are untouched, so loot progression is preserved — "
                           "you just get to USE anything you find immediately.",
            "type": "bool", "default": False,
        },
        "grant_access": {
            "title": "Cross-hero equipment access",
            "description": "Let heroes equip item categories normally closed to them "
                           "(adds the hero's squad type to those items' allow-lists). "
                           "Conditions tied to upgrades (e.g. weapon specialisations) still apply. "
                           "WARNING — terminator armour: do NOT put Tarkus in terminator "
                           "armour before the final Idranel mission. That mission re-equips "
                           "him into terminator armour, and the game hits a fatal error if "
                           "he is already wearing one — equip it only after that mission.",
            "type": "access_matrix",
            "rows": HERO_SQUAD_TYPES,
            "cols": ITEM_TYPES,
            "default": {},
        },
    },
}


WARNINGS: list[str] = []


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    changes: list[dict] = []
    remove_levels = bool(cfg.get("remove_level_restrictions"))
    grant: dict[str, list[str]] = cfg.get("grant_access", {}) or {}
    if not isinstance(grant, dict):
        raise ValueError("wargear_restrictions: 'grant_access' must be a mapping "
                         "of hero squad type -> [item types]")
    # invert: item_type -> squad types to add
    for st in sorted(set(grant) - set(HERO_SQUAD_TYPES)):
        WARNINGS.append(f"grant_access: unknown hero squad type {st!r} (skipped) "
                        "— valid: " + ", ".join(HERO_SQUAD_TYPES))
    add_for_type: dict[str, list[str]] = {}
    for st, types in grant.items():
        if st not in HERO_SQUAD_TYPES:
            continue
        if not isinstance(types, (list, tuple)):
            raise ValueError(f"wargear_restrictions: grant_access/{st} must be "
                             "a list of item types")
        for t in types:
            if t not in ITEM_TYPES:
                WARNINGS.append(f"grant_access/{st}: unknown item type {t!r} "
                                "(skipped) — valid: " + ", ".join(ITEM_TYPES))
                continue
            add_for_type.setdefault(t, []).append(st)
    if not remove_levels and not add_for_type:
        return changes

    for vp in src.attrib_paths("wargear/wargear/campaign/playable"):
        t = src.attrib_tree(vp)
        bag = t.children[0]
        modified = []
        req = rbf.find(bag, "requirements")
        item_type = (rbf.find(bag, "type").value
                     if rbf.find(bag, "type") is not None else None)

        if remove_levels and req is not None:
            for path, n in rbf.walk(req):
                if n.key == "level_threshold" and n.type == rbf.INT and n.value > 1:
                    modified.append({"path": f"requirements/{path}", "old": n.value, "new": 1})
                    n.value = 1

        adds = add_for_type.get(item_type, []) if "race_marine" in vp else []
        if adds and req is not None:
            # collect every required_squad_type type_list in the tree
            lists = [n for path, n in rbf.walk(req)
                     if n.key == "type_list" and n.type == rbf.TABLE
                     and path.split("/")[-2].startswith("required_squad_type")]
            # only broaden items that HAVE a squad restriction
            for tl in lists:
                existing = {c.value for c in tl.children}
                for st in adds:
                    if st not in existing:
                        tl.children.append(rbf.RbfNode("squad_type", rbf.STRING, st))
                        modified.append({"path": "requirements/.../type_list",
                                         "old": None, "new": f"+{st}"})

        if modified:
            src.write_attrib(vp, t, out_data)
            label = src.attrib_label(vp)
            for m in modified:
                changes.append({"file": label, **m})
    return changes
