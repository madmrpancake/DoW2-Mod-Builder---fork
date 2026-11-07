"""Character Loadouts module — starting equipment for the Chaos Rising campaign.

Operates on: campaign/xp1/default_profile/squads.lua  (data space, Lua)

Discovery: a NEW Chaos Rising campaign started
without importing a DoW2 save is initialised from
campaign/xp1/default_profile/{campaign,squads,inventory}.lua inside
200_data.sga. squads.lua defines each starting hero with per-slot equipped
wargear: weapon_1 (ranged), weapon_2 (melee), armor, accessory_1..3,
commander_accessory. The vanilla DoW2 campaign builds heroes in mission
scripts instead, so this module targets Chaos Rising.

Transform strategy: targeted text substitution inside each hero's squad block
(everything else in the file is preserved byte-for-byte), which keeps us
robust against the parts of the Lua we haven't reverse-engineered.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))

PROFILE_REL = Path("campaign/xp1/default_profile/squads.lua")

HEROES = [
    {"id": "sm_force_commander",         "label": "Force Commander", "squad_type": "force_commander"},
    {"id": "sm_tactical_marine_tarkus",  "label": "Tarkus",          "squad_type": "tactical_marine"},
    {"id": "sm_devastator_marine_avitus","label": "Avitus",          "squad_type": "devastator_marine"},
    {"id": "sm_scout_marine_cyrus",      "label": "Cyrus",           "squad_type": "scout_marine"},
    {"id": "sm_assault_marine_thaddeus", "label": "Thaddeus",        "squad_type": "assault_marine"},
    {"id": "sm_librarian_jonah",         "label": "Jonah (Librarian)", "squad_type": "librarian"},
    {"id": "sm_dreadnought_davian",      "label": "Davian Thule (Dreadnought)", "squad_type": "dreadnought"},
]
SLOTS = ["weapon_1", "weapon_2", "armor", "accessory_1", "accessory_2",
         "accessory_3", "commander_accessory"]
SLOT_FILTER = {   # slot -> (item type, weapon slot int or None)
    "weapon_1": ("weapon", 1), "weapon_2": ("weapon", 2),
    "armor": ("armour", None),
    "accessory_1": ("accessory", None), "accessory_2": ("accessory", None),
    "accessory_3": ("accessory", None),
    "commander_accessory": ("commander_accessory", None),
}

GAMES = ["dow2cr"]

SCHEMA = {
    "module": "loadouts",
    "title": "Character Loadouts (Chaos Rising start)",
    "target_file": str(PROFILE_REL).replace("/", "\\"),
    "note": "Applies to NEW Chaos Rising campaigns started without importing a "
            "Dawn of War II save. Leave a slot on 'keep default' to not touch it.",
    "options": {
        "loadout": {
            "title": "Starting loadouts",
            "description": "Per-hero equipped wargear at campaign start.",
            "type": "loadout",
            "heroes": HEROES,
            "slots": SLOTS,
            "slot_filter": SLOT_FILTER,
            "default": {},
        },
    },
}

_BP = r'blueprint = "((?:[^"\\]|\\.)*)"'


def read_defaults(src) -> dict:
    """Parse current per-hero slot assignments from squads.lua."""
    txt = src.script_text(str(PROFILE_REL))
    out = {}
    blocks = _split_blocks(txt)
    for hero_id, seg in blocks.items():
        slots = {}
        for slot in SLOTS:
            m = re.search(slot + r"\s*=\s*\{\s*" + _BP, seg)
            if m:
                slots[slot] = m.group(1).replace("\\\\", "\\")
        out[hero_id] = slots
    return out


def _split_blocks(txt: str) -> dict[str, str]:
    """Map hero id -> the text segment of its squad entry."""
    marker = re.compile(r'blueprint = "sbps\\\\[^"]*\\\\([a-z0-9_]+)"')
    hits = [(m.start(), m.group(1)) for m in marker.finditer(txt)]
    blocks = {}
    for i, (pos, hid) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(txt)
        blocks[hid] = txt[pos:end]
    return blocks


WARNINGS: list[str] = []


def _validate(loadout: dict) -> list[str]:
    """Cross-check picks against the wargear catalog (warn, don't block)."""
    import json
    warns = []
    cat_p = Path(__file__).resolve().parent.parent / "knowledge" / "wargear_catalog.json"
    if not cat_p.exists():
        return ["wargear_catalog.json missing - run build_catalog.py for pick validation"]
    items = {i["attrib_ref"]: i for i in json.loads(cat_p.read_text())["items"]}
    sq_type = {h["id"]: h["squad_type"] for h in HEROES}
    for hid, slots in loadout.items():
        for slot, ref in slots.items():
            it = items.get(ref)
            if it is None:
                warns.append(f"{hid}/{slot}: item not found in catalog: {ref}")
                continue
            want_type, want_slot = SLOT_FILTER[slot]
            if it["type"] != want_type or (want_slot and it["slot"] != want_slot):
                warns.append(f"{hid}/{slot}: {it['name']} is a {it['type']} (slot {it['slot']}), "
                             f"expected {want_type}" + (f" slot {want_slot}" if want_slot else ""))
            allowed = it.get("allowed_squad_types") or []
            st = sq_type.get(hid, hid)
            if allowed and st not in allowed:
                warns.append(f"{hid}/{slot}: '{it['name']}' is restricted to "
                             f"{', '.join(allowed)} - {hid} ({st}) cannot equip it unless the "
                             f"Expanded Wargear module grants {st} access to {it['type']}s")
    return warns


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    loadout: dict = cfg.get("loadout", {}) or {}
    if not isinstance(loadout, dict) or not all(
            isinstance(s, dict) for s in loadout.values()):
        raise ValueError("loadouts: 'loadout' must be a mapping of "
                         "hero id -> {slot: item path}")
    loadout = {h: {s: v for s, v in slots.items() if v} for h, slots in loadout.items()}
    loadout = {h: s for h, s in loadout.items() if s}
    if not loadout:
        return []
    known = {h["id"] for h in HEROES}
    bad = sorted(set(loadout) - known)
    if bad:
        raise ValueError(
            f"loadouts: unknown hero id(s) {', '.join(bad)} — valid ids: "
            + ", ".join(sorted(known)))

    WARNINGS.extend(_validate(loadout))
    txt = src.script_text(str(PROFILE_REL))
    changes: list[dict] = []

    marker = re.compile(r'blueprint = "sbps\\\\[^"]*\\\\([a-z0-9_]+)"')
    hits = [(m.start(), m.group(1)) for m in marker.finditer(txt)]
    # process from last to first so offsets stay valid
    for i in range(len(hits) - 1, -1, -1):
        pos, hid = hits[i]
        if hid not in loadout:
            continue
        end = hits[i + 1][0] if i + 1 < len(hits) else len(txt)
        seg = txt[pos:end]
        for slot, ref in loadout[hid].items():
            if slot not in SLOTS:
                raise ValueError(f"unknown slot {slot!r} for {hid}")
            lua_ref = ref.replace("\\", "\\\\")
            pat = re.compile("(" + slot + r"\s*=\s*\{\s*blueprint = \")((?:[^\"\\]|\\.)*)(\")")
            m = pat.search(seg)
            if not m:
                raise ValueError(f"slot {slot} not found in squad block of {hid}")
            old = m.group(2).replace("\\\\", "\\")
            if old == ref:
                continue
            seg = seg[:m.start()] + m.group(1) + lua_ref + m.group(3) + seg[m.end():]
            changes.append({"file": str(PROFILE_REL).replace("/", "\\"),
                            "path": f"{hid}/{slot}", "old": old, "new": ref})
        txt = txt[:pos] + seg + txt[end:]

    if changes:
        out = out_data / PROFILE_REL
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(txt)
        # validation: re-read and confirm every configured slot has its value
        check = _split_blocks(txt)
        for hid, slots in loadout.items():
            for slot, ref in slots.items():
                m = re.search(slot + r"\s*=\s*\{\s*" + _BP, check[hid])
                got = m.group(1).replace("\\\\", "\\") if m else None
                if got != ref:
                    raise RuntimeError(f"post-write validation failed: {hid}/{slot}")
    return changes
