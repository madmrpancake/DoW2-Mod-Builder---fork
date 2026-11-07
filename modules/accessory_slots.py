"""Accessory Slots — how many accessory slots each hero has.

Verified source (tuning/tuning_info.rbf, campaign/accessory_slots, both games):
  * squads/squad_slots[]: one row per hero squad with default_slots (vanilla
    1 or 2 — DoW2/CR lists 21 squads incl. terminator variants, Retribution 24
    across all six races);
  * upgrades/upgrade_slots[]: trait upgrades that add or remove a slot (the
    'Improved Loadout' traits are modify_slots_by = +1, and one corruption
    trait is -1).

The paperdoll UI has exactly three accessory slot widgets
(accessory_slot0..2_mc in the flash movie), so 3 is the hard ceiling —
values above it are clamped here rather than shipped broken.

Config:
    {"set_all": 0,            # 0 = leave alone; 1..3 sets every hero
     "add": 0,                # -2..2 added to each hero's vanilla count
     "per_squad": {"<sbps path>": 3, ...}}   # wins over the two above
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

GAMES = ["dow2cr", "retribution"]

TUNING = "tuning/tuning_info.rbf"
UI_MAX = 3

SCHEMA = {
    "module": "accessory_slots",
    "title": "Accessory Slots",
    "target_file": "simulation/attrib/tuning/tuning_info.rbf "
                   "(campaign/accessory_slots)",
    "note": "Heroes start with 1 or 2 accessory slots; some traits add one. "
            "This sets the starting counts. The squad screen has three slot "
            "positions, so 3 is the most the interface can show — values are "
            "capped there. Trait bonuses still apply on top but cannot push "
            "past what the screen can display.",
    "options": {
        "set_all": {
            "title": "Set every hero to", "type": "int", "default": 0,
            "min": 0, "max": UI_MAX,
            "description": "0 leaves heroes alone. 3 gives everyone the full "
                           "row of accessory slots from the start.",
        },
        "add": {
            "title": "Add to every hero", "type": "int", "default": 0,
            "min": -2, "max": 2,
            "description": "Added to each hero's own vanilla count instead of "
                           "flattening them (ignored when 'set every hero' is "
                           "used). Result is kept between 0 and 3.",
        },
    },
}

WARNINGS: list[str] = []


EXTRA_CONFIG_KEYS = ("per_squad",)


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    changes: list[dict] = []
    set_all = int(cfg.get("set_all", 0) or 0)
    add = int(cfg.get("add", 0) or 0)
    if not isinstance(cfg.get("per_squad") or {}, dict):
        raise ValueError("accessory_slots: 'per_squad' must be a mapping of "
                         "squad path -> slot count")
    per_squad = {k.replace("/", "\\").lower(): int(v)
                 for k, v in (cfg.get("per_squad") or {}).items()}
    matched: set[str] = set()
    if not set_all and not add and not per_squad:
        return changes

    t = src.attrib_tree(TUNING)
    section = rbf.find_indexed(t, "campaign/accessory_slots/squads")
    if section is None:
        raise ValueError("accessory_slots: campaign/accessory_slots/squads "
                         "not present in this game's tuning data")
    touched = False
    for row in section.children:
        if row.type != rbf.TABLE:
            continue
        sq = rbf.find(row, "squad")
        ds = rbf.find(row, "default_slots")
        if sq is None or ds is None:
            continue
        key = str(sq.value).replace("/", "\\").lower()
        old = int(ds.value)
        if key in per_squad:
            new = per_squad[key]
            matched.add(key)
        elif set_all:
            new = set_all
        else:
            new = old + add
        new = max(0, min(UI_MAX, new))
        if new == old:
            continue
        ds.value = new
        touched = True
        changes.append({"file": src.attrib_label(TUNING),
                        "path": f"campaign/accessory_slots/{sq.value.split(chr(92))[-1]}",
                        "old": old, "new": new,
                        "tweak": f"{sq.value.split(chr(92))[-1]}: {new} slots"})
    for k in sorted(set(per_squad) - matched):
        WARNINGS.append(f"per_squad: no hero squad matches {k!r} (skipped)")
    if touched:
        src.write_attrib(TUNING, t, out_data)
    elif set_all or add:
        WARNINGS.append("every hero already had the requested slot count")
    return changes
