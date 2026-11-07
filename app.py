#!/usr/bin/env python3
"""DoW2 Mod Framework — local mod manager.

Run:  python app.py        (then open http://localhost:8420)

Pure Python standard library; no external dependencies; no network access
beyond localhost. All state lives in this folder:
    config/*.json            mod configurations (source of truth)
    workspace/build/<Mod>/   generated mod output + manifest
    workspace/extracted/     pristine extracted game data (read-only inputs)
    settings.json            game path + options
The original game installation is only ever ADDED to (Mod.module + Mod\\ folder
on install), and those exact paths are removed again on uninstall.
"""
from __future__ import annotations
import importlib
import io
import json
import re
import shutil
import sys
import threading
import time
import traceback
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# When frozen into an exe (PyInstaller), everything lives NEXT TO the exe:
# the ui/, engine/, modules/, config/ folders ship alongside it.
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine"))

CONFIG_DIR = ROOT / "config"
BUILD_DIR = ROOT / "workspace" / "build"
LOG_FILE = ROOT / "workspace" / "logs" / "modmanager.log"
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{1,31}$")
VERSION = "1.2.6"


def _build_stamp() -> str:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent / "engine"))
        import buildstamp
        return buildstamp.stamp(Path(__file__).resolve().parent)
    except Exception:
        return "unknown"


BUILD_STAMP = _build_stamp()

_log_lock = threading.Lock()


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    # sys.__stdout__, not print(): during a build stdout is captured, and
    # printing there would feed the capture straight back into this function
    try:
        if sys.__stdout__ is not None:
            sys.__stdout__.write(line + "\n")
            sys.__stdout__.flush()
    except Exception:
        pass
    with _log_lock:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def settings() -> dict:
    p = ROOT / "settings.json"
    s = json.loads(p.read_text()) if p.exists() else {}
    s.setdefault("port", 8420)
    # migrate single-game settings to the multi-game structure
    if "games" not in s:
        try:
            import bootstrap
            det = {g: (bootstrap.detect_game_path(g) or "")
                   for g in ("dow2cr", "retribution")}
        except Exception:
            det = {"dow2cr": "", "retribution": ""}
        s["games"] = {
            "dow2cr": {"title": "DoW2 + Chaos Rising (Anniversary Edition)",
                       "game_path": s.get("game_path", det["dow2cr"])},
            "retribution": {"title": "DoW2 - Retribution",
                            "game_path": det["retribution"]},
        }
    s.setdefault("active_game", "dow2cr")
    # legacy mirror — tolerate a settings file that has been edited by hand and
    # is missing pieces, rather than failing every request
    gc = s["games"].setdefault(s["active_game"], {})
    s["game_path"] = gc.get("game_path", "")
    return s


def active_game() -> str:
    return settings()["active_game"]


def game_path_of(game: str) -> Path:
    s = settings()
    return Path(s["games"].get(game, {}).get("game_path", s["game_path"]))


def save_settings(s: dict) -> None:
    (ROOT / "settings.json").write_text(json.dumps(s, indent=2))
    _STATE_CACHE.clear()          # game paths may have moved


_SCHEMA_CACHE: dict = {}
_STATE_CACHE: dict = {}


def schemas() -> dict:
    """Module option schemas. Re-read only when a module file actually
    changes — the page asks for these on every refresh, and re-importing
    twenty modules each time is what made a finished build feel slow."""
    pys = sorted((ROOT / "modules").glob("*.py"))
    stamp = tuple((py.name, py.stat().st_mtime_ns) for py in pys)
    if _SCHEMA_CACHE.get("stamp") == stamp:
        return _SCHEMA_CACHE["data"]
    out = {}
    for py in pys:
        if py.name.startswith("_"):
            continue
        mod = importlib.import_module(f"modules.{py.stem}")
        importlib.reload(mod)
        if hasattr(mod, "SCHEMA"):
            sch = dict(mod.SCHEMA)
            sch["games"] = getattr(mod, "GAMES", ["dow2cr"])
            out[py.stem] = sch
    _SCHEMA_CACHE.update(stamp=stamp, data=out)
    return out


_MOD_CACHE: dict = {}


def _build_summary(build: Path) -> dict | None:
    """What the dashboard needs about a build. Prefers summary.json, which the
    builder writes alongside manifest.json — a big mod's manifest runs to many
    megabytes, and re-reading it on every refresh is what left the card sitting
    on 'built' with an empty change list for several seconds."""
    sp, mp = build / "summary.json", build / "manifest.json"
    if sp.exists():
        try:
            return json.loads(sp.read_text())
        except (ValueError, OSError):
            pass
    if not mp.exists():
        return None
    m = json.loads(mp.read_text())              # pre-1.0.5 build: derive it
    s = {"built": m["built"],
         "transformations": m["transformations"][:40],
         "transformations_total": len(m["transformations"]),
         "files_changed": [f["file"] for f in m["files_changed"]],
         "warnings": m.get("warnings", [])}
    try:
        sp.write_text(json.dumps(s))            # so it's cheap from now on
    except OSError:
        pass
    return s


def mod_state(cfg_path: Path, game: Path) -> dict:
    build_p = None
    key = str(cfg_path)
    stamp = [cfg_path.stat().st_mtime_ns, 0]
    hit = _MOD_CACHE.get(key)
    if hit:
        build_p = hit["build"]
        for f in ("summary.json", "manifest.json"):
            p = build_p / f
            if p.exists():
                stamp[1] = p.stat().st_mtime_ns
                break
        if hit["stamp"] == tuple(stamp):
            st = dict(hit["state"])
            st["installed"] = (game_path_of(st["game"]) / f"{st['name']}.module").exists()
            return st

    cfg = json.loads(cfg_path.read_text())
    name = cfg["mod"]["name"]
    mod_game = cfg.get("game", "dow2cr")
    build = BUILD_DIR / name
    s = _build_summary(build)
    for f in ("summary.json", "manifest.json"):
        p = build / f
        if p.exists():
            stamp[1] = p.stat().st_mtime_ns
            break
    state = {
        "name": name,
        "game": mod_game,
        "config_file": cfg_path.name,
        "config": cfg,
        "built": s is not None,
        "built_at": s["built"] if s else None,
        "installed": False,
        "files_changed": s["files_changed"] if s else [],
        # only the preview the card shows — full detail stays in manifest.json
        "transformations": s["transformations"] if s else [],
        "transformations_total": s["transformations_total"] if s else 0,
        "warnings": s.get("warnings", []) if s else [],
    }
    _MOD_CACHE[key] = {"stamp": tuple(stamp), "state": state, "build": build}
    st = dict(state)
    st["installed"] = (game_path_of(mod_game) / f"{name}.module").exists()
    return st


def full_state() -> dict:
    s = settings()
    game = Path(s["game_path"])
    mods = []
    CONFIG_DIR.mkdir(exist_ok=True)
    for cfg_path in sorted(CONFIG_DIR.glob("*.json")):
        try:
            mods.append(mod_state(cfg_path, game))
        except Exception as e:  # corrupt config shouldn't kill the dashboard
            mods.append({"name": cfg_path.stem, "error": str(e), "config_file": cfg_path.name})
    # conflict detection: built mods touching the same game file.
    # A profile never "conflicts" with its own members, and conflicts are
    # aggregated per mod-pair rather than reported per file.
    members_of = {m["name"]: set(m.get("config", {}).get("profile") or []) for m in mods}
    seen: dict[str, list[str]] = {}
    for m in mods:
        for f in m.get("files_changed", []):
            seen.setdefault(f, []).append(m["name"])
    pair_files: dict[tuple, list[str]] = {}
    for f, names in seen.items():
        if len(names) < 2:
            continue
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                if b in members_of.get(a, ()) or a in members_of.get(b, ()):
                    continue  # profile vs its own member
                pair_files.setdefault(tuple(sorted((a, b))), []).append(f)
    conflicts = [{"mods": list(pair), "count": len(files),
                  "file": files[0] + (f"  (+{len(files)-1} more files)" if len(files) > 1 else "")}
                 for pair, files in sorted(pair_files.items())]
    for m in mods:                      # the browser never reads these
        n_files = len(m.pop("files_changed", []) or [])
        if m.get("built"):
            m["files_changed_count"] = n_files
    tail = ""
    if LOG_FILE.exists():                # read the tail only — the log grows
        with open(LOG_FILE, "rb") as f:  # all session and gets re-read often
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            chunk = f.read().decode("utf-8", "replace")
        tail = "\n".join(chunk.splitlines()[-200:])
    def source_stat(g):
        cached = _STATE_CACHE.get(("source", g, str(game_path_of(g))))
        if cached is not None:
            return cached
        try:
            s2 = game_source(g)
            idx_p = ROOT / "knowledge" / _INDEX_FILES.get(g, "entity_index.json")
            gen = None
            if idx_p.exists():
                gen = json.loads(idx_p.read_text()).get("generated")
            stat = {"ok": True, "trees": len(s2.attrib_paths()),
                    "knowledge_generated": gen}
        except Exception as e:
            stat = {"ok": False, "error": str(e)}
        _STATE_CACHE[("source", g, str(game_path_of(g)))] = stat
        return stat
    return {
        "settings": s,
        "active_game": s["active_game"],
        "games": {g: {"title": gc.get("title", g), "game_path": gc.get("game_path"),
                      "detected": (Path(gc.get("game_path", "")) / "DOW2.exe").exists()}
                  for g, gc in s["games"].items()},
        "game_detected": (game / "DOW2.exe").exists(),
        "chaos_rising": (game / "ChaosRisingGDF.dll").exists(),
        "source": source_stat(s["active_game"]),
        "schemas": schemas(),
        "mods": mods,
        "conflicts": conflicts,
        "log": tail,
        "python": sys.version.split()[0],
        "version": VERSION,
        "build": BUILD_STAMP,
        "root": str(ROOT),
    }


# ---------------- game source (direct archive access) ----------------------

_SOURCES: dict = {}


def game_source(game: str | None = None):
    import source as source_mod
    g = game or active_game()
    key = (g, str(game_path_of(g)))
    if key not in _SOURCES:
        _SOURCES[key] = source_mod.GameSource(g, game_path_of(g))
    return _SOURCES[key]


# ---------------- entity index / data browser ------------------------------

_INDEX_CACHE: dict = {}


_INDEX_FILES = {"dow2cr": "entity_index.json",
                "retribution": "entity_index_retribution.json"}


def entity_index(game: str | None = None) -> dict:
    """Load the game's entity index once; derive reverse edges."""
    g = game or active_game()
    idx_p = ROOT / "knowledge" / _INDEX_FILES.get(g, "entity_index.json")
    if not idx_p.exists():
        return {"entities": [], "by_path": {}, "refs_in": {}}
    mtime = idx_p.stat().st_mtime
    slot = _INDEX_CACHE.setdefault(g, {})
    if slot.get("mtime") == mtime:
        return slot["data"]
    raw = json.loads(idx_p.read_text())
    by_path = {e["path"]: e for e in raw["entities"]}
    refs_in: dict[str, list[str]] = {}
    for e in raw["entities"]:
        for r in e.get("refs_out", []):
            refs_in.setdefault(r, []).append(e["path"])
    data = {"entities": raw["entities"], "by_path": by_path, "refs_in": refs_in}
    slot.update(mtime=mtime, data=data)
    return data


def api_entities(query: dict) -> dict:
    idx = entity_index(query.get("game"))
    q = (query.get("q") or "").lower().strip()
    cat = (query.get("cat") or "").strip()
    terms = q.split()
    out = []
    for e in idx["entities"]:
        if cat and e["category"] != cat:
            continue
        hay = (e["path"] + " " + str(e.get("name", ""))).lower()
        if terms and not all(t in hay for t in terms):
            continue
        out.append({"path": e["path"], "category": e["category"],
                    "name": e.get("name"),
                    "refs": len(e.get("refs_out", [])),
                    "used_by": len(idx["refs_in"].get(e["path"], []))})
        if len(out) >= 200:
            break
    cats = sorted({e["category"] for e in idx["entities"]})
    return {"results": out, "categories": cats, "total": len(idx["entities"])}


def _tree_json(node, ipath=""):
    import rbf as _rbf
    kind = ("bool", "float", "int", "string", "table")[node.type]
    if node.type == 4:
        counts = {}
        kids = []
        for c in node.children:
            n = counts.get(c.key, 0)
            counts[c.key] = n + 1
            seg = c.key if n == 0 else f"{c.key}[{n}]"
            kids.append(_tree_json(c, f"{ipath}/{seg}" if ipath else seg))
        return {"key": node.key, "type": kind, "children": kids, "ipath": ipath}
    return {"key": node.key, "type": kind, "value": node.value, "ipath": ipath}


def api_entity(query: dict) -> dict:
    import rbf as _rbf
    idx = entity_index(query.get("game"))
    path = (query.get("path") or "").replace("\\", "/")
    e = idx["by_path"].get(path)
    if e is None:
        raise ValueError(f"unknown entity: {path}")
    tree = game_source("dow2cr").attrib_tree(path)
    root = {"key": "(file)", "type": "table", "ipath": "",
            "children": [_tree_json(c, c.key) for c in tree.children]}
    def label(p):
        t = idx["by_path"].get(p, {})
        return {"path": p, "name": t.get("name"), "category": t.get("category")}
    icon_n = None
    try:
        _n = _rbf.find(tree, "ui/icon_name") or _rbf.find(tree.children[0], "ui/icon_name") if tree.children else None
        if _n is not None and getattr(_n, "value", None):
            icon_n = _n.value
    except Exception:
        pass
    return {
        "path": path, "category": e["category"], "name": e.get("name"),
        "icon": icon_n,
        "tree": root,
        "refs_out": [label(p) for p in e.get("refs_out", [])],
        "refs_in": [label(p) for p in idx["refs_in"].get(path, [])[:100]],
        "refs_in_total": len(idx["refs_in"].get(path, [])),
    }


_STAT_TARGETS_CACHE: dict = {}
_ICON_CACHE: dict = {}
_UNIT_CATALOG_CACHE: dict = {}


def api_unit_catalog(query: dict | None = None) -> dict:
    from modules import unit_stats
    game = (query or {}).get("game") or active_game()
    src = game_source(game)
    key = (game, str(src.game_path))
    if key not in _UNIT_CATALOG_CACHE:
        _UNIT_CATALOG_CACHE[key] = unit_stats.catalog(src)
    return {"squads": _UNIT_CATALOG_CACHE[key],
            "stat_meta": unit_stats.STAT_META,
            "squad_stats": list(unit_stats.SQUAD_STATS),
            "entity_stats": list(unit_stats.ENTITY_STATS),
            "growth_stats": list(unit_stats.GROWTH_STATS)}


def api_stat_targets(query: dict) -> dict:
    from modules import stat_tweaks
    stat = query.get("stat") or ""
    if stat not in stat_tweaks.STATS:
        raise ValueError(f"unknown stat {stat!r}")
    src = game_source(query.get("game") or active_game())
    key = (stat, str(src.game_path))
    if key not in _STAT_TARGETS_CACHE:
        _STAT_TARGETS_CACHE[key] = stat_tweaks.list_targets(src, stat)
    return {"stat": stat, "targets": _STAT_TARGETS_CACHE[key]}


# ---------------- actions -------------------------------------------------

def action_add_override(body):
    """Append one override (from the Data Browser) into a mod config."""
    mod_name = body["mod"]
    ov = body["override"]  # {file, path, value}
    if not NAME_RE.match(mod_name):
        raise ValueError("bad mod name")
    cfg_p = CONFIG_DIR / f"{mod_name.lower()}.json"
    if cfg_p.exists():
        cfg = json.loads(cfg_p.read_text())
    else:
        cfg = {"mod": {"name": mod_name, "title": mod_name,
                       "description": "Raw overrides from the Data Browser",
                       "category": "Overrides"}, "modules": {}}
    m = cfg["modules"].setdefault("generic_overrides", {"enabled": True, "overrides": []})
    ovs = m.setdefault("overrides", [])
    ovs[:] = [o for o in ovs if not (o["file"] == ov["file"] and o["path"] == ov["path"])]
    ovs.append(ov)
    cfg_p.write_text(json.dumps(cfg, indent=2))
    log(f"Override added to {mod_name}: {ov['file']} :: {ov['path']} = {ov['value']!r}")
    return {"ok": True, "count": len(ovs)}


def action_build_index(_body):
    import build_index
    importlib.reload(build_index)
    buf = io.StringIO()
    with redirect_stdout(buf):
        build_index.build()
    for line in buf.getvalue().splitlines():
        log(line)
    return {"ok": True}


def action_extract(body):
    """Rebuild derived knowledge (catalog + entity index) by reading the game
    archives directly. Nothing is extracted or duplicated on disk any more —
    the framework stores only the files a mod actually changes."""
    game = (body or {}).get("game") or active_game()
    _SOURCES.clear()          # re-open archives (picks up game patches)
    _STATE_CACHE.clear()
    _STAT_TARGETS_CACHE.clear()
    _UNIT_CATALOG_CACHE.clear()
    _INDEX_CACHE.clear()
    src = game_source(game)
    n = len(src.attrib_paths())
    log(f"[{game}] source archives OK - {n} attribute trees readable")
    if game in ("dow2cr", "retribution"):
        for step in ("build_catalog", "build_index"):
            mod = importlib.import_module(step)
            importlib.reload(mod)
            buf = io.StringIO()
            with redirect_stdout(buf):
                mod.build(game)
            for line in buf.getvalue().splitlines():
                log(line)
    return {"game": game, "attribute_trees": n,
            "note": "read directly from archives; no files copied"}


def action_save_mod(body):
    cfg = body["config"]
    name = cfg["mod"]["name"]
    if not NAME_RE.match(name):
        raise ValueError("Mod name must be 2-32 chars, letters/digits/underscore, starting with a letter")
    (CONFIG_DIR / f"{name.lower()}.json").write_text(json.dumps(cfg, indent=2))
    log(f"Saved config for {name}")
    return {"ok": True}


def action_delete_mod(body):
    name = body["name"]
    p = CONFIG_DIR / f"{name.lower()}.json"
    if p.exists():
        p.unlink()
    log(f"Deleted config {name} (build output kept in workspace/build)")
    return {"ok": True}


_BUILD_PROGRESS = {"running": False, "name": "", "line": "", "steps": 0,
                   "started": 0.0, "estimate": 0.0}

# Cloud-measured cost of a full sweep of each module (seconds on the reference
# machine, per reports/validation_report.json). Used only when a mod has never
# been built before; after that the mod's own last duration is the estimate.
_MODULE_UNITS = {
    "mass_scaling": 2.2, "enemy_tuning": 2.4, "xp_tuning": 1.8,
    "ability_tuning": 0.6, "ability_hotkeys": 0.9, "loot_mix": 1.0,
    "loot_quality": 0.7, "wargear_restrictions": 0.9, "last_stand": 0.3,
    "respec": 0.5, "unit_stats": 0.2, "stat_tweaks": 0.2,
    "difficulty_tuning": 0.1, "campaign_loot": 0.1, "campaign_pacing": 0.1,
    "mission_generators": 0.1, "mission_rewards": 0.1,
    "generic_overrides": 0.1, "loadouts": 0.1,
    "corruption_tuning": 0.1, "accessory_slots": 0.1,
}
_CALIB_FILE = ROOT / "workspace" / "calibration.json"


def _calibration() -> float:
    """How much slower this machine is than the reference (starts at 4x —
    a typical desktop against the tuned reference box — and learns from every
    completed build)."""
    try:
        return max(0.5, min(40.0, float(
            json.loads(_CALIB_FILE.read_text())["factor"])))
    except Exception:
        return 4.0


def _estimate_build(name: str) -> tuple[float, float]:
    """(estimated_seconds, units). Last real duration of this mod wins;
    otherwise module weights x machine calibration."""
    units = 1.0
    try:
        cfg = json.loads((CONFIG_DIR / f"{name.lower()}.json").read_text())
        mods = cfg.get("modules", {})
        if cfg.get("profile"):
            mods = {m: {} for member in cfg["profile"]
                    for m in json.loads((CONFIG_DIR / f"{member.lower()}.json")
                                        .read_text()).get("modules", {})}
        units += sum(_MODULE_UNITS.get(m, 0.3)
                     for m, mc in mods.items() if mc.get("enabled", True) or not mc)
    except Exception:
        units += 3.0
    sp = BUILD_DIR / name / "summary.json"
    try:
        prev = float(json.loads(sp.read_text()).get("seconds") or 0)
        if prev > 0:
            return max(3.0, prev * 1.1), units
    except Exception:
        pass
    return max(3.0, units * _calibration()), units


def _learn_calibration(units: float, actual: float) -> None:
    if units <= 0 or actual <= 0:
        return
    try:
        old = _calibration()
        new = max(0.5, min(40.0, 0.7 * old + 0.3 * (actual / units)))
        _CALIB_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CALIB_FILE.write_text(json.dumps({"factor": round(new, 2)}))
    except OSError:
        pass
# One build at a time. A second build started while one is running wipes and
# rewrites the same output folder underneath it, which fails mid-pack with a
# confusing "cannot find the path specified".
_BUILD_LOCK = threading.Lock()


class _LiveLog(io.TextIOBase):
    """Feeds a build's output to the log and the progress endpoint line by line,
    so the page can show what the build is actually doing instead of a spinner
    with no news."""

    def __init__(self, name: str):
        self.mod = name
        self.buf = ""

    def write(self, s: str) -> int:
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                _BUILD_PROGRESS["line"] = line.strip()[:180]
                _BUILD_PROGRESS["steps"] += 1
                log(f"build[{self.mod}] {line}")
        return len(s)


def build_progress() -> dict:
    p = dict(_BUILD_PROGRESS)
    p["elapsed"] = round(time.time() - p["started"], 1) if p["running"] else 0
    p["remaining"] = round(max(0.0, p.get("estimate", 0) - p["elapsed"]), 1) \
        if p["running"] else 0
    return p


def action_build(body):
    name = body["name"]
    if not _BUILD_LOCK.acquire(blocking=False):
        raise ValueError(f"A build is already running "
                         f"({_BUILD_PROGRESS.get('name') or 'another mod'}) — "
                         "wait for it to finish before starting another.")
    try:
        return _do_build(name)
    finally:
        _BUILD_LOCK.release()


def _do_build(name):
    # reload the whole build pipeline so a running app always builds with
    # current code (engine included) — stale in-memory modules otherwise
    # survive file updates and cause attribute errors
    import source as source_mod
    importlib.reload(source_mod)
    _SOURCES.clear()
    import build_mod
    importlib.reload(build_mod)
    cfg_path = CONFIG_DIR / f"{name.lower()}.json"
    est, units = _estimate_build(name)
    _BUILD_PROGRESS.update(running=True, name=name, line="starting…", steps=0,
                           started=time.time(), estimate=round(est, 1))
    t0 = time.time()
    try:
        with redirect_stdout(_LiveLog(name)):
            manifest = build_mod.build(str(cfg_path))
        _learn_calibration(units, time.time() - t0)
    finally:
        _BUILD_PROGRESS.update(running=False, line="")
    return {"ok": True, "summary": {
        "transformations": len(manifest["transformations"]),
        "files": len(manifest["files_changed"]),
        "archives": list(manifest.get("archives", {})),
        "warnings": len(manifest.get("warnings", []))}}


def _install_paths(name: str):
    cfg_p = CONFIG_DIR / f"{name.lower()}.json"
    mod_game = "dow2cr"
    if cfg_p.exists():
        try:
            mod_game = json.loads(cfg_p.read_text()).get("game", "dow2cr")
        except Exception:
            pass
    game = game_path_of(mod_game)
    return game / f"{name}.module", game / name


def action_install(body):
    name = body["name"]
    if not NAME_RE.match(name) or name.lower() in ("gameassets", "tools", "assets", "install", "drivers", "manual"):
        raise ValueError("refusing to install with unsafe mod name")
    build = BUILD_DIR / name
    if not (build / "manifest.json").exists():
        raise ValueError("build the mod first")
    module_dst, folder_dst = _install_paths(name)
    shutil.copy2(build / f"{name}.module", module_dst)
    if folder_dst.exists():
        shutil.rmtree(folder_dst)
    shutil.copytree(build / name, folder_dst)
    log(f"Installed {name} -> {module_dst.parent} (additive only)")
    return {"ok": True, "launch_options": f"-modname {name}"}


def action_uninstall(body):
    name = body["name"]
    if not NAME_RE.match(name) or name.lower() in ("gameassets", "tools", "assets", "install", "drivers", "manual"):
        raise ValueError("refusing to uninstall unsafe name")
    module_dst, folder_dst = _install_paths(name)
    if module_dst.exists():
        module_dst.unlink()
    if folder_dst.exists():
        shutil.rmtree(folder_dst)
    log(f"Uninstalled {name} (removed {module_dst.name} and {folder_dst.name}\\)")
    return {"ok": True}


def action_settings(body):
    s = settings()
    s.update(body.get("settings", {}))
    save_settings(s)
    log("Settings updated")
    return {"ok": True}


# ---------------- controls / hotkeys --------------------------------------

_MYGAMES_NAMES = {"dow2cr": "Dawn of War 2",
                  "retribution": "Dawn of War II - Retribution"}


def controls_settings_dir(game: str) -> Path:
    s = settings()
    override = s.get("games", {}).get(game, {}).get("mygames_path")
    if override:
        return Path(override) / "Settings"
    return (Path.home() / "Documents" / "My Games"
            / _MYGAMES_NAMES.get(game, "Dawn of War 2") / "Settings")


def _controls_defaults_text(game: str) -> str:
    cands = [controls_settings_dir(game) / "_keydefaults.lua"]
    if game == "dow2cr":   # snapshot + cloud-dev fallbacks
        cands += [Path("/mnt/user-data/uploads/My Games--Dawn of War 2/Settings/_keydefaults.lua"),
                  ROOT / "gamedata" / "dow2cr_keydefaults.lua"]
    elif game == "retribution":
        cands += [ROOT / "gamedata" / "retribution" / "keydefaults.lua"]
    for c in cands:
        if c.exists():
            return c.read_text(encoding="utf-8", errors="replace")
    raise FileNotFoundError(
        f"_keydefaults.lua not found for {game} — launch the game once so it "
        f"generates {cands[0]}")


def api_controls(query: dict) -> dict:
    import keybinds
    game = query.get("game") or active_game()
    text = _controls_defaults_text(game)
    defaults = keybinds.parse(text)
    sdir = controls_settings_dir(game)
    custom_p = sdir / "keydefaults.lua"
    custom = {}
    active = custom_p.exists()
    if active:
        cur = {b.name: b.combo for b in keybinds.parse(
            custom_p.read_text(encoding="utf-8", errors="replace"))}
        for b in defaults:
            if b.name in cur and cur[b.name] != b.combo:
                custom[b.name] = cur[b.name]
    presets = {}
    for k, v in keybinds.PRESETS.items():
        remaps = (keybinds.expand_wasd(defaults)
                  if v.get("dynamic") == "wasd" else v["remaps"])
        presets[k] = {kk: vv for kk, vv in v.items()
                      if kk not in ("remaps", "dynamic")} | {"remaps": remaps}
    return {
        "game": game,
        "settings_dir": str(sdir),
        "writable": sdir.exists(),
        "active": active,
        "custom": custom,
        "presets": presets,
        "defaults": [{"name": b.name, "combo": b.combo, "section": b.section}
                     for b in defaults],
    }


def action_apply_controls(body):
    import keybinds
    game = (body or {}).get("game") or active_game()
    remaps = {k: v for k, v in ((body or {}).get("remaps") or {}).items()}
    if not remaps:
        raise ValueError("no remaps given")
    text = _controls_defaults_text(game)
    # tolerant: a remap set carried over from the other game (or an older
    # defaults file) skips absent names instead of failing the whole apply
    new_text, applied = keybinds.apply_overrides(text, remaps, missing_ok=True)
    sdir = controls_settings_dir(game)
    if not sdir.exists():
        raise FileNotFoundError(f"Settings folder not found: {sdir} — launch "
                                "the game once first")
    out = sdir / "keydefaults.lua"
    out.write_text(new_text, encoding="utf-8", newline="")
    confl = keybinds.conflicts(keybinds.parse(text), remaps)
    log(f"[{game}] controls applied: {len(applied)} remap(s) -> {out}")
    skipped = sorted(set(remaps) - set(applied))
    return {"ok": True, "applied": sorted(applied), "skipped": skipped,
            "file": str(out), "conflicts": confl}


def action_revert_controls(body):
    game = (body or {}).get("game") or active_game()
    p = controls_settings_dir(game) / "keydefaults.lua"
    if p.exists():
        p.replace(p.with_suffix(".lua.off"))
        log(f"[{game}] controls reverted (renamed to keydefaults.lua.off)")
        return {"ok": True, "reverted": True}
    return {"ok": True, "reverted": False}


_UCS_TABLES: dict = {}


def _ucs_text(game: str, sid):
    """Resolve a locale string id the way the game does (for item tooltips)."""
    if not sid:
        return None
    if game not in _UCS_TABLES:
        import ucs as _ucs
        rel = ("gamedata/DOW2.ucs" if game == "dow2cr"
               else "gamedata/retribution/DOW2.ucs")
        p = ROOT / rel
        try:
            _UCS_TABLES[game] = _ucs.load(p) if p.exists() else {}
        except Exception:
            _UCS_TABLES[game] = {}
    tbl = _UCS_TABLES[game]
    return tbl.get(int(sid)) or tbl.get(str(int(sid))) or None


def action_loot_unused(body):
    """The items that have no drop pool, grouped by kind, for the UI list."""
    game = body.get("game") or active_game()
    mod = importlib.import_module("modules.loot_mix")
    importlib.reload(mod)
    key = ("lootunused", game, tuple(sorted(body.get("types") or mod.TYPES)))
    out = _STATE_CACHE.get(key)
    if out is None:
        out = mod.unused_census(game_source(game), body.get("types") or mod.TYPES)
        # join the wargear catalog so the list reads like the save editor's gear
        # picker: real in-game name and icon rather than a file stem
        files = {"dow2cr": "wargear_catalog.json",
                 "retribution": "wargear_catalog_retribution.json"}
        cat_p = ROOT / "knowledge" / files.get(game, files["dow2cr"])
        by_path = {}
        if cat_p.exists():
            try:
                for it in (json.loads(cat_p.read_text()).get("items") or []):
                    pth = (it.get("path") or "").replace("\\", "/").lower()
                    if pth:
                        by_path[pth] = it
            except Exception:
                by_path = {}
        for items in out["buckets"].values():
            for i in items:
                c = by_path.get(i["path"].replace("\\", "/").lower()) or {}
                nm = c.get("name") or ""
                i["name"] = nm if nm and not nm.startswith("$") else None
                i["icon"] = c.get("icon")
                i["tag"] = (c.get("wargear_tag") if c.get("wargear_tag")
                            not in (None, "untagged") else None)
                i["campaign"] = mod.campaign_of(i["path"], c.get("campaigns"))
                i["stats"] = [t for t in (_ucs_text(game, x) for x in i.pop("stat_ids", [])) if t]
                i["bonus"] = [t for t in (_ucs_text(game, x) for x in i.pop("bonus_ids", [])) if t]
                i["desc"] = _ucs_text(game, i.pop("desc_id", None))
                i["unique"] = bool(c.get("unique"))
        out["named"] = sum(1 for v in out["buckets"].values()
                           for i in v if i.get("name"))
        _STATE_CACHE[key] = out
    return out


def action_wargear_stats(body):
    """Icon + real stats for one wargear item, for the in-list item viewer."""
    game = body.get("game") or active_game()
    mod = importlib.import_module("modules.loot_mix")
    importlib.reload(mod)
    vp = (body.get("path") or "").replace("\\", "/")
    if not vp:
        raise ValueError("no item path given")
    key = ("wgstats", game, vp)
    out = _STATE_CACHE.get(key)
    if out is None:
        out = mod.item_stats(game_source(game), vp)
        out["text"] = [t for t in (_ucs_text(game, x) for x in
                                   (body.get("string_ids") or [])) if t]
        _STATE_CACHE[key] = out
    return out


def action_loot_preview(body):
    """Vanilla vs planned grade mix for the Loot Rarity Mix module, so the
    numbers can be checked before a build rather than after."""
    game = body.get("game") or active_game()
    mod = importlib.import_module("modules.loot_mix")
    importlib.reload(mod)
    src = game_source(game)
    sources = mod._sources_from_cfg(body)
    grades = mod._grades_from_cfg(body)
    key = ("lootcensus", game, tuple(sorted(body.get("types") or mod.TYPES)),
           tuple(sorted(sources)), tuple(sorted(grades)))
    items = _STATE_CACHE.get(key)
    if items is None:
        items = mod.scan(src, body.get("types") or mod.TYPES, sources, grades)
        _STATE_CACHE[key] = items
    win = (int(body.get("level_min_offset", -2)), int(body.get("level_max_offset", 2)))
    pv = mod.preview(items, body.get("targets") or {}, win,
                     mod._type_weights(src),
                     int(body.get("min_per_bucket", 1)),
                     any_level_grades=body.get("any_level_grades") or [],
                     game=game,
                     duplicate_grades=(body.get("duplicate_grades") or ["epic", "legendary"])
                     if body.get("allow_duplicates") else [],
                     campaign_grades=body.get("base_campaign_grades") or [])
    pv["window"] = list(win)
    pv["items_scanned"] = len(items)
    return pv


# ---------------- campaign save editor ------------------------------------

def saves_dir(game: str) -> Path:
    s = settings()
    override = s.get("games", {}).get(game, {}).get("mygames_path")
    base = (Path(override) if override else
            Path.home() / "Documents" / "My Games" / _MYGAMES_NAMES.get(game, "Dawn of War 2"))
    return base / "Saved Games"


SAVE_EXTS = (".sav", ".sv")

# Steam app id per game; Retribution keeps its campaigns in Steam Cloud
_STEAM_APPIDS = {"retribution": "56400"}


def steam_cloud_dir(game: str) -> Path | None:
    """Folder holding the game's Steam Cloud campaign saves, if there is one.

    Override with ``games.<game>.steam_cloud_path`` in settings. Otherwise look
    in ``userdata\\<account>\\<appid>\\remote`` under every Steam folder and take
    the account with the most ``campaign_*.sav`` files.
    """
    override = settings().get("games", {}).get(game, {}).get("steam_cloud_path")
    if override:
        p = Path(override)
        return p if p.is_dir() else None
    appid = _STEAM_APPIDS.get(game)
    if not appid:
        return None
    import bootstrap
    best, best_n = None, 0
    for lib in bootstrap._steam_libraries():
        try:
            for acct in (lib / "userdata").iterdir():
                remote = acct / appid / "remote"
                n = len(list(remote.glob("campaign_*.sav"))) if remote.is_dir() else 0
                if n > best_n:
                    best, best_n = remote, n
        except OSError:
            continue
    return best


def _list_saves(d: Path) -> list:
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in SAVE_EXTS)


def _is_cloud_save(game: str, p: Path) -> bool:
    cdir = steam_cloud_dir(game)
    return bool(cdir) and p.parent == cdir.resolve()


def _save_path(game: str, name: str) -> Path:
    """Resolve a save name to a file in the game's Saved Games or Steam Cloud folder."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("bad save name")
    p = (saves_dir(game) / name).resolve()
    if not p.exists():
        cdir = steam_cloud_dir(game)
        if cdir and (cdir / name).exists():
            p = (cdir / name).resolve()
            if p.parent != cdir.resolve() or p.suffix.lower() != ".sav":
                raise ValueError("bad save name")
            return p
    if p.parent != saves_dir(game).resolve() or p.suffix.lower() not in SAVE_EXTS:
        raise ValueError("saves can only be read from the game's Saved Games folder")
    return p


def _level_table(game: str) -> list[float]:
    """required_xp_points per level, read from the game's own tuning data, so a
    hero's level always matches what this install would show."""
    key = ("levels", game)
    if key in _STATE_CACHE:
        return _STATE_CACHE[key]
    rows: list[float] = []
    try:
        import rbf
        tab = {"dow2cr": "leveling/campaign_tables",
               "retribution": "leveling/xp2_campaign_tables"}[game]
        t = game_source(game).attrib_tree("tuning/tuning_info.rbf")
        node = rbf.find_indexed(t, f"{tab}/level_xp_table")
        if node is not None:
            for _p, n in rbf.walk(node):
                if n.key == "required_xp_points" and isinstance(n.value, (int, float)):
                    rows.append(float(n.value))
    except Exception as e:
        log(f"[saves] level table unavailable ({e}) — levels will not be shown")
    rows.sort()
    _STATE_CACHE[key] = rows
    return rows


def _level_cap(game: str) -> int | None:
    """Highest level the campaign's own tables cater for. The game caps wargear
    drops at this level, so it is the practical ceiling for a hero."""
    key = ("levelcap", game)
    if key in _STATE_CACHE:
        return _STATE_CACHE[key]
    cap = None
    try:
        import rbf
        t = game_source(game).attrib_tree("tuning/tuning_info.rbf")
        n = rbf.find_indexed(t, "wargear/wargear_drop_level_absolute_maximum")
        if n is not None and isinstance(n.value, (int, float)):
            cap = int(n.value)
    except Exception:
        cap = None
    _STATE_CACHE[key] = cap
    return cap


def _level_for_xp(xp: float, table: list[float]) -> int | None:
    if not table:
        return None
    lvl = 1
    for req in table:
        if req > 0 and xp >= req:
            lvl += 1
    return lvl


def api_changelog() -> dict:
    """CHANGELOG.md, turned into something the version dialog can render.

    Kept as markdown rather than a data file so it stays readable on its own and
    can be pasted straight onto a release page. Shape:
        ## <version> — <date>
        ### Added / Changed / Fixed / Known
        - one plain-English line
    """
    p = ROOT / "CHANGELOG.md"
    if not p.exists():
        return {"version": VERSION, "releases": []}
    key = ("changelog", p.stat().st_mtime_ns)
    if key in _STATE_CACHE:
        return _STATE_CACHE[key]
    releases, rel, group = [], None, None
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            head = line[3:].strip()
            sep = "—" if "—" in head else (" - " if " - " in head else None)
            ver, when = head.split(sep, 1) if sep else (head, "")
            rel = {"version": ver.strip().lstrip("vV"), "date": when.strip(),
                   "groups": []}
            releases.append(rel)
            group = None
        elif line.startswith("### ") and rel is not None:
            group = {"title": line[4:].strip(), "items": []}
            rel["groups"].append(group)
        elif line.startswith("- ") and group is not None:
            group["items"].append(line[2:].strip())
        elif line.strip() and line.startswith("  ") and group is not None \
                and group["items"]:
            # continuation of a wrapped bullet
            group["items"][-1] += " " + line.strip()
    out = {"version": VERSION, "releases": releases}
    _STATE_CACHE[key] = out
    return out


def api_saves(query: dict) -> dict:
    game = query.get("game") or active_game()
    sdir = saves_dir(game)
    files = []
    if sdir.exists():
        for p in _list_saves(sdir):
            files.append({"name": p.name, "bytes": p.stat().st_size,
                          "modified": time.strftime("%Y-%m-%d %H:%M",
                                                    time.localtime(p.stat().st_mtime))})
    backups = []
    bdir = sdir / "PA_backups"
    if bdir.exists():
        for p in sorted(_list_saves(bdir), reverse=True)[:20]:
            backups.append({"name": p.name, "bytes": p.stat().st_size})
    cdir = steam_cloud_dir(game)
    if cdir:
        for p in sorted(cdir.glob("campaign_*.sav")):
            files.append({"name": p.name, "bytes": p.stat().st_size, "cloud": True,
                          "modified": time.strftime("%Y-%m-%d %H:%M",
                                                    time.localtime(p.stat().st_mtime))})
    out = {"game": game, "dir": str(sdir), "exists": sdir.exists(),
           "cloud_dir": str(cdir) if cdir else None,
           "files": files, "backups": backups}
    name = query.get("file")
    if name:
        import savefile
        import chunkysave
        path = _save_path(game, name)
        if _is_cloud_save(game, path):
            out["chunky"] = chunkysave.summarize_cloud(path)
            return out
        if chunkysave.is_chunky(path):
            out["chunky"] = chunkysave.summarize(path)
            return out
        model = savefile.parse(path)
        d = savefile.describe(model)
        tbl = _level_table(game)
        for s in d["squads"]:
            s["level"] = _level_for_xp(s["xp"], tbl)
        d["max_level"] = _level_cap(game) or ((len(tbl) + 1) if tbl else None)
        d["level_table"] = tbl[:40]
        out["save"] = d
    return out


def action_edit_save(body):
    """Apply hero edits and/or a new inventory to a save. Always backs up."""
    import savefile
    game = body.get("game") or active_game()
    p = _save_path(game, body["file"])
    model = savefile.parse(p)
    n_edits = 0
    for i, sq in enumerate(body.get("squads") or []):
        if sq is None:
            continue
        if "xp" in sq and abs(float(sq["xp"]) - model["squads"][i]["xp"]) > 0.01:
            savefile.set_scalar(model, "xp", i, None, float(sq["xp"])); n_edits += 1
        if "recruited" in sq and bool(sq["recruited"]) != bool(model["squads"][i]["recruited"]):
            savefile.set_scalar(model, "recruited", i, None, sq["recruited"]); n_edits += 1
        if "unspent" in sq and int(sq["unspent"]) != model["squads"][i]["unspent"]:
            savefile.set_scalar(model, "unspent", i, None, int(sq["unspent"])); n_edits += 1
        for a, v in (sq.get("attributes") or {}).items():
            if int(v) != model["squads"][i]["attributes"].get(a):
                savefile.set_scalar(model, "attribute", i, a, int(v)); n_edits += 1
    n_edits += _apply_commander(savefile, model, body)
    n_edits += _apply_campaign(savefile, model, body.get("campaign") or {})
    n_edits += _apply_flags(savefile, model, body.get("flags") or [])
    inv = None
    if body.get("inventory") is not None:
        inv = []
        for sec, given in zip(model["inventory"], body["inventory"]):
            items = [{"present": 1, "quantity": 1, "path": it["path"],
                      "flag": int(it.get("flag", 1))} for it in given["items"]]
            inv.append({"items": items})
            n_edits += abs(len(items) - len(sec["items"]))
    if not n_edits and inv is None:
        return {"ok": True, "changed": 0, "note": "nothing to change"}
    info = savefile.save(model, inventory=inv)
    log(f"[saves] {p.name}: {n_edits} edit(s) written, backup {info['backup']}")
    # The campaign save is named after the commander, so a rename can carry the
    # file with it — only ever to a free name, and only after the write landed.
    if body.get("rename_file") and model.get("commander"):
        new_stem = re.sub(r"[^A-Za-z0-9 '._-]", "", model["commander"]["name"]).strip()
        if new_stem and new_stem.lower() != p.stem.lower():
            target = p.with_name(new_stem + p.suffix)
            if target.exists():
                info["rename_note"] = f"{target.name} already exists — file left as {p.name}"
            else:
                p.rename(target)
                info["file"] = str(target)
                info["renamed_from"] = p.name
                log(f"[saves] {p.name} renamed to {target.name}")
    return {"ok": True, "changed": n_edits, **info}


def _apply_commander(savefile, model, body) -> int:
    name = (body.get("commander") or "").strip()
    cmd = model.get("commander")
    if not name or not cmd or name == cmd["name"]:
        return 0
    savefile.set_commander(model, name)
    return 1


def _apply_flags(savefile, model, given: list) -> int:
    n = 0
    for i, f in enumerate(given):
        if f is None or i >= len(model["flags"]):
            continue
        cur = model["flags"][i]
        val = str(f.get("value", cur["value"]))
        if val != cur["value"]:
            savefile.set_text(model, {"off": cur["off"], "len": cur["len"],
                                      "text": cur["value"]}, val)
            cur["value"] = val
            n += 1
    return n


def _apply_campaign(savefile, model, given: dict) -> int:
    """Campaign-state edits, addressed by position in the model the UI was
    handed — so nothing is matched by name and nothing is guessed at."""
    prog = model.get("progress")
    if not prog or not given:
        return 0
    n = 0

    def num(slot, value):
        nonlocal n
        if value is None:
            return
        if int(value) != slot["value"]:
            savefile.set_number(model, slot, value)
            n += 1

    def text(slot, value):
        nonlocal n
        if not value:
            return
        if str(value) != slot["text"]:
            savefile.set_text(model, slot, value)
            n += 1

    num(prog["day"], given.get("day"))
    text(prog["current_planet"], given.get("planet"))
    for i, k in enumerate(given.get("kinds") or []):
        if k is not None and i < len(prog["kinds"]):
            num(prog["kinds"][i]["count"], k.get("count"))
    for i, r in enumerate(given.get("races") or []):
        if r is not None and i < len(prog["races"]):
            num(prog["races"][i]["count"], r.get("count"))
    for i, m in enumerate(given.get("missions") or []):
        if m is None or i >= len(prog["missions"]):
            continue
        rec = prog["missions"][i]
        for key in ("day", "seconds", "score", "objectives", "objectives_max",
                    "result", "kind"):
            num(rec[key], m.get(key))
    for pi, pl in enumerate(given.get("planets") or []):
        if pl is None or pi >= len(prog["planets"]):
            continue
        zones = prog["planets"][pi]["zones"]
        for zi, z in enumerate(pl.get("zones") or []):
            if z is None or zi >= len(zones):
                continue
            zone = zones[zi]
            for oi, owner in enumerate(z.get("owners") or []):
                if owner is None or oi >= len(zone["owners"]):
                    continue
                text(zone["owners"][oi]["faction"], owner.get("faction"))
                num(zone["owners"][oi]["day"], owner.get("day"))
            if zone["mission"] and z.get("reward"):
                text(zone["mission"]["reward"], z["reward"])
    return n


def action_restore_save(body):
    game = body.get("game") or active_game()
    bdir = saves_dir(game) / "PA_backups"
    name = body["backup"]
    if "/" in name or "\\" in name:
        raise ValueError("bad backup name")
    src = (bdir / name).resolve()
    if src.parent != bdir.resolve() or not src.exists():
        raise ValueError("backup not found")
    target = saves_dir(game) / (name.rsplit("_", 2)[0] + src.suffix)
    shutil.copy2(src, target)
    log(f"[saves] restored {target.name} from {name}")
    return {"ok": True, "restored": str(target)}


# ---------------- sharing: export / import --------------------------------

def build_export_zip(mod_name: str) -> bytes:
    """Zip: config + built mod output + README — ready to share or publish."""
    import zipfile
    if not NAME_RE.match(mod_name):
        raise ValueError("bad mod name")
    cfg_p = next((p for p in CONFIG_DIR.glob("*.json")
                  if json.loads(p.read_text()).get("mod", {}).get("name") == mod_name), None)
    if cfg_p is None:
        raise FileNotFoundError(f"no config for {mod_name}")
    cfg = json.loads(cfg_p.read_text())
    game = cfg.get("game", "dow2cr")
    game_title = {"dow2cr": "Dawn of War II / Chaos Rising (Anniversary Edition)",
                  "retribution": "Dawn of War II - Retribution"}.get(game, game)
    build = BUILD_DIR / mod_name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        stamp = _build_stamp()
        cfg = {**cfg, "builder_version": VERSION, "build": stamp}
        z.writestr(f"{mod_name}/modconfig.json", json.dumps(cfg, indent=1))
        readme = (
            f"{cfg['mod'].get('title', mod_name)}\n"
            f"{'=' * len(cfg['mod'].get('title', mod_name))}\n\n"
            f"{cfg['mod'].get('description', '')}\n\n"
            f"Game: {game_title}\n\n"
            "INSTALL\n"
            f"1. Copy {mod_name}.module and the {mod_name} folder into the game's\n"
            "   install directory (next to DOW2.exe).\n"
            "2. In Steam: right-click the game -> Properties -> Launch Options:\n"
            f"     -modname {mod_name} -dev\n"
            "3. Launch. Remove the launch options to play 100% vanilla again.\n\n"
            "UNINSTALL\n"
            f"Delete {mod_name}.module and the {mod_name} folder. No game files\n"
            "are ever modified.\n\n"
            "FOR MODDERS\n"
            "modconfig.json is the full recipe — import it into the Proelium\n"
            "Artifex DoW2 Mod Builder to inspect or rebuild this mod.\n\n"
            f"Built with the Proelium Artifex DoW2 Mod Builder v{VERSION} (build {stamp}).\n")
        z.writestr(f"{mod_name}/README.txt", readme)
        mod_file = build / f"{mod_name}.module"
        if mod_file.exists():
            z.write(mod_file, f"{mod_name}/{mod_name}.module")
            payload = build / mod_name
            if payload.exists():
                for f in sorted(payload.rglob("*")):
                    if f.is_file():
                        z.write(f, f"{mod_name}/{mod_name}/{f.relative_to(payload)}")
        else:
            z.writestr(f"{mod_name}/NOT_BUILT.txt",
                       "This export contains only the recipe (modconfig.json).\n"
                       "Build the mod in the builder to produce installable files.\n")
    return buf.getvalue()


def action_import_mod(body):
    """Import a shared mod: a modconfig.json or an exported zip (base64)."""
    import base64, zipfile
    fname = (body or {}).get("filename", "")
    raw = base64.b64decode((body or {}).get("content_b64", ""))
    configs = []
    if fname.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            for n in z.namelist():
                if n.endswith("modconfig.json") or (n.endswith(".json") and "/config/" in n):
                    configs.append(z.read(n).decode("utf-8"))
    else:
        configs.append(raw.decode("utf-8"))
    imported = []
    for text in configs:
        cfg = json.loads(text)
        name = cfg.get("mod", {}).get("name", "")
        if not NAME_RE.match(name):
            raise ValueError(f"config has invalid mod name {name!r}")
        out = CONFIG_DIR / f"{name.lower()}.json"
        out.write_text(json.dumps(cfg, indent=1))
        imported.append(name)
    if not imported:
        raise ValueError("no mod configuration found in that file")
    log(f"imported mod config(s): {', '.join(imported)}")
    return {"ok": True, "imported": imported}


_HTTPD = None


def action_shutdown(body):
    """Stop this instance (used when another copy takes over)."""
    if _HTTPD is not None:
        threading.Thread(target=_HTTPD.shutdown, daemon=True).start()
    log("shutdown requested by another copy of the builder")
    return {"ok": True, "stopping": True}


ACTIONS = {
    "extract": action_extract,
    "add_override": action_add_override,
    "build_index": action_build_index,
    "save_mod": action_save_mod,
    "delete_mod": action_delete_mod,
    "build": action_build,
    "install": action_install,
    "uninstall": action_uninstall,
    "settings": action_settings,
    "import_mod": action_import_mod,
    "shutdown": action_shutdown,
    "apply_controls": action_apply_controls,
    "revert_controls": action_revert_controls,
    "loot_preview": action_loot_preview,
    "loot_unused": action_loot_unused,
    "wargear_stats": action_wargear_stats,
    "edit_save": action_edit_save,
    "restore_save": action_restore_save,
}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (ROOT / "ui" / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path == "/api/build_progress":
            try:
                self._send(200, json.dumps(build_progress()).encode())
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode())
        elif self.path == "/api/state":
            try:
                self._send(200, json.dumps(full_state(), default=str).encode())
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode())
        elif self.path.startswith("/api/entities"):
            from urllib.parse import urlparse, parse_qs
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            try:
                self._send(200, json.dumps(api_entities(q), default=str).encode())
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode())
        elif self.path.startswith("/api/icon"):
            from urllib.parse import urlparse, parse_qs
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            name = (q.get("name") or "").strip()
            png = _ICON_CACHE.get(name)
            if png is None and name:
                try:
                    png = game_source("dow2cr").icon_png(name)
                except Exception:
                    png = None
                _ICON_CACHE[name] = png or b""
            png = _ICON_CACHE.get(name) or b""
            if png:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                self.wfile.write(png)
            else:
                self._send(404, b'{"error":"no icon"}')
        elif self.path.startswith("/api/saves"):
            from urllib.parse import urlparse, parse_qs
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            try:
                self._send(200, json.dumps(api_saves(q), default=str).encode())
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode())
        elif self.path.startswith("/api/stat_targets"):
            from urllib.parse import urlparse, parse_qs
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            try:
                self._send(200, json.dumps(api_stat_targets(q), default=str).encode())
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode())
        elif self.path.startswith("/api/entity?"):
            from urllib.parse import urlparse, parse_qs, unquote
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            try:
                self._send(200, json.dumps(api_entity(q), default=str).encode())
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode())
        elif self.path.startswith("/api/export"):
            from urllib.parse import urlparse, parse_qs
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            try:
                data = build_export_zip(q.get("mod", ""))
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="{q.get("mod","mod")}_PA.zip"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode())
        elif self.path.startswith("/api/controls"):
            from urllib.parse import urlparse, parse_qs
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            try:
                self._send(200, json.dumps(api_controls(q), default=str).encode())
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode())
        elif self.path.startswith("/api/unit_catalog"):
            from urllib.parse import urlparse, parse_qs
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            try:
                self._send(200, json.dumps(api_unit_catalog(q), default=str).encode())
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode())
        elif self.path.startswith("/api/logfile"):
            try:
                data = (LOG_FILE.read_bytes() if LOG_FILE.exists()
                        else b"(no log yet)\n")
                stamp = time.strftime("%Y%m%d_%H%M%S")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition",
                                 f'attachment; filename="modbuilder_log_{stamp}.txt"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}).encode())
        elif self.path == "/api/changelog":
            try:
                self._send(200, json.dumps(api_changelog()).encode())
            except Exception as e:
                self._send(400, json.dumps({"error": str(e)}).encode())
        elif self.path.startswith("/api/catalog"):
            from urllib.parse import urlparse, parse_qs
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            g = q.get("game") or active_game()
            files = {"dow2cr": "wargear_catalog.json",
                     "retribution": "wargear_catalog_retribution.json"}
            cat_p = ROOT / "knowledge" / files.get(g, files["dow2cr"])
            cat = json.loads(cat_p.read_text()) if cat_p.exists() else {"items": [], "heroes": []}
            cat["game"] = g
            if g == "dow2cr":            # starting loadouts are a CR-only system
                try:
                    from modules import loadouts as _lo
                    cat["loadout_defaults"] = _lo.read_defaults(game_source("dow2cr"))
                except Exception as e:
                    cat["loadout_defaults"] = {}
                    cat["defaults_error"] = str(e)
            else:
                cat["loadout_defaults"] = {}
            self._send(200, json.dumps(cat, default=str).encode())
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        m = re.match(r"^/api/action/(\w+)$", self.path)
        if not m or m.group(1) not in ACTIONS:
            name = m.group(1) if m else "?"
            self._send(404, json.dumps({
                "error": f"this copy of the builder has no '{name}' action. It is "
                         f"running version {VERSION} (build {BUILD_STAMP}); if you "
                         "have just updated the files, close the Mod Builder "
                         "completely and start it again.",
                "stale": True, "version": VERSION, "build": BUILD_STAMP,
                "known": sorted(ACTIONS)}).encode())
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            result = ACTIONS[m.group(1)](body)
            self._send(200, json.dumps(result, default=str).encode())
        except (Exception, SystemExit) as e:
            log(f"ERROR in {m.group(1)}: {e}")
            traceback.print_exc()
            self._send(400, json.dumps({"error": str(e)}).encode())


def _bootstrap_gamedata():
    """Generate game-derived data from the player's own install. Slow on the
    first run, so it happens in the background — the page is usable straight
    away, and anything that needs a piece of it asks for that piece on demand."""
    try:
        import bootstrap
        for action in bootstrap.ensure_gamedata(log):
            log(f"[bootstrap] {action}")
    except Exception as e:
        log(f"[bootstrap] non-fatal: {e}")


def main(port: int | None = None):
    # detect game paths first (fast); the heavy extraction runs in the
    # background once the server is listening
    try:
        import bootstrap
        bootstrap.ensure_settings()
    except Exception as e:
        log(f"[bootstrap] non-fatal: {e}")
    global _HTTPD
    port = port or settings()["port"]
    httpd = _HTTPD = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    import threading
    threading.Thread(target=_bootstrap_gamedata, daemon=True).start()
    log(f"Proelium Artifex DoW2 Mod Builder v{VERSION} — http://localhost:{port}")
    print(f"\n  Open http://localhost:{port} in your browser. Ctrl+C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
