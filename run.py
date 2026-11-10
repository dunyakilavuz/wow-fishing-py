#!/usr/bin/env python3
"""Cross-platform launcher: sets everything up on first run, then starts the bot.

    python run.py              install (first time only) and start
    python run.py --install    only install / update the dependencies
    python run.py --reinstall  wipe the private environment and install from scratch

Everything is installed into a private folder (.venv) next to this file, so nothing
is changed on the rest of your system.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQ = ROOT / "requirements.txt"
STAMP = VENV / ".requirements.sha256"
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def say(msg):
    print(f"[setup] {msg}", flush=True)


def die(msg):
    print(f"\nERROR: {msg}\n", file=sys.stderr, flush=True)
    sys.exit(1)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def check_python():
    if sys.version_info < (3, 9):
        die(f"Python 3.9 or newer is required (this is {sys.version.split()[0]}).\n"
            "Download it from https://www.python.org/downloads/")


def create_venv():
    say("creating private environment (.venv)...")
    try:
        venv.EnvBuilder(with_pip=True).create(VENV)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(VENV, ignore_errors=True)
        hint = "\nOn Debian/Ubuntu run: sudo apt install python3-venv" if IS_LINUX else ""
        die(f"could not create the virtual environment: {e}{hint}")


def install_requirements(py: Path):
    if not REQ.exists():
        die("requirements.txt is missing - keep all the files from the zip together.")
    digest = hashlib.sha256(REQ.read_bytes() + sys.version.encode()).hexdigest()
    if STAMP.exists() and STAMP.read_text().strip() == digest:
        return
    say("installing dependencies (this takes a minute the first time)...")
    r = subprocess.run([str(py), "-m", "pip", "install", "--disable-pip-version-check",
                        "-r", str(REQ)])
    if r.returncode != 0:
        die("installing the dependencies failed. Check your internet connection and run again.")
    STAMP.write_text(digest)


def check_tk(py: Path):
    r = subprocess.run([str(py), "-c", "import tkinter; print(tkinter.TkVersion)"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        if IS_LINUX:
            how = "Install it with: sudo apt install python3-tk   (Fedora: sudo dnf install python3-tkinter)"
        elif IS_MAC:
            how = ("Install Python from https://www.python.org/downloads/ "
                   "or run: brew install python-tk")
        else:
            how = ("Re-run the Python installer from https://www.python.org/downloads/ "
                   "and make sure 'tcl/tk and IDLE' is ticked.")
        die(f"Python's tkinter (the window toolkit) is missing.\n{how}")
    try:
        if IS_MAC and float(r.stdout.strip()) < 8.6:
            say("WARNING: this Python ships an old Tk 8.5, so the window may look wrong or glitch.\n"
                "         Install Python from https://www.python.org/downloads/ for best results.")
    except ValueError:
        pass


def main():
    args = set(sys.argv[1:])
    check_python()
    if "--reinstall" in args:
        shutil.rmtree(VENV, ignore_errors=True)
    if not venv_python().exists():
        create_venv()
    py = venv_python()
    install_requirements(py)
    check_tk(py)

    if IS_LINUX and not shutil.which("ydotool"):
        say("WARNING: 'ydotool' was not found. The bot needs it to press keys on Linux\n"
            "         (sudo apt install ydotool, and make sure the ydotoold service is running).")

    if args & {"--install", "--reinstall"}:
        say("All set. Start the bot with run.bat (Windows), run.command (Mac) or run.sh (Linux).")
        return

    say("starting WoW Fishing Bot...")
    os.chdir(ROOT)
    sys.exit(subprocess.call([str(py), str(ROOT / "main.py")]))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
