#!/bin/bash
# Operator-run: installs the 15-minute tick as a systemd USER timer. Reversible: ops/install-timer.sh --remove
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
U="$HOME/.config/systemd/user"
if [ "$1" = "--remove" ]; then
  systemctl --user disable --now farmv2-tick.timer farmv2-poll.timer 2>/dev/null || true
  rm -f "$U"/farmv2-*.service "$U"/farmv2-*.timer
  systemctl --user daemon-reload
  echo "removed"; exit 0
fi
mkdir -p "$U"
cp "$DIR"/systemd/farmv2-*.service "$DIR"/systemd/farmv2-*.timer "$U/"
systemctl --user daemon-reload
systemctl --user enable --now farmv2-tick.timer farmv2-poll.timer
systemctl --user list-timers "farmv2-*" --no-pager
