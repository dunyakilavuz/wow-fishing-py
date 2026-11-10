#!/bin/sh
# macOS: double-click this file in Finder to install (first time) and start the bot.
cd "$(dirname "$0")" || exit 1
sh ./run.sh "$@"
status=$?
if [ "$status" -ne 0 ]; then
  echo
  echo "Press any key to close this window."
  read -r _
fi
exit "$status"
