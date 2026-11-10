#!/bin/sh
# Works on Linux and macOS. Sets everything up on first run, then starts the bot.
cd "$(dirname "$0")" || exit 1

for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then
    exec "$py" run.py "$@"
  fi
done

echo "Python 3 was not found."
echo "  macOS: install it from https://www.python.org/downloads/ (or: brew install python-tk)"
echo "  Linux: sudo apt install python3 python3-venv python3-tk"
exit 1
