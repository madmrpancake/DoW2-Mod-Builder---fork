"""Loot Rarity Mix — shared constants and item classifiers."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "engine"))
import rbf  # noqa: E402,F401

# The game's four gear grades, in order, with the colour it prints each in
# (tuning_info wargear/message_colours). Verified identical in DoW2/CR and
# Retribution: there is no fifth grade — "consumable" (yellow) is a category of
# item, not a rarity, and those types are excluded from this module.
QUALITIES = ["common", "rare", "epic", "legendary"]
GRADE_COLOURS = {"common": "#ffffff", "rare": "#00ff00",
                 "epic": "#007aff", "legendary": "#ff00ff"}
CLASSES = ["chaff", "swarm", "mini_boss", "boss", "planet_boss"]
TYPES = ["weapon", "armour", "accessory", "commander_accessory"]
WG_PREFIXES = {"dow2cr": "wargear/wargear/campaign/playable",
               "retribution": "wargear/wargear/xp2/campaign"}
LEVEL_CAP = 30

# Unused items are not one thing. Each is classified into exactly ONE bucket,
# in this priority order, so the UI toggles never overlap.
UNUSED_SOURCES = ["shelved", "no_level", "unfinished", "unused_folder", "enemy_gear"]
UNUSED_LABELS = {
    "shelved":       "Shelved gear (finished, levelled, never given a pool)",
    "no_level":      "No level set (treated as droppable at any level)",
    "unfinished":    "Unfinished (missing a name or an icon — not recommended)",
    "unused_folder": "In the game's own 'unused' folder",
    "enemy_gear":    "Enemy loadout gear (chaos units' own equipment)",
}


CAMPAIGN_LABELS = {"xp1": "Chaos Rising", "space_marines": "Dawn of War II",
                   "both": "both campaigns"}


def campaign_of(path: str, campaigns=None) -> str:
    """'xp1', 'space_marines' or 'both'. The catalog knows for wargear; for
    anything else the /xp1/ folder is the marker Relic itself uses."""
    if campaigns:
        c = {x for x in campaigns if x in ("xp1", "space_marines")}
        if c == {"xp1"}:
            return "xp1"
        if c == {"space_marines"}:
            return "space_marines"
        if len(c) > 1:
            return "both"
    p = path.replace("\\", "/").lower()
    return "xp1" if "/xp1/" in p else "space_marines"


def classify_unused(path: str, level: int, named: bool, icon: bool) -> str:
    """Which bucket an item with no drop pool belongs to (first match wins)."""
    p = path.replace("\\", "/").lower()
    if "/race_chaos/" in p or "/race_ork/" in p or "/race_eldar/" in p \
            or "/race_tyranid/" in p or "/race_imperial_guard/" in p:
        return "enemy_gear"
    if "/unused/" in p:
        return "unused_folder"
    if not named or not icon:
        return "unfinished"
    if level < 1 or level > LEVEL_CAP:
        return "no_level"
    return "shelved"
