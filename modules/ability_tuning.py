"""Ability Tuning module — global multipliers over your abilities.

Verified structure: every ability file carries an ability_bag
with energy_cost (172 playable campaign abilities > 0) and recharge_time
(251 > 0). This module scales both across ability/campaign/playable/** —
player-side only, enemy abilities untouched.

Config: {"energy_cost_multiplier": 0.7, "recharge_multiplier": 0.7}
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
    "module": "ability_tuning",
    "title": "Ability Tuning",
    "target_file": "simulation/attrib/ability/campaign/playable/**",
    "note": "Scales the energy cost and cooldown of every player campaign "
            "ability (grenades, jumps, psychic powers, wargear actives...). "
            "Below 1.0 = cheaper / faster.",
    "options": {
        "energy_cost_multiplier": {
            "title": "Energy cost x", "type": "float", "default": 1.0,
            "min": 0.0, "max": 5,
            "description": "Multiplies ability_bag/energy_cost on all "
                           "playable abilities that cost energy."},
        "recharge_multiplier": {
            "title": "Cooldown x", "type": "float", "default": 1.0,
            "min": 0.05, "max": 5,
            "description": "Multiplies ability_bag/recharge_time (and toggled "
                           "recharge times) — 0.5 = abilities back twice as fast."},
    },
}

WARNINGS: list[str] = []

_FIELDS = {
    "energy": ("ability_bag/energy_cost",),
    "recharge": ("ability_bag/recharge_time",
                 "ability_bag/toggled_recharge_time_on",
                 "ability_bag/toggled_recharge_time_off"),
}


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    em = float(cfg.get("energy_cost_multiplier", 1.0))
    rm = float(cfg.get("recharge_multiplier", 1.0))
    changes: list[dict] = []
    if em == 1.0 and rm == 1.0:
        return changes
    for vp in src.attrib_paths(PREFIXES[src.game]):
        try:
            t = src.attrib_tree(vp)
        except Exception:
            continue
        label = src.attrib_label(vp)
        touched = False
        for group, mult in (("energy", em), ("recharge", rm)):
            if mult == 1.0:
                continue
            for path in _FIELDS[group]:
                n = rbf.find_indexed(t, path)
                if n is None or n.type not in (rbf.FLOAT, rbf.INT) or n.value <= 0:
                    continue
                old = n.value
                new = round(float(old) * mult, 4)
                if new != old:
                    n.value = new
                    touched = True
                    changes.append({"file": label, "path": path,
                                    "old": old, "new": new,
                                    "tweak": f"{'energy cost' if group=='energy' else 'cooldown'} x{mult}"})
        if touched:
            src.write_attrib(vp, t, out_data)
    return changes
