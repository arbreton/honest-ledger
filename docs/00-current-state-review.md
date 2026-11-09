# 00 — Current-State Review of v1 (`crypto-scanner`)

Review date: 2026-11-08. Everything here comes from reading the code and `ledger.db`, plus read-only on-chain calls. Nothing in v1 was changed.

> **Correction notice (2026-11-08, after the v2 ledger was built).** The first version of this review trusted some figures from v1's own logs. Rebuilding the wallet's history from raw chain data showed one claim was wrong (F-17, Morpho gas) and sharpened others (F-16, F-18, NAV). They are marked below. The core conclusions hold: v1's auditor, discovery and outcome tracking did not work, and one unguarded transaction cost more than v1 earned.

## 1. Verdict

**v1 is a well-intentioned monitor that reports activity as if it were progress.** It runs about every 30 minutes and produces a lot of records, but it has not found a new opportunity, its Auditor has never rejected anything, and its money-moving actions happen outside its own safety gates.

| Question | Answer | Evidence |
|---|---|---|
| Does it discover opportunities? | No | `collect()` returns six hardcoded seeds; 9 distinct IDs across 2,589 rows |
| Does the Auditor audit? | No | 2,646 of 2,646 verdicts are `PASS / ok`; the drift check cannot fire |
| Does it measure results? | No | `outcomes` has 0 rows; "realized" is hardcoded to 0 |
| Does it control the money? | No | No repo code signs transactions; live transactions bypassed the allowlist |
| Is it making money? | No | NAV $66.53 vs $74.43 put in. Price moved −$5.74; strategies and gas −$2.17 vs simply holding. See the correction below |
| Is it safe? | Partly | Caps exist on paper; the key is reachable from the agent's account |

## 2. Where the money actually is

Read from Base on 2026-11-08, ETH = $2,126.92 (from the pool's `slot0`).

| Holding | Amount | USD |
|---|---:|---:|
| ETH | 0.013144 | 27.96 |
| WETH | 0.000640 | 1.36 |
| USDC | 2.028 | 2.03 |
| Slipstream LP #8905566 | 0.012279 WETH + 3.87 USDC | 29.99 |
| Dolomite supply (from log, not re-read) | 0.00085 ETH | 1.81 |
| Morpho Gauntlet USDC Prime | 2.0027 USDC | 2.00 |
| **Net asset value** (first reading, 2026-11-08 morning; the v2 ledger later gave $66.53 once uncollected LP fees of $0.58 were included) | | **$65.14** |

- The dashboard says $73.86 and 0.01753 ETH. Both are stale: `update_dashboard.py` never writes `networth` or `balance_eth`.
- 0.03184 ETH, the starting balance, was the only funding event in the rebuilt ledger (v2 backfill confirmed no other deposits or withdrawals). Held, it would be worth **$68.69** at the same moment v1 is worth $66.53, so v1 is **$2.17 behind** buy-and-hold. Of the −$7.91 total loss on $74.43 put in, **−$5.74 was ETH falling** and −$2.17 was strategies plus gas.

## 3. Findings

Severity: **S1** can lose funds or invalidates the system's core claim; **S2** materially wrong or wasteful; **S3** cleanup.

### Truth and measurement

| ID | Sev | Finding | Evidence |
|---|---|---|---|
| F-01 | S1 | Auditor has never disagreed: every verdict is `PASS / ok` | `audits` table |
| F-02 | S1 | Drift check is impossible. `rescore = score - 5`, then it tests `abs(rescore - score) > 15` | `auditor/main.py:25,29` |
| F-03 | S1 | P&L check is hardcoded: `p_and_l_ok` is passed as `True` | `auditor/main.py:28` |
| F-04 | S1 | Discovery is a fixed list. `collect()` never calls `fetch_static()`, and `meta` values such as TVL are typed by hand | `hunter/sources/rss.py` |
| F-05 | S1 | Realized results are fake: every row is written with `realized=0.0, cost=0.55`. That produced 996 `points-farm` rows and $547.80 of phantom cost | `auditor/main.py:98`, `growth_outcomes` |
| F-06 | S1 | The feedback loop is never closed; `outcomes` is empty after 392 runs | `ledger.db` |
| F-07 | S2 | "Deep checks" do no research: they add or subtract points based on the title and URLs, with no network calls | `hunter/deep_checks.py` |
| F-08 | S2 | Strategy labels are wrong: anything without `pool`, `base-quests` or `aero` in its ID is tagged `points-farm`, including Morpho | `auditor/main.py:98` |
| F-09 | S2 | Dashboard state is scraped from log text with regexes, and fields like `tests: "23 passed"` are not refreshed by the script | `scripts/update_dashboard.py` |
| F-10 | S2 | Goal drift: $50k in docs, $100k now; config says start `$300`, real start was about $74 | `config.yaml`, `data.json` |

### Airdrop logic

| ID | Sev | Finding | Evidence |
|---|---|---|---|
| F-11 | S1 | Every EV input is a guess. `payout_est` and `prob` are typed by hand, and evidence links are aggregator or affiliate pages | `hunter/sources/airdrop_programs.py` |
| F-12 | S2 | "Base token positioned" means `nonce > 10`. No such criterion exists; Base has published no token or eligibility rules | `airdrop_check.py:41` |
| F-13 | S2 | The same line ("best EV base-token $43.0, positioned 5/6") is appended every run with no new information | `ideas/01-airdrops/probe-log.md` |
| F-14 | S2 | Even at face value the whole registry sums to **$113 of one-time EV**, or 0.11% of the goal | `ev()` over `PROGRAMS` |
| F-15 | S1 | Config plans `burner_per_airdrop` wallets. Splitting activity across wallets is Sybil behaviour: it breaks program rules and filters now remove it at scale | `config.yaml` |

### Money and execution

| ID | Sev | Finding | Evidence |
|---|---|---|---|
| F-16 | S1 | No gas guard. Tx nonce 16 (`0x130bdc9f…`) paid **8 gwei when base fee was 0.005 gwei (1,600×)**: **$3.73** of gas (at that day's ETH price) to swap about $1. This one transaction is 95% of all gas ever paid and exceeds every dollar v1 earned | Receipt; v2 ledger |
| F-17 | — | **CORRECTED — this finding was wrong.** I originally reported that the Morpho deposit burned ~$2.98 of gas. That figure came from v1's log, which attributed an ETH→USDC *swap* (buying the 2 USDC) to "gas". The rebuilt ledger shows the deposit (nonce 20) cost 0.0000222 ETH (about $0.05), plus $0.03 for a reverted first attempt. Morpho yield has been about 5.5% APY | v2 ledger; on-chain receipts |
| F-18 | S2 | **Corrected:** avoidable gas totals **$3.85**, almost all from the one transaction in F-16. Two reverted transactions cost about $0.06 combined. Without the F-16 mistake, v1 would be about $1.68 *ahead* of holding, because the LP beat holding by $0.13 after fees and Morpho earned a little. The strategies were roughly break-even; the gas blunder and the market made the loss | v2 ledger |
| F-19 | S2 | Harvest can never fire: `_fee = 0.0001` is a constant and on-chain fees are never read | `auditor/main.py:112` |
| F-20 | S2 | Cost model uses constants: `gas = 0.05`, `eth_price = 2338`, benefit `score/100 × 4` | `shared/cost_benefit.py` |
| F-21 | S2 | LP is in a killed gauge (`isAlive=false`, rewards ended about 18 days ago), so it earns trading fees only, with a fixed range and no impermanent-loss accounting | On-chain |
| F-22 | S3 | Latent parser bug: `cast` with a `(bool)` return prints `true`, but the code tests for `0x00…01`. The gauge would report dead even when alive | `auditor/main.py:119` |

### Security

| ID | Sev | Finding | Evidence |
|---|---|---|---|
| F-23 | S1 | Safety gates are not in the money path. The only references to `HOT_WALLET_KEY` are diff blocklists, so live transactions were signed outside the repo | `grep`, `hunter.log` `LIVE-*` lines |
| F-24 | S1 | Morpho, Dolomite and the Slipstream NPM are not allowlisted, yet all received live transactions | `auditor/approvals.py:2` |
| F-25 | S1 | Key isolation is absent. `.env` is readable by the account the LLM agent runs under, and the agent has shell access and standing authority. This contradicts PRD §2.4 | Cron prompt on profile `bot2` |
| F-26 | S2 | Allowlist data is corrupt: AERO (42 hex chars) and veAERO (41) are malformed, and Voter is missing though the cron prompt says it is allowed | `auditor/approvals.py:2` |
| F-27 | S2 | The code-change gate is given the literal string `"L0 param tune"`, not a diff, so it always approves. The cron prompt also authorizes applying L0/L1 tunes | `auditor/main.py:88` |
| F-28 | S2 | The `STOP` kill switch in the checklist does not exist in code; only `FREEZE` does, and only `executor.py` reads it | `grep` |
| F-29 | S2 | Red team is three fixed cases that are known to pass | `auditor/redteam.py` |
| F-30 | S2 | Dashboard data, including wallet and logs, is pushed to Netlify. Access protection was not verified | `update_dashboard.py` |

### Reliability and engineering

| ID | Sev | Finding | Evidence |
|---|---|---|---|
| F-31 | S2 | 98.8 hours lost in three outages over 12 days (76.6h, 13.7h, 8.6h): the host is a laptop under WSL | `runs` timestamps |
| F-32 | S2 | No version control, so "auto-applied" changes cannot be reviewed or reverted | Not a git repo |
| F-33 | S2 | 48 agent runs a day over unchanged data; 15,576 `EXEC` log lines with no decisions behind them. LLM cost is not tracked | `hunter.log` |
| F-34 | S3 | About 1,500 lines of code with a 168-line Auditor procedure; 23 tests, none covering money movement | Source tree |

## 4. What is worth keeping

- **Fork simulation before live.** The Dolomite deposit used an anvil fork and worked first time. v2 makes this mandatory.
- **Multi-RPC balance agreement.** It correctly explained every balance change.
- **Hard-zero rules** for punycode, typosquats and unlimited approvals.
- **Paper-first culture and honest kill rules.** Pausing points farming after 1 win in 16 was the right call.
- **Base as the home chain.** Gas is negligible when priced correctly.
- **Documented lessons** in `resources/what-works.md` and the strategy notes.

## 5. Strategy results so far

| Strategy | Sample | Result | v2 decision |
|---|---|---|---|
| Quest/points grinding | 16 paper bets, 1 win | -$7.60 | Retire unless hourly rate is proven |
| Limitless momentum | 48 paper trades | -$3.84 | Retire |
| New-pool snipe | Backtest: about 0 hits in 14 days | None | Retire |
| NFT flips, MEV, flash loans | Not proven; v1's own notes are skeptical | None | Retire |
| Concentrated LP | 5 logged samples | Unproven net of IL | Keep; must beat holding |
| USDC lending | 1 sample | Works, low yield | Keep as parking |
| Airdrop positioning | 5 of 6 programs touched | No payout yet | Keep, rebuilt on evidence |

Sources for external claims: Base token status ([Zerion](https://zerion.io/blog/base-token-airdrop-how-to-get-it/), [KuCoin](https://www.kucoin.com/news/flash/base-s-token-infrastructure-progress-sparks-speculation-on-network-token)); Sybil filtering ([The Block on Linea](https://www.theblock.co/amp/post/335979/linea-filters-over-half-a-million-sybil-addresses-from-upcoming-token-airdrop)); USDC vault rates, undated snapshots ([Aavescan](https://aavescan.com/rates/morpho-base-gauntlet-usdc)).
