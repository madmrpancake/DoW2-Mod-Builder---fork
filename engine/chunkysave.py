"""Read-only summary of Retribution campaign saves (Relic Chunky ``.sv``).

These files are Relic Chunky containers, not the flat layout savefile.py
reads. Campaign state (heroes, gear) lives inside a persisted Lua state at
SCEN/APST/SCAR/SCAR/SLua. Only strings and floats that can be recognised
there are read. Nothing in this module ever writes.

Chunk header: 4s type (DATA|FOLD), 4s id, u32 version, u32 size, u32 name_len,
2 x u32, then name bytes, then ``size`` bytes of body. Inside the Lua blob a
string is  u32 4, u32 len, bytes  and a number is  u32 3, f32.
"""
from __future__ import annotations
import re
import struct
from pathlib import Path

MAGIC = b"Relic Chunky"
_XP = re.compile(rb"\x04\x00\x00\x00\x0a\x00\x00\x00experience\x03\x00\x00\x00(....)",
                 re.S)
_SBP = re.compile(rb"sbps\\[\x20-\x7e]+")


class ChunkyError(Exception):
    pass


def is_chunky(path: str | Path) -> bool:
    with open(path, "rb") as fh:
        return fh.read(len(MAGIC)) == MAGIC


def _find_chunk(d: bytes, wanted: list[str]) -> tuple[int, int]:
    """Body (offset, size) of the chunk reached by following ``wanted`` ids."""
    o, end = 36, len(d)
    for depth, want in enumerate(wanted):
        while True:
            if o + 28 > end:
                raise ChunkyError(f"chunk {want} not found")
            typ, cid = d[o:o + 4], d[o + 4:o + 8].decode("latin1")
            _ver, size, nlen = struct.unpack_from("<3I", d, o + 8)
            body = o + 28 + nlen
            if typ not in (b"DATA", b"FOLD") or body + size > end:
                raise ChunkyError(f"bad chunk header at offset {o}")
            if cid == want:
                if depth == len(wanted) - 1:
                    return body, size
                o, end = body, body + size
                break
            o = body + size
    raise ChunkyError("chunk not found")


_CAMS_ITEM = re.compile(rb"(.)\x00\x00\x00wargear\\", re.S)
_TEXT = re.compile(rb"[\x20-\x7e]{6,}")
_CAMS_SBP = re.compile(rb"(.)\x00\x00\x00sbps\\", re.S)


def _campaign_heroes(d: bytes) -> list[dict]:
    """Heroes from the campaign-state chunk SCEN/APPD/CAMP/CAMS."""
    off, size = _find_chunk(d, ["SCEN", "APPD", "CAMP", "CAMS"])
    return _heroes_in_record(d[off:off + size])


def _heroes_in_record(b: bytes) -> list[dict]:
    """Heroes in a campaign record (the CAMS body, or a whole cloud ``.sav``).

    Each hero is a length-prefixed ``sbps\\...`` string followed by an f32 XP.
    The same blueprint may reappear later with 0.0; only the first is kept.
    """
    seen, heroes = set(), []
    for m in _CAMS_SBP.finditer(b):
        start, n = m.start() + 4, m.group(1)[0]
        name = b[start:start + n]
        if len(name) != n or start + n + 4 > len(b) or name in seen:
            continue
        if not re.fullmatch(rb"[\x20-\x7e]+", name):
            continue
        seen.add(name)
        heroes.append({"xp": round(struct.unpack_from("<f", b, start + n)[0], 1),
                       "blueprint": name.decode("latin1"),
                       "gear": _gear_after(b, start + n + 4)})
    return heroes


def _items_between(b: bytes, pos: int, end: int) -> list[str]:
    """Wargear entries in b[pos:end]. A real entry is followed by a 0/1 flag
    byte; other wargear-looking strings (e.g. upgrade rewards) are skipped."""
    out, last = [], pos
    for m in _CAMS_ITEM.finditer(b, pos, end):
        if m.start() - last > 300:  # far-away entries belong to other tables
            break
        start, n = m.start() + 4, m.group(1)[0]
        name = b[start:start + n]
        if len(name) != n or not re.fullmatch(rb"[\x20-\x7e]+", name):
            continue
        if start + n < len(b) and b[start + n] in (0, 1):
            out.append(name.decode("latin1"))
            last = start + n
    return out


def _gear_after(b: bytes, pos: int) -> list[str]:
    """Wargear equipped by the hero whose record ends at ``pos``: the entries
    between it and the next hero (matches the in-game equipment screens)."""
    nxt = _CAMS_SBP.search(b, pos)
    return _items_between(b, pos, nxt.start() if nxt else len(b))


def _stash_in_record(b: bytes) -> list[str]:
    """Unequipped wargear: entries before the first hero record."""
    first = _CAMS_SBP.search(b)
    return _items_between(b, 0, first.start()) if first else []


def summarize_cloud(path: str | Path) -> dict:
    """Read-only summary of a Steam Cloud ``campaign_<Race>_<n>.sav``.

    These hold the same campaign record as the CAMS chunk, without the
    Relic Chunky wrapper.
    """
    return {"format": "Steam Cloud campaign", "source": "cloud",
            "heroes": _heroes_in_record(Path(path).read_bytes()),
            "stash": _stash_in_record(Path(path).read_bytes())}


def summarize(path: str | Path) -> dict:
    d = Path(path).read_bytes()
    if d[:len(MAGIC)] != MAGIC:
        raise ChunkyError("not a Relic Chunky file")
    try:
        heroes = _campaign_heroes(d)
    except ChunkyError:
        heroes = []
    if heroes:
        return {"format": "Relic Chunky", "source": "CAMS", "heroes": heroes}
    off, size = _find_chunk(d, ["SCEN", "APST", "SCAR", "SCAR", "SLua"])
    blob = d[off:off + size]
    heroes = []
    for m in _XP.finditer(blob):
        sbps = _SBP.findall(blob[max(0, m.start() - 600):m.start()])
        # entries with no hero blueprint nearby are template defaults, not heroes
        if sbps:
            heroes.append({"xp": round(struct.unpack("<f", m.group(1))[0], 1),
                           "blueprint": sbps[-1].decode("latin1")})
    return {"format": "Relic Chunky", "lua_bytes": size, "heroes": heroes}


def set_cloud_hero_xp(src: str | Path, dest: str | Path, hero: str, xp: float) -> float:
    """Write a copy of a cloud ``.sav`` with one hero's XP changed.

    ``hero`` is matched against the end of the blueprint name. Only the 4-byte
    float is replaced, so the file size is unchanged. Returns the old XP. If
    ``dest`` exists it is backed up to ``<dest>.bak`` first.
    """
    b = bytearray(Path(src).read_bytes())
    for m in _CAMS_SBP.finditer(bytes(b)):
        start, n = m.start() + 4, m.group(1)[0]
        name = bytes(b[start:start + n])
        if name.decode("latin1").endswith(hero):
            old = struct.unpack_from("<f", b, start + n)[0]
            struct.pack_into("<f", b, start + n, float(xp))
            dest = Path(dest)
            if dest.exists():
                dest.with_name(dest.name + ".bak").write_bytes(dest.read_bytes())
            dest.write_bytes(bytes(b))
            return old
    raise ChunkyError(f"hero {hero!r} not found")


if __name__ == "__main__":
    import json
    import sys
    if sys.argv[1] == "--set-xp":
        _, _, s, d, h, x = sys.argv
        print("old xp", set_cloud_hero_xp(s, d, h, float(x)))
    else:
        print(json.dumps(summarize(sys.argv[1]), indent=1))
