# ADR-0016: LP management by trigger, with bounded standing approvals

*Architecture Decision Record*

**Status:** Accepted by the operator ("approve all", 2026-11-08), allowlist change **pending the operator's own approval step** · **Decider:** Operator

## Context
The Aerodrome WETH/USDC concentrated LP is the only strategy with meaningful income: about $0.053/day measured from pool fee growth over 7 real days (63% APR gross), about 10x the Morpho vault. Its failure mode is leaving range: it becomes 100% ETH and earns nothing until someone recenters. Without Telegram, a per-action human tap is impractical.

## Decision
- `lp-manage` acts only after the position has been **out of range for 60 minutes**, at most **once per 24 hours**. Recenter (about +/-8% around spot) if the 7-day fee run-rate is at least 15% APR, otherwise exit to the wallet.
- Plans are built from on-chain state, **simulated on a mainnet fork** with a post-check (new range as planned, one NFT, total value within 1.2%), carry an **on-chain slippage floor** on decrease/swap/mint, approve **exact amounts and revoke at the end**, and send every output to the wallet.
- The R-21 human tap is replaced by a **standing approval**: `registry-data/standing_approvals.json`, per action, size-capped ($45), **expiring (2026-12-08)**, and only usable when no BLOCK rule fails. Each use is recorded in `decisions`.
- "Internal" rebalances (all recipients = wallet) get their own per-tx cap (min $60, 95% NAV) and are exempt from the daily outflow cap; external moves keep the tight cap.
- The signer allowlist gains: NPM `decreaseLiquidity/collect/burn/mint` and one SwapRouter `exactInputSingle`, with recipient rules and wider (still exact, capped) approvals. **Widening the allowlist is an operator-only act** (`ops/approve-allowlist.sh --yes`); until then the strategy refuses to try (`executor.allowlist_current()`).
- The SwapRouter address was **discovered on-chain** (top swap sender on our pool; `factory()` equals the pool's factory; correct WETH9). An address recalled from memory was rejected because its factory differed.

## Consequences
- The LP is protected from sitting idle out of range, at a cost of about $0.05-0.10 per recenter against about $0.05/day of fees at stake.
- A bug or a manipulated price during a recenter can cost up to the slippage floors (about 1.2% of $30) and cannot send value anywhere except the wallet.
- A worse-than-expected market can make recentering realise losses relative to holding; the rule uses the last 7 days of fees and is reviewed weekly.

## Alternatives rejected
Telegram approval for every action (not configured); acting immediately on leaving range (thrashes at the edge); a wider static range (lower fee income, still needs a rule when it breaks); doing nothing (idle days cost income).
