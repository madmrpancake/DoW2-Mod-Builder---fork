"""Loot Rarity Mix — projecting the grade mix a kill produces, and previews."""
from __future__ import annotations

from .common import QUALITIES, LEVEL_CAP
from .planner import plan, _apply_plan
from .rules import (ENEMY, DOW2_CAMPAIGNS, in_campaign, campaign_notes,
                    repeatable_notes, infer_game)


def project(items: list[dict], cls: str, level: int,
            window=(-2, 2), type_weights: dict | None = None) -> dict:
    """The grade mix a kill of this class would actually produce at this hero
    level: the game rolls an item TYPE by weight, then an eligible item of that
    type, where eligible means the class is in its pool and its level is inside
    the window. Returns percentages plus the eligible item count."""
    lo, hi = window
    tw = type_weights or {}
    per_type: dict[str, dict] = {}
    for i in items:
        if cls not in i["pools"]:
            continue
        if not i.get("any_level") and not (level + lo <= i["level"] <= level + hi):
            continue
        d = per_type.setdefault(i["type"], {q: 0 for q in QUALITIES})
        d[i["quality"]] += 1
    if not per_type:
        return {"n": 0, **{q: 0.0 for q in QUALITIES}}
    wsum = sum(max(0.0, float(tw.get(t, 1.0))) for t in per_type) or 1.0
    mix = {q: 0.0 for q in QUALITIES}
    n = 0
    for t, counts in per_type.items():
        tot = sum(counts.values())
        n += tot
        share = max(0.0, float(tw.get(t, 1.0))) / wsum
        for q in QUALITIES:
            mix[q] += share * (counts[q] / tot) * 100.0
    return {"n": n, **{q: round(mix[q], 1) for q in QUALITIES}}


def shortfalls(items: list[dict], after: list[dict], targets: dict, window,
               type_weights: dict | None, agnostic,
               levels=(5, 10, 15, 20, 25, 30)) -> list[str]:
    """Why a target is missed: nothing at all at a level, no items of a grade
    in the window, or no finer split. Used by preview() AND at build time."""
    notes = []
    agnostic = set(agnostic)
    for cls, mixin in targets.items():
        if not isinstance(mixin, dict):
            continue
        mix = {q: max(0.0, float(mixin.get(q, 0) or 0)) for q in QUALITIES}
        tot = sum(mix.values())
        if tot <= 0:
            continue
        rows = [{"level": lv, "planned": project(after, cls, lv, window, type_weights)}
                for lv in levels]
        empty = [r["level"] for r in rows if not r["planned"]["n"]]
        if empty:
            notes.append(f"{cls}: NOTHING can drop at level(s) "
                         f"{', '.join(map(str, empty))} — no item of the grades "
                         f"this row asks for is eligible there.")
        for q in QUALITIES:
            want = 100.0 * mix[q] / tot
            if want <= 0:
                continue
            short = [r for r in rows if r["planned"]["n"]
                     and r["planned"][q] < want * 0.6]
            if not short:
                continue
            worst = min(short, key=lambda r: r["planned"][q])
            n_avail = _ceiling(items, cls, worst["level"], q, window, q in agnostic)
            if n_avail < 3:
                notes.append(
                    f"{cls}: {round(want)}% {q} can't be reached around level "
                    f"{worst['level']} — the game only has {n_avail} {q} item(s) "
                    f"in that level window. Widen the drop level window, or tick "
                    f"{q} under 'grades that ignore the level window'.")
            else:
                notes.append(
                    f"{cls}: {q} lands at {worst['planned'][q]}% near level "
                    f"{worst['level']} rather than {round(want)}% — with "
                    f"{n_avail} {q} item(s) in the window the split can't divide "
                    f"any finer once the other grades are placed. Raise the {q} "
                    f"number if you want more of it.")
    return notes


def finalise(items: list[dict], p: dict, *, duplicate_grades=(),
             campaign_grades=(), game: str = "dow2cr") -> list[dict]:
    """The census as the build leaves it: planned pools, the any-level flag,
    and the unique / valid_campaigns changes the options ask for."""
    after = _apply_plan(items, p)
    agn = set(p.get("agnostic") or [])
    dup, camp = set(duplicate_grades), set(campaign_grades)
    for i in after:
        if i["quality"] in agn or i.get("source") == "no_level" \
                or not (1 <= i["level"] <= LEVEL_CAP):
            if i["pools"]:
                i["any_level"] = True
        if not i["pools"] & ENEMY:
            continue
        if i["quality"] in dup:
            i["unique"] = False
        if game == "dow2cr" and i["quality"] in camp and set(i.get("camps") or []) == {"xp1"}:
            i["camps"] = sorted(set(i["camps"]) | {"space_marines"})
    return after


def preview(items: list[dict], targets: dict, window=(-2, 2),
            type_weights: dict | None = None, min_per_bucket: int = 2,
            levels=(5, 10, 15, 20, 25, 30), any_level_grades=(), *,
            game: str | None = None, duplicate_grades=(), campaign_grades=()) -> dict:
    """Vanilla vs planned mix per tier, plus what each tier's ceiling is."""
    game = game or infer_game(items)
    p = plan(items, targets, min_per_bucket, type_weights, any_level_grades,
             window)
    after = finalise(items, p, duplicate_grades=duplicate_grades,
                     campaign_grades=campaign_grades, game=game)
    camps = DOW2_CAMPAIGNS if game == "dow2cr" else ()
    out = {"levels": list(levels), "tiers": {}, "notes": list(p.get("notes") or []),
           "agnostic": p.get("agnostic") or []}
    for cls in targets:
        if cls not in p["keeps"]:
            continue
        rows = []
        for lv in levels:
            row = {"level": lv,
                   "vanilla": project(items, cls, lv, window, type_weights),
                   "planned": project(after, cls, lv, window, type_weights)}
            if camps:
                row["by_campaign"] = {
                    c: project([i for i in after if in_campaign(i, c)], cls, lv,
                               window, type_weights) for c in camps}
            rows.append(row)
        out["tiers"][cls] = rows
    out["notes"] += shortfalls(items, after, targets, window, type_weights,
                               p.get("agnostic") or [], levels)
    out["notes"] += campaign_notes(after, targets, game)
    out["notes"] += repeatable_notes(after, [c for c in targets if c in p["keeps"]],
                                     window)
    out["shortfalls"] = out["notes"]
    return out


def _ceiling(items: list[dict], cls: str, level: int, quality: str, window,
             any_level: bool = False) -> int:
    """How many items of this grade the game could possibly offer here."""
    lo, hi = window
    return sum(1 for i in items if i["quality"] == quality
               and (any_level or level + lo <= i["level"] <= level + hi))
