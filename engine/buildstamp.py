"""Fingerprint of the builder's own code.

Two builds of the same version are otherwise indistinguishable, which is how a
stale background copy ends up serving old code after an update. app.py reports
this in /api/state; the launcher compares it against the files on disk so it can
tell "already running" from "running something older".
"""
from __future__ import annotations
import hashlib
from pathlib import Path

FILES = ("app.py", "build_mod.py", "ui/index.html")


def stamp(root: Path | str) -> str:
    root = Path(root)
    h = hashlib.sha256()
    for rel in FILES:
        p = root / rel
        if p.exists():
            h.update(p.read_bytes())
    mod = root / "modules"
    if mod.is_dir():
        for p in sorted(mod.rglob("*.py")):     # incl. modules/lootmix/ (1.2.6)
            if "__pycache__" in p.parts:
                continue
            h.update(p.read_bytes())
    return h.hexdigest()[:8]


def builder_version(root: Path | str) -> str:
    """VERSION from app.py — the one place the version lives (with the zip name)."""
    import re
    try:
        txt = (Path(root) / "app.py").read_text(encoding="utf-8")
    except OSError:
        return "?"
    m = re.search(r'^VERSION = "([^"]+)"', txt, re.M)
    return m.group(1) if m else "?"
