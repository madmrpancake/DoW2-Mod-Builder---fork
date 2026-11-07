"""UCS localisation table support (DOW2.ucs).

Format: UTF-16 text, one `ID<TAB>text` per line. RBF fields such as
wargear `name` reference these numeric IDs.

Framework use (EXPERIMENTAL — pending in-game verification):
- parse the shipped table
- allocate custom IDs in a reserved range far above Relic's (20,000,000+)
- emit a merged DOW2.ucs into the mod's build output
  (<Mod>/Locale/English/DOW2.ucs)

Caveat: the engine auto-mounts locale from the
module's ModFolder; whether a mod-local Locale folder is honoured without
changing ModFolder is untested. Until verified, custom strings are emitted
but marked experimental in the manifest.
"""
from __future__ import annotations
from pathlib import Path

CUSTOM_ID_BASE = 20_000_000


def load(path: str | Path) -> dict[int, str]:
    out: dict[int, str] = {}
    for line in Path(path).read_text(encoding="utf-16", errors="replace").splitlines():
        if "\t" in line:
            sid, _, text = line.partition("\t")
            if sid.isdigit():
                out[int(sid)] = text
    return out


def save(table: dict[int, str], path: str | Path) -> None:
    lines = [f"{sid}\t{table[sid]}" for sid in sorted(table)]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\r\n".join(lines) + "\r\n", encoding="utf-16")


def merge(base: dict[int, str], additions: dict[int, str]) -> dict[int, str]:
    """Additions win; refuses to overwrite Relic IDs silently."""
    out = dict(base)
    for sid, text in additions.items():
        sid = int(sid)
        if sid in base and sid < CUSTOM_ID_BASE and base[sid] != text:
            raise ValueError(
                f"refusing to overwrite shipped UCS id {sid} ({base[sid]!r}); "
                f"use ids >= {CUSTOM_ID_BASE} for custom strings")
        out[sid] = text
    return out


def next_free_id(table: dict[int, str]) -> int:
    used = [sid for sid in table if sid >= CUSTOM_ID_BASE]
    return (max(used) + 1) if used else CUSTOM_ID_BASE
