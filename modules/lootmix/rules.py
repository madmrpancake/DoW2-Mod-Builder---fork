"""Loot Rarity Mix — the game rules the builder models beyond pool membership (1.2.6).

* `unique`: every rare/epic/legendary ships unique=True and the game never re-drops
  a unique item the player already has. Vanilla keeps ~111 non-unique commons in the
  enemy pools as repeatable filler; a mix with commons at 0% removes them all.
* `valid_campaigns`: DoW2/CR items are gated to 'space_marines' (base campaign)
  and/or 'xp1' (Chaos Rising). Every legendary is xp1-only. Retribution gates per race.
* placeholder items: unfinished entries with no defence, weapon, buff or action.
"""
from __future__ import annotations

from .common import rbf, QUALITIES, CLASSES, LEVEL_CAP, CAMPAIGN_LABELS

ENEMY = set(CLASSES)
DOW2_CAMPAIGNS = ("space_marines", "xp1")
_STAT_KEYS = ("weapons", "on_equip_buffs", "on_equip_squad_actions",
              "on_equip_entity_actions", "owner_modifiers",
              "on_grant_entity_actions", "on_grant_player_actions")


def _has_value(n) -> bool:
    if not n.children:
        return bool(n.value) and n.key != "$REF"
    return any(_has_value(c) for c in n.children)


def zero_stat(bag) -> bool:
    """True for a placeholder: no defence and nothing it grants or fires."""
    d = rbf.find(bag, "defence")
    if d is not None and d.value:
        return False
    for key in _STAT_KEYS:
        n = rbf.find(bag, key)
        if n is not None and _has_value(n):
            return False
    return True


def infer_game(items: list[dict]) -> str:
    """Retribution gates by race ('xp2_marine' ...); DoW2/CR by expansion."""
    return "retribution" if any(c.startswith("xp2") for i in items
                                for c in i.get("camps") or []) else "dow2cr"


def in_campaign(item: dict, camp: str) -> bool:
    """An empty valid_campaigns list is treated as unrestricted."""
    return not item.get("camps") or camp in item["camps"]


def _ranges(levels: list[int]) -> str:
    out, start, prev = [], None, None
    for lv in sorted(levels):
        if start is None:
            start = prev = lv
        elif lv == prev + 1:
            prev = lv
        else:
            out.append(f"{start}" if start == prev else f"{start}-{prev}")
            start = prev = lv
    if start is not None:
        out.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(out)


def _eligible(items, cls, lv, window):
    lo, hi = window
    return [i for i in items if cls in i["pools"]
            and (i.get("any_level") or lv + lo <= i["level"] <= lv + hi)]


def repeatable_notes(after: list[dict], classes, window) -> list[str]:
    """Warn per enemy class where every eligible item is one-of-a-kind."""
    notes = []
    for cls in classes:
        bad = []
        for lv in range(1, LEVEL_CAP + 1):
            el = _eligible(after, cls, lv, window)
            if el and not any(not i.get("unique", True) for i in el):
                bad.append(lv)
        if bad:
            notes.append(
                f"{cls}: every drop is one-of-a-kind at level(s) {_ranges(bad)}. "
                f"The game never drops a unique item you already have, so once "
                f"they're collected {cls} stops dropping gear. Keep some common %, "
                f"or tick 'Allow duplicates'.")
    return notes


def campaign_notes(after: list[dict], targets: dict, game: str) -> list[str]:
    """dow2cr: a row asks for a grade that no item in its pool may drop in a campaign."""
    if game != "dow2cr":
        return []
    notes = []
    for camp in DOW2_CAMPAIGNS:
        for q in QUALITIES:
            rows = [cls for cls, mix in targets.items() if cls in ENEMY
                    and isinstance(mix, dict) and float(mix.get(q, 0) or 0) > 0
                    and not any(i["quality"] == q and cls in i["pools"]
                                and in_campaign(i, camp) for i in after)]
            if rows:
                other = [c for c in DOW2_CAMPAIGNS if c != camp][0]
                hint = (" Tick it under 'Chaos Rising gear in the base campaign' "
                        "(experimental)." if camp == "space_marines" else "")
                notes.append(
                    f"{', '.join(rows)}: asks for {q}, but no {q} in that pool can "
                    f"drop in the {CAMPAIGN_LABELS[camp]} campaign — the game flags "
                    f"them {CAMPAIGN_LABELS[other]} only.{hint}")
    return notes


def campaign_counts(after: list[dict], game: str) -> str:
    """Retribution: each race campaign only sees gear gated to that race."""
    if game != "retribution":
        return ""
    tally: dict[str, int] = {}
    n = 0
    for i in after:
        if not i["pools"] & ENEMY:
            continue
        n += 1
        for c in i.get("camps") or ["(any)"]:
            tally[c] = tally.get(c, 0) + 1
    return ("items in enemy pools per race campaign (of " + str(n) + "): "
            + ", ".join(f"{k} {v}" for k, v in sorted(tally.items())))
