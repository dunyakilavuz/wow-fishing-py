# WoW Fishing Bot

## Start it

| System  | Double-click / run        |
|---------|---------------------------|
| Windows | `run.bat`                 |
| macOS   | `run.command`             |
| Linux   | `sh run.sh`               |
| Any     | `python run.py`           |

The first start downloads what it needs into a private `.venv` folder (about a minute, needs internet).
After that it starts straight away. `install.bat` / `install.sh` only do the setup without starting the bot.
`python run.py --reinstall` wipes `.venv` and installs from scratch if something breaks.

You need **Python 3.9+** from <https://www.python.org/downloads/> (Windows: tick "Add python.exe to PATH").

## First-time setup in the app

1. Open WoW in **windowed or borderless** mode, with nothing covering it.
2. Cast a line so the gear icon and bobber are visible, then click **Grab gear** and **Grab bobber** and drag a box around each (Enter to save). Do this on your own screen: sizes differ from computer to computer.
3. Check the **Cast / loot key** matches your in-game keybind (use **Change key** to pick another).
4. Press **Start**, then click into the WoW window.

## Per system

**Windows** - if WoW runs as administrator, run the bot as administrator too. SmartScreen / antivirus may complain about a script that sends key presses; that is expected.

**macOS** - the first time, macOS asks for permissions. Enable your Terminal (or Python) in
System Settings > Privacy & Security under **Screen Recording** and **Accessibility**, then start again.
If `run.command` is blocked ("unidentified developer"), right-click it > Open, or run `chmod +x run.command run.sh` and `xattr -d com.apple.quarantine run.command` in Terminal.
If `<` doesn't work as the key, pick a plain key such as `5` or `F5` with **Change key**.

**Linux** - needs `python3-venv` and `python3-tk` (`sudo apt install python3-venv python3-tk`) and the `ydotool` program with its `ydotoold` service running, so the bot can press keys. Screen capture goes through PipeWire: you will be asked to pick the WoW window. Run `chmod +x run.sh install.sh` if the files aren't executable.

## Files

- `main.py` - the bot
- `run.py` - the setup + launcher used by every script
- `requirements.txt` - Python packages (installed automatically)
- `config.json`, `gear.png`, `bobber.png` - created by the app on your machine

Automating gameplay is against Blizzard's terms of service. Use at your own risk.
