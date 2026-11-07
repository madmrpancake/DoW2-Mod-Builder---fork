"""XP Tuning module — level faster (or slower).

Where campaign XP actually comes from (verified against game data):
  1. kills: every enemy entity carries cost_ext/xp_points
     (e.g. hormagaunt 1.0) — granted to all conscious squads
     (tuning_info leveling: xp_granting_method all_conscious_squads)
  2. mission completion: campaign/tuning.lua
        mission_xp_reward_base = 15
        zeal/resilience/speed_star_value = 2 each  (rating stars)
     plus per-mission `experience` values in the mission rewards block
     (those are handled by the Mission Rewards module)

This module scales (1) across every campaign NPC entity and edits (2) in
the effective tuning.lua. It chains with Campaign Pacing on tuning.lua —
whichever runs second re-reads the already-emitted copy.

Config:
    {"kill_xp_multiplier": 2.0,
     "mission_xp_base": 15,
     "star_xp_value": 2}
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

GAMES = ["dow2cr", "retribution"]

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "gamedata" / "dow2cr_scripts"
NPC_PREFIXES = {"dow2cr": "ebps/campaign/npc",
                "retribution": "ebps/xp2/campaign"}

SCHEMA = {
    "module": "xp_tuning",
    "title": "XP Tuning",
    "target_file": "simulation/attrib/ebps/campaign/npc/** + campaign/tuning.lua",
    "note": "Kill XP is per enemy entity; mission XP comes from tuning.lua "
            "base + rating stars. Per-mission bonus XP lives in the Mission "
            "Rewards module.",
    "options": {
        "kill_xp_multiplier": {
            "title": "Kill XP x", "type": "float", "default": 1.0,
            "min": 0.0, "max": 20,
            "description": "Multiplies the xp_points every campaign enemy "
                           "grants when killed."},
        "mission_xp_base": {
            "title": "Mission completion XP base", "type": "int", "default": 15,
            "min": 0, "max": 1000, "vanilla": 15,
            "description": "Base XP for finishing any mission "
                           "(before star bonuses)."},
        "star_xp_value": {
            "title": "XP per rating star", "type": "int", "default": 2,
            "min": 0, "max": 200, "vanilla": 2,
            "description": "XP value of each zeal / resilience / speed star "
                           "earned on the end-of-mission report."},
        "points_per_level": {
            "title": "Attribute points per level-up", "type": "int",
            "default": 0, "min": 0, "max": 20, "vanilla": 2,
            "description": "Attribute points granted on EVERY level-up — the "
                           "points you spend on Health/Melee/Ranged/Will "
                           "(DoW2/CR vanilla 2, Retribution vanilla 1). "
                           "0 keeps vanilla. Note each hero also caps how much "
                           "a single attribute can absorb, so very high values "
                           "leave points you cannot spend.",
        },
        "starting_points": {
            "title": "Starting attribute points", "type": "int",
            "default": 0, "min": 0, "max": 50, "vanilla": 5,
            "description": "One-off pool a hero begins with, before any "
                           "level-up (DoW2/CR vanilla 5, Retribution 0). "
                           "0 keeps vanilla.",
        },
        "level_curve_multiplier": {
            "title": "XP needed per level x", "type": "float", "default": 1.0,
            "min": 0.05, "max": 5,
            "description": "Scales the campaign level-up curve "
                           "(required_xp_points per level, vanilla 150 / 325 / "
                           "575…). 0.5 = level twice as fast."},
    },
}

_LEVELING_TABLES = {"dow2cr": "leveling/campaign_tables",
                    "retribution": "leveling/xp2_campaign_tables"}

EXTRA_CONFIG_KEYS = ("attribute_points",)   # retired; warned about

WARNINGS: list[str] = []


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    changes: list[dict] = []
    km = float(cfg.get("kill_xp_multiplier", 1.0))
    base = int(cfg.get("mission_xp_base", 15))
    star = int(cfg.get("star_xp_value", 2))

    # ---- kill xp ---------------------------------------------------------
    if km != 1.0:
        for vp in src.attrib_paths(NPC_PREFIXES[src.game]):
            try:
                t = src.attrib_tree(vp)
            except Exception:
                continue
            n = rbf.find_indexed(t, "cost_ext/xp_points")
            if n is None or n.type not in (rbf.FLOAT, rbf.INT) or n.value <= 0:
                continue
            old = n.value
            new = round(float(old) * km, 4) if n.type == rbf.FLOAT else max(1, int(old * km + 0.5))
            if new == old:
                continue
            n.value = new
            changes.append({"file": src.attrib_label(vp),
                            "path": "cost_ext/xp_points",
                            "old": old, "new": new, "tweak": f"kill XP x{km}"})
            src.write_attrib(vp, t, out_data)

    # ---- leveling tables: attribute points + xp curve ---------------------
    if cfg.get("attribute_points"):
        WARNINGS.append(
            "'attribute_points' is retired and was ignored — it edited "
            "attribute_points_distribution, the AUTO-allocation table, and "
            "every campaign squad in both games has auto_allocate_discretionary"
            "_points = false, so the game never reads it. Use 'Attribute "
            "points per level-up' instead.")
    ppl = int(cfg.get("points_per_level", 0) or 0)
    start_pts = int(cfg.get("starting_points", 0) or 0)
    curve = float(cfg.get("level_curve_multiplier", 1.0))
    if ppl or start_pts or curve != 1.0:
        tab = _LEVELING_TABLES[src.game]
        t = src.attrib_tree("tuning/tuning_info.rbf")
        touched_t = False
        if ppl or start_pts:
            tbl = rbf.find_indexed(t, f"{tab}/level_xp_table")
            rows = [c for c in tbl.children
                    if c.type == rbf.TABLE] if tbl is not None else []
            pts = [rbf.find(r, "discretionary_attrib_points") for r in rows]
            pts = [n for n in pts if n is not None and n.type == rbf.INT]
            if len(pts) < 3:
                WARNINGS.append(f"{tab}/level_xp_table has no readable "
                                "discretionary_attrib_points rows (skipped)")
            else:
                if start_pts:
                    n0 = pts[0]
                    if n0.value != start_pts:
                        changes.append({
                            "file": src.attrib_label("tuning/tuning_info.rbf"),
                            "path": f"{tab}/level_xp_table[0]/"
                                    "discretionary_attrib_points",
                            "old": n0.value, "new": start_pts,
                            "tweak": f"starting points = {start_pts}"})
                        n0.value = start_pts
                        touched_t = True
                if ppl:
                    # Per-level rows are the NON-ZERO rows after the starting
                    # one. A 0 means "no points at this level" — either a
                    # deliberate gap (DoW2/CR row 1) or a level the campaign
                    # never reaches (Retribution caps at 10, leaving 100 dead
                    # rows). Never invent points for those.
                    tail = [n.value for n in pts[1:] if n.value > 0]
                    if not tail:
                        WARNINGS.append(f"{tab}/level_xp_table grants no "
                                        "per-level points to change (skipped)")
                        tail = [0]
                    modal = max(set(tail), key=tail.count)
                    hit = 0
                    for n in pts[1:]:
                        if n.value > 0 and n.value != ppl:
                            n.value = ppl
                            hit += 1
                    if hit:
                        touched_t = True
                        changes.append({
                            "file": src.attrib_label("tuning/tuning_info.rbf"),
                            "path": f"{tab}/level_xp_table/"
                                    "discretionary_attrib_points",
                            "old": f"{modal} x {hit} levels", "new": ppl,
                            "tweak": f"attribute points per level = {ppl}"})
                        if ppl > modal:
                            WARNINGS.append(
                                f"attribute points per level {modal} -> {ppl}: "
                                "each hero also caps how much one attribute can "
                                "hold (squad_leveling_ext/max_attribute_points — "
                                "about 62 across all attributes for a typical "
                                "DoW2/CR hero), so a large rise can leave points "
                                "that cannot be spent.")
        if curve != 1.0:
            # scale every required_xp_points row in the campaign level table
            node = rbf.find_indexed(t, f"{tab}/level_xp_table")
            n_rows = 0
            if node is not None:
                for path, n in rbf.walk(node):
                    if n.key == "required_xp_points" and n.type in (rbf.FLOAT, rbf.INT) \
                            and n.value > 0:
                        n.value = round(float(n.value) * curve, 1)
                        n_rows += 1
                if n_rows:
                    touched_t = True
                    changes.append({"file": src.attrib_label("tuning/tuning_info.rbf"),
                                    "path": f"{tab}/level_xp_table",
                                    "old": f"{n_rows} levels", "new": f"x{curve}",
                                    "tweak": f"XP curve x{curve}"})
            else:
                WARNINGS.append(f"{tab}/level_xp_table missing (curve skipped)")
        if touched_t:
            src.write_attrib("tuning/tuning_info.rbf", t, out_data)

    # ---- tuning.lua (base/star XP: DoW2/CR campaign scripts only) --------
    if src.game != "dow2cr":
        if base != 15 or star != 2:
            WARNINGS.append("mission XP base/star values are DoW2/CR-only "
                            "(Retribution campaign scripts differ)")
        return changes
    rel = "campaign/tuning.lua"
    emitted = out_data / rel                     # chain after campaign_pacing
    if emitted.exists():
        src_p = emitted
    else:
        import bootstrap
        src_p = bootstrap.require_scripts(src) / rel
    text = src_p.read_text(encoding="utf-8", errors="replace")
    touched = False

    def set_num(name, new):
        nonlocal text, touched
        m = re.search(rf"^(\s*){name}(\s*)=(\s*)(\d+)\s*,", text, re.M)
        if not m:
            WARNINGS.append(f"tuning.lua: {name} not found")
            return
        old = int(m.group(4))
        if old == new:
            return
        text = text[:m.start(4)] + str(new) + text[m.end(4):]
        touched = True
        changes.append({"file": rel, "path": name, "old": old, "new": new,
                        "tweak": f"{name} = {new}"})

    set_num("mission_xp_reward_base", base)
    for name in ("zeal_star_value", "resilience_star_value", "speed_star_value"):
        set_num(name, star)
    if touched:
        emitted.parent.mkdir(parents=True, exist_ok=True)
        emitted.write_text(text, encoding="utf-8", newline="")
    return changes
