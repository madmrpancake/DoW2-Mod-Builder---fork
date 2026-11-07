"""Difficulty Tuning module — reshape the difficulty levels themselves.

Verified source: tuning/tuning_info.rbf
  world/campaign_difficulty/<campaign>/{enemy_health_multipliers,
    friend_damage_received_multipliers, friend_health_multipliers}/{easy,
    medium, hard, legendary}
Campaigns: space_marines (base DoW2) and xp1 (Chaos Rising).

Vanilla values worth knowing:
  base DoW2:  damage received x0.66 / 1 / 3 / 4.5  (enemy health flat 1)
  CR (xp1):   damage received x0.9 / 1 / 1.5 / 2 ; enemy health x0.75-2

'legendary' is Primarch. Values are what YOUR squads receive / enemies have.
Blank keeps vanilla.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

GAMES = ["dow2cr", "retribution"]

TUNING = "tuning/tuning_info.rbf"
CAMPAIGNS = {"space_marines": "Dawn of War II (base campaign)", "xp1": "Chaos Rising",
             "xp2_all": "Retribution (all races)"}
XP2_RACES = ["xp2_marine", "xp2_chaos", "xp2_eldar", "xp2_ork",
             "xp2_imperial_guard", "xp2_tyranid"]
TABLES = {
    "enemy_health_multipliers": "Enemy health x",
    "friend_damage_received_multipliers": "Damage you take x",
    "friend_health_multipliers": "Your health x",
}
DIFFS = ["easy", "medium", "hard", "legendary"]

SCHEMA = {
    "module": "difficulty_tuning",
    "title": "Difficulty Tuning",
    "target_file": "simulation/attrib/tuning/tuning_info.rbf (campaign_difficulty)",
    "note": "Rewrites what each difficulty level actually means. legendary = "
            "Primarch. Vanilla DoW2 Primarch makes you take 4.5x damage; "
            "CR Primarch is 2x damage taken + 2x enemy health. Blank = vanilla.",
    "options": {},
}
# one map[float] option per campaign+table, keys = difficulties
for camp, camp_title in CAMPAIGNS.items():
    for table, table_title in TABLES.items():
        SCHEMA["options"][f"{camp}.{table}"] = {
            "title": f"{camp_title}: {table_title}",
            "description": "",
            "type": "map[float]",
            "keys": DIFFS,
            "default": {},
        }

WARNINGS: list[str] = []


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    changes: list[dict] = []
    skipped_other: set = set()
    t = src.attrib_tree(TUNING)
    touched = False
    for opt_key, values in (cfg or {}).items():
        if opt_key in ("enabled",) or not isinstance(values, dict):
            continue
        if "." not in opt_key:
            continue
        camp, table = opt_key.split(".", 1)
        if camp not in CAMPAIGNS or table not in TABLES:
            WARNINGS.append(f"unknown difficulty table {opt_key} (skipped)")
            continue
        # each game only has its own campaigns; quietly skip the other's
        if (src.game == "dow2cr") != (camp != "xp2_all"):
            skipped_other.add(camp)
            continue
        real_camps = XP2_RACES if camp == "xp2_all" else [camp]
        for diff, val in values.items():
            if diff not in DIFFS:
                WARNINGS.append(f"{opt_key}: unknown difficulty {diff} (skipped)")
                continue
            new = round(float(val), 4)
            if new <= 0:
                raise ValueError(f"difficulty_tuning: {opt_key}/{diff} must be > 0")
            for real in real_camps:      # fan out over the real sections
                path = f"world/campaign_difficulty/{real}/{table}/{diff}"
                n = rbf.find_indexed(t, path)
                if n is None or n.type not in (rbf.FLOAT, rbf.INT):
                    WARNINGS.append(f"{path} missing (skipped)")
                    continue
                old = n.value
                if new != old:
                    n.value = new
                    touched = True
                    changes.append({"file": src.attrib_label(TUNING), "path": path,
                                    "old": old, "new": new,
                                    "tweak": f"{CAMPAIGNS[camp]} {diff} "
                                             f"{TABLES[table].lower()} {new}"})
    if skipped_other:
        WARNINGS.append(
            "settings for the other game's campaigns were skipped ("
            + ", ".join(sorted(skipped_other)) +
            f") — this mod targets {src.game}.")
    if touched:
        src.write_attrib(TUNING, t, out_data)
    return changes
