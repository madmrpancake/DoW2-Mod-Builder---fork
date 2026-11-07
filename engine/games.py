"""Game-target registry for the multi-game split.

Each target defines where its install lives, how its attribute data is
stored, and which base .module file mod generation starts from.
"""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GAMES = {
    "dow2cr": {
        "title": "Dawn of War II + Chaos Rising (Anniversary Edition)",
        "default_game_path": r"C:\Program Files (x86)\Steam\steamapps\common\Dawn of War 2",
        "attrib_storage": "rbf_files",     # classic: one RBF per entity
        "base_module": "gamedata/DOW2.module",
        "extracted_dir": "workspace/extracted/GameAttrib",
        "scripts_dir": "workspace/extracted/scripts/200_data",
        "exe_check": "DOW2.exe",
        "notes": "attributes in GameAttrib.sga as 9,027 classic RBF files",
    },
    "retribution": {
        "title": "Dawn of War II - Retribution",
        "default_game_path": r"C:\Program Files (x86)\Steam\steamapps\common\Dawn of War II - Retribution",
        "attrib_storage": "rb2",           # consolidated attribmegabinary.rb2
        "base_module": "gamedata/retribution/DOW2.module",
        "extracted_dir": "workspace/extracted/retribution",
        "scripts_dir": "workspace/extracted/scripts_retribution/000_campaign",
        "exe_check": "DOW2.exe",
        "notes": "attributes consolidated in attribmegabinary.rb2 (RBF variant, "
                 "shared fieldnames.flb); campaign wargear under wargear\\wargear\\xp2",
    },
}


def game_def(game: str) -> dict:
    if game not in GAMES:
        raise ValueError(f"unknown game target {game!r} (know: {list(GAMES)})")
    return GAMES[game]


class RetributionAttrib:
    """Loaded view of Retribution's consolidated attribute data."""

    def __init__(self, extracted_dir: Path):
        import rbf2
        self.dir = Path(extracted_dir)
        self.fields = rbf2.FieldNames((self.dir / "fieldnames.flb").read_bytes())
        self.rb2 = rbf2.Rb2.parse((self.dir / "attribmegabinary.rb2").read_bytes())
        self._rbf2 = rbf2

    def tree(self, name: str):
        """name e.g. 'tuning\\tuning_info' (case-insensitive)."""
        return self.rb2.tree(name, self.fields)

    def replace(self, name: str, tree) -> None:
        self.rb2.replace(name, tree, self.fields)

    def write_modified(self, out_data: Path) -> Path:
        out = Path(out_data) / "simulation" / "attrib" / "attribmegabinary.rb2"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(self.rb2.serialize())
        return out
