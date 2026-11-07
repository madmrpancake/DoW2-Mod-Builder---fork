"""DoW2 key binding file support (keydefaults.lua).

Mechanism (verified against the game + community guides):
  The game regenerates Settings\\_keydefaults.lua (defaults, with underscore)
  every launch. A file named keydefaults.lua (no underscore) in the same
  Settings folder OVERRIDES the defaults and survives launches. Revert =
  remove/rename that file. There is no in-game remapping UI in any DoW2.
  Settings folder: Documents\\My Games\\<game>\\Settings
  Applies to DoW2, Chaos Rising and Retribution alike.

This module parses the defaults file, applies a {command: combo} override
map by rewriting just those lines (comments and layout preserved), and
validates combos / reports conflicts.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# group 6 keeps any trailing "-- comment" so rewrites preserve it. Without it
# every commented binding line — the whole single-player ability block — was
# invisible to the parser, which is how taunt/battle-cry stayed stuck on W.
_BIND_RE = re.compile(r'^(\s*)([a-zA-Z_][\w]*)(\s*=\s*)"([^"]*)"(\s*,?\s*)((?:--.*)?)$')

VALID_KEYS = {
    *"abcdefghijklmnopqrstuvwxyz".upper(), *"0123456789",
    "Backspace", "Tab", "Enter", "Escape", "Space", "Apostrophe", "Comma",
    "Minus", "Period", "Slash", "Semicolon", "Equal", "LBracket", "Backslash",
    "RBracket", "Grave", "Up", "Down", "Left", "Right", "Control", "Shift",
    "Alt", "CapsLock", "NumLock", "ScrollLock", "Insert", "Delete", "Home",
    "End", "PageUp", "PageDown", "PrintScreen", "Pause",
    *(f"F{i}" for i in range(1, 13)),
    "MouseLeft", "MouseRight", "MouseMiddle", "MouseTop", "MouseBottom",
    "ScreenLeft", "ScreenRight", "ScreenTop", "ScreenBottom",
    *(f"Numpad{i}" for i in range(10)),
    "NumpadMultiply", "NumpadPlus", "NumpadSeparator", "NumpadMinus",
    "NumpadPeriod", "NumpadSlash",
}
MODIFIERS = ("Control", "Shift", "Alt")


@dataclass
class Bind:
    name: str
    combo: str
    section: str
    line: int


def validate_combo(combo: str) -> str | None:
    """Return an error string, or None if the combo is valid."""
    if combo == "":
        return None                      # empty = unbind is allowed
    parts = combo.split("+")
    for p in parts[:-1]:
        if p not in MODIFIERS:
            return f"'{p}' is not a modifier (use Control/Shift/Alt)"
    last = parts[-1]
    if last not in VALID_KEYS:
        return f"'{last}' is not a valid key name"
    return None


def parse(text: str) -> list[Bind]:
    """All bindings in file order, tagged with the comment section above them."""
    out: list[Bind] = []
    section = ""
    for i, line in enumerate(text.splitlines()):
        s = line.strip()
        if s.startswith("--") and len(s.strip("- \t")) > 3 and "=" not in s:
            title = s.strip("- \t")
            if not title.lower().startswith(("note", "checked", "valid", "bindings use",
                                             "modify", "this is", "the file", "to change",
                                             "if you wish", "will be overwritten", "(c)")):
                section = title
            continue
        m = _BIND_RE.match(line)
        if m and not s.startswith("--"):
            out.append(Bind(m.group(2), m.group(4), section, i))
    return out


def conflicts(binds: list[Bind], remaps: dict[str, str]) -> list[dict]:
    """Same-combo collisions after applying remaps, judged PER SECTION —
    bindings are contextual (unit selected / screen open), and vanilla itself
    shares letters heavily across sections (bare B has 54 users). A clash only
    matters between commands that can be live at the same time, which the
    section grouping approximates. Identity letter binds (q = "Q") are the
    game's grid/typing table and are ignored."""
    by_key: dict[tuple, list[str]] = {}
    seen = set()
    for b in binds:
        combo = remaps.get(b.name, b.combo)
        seen.add(b.name)
        if not combo:
            continue
        if len(b.name) == 1 and b.name.upper() == combo:
            continue                     # identity letter table
        by_key.setdefault((b.section, combo), []).append(b.name)
    out = []
    for (section, combo), names in sorted(by_key.items()):
        names = sorted(set(names))
        if len(names) > 1 and any(n in remaps for n in names):
            out.append({"combo": combo, "section": section, "commands": names})
    return out


def apply_overrides(text: str, remaps: dict[str, str],
                    missing_ok: bool = False) -> tuple[str, list[str]]:
    """Rewrite binding lines named in remaps. Returns (new_text, applied).
    missing_ok skips names absent from this defaults file instead of failing —
    needed when a preset built against one game is applied to the other, whose
    defaults list a different set of commands."""
    for name, combo in remaps.items():
        err = validate_combo(combo)
        if err:
            raise ValueError(f"{name}: {err}")
    applied = []
    lines = text.splitlines(keepends=False)
    for i, line in enumerate(lines):
        m = _BIND_RE.match(line)
        if m and m.group(2) in remaps and not line.strip().startswith("--"):
            new = remaps[m.group(2)]
            lines[i] = (f'{m.group(1)}{m.group(2)}{m.group(3)}"{new}"'
                        f'{m.group(5)}{m.group(6)}')
            applied.append(m.group(2))
    missing = set(remaps) - set(applied)
    if missing and not missing_ok:
        raise ValueError(f"commands not present in defaults file: {sorted(missing)}")
    header = ("-- CUSTOM KEY BINDINGS - generated by the DoW2 Mod Builder\n"
              "-- Changed: " + ", ".join(sorted(applied)) + "\n"
              "-- Delete this file (keydefaults.lua) to restore defaults.\n")
    return header + "\n".join(lines) + "\n", applied


# Ready-made presets ------------------------------------------------------
#
# The WASD preset is DYNAMIC: the hand-picked core below is fixed, and every
# other binding sitting on bare W/A/S/D in the ACTIVE game's defaults file is
# relocated at request time by expand_wasd(). Baking a full list from one
# game's file cannot work — Retribution's defaults carry ~161 xp2-only
# binding names the DoW2/CR file has never heard of.

_WASD_CORE = {
    # camera
    "camera_up": "W", "camera_down": "S",
    "camera_left": "A", "camera_right": "D",
    # displaced global commands
    "attack": "Q", "halt": "J",
    # hand-picked homes for the most-used displaced keys
    "sm_assault_marine": "K",          # was A
    "sm_tactical_marine": "M",         # was S
    "sm_dreadnought": "I",             # was D
    "csm_dreadnought_dual_claw": "U",  # was W (K clashes with mark_of_khorne)
    "tyr_slow_addon": "M",             # was S (tyranid context)
    "ui_arrow": "Control+Alt+A",       # was A
    "jumbo_cursor": "Control+Alt+W",   # was W
}
_WASD_PREFS = ["Z", "X", "U", "N", "V", "L", "Y", "O", "K", "I", "J", "M", "P"]
_CAMERA = {"camera_up", "camera_down", "camera_left", "camera_right"}


def expand_wasd(binds: list[Bind]) -> dict[str, str]:
    """Full WASD remap set for one game's parsed defaults: the core above
    (names present in this file only) plus a relocation for EVERY other
    binding on bare W/A/S/D, each moved to the first preference letter free
    in its own section. Deterministic; verified on DoW2/CR to leave zero
    bare-WASD bindings and zero same-section clashes."""
    names = {b.name for b in binds}
    remaps = {k: v for k, v in _WASD_CORE.items() if k in names}
    occupancy: dict[str, set] = {}
    for b in binds:
        if len(b.name) == 1:
            continue
        combo = remaps.get(b.name, b.combo or "").upper()
        if len(combo) == 1:
            occupancy.setdefault(b.section, set()).add(combo)
    for b in binds:
        if len(b.name) == 1 or b.name in remaps or b.name in _CAMERA:
            continue
        combo = (b.combo or "").upper()
        if combo not in ("W", "A", "S", "D"):
            continue
        occ = occupancy.setdefault(b.section, set())
        for target in _WASD_PREFS:
            if target not in occ:
                remaps[b.name] = target
                occ.discard(combo)
                occ.add(target)
                break
        # every preference taken (never seen in practice): leave the binding
        # alone rather than create a clash — conflicts() will surface it
    return remaps


PRESETS = {
    "wasd_camera": {
        "title": "WASD camera",
        "description": "Camera on W/A/S/D with every displaced binding "
                       "relocated — computed from THIS game's own bindings "
                       "file, so campaign hero abilities (Taunt, Battle Cry, "
                       "Suppressive Fire, Sprint...) and Retribution's xp2 "
                       "keys are all covered. Each key moves to a letter "
                       "free in its own context.",
        "dynamic": "wasd",       # remaps are computed per game by expand_wasd
        "remaps": dict(_WASD_CORE),
    },
}
