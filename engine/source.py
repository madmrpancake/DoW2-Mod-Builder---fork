"""GameSource — read game data straight from the installed archives.

No extraction step, no duplicate copies on disk: archives are opened lazily
(header + TOC only) and individual files are seek-read + decompressed on
demand. The only files the framework ever stores are the ones a mod changes.

Unifies both games behind one attribute API:
  dow2cr      attrib trees = individual RBF files in GameAttrib.sga
  retribution attrib trees = entries in attribmegabinary.rb2 (inside GameAttrib.sga)

Write side: modules call write_attrib(); for dow2cr that stages a single RBF
into the mod output, for Retribution it edits the in-memory rb2 copy which
build_mod flushes once at the end.

Fallback: if an archive is missing (e.g. developing off-machine), reads fall
back to workspace/extracted/... copies when present.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))
import sga as sga_mod   # noqa: E402
import rbf as rbf_mod   # noqa: E402

_CACHE: dict = {}       # (kind, path, mtime) -> object


def _archive(path: Path):
    key = ("sga", str(path), path.stat().st_mtime if path.exists() else 0)
    if key not in _CACHE:
        _CACHE[key] = sga_mod.SgaArchive.open(path)
    return _CACHE[key]


class GameSource:
    def __init__(self, game: str, game_path: Path):
        import games as games_reg
        self.game = game
        self.gdef = games_reg.game_def(game)
        self.game_path = Path(game_path)
        self._ret = None            # lazy RetributionAttrib-ish state
        self._ret_dirty = False

    # ---- attrib ----------------------------------------------------------
    _FALLBACK_GAME_DIRS = {
        # cloud-development fallbacks (staged copies); harmless if absent
        "dow2cr": [Path("/mnt/user-data/uploads/Dawn of War 2")],
        "retribution": [Path("/mnt/user-data/uploads/Dawn of War II - Retribution")],
    }

    def _attrib_archive(self):
        candidates = [self.game_path] + self._FALLBACK_GAME_DIRS.get(self.game, [])
        for base in candidates:
            arc_p = Path(base) / "GameAssets" / "Archives" / "GameAttrib.sga"
            if arc_p.exists():
                return _archive(arc_p)
        raise FileNotFoundError(
            f"GameAttrib.sga not found for {self.game} (looked in "
            f"{', '.join(str(c) for c in candidates)}) - check the game path in Settings")

    def _retribution(self):
        if self._ret is None:
            import rbf2
            arc = self._attrib_archive()
            fields = rbf2.FieldNames(arc.read("simulation/attrib/fieldnames.flb"))
            rb2 = rbf2.Rb2.parse(arc.read("simulation/attrib/attribmegabinary.rb2"))
            self._ret = (rb2, fields, rbf2)
        return self._ret

    def attrib_paths(self, prefix: str = "") -> list[str]:
        """Virtual paths relative to simulation/attrib, '/'-separated, .rbf suffix."""
        prefix = prefix.replace("\\", "/").lower().rstrip("/")
        if self.gdef["attrib_storage"] == "rb2":
            rb2, fields, _ = self._retribution()
            out = [n.replace("\\", "/").lower() + ".rbf" for n in rb2.names]
        else:
            arc = self._attrib_archive()
            base = "simulation/attrib/"
            out = [p[len(base):] for p in arc.files if p.startswith(base) and p.endswith(".rbf")]
        if prefix:
            out = [p for p in out if p.startswith(prefix + "/")]
        return sorted(out)

    def set_overlay(self, out_data) -> None:
        """During a build, prefer files already emitted to out_data so several
        modules can edit the SAME attrib file without clobbering each other
        (each module read-edits-writes the previous module's output)."""
        from pathlib import Path as _P
        self._overlay = _P(out_data) if out_data else None

    def attrib_bytes(self, vpath: str) -> bytes:
        vpath = vpath.replace("\\", "/").lower()
        if self.gdef["attrib_storage"] == "rb2":
            rb2, fields, _ = self._retribution()
            return rb2.blobs[rb2.index[vpath.removesuffix(".rbf").replace("/", "\\")]]
        ov = getattr(self, "_overlay", None)
        if ov is not None:
            p = ov / "simulation" / "attrib" / vpath
            if p.exists():
                return p.read_bytes()
        arc = self._attrib_archive()
        return arc.read("simulation/attrib/" + vpath)

    def attrib_tree(self, vpath: str):
        vpath = vpath.replace("\\", "/").lower()
        if self.gdef["attrib_storage"] == "rb2":
            rb2, fields, rbf2 = self._retribution()
            return rb2.tree(vpath.removesuffix(".rbf").replace("/", "\\"), fields)
        return rbf_mod.load(self.attrib_bytes(vpath))

    def attrib_label(self, vpath: str) -> str:
        """Manifest-friendly file label for a changed attribute tree."""
        vpath = vpath.replace("/", "\\")
        if self.gdef["attrib_storage"] == "rb2":
            return "simulation\\attrib\\attribmegabinary.rb2::" + vpath.removesuffix(".rbf")
        return "simulation\\attrib\\" + vpath

    def write_attrib(self, vpath: str, tree, out_data: Path) -> None:
        """Stage a modified attribute tree into the mod output."""
        vpath = vpath.replace("\\", "/").lower()
        if self.gdef["attrib_storage"] == "rb2":
            rb2, fields, rbf2 = self._retribution()
            rb2.replace(vpath.removesuffix(".rbf").replace("/", "\\"), tree, fields)
            self._ret_dirty = True
            return
        out = Path(out_data) / "simulation" / "attrib" / vpath
        out.parent.mkdir(parents=True, exist_ok=True)
        blob = rbf_mod.save(tree)
        out.write_bytes(blob)
        check = rbf_mod.load(blob)
        if not rbf_mod.equal(tree, check):
            raise RuntimeError(f"{vpath}: written RBF does not re-parse identically")

    def flush(self, out_data: Path) -> list[str]:
        """Write any container-level staged changes (Retribution rb2)."""
        written = []
        if self._ret_dirty and self._ret is not None:
            rb2, fields, _ = self._ret
            out = Path(out_data) / "simulation" / "attrib" / "attribmegabinary.rb2"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(rb2.serialize())
            written.append(str(out))
            # drop the dirty copy so later builds start pristine
            self._ret = None
            self._ret_dirty = False
        return written

    # ---- ui icons ----------------------------------------------------------
    def _icon_map(self) -> dict:
        """icon file stem -> (archive, virtual path). Delta archives win."""
        if getattr(self, "_icons", None) is not None:
            return self._icons
        names = ["240_data.sga", "230_data.sga", "220_data.sga", "210_data.sga",
                 "200_data.sga", "GameDefault_DELTA.sga", "gamedefault.sga"]
        order = ["GameDefault_DELTA.sga", "gamedefault.sga", "240_data.sga",
                 "230_data.sga", "220_data.sga", "210_data.sga", "200_data.sga"]
        icons: dict = {}
        for n in order:
            arc_p = self.game_path / "GameAssets" / "Archives" / n
            if not arc_p.exists():
                for base in self._FALLBACK_GAME_DIRS.get(self.game, []):
                    if (base / "GameAssets" / "Archives" / n).exists():
                        arc_p = base / "GameAssets" / "Archives" / n
                        break
            if not arc_p.exists():
                continue
            arc = _archive(arc_p)
            for vp in arc.files:
                if "/icon_wargear/" in vp and vp.endswith(".dds"):
                    stem = vp.rsplit("/", 1)[-1][:-4]
                    icons.setdefault(stem, (arc, vp))
        self._icons = icons
        return icons

    def icon_png(self, icon_name: str) -> bytes | None:
        import dds
        hit = self._icon_map().get(icon_name.lower())
        if not hit:
            return None
        arc, vp = hit
        try:
            return dds.to_png(arc.read(vp))
        except Exception:
            return None

    # ---- scripts (data space) --------------------------------------------
    def _script_archives(self):
        """Every archive that can hold campaign scripts, in patch priority.

        The base campaign's mission scripts live in gamedefault.sga with patched
        copies in GameDefault_DELTA.sga — reading only 220/200_data saw 1 of the
        84 base missions, so anything driven off these paths silently covered
        Chaos Rising alone. This is the same order bootstrap extracts with:
        higher-numbered patches first, DELTA before the base it patches.
        """
        arcs = []
        names = (["240_data.sga", "230_data.sga", "220_data.sga", "210_data.sga",
                  "200_data.sga", "GameDefault_DELTA.sga", "gamedefault.sga"]
                 if self.game == "dow2cr"
                 else ["002_campaign.sga", "001_campaign.sga", "000_campaign.sga"])
        adir = self.game_path / "GameAssets" / "Archives"
        for n in names:
            p = adir / n
            if not p.exists():                      # case differs on some installs
                try:
                    cand = [c for c in adir.iterdir() if c.name.lower() == n.lower()]
                except OSError:
                    cand = []
                if not cand:
                    continue
                p = cand[0]
            arcs.append(_archive(p))
        return arcs

    def _script_fallback_dirs(self):
        if self.game == "dow2cr":
            return [ROOT / "workspace" / "extracted" / "scripts" / "200_data"]
        return [ROOT / "workspace" / "extracted" / "scripts_retribution" / d
                for d in ("002_campaign", "001_campaign", "000_campaign")]

    def script_paths(self, prefix: str, suffixes=(".lua", ".scar")) -> list[str]:
        prefix = prefix.replace("\\", "/").lower().rstrip("/")
        seen = {}
        arcs = self._script_archives()
        if arcs:
            for arc in arcs:                       # earlier archive = higher priority
                for p in arc.files:
                    if p.startswith(prefix + "/") and p.endswith(suffixes) and p not in seen:
                        seen[p] = True
        else:
            for d in self._script_fallback_dirs():
                if not d.exists():
                    continue
                for f in d.rglob("*"):
                    if f.is_file() and f.suffix in suffixes:
                        rel = str(f.relative_to(d)).replace("\\", "/").lower()
                        if rel.startswith(prefix + "/") and rel not in seen:
                            seen[rel] = True
        return sorted(seen)

    def script_text(self, vpath: str) -> str:
        vpath = vpath.replace("\\", "/").lower()
        for arc in self._script_archives():
            if vpath in arc.files:
                return arc.read(vpath).decode("utf-8", "replace")
        for d in self._script_fallback_dirs():
            p = d / vpath
            if p.exists():
                return p.read_text(encoding="utf-8", errors="replace")
        raise FileNotFoundError(f"script not found in archives or fallbacks: {vpath}")


def open_source(game: str | None = None) -> GameSource:
    """Build a GameSource from settings.json (falls back to registry defaults)."""
    import json
    import games as games_reg
    settings = {}
    sp = ROOT / "settings.json"
    if sp.exists():
        settings = json.loads(sp.read_text())
    game = game or settings.get("active_game", "dow2cr")
    gp = settings.get("games", {}).get(game, {}).get("game_path") \
        or games_reg.game_def(game)["default_game_path"]
    return GameSource(game, Path(gp))
