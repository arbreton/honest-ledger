# Pitch template: "books that reconcile to the chain" (for DAOs, small funds, trading teams, treasuries)

Use after reading the target's public site. Replace the bracketed parts with something TRUE about them. Do not send unless the offer fits what they actually do.

---

**Subject:** Independent on-chain reconciliation for [Project]'s treasury, fixed price, with a trial

Hi [name],

I noticed [one specific, true observation about their treasury or wallets, e.g. they hold funds across N chains / publish a treasury page].

I build tooling that rebuilds a wallet's complete history straight from RPC data and **checks its own books against the chain every few minutes**, then halts and alerts when anything doesn't match (an unexpected transfer, a changed contract, a stale price). It is the same system I run on my own wallet, and it is open source so you can judge it before talking to me: https://github.com/arbreton/honest-ledger

What I would deliver for [Project]:
* A read-only dashboard of balances, positions and P&L that reconciles to the chain, with an audit trail.
* Alerts for transfers that don't match your approved activity, new approvals, and contract-code changes.
* A plain-language report of what changed and why, weekly.

Fixed price: **$[1,500-4,000]** depending on chains and positions, delivered in **[2] weeks**. I'm happy to start with a **free read-only trial on one wallet** so you can see the output first.

I don't need any keys or signing access: read-only addresses only.

Would a short call this week make sense?

[name]

---

## Checklist before sending
- [ ] The observation is true and specific, not flattery
- [ ] I can actually deliver on the chains they use (the code is proven on Base and Ethereum-style RPCs)
- [ ] Price and date are realistic for me, not hopeful
- [ ] No claims beyond `pipeline/profile.json` (no audit history, no clients yet)
- [ ] Record it: `python3 -m farmv2 pipeline lead-add "Name" URL`, then `lead-contacted N` after sending
