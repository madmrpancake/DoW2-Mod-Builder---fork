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


_CAMS_SBP = re.compile(rb"(.)\x00\x00\x00sbps\\", re.S)


def _campaign_heroes(d: bytes) -> list[dict]:
    """Heroes from the campaign-state chunk SCEN/APPD/CAMP/CAMS.

    Each hero is a length-prefixed ``sbps\\...`` string followed by an f32 XP.
    The same blueprint may reappear later with 0.0; only the first is kept.
    """
    off, size = _find_chunk(d, ["SCEN", "APPD", "CAMP", "CAMS"])
    b = d[off:off + size]
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
                       "blueprint": name.decode("latin1")})
    return heroes


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


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(summarize(sys.argv[1]), indent=1))
