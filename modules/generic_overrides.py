"""Generic Overrides module — raw attribute editing for systems without a
dedicated UI module yet.

Operates on: any RBF under simulation/attrib (attrib space).

Config shape:
    {"overrides": [
        {"file": "weapons/weapon/campaign/playable/race_marine/sm_plasma_cannon.rbf",
         "path": "weapon/damage/max_damage",      # indexed path, [n] to disambiguate
         "value": 55}
    ]}

The value's type is coerced to the existing node's type (bool/int/float/string).
Table nodes cannot be overridden. This is the experimentation layer the
framework uses BEFORE a dedicated module exists for a system; once a pattern
proves out in-game, it graduates into a proper schema-driven module.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
import rbf  # noqa: E402

GAMES = ["dow2cr"]

SCHEMA = {
    "module": "generic_overrides",
    "title": "Generic Overrides (advanced)",
    "target_file": "simulation/attrib/** (any attribute file)",
    "note": "Raw value overrides added from the Data Browser. "
            "Use the browser's 'override' button next to any value.",
    "options": {
        "overrides": {
            "title": "Value overrides",
            "description": "Each row pins one attribute value in one game file.",
            "type": "overrides",
            "default": [],
        },
    },
}

WARNINGS: list[str] = []


def apply(src, out_data: Path, cfg: dict) -> list[dict]:
    global WARNINGS
    WARNINGS = []
    overrides = cfg.get("overrides", []) or []
    if not isinstance(overrides, list) or not all(
            isinstance(o, dict) and {"file", "path", "value"} <= set(o)
            for o in overrides):
        raise ValueError("generic_overrides: 'overrides' must be a list of "
                         "{file, path, value} entries")
    if not overrides:
        return []
    changes: list[dict] = []

    by_file: dict[str, list[dict]] = {}
    for ov in overrides:
        f = ov["file"].replace("\\", "/")
        if f.startswith("simulation/attrib/"):
            f = f[len("simulation/attrib/"):]
        by_file.setdefault(f, []).append(ov)

    for rel, ovs in sorted(by_file.items()):
        try:
            tree = src.attrib_tree(rel)
        except (KeyError, FileNotFoundError):
            raise ValueError(f"generic_overrides: file not found: {rel}")
        touched = False
        for ov in ovs:
            node = rbf.find_indexed(tree, ov["path"])
            if node is None:
                raise ValueError(f"generic_overrides: path not found: {rel} :: {ov['path']}")
            if node.type == rbf.TABLE:
                raise ValueError(f"generic_overrides: {ov['path']} is a table, not a value")
            old = node.value
            try:
                if node.type == rbf.BOOL:
                    new = ov["value"] in (True, 1, "1", "true", "True")
                elif node.type == rbf.INT:
                    new = int(ov["value"])
                elif node.type == rbf.FLOAT:
                    new = float(ov["value"])
                else:
                    new = str(ov["value"])
            except (TypeError, ValueError):
                raise ValueError(
                    f"generic_overrides: {ov['path']}: cannot convert {ov['value']!r} "
                    f"to {('bool','float','int','string')[node.type]}")
            if new == old:
                WARNINGS.append(f"{rel} :: {ov['path']} already has value {old!r}")
                continue
            node.value = new
            touched = True
            changes.append({"file": src.attrib_label(rel),
                            "path": ov["path"], "old": old, "new": new})
        if touched:
            src.write_attrib(rel, tree, out_data)
    return changes
