#!/usr/bin/env python3
"""Build the entity index: every attribute file, categorised, with display
names and outgoing reference edges (the dependency graph).

Output: knowledge/entity_index.json
  entities: [{path, category, name, refs_out:[paths]}]
Reverse edges (refs_in) are derived in-memory by the mod manager at load.

An outgoing reference is any string value that resolves to another file in
the extracted attrib tree (e.g. "weapons\\weapon\\campaign\\...\\sm_plasma_cannon"
-> simulation/attrib/weapons/weapon/campaign/.../sm_plasma_cannon.rbf).
"""
from __future__ import annotations
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "engine"))
import rbf  # noqa: E402
from build_catalog import load_ucs  # noqa: E402



REF_RE = re.compile(r"^[a-z0-9_]+(\\[a-z0-9_.\-]+)+$", re.I)


INDEX_FILES = {"dow2cr": "entity_index.json",
               "retribution": "entity_index_retribution.json"}


def build(game: str = "dow2cr") -> dict:
    import source as source_mod
    src = source_mod.open_source(game)
    t0 = time.time()
    ucs = load_ucs(game)
    all_files = set(src.attrib_paths())
    # lookup: attrib-style ref -> canonical index key
    def resolve(ref: str):
        k = ref.replace("\\", "/").lower()
        if not k.endswith(".rbf"):
            k += ".rbf"
        return k if k in all_files else None

    entities = []
    for key in sorted(all_files):
        try:
            tree = src.attrib_tree(key)
        except Exception as e:
            entities.append({"path": key, "category": key.split("/")[0],
                             "error": str(e)})
            continue
        name = None
        refs = set()
        for ipath, n in rbf.walk_indexed(tree):
            if n.type == rbf.STRING and "\\" in n.value and REF_RE.match(n.value):
                r = resolve(n.value)
                if r and r != key:
                    refs.add(r)
            elif n.type == rbf.INT and name is None and ipath.endswith("/name") \
                    and ipath.count("/") == 1:
                name = ucs.get(n.value)
        entities.append({
            "path": key,
            "category": key.split("/")[0],
            "name": name or Path(key).stem,
            "refs_out": sorted(refs),
        })

    out = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(entities),
        "entities": entities,
    }
    dest = ROOT / "knowledge" / INDEX_FILES[game]
    dest.write_text(json.dumps(out))
    edges = sum(len(e.get("refs_out", [])) for e in entities)
    print(f"indexed {len(entities)} entities, {edges} reference edges "
          f"in {time.time()-t0:.1f}s -> {dest} ({dest.stat().st_size//1024} KB)")
    return out


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else "dow2cr")
