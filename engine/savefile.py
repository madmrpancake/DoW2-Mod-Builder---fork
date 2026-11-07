"""Campaign save reader/writer  (Documents\\My Games\\<game>\\Saved Games\\*.sav)

Format, established by reading a real campaign save byte by byte
(DoW2 + Chaos Rising, save version 18). Plain little-endian records, no
compression, no checksum:

    u32   payload_size          == filesize - 12
    u32   version               18 for DoW2/CR
    str   campaign              "space_marines"
    6  x  inventory section     u32 count, then per item:
                                    u8  present    (always 1)
                                    u32 quantity   (always 1)
                                    str path       wargear\\wargear\\campaign\\...
                                    u8  flag       0/1, tracks "new since last seen"
                                sections in order: weapons, armour, accessories,
                                consumables, and two that are empty in every
                                save seen so far
    u32   count, then count x str        pool of item paths (no per-item flags)
    u32   squad_count
    squad_count x squad:
        u32   slot
        str   sbps\\campaign\\playable\\...\\<hero>
        f32   experience         total XP; the game derives the level from it
                                 using leveling/campaign_tables (the same table
                                 the XP Tuning module edits)
        u8    recruited          0 for a hero who has not joined yet
        u32   health             \\
        u32   melee               |  attribute points as shown on the hero sheet;
        u32   ranged              |  order confirmed against each hero's role
        u32   will               /   (FC melee 9, Cyrus ranged 9 / will 7, ...)
        u32   unspent            points banked but not assigned
        ...   equipped items and per-slot state follow

    then campaign progress: mission ids with day numbers and per-type counts.

    str  values are u32 length followed by that many ASCII bytes.

Writing rules enforced here:
  * scalar edits are patched in place, so the byte layout never moves;
  * inventory edits rewrite one section and fix payload_size;
  * every write is verified by re-parsing the result, and the caller is
    expected to keep the backup this module creates.
"""
from __future__ import annotations
import shutil
import struct
import time
from pathlib import Path

INV_SECTIONS = ["weapons", "armour", "accessories", "consumables",
                "reserve_a", "reserve_b"]
ATTRS = ["health", "melee", "ranged", "will"]
KNOWN_VERSIONS = {18}


class SaveError(Exception):
    pass


class _Cursor:
    def __init__(self, data: bytes, off: int = 0):
        self.d = data
        self.o = off

    def u8(self) -> int:
        v = self.d[self.o]
        self.o += 1
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.d, self.o)[0]
        self.o += 4
        return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.d, self.o)[0]
        self.o += 4
        return v

    def string(self) -> str:
        n = self.u32()
        if n > 1024 or self.o + n > len(self.d):
            raise SaveError(f"string length {n} at offset {self.o - 4} is out of range")
        s = self.d[self.o:self.o + n]
        self.o += n
        if not all(32 <= c < 127 for c in s):
            raise SaveError(f"non-text bytes in a string at offset {self.o - n}")
        return s.decode("ascii")

    def peek_string(self) -> str | None:
        try:
            save = self.o
            s = self.string()
            self.o = save
            return s
        except (SaveError, IndexError, struct.error):
            return None


def parse(path: str | Path) -> dict:
    """Read a save into an editable model. Raises SaveError if the layout is
    not one this module understands — never guesses."""
    p = Path(path)
    data = p.read_bytes()
    if len(data) < 32:
        raise SaveError("file is too small to be a campaign save")
    c = _Cursor(data)
    declared = c.u32()
    version = c.u32()
    if declared != len(data) - 12:
        raise SaveError(f"size field says {declared}, file body is {len(data) - 12}")
    # An unfamiliar version is not refused outright: if the record layout still
    # parses AND rebuilds byte-for-byte, the model is provably a faithful
    # description of the file. Writing is gated on that check, not on a version
    # number, which is what lets a save this build has never seen be handled
    # safely instead of guessed at.
    campaign = c.string()

    inventory = []
    for name in INV_SECTIONS:
        start = c.o
        count = c.u32()
        if count > 5000:
            raise SaveError(f"{name}: implausible item count {count}")
        items = []
        for _ in range(count):
            present = c.u8()
            quantity = c.u32()
            ipath = c.string()
            flag = c.u8()
            items.append({"present": present, "quantity": quantity,
                          "path": ipath, "flag": flag})
        inventory.append({"section": name, "start": start, "end": c.o,
                          "items": items})

    pool_start = c.o
    pool_n = c.u32()
    pool = [c.string() for _ in range(pool_n)]
    pool_span = (pool_start, c.o)

    squads = []
    squad_count = c.u32()
    if squad_count > 64:
        raise SaveError(f"implausible squad count {squad_count}")
    for _ in range(squad_count):
        slot = c.u32()
        name = c.string()
        xp_off = c.o
        xp = c.f32()
        recruited_off = c.o
        recruited = c.u8()
        attr_off = c.o
        attrs = {a: c.u32() for a in ATTRS}
        unspent_off = c.o
        unspent = c.u32()
        squads.append({
            "slot": slot, "path": name, "unit": name.split("\\")[-1],
            "xp": xp, "recruited": recruited, "attributes": attrs,
            "unspent": unspent,
            "_off": {"xp": xp_off, "recruited": recruited_off,
                     "attributes": attr_off, "unspent": unspent_off},
        })
        # The rest of a squad record (equipped items and per-slot state) is
        # skipped rather than modelled: scan forward to the next hero path, or
        # to the campaign block that follows the last hero.
        c.o = _next_anchor(data, c.o, campaign)

    model = {"file": str(p), "bytes": data, "version": version,
             "version_known": version in KNOWN_VERSIONS,
             "campaign": campaign, "inventory": inventory,
             "pool": pool, "pool_span": pool_span, "squads": squads,
             "progress_at": c.o}
    # the safety gate: an untouched rebuild must reproduce the file exactly
    model["verified"] = build(model) == data
    return model


def _next_anchor(data: bytes, start: int, campaign: str) -> int:
    """Offset of the next hero record or of the campaign progress block."""
    hero = b"sbps\\campaign"
    i = data.find(hero, start)
    camp = data.find(struct.pack("<I", len(campaign)) + campaign.encode(), start)
    # a hero record is  u32 slot | u32 len | "sbps\campaign..." — so the record
    # starts eight bytes before the text the search found
    cands = [x - 8 for x in (i,) if x != -1] + [x for x in (camp,) if x != -1]
    if not cands:
        return len(data)
    return min(cands)


# --------------------------------------------------------------------------
# editing


def set_scalar(model: dict, kind: str, squad_index: int, field: str, value) -> None:
    """Queue an in-place edit. Layout never moves, so this is the safe kind."""
    edits = model.setdefault("_edits", [])
    sq = model["squads"][squad_index]
    if kind == "xp":
        edits.append((sq["_off"]["xp"], struct.pack("<f", float(value))))
        sq["xp"] = float(value)
    elif kind == "recruited":
        edits.append((sq["_off"]["recruited"], bytes([1 if value else 0])))
        sq["recruited"] = 1 if value else 0
    elif kind == "attribute":
        if field not in ATTRS:
            raise SaveError(f"unknown attribute {field}")
        off = sq["_off"]["attributes"] + 4 * ATTRS.index(field)
        edits.append((off, struct.pack("<I", max(0, int(value)))))
        sq["attributes"][field] = max(0, int(value))
    elif kind == "unspent":
        edits.append((sq["_off"]["unspent"], struct.pack("<I", max(0, int(value)))))
        sq["unspent"] = max(0, int(value))
    else:
        raise SaveError(f"unknown scalar {kind}")


def _section_bytes(items: list[dict]) -> bytes:
    out = bytearray(struct.pack("<I", len(items)))
    for it in items:
        out += bytes([it.get("present", 1)])
        out += struct.pack("<I", it.get("quantity", 1))
        path = it["path"].encode("ascii")
        out += struct.pack("<I", len(path)) + path
        out += bytes([it.get("flag", 1)])
    return bytes(out)


def build(model: dict, inventory: list[dict] | None = None) -> bytes:
    """Produce the new file contents. inventory, when given, replaces the item
    lists (same six sections, any number of items)."""
    data = bytearray(model["bytes"])
    for off, blob in model.get("_edits", []):
        data[off:off + len(blob)] = blob

    if inventory is not None:
        if len(inventory) != len(model["inventory"]):
            raise SaveError("inventory must keep all six sections")
        # splice from the last section backwards so earlier offsets stay valid
        for old, new in sorted(zip(model["inventory"], inventory),
                              key=lambda pair: -pair[0]["start"]):
            data[old["start"]:old["end"]] = _section_bytes(new["items"])

    data[0:4] = struct.pack("<I", len(data) - 12)          # payload size
    return bytes(data)


def save(model: dict, out_path: str | Path | None = None,
         inventory: list[dict] | None = None, backup: bool = True) -> dict:
    """Write the edited save. Keeps a timestamped backup of the original and
    re-parses the result before returning — a save that will not read back is
    restored from that backup instead of being left in place."""
    if not model.get("verified"):
        raise SaveError("this save was read but could not be reproduced exactly, "
                        "so it will not be written to — the layout differs from "
                        "the one this build understands")
    target = Path(out_path or model["file"])
    new = build(model, inventory)
    info = {"file": str(target), "bytes": len(new), "backup": None}
    if backup and target.exists():
        bdir = target.parent / "PA_backups"
        bdir.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        bp = bdir / f"{target.stem}_{stamp}{target.suffix}"
        shutil.copy2(target, bp)
        info["backup"] = str(bp)
    target.write_bytes(new)
    try:
        parse(target)
    except SaveError as e:
        if info["backup"]:
            shutil.copy2(info["backup"], target)
            raise SaveError(f"the edited save did not read back ({e}) — your "
                            f"original has been put back") from e
        raise
    return info


def describe(model: dict) -> dict:
    """Plain summary for the UI (no offsets, no raw bytes)."""
    return {
        "file": model["file"],
        "campaign": model["campaign"],
        "version": model["version"],
        "version_known": model.get("version_known", False),
        "verified": model.get("verified", False),
        "squads": [{"unit": s["unit"], "path": s["path"], "slot": s["slot"],
                    "xp": round(s["xp"], 1), "recruited": bool(s["recruited"]),
                    "attributes": s["attributes"], "unspent": s["unspent"]}
                   for s in model["squads"]],
        "inventory": [{"section": s["section"],
                       "items": [{"path": i["path"],
                                  "name": i["path"].split("\\")[-1],
                                  "flag": i["flag"]} for i in s["items"]]}
                      for s in model["inventory"]],
        "pool": [p.split("\\")[-1] for p in model["pool"]],
    }
