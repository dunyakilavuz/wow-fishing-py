#!/bin/sh
# Works on Linux and macOS. Installs everything without starting the bot.
cd "$(dirname "$0")" || exit 1
exec sh ./run.sh --install
