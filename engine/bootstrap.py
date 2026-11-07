"""First-run bootstrap — generate all game-derived data from the player's
own installation, so the distributed builder ships with no game content.

What it prepares (idempotent; only missing pieces are generated):
  gamedata/DOW2.module              copied from the DoW2/CR install
  gamedata/retribution/DOW2.module  copied from the Retribution install
  gamedata/dow2cr_keydefaults.lua   copied from My Games Settings (if present)
  gamedata/dow2cr_scripts/**        effective campaign lua + procedural scar,
                                    extracted at true patch priority
Also auto-detects Steam install paths when the configured ones don't exist.
"""
from __future__ import annotations
import re
import shutil
import string
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sga  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS_LOCK = threading.Lock()

# priority order of data archives for DoW2/CR (first hit wins)
_DATA_ORDER = ["240_data.sga", "230_data.sga", "220_data.sga", "210_data.sga",
               "200_data.sga", "GameDefault_DELTA.sga", "gamedefault.sga"]
_SCRIPT_PREFIXES = ("campaign/", "simulation/scar/proceduralcontent/")

GAME_DIRS = {"dow2cr": ["Dawn of War 2"],
             "retribution": ["Dawn of War II - Retribution",
                             "Dawn of War II – Retribution"]}


def _steam_libraries(extra_roots=()) -> list[Path]:
    """Every Steam library folder on this machine, best effort.

    Asking Steam where its libraries are beats guessing: people put them on
    any drive under any folder name, so a fixed list of locations only ever
    finds the common cases.
    """
    steam_dirs: list[Path] = []
    try:                                   # Windows: Steam records its own home
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE,
                           r"SOFTWARE\WOW6432Node\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for value in ("SteamPath", "InstallPath"):
                        try:
                            v = winreg.QueryValueEx(k, value)[0]
                            if v:
                                steam_dirs.append(Path(str(v)))
                        except OSError:
                            pass
            except OSError:
                pass
    except Exception:
        pass
    for common in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        steam_dirs.append(Path(common))
    steam_dirs.extend(Path(r) for r in extra_roots)   # injectable, for tests

    libs: list[Path] = []
    seen: set[str] = set()
    def _add(p: Path) -> None:
        key = str(p).rstrip("\\/").lower()
        if key and key not in seen:
            seen.add(key)
            libs.append(p)
    for sd in steam_dirs:
        _add(sd)
        # libraryfolders.vdf lists every library Steam knows about
        for vdf in (sd / "steamapps" / "libraryfolders.vdf",
                    sd / "config" / "libraryfolders.vdf"):
            try:
                text = vdf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in re.finditer(r'"path"\s*"([^"]+)"', text):
                _add(Path(m.group(1).replace("\\\\", "\\")))
    return libs


def detect_game_path(game: str, extra_roots=()) -> str | None:
    """Find the install: ask Steam first, then scan the usual locations."""
    names = GAME_DIRS.get(game, [])
    for lib in _steam_libraries(extra_roots):
        for name in names:
            p = lib / "steamapps" / "common" / name
            try:
                if (p / "DOW2.exe").exists():
                    return str(p)
            except OSError:
                continue
    stems = [r"Program Files (x86)\Steam\steamapps\common",
             r"Program Files\Steam\steamapps\common",
             r"SteamLibrary\steamapps\common",
             r"Steam\steamapps\common",
             r"Games\SteamLibrary\steamapps\common"]
    for drive in string.ascii_uppercase:
        for stem in stems:
            for name in names:
                p = Path(f"{drive}:\\") / stem / name
                if (p / "DOW2.exe").exists():
                    return str(p)
    return None


def ensure_settings() -> dict:
    """Create/repair settings.json with detected game paths."""
    import json
    sp = ROOT / "settings.json"
    s = json.loads(sp.read_text()) if sp.exists() else {}
    s.setdefault("games", {})
    changed = not sp.exists()
    titles = {"dow2cr": "DoW2 + Chaos Rising (Anniversary Edition)",
              "retribution": "DoW2 - Retribution"}
    for g in ("dow2cr", "retribution"):
        gc = s["games"].setdefault(g, {"title": titles[g], "game_path": ""})
        gp = gc.get("game_path", "")
        if not gp or not (Path(gp) / "DOW2.exe").exists():
            found = detect_game_path(g)
            if found and found != gp:
                gc["game_path"] = found
                changed = True
    s.setdefault("active_game", "dow2cr")
    if changed:
        sp.write_text(json.dumps(s, indent=2))
    return s


def ensure_gamedata(log=print) -> list[str]:
    """Generate missing game-derived files. Returns a list of actions done."""
    done: list[str] = []
    import json
    sp = ROOT / "settings.json"
    s = json.loads(sp.read_text()) if sp.exists() else {}
    games = s.get("games", {})

    # ---- base .module copies --------------------------------------------
    for g, rel in (("dow2cr", "gamedata/DOW2.module"),
                   ("retribution", "gamedata/retribution/DOW2.module")):
        dst = ROOT / rel
        gp = games.get(g, {}).get("game_path", "")
        src_mod = Path(gp) / "DOW2.module" if gp else None
        if not dst.exists() and src_mod and src_mod.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src_mod.read_bytes())
            done.append(f"copied base module for {g}")

    # ---- locale snapshots (display names for the catalogs) ---------------
    for g, rel in (("dow2cr", "gamedata/DOW2.ucs"),
                   ("retribution", "gamedata/retribution/DOW2.ucs")):
        dst = ROOT / rel
        gp = games.get(g, {}).get("game_path", "")
        src_ucs = (Path(gp) / "GameAssets" / "Locale" / "English" / "DOW2.ucs"
                   if gp else None)
        if not dst.exists() and src_ucs and src_ucs.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src_ucs.read_bytes())
            done.append(f"snapshotted item names for {g}")

    # ---- keydefaults snapshots ------------------------------------------
    for mg, rel in (("Dawn of War 2", "gamedata/dow2cr_keydefaults.lua"),
                    ("Dawn of War II - Retribution",
                     "gamedata/retribution/keydefaults.lua")):
        kd_dst = ROOT / rel
        if kd_dst.exists():
            continue
        kd_src = (Path.home() / "Documents" / "My Games" / mg
                  / "Settings" / "_keydefaults.lua")
        if kd_src.exists():
            kd_dst.parent.mkdir(parents=True, exist_ok=True)
            kd_dst.write_bytes(kd_src.read_bytes())
            done.append(f"snapshotted key defaults ({mg})")

    # ---- effective campaign scripts (DoW2/CR) ---------------------------
    gp = games.get("dow2cr", {}).get("game_path", "")
    if ensure_scripts(gp, log):
        done.append("extracted the campaign scripts at patch priority")
    return done


def scripts_ready() -> bool:
    return (ROOT / "gamedata" / "dow2cr_scripts" / "campaign" / "tuning.lua").exists()


def _copy_tree(tmp: Path, dst: Path) -> None:
    for item in tmp.rglob("*"):
        if item.is_file():
            out = dst / item.relative_to(tmp)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(item.read_bytes())


def require_scripts(src=None, log=print) -> Path:
    """Return the campaign-scripts snapshot folder, reading it out of the
    player's install on demand. Modules call this instead of assuming the
    first-run bootstrap already finished — a build started before (or instead
    of) that one-time step then just works."""
    dst = ROOT / "gamedata" / "dow2cr_scripts"
    if scripts_ready():
        return dst
    gp = ""
    if src is not None and getattr(src, "game", "") == "dow2cr":
        gp = str(getattr(src, "game_path", "") or "")
    if not gp:
        try:
            gp = ensure_settings()["games"].get("dow2cr", {}).get("game_path", "")
        except Exception:
            gp = ""
    ensure_scripts(gp, log)
    if not scripts_ready():
        raise ValueError(
            "This option needs the campaign scripts from your Dawn of War II "
            "/ Chaos Rising install, and they could not be read. Open Settings "
            "and check the game folder is right (it must be the folder holding "
            "DOW2.exe), then build again.")
    return dst


def ensure_scripts(game_path, log=print) -> bool:
    """Extract the effective (patch-priority) campaign scripts from the
    player's own DoW2/CR install. Safe to call any time; does nothing when the
    snapshot is already there. Returns True if it extracted something.

    Serialised: a build asking for the scripts while the background first-run
    pass is still extracting them simply waits for that pass to finish."""
    if scripts_ready():
        return False
    if not game_path:
        return False
    arcs_dir = Path(game_path) / "GameAssets" / "Archives"
    if not arcs_dir.exists():
        return False
    with _SCRIPTS_LOCK:
        if scripts_ready():
            return False
        return _extract_scripts(arcs_dir, log)


def _extract_scripts(arcs_dir: Path, log) -> bool:
    scripts_dst = ROOT / "gamedata" / "dow2cr_scripts"
    log("[bootstrap] reading campaign scripts from your game install "
        "(one-time, up to a minute)...")
    eff: dict[str, str] = {}
    opened = {}
    for name in _DATA_ORDER:
        p = arcs_dir / name
        if not p.exists():                     # case-insensitive fallback
            cands = [c for c in arcs_dir.iterdir()
                     if c.name.lower() == name.lower()]
            if not cands:
                continue
            p = cands[0]
        try:
            opened[name] = a = sga.SgaArchive.open(p)
        except Exception as e:
            log(f"[bootstrap] skipped {p.name}: {e}")
            continue
        for f in a.files:
            if f.startswith(_SCRIPT_PREFIXES) and f.endswith((".lua", ".scar")) \
                    and f not in eff:
                eff[f] = name
    if not eff:
        log("[bootstrap] no campaign scripts found in the game archives")
        return False
    tmp = scripts_dst.with_name(scripts_dst.name + ".part")
    n = 0
    for f, name in eff.items():                # write to .part, then swap in,
        dst = tmp / f                          # so a half-done run is never
        dst.parent.mkdir(parents=True, exist_ok=True)   # mistaken for complete
        dst.write_bytes(opened[name].read(f))
        n += 1
    if not scripts_dst.exists():
        scripts_dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            tmp.replace(scripts_dst)           # single atomic rename: another
        except OSError:                        # thread never sees it half-done
            _copy_tree(tmp, scripts_dst)
    else:
        _copy_tree(tmp, scripts_dst)
    shutil.rmtree(tmp, ignore_errors=True)
    log(f"[bootstrap] campaign scripts ready ({n} files)")
    return True
