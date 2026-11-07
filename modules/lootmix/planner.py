"""Loot Rarity Mix — deciding which items stay in each enemy class's pool."""
from __future__ import annotations

from .common import QUALITIES, CLASSES, LEVEL_CAP
from .rules import _ranges


def _mix_of(keeps: dict, tw: dict) -> dict:
    """Grade mix produced by a keep-plan, modelling the game's roll: type first
    (by wargear_type_drop_probabilities), then an eligible item of that type."""
    live = {t: k for t, k in keeps.items() if sum(k.values()) > 0}
    if not live:
        return {q: 0.0 for q in QUALITIES}
    wsum = sum(max(0.0, float(tw.get(t, 1.0))) for t in live) or 1.0
    mix = {q: 0.0 for q in QUALITIES}
    for t, k in live.items():
        tot = sum(k.values())
        share = max(0.0, float(tw.get(t, 1.0))) / wsum
        for q in QUALITIES:
            mix[q] += share * k[q] / tot
    return mix


def _allocate(avail: dict, wanted: dict, tw: dict, floor: int,
              fixed: dict | None = None) -> dict:
    """How many items of each grade to leave eligible, per item type.

    A grade that exists in only one type still has to reach its target share of
    ALL drops, so the split cannot be decided type by type: the allocator starts
    proportional, then trades single slots between grades — leaning on the types
    that actually hold the scarce grade — until the modelled mix stops getting
    closer to the target. Cheap (a few hundred integer steps per level) and
    deterministic.
    """
    fixed = fixed or {}
    keeps = {t: {q: 0 for q in QUALITIES} for t in avail}
    for t, per_q in avail.items():
        for q, n in (fixed.get(t) or {}).items():
            keeps[t][q] = min(int(n), len(per_q[q]))
        pinned = set((fixed.get(t) or {}))
        scales = [len(per_q[q]) / w for q, w in wanted.items()
                  if w > 0 and per_q[q] and q not in pinned]
        scale = min(scales) if scales else 0.0
        for q in QUALITIES:
            if wanted[q] <= 0 or q in pinned:
                continue
            n = int(round(wanted[q] * scale))
            if per_q[q]:
                n = max(n, min(floor, len(per_q[q])))
            keeps[t][q] = min(n, len(per_q[q]))
        if sum(keeps[t].values()) == 0:      # never leave a type with no items
            for q in QUALITIES:
                if wanted[q] > 0 and per_q[q]:
                    keeps[t][q] = 1
                    break

    def err(k):
        m = _mix_of(k, tw)
        return sum(abs(m[q] - wanted[q]) for q in QUALITIES)

    def pinned_at(t, q):
        return q in (fixed.get(t) or {})

    def can_drop(k, t, q):
        return (not pinned_at(t, q) and k[t][q] > 0 and sum(k[t].values()) > 1
                and k[t][q] > min(floor, len(avail[t][q])))

    best = err(keeps)
    for _ in range(600):
        m = _mix_of(keeps, tw)
        low = max((q for q in QUALITIES if wanted[q] > 0),
                  key=lambda q: wanted[q] - m[q], default=None)
        high = max(QUALITIES, key=lambda q: m[q] - wanted[q])
        if low is None:
            break
        moves = []
        for t in avail:
            room = (not pinned_at(t, low)) and keeps[t][low] < len(avail[t][low])
            if room:                                    # more of the scarce grade
                moves.append([(t, low, +1)])
            if can_drop(keeps, t, high):                # less of the excess grade
                moves.append([(t, high, -1)])
                if room:                                # both, inside one type:
                    moves.append([(t, low, +1), (t, high, -1)])
            for t2 in avail:                            # or across two types
                if room and t2 != t and can_drop(keeps, t2, high):
                    moves.append([(t, low, +1), (t2, high, -1)])
        improved = None
        for mv in moves:
            trial = {tt: dict(kk) for tt, kk in keeps.items()}
            for t, q, d in mv:
                trial[t][q] += d
            e = err(trial)
            if e < best - 1e-9 and (improved is None or e < improved[1]):
                improved = (trial, e)
        if improved is None:
            break
        keeps, best = improved
    return keeps


def plan(items: list[dict], targets: dict, min_per_bucket: int = 2,
         type_weights: dict | None = None,
         any_level_grades=(), window=(-2, 2)) -> dict:
    """Decide, per enemy class, which items stay eligible.

    Two passes. Per level, an allocator picks how many items of each grade and
    type to leave in the pool. Grades told to ignore the level window are not a
    per-level decision — one set of items is eligible at every level — so a
    second pass picks the single count per (type, grade) that fits all levels
    best, and the per-level pass runs again around it.
    """
    add: dict[str, set] = {}
    remove: dict[str, set] = {}
    keeps_out: dict[str, dict] = {}
    tw = type_weights or {}
    agnostic = {q for q in any_level_grades if q in QUALITIES}
    types = sorted({i["type"] for i in items})
    # An item with no level cannot be placed in a level band, so it is eligible
    # at every level instead — otherwise it is scanned, counted and then never
    # chosen (119 items in DoW2/CR before 1.2.5).
    levelfree = {i["path"] for i in items
                 if i.get("source") == "no_level" or not (1 <= i["level"] <= LEVEL_CAP)}

    # Never ship an empty tier (1.2.6). If, at some level, none of the grades a
    # row asks for has an item inside the drop window, that enemy would drop
    # NOTHING there — the allocator can only choose among what exists. Make the
    # asked grades ignore the window instead (plan-wide: the flag is per item),
    # and say so. A grade that is merely short is a shortfall note, not this.
    auto_notes: list[str] = []
    lo, hi = window
    base_agn = set(agnostic)
    hit: dict[tuple, list] = {}          # (grades fixed) -> [(cls, empty levels)]
    for cls, mix in targets.items():
        if cls not in CLASSES or not isinstance(mix, dict):
            continue
        asked = {q for q in QUALITIES if float(mix.get(q, 0) or 0) > 0}
        if not asked or asked & base_agn:
            continue
        have = [i for i in items if i["quality"] in asked]
        if not have or any(i["path"] in levelfree or i.get("any_level")
                           for i in have):
            continue
        empty = [lv for lv in range(1, LEVEL_CAP + 1)
                 if not any(lv + lo <= i["level"] <= lv + hi for i in have)]
        if empty:
            fix = tuple(sorted({i["quality"] for i in have}, key=QUALITIES.index))
            agnostic |= set(fix)
            hit.setdefault(fix, []).append((cls, empty))
    for fix, rows in hit.items():
        auto_notes.append(
            "; ".join(f"{c} would drop NOTHING at level(s) {_ranges(e)}" for c, e in rows)
            + f" — the game has no {'/'.join(fix)} item in the drop window there. "
            f"{'/'.join(fix)} now ignore(s) the level window, the same as ticking it "
            f"under 'Grades that ignore the level window'.")

    for cls, mix in targets.items():
        if cls not in CLASSES:
            continue
        wanted = {q: max(0.0, float(mix.get(q, 0) or 0)) for q in QUALITIES}
        total = sum(wanted.values())
        if total <= 0:
            continue                        # blank row: leave this tier alone
        wanted = {q: v / total for q, v in wanted.items()}
        order = lambda i: (cls not in i["pools"], i["path"])   # noqa: E731

        free = {ty: {q: sorted((i for i in items if i["type"] == ty
                                and i["quality"] == q
                                and (q in agnostic or i["path"] in levelfree)),
                               key=order)
                     for q in QUALITIES} for ty in types}
        levelled = {ty: {lv: {q: sorted((i for i in items if i["type"] == ty
                                         and i["level"] == lv
                                         and i["quality"] == q
                                         and q not in agnostic
                                         and i["path"] not in levelfree), key=order)
                              for q in QUALITIES}
                         for lv in range(1, LEVEL_CAP + 1)} for ty in types}

        lo, hi = window
        width = max(1, hi - lo + 1)

        def alloc(level, fixed):
            """Allocate for what a hero at this level can actually be offered:
            every item in the level window, not just this one level. Getting the
            band right is what stops a level-free grade being drowned out by the
            five levels of ordinary items it competes with."""
            avail = {}
            for ty in types:
                per_q = {q: [i for lv in range(level + lo, level + hi + 1)
                             for i in levelled[ty].get(lv, {}).get(q, [])]
                         for q in QUALITIES}
                for q in QUALITIES:
                    if q in agnostic:
                        per_q[q] = free[ty][q]
                    elif free[ty][q]:
                        per_q[q] = per_q[q] + free[ty][q]
                if any(per_q.values()):
                    avail[ty] = per_q
            if not avail:
                return {}
            return _allocate(avail, wanted, tw, min_per_bucket * width, fixed)

        # Pass 1: allocate each level freely, with the level-free grades in the
        # running as ordinary candidates.
        first = {lv: alloc(lv, None) for lv in range(1, LEVEL_CAP + 1)}
        # Pass 2: those grades can only have ONE eligible set for all levels, so
        # take the middle of what the levels asked for and allocate again around
        # it — the level-bound grades then adapt to the real count.
        fixed = {}
        for ty in types:
            per_q = {}
            for q in QUALITIES:
                if not free[ty][q]:
                    continue
                asked = sorted(k[ty][q] for k in first.values() if ty in k)
                if asked:
                    per_q[q] = min(len(free[ty][q]), asked[len(asked) // 2])
            if per_q:
                fixed[ty] = per_q
        per_level = {lv: alloc(lv, fixed) for lv in range(1, LEVEL_CAP + 1)}

        # membership: level-free grades once, everything else per level
        for ty in types:
            for q in QUALITIES:
                if not free[ty][q]:
                    continue
                n = fixed.get(ty, {}).get(q, 0)
                for i in free[ty][q][:n]:
                    if cls not in i["pools"]:
                        add.setdefault(i["path"], set()).add(cls)
                for i in free[ty][q][n:]:
                    if cls in i["pools"]:
                        remove.setdefault(i["path"], set()).add(cls)
        counts = {}
        for lv, k in per_level.items():
            tally = {q: 0 for q in QUALITIES}
            for ty in types:
                if ty not in k:
                    continue
                for q in QUALITIES:
                    tally[q] += k[ty][q]
                    if q in agnostic:
                        continue
                    # the band asked for k items across `width` levels, so this
                    # level carries its share of them
                    share = int(round(k[ty][q] / width))
                    pool = levelled[ty][lv][q]
                    if k[ty][q] > 0 and share == 0 and pool:
                        share = 1 if (lv % width) == 0 else 0
                    for i in pool[:share]:
                        if cls not in i["pools"]:
                            add.setdefault(i["path"], set()).add(cls)
                    for i in pool[share:]:
                        if cls in i["pools"]:
                            remove.setdefault(i["path"], set()).add(cls)
            counts[lv] = tally
        keeps_out[cls] = counts

    # an item can be both added and removed for different classes; that is fine,
    # but never for the same class
    for path, cls_set in add.items():
        overlap = cls_set & remove.get(path, set())
        if overlap:
            remove[path] -= overlap
    return {"add": add, "remove": remove, "keeps": keeps_out, "shortfalls": [],
            "agnostic": sorted(agnostic, key=QUALITIES.index), "notes": auto_notes}


def _median_total(per_level: dict) -> float:
    """Typical number of level-bound items a type offers at one level."""
    totals = sorted(sum(len(v) for v in per_q.values())
                    for per_q in per_level.values())
    totals = [t for t in totals if t]
    if not totals:
        return 0.0
    return float(totals[len(totals) // 2])


def vp_not_dropped(item: dict, p: dict) -> bool:
    """True when the plan leaves this item in at least one shaped class."""
    return bool((item["pools"] - p["remove"].get(item["path"], set()))
                & set(p["keeps"]))


def _apply_plan(items: list[dict], p: dict) -> list[dict]:
    """Copy of the census with the planned membership applied, for projecting."""
    out = []
    for i in items:
        pools = set(i["pools"]) - p["remove"].get(i["path"], set())
        pools |= p["add"].get(i["path"], set())
        out.append({**i, "pools": pools})
    return out
