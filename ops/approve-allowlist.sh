#!/bin/bash
# OPERATOR-RUN. Approves the CURRENT registry/policy allowlist for the signer: it shows exactly what changes, then
# (with --yes) records the new approved hash and restarts the signer. This widens what the signer can ever sign, so it is yours to run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
python3 - <<'PY'
import sys, json, hashlib, pathlib; sys.path.insert(0, '.')
from farmv2 import policy
new = policy.build()
cur = json.loads(pathlib.Path('data/signer/allowlist.json').read_text())
print("== signer permissions: CURRENT approved -> PROPOSED ==")
for addr, t in new['targets'].items():
    old = cur['targets'].get(addr, {}).get('selectors', {})
    for sel, s in t['selectors'].items():
        tag = "      " if sel in old else "NEW   "
        rules = ("  [recipient/arg rules: " + ", ".join(f"arg{k}={v}" for k, v in s['args'].items()) + "]") if s['args'] else ""
        print(f" {tag}{t['id']:<28} {s['sig']}{rules}")
    if t.get('spenders'):
        o = cur['targets'].get(addr, {}); chg = " (WIDENED)" if (len(o.get('spenders', [])) != len(t['spenders']) or o.get('max_approve') != t.get('max_approve')) else ""
        print(f"        approvals on {t['id']} only to {len(t['spenders'])} registered spender(s) [was {len(o.get('spenders', []))}], cap {t.get('max_approve')} [was {o.get('max_approve')}]{chg}")
print("limits:", new['limits'], "(was daily_tx", cur['limits'].get('daily_tx'), ")")
print("\nWhat NEW means: the signer will be able to remove/collect/burn/mint YOUR liquidity position and swap WETH<->USDC on one router.")
print("Every call must return value to your wallet; NFT transfers and token transfers stay impossible.")
PY
if [ "${1:-}" != "--yes" ]; then echo; echo "Dry run only. To approve: ops/approve-allowlist.sh --yes"; exit 0; fi
python3 -m farmv2 export-allowlist | awk '{print $NF}' > data/signer/allowlist.sha256; chmod 600 data/signer/allowlist.sha256
pkill -f "python3 -m signer" 2>/dev/null || true; sleep 1; rm -f data/signer/signer.sock
python3 -m farmv2 unlock; python3 -m farmv2 signer-status
echo "approved: sha256 $(cut -c1-12 data/signer/allowlist.sha256)..."
