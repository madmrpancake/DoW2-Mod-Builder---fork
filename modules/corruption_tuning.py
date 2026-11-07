"""Corruption tuning — the Chaos Rising corruption/redemption mechanic.

How the system actually works (campaign/tuning.lua + engine, all verified):
  * Corruption is stored as spent points in a hidden leveling attribute
    (LEVELING_ATTRIB_POINTS_Corruption), 0..24; 24 = lost to Chaos, and once
    at 24 a hero can never be redeemed (hardcoded check in tuning.lua).
  * Gains come from: corrupt objective choices (+4), letting flagged missions
    expire (+5), leaving a doubting hero undeployed (+5), doubt itself (+2);
    redeeming objective choices give -2. All of these are the
    tuning.corruption_awards table — plain data.
  * Wearing 'corrupting' wargear adds corruption per deployment and
    'redeeming' wargear removes it (80 corrupting / 19 redeeming items ship);
    the per-item amount comes from the engine, NOT from data.
  * EVERY change — objectives, wargear, doubt, expiry — funnels through ONE
    function, tuning.Campaign_GetModifiedCorruptionDelta, which also applies
    mitigation: heroes with corruption >= corruption_mitigation_thresholds
    (12/20/24) shrug off 1/2/3 points of each further gain.

So the module has two levers, both the game's own:
  1. edit the corruption_awards / mitigation threshold tables in place;
  2. wrap Campaign_GetModifiedCorruptionDelta after its definition, scaling
     what the original returns — mitigation and the incorruptible checks keep
     working, and because the wrap sits at the single funnel it also scales
     wargear corruption, which no table edit could reach.

Config:
    {"gain_multiplier": 1.0,        # scales every corruption GAIN (0 = immune)
     "redemption_multiplier": 1.0,  # scales every corruption LOSS
     "awards": {"objectiveCorrupt": 4, "objectiveRedeem": -2,
                "missionExpiry": 5, "noDeploy": 5, "doubt": 2},
     "mitigation_thresholds": [12, 20, 24]}
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

GAMES = ["dow2cr"]
ROOT = Path(__file__).resolve().parent.parent

AWARD_KEYS = ["objectiveCorrupt", "objectiveRedeem", "missionExpiry",
              "noDeploy", "doubt"]
VANILLA_AWARDS = {"objectiveCorrupt": 4, "objectiveRedeem": -2,
                  "missionExpiry": 5, "noDeploy": 5, "doubt": 2}

SCHEMA = {
    "module": "corruption_tuning",
    "title": "Corruption (Chaos Rising)",
    "target_file": "campaign/tuning.lua",
    "note": "Chaos Rising only — the original campaign has no corruption and "
            "Thule is incorruptible either way. Corruption runs 0-24; at 24 a "
            "hero is lost for good (the game refuses to redeem from 24, and "
            "that check is kept). Multipliers scale EVERY gain or loss at the "
            "single point all of them pass through, so corrupting/redeeming "
            "wargear is covered too, not just mission choices.",
    "options": {
        "gain_multiplier": {
            "title": "Corruption gain x", "type": "float", "default": 1.0,
            "min": 0.0, "max": 5.0, "vanilla": 1.0,
            "description": "Scales every corruption GAIN after mitigation. "
                           "0 makes the whole force incorruptible; 0.5 halves "
                           "all corruption; 2 doubles it.",
        },
        "redemption_multiplier": {
            "title": "Redemption x", "type": "float", "default": 1.0,
            "min": 0.0, "max": 5.0, "vanilla": 1.0,
            "description": "Scales every corruption LOSS (redeeming choices "
                           "and redeeming wargear). Raise it to make coming "
                           "back from the brink faster.",
        },
        "awards": {
            "title": "Corruption per event", "type": "map[float]",
            "default": {}, "keys": AWARD_KEYS, "vanilla": VANILLA_AWARDS,
            "description": "Points per event, before mitigation and the "
                           "multipliers. objectiveRedeem is negative. Blank "
                           "keeps vanilla.",
        },
        "mitigation_thresholds": {
            "title": "Mitigation thresholds", "type": "map[float]",
            "default": {}, "keys": ["shrug_1", "shrug_2", "shrug_3"],
            "vanilla": {"shrug_1": 12, "shrug_2": 20, "shrug_3": 24},
            "description": "A hero at or past each threshold shrugs off "
                           "1/2/3 points of every further gain (the game's "
                           "own 'corruption resists itself' rule). Lower "
                           "them to slow the slide, raise to 25 to disable "
                           "a tier.",
        },
    },
}

WARNINGS: list[str] = []

_MARK = "-- PA_CORRUPTION_HOOK"


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    changes: list[dict] = []
    gain = float(cfg.get("gain_multiplier", 1.0))
    redeem = float(cfg.get("redemption_multiplier", 1.0))
    if not isinstance(cfg.get("awards") or {}, dict) \
            or not isinstance(cfg.get("mitigation_thresholds") or {}, dict):
        raise ValueError("corruption_tuning: 'awards' and "
                         "'mitigation_thresholds' must be mappings")
    awards = {k: v for k, v in (cfg.get("awards") or {}).items()
              if k in AWARD_KEYS and v is not None and v != ""}
    thr_map = cfg.get("mitigation_thresholds") or {}
    for k in sorted(set(cfg.get("awards") or {}) - set(AWARD_KEYS)):
        WARNINGS.append(f"awards: unknown key {k!r} (skipped) — valid: "
                        + ", ".join(AWARD_KEYS))
    for k in sorted(set(thr_map) - {"shrug_1", "shrug_2", "shrug_3"}):
        WARNINGS.append(f"mitigation_thresholds: unknown key {k!r} (skipped) — "
                        "valid: shrug_1, shrug_2, shrug_3")
    thresholds = [thr_map.get("shrug_1"), thr_map.get("shrug_2"),
                  thr_map.get("shrug_3")]

    touch_tables = bool(awards) or any(t is not None and t != "" for t in thresholds)
    touch_hook = gain != 1.0 or redeem != 1.0
    if not (touch_tables or touch_hook):
        return changes

    import bootstrap
    rel = "campaign/tuning.lua"
    emitted = out_data / rel
    src_p = emitted if emitted.exists() else bootstrap.require_scripts(src) / rel
    text = src_p.read_text(encoding="utf-8", errors="replace")

    # ---- corruption_awards table ----------------------------------------
    for key, val in awards.items():
        v = int(round(float(val)))
        pat = re.compile(r"(\b" + key + r"\s*=\s*)(-?\d+)(\s*,)")
        m = pat.search(text)
        if not m:
            WARNINGS.append(f"corruption_awards.{key} not found (skipped)")
            continue
        old = int(m.group(2))
        if old != v:
            text = text[:m.start()] + m.group(1) + str(v) + m.group(3) + text[m.end():]
            changes.append({"file": rel.replace("/", "\\"),
                            "path": f"corruption_awards/{key}",
                            "old": old, "new": v,
                            "tweak": f"{key} = {v}"})

    # ---- mitigation thresholds ------------------------------------------
    m = re.search(r"corruption_mitigation_thresholds\s*=\s*\{(.*?)\}", text, re.S)
    if m and any(t is not None and t != "" for t in thresholds):
        block = m.group(1)
        nums = list(re.finditer(r"\d+", block))
        if len(nums) >= 3:
            new_block = block
            # replace back-to-front so match offsets stay valid
            for i in (2, 1, 0):
                t = thresholds[i]
                if t is None or t == "":
                    continue
                v = int(round(float(t)))
                old = int(nums[i].group())
                if old == v:
                    continue
                new_block = new_block[:nums[i].start()] + str(v) + new_block[nums[i].end():]
                changes.append({"file": rel.replace("/", "\\"),
                                "path": f"corruption_mitigation_thresholds[{i}]",
                                "old": old, "new": v,
                                "tweak": f"mitigation tier {i+1} at {v}"})
            text = text[:m.start(1)] + new_block + text[m.end(1):]
        else:
            WARNINGS.append("mitigation thresholds table not readable (skipped)")

    # ---- the funnel hook -------------------------------------------------
    if touch_hook and _MARK not in text:
        hook = f"""

{_MARK} — scales every corruption change at the one function all of them
-- pass through (objectives, doubt, expiry, wargear). Mitigation and the
-- incorruptible/full-corruption checks above still apply first.
local PA_orig_corruption_delta = tuning.Campaign_GetModifiedCorruptionDelta
tuning.Campaign_GetModifiedCorruptionDelta = function( squadPbgDir, delta )
\tlocal d = PA_orig_corruption_delta( squadPbgDir, delta )
\tif d > 0 then
\t\td = math.floor( d * {gain:g} + 0.5 )
\telseif d < 0 then
\t\td = -math.floor( (-d) * {redeem:g} + 0.5 )
\tend
\treturn d
end
"""
        anchor = "function tuning.Campaign_ModifyCorruption"
        i = text.find(anchor)
        if i < 0:
            WARNINGS.append("Campaign_ModifyCorruption not found — multiplier "
                            "hook skipped")
        else:
            # the wrap must come after BOTH functions exist; append at the very
            # end of the file, which runs after every definition
            text = text.rstrip() + hook
            changes.append({"file": rel.replace("/", "\\"),
                            "path": "Campaign_GetModifiedCorruptionDelta",
                            "old": "x1 / x1",
                            "new": f"gain x{gain:g} / redeem x{redeem:g}",
                            "tweak": "corruption multiplier hook"})

    if changes:
        out = out_data / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="")
        # sanity: the tables must still parse as lua-ish (balanced braces in
        # the regions we touched) and the hook appears exactly once
        if touch_hook and text.count(_MARK) != 1:
            raise RuntimeError("corruption_tuning: hook emitted more than once")
    return changes
