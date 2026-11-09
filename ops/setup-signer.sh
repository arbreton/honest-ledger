#!/bin/bash
# OPERATOR-RUN, interactive. Moves the v1 hot-wallet key into an encrypted Foundry keystore for the v2 signer.
# The key is read from v1's .env without being printed, checked against the registered wallet, then encrypted
# with a passphrase only you know. The assistant never sees the key or the passphrase.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
export PATH="$HOME/.foundry/bin:$PATH"
V1ENV="$HOME/workspace/crypto-scanner/.env"
[ -f "$V1ENV" ] || { echo "v1 .env not found at $V1ENV"; exit 1; }
[ ! -e data/signer/keystore/farmv2 ] || { echo "keystore already exists (data/signer/keystore/farmv2). Remove it deliberately if you want to redo this."; exit 1; }
KEY="$(grep -E '^HOT_WALLET_KEY=' "$V1ENV" | head -1 | cut -d= -f2- | tr -d "\"' \r")"
[ -n "$KEY" ] || { echo "HOT_WALLET_KEY not found in v1 .env"; exit 1; }
case "$KEY" in 0x*) ;; *) KEY="0x$KEY";; esac
ADDR="$(cast wallet address --private-key "$KEY")"
WALLET="$(PYTHONPATH=. python3 -c "from farmv2 import registry; print(registry.load()['wallet']['address'])")"
if [ "${ADDR,,}" != "${WALLET,,}" ]; then echo "STOP: that key controls $ADDR, not the registered wallet $WALLET"; exit 1; fi
echo "OK: key controls the registered wallet ($WALLET)."
read -r -s -p "Choose a signer passphrase (min 10 chars; you type it at every unlock; there is NO recovery): " P1; echo
read -r -s -p "Again: " P2; echo
[ "$P1" = "$P2" ] && [ "${#P1}" -ge 10 ] || { echo "passphrases differ or too short"; exit 1; }
umask 077; mkdir -p data/signer/keystore data/secrets
cast wallet import farmv2 --keystore-dir data/signer/keystore --private-key "$KEY" --unsafe-password "$P1" >/dev/null
unset KEY P1 P2
head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > data/signer/receipt.key; chmod 600 data/signer/receipt.key
echo; echo "Keystore written (encrypted): data/signer/keystore/farmv2"
echo "BACK IT UP together with your passphrase (offline). If either is lost, this wallet is only recoverable from v1's .env."
echo; echo "=== What the signer will be allowed to sign, ever (everything else is refused) ==="
python3 - <<'PY'
import sys, json; sys.path.insert(0, '.')
from farmv2 import policy
a = policy.build()
print("chain", a["chain_id"], "| only for wallet", a["wallet"]); print("limits:", json.dumps(a["limits"]))
for addr, t in a["targets"].items():
    print(f" - {t['id']} {addr}"); [print("     ", s["sig"]) for s in t["selectors"].values()]
    if t.get("spenders"): print("      approvals only to:", t["spenders"], "max", t.get("max_approve"))
PY
read -r -p "Approve exactly this allowlist? [y/N] " yn
[ "$yn" = "y" ] || { echo "not approved; signer will refuse to start"; exit 1; }
python3 -m farmv2 export-allowlist | awk '{print $NF}' > data/signer/allowlist.sha256
echo "Approved. Next: ops/unlock-signer.sh   (and optionally ops/setup-telegram.sh)"
echo
echo "Recommended once you have confirmed the signer works: remove HOT_WALLET_KEY from v1's .env (v1 is retired)."
