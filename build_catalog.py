#!/usr/bin/env python3
"""Build the machine-readable wargear/hero catalog straight from the game archives.

Outputs knowledge/wargear_catalog.json:
  heroes: campaign hero squads (squad_type, display name, source file)
  items:  every campaign wargear item (name, type, quality, level, slot,
          allowed squad types, level threshold, excluded tags, campaigns)
  squad_types: reverse map squad_type -> heroes using it

Deterministic: read directly from GameAttrib.sga + DOW2.ucs (no extraction).
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "engine"))
import rbf  # noqa: E402




def load_ucs(game: str = "dow2cr") -> dict[int, str]:
    import json
    snap = {"dow2cr": ROOT / "gamedata" / "DOW2.ucs",
            "retribution": ROOT / "gamedata" / "retribution" / "DOW2.ucs"}
    stage = {"dow2cr": "Dawn of War 2", "retribution": "Dawn of War II - Retribution"}
    cands = [snap[game],
             Path(f"/mnt/user-data/uploads/{stage[game]}/GameAssets/Locale/English/DOW2.ucs")]
    sp = ROOT / "settings.json"
    if sp.exists():
        gp = json.loads(sp.read_text()).get("games", {}).get(game, {}).get("game_path")
        if gp:
            cands.insert(0, Path(gp) / "GameAssets" / "Locale" / "English" / "DOW2.ucs")
    for cand in cands:
        if cand.exists():
            txt = cand.read_text(encoding="utf-16", errors="replace")
            out = {}
            for line in txt.splitlines():
                m = re.match(r"^(\d+)\t(.*)$", line)
                if m:
                    out[int(m.group(1))] = m.group(2)
            return out
    return {}


def walk_requirements(req_table) -> dict:
    """Collect usable facts from a wargear requirements expression tree."""
    info = {"level_threshold": None, "squad_types": [], "excluded_tags": [],
            "upgrade_conditions": []}

    def walk(node, negated=False):
        for c in node.children:
            if c.type != rbf.TABLE:
                continue
            if c.key == "required_leveling":
                lt = rbf.find(c, "level_threshold")
                if lt is not None and (info["level_threshold"] is None or lt.value > info["level_threshold"]):
                    info["level_threshold"] = lt.value
            elif c.key == "required_squad_type":
                tl = rbf.find(c, "type_list")
                if tl:
                    for st in tl.children:
                        if st.type == rbf.STRING and st.value not in info["squad_types"]:
                            info["squad_types"].append(st.value)
            elif c.key == "required_squad_type_and_upgrade":
                st_tbl = rbf.find(c, "squad_type/type_list")
                up = rbf.find(c, "squad_upgrade/upgrade_name")
                types = [s.value for s in st_tbl.children] if st_tbl else []
                info["upgrade_conditions"].append(
                    {"squad_types": types, "upgrade": up.value if up else None})
                for t in types:
                    if t not in info["squad_types"]:
                        info["squad_types"].append(t)
            elif c.key == "required_wargear_tag":
                tag = rbf.find(c, "wargear_tag")
                if tag and negated and tag.value not in info["excluded_tags"]:
                    info["excluded_tags"].append(tag.value)
            elif c.key == "required_unary_expr":
                op = rbf.find(c, "operation")
                inner = rbf.find(c, "requirements")
                if inner:
                    walk(inner, negated=(op and op.value == "not") != negated)
            elif c.key == "required_binary_expr":
                for side in ("requirements_lhs", "requirements_rhs"):
                    inner = rbf.find(c, side)
                    if inner:
                        walk(inner, negated)
            elif c.key.startswith("required_"):
                pass
    walk(req_table)
    return info


CATALOG_FILES = {"dow2cr": "wargear_catalog.json",
                 "retribution": "wargear_catalog_retribution.json"}
HERO_PREFIXES = {"dow2cr": ["sbps/campaign/playable"],
                 "retribution": ["sbps/xp2/campaign"]}
WG_PREFIXES = {"dow2cr": "wargear/wargear/campaign/playable",
               "retribution": "wargear/wargear/xp2/campaign"}


def build(game: str = "dow2cr") -> dict:
    ucs = load_ucs(game)

    def name_of(ucs_id):
        try:
            return ucs.get(int(ucs_id), f"${ucs_id}")
        except (TypeError, ValueError):
            return str(ucs_id)

    import source as source_mod
    src = source_mod.open_source(game)

    # ---- heroes ----------------------------------------------------------
    heroes = []
    for vp in (p for pref in HERO_PREFIXES[game] for p in src.attrib_paths(pref)):
        p = Path(vp)
        t = src.attrib_tree(vp)
        bag = t.children[0] if t.children else None
        if bag is None:
            continue
        squad_type = None
        ui_name = None
        for ext in rbf.walk(bag):
            path, n = ext
            if n.key == "squad_type" and n.type == rbf.STRING and squad_type is None:
                squad_type = n.value
            if n.key == "screen_name_id" or (n.key == "screen_name" and n.type == rbf.INT):
                ui_name = n.value
        ui = rbf.find(bag, "squad_ui_ext")
        heroes.append({
            "file": vp,
            "id": p.stem,
            "squad_type": squad_type,
            "xp1": "/xp1/" in vp,
            "kind": p.parent.name,   # troops / vehicles
        })

    # ---- items -----------------------------------------------------------
    items = []
    wg_prefix = WG_PREFIXES[game]
    for vp in src.attrib_paths(wg_prefix):
        p = Path(vp)
        rel_wg = vp[len(wg_prefix)+1:]
        t = src.attrib_tree(vp)
        bag = t.children[0]
        g = lambda k: rbf.find(bag, k)
        v = lambda k, d=None: (g(k).value if g(k) is not None else d)
        req = g("requirements")
        rinfo = walk_requirements(req) if req else {
            "level_threshold": None, "squad_types": [], "excluded_tags": [],
            "upgrade_conditions": []}
        campaigns = [c.value for c in g("valid_campaigns").children] if g("valid_campaigns") else []
        items.append({
            "id": p.stem,
            "path": vp,
            "attrib_ref": wg_prefix.replace("/", "\\") + "\\" + rel_wg.replace("/", "\\").removesuffix(".rbf"),
            "name": name_of(v("name")),
            "name_ucs": v("name"),
            "type": v("type"),
            "quality": v("quality"),
            "level": v("level"),
            "slot": v("slot"),
            "unique": v("unique"),
            "wargear_tag": v("wargear_tag"),
            "icon": (rbf.find(bag, "ui/icon_name").value
                     if rbf.find(bag, "ui/icon_name") is not None else None),
            "dropped_by": [c.value for c in g("dropped_by").children] if g("dropped_by") else [],
            "ignore_level_when_dropping": v("ignore_level_requirement_when_dropping"),
            "level_threshold": rinfo["level_threshold"],
            "allowed_squad_types": rinfo["squad_types"],
            "excluded_tags": rinfo["excluded_tags"],
            "upgrade_conditions": rinfo["upgrade_conditions"],
            "campaigns": campaigns,
            "race_dir": rel_wg.split("/")[0],
        })

    squad_types: dict[str, list[str]] = {}
    for h in heroes:
        if h["squad_type"]:
            squad_types.setdefault(h["squad_type"], []).append(h["id"])

    catalog = {
        "generated_from": "GameAttrib.sga (read directly) + DOW2.ucs",
        "heroes": heroes,
        "squad_types": squad_types,
        "items": items,
        "counts": {"heroes": len(heroes), "items": len(items)},
    }
    out = ROOT / "knowledge" / CATALOG_FILES[game]
    out.write_text(json.dumps(catalog, indent=1))
    print(f"catalog: {len(heroes)} hero squads, {len(items)} items -> {out}")
    return catalog


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "dow2cr")
