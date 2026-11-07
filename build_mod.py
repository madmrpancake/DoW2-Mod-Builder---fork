#!/usr/bin/env python3
"""Reproducible mod build pipeline (v2 — multi-module, multi-data-space).

    pristine extracted game data + JSON config
        -> per-module apply() transforms (attrib RBFs and/or campaign Lua)
        -> validation
        -> mod output:  <Mod>.module
                        <Mod>/<Mod>_Attrib.sga   (attrib space, drive 'Attrib')
                        <Mod>/<Mod>_Data.sga     (data space,  drive 'DATA')
                        <Mod>/Data/...           (loose copy, mounted first)
                        manifest.json

Module interface (modules/<name>.py):
    SCHEMA: dict     — drives the UI
    apply(extracted_attrib_root, scripts_root, out_data_dir, cfg) -> [changes]
      each change: {"file": game path, "path": value path, "old":…, "new":…}

Usage:  python3 build_mod.py config/loot_test.json
"""
from __future__ import annotations
import hashlib
import importlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT))
import sga_write    # noqa: E402

BUILD = ROOT / "workspace" / "build"

# Modules chain their edits through one overlay, so where two of them touch the
# same field the LAST one wins. Config files list modules in whatever order they
# were written, which would make the same settings build differently — so the
# order is fixed here. loot_quality opens and revives drop pools; loot_mix then
# shapes the final percentages, so it must run after it and have the last word.
MODULE_ORDER = [
    "campaign_loot", "loot_quality", "loot_mix", "mission_rewards",
    "campaign_pacing", "mission_generators", "xp_tuning", "difficulty_tuning",
    "enemy_tuning", "mass_scaling", "last_stand", "unit_stats", "stat_tweaks",
    "ability_tuning", "ability_hotkeys", "accessory_slots", "corruption_tuning",
    "wargear_restrictions", "loadouts", "respec", "generic_overrides",
]


def _ordered(modules: dict) -> list:
    """Config modules in a fixed build order; anything unlisted runs last."""
    rank = {n: i for i, n in enumerate(MODULE_ORDER)}
    return sorted(modules.items(),
                  key=lambda kv: (rank.get(kv[0], len(rank)), kv[0]))
import games as games_reg  # noqa: E402
import source as source_mod  # noqa: E402
import buildstamp as _buildstamp  # noqa: E402


def _deep_merge(dst, src, where, report):
    """Merge src into dst (src wins). Records every overwrite in report."""
    for k, v in src.items():
        if k == "enabled":
            dst[k] = dst.get(k, True) or v
            continue
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v, f"{where}/{k}", report)
        elif isinstance(v, list) and isinstance(dst.get(k), list) and k == "overrides":
            keep = [o for o in dst[k]
                    if not any(o.get("file") == n.get("file") and o.get("path") == n.get("path")
                               for n in v)]
            dropped = len(dst[k]) - len(keep)
            if dropped:
                report.append({"key": f"{where}/{k}", "note": f"{dropped} override(s) superseded"})
            dst[k] = keep + v
        else:
            if k in dst and dst[k] != v:
                report.append({"key": f"{where}/{k}", "losing": dst[k], "winning": v})
            dst[k] = v


def resolve_profile(cfg: dict) -> tuple[dict, list]:
    """If cfg is a profile ({'profile': [mod names]}), merge member configs
    in order (later members win). Returns (effective_cfg, merge_report)."""
    members = cfg.get("profile")
    if not members:
        return cfg, []
    report: list = []
    merged: dict = {}
    for name in members:
        p = ROOT / "config" / f"{name.lower()}.json"
        if not p.exists():
            # fall back: find any config whose mod.name matches (case-insensitive)
            for cand in (ROOT / "config").glob("*.json"):
                try:
                    c = json.loads(cand.read_text())
                except Exception:
                    continue
                if c.get("mod", {}).get("name", "").lower() == name.lower():
                    p = cand
                    break
        if not p.exists():
            raise ValueError(f"profile member config not found: {name}")
        mcfg = json.loads(p.read_text())
        if mcfg.get("profile"):
            raise ValueError(f"profiles cannot nest ({name} is itself a profile)")
        for mod_name, mconf in mcfg.get("modules", {}).items():
            if not mconf.get("enabled", True):
                continue
            _deep_merge(merged.setdefault(mod_name, {}), dict(mconf),
                        f"{name}:{mod_name}", report)
    eff = dict(cfg)
    eff["modules"] = merged
    return eff, report


def _ensure_base_module(gdef: dict, game: str) -> None:
    """The base .module ships as a README placeholder and is copied from the
    player's install by a background thread at launch. A build started before
    that thread finishes — or right after a fresh extract — would otherwise die
    with a raw 'No such file' on gamedata/DOW2.module. Copy it on demand here so
    the build never depends on that thread's timing, with a clear message if the
    game itself can't be located."""
    dst = ROOT / gdef["base_module"]
    if dst.exists():
        return
    # resolve the game path: settings.json -> registry default -> live detection
    gp = ""
    sp = ROOT / "settings.json"
    if sp.exists():
        try:
            gp = (json.loads(sp.read_text()).get("games", {})
                  .get(game, {}).get("game_path") or "")
        except Exception:
            gp = ""
    if not gp or not (Path(gp) / "DOW2.module").exists():
        cand = gdef.get("default_game_path", "")
        if cand and (Path(cand) / "DOW2.module").exists():
            gp = cand
    if not gp or not (Path(gp) / "DOW2.module").exists():
        try:
            import bootstrap
            found = bootstrap.detect_game_path(game)
            if found and (Path(found) / "DOW2.module").exists():
                gp = found
        except Exception:
            pass
    src_mod = Path(gp) / "DOW2.module" if gp else None
    if not src_mod or not src_mod.exists():
        raise ValueError(
            f"can't find the base game module for {game}. Set the game path in "
            "Settings (it must point at the folder containing DOW2.module and "
            "DOW2.exe), then rebuild.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src_mod.read_bytes())
    print(f"[build] copied base module for {game} from {gp}")


def build(config_path: str) -> dict:
    _build_t0 = time.time()
    cfg = json.loads(Path(config_path).read_text())
    cfg, merge_report = resolve_profile(cfg)
    game = cfg.get("game", "dow2cr")
    gdef = games_reg.game_def(game)
    _ensure_base_module(gdef, game)
    mod_name = cfg["mod"]["name"]
    out_dir = BUILD / mod_name
    data_dir = out_dir / mod_name / "Data"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    data_dir.mkdir(parents=True)

    manifest = {
        "mod": cfg["mod"],
        "built": time.strftime("%Y-%m-%d %H:%M:%S"),
        "builder_version": _buildstamp.builder_version(ROOT),
        "build": _buildstamp.stamp(ROOT),
        "config": cfg,
        "framework": "dow2-framework v2",
        "files_changed": [],
        "transformations": [],
        "warnings": [],
    }
    if merge_report:
        manifest["profile_merge"] = merge_report
        for r in merge_report:
            if "winning" in r:
                print(f"[profile] MERGE: {r['key']}: {r['losing']} superseded by {r['winning']}")
            else:
                print(f"[profile] MERGE: {r['key']}: {r['note']}")
    if cfg.get("profile"):
        print(f"[profile] building '{mod_name}' from members: {', '.join(cfg['profile'])}")

    src = source_mod.open_source(game)
    if not hasattr(src, "set_overlay"):
        raise SystemExit("The builder's files were updated while the app was "
                         "running. Close the Mod Builder completely, start it "
                         "again, and rebuild.")
    src.set_overlay(data_dir)   # modules chain edits on shared files safely

    # Two modules can legitimately want the same value; the later one wins by
    # build order. That must never happen silently, so record who claimed what
    # and report every setting that ended up overridden.
    claimed: dict = {}
    overridden: dict = {}

    for module_name, module_cfg in _ordered(cfg.get("modules", {}) or {}):
        if not module_cfg.get("enabled", True):
            continue
        try:
            mod = importlib.import_module(f"modules.{module_name}")
        except ModuleNotFoundError:
            valid = sorted(p.stem for p in
                           (Path(__file__).parent / "modules").glob("*.py")
                           if p.stem != "__init__")
            raise ValueError(f"unknown module '{module_name}' in config — "
                             f"available: {', '.join(valid)}")
        importlib.reload(mod)
        supported = getattr(mod, "GAMES", ["dow2cr"])
        if game not in supported:
            raise ValueError(f"module {module_name} does not support game target "
                             f"'{game}' (supports: {supported})")
        if module_name == "loot_mix" and "loot_quality" in cfg.get("modules", {}):
            module_cfg = dict(module_cfg, _with_loot_quality=True)
        changes = mod.apply(src, data_dir, module_cfg)
        for c in changes:
            key = (str(c.get("file")), str(c.get("path")))
            prev = claimed.get(key)
            if prev and prev != module_name:
                overridden.setdefault((prev, module_name), []).append(key)
            claimed[key] = module_name
        files = sorted({c["file"] for c in changes})
        for f in files:
            manifest["files_changed"].append({"file": f, "module": module_name})
        manifest["transformations"].extend(
            [{"module": module_name, **c} for c in changes])
        schema_opts = getattr(mod, "SCHEMA", {}).get("options", {})
        allowed = (set(schema_opts) | {"enabled"}
                   | set(getattr(mod, "EXTRA_CONFIG_KEYS", ())))
        module_warns = list(getattr(mod, "WARNINGS", []))
        unknown = sorted(k for k in set(module_cfg) - allowed
                         if not k.startswith("_"))   # _keys are injected by build()
        if unknown:
            module_warns.append(
                "ignored unknown option(s) " + ", ".join(unknown)
                + " — valid options: " + ", ".join(sorted(allowed - {"enabled"})))
        if not changes and not module_warns:
            tuned = sorted(k for k, v in module_cfg.items()
                           if k in schema_opts and v != schema_opts[k].get("default"))
            if tuned:
                module_warns.append(
                    "enabled with settings (" + ", ".join(tuned) + ") but produced "
                    "no changes — the values may already match the game's, or the "
                    "config shape is wrong")
        for w in module_warns:
            manifest["warnings"].append({"module": module_name, "warning": w})
            print(f"[{module_name}] WARNING: {w}")
        print(f"[{module_name}] {len(changes)} change(s) across {len(files)} file(s)")
        shown = 0
        for c in changes:
            if shown < 12:
                print(f"    {c['file'].split(chr(92))[-1]} :: {c['path']}: {c['old']} -> {c['new']}")
                shown += 1
        if len(changes) > shown:
            print(f"    ... and {len(changes)-shown} more (see manifest.json)")

    if overridden:
        manifest["overrides"] = []
        for (first, second), keys in sorted(overridden.items()):
            sample = ", ".join(sorted({k[1].split("/")[-1] for k in keys})[:3])
            msg = (f"{second} overrode {len(keys)} setting(s) also changed by "
                   f"{first} — {second}'s values are the ones in the build "
                   f"({sample}{', …' if len(keys) > 3 else ''}). Both modules "
                   "target the same data; this is the build order working, not "
                   "an error.")
            manifest["warnings"].append({"module": second, "warning": msg})
            manifest["overrides"].append({"overridden": first, "winner": second,
                                          "count": len(keys),
                                          "settings": [list(k) for k in keys[:20]]})
            print(f"[build] WARNING: {msg}")

    if not manifest["transformations"]:
        raise SystemExit("No changes produced — nothing to build. Check the config.")
    manifest["game"] = game

    src.set_overlay(None)
    for written in src.flush(data_dir):
        print(f"[{game}] container flushed: {Path(written).name} "
              f"({Path(written).stat().st_size//1024//1024} MB, full container with edits)")

    # ---- package ----------------------------------------------------------
    # attrib space: everything under Data/simulation ; data space: the rest
    # Packed straight from the build output — no staging copy. That halves the
    # disk churn and keeps paths short enough for Windows even when the builder
    # sits several folders deep.
    archives = {}
    n_out = sum(1 for p in data_dir.rglob("*") if p.is_file())
    print(f"packing {n_out} file(s) into the mod archives...")
    _t0 = time.time()
    if len(str(out_dir)) > 150:
        print("NOTE: this builder sits in a very deep folder — if packing "
              "fails, move the builder nearer the top of the drive "
              "(for example D:\\ModBuilder).")
    def _tick(what):
        def report(done, total):
            pct = done * 100 // max(1, total)
            print(f"  {what}: {done}/{total} files ({pct}%), "
                  f"{time.time() - _t0:.0f}s elapsed")
        return report

    if (data_dir / "simulation").exists():
        archives["attrib"] = sga_write.build_sga(
            data_dir, out_dir / mod_name / f"{mod_name}_Attrib.sga",
            archive_name=f"{mod_name}Attributes",
            toc_alias="Attrib", toc_name="Attributes",
            only={"simulation"}, progress=_tick("attributes"))
    if [p for p in data_dir.iterdir() if p.name != "simulation"]:
        archives["data"] = sga_write.build_sga(
            data_dir, out_dir / mod_name / f"{mod_name}_Data.sga",
            archive_name=f"{mod_name}Data",
            toc_alias="DATA", toc_name="All",
            skip={"simulation"}, progress=_tick("campaign data"))
    for a in archives.values():
        print(f"  {Path(a['out']).name}: {a['bytes']//1024} KB")
    print(f"packed in {time.time() - _t0:.1f}s")
    stage = out_dir / "_stage"                  # tidy up older builds' leftovers
    if stage.exists():
        shutil.rmtree(stage, ignore_errors=True)
    manifest["archives"] = archives

    # ---- custom UCS strings (experimental) -------------------------------
    custom = cfg.get("custom_strings") or {}
    if custom:
        import ucs as _ucs
        base_ucs = ROOT / "gamedata" / "DOW2.ucs"
        merged = _ucs.merge(_ucs.load(base_ucs), {int(k): v for k, v in custom.items()})
        out_ucs = out_dir / mod_name / "Locale" / "English" / "DOW2.ucs"
        _ucs.save(merged, out_ucs)
        manifest["custom_strings"] = custom
        manifest["warnings"].append({
            "module": "ucs",
            "warning": "custom strings emitted to Locale/English/DOW2.ucs - EXPERIMENTAL: "
                       "engine locale mounting for mods is unverified in-game"})
        print(f"[ucs] {len(custom)} custom string(s) merged into mod-local DOW2.ucs (experimental)")

    # ---- .module file -------------------------------------------------------
    module_text = generate_module(mod_name, cfg, archives)
    # CRLF + ASCII: the engine's .module parser reads Windows lines only —
    # an LF-only file is seen as one giant "line 0" and the mod is rejected
    # ("Could not parse MOD Definition File" in the engine warnings log)
    (out_dir / f"{mod_name}.module").write_bytes(
        module_text.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii"))

    # hashes for reproducibility audit
    for entry in manifest["files_changed"]:
        rel = entry["file"].replace("\\", "/")
        p = data_dir / rel
        if p.exists():
            entry["sha256_modified"] = hashlib.sha256(p.read_bytes()).hexdigest()

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    # small companion file with just what the dashboard shows, so refreshing
    # the page never has to read a multi-megabyte manifest
    (out_dir / "summary.json").write_text(json.dumps({
        "seconds": round(time.time() - _build_t0, 1),
        "built": manifest["built"],
        "builder_version": manifest["builder_version"],
        "build": manifest["build"],
        "transformations": manifest["transformations"][:40],
        "transformations_total": len(manifest["transformations"]),
        "files_changed": [f["file"] for f in manifest["files_changed"]],
        "warnings": manifest["warnings"]}))
    n_tr = len(manifest["transformations"])
    print(f"\nBuilt: {out_dir}  ({n_tr} transformations, "
          f"{len(manifest['files_changed'])} files, archives: {list(archives)})")
    return manifest


def generate_module(mod_name: str, cfg: dict, archives: dict) -> str:
    gdef = games_reg.game_def(cfg.get("game", "dow2cr"))
    base_module = (ROOT / gdef["base_module"]).read_text()
    out_lines = []
    section = None
    inserted: set[tuple[str, str]] = set()   # (section, kind) pairs we prepended
    for ln in base_module.splitlines():
        s = ln.strip()
        if s.startswith("["):
            section = s
            out_lines.append(ln)
            # archive-only mounts: we never ship a loose Data folder, and a
            # folder.01 line pointing at a missing directory is a boot risk
            if section == "[attrib:common]" and "attrib" in archives:
                out_lines.append(f"archive.01 = {mod_name}\\{mod_name}_Attrib.sga")
                inserted.add((section, "archive"))
            elif section == "[data:common]" and "data" in archives:
                out_lines.append(f"archive.01 = {mod_name}\\{mod_name}_Data.sga")
                inserted.add((section, "archive"))
            continue
        if section in ("[attrib:common]", "[data:common]") and \
                (s.startswith("folder.") or s.startswith("archive.")):
            kind, rest = s.split(".", 1)
            num, val = rest.split("=", 1)
            # only renumber the kinds we actually inserted ahead of; leave
            # untouched kinds (e.g. folder.*) exactly as the vanilla module
            if (section, kind) in inserted:
                out_lines.append(f"{kind}.{int(num)+1:02d} ={val}")
            else:
                out_lines.append(ln)
            continue
        if s.startswith("Name ="):
            out_lines.append(f"Name = {mod_name}")
            continue
        if s.startswith("UIName ="):
            out_lines.append(f"UIName = {cfg['mod'].get('title', mod_name)}")
            continue
        if s.startswith("Description ="):
            out_lines.append(f"Description = {cfg['mod'].get('description', '')}")
            continue
        out_lines.append(ln)
    return "\n".join(out_lines) + "\n"


if __name__ == "__main__":
    build(sys.argv[1])
