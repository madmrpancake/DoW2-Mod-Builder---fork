"""Proelium Artifex — DoW2 Mod Builder launcher.

Double-click this file (requires Python 3 — see README.md).
Starts the builder and opens it in its own app window (no address bar or
tabs) using Chrome or Edge in app mode; if neither is installed it falls
back to a normal browser tab. To force a plain tab, add
  "window": "tab"
to settings.json ("app" is the default).

Handles the awkward cases so you don't have to:
  * builder already running          -> just opens the existing window
  * port 8420 busy / blocked         -> quietly moves to the next free port
  * anything goes wrong at startup   -> writes workspace/logs/launcher.log
                                        and shows the error in a dialog
Keep this running while you use the builder; close it to stop.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "engine"))

LOG = HERE / "workspace" / "logs" / "launcher.log"
FIRST_PORT = 8420
PORT_TRIES = 20


def note(msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass
    print(msg)


def show_error(title: str, body: str) -> None:
    """Never fail silently: pythonw has no console, so use a dialog."""
    note(f"ERROR: {title}\n{body}")
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, body, title, 0x10)
            return
        except Exception:
            pass
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(title, body)
        root.destroy()
    except Exception:
        pass


def _browser_exe() -> str | None:
    """Full path of Chrome or Edge for app-mode, or None if neither exists.
    Chrome is preferred (it keeps a separate taskbar icon per app window)."""
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LocalAppData", "")
    candidates = [
        Path(pf) / "Google/Chrome/Application/chrome.exe",
        Path(pf86) / "Google/Chrome/Application/chrome.exe",
        Path(local) / "Google/Chrome/Application/chrome.exe" if local else None,
        Path(pf86) / "Microsoft/Edge/Application/msedge.exe",
        Path(pf) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for c in candidates:
        if c and c.is_file():
            return str(c)
    return None


def open_ui(url: str) -> None:
    """Open the builder as its own app-style window (no tabs/address bar).
    Falls back to a normal browser tab if no Chrome/Edge is found, if the
    launch fails, or if settings.json says "window": "tab"."""
    mode = "app"
    try:
        mode = json.loads((HERE / "settings.json").read_text("utf-8")
                          ).get("window", "app")
    except (OSError, ValueError):
        pass
    if mode == "app" and sys.platform == "win32":
        exe = _browser_exe()
        if exe:
            try:
                subprocess.Popen(
                    [exe, f"--app={url}", "--window-size=1360,900"],
                    creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
                    close_fds=True)
                note(f"opened app window via {exe}")
                return
            except OSError as e:
                note(f"app window failed ({e}); falling back to browser tab")
        else:
            note("no Chrome/Edge found for app mode; opening a browser tab")
    webbrowser.open(url)


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) != 0


def running_builder_info(port: int):
    """Folder the builder on this port serves from, or None if not ours."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state",
                                    timeout=3) as r:
            import json
            state = json.loads(r.read().decode("utf-8", "replace"))
        if "schemas" not in state:
            return None
        return (state.get("root") or "(unknown folder)", state.get("build"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def ask_yes_no(title: str, body: str) -> bool:
    """Yes/No dialog; defaults to Yes if no GUI is available."""
    if sys.platform == "win32":
        try:
            import ctypes                      # MB_YESNO | MB_ICONQUESTION
            return ctypes.windll.user32.MessageBoxW(None, body, title, 0x24) == 6
        except Exception:
            pass
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk(); root.withdraw()
        ans = messagebox.askyesno(title, body)
        root.destroy()
        return ans
    except Exception:
        return True


def stop_running_builder(port: int) -> bool:
    """Politely ask the copy on this port to shut down; wait for the port."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/action/shutdown", data=b"{}",
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
    except (urllib.error.URLError, OSError):
        pass                                   # older copy without the endpoint
    for _ in range(40):
        if port_is_free(port):
            return True
        time.sleep(0.25)
    return False


def pick_port() -> tuple[int, str | None]:
    """(port, folder_of_running_builder_or_None)."""
    for port in range(FIRST_PORT, FIRST_PORT + PORT_TRIES):
        if port_is_free(port):
            return port, None
        info = running_builder_info(port)
        if info is not None:
            return port, info
        note(f"port {port} is in use by something else — trying the next one")
    raise RuntimeError(f"No free port found in {FIRST_PORT}-{FIRST_PORT + PORT_TRIES - 1}.")


def open_when_ready(port: int) -> None:
    url = f"http://localhost:{port}"
    for _ in range(60):                      # wait up to ~15s for first response
        if not port_is_free(port):
            break
        time.sleep(0.25)
    time.sleep(0.4)
    open_ui(url)


def run() -> None:
    note(f"launcher starting in {HERE}")
    if not (HERE / "ui" / "index.html").exists():
        show_error("DoW2 Mod Builder",
                   "The builder's files look incomplete — ui\\index.html is "
                   "missing.\n\nExtract the whole ZIP (keeping its folder "
                   "structure) and run this launcher from inside the extracted "
                   f"folder.\n\nLooked in:\n{HERE}")
        return

    port, running_info = pick_port()
    running_from = running_info[0] if isinstance(running_info, tuple) else running_info
    running_build = running_info[1] if isinstance(running_info, tuple) else None
    if running_from is not None:
        same = str(HERE).rstrip("\\/").lower() == str(running_from).rstrip("\\/").lower()
        note(f"a builder is already running on {port} from {running_from}")
        if same:
            # Same folder — but is it running the code that is on disk NOW? After
            # an update the old process keeps the port and keeps serving the old
            # code, which looks exactly like a broken update.
            try:
                sys.path.insert(0, str(HERE / "engine"))
                import buildstamp
                ours = buildstamp.stamp(HERE)
            except Exception:
                ours = None
            if ours and running_build and running_build == ours:
                open_ui(f"http://localhost:{port}")      # genuinely the same build
                return
            if ours is None:
                open_ui(f"http://localhost:{port}")      # can't tell; behave as before
                return
            note(f"running copy is build {running_build or 'older'}, on disk is "
                 f"{ours} — restarting it")
            if not stop_running_builder(port):
                show_error(
                    "DoW2 Mod Builder — update not applied",
                    "The builder already running in the background is from "
                    "BEFORE this update, and it would not shut down.\n\n"
                    "It has no window of its own, so closing the browser tab "
                    "does not stop it.\n\nOpen Task Manager, end "
                    "pythonw.exe (or python.exe), then run this launcher "
                    "again.")
                return
        use_old = ask_yes_no(
            "DoW2 Mod Builder — already running",
            f"A copy of the builder is already running in the background and "
            f"using port {port}.\n\nIt is running from:\n{running_from}\n\n"
            f"This launcher is in:\n{HERE}\n\n"
            "It has no window of its own — it just serves the page in your "
            "browser, so it keeps running after you close the tab.\n\n"
            "YES  — open the copy that's already running\n"
            "NO   — close it and start THIS copy instead")
        if use_old:
            open_ui(f"http://localhost:{port}")
            return
        note("user chose to take over the port")
        if not stop_running_builder(port):
            show_error("DoW2 Mod Builder",
                       f"The other copy did not shut down.\n\nClose it from "
                       "Task Manager (look for pythonw.exe or python.exe) and "
                       "run this launcher again — or just open "
                       f"http://localhost:{port} to use it.")
            return

    import app                                # imported late so errors are caught
    threading.Thread(target=open_when_ready, args=(port,), daemon=True).start()
    note(f"serving on http://localhost:{port}")
    app.main(port)


if __name__ == "__main__":
    try:
        run()
    except Exception:
        tb = traceback.format_exc()
        show_error("DoW2 Mod Builder — startup failed",
                   "The builder could not start.\n\n"
                   f"{tb.strip().splitlines()[-1]}\n\n"
                   f"Full details were written to:\n{LOG}")
