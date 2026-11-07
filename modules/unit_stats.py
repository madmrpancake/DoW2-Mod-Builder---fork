"""Unit Stats module — RPG-style editing of squad & character base stats.

Edits the SOURCE blueprints the campaign reads when it spawns your squads
(ebps entity files + sbps squad files) — never the save file. Changed values
apply to any campaign, new or in progress, because the game re-reads these
blueprints every mission load.

Two layers per squad:
  squad-level  (sbps): morale pool/regen, energy pool/regen, level cap
  entity-level (ebps): per squad member — health, health regen, sight,
                       speed, melee skill, charge range

Config:
    {"squads": {
        "<sbps vpath>": {
            "squad":    {"morale": 400, ...},
            "entities": {"<ebps vpath>": {"hitpoints": 4000, ...}}
        }}}

Values are absolute (what you type is what the game uses). The UI shows the
current live value next to each field. Verified locations:
health_ext/hitpoints etc. — see SQUAD_STATS / ENTITY_STATS.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

GAMES = ["dow2cr", "retribution"]

# largest squad vanilla ships anywhere (ork_reinforcements_weak_bg: num=max=12)
_VANILLA_MAX_SQUAD = 12

_RET_RACES = ["race_marine", "race_chaos", "race_eldar", "race_ork",
              "race_imperial_guard", "race_tyranid"]
SQUAD_PREFIXES = {
    "dow2cr": [
        "sbps/campaign/playable/race_marine/troops",
        "sbps/campaign/playable/race_marine/vehicles",
        "sbps/campaign/playable/race_marine/xp1/troops",
        "sbps/campaign/playable/race_marine/xp1/vehicles",
        "sbps/campaign/playable/race_chaos/troops",
        "sbps/campaign/playable/race_chaos/vehicles",
    ],
    "retribution": [f"sbps/xp2/campaign/{r}/{kind}"
                    for r in _RET_RACES
                    for kind in ("heroes", "troops", "vehicles", "honor_guard")],
}

# stat key -> (extension, path inside extension, kind, min)
SQUAD_STATS = {
    "morale":       ("squad_morale_ext",   "starting_morale", "int",   1),
    "morale_regen": ("squad_morale_ext",   "regen_rate",      "float", 0.0),
    "energy":       ("squad_energy_ext",   "starting_energy", "float", 0.0),
    "energy_regen": ("squad_energy_ext",   "regen_rate",      "float", 0.0),
    "max_level":    ("squad_leveling_ext", "max_level",       "int",   1),
}
ENTITY_STATS = {
    "hitpoints":    ("health_ext", "hitpoints",     "float", 1.0),
    "health_regen": ("health_ext", "regeneration",  "float", 0.0),
    "sight_radius": ("sight_ext",  "sight_radius",  "float", 5.0),
    "speed":        ("moving_ext", "speed_max",     "float", 0.5),
    "melee_skill":  ("melee_ext",  "weapon_skill",  "int",   1),
    "charge_range": ("melee_ext",  "charge/range",  "float", 0.0),
}

# level-up growth: attrib_level_attributes rows inside ebps leveling_ext.
# Each row is one step of the level/point curve (46-101 rows per hero,
# non-uniform), so growth edits are MULTIPLIERS across every row.
# kind "mult": plain scale; kind "delta": value is a multiplier stat where
# 1.0 is neutral, so we scale its distance from 1.0.
GROWTH_STATS = {
    "g_health":        ("health/health",                 "mult",  "Health growth"),
    "g_health_regen":  ("health/regeneration",           "mult",  "Health regen growth"),
    "g_melee_skill":   ("weapon/melee_skill",            "mult",  "Melee skill growth"),
    "g_melee_dmg":     ("weapon/melee_damage_modifier",  "delta", "Melee damage growth"),
    "g_ranged_dmg":    ("weapon/ranged_damage_modifier", "delta", "Ranged damage growth"),
    "g_morale":        ("skills/morale",                 "mult",  "Morale growth"),
    "g_morale_regen":  ("skills/morale_regeneration",    "mult",  "Morale regen growth"),
    "g_energy":        ("skills/energy",                 "mult",  "Energy growth"),
    "g_energy_regen":  ("skills/energy_regeneration",    "mult",  "Energy regen growth"),
    "g_suppression":   ("skills/supression_resistance",  "mult",  "Suppression resist growth"),
}

STAT_META = {
    "morale":       {"title": "Morale", "unit": "", "hint": "Pool before the squad breaks"},
    "morale_regen": {"title": "Morale regen", "unit": "/s", "hint": ""},
    "energy":       {"title": "Energy", "unit": "", "hint": "Ability resource pool"},
    "energy_regen": {"title": "Energy regen", "unit": "/s", "hint": ""},
    "max_level":    {"title": "Level cap", "unit": "", "hint": "Campaign level cap for this hero"},
    "extra_members": {"title": "Extra members", "unit": "+n",
                      "hint": "ADDS this many members — not the total size, and "
                              "base sizes differ: most hero squads are 3, but "
                              "Tarkus and Terminator Tarkus are 4. Check the "
                              "current size, then add the difference. Lone "
                              "heroes (Davian Thule) cannot grow."},
    "hitpoints":    {"title": "Health", "unit": "hp",
                     "hint": "Per squad member — every model has its own separate "
                             "pool and dies when it empties; nothing is shared. "
                             "The game draws one health bar for the whole squad, "
                             "which is why it can look like a shared pool."},
    "health_regen": {"title": "Health regen", "unit": "hp/s", "hint": ""},
    "sight_radius": {"title": "Sight radius", "unit": "m", "hint": ""},
    "speed":        {"title": "Move speed", "unit": "m/s", "hint": ""},
    "melee_skill":  {"title": "Melee skill", "unit": "", "hint": "Higher = hits and syncs more in melee"},
    "charge_range": {"title": "Charge range", "unit": "m", "hint": ""},
    **{k: {"title": v[2], "unit": "x",
           "hint": "Multiplies every step of this hero's level-up curve"}
       for k, v in GROWTH_STATS.items()},
}

SCHEMA = {
    "module": "unit_stats",
    "title": "Unit Stats (RPG sheet)",
    "target_file": "simulation/attrib/{sbps,ebps}/campaign/playable/**",
    "note": "Character-sheet editing of your squads' base stats. Edits the "
            "blueprints the game loads, not the save — works on existing "
            "campaigns.",
    "options": {
        "squads": {
            "title": "Squad overrides",
            "description": "Per-squad and per-member stat overrides.",
            "type": "unit_stats",
            "default": {},
        },
    },
}

WARNINGS: list[str] = []


def _ext(tree, name):
    for c in tree.children:
        if c.key == name:
            return c
    return None


def _clone(node):
    n = rbf.RbfNode(node.key, node.type, node.value)
    n.children = [_clone(c) for c in node.children]
    return n


def _get(tree, ext_name, path):
    e = _ext(tree, ext_name)
    if e is None:
        return None
    return rbf.find(e, path)


def catalog(src) -> list[dict]:
    """Hero squads with entities and current stat values (for the UI)."""
    out = []
    for prefix in SQUAD_PREFIXES[src.game]:
        for vp in src.attrib_paths(prefix):
            try:
                t = src.attrib_tree(vp)
            except Exception:
                continue
            lev = _ext(t, "squad_leveling_ext")
            ml = rbf.find(lev, "max_level") if lev is not None else None
            if ml is None or (ml.value or 0) < 2:
                continue                       # only leveling (hero) squads
            ui = _ext(t, "squad_ui_ext")
            entry = {
                "squad": vp,
                "id": Path(vp).stem,
                "xp1": "/xp1/" in vp,
                "race": next((r.removeprefix("race_") for r in
                              ("race_chaos", "race_eldar", "race_ork",
                               "race_imperial_guard", "race_tyranid", "race_marine")
                              if r in vp), "marine"),
                "screen_name": (rbf.find(ui, "screen_name").value
                                if ui is not None and rbf.find(ui, "screen_name") else None),
                "icon_name": (rbf.find(ui, "icon_name").value
                              if ui is not None and rbf.find(ui, "icon_name") else None),
                "squad_type": None,
                "stats": {}, "entities": [],
            }
            lo = _ext(t, "squad_loadout_ext")
            if lo is not None:
                st = rbf.find(lo, "squad_type")
                entry["squad_type"] = st.value if st is not None else None
            for key, (ext, path, kind, mn) in SQUAD_STATS.items():
                n = _get(t, ext, path)
                if n is not None and n.type in (rbf.FLOAT, rbf.INT):
                    entry["stats"][key] = round(n.value, 3) if kind == "float" else n.value
            # member entities
            ents = []
            if lo is not None:
                ul = rbf.find(lo, "unit_list")
                if ul is not None:
                    for e in ul.children:
                        ty = rbf.find(e, "type")
                        if ty is not None and ty.value:
                            ep = ty.value.replace("\\", "/") + ".rbf"
                            if ep not in ents:
                                ents.append(ep)
            for ep in ents:
                try:
                    et = src.attrib_tree(ep)
                except Exception:
                    continue
                ee = {"entity": ep, "id": Path(ep).stem, "stats": {}}
                for key, (ext, path, kind, mn) in ENTITY_STATS.items():
                    n = _get(et, ext, path)
                    if n is not None and n.type in (rbf.FLOAT, rbf.INT):
                        ee["stats"][key] = round(n.value, 3) if kind == "float" else n.value
                entry["entities"].append(ee)
            # growth baseline: first curve row of the leader entity
            if entry["entities"]:
                try:
                    lt = src.attrib_tree(entry["entities"][0]["entity"])
                    lev = _ext(lt, "leveling_ext")
                    al = rbf.find(lev, "attrib_levels") if lev is not None else None
                    rows = [c for c in al.children
                            if c.key == "attrib_level_attributes"] if al is not None else []
                    if rows:
                        gb = {"rows": len(rows)}
                        for key, (sub, kind, title) in GROWTH_STATS.items():
                            n = rbf.find(rows[0], sub)
                            if n is not None and n.type in (rbf.FLOAT, rbf.INT):
                                gb[key] = round(float(n.value), 3)
                        entry["growth_base"] = gb
                except Exception:
                    pass
            if entry["entities"]:
                out.append(entry)
    return out


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    changes: list[dict] = []
    squads = cfg.get("squads", {}) or {}
    if not isinstance(squads, dict):
        raise ValueError("unit_stats: 'squads' must be a mapping of sbps paths "
                         "-> {squad/entities/growth}")
    if set(squads) == {"squads"} and isinstance(squads["squads"], dict):
        squads = squads["squads"]   # editor versions before 1.2.2 saved a
                                    # second 'squads' wrapper around the paths
    _known_sections = {"squad", "entities", "growth"}
    for svp, sc in squads.items():
        if sc is not None and not isinstance(sc, dict):
            raise ValueError(f"unit_stats: entry for {svp!r} must be a mapping "
                             "with 'squad', 'entities' and/or 'growth' sections")
        for _sect in _known_sections:
            _v = (sc or {}).get(_sect)
            if _v is not None and not isinstance(_v, dict):
                raise ValueError(f"unit_stats: {svp}: '{_sect}' must be a mapping")
        stray = set(sc or {}) - _known_sections
        if stray:
            hint = ""
            if svp == "squads" and any("/" in k for k in stray):
                hint = (" — it looks like the squad paths are wrapped in an "
                        "extra 'squads' key: move them up one level, so each "
                        "'sbps/....rbf' path sits directly under the option")
            WARNINGS.append(f"{svp.split('/')[-1]}: ignored unknown key(s) "
                            f"{', '.join(sorted(stray))} — stats go under "
                            f"'squad', 'entities' or 'growth'{hint}")
        svp_n = svp.replace("\\", "/")
        # squad-level
        squad_sets = dict((sc or {}).get("squad", {}) or {})
        extra_members = int(squad_sets.pop("extra_members", 0) or 0)
        if squad_sets or extra_members:
            try:
                t = src.attrib_tree(svp_n)
            except (KeyError, FileNotFoundError):
                raise ValueError(f"unit_stats: squad not found: {svp_n}")
            touched = False
            if extra_members > 0:
                lo = _ext(t, "squad_loadout_ext")
                ul = rbf.find(lo, "unit_list") if lo is not None else None
                entries = [c for c in ul.children
                           if c.key == "squad_loadout_unit_entry"] if ul is not None else []
                # A squad's size is the SUM of each entry's 'num' — one entry can
                # spawn several models (vanilla csm_chaos_marine is a single entry
                # with num=3). So we GROW the last entry rather than cloning it:
                # a cloned entry brings its own num with it, which added 3 models
                # per "+1" on squads like Terminator Tarkus and left the squad
                # declaring more members than ever spawn (breaks the member
                # counter and the squad-is-dead check).
                nums = [rbf.find(e, "num") for e in entries]
                maxs = [rbf.find(e, "max") for e in entries]
                total = sum(n.value for n in nums if n is not None)
                if not entries or any(n is None for n in nums) \
                        or any(m is None for m in maxs):
                    WARNINGS.append(f"{svp_n}: no readable unit_list "
                                    "(extra members skipped)")
                elif total <= 1:
                    WARNINGS.append(f"{svp_n}: single-model squad — extra members "
                                    "skipped (would duplicate the hero)")
                else:
                    nums[-1].value += extra_members
                    maxs[-1].value += extra_members
                    touched = True
                    changes.append({"file": src.attrib_label(svp_n),
                                    "path": "squad_loadout_ext/unit_list",
                                    "old": f"{total} members",
                                    "new": f"{total + extra_members} members",
                                    "tweak": f"squad size +{extra_members}"})
                    if total + extra_members > _VANILLA_MAX_SQUAD:
                        WARNINGS.append(
                            f"{svp_n}: {total + extra_members} members — larger "
                            f"than any vanilla squad ({_VANILLA_MAX_SQUAD}); the "
                            "game may not spawn them all, which leaves the squad "
                            "counting members that do not exist.")
            for key, val in squad_sets.items():
                if key not in SQUAD_STATS:
                    WARNINGS.append(f"{svp_n}: unknown squad stat {key} (skipped)")
                    continue
                ext, path, kind, mn = SQUAD_STATS[key]
                n = _get(t, ext, path)
                if n is None:
                    WARNINGS.append(f"{svp_n}: {ext}/{path} missing (skipped)")
                    continue
                old = n.value
                new = max(mn, int(float(val) + 0.5)) if kind == "int" \
                    else max(mn, round(float(val), 4))
                if new != old:
                    n.value = new
                    touched = True
                    changes.append({"file": src.attrib_label(svp_n),
                                    "path": f"{ext}/{path}",
                                    "old": old, "new": new,
                                    "tweak": f"{STAT_META[key]['title']} = {new}"})
            if touched:
                src.write_attrib(svp_n, t, out_data)
        # entity work: explicit sets + squad-wide growth multipliers merged so
        # each entity file is read, edited and written exactly once
        growth = {k: float(v) for k, v in ((sc or {}).get("growth", {}) or {}).items()
                  if k in GROWTH_STATS and float(v) != 1.0}
        ent_work: dict[str, dict] = {}
        for evp, ent_sets in ((sc or {}).get("entities", {}) or {}).items():
            if ent_sets:
                ent_work.setdefault(evp.replace("\\", "/"), {})["sets"] = ent_sets
        if growth:
            try:
                sq_tree = src.attrib_tree(svp_n)
            except (KeyError, FileNotFoundError):
                raise ValueError(f"unit_stats: squad not found: {svp_n}")
            lo = _ext(sq_tree, "squad_loadout_ext")
            if lo is not None:
                ul = rbf.find(lo, "unit_list")
                if ul is not None:
                    for e in ul.children:
                        ty = rbf.find(e, "type")
                        if ty is not None and ty.value:
                            ep = ty.value.replace("\\", "/") + ".rbf"
                            ent_work.setdefault(ep, {})["growth"] = growth

        for evp_n, work in ent_work.items():
            try:
                t = src.attrib_tree(evp_n)
            except (KeyError, FileNotFoundError):
                if "sets" in work:
                    raise ValueError(f"unit_stats: entity not found: {evp_n}")
                WARNINGS.append(f"{svp_n}: member {evp_n} not found (skipped)")
                continue
            touched = False
            for key, val in (work.get("sets") or {}).items():
                if key not in ENTITY_STATS:
                    WARNINGS.append(f"{evp_n}: unknown entity stat {key} (skipped)")
                    continue
                ext, path, kind, mn = ENTITY_STATS[key]
                n = _get(t, ext, path)
                if n is None:
                    WARNINGS.append(f"{evp_n}: {ext}/{path} missing (skipped)")
                    continue
                old = n.value
                new = max(mn, int(float(val) + 0.5)) if kind == "int" \
                    else max(mn, round(float(val), 4))
                if new != old:
                    n.value = new
                    touched = True
                    changes.append({"file": src.attrib_label(evp_n),
                                    "path": f"{ext}/{path}",
                                    "old": old, "new": new,
                                    "tweak": f"{STAT_META[key]['title']} = {new}"})
            gw = work.get("growth") or {}
            if gw:
                lev = _ext(t, "leveling_ext")
                al = rbf.find(lev, "attrib_levels") if lev is not None else None
                rows = [c for c in al.children
                        if c.key == "attrib_level_attributes"] if al is not None else []
                if not rows:
                    WARNINGS.append(f"{evp_n}: no level curve (growth skipped)")
                else:
                    per_key: dict[str, int] = {}
                    for key, m in gw.items():
                        sub, kind, _title = GROWTH_STATS[key]
                        for r in rows:
                            n = rbf.find(r, sub)
                            if n is None or n.type not in (rbf.FLOAT, rbf.INT):
                                continue
                            old = n.value
                            new = 1.0 + (float(old) - 1.0) * m if kind == "delta" \
                                else float(old) * m
                            new = int(new + 0.5) if n.type == rbf.INT else round(new, 4)
                            if new != old:
                                n.value = new
                                touched = True
                                per_key[key] = per_key.get(key, 0) + 1
                    for key, cnt in per_key.items():
                        changes.append({"file": src.attrib_label(evp_n),
                                        "path": GROWTH_STATS[key][0],
                                        "old": f"{cnt} curve rows",
                                        "new": f"x{gw[key]}",
                                        "tweak": f"{STAT_META[key]['title']} x{gw[key]}"})
            if touched:
                src.write_attrib(evp_n, t, out_data)
    return changes
