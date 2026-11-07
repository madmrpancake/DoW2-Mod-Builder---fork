"""Last Stand module — tune the survival mode.

Last Stand content lives in the 'survive' files (verified in game data):
  ebps/core/race_*/**survive**   hero entities (hitpoints)
  weapons/weapon/core/**survive** hero weapons (damage)
  wargear/wargear/core/**survive** Last Stand wargear (defence + modifiers)
DoW2/CR has 260 survive files; Retribution 631 (incl. IG/Tau/Necron heroes).

Multipliers over your Last Stand heroes and their gear. Wave scripts are
engine/map-side; hero power is the practical lever.

Config: {"hero_health_multiplier": 1.5, "hero_damage_multiplier": 1.5,
         "wargear_defence_multiplier": 1.5, "buff_multiplier": 1.3}
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402
from modules.mass_scaling import _scale_modifiers  # noqa: E402  (same rules)

GAMES = ["dow2cr", "retribution"]

_AOE_KEYS = ("short", "medium", "long", "distant")

SCHEMA = {
    "module": "last_stand",
    "title": "Last Stand",
    "target_file": "simulation/attrib/**survive** (Last Stand content)",
    "note": "Buff (or nerf) your Last Stand heroes: health, weapon damage, "
            "wargear defence and item buffs. Applies to the survival mode "
            "only — campaign and skirmish untouched.",
    "options": {
        "hero_health_multiplier": {
            "title": "Hero health x", "type": "float", "default": 1.0,
            "min": 0.25, "max": 10, "description": ""},
        "hero_damage_multiplier": {
            "title": "Weapon damage x", "type": "float", "default": 1.0,
            "min": 0.25, "max": 10, "description": ""},
        "wargear_defence_multiplier": {
            "title": "Wargear defence x", "type": "float", "default": 1.0,
            "min": 0.25, "max": 10, "description": ""},
        "buff_multiplier": {
            "title": "Wargear buffs x", "type": "float", "default": 1.0,
            "min": 0.25, "max": 5,
            "description": "Scales modifier strength on Last Stand wargear "
                           "(same delta rules as Mass Scaling)."},
    },
}

WARNINGS: list[str] = []


def _survive_paths(src, top):
    return [p for p in src.attrib_paths(top) if "survive" in p]


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    hh = float(cfg.get("hero_health_multiplier", 1.0))
    hd = float(cfg.get("hero_damage_multiplier", 1.0))
    wd = float(cfg.get("wargear_defence_multiplier", 1.0))
    bm = float(cfg.get("buff_multiplier", 1.0))
    changes: list[dict] = []

    if hh != 1.0:
        for vp in _survive_paths(src, "ebps"):
            try:
                t = src.attrib_tree(vp)
            except Exception:
                continue
            hp = None
            for c in t.children:
                if c.key == "health_ext":
                    hp = rbf.find(c, "hitpoints")
                    break
            if hp is None or hp.type not in (rbf.FLOAT, rbf.INT) or hp.value <= 0:
                continue
            old = hp.value
            new = round(float(old) * hh, 2)
            if new != old:
                hp.value = new
                changes.append({"file": src.attrib_label(vp),
                                "path": "health_ext/hitpoints",
                                "old": old, "new": new, "tweak": f"LS health x{hh}"})
                src.write_attrib(vp, t, out_data)

    if hd != 1.0:
        for vp in _survive_paths(src, "weapons/weapon"):
            try:
                t = src.attrib_tree(vp)
            except Exception:
                continue
            label = src.attrib_label(vp)
            touched = False
            for key in ["weapon_bag/damage_hp"] + \
                       [f"weapon_bag/area_effect/hp_damage/{k}" for k in _AOE_KEYS]:
                n = rbf.find_indexed(t, key)
                if n is None or n.type not in (rbf.FLOAT, rbf.INT) or n.value <= 0:
                    continue
                old = n.value
                new = round(float(old) * hd, 4)
                if new != old:
                    n.value = new
                    touched = True
                    changes.append({"file": label, "path": key, "old": old,
                                    "new": new, "tweak": f"LS damage x{hd}"})
            if touched:
                src.write_attrib(vp, t, out_data)

    if wd != 1.0 or bm != 1.0:
        for vp in _survive_paths(src, "wargear/wargear"):
            try:
                t = src.attrib_tree(vp)
            except Exception:
                continue
            bag = t.children[0] if t.children else None
            if bag is None:
                continue
            label = src.attrib_label(vp)
            touched = False
            if wd != 1.0:
                ty = rbf.find(bag, "type")
                d = rbf.find(bag, "defence")
                if ty is not None and ty.value == "armour" and d is not None \
                        and d.type in (rbf.INT, rbf.FLOAT) and d.value > 0:
                    old = d.value
                    new = int(old * wd + 0.5) if d.type == rbf.INT else round(float(old) * wd, 4)
                    if new != old:
                        d.value = new
                        touched = True
                        changes.append({"file": label, "path": "wargear/defence",
                                        "old": old, "new": new,
                                        "tweak": f"LS defence x{wd}"})
            if bm != 1.0 and _scale_modifiers(bag, bm, changes, label):
                touched = True
            if touched:
                src.write_attrib(vp, t, out_data)
    return changes
