# honest-ledger

**Self-custody tooling for AI agents: rules enforced outside the model, and books that reconcile to the chain.**

Started as an experiment: give an AI agent about $66 on Base and see whether it can grow it. The money lesson is humbling
(790 strategies tested, none survived honest testing). The engineering is the reusable part: an agent that can research but
cannot sign, a ledger that checks itself against the blockchain, and a lab that tells you when you are fooling yourself.
Read the story: [`content/i-gave-an-ai-66-dollars.md`](content/i-gave-an-ai-66-dollars.md).

> **Experimental software that can move real funds. Not financial advice. Use at your own risk, start read-only, and read the code before trusting it.**

## What is in here
| Piece | What it does |
|---|---|
| **Ledger** (`farmv2/ledger.py`, `chain.py`, `reconcile.py`) | Append-only, hash-chained double-entry books rebuilt from raw RPC; compared to the chain to the wei every cycle; any mismatch halts everything |
| **Risk Gate** (`farmv2/rules.py`) | 20+ pure-function rules: allowlisted contracts and selectors, pinned code hashes, gas caps relative to the real base fee, exact approvals, payback test, daily caps |
| **Signer** (`signer/`) | Separate process, imports nothing from the rest; verifies a single-use signed receipt, re-checks its own allowlist and recipient rules decoded from calldata, signs with Foundry `cast` from an encrypted keystore |
| **Fork simulation** (`farmv2/sim.py`) | Every plan runs on an anvil fork of mainnet first; balance changes and leftover allowances must match the plan |
| **Independent auditor** (`auditor/`) | Own code, own RPC path; can halt, never approve; runs 18 adversarial canaries through the real gate daily |
| **Research lab** (`lab/`) | Isolated venv; TA + walk-forward ML + perp/liquidation backtester; deflated Sharpe, reality check, parameter-plateau test; pre-registered forward paper trading |
| **Opportunity pipeline** (`pipeline/`) | Scans public bounty/grant listings, ranks by expected $/hour, drafts reviewable packets. It never submits or contacts anyone |
| **Docs** (`docs/`) | PRD, SRS, NFR, architecture, HLD/LLD, TDD, RFC, SLOs, 16 decision records, a build log with every mistake found |

## Quick start (read-only)
```bash
git clone https://github.com/arbreton/honest-ledger && cd honest-ledger
python3 -m unittest discover -s tests          # offline tests; FARMV2_LIVE=1 adds mainnet-fork integration (needs network + Foundry's anvil)
cp registry-data/local.example.json registry-data/local.json    # git-ignored: put YOUR wallet address here
python3 -m farmv2 tick                         # index, reconcile, value, audit, render ./site  (read-only: it cannot sign)
python3 -m farmv2 status
```
Signing is opt-in and off by default. To enable it you create an encrypted keystore with `ops/setup-signer.sh` and review the allowlist it prints
(`ops/approve-allowlist.sh`). Read `docs/04-ADD.md`, `ops/HARDENING.md` and the threat model first.

## Honest limits
* One chain (Base) and one wallet; unknown tokens arriving in the wallet are not detected on a free RPC tier.
* The signer shares an OS user with the rest unless you follow `ops/HARDENING.md`.
* The strategies are research, not recommendations: the lab found no edge, and says so (`docs/11-build-log.md`).

## License
MIT, see `LICENSE`.
