"""Mission Generators module — strategic-asset defences & defend missions.

The "generators" the campaign deploys around secured strategic assets
(communication arrays, imperial shrines, automated foundries) are driven by
two scar scripts (effective patch-priority copies from 220_data.sga):

  quests/defend/defenddata.scar — the defend-the-asset missions:
      numberOfWaves = 4 per scenario block, waveSpawnRate (secs between
      encounter spawns inside a wave)
  stratagems.scar — what secured assets grant:
      quantityPerPlanetStratagem = 1  (Signum / Rosarius / Locator Beacon
      items granted per secured asset each mission)
      captureCount = 1 (assets needed before the benefit switches on)

Ships edited scar in the mod's Data archive, mounted above every game
archive. Player-facing knobs only; blank/defaults keep vanilla.

Config: {"defend_waves": 4, "defend_spawn_rate_multiplier": 1.0,
         "items_per_asset": 1}
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

GAMES = ["dow2cr"]

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "gamedata" / "dow2cr_scripts"
DEFEND = "simulation/scar/proceduralcontent/quests/defend/defenddata.scar"
STRAT = "simulation/scar/proceduralcontent/stratagems.scar"

SCHEMA = {
    "module": "mission_generators",
    "title": "Mission Generators (strategic assets)",
    "target_file": "simulation/scar/proceduralcontent/**  (defend + stratagems)",
    "note": "Tunes the generator-defence missions around secured arrays / "
            "shrines / foundries, and how many bonus items (Signum, "
            "Rosarius, Locator Beacon) each secured asset grants per mission.",
    "options": {
        "defend_waves": {
            "title": "Defend mission waves", "type": "int", "default": 4,
            "min": 1, "max": 12, "vanilla": 4,
            "description": "Enemy waves per generator-defence mission."},
        "defend_spawn_rate_multiplier": {
            "title": "Wave spawn interval x", "type": "float", "default": 1.0,
            "min": 0.25, "max": 4,
            "description": "Multiplies the seconds between encounter spawns "
                           "inside a wave — below 1.0 = more frantic."},
        "items_per_asset": {
            "title": "Items per secured asset", "type": "int", "default": 1,
            "min": 0, "max": 5, "vanilla": 1,
            "description": "Signums / Rosarii / Locator Beacons granted per "
                           "secured asset at each mission start."},
    },
}

WARNINGS: list[str] = []


def _edit_numbers(text: str, name: str, new_val, changes: list, rel: str,
                  transform=None) -> tuple[str, bool]:
    touched = False
    out = []
    pat = re.compile(rf"^(\s*{name}\s*=\s*)([\d.]+)(\s*,?)(.*)$")
    for line in text.split("\n"):
        m = pat.match(line)
        if m and not line.lstrip().startswith("--"):
            old = float(m.group(2))
            new = transform(old) if transform else new_val
            new_s = str(int(new)) if float(new).is_integer() else f"{new:g}"
            if float(new) != old:
                line = f"{m.group(1)}{new_s}{m.group(3)}{m.group(4)}"
                touched = True
                changes.append({"file": rel, "path": name,
                                "old": old if old != int(old) else int(old),
                                "new": int(new) if float(new).is_integer() else new,
                                "tweak": f"{name} -> {new_s}"})
        out.append(line)
    return "\n".join(out), touched


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    changes: list[dict] = []
    waves = int(cfg.get("defend_waves", 4))
    rate_m = float(cfg.get("defend_spawn_rate_multiplier", 1.0))
    items = int(cfg.get("items_per_asset", 1))

    for rel, edits in (
        (DEFEND, [("numberOfWaves", waves, None),
                  ("waveSpawnRate", None,
                   (lambda old: max(1.0, round(old * rate_m, 2))) if rate_m != 1.0 else None)]),
        (STRAT, [("quantityPerPlanetStratagem", items, None)]),
    ):
        import bootstrap
        srcp = bootstrap.require_scripts(src) / rel
        if not srcp.exists():
            raise ValueError(
                f"This option edits {rel}, which isn't present in your game "
                "install's scripts — the game may be a different edition or "
                "patch level than this option expects.")
        text = srcp.read_text(encoding="utf-8", errors="replace")
        any_touched = False
        for name, val, transform in edits:
            if transform is None and val is None:
                continue
            if transform is None and name == "numberOfWaves" and val == 4:
                continue
            if transform is None and name == "quantityPerPlanetStratagem" and val == 1:
                continue
            text, touched = _edit_numbers(text, name, val, changes, rel,
                                          transform=transform)
            any_touched = any_touched or touched
        if any_touched:
            dst = out_data / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8", newline="")
    return changes
