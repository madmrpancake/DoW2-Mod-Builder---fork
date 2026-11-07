"""Campaign Pacing module — mission timers and deployments per day.

Verified sources (extracted at true patch priority
240>230>220>210>200>DELTA>base into gamedata/dow2cr_scripts):
  campaign/tuning.lua
      max_deployments = 3                     (base DoW2 campaign, per day)
      Campaign_CalculateMaxDeploymentsPerDay(): returns hardcoded 1 for xp1
      mission_urgency_threshold = 3           (UI "urgent" marker)
  campaign/<campaign>/missions/*.lua
      days_till_expiry = N   on timed side missions (61 files across
      space_marines + xp1)

Edited lua ships in the mod's Data archive (alias DATA), mounted above every
game archive, so it wins at load time. Non-destructive like everything else.

Config:
    {"days_till_expiry_multiplier": 2.0,   # or days_till_expiry_set
     "days_till_expiry_set": 0,            # 0 = unused
     "max_deployments": 3,                 # base campaign, per day
     "xp1_deployments": 1}                 # Chaos Rising, per day
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

GAMES = ["dow2cr"]

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "gamedata" / "dow2cr_scripts"

SCHEMA = {
    "module": "campaign_pacing",
    "title": "Campaign Pacing",
    "target_file": "campaign/tuning.lua + campaign/*/missions/*.lua",
    "note": "Longer mission timers and more deployments per day. Mission "
            "expiry only applies to timed side missions; story missions "
            "never expire.",
    "options": {
        "days_till_expiry_multiplier": {
            "title": "Mission timer x", "type": "float", "default": 1.0,
            "min": 0.5, "max": 10,
            "description": "Multiplies days_till_expiry on every timed side "
                           "mission (vanilla is 3 days). Ignored if a fixed "
                           "value is set below."},
        "days_till_expiry_set": {
            "title": "Mission timer fixed (days)", "type": "int", "default": 0,
            "min": 0, "max": 99,
            "description": "Set every timed mission to exactly this many days. "
                           "0 = use the multiplier instead."},
        "max_deployments": {
            "title": "Deployments per day (Dawn of War II)", "type": "int", "default": 3,
            "min": 1, "max": 10,
            "description": "Base-campaign missions per day before the day "
                           "advances (vanilla 3)."},
        "xp1_deployments": {
            "title": "Deployments per day (Chaos Rising)", "type": "int",
            "default": 1, "min": 1, "max": 10,
            "description": "Chaos Rising is hardcoded to 1 deployment per "
                           "day in vanilla."},
    },
}

WARNINGS: list[str] = []

_EXPIRY_RE = re.compile(r"^(\s*)days_till_expiry(\s*)=(\s*)(\d+)(\s*,?)", re.M)


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    import bootstrap
    bootstrap.require_scripts(src)          # reads them from your install if
    #                                         the one-time setup hasn't run yet
    mult = float(cfg.get("days_till_expiry_multiplier", 1.0))
    fixed = int(cfg.get("days_till_expiry_set", 0) or 0)
    max_dep = int(cfg.get("max_deployments", 3))
    xp1_dep = int(cfg.get("xp1_deployments", 1))
    changes: list[dict] = []

    def emit(rel: str, text: str):
        dst = out_data / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text, encoding="utf-8", newline="")

    # ---- tuning.lua (chain: re-read an already-emitted copy so this
    # module and xp_tuning can both edit it in one build) ------------------
    tuning_rel = "campaign/tuning.lua"
    _emitted = out_data / tuning_rel
    tuning = (_emitted if _emitted.exists() else SCRIPTS / tuning_rel
              ).read_text(encoding="utf-8", errors="replace")
    tuning_touched = False
    m = re.search(r"^(\s*)max_deployments(\s*)=(\s*)(\d+)\s*,", tuning, re.M)
    if m:
        old = int(m.group(4))
        if max_dep != old:
            tuning = tuning[:m.start()] + \
                f"{m.group(1)}max_deployments{m.group(2)}={m.group(3)}{max_dep}," + \
                tuning[m.end():]
            tuning_touched = True
            changes.append({"file": tuning_rel, "path": "max_deployments",
                            "old": old, "new": max_dep,
                            "tweak": f"deployments/day = {max_dep}"})
    else:
        WARNINGS.append("tuning.lua: max_deployments assignment not found")
    # xp1 hardcoded `return 1` inside Campaign_CalculateMaxDeploymentsPerDay
    fn = re.search(
        r"(function\s+tuning\.Campaign_CalculateMaxDeploymentsPerDay\s*\(\s*\).*?"
        r"if\s+Campaign_GetCampaignID\(\)\s*==\s*\"xp1\"\s*then\s*\n\s*return\s+)(\d+)",
        tuning, re.S)
    if fn:
        old = int(fn.group(2))
        if xp1_dep != old:
            tuning = tuning[:fn.start(2)] + str(xp1_dep) + tuning[fn.end(2):]
            tuning_touched = True
            changes.append({"file": tuning_rel,
                            "path": "Campaign_CalculateMaxDeploymentsPerDay/xp1",
                            "old": old, "new": xp1_dep,
                            "tweak": f"CR deployments/day = {xp1_dep}"})
    else:
        WARNINGS.append("tuning.lua: xp1 deployment branch not found")
    if tuning_touched:
        emit(tuning_rel, tuning)

    # ---- mission timers --------------------------------------------------
    if fixed > 0 or mult != 1.0:
        for f in sorted(SCRIPTS.glob("campaign/*/missions/*.lua")):
            rel = str(f.relative_to(SCRIPTS)).replace("\\", "/")
            text = f.read_text(encoding="utf-8", errors="replace")
            touched = False

            def sub(m):
                nonlocal touched
                old = int(m.group(4))
                new = fixed if fixed > 0 else max(1, int(old * mult + 0.5))
                if new == old:
                    return m.group(0)
                touched = True
                changes.append({"file": rel, "path": "days_till_expiry",
                                "old": old, "new": new,
                                "tweak": f"timer {old} -> {new} days"})
                return f"{m.group(1)}days_till_expiry{m.group(2)}={m.group(3)}{new}{m.group(5)}"

            # only lines that are not commented out
            out_lines = []
            for line in text.split("\n"):
                if "days_till_expiry" in line and not line.lstrip().startswith("--"):
                    line = _EXPIRY_RE.sub(sub, line)
                out_lines.append(line)
            if touched:
                emit(rel, "\n".join(out_lines))
    return changes
