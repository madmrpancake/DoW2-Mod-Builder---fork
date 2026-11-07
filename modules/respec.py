"""Respec module (EXPERIMENTAL) — refund trait points after every mission.

Mechanism (proven by the vanilla game): the game itself resets a squad's
attributes in mission mc1.lua using
    Campaign_SetSquadAttribute(sbps_path, LEVELING_ATTRIB_POINTS_X, n)
so a script hook can zero every hero's allocated attributes, returning ALL
points as spendable on the squad screen.

This module appends a guarded respec block to campaign/tuning.lua's
Campaign_GenerateMissionRewardXP (called at every mission end). While the
mod is installed, finishing any mission refunds every squad's attribute
points — respec freely between missions; uninstall to lock builds again.
Every call is pcall-wrapped: if the function isn't available in that
context it silently does nothing rather than crashing.

EXPERIMENTAL until verified in-game. DoW2/CR only.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

GAMES = ["dow2cr"]

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "gamedata" / "dow2cr_scripts"

SCHEMA = {
    "module": "respec",
    "title": "Respec (experimental)",
    "target_file": "campaign/tuning.lua (mission-end hook)",
    "note": "While installed, every mission end refunds ALL trait points on "
            "every hero — reassign freely on the squad screen. Uses the same "
            "engine call the game uses to rebuild Dreadnought Thule. "
            "Experimental until playtested; harmless no-op if the engine "
            "call is unavailable.",
    "options": {
        "refund_after_missions": {
            "title": "Refund points after every mission", "type": "bool",
            "default": True, "description": ""},
    },
}

WARNINGS: list[str] = []

_MARK = "-- PA_RESPEC_HOOK"


def _hero_squads(src) -> list[str]:
    from modules import unit_stats
    return [e["squad"].removesuffix(".rbf").replace("/", "\\\\")
            for e in unit_stats.catalog(src)]


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    changes: list[dict] = []
    if not cfg.get("refund_after_missions", True):
        return changes
    rel = "campaign/tuning.lua"
    emitted = out_data / rel
    if emitted.exists():
        src_p = emitted
    else:
        import bootstrap
        src_p = bootstrap.require_scripts(src) / rel
    text = src_p.read_text(encoding="utf-8", errors="replace")
    if _MARK in text:
        return changes
    anchor = "function tuning.Campaign_GenerateMissionRewardXP("
    i = text.find(anchor)
    if i < 0:
        raise ValueError("respec: Campaign_GenerateMissionRewardXP not found")
    body_start = text.index("\n", i) + 1
    squads = _hero_squads(src)
    lines = [f'\t{_MARK} (Proelium Artifex): refund all trait points at mission end',
             '\tpcall(function()',
             '\t\tlocal _pa_squads = {']
    for s in squads:
        lines.append(f'\t\t\t"{s}",')
    lines += ['\t\t}',
              '\t\tfor _, _pa_s in ipairs(_pa_squads) do',
              '\t\t\tpcall(function()',
              '\t\t\t\tCampaign_SetSquadAttribute(_pa_s, LEVELING_ATTRIB_POINTS_Health, 0)',
              '\t\t\t\tCampaign_SetSquadAttribute(_pa_s, LEVELING_ATTRIB_POINTS_Ranged, 0)',
              '\t\t\t\tCampaign_SetSquadAttribute(_pa_s, LEVELING_ATTRIB_POINTS_Melee, 0)',
              '\t\t\t\tCampaign_SetSquadAttribute(_pa_s, LEVELING_ATTRIB_POINTS_Energy, 0)',
              '\t\t\tend)',
              '\t\tend',
              '\tend)',
              '']
    text = text[:body_start] + "\n".join(lines) + text[body_start:]
    emitted.parent.mkdir(parents=True, exist_ok=True)
    emitted.write_text(text, encoding="utf-8", newline="")
    changes.append({"file": rel, "path": "Campaign_GenerateMissionRewardXP",
                    "old": "no hook", "new": f"respec {len(squads)} squads",
                    "tweak": "refund trait points after every mission"})
    WARNINGS.append("respec is EXPERIMENTAL — verify in-game that points "
                    "refund at mission end and heroes still function")
    return changes
