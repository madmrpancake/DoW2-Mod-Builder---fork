"""Mass Scaling module — global multipliers across ALL player gear.

One switch each for:
  * weapon damage       - every campaign/playable weapon file (ranged, melee,
                          special weapons; direct hit + area-effect damage)
  * armour defence      - every campaign/playable wargear item of type armour
  * buffs / modifiers   - every *_modifier value carried by playable wargear
                          items (accessories, trinkets, commander items, armour
                          traits, on-hit procs) and, optionally, the campaign
                          trait upgrades (attrib_bonuses)

Player-only by design: enemy/NPC files (campaign/npc, pvp, core) are never
touched.

Scaling rules:
  multiplication modifiers: the bonus DELTA from 1.0 is scaled
      1.5x damage buff at m=1.3  ->  1 + 0.5*1.3 = 1.65
      0.8x received damage (a protection) -> 1 - 0.2*1.3 = 0.74 (stronger)
      (downsides on corrupt items scale too - documented behaviour)
  addition modifiers: value * m (sign preserved)
  enable modifiers: untouched
  grant_bonus_attribute_points_action/add_attribute_points: * m, half-up
Probabilities and durations are deliberately NOT scaled.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

GAMES = ["dow2cr", "retribution"]

SCHEMA = {
    "module": "mass_scaling",
    "title": "Mass Scaling (global)",
    "target_file": "simulation/attrib/{weapons,wargear,upgrade}/**  (campaign/playable only)",
    "note": "Blanket multipliers over all player-side gear. Enemy files are "
            "never touched. Overlaps with Stat Tweaks — don't scale the same "
            "stat in both.",
    "options": {
        "weapon_damage_multiplier": {
            "title": "Weapon damage x", "type": "float", "default": 1.0,
            "min": 0.1, "max": 10,
            "description": "Multiplies damage (incl. area-effect damage of "
                           "special weapons) on every playable campaign weapon."},
        "armour_defence_multiplier": {
            "title": "Armour defence x", "type": "float", "default": 1.0,
            "min": 0.1, "max": 10,
            "description": "Multiplies the defence stat of every playable "
                           "campaign armour item."},
        "buff_multiplier": {
            "title": "Buffs / modifiers x", "type": "float", "default": 1.0,
            "min": 0.1, "max": 5,
            "description": "Scales the strength of every modifier granted by "
                           "wargear (accessories, trinkets, procs). "
                           "Multiplicative buffs scale their bonus over 1.0."},
        "consumable_charges_multiplier": {
            "title": "Consumable charges x", "type": "float", "default": 1.0,
            "min": 0.5, "max": 10,
            "description": "Multiplies how many uses consumables grant "
                           "(grenade packs, medkits) so you can carry more "
                           "charges into a mission."},
        "include_trait_upgrades": {
            "title": "Also scale trait upgrades", "type": "bool", "default": True,
            "description": "Apply the buff multiplier to campaign level-up "
                           "trait bonuses (upgrade/campaign/**) as well."},
    },
}

WARNINGS: list[str] = []

_PREFIXES = {
    "dow2cr": {"weapon": "weapons/weapon/campaign/playable",
               "wargear": "wargear/wargear/campaign/playable",
               "upgrade": "upgrade/campaign"},
    # Retribution campaign gear lives under xp2/campaign/<race>; the campaign
    # dirs are used by playable armies (enemy chaff mostly uses core/pvp)
    "retribution": {"weapon": "weapons/weapon/xp2/campaign",
                    "wargear": "wargear/wargear/xp2/campaign",
                    "upgrade": "upgrade/xp2/campaign"},
}

_AOE_KEYS = ("short", "medium", "long", "distant")


def _scale_modifiers(root, m: float, changes: list, label: str) -> bool:
    """Scale every *_modifier value under root. Returns True if anything changed."""
    touched = False

    def walk(node, path):
        nonlocal touched
        for c in node.children:
            p = f"{path}/{c.key}" if path else c.key
            if c.type != rbf.TABLE:
                continue
            if c.key.endswith("_modifier"):
                u = rbf.find(c, "usage_type")
                v = rbf.find(c, "value")
                if v is not None and v.type in (rbf.FLOAT, rbf.INT) and u is not None:
                    old = v.value
                    if u.value == "multiplication":
                        new = 1.0 + (float(old) - 1.0) * m
                    elif u.value == "addition":
                        new = float(old) * m
                    else:                      # enable / unknown
                        new = old
                    if v.type == rbf.INT:
                        new = int(new + 0.5) if new >= 0 else -int(-new + 0.5)
                    else:
                        new = round(float(new), 4)
                    if new != old:
                        v.value = new
                        touched = True
                        changes.append({"file": label, "path": f"{p}/value",
                                        "old": old, "new": new,
                                        "tweak": f"buff x{m}"})
            if c.key == "grant_bonus_attribute_points_action":
                pts = rbf.find(c, "add_attribute_points")
                if pts is not None and pts.type == rbf.INT and pts.value > 0:
                    old = pts.value
                    new = max(old, int(old * m + 0.5))
                    if new != old:
                        pts.value = new
                        touched = True
                        changes.append({"file": label,
                                        "path": f"{p}/add_attribute_points",
                                        "old": old, "new": new,
                                        "tweak": f"buff x{m}"})
            walk(c, p)
    walk(root, "")
    return touched


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    wm = float(cfg.get("weapon_damage_multiplier", 1.0))
    am = float(cfg.get("armour_defence_multiplier", 1.0))
    bm = float(cfg.get("buff_multiplier", 1.0))
    inc_up = bool(cfg.get("include_trait_upgrades", True))
    ccm = float(cfg.get("consumable_charges_multiplier", 1.0))
    changes: list[dict] = []

    pf = _PREFIXES[src.game]
    # ---- weapons ---------------------------------------------------------
    if wm != 1.0:
        for vp in src.attrib_paths(pf["weapon"]):
            try:
                t = src.attrib_tree(vp)
            except Exception:
                continue
            label = src.attrib_label(vp)
            touched = False
            dmg = rbf.find_indexed(t, "weapon_bag/damage_hp")
            if dmg is not None and dmg.type in (rbf.FLOAT, rbf.INT) and dmg.value > 0:
                old = dmg.value
                new = round(float(old) * wm, 4) if dmg.type == rbf.FLOAT else int(old * wm + 0.5)
                dmg.value = new
                touched = True
                changes.append({"file": label, "path": "weapon_bag/damage_hp",
                                "old": old, "new": new, "tweak": f"weapon damage x{wm}"})
            for k in _AOE_KEYS:
                n = rbf.find_indexed(t, f"weapon_bag/area_effect/hp_damage/{k}")
                if n is not None and n.type in (rbf.FLOAT, rbf.INT) and n.value > 0:
                    old = n.value
                    new = round(float(old) * wm, 4) if n.type == rbf.FLOAT else int(old * wm + 0.5)
                    n.value = new
                    touched = True
                    changes.append({"file": label,
                                    "path": f"weapon_bag/area_effect/hp_damage/{k}",
                                    "old": old, "new": new,
                                    "tweak": f"weapon damage x{wm}"})
            if touched:
                src.write_attrib(vp, t, out_data)

    # ---- wargear: armour defence + buffs + consumable charges -----------
    if am != 1.0 or bm != 1.0 or ccm != 1.0:
        for vp in src.attrib_paths(pf["wargear"]):
            try:
                t = src.attrib_tree(vp)
            except Exception:
                continue
            label = src.attrib_label(vp)
            bag = t.children[0] if t.children else None
            if bag is None:
                continue
            touched = False
            if am != 1.0:
                ty = rbf.find(bag, "type")
                d = rbf.find(bag, "defence")
                if ty is not None and ty.value == "armour" and d is not None \
                        and d.type in (rbf.INT, rbf.FLOAT):
                    old = d.value
                    new = int(old * am + 0.5) if d.type == rbf.INT else round(float(old) * am, 4)
                    if new != old:
                        d.value = new
                        touched = True
                        changes.append({"file": label, "path": "wargear/defence",
                                        "old": old, "new": new,
                                        "tweak": f"armour defence x{am}"})
            if bm != 1.0:
                if _scale_modifiers(bag, bm, changes, label):
                    touched = True
            if ccm != 1.0:
                ty2 = rbf.find(bag, "type")
                if ty2 is not None and ty2.value in ("consumable", "expendable"):
                    for path, n in rbf.walk(bag):
                        if n.key == "count" and "slot_item_add" in path \
                                and n.type == rbf.INT and n.value > 0:
                            old = n.value
                            new = max(1, int(old * ccm + 0.5))
                            if new != old:
                                n.value = new
                                touched = True
                                changes.append({"file": label,
                                                "path": f"{path}/count",
                                                "old": old, "new": new,
                                                "tweak": f"charges x{ccm}"})
            if touched:
                src.write_attrib(vp, t, out_data)

    # ---- trait upgrades --------------------------------------------------
    if bm != 1.0 and inc_up:
        for vp in src.attrib_paths(pf["upgrade"]):
            try:
                t = src.attrib_tree(vp)
            except Exception:
                continue
            label = src.attrib_label(vp)
            if _scale_modifiers(t, bm, changes, label):
                src.write_attrib(vp, t, out_data)

    return changes
