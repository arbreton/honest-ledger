#!/bin/bash
# OPERATOR-RUN. Unlocks the signer: passphrase goes to a RAM-only file (/dev/shm), checked, and the daemon is started.
# Lock again with ops/lock-signer.sh. After a reboot the signer is locked and v2 is read-only until you run this.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
export PATH="$HOME/.foundry/bin:$PATH"
PW=/dev/shm/farmv2-signer.pw
read -r -s -p "Signer passphrase: " P; echo
umask 077; printf %s "$P" > "$PW"; unset P; chmod 600 "$PW"
WALLET="$(PYTHONPATH=. python3 -c "from farmv2 import registry; print(registry.load()['wallet']['address'])")"
GOT="$(cast wallet address --keystore data/signer/keystore/farmv2 --password-file "$PW" 2>/dev/null || true)"
if [ "${GOT,,}" != "${WALLET,,}" ]; then rm -f "$PW"; echo "wrong passphrase (or wrong keystore)"; exit 1; fi
if ! pgrep -f "python3 -m signer" >/dev/null; then
  nohup env PYTHONPATH="$ROOT" python3 -m signer > data/signer/signer.log 2>&1 &
  sleep 1
fi
python3 -m farmv2 signer-status
echo "Unlocked. The next tick may act within the Risk Gate: auto up to \$5, bigger needs your approval."
