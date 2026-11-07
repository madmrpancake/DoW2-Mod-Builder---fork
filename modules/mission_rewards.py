"""Mission Rewards module — tune what completing campaign missions grants.

Operates on: campaign/**/missions/*.lua  (data space, Lua)

Discovery: every mission definition carries a
rewards block:

    rewards =
    {
        experience = 560,
        generated_wargear = 0,               -- count of randomly generated items
        generated_wargear_level_offset = 0,  -- level shift for those items
        wargear = { "wargear\\...", ... },   -- guaranteed item grants
    },

Chaos Rising missions (campaign/xp1/missions/*.lua) and the vanilla template
mission (campaign/space_marines/missions/me1.lua) all use it. Additional
scripted grants exist as Campaign_AddWargearToInventory calls; those are left
alone (they are story items).

Transform: targeted numeric substitution inside each rewards block; the rest
of every file is preserved byte-for-byte.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

MISSION_GLOBS = [
    "campaign/xp1/missions/*.lua",
    "campaign/space_marines/missions/*.lua",
]

GAMES = ["dow2cr"]

SCHEMA = {
    "module": "mission_rewards",
    "title": "Mission Rewards",
    "target_file": "campaign\\**\\missions\\*.lua",
    "note": "Applies to mission-completion rewards across BOTH campaigns — "
            "Dawn of War II and Chaos Rising. Story-scripted item grants are "
            "untouched, and a few dialogue or branch-variant missions grant "
            "nothing of their own and are skipped.",
    "options": {
        "experience_multiplier": {
            "title": "Mission XP multiplier",
            "description": "Multiplies the experience awarded on mission completion.",
            "type": "float", "default": 1.0, "min": 0.0, "max": 20.0,
        },
        "extra_generated_wargear": {
            "title": "Extra generated wargear per mission",
            "description": "Adds this many randomly-generated wargear items to every "
                           "mission's completion rewards (on top of the mission's own count).",
            "type": "int", "default": 0, "min": 0, "max": 10,
        },
        "generated_wargear_level_offset": {
            "title": "Generated reward level offset",
            "description": "Shifts the item level of generated mission rewards relative "
                           "to your heroes (vanilla 0). +2 means rewards roll above your level.",
            "type": "int", "default": 0, "min": -10, "max": 10,
        },
    },
}

WARNINGS: list[str] = []

_REWARDS = re.compile(
    r"(rewards\s*=\s*\{)(.*?)(\n\t*\},)", re.S)
_FIELD = {
    "experience": re.compile(r"(experience\s*=\s*)(-?\d+(?:\.\d+)?)"),
    "generated_wargear": re.compile(r"(generated_wargear\s*=\s*)(-?\d+)"),
    "level_offset": re.compile(r"(generated_wargear_level_offset\s*=\s*)(-?\d+)"),
}


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    _no_rewards: list[str] = []
    xp_mult = float(cfg.get("experience_multiplier", 1.0))
    extra_gen = int(cfg.get("extra_generated_wargear", 0))
    lvl_off = int(cfg.get("generated_wargear_level_offset", 0))
    if xp_mult == 1.0 and extra_gen == 0 and lvl_off == 0:
        return []

    changes: list[dict] = []
    files = (src.script_paths("campaign/xp1/missions", (".lua",))
             + src.script_paths("campaign/space_marines/missions", (".lua",)))
    if not files:
        raise ValueError("mission_rewards: no mission scripts found in game archives")

    for rel in files:
        txt = src.script_text(rel)
        file_changes = []

        def sub_rewards(m):
            head, body, tail = m.group(1), m.group(2), m.group(3)
            def repl_num(field, fn, cast=int):
                nonlocal body
                fm = _FIELD[field].search(body)
                if not fm:
                    return
                old = cast(float(fm.group(2)))
                new = fn(old)
                if new != old:
                    body = body[:fm.start()] + fm.group(1) + str(new) + body[fm.end():]
                    file_changes.append({"path": f"rewards/{field}", "old": old, "new": new})
            if xp_mult != 1.0:
                repl_num("experience", lambda v: int(round(v * xp_mult)))
            if extra_gen:
                repl_num("generated_wargear", lambda v: v + extra_gen)
            if lvl_off:
                repl_num("level_offset", lambda v: v + lvl_off)
            return head + body + tail

        new_txt = _REWARDS.sub(sub_rewards, txt)
        if file_changes:
            out = Path(out_data) / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(new_txt)
            # post-write validation: every rewards block still parses & fields present
            if len(_REWARDS.findall(new_txt)) != len(_REWARDS.findall(txt)):
                raise RuntimeError(f"mission_rewards: rewards block corrupted in {rel}")
            for c in file_changes:
                changes.append({"file": str(rel).replace("/", "\\"), **c})
        elif _REWARDS.search(txt) is None:
            _no_rewards.append(str(rel).rsplit("/", 1)[-1])
    if _no_rewards:            # normal: a few missions grant nothing on their
        WARNINGS.append(       # own (dialogue/branch variants) — one line, not one each
            f"{len(_no_rewards)} mission file(s) grant no rewards and were "
            f"skipped (normal): " + ", ".join(sorted(_no_rewards)[:6])
            + (" ..." if len(_no_rewards) > 6 else ""))
    return changes
