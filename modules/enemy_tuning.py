"""Enemy Tuning module — the other side of the battlefield.

Boss pacing and enemy rebalance. Verified sources:
  ebps/campaign/npc/**    health_ext/hitpoints  (boss dirs contain "/boss")
  weapons/weapon/campaign/npc/**  weapon_bag/damage_hp (+ area_effect)

Multipliers apply to campaign NPC files only — your squads are untouched
(that's Mass Scaling's job). DoW2/CR only for now: Retribution mixes enemy
and player units in the same xp2 dirs.

Config: {"enemy_health_multiplier": 1.0, "boss_health_multiplier": 0.7,
         "enemy_damage_multiplier": 1.0}
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

GAMES = ["dow2cr"]

EBPS_PREFIX = "ebps/campaign/npc"
WEAP_PREFIX = "weapons/weapon/campaign/npc"
_AOE_KEYS = ("short", "medium", "long", "distant")

SCHEMA = {
    "module": "enemy_tuning",
    "title": "Enemy Tuning (bosses & NPCs)",
    "target_file": "simulation/attrib/{ebps,weapons}/campaign/npc/**",
    "note": "Scale enemy health and boss health separately (trim the "
            "HP-sponge bosses without softening everything else), plus "
            "enemy weapon damage. Player units are never touched.",
    "options": {
        "enemy_health_multiplier": {
            "title": "Enemy health x", "type": "float", "default": 1.0,
            "min": 0.1, "max": 10,
            "description": "All campaign enemies except bosses."},
        "boss_health_multiplier": {
            "title": "Boss health x", "type": "float", "default": 1.0,
            "min": 0.1, "max": 10,
            "description": "Enemies in boss folders only (Warboss, Avatar, "
                           "hive tyrants...). 0.7 = snappier boss fights."},
        "enemy_damage_multiplier": {
            "title": "Enemy damage x", "type": "float", "default": 1.0,
            "min": 0.1, "max": 10,
            "description": "Every campaign NPC weapon (direct + area "
                           "damage)."},
    },
}

WARNINGS: list[str] = []


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    eh = float(cfg.get("enemy_health_multiplier", 1.0))
    bh = float(cfg.get("boss_health_multiplier", 1.0))
    ed = float(cfg.get("enemy_damage_multiplier", 1.0))
    changes: list[dict] = []

    if eh != 1.0 or bh != 1.0:
        for vp in src.attrib_paths(EBPS_PREFIX):
            is_boss = "/boss" in vp
            m = bh if is_boss else eh
            if m == 1.0:
                continue
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
            new = round(float(old) * m, 2)
            if new != old:
                hp.value = new
                changes.append({"file": src.attrib_label(vp),
                                "path": "health_ext/hitpoints",
                                "old": old, "new": new,
                                "tweak": f"{'boss' if is_boss else 'enemy'} health x{m}"})
                src.write_attrib(vp, t, out_data)

    if ed != 1.0:
        for vp in src.attrib_paths(WEAP_PREFIX):
            try:
                t = src.attrib_tree(vp)
            except Exception:
                continue
            label = src.attrib_label(vp)
            touched = False
            keys = ["weapon_bag/damage_hp"] + \
                   [f"weapon_bag/area_effect/hp_damage/{k}" for k in _AOE_KEYS]
            for key in keys:
                n = rbf.find_indexed(t, key)
                if n is None or n.type not in (rbf.FLOAT, rbf.INT) or n.value <= 0:
                    continue
                old = n.value
                new = round(float(old) * ed, 4)
                if new != old:
                    n.value = new
                    touched = True
                    changes.append({"file": label, "path": key,
                                    "old": old, "new": new,
                                    "tweak": f"enemy damage x{ed}"})
            if touched:
                src.write_attrib(vp, t, out_data)
    return changes
