#!/bin/bash
# Non-interactive signer setup, chosen by the operator ("no passphrase, you do it").
# A random passphrase is generated and kept in data/secrets/signer.pass (mode 0600) so the signer can restart unattended.
# TRADE-OFF (stated plainly): encryption then only protects the keystore file if it is copied WITHOUT the pass file.
# Nothing secret is printed. The key is checked against the registered wallet before anything is written.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
export PATH="$HOME/.foundry/bin:$PATH"
V1ENV="$HOME/workspace/crypto-scanner/.env"
[ ! -e data/signer/keystore/farmv2 ] || { echo "keystore already exists; refusing to overwrite"; exit 1; }
KEY="$(grep -E '^HOT_WALLET_KEY=' "$V1ENV" | head -1 | cut -d= -f2- | tr -d "\"' \r")"
[ -n "$KEY" ] || { echo "HOT_WALLET_KEY not found"; exit 1; }
case "$KEY" in 0x*) ;; *) KEY="0x$KEY";; esac
ADDR="$(cast wallet address --private-key "$KEY")"
WALLET="$(PYTHONPATH=. python3 -c "from farmv2 import registry; print(registry.load()['wallet']['address'])")"
[ "${ADDR,,}" = "${WALLET,,}" ] || { echo "STOP: key controls $ADDR, not $WALLET"; exit 1; }
echo "OK: key controls the registered wallet ($WALLET)"
umask 077; mkdir -p data/signer/keystore data/secrets
head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' > data/secrets/signer.pass; chmod 600 data/secrets/signer.pass
cast wallet import farmv2 --keystore-dir data/signer/keystore --private-key "$KEY" --unsafe-password "$(cat data/secrets/signer.pass)" >/dev/null
unset KEY
head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > data/signer/receipt.key; chmod 600 data/signer/receipt.key
GOT="$(cast wallet address --keystore data/signer/keystore/farmv2 --password-file data/secrets/signer.pass)"
[ "${GOT,,}" = "${WALLET,,}" ] || { echo "keystore verification FAILED"; rm -rf data/signer/keystore/farmv2; exit 1; }
echo "keystore verified: decrypts to $GOT"
python3 -m farmv2 export-allowlist | awk '{print $NF}' > data/signer/allowlist.sha256
echo "allowlist approved (sha256 $(cut -c1-12 data/signer/allowlist.sha256)...)"
python3 - <<'PY'
import sys, json; sys.path.insert(0, '.')
from farmv2 import policy
a = policy.build()
print("signer may ONLY sign, on chain", a["chain_id"], "for", a["wallet"][:8] + "...:")
for addr, t in a["targets"].items():
    print(" -", t["id"], ":", ", ".join(s["sig"] for s in t["selectors"].values()), "| approve spenders:", len(t.get("spenders", [])), "| max approve:", t.get("max_approve", "n/a"))
print("limits:", json.dumps(a["limits"]))
PY
