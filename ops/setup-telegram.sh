#!/bin/bash
# OPERATOR-RUN. Create a NEW bot with @BotFather (not Hermes's), message it once, then run this.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
read -r -s -p "Bot token from BotFather: " T; echo
read -r -p "Your numeric Telegram chat id (message @userinfobot): " C
umask 077; mkdir -p data/secrets
python3 -c "import json,sys; json.dump({'token': sys.argv[1], 'chat_id': int(sys.argv[2])}, open('data/secrets/telegram.json','w'))" "$T" "$C"
unset T
python3 -c "import sys; sys.path.insert(0,'.'); from farmv2 import notify; print('sent' if notify.send('INFO','farmv2 alerts connected. Commands: /status /halt /approve <id> <code> /deny <id>') else 'FAILED: check token/chat id')"
