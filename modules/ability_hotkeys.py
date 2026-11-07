"""Ability Hotkeys module — move ability/item keys that keydefaults can't.

Ability taskbar keys resolve in two layers:
  ability file ui_info/hotkey_name -> named binding in keydefaults.lua,
  or, if the name is a single letter, that literal key.
The Controls tab handles the named-binding layer. This module handles the
attrib layer: abilities whose hotkey_name IS a literal letter (six playable
campaign abilities ship with 's' — Rally, Berserker Fury, Chapter's Fury,
Wrath of the Blood Ravens, Avitus's focused-fire toggle) which collide with
WASD camera. Remapping them means editing the ability files, so it ships as
part of a mod.

Config: {"remap": {"s": "v"}}   # letter -> letter, campaign/playable only
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

GAMES = ["dow2cr", "retribution"]

PREFIXES = {"dow2cr": "ability/campaign/playable",
            "retribution": "ability/xp2/campaign"}

SCHEMA = {
    "module": "ability_hotkeys",
    "title": "Ability Hotkeys",
    "target_file": "simulation/attrib/ability/campaign/playable/**",
    "note": "Some ability keys are baked into the ability files as literal "
            "letters rather than named bindings (DoW2/CR ships six playable "
            "abilities on 'S'; Retribution has over a hundred on 'S' and 'G' "
            "plus one each on 'W' and 'D'). This remaps those letters — "
            "everything ELSE, including Taunt and Battle Cry, is a named "
            "binding handled by the Controls tab, whose WASD preset clears "
            "all of W/A/S/D. Pair the two for a fully clean WASD setup.",
    "options": {
        "remap": {
            "title": "Letter remaps",
            "description": "Move every playable ability using the left letter "
                           "onto the right letter (e.g. s → v frees S for "
                           "camera-down).",
            "type": "map[str]",
            # every letter observed on playable campaign abilities in either
            # game (census in knowledge/systems.json); w/d/q are Retribution
            "keys": ["s", "g", "h", "w", "d", "c", "e", "f", "k", "p", "q",
                     "r", "y"],
            "default": {"s": "v"},
        },
    },
}

WARNINGS: list[str] = []


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    if not isinstance(cfg.get("remap") or {}, dict):
        raise ValueError("ability_hotkeys: 'remap' must be a mapping of "
                         "old key -> new key")
    remap = {str(k).lower(): str(v).lower()
             for k, v in (cfg.get("remap", {}) or {}).items() if v}
    for k, v in remap.items():
        if len(k) != 1 or len(v) != 1 or not v.isalpha():
            raise ValueError(f"ability_hotkeys: bad remap {k!r} -> {v!r} "
                             "(single letters only)")
    changes: list[dict] = []
    if not remap:
        return changes
    used: set[str] = set()
    for vp in src.attrib_paths(PREFIXES[src.game]):
        try:
            t = src.attrib_tree(vp)
        except Exception:
            continue
        touched = False
        for path, n in rbf.walk(t):
            if n.key == "hotkey_name" and n.type == rbf.STRING \
                    and n.value and n.value.strip().lower() in remap:
                old = n.value
                new = remap[old.strip().lower()]
                used.add(old.strip().lower())
                n.value = new
                touched = True
                changes.append({"file": src.attrib_label(vp),
                                "path": f"{path}",
                                "old": old, "new": new,
                                "tweak": f"hotkey {old.strip().upper()} -> {new.upper()}"})
        if touched:
            src.write_attrib(vp, t, out_data)
    for k in sorted(set(remap) - used):
        WARNINGS.append(f"no ability currently uses hotkey '{k.upper()}' — "
                        f"remap {k.upper()} -> {remap[k].upper()} did nothing")
    return changes
