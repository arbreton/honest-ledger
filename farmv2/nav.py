"""NAV from chain state at any block: wallet assets + protocol positions, in USD and ETH (FR-L4).
LP value includes uncollected fees computed from pool fee-growth accounting (v1 hardcoded 0.0001)."""
from . import registry, prices
from .abi import call_data, words, u, s, sint, word
from .keccak import selector

Q128 = 1 << 128
M256 = (1 << 256) - 1

def _bal20(rpc, token, owner, block):
    return u(words(rpc.eth_call(token, call_data("balanceOf(address)", owner), block))[0])

def lp_amounts(liq, sqrtp, tick_lo, tick_hi):
    """Uniswap-v3 style token amounts for liquidity in [tick_lo, tick_hi] at sqrt price sqrtp (X96)."""
    sa = int((1.0001 ** (tick_lo / 2)) * 2**96)
    sb = int((1.0001 ** (tick_hi / 2)) * 2**96)
    if sqrtp <= sa:
        return liq * (sb - sa) * 2**96 // (sa * sb), 0
    if sqrtp >= sb:
        return 0, liq * (sb - sa) // 2**96
    return liq * (sb - sqrtp) * 2**96 // (sqrtp * sb), liq * (sqrtp - sa) // 2**96

def _pool_state(rpc, pool, block):
    w = words(rpc.eth_call(pool, call_data("slot0()"), block))
    return u(w[0]), sint(u(w[1]), 24)

def _tick_outside(rpc, pool, tick, block):
    w = words(rpc.eth_call(pool, call_data("ticks(int24)", tick & ((1 << 256) - 1)), block))
    return u(w[3]), u(w[4])   # feeGrowthOutside0/1 (Slipstream tuple layout)

def uncollected_fees(rpc, pool, pos, tick_now, block):
    g0 = u(words(rpc.eth_call(pool, call_data("feeGrowthGlobal0X128()"), block))[0])
    g1 = u(words(rpc.eth_call(pool, call_data("feeGrowthGlobal1X128()"), block))[0])
    lo0, lo1 = _tick_outside(rpc, pool, pos["tick_lo"], block)
    hi0, hi1 = _tick_outside(rpc, pool, pos["tick_hi"], block)
    below0, below1 = (lo0, lo1) if tick_now >= pos["tick_lo"] else ((g0 - lo0) & M256, (g1 - lo1) & M256)
    above0, above1 = (hi0, hi1) if tick_now < pos["tick_hi"] else ((g0 - hi0) & M256, (g1 - hi1) & M256)
    in0 = (g0 - below0 - above0) & M256
    in1 = (g1 - below1 - above1) & M256
    f0 = pos["liq"] * ((in0 - pos["fg0"]) & M256) // Q128 + pos["owed0"]
    f1 = pos["liq"] * ((in1 - pos["fg1"]) & M256) // Q128 + pos["owed1"]
    return f0, f1

def read_position(rpc, npm, token_id, block):
    w = words(rpc.eth_call(npm, call_data("positions(uint256)", token_id), block))
    return {"tick_lo": sint(u(w[5]), 24), "tick_hi": sint(u(w[6]), 24), "liq": u(w[7]),
            "fg0": u(w[8]), "fg1": u(w[9]), "owed0": u(w[10]), "owed1": u(w[11])}

def lp_nft_ids(L, wallet_acct, npm, block=None):
    """NFT ids held per ledger quantities as of `block` (the chain is checked by the reconciler)."""
    out = []
    bal = L.balances_asof(block, wallet_acct) if block else L.balances(wallet_acct)
    for (acct, asset), q in bal.items():
        if asset.startswith("erc721:" + npm.lower() + "#") and q == 1:
            out.append(int(asset.split("#")[1]))
    return sorted(out)

def nav_at(rpc, L, reg, block, quorum=False):
    """Returns dict with holdings (qty + USD), buckets, totals. Positions are discovered from the ledger."""
    wallet = reg["wallet"]["address"]
    px, src = prices.eth_usd(rpc, reg, block, quorum=quorum)
    A = lambda cid: registry.addr(reg, cid)
    eth = rpc.balance(wallet, block, quorum)
    weth = _bal20(rpc, A("weth"), wallet, block)
    usdc = _bal20(rpc, A("usdc"), wallet, block)
    vault = A("morpho-gauntlet-usdc-prime")
    shares = _bal20(rpc, vault, wallet, block)
    vault_assets = u(words(rpc.eth_call(vault, call_data("convertToAssets(uint256)", shares), block))[0]) if shares else 0
    H = []   # holdings rows
    def add(name, bucket, qty_txt, usd, kind="wallet"):
        H.append({"name": name, "bucket": bucket, "qty": qty_txt, "usd": round(usd, 6), "kind": kind})
    add("ETH", "core", f"{eth / 1e18:.6f}", eth / 1e18 * px)
    add("WETH", "core", f"{weth / 1e18:.6f}", weth / 1e18 * px)
    add("USDC", "core", f"{usdc / 1e6:.4f}", usdc / 1e6)
    if shares:
        add("Morpho Gauntlet USDC Prime", "core", f"{vault_assets / 1e6:.4f} USDC", vault_assets / 1e6, "position")
    lp = []
    npm, pool = A("aero-cl-npm"), A("aero-cl-weth-usdc")
    for tid in lp_nft_ids(L, "wallet:" + wallet.lower(), npm, block):
        pos = read_position(rpc, npm, tid, block)
        sq, tick = _pool_state(rpc, pool, block)
        a0, a1 = lp_amounts(pos["liq"], sq, pos["tick_lo"], pos["tick_hi"]) if pos["liq"] else (0, 0)
        f0, f1 = uncollected_fees(rpc, pool, pos, tick, block) if pos["liq"] else (pos["owed0"], pos["owed1"])
        usd = (a0 + f0) / 1e18 * px + (a1 + f1) / 1e6
        add(f"Aerodrome WETH/USDC LP #{tid}", "farm", f"{a0 / 1e18:.5f} WETH + {a1 / 1e6:.2f} USDC", usd, "position")
        lp.append({"id": tid, "tick": tick, "tick_lo": pos["tick_lo"], "tick_hi": pos["tick_hi"], "liquidity": pos["liq"],
                   "weth": a0 / 1e18, "usdc": a1 / 1e6, "fees_weth": f0 / 1e18, "fees_usdc": f1 / 1e6,
                   "fees_usd": f0 / 1e18 * px + f1 / 1e6, "in_range": pos["tick_lo"] <= tick < pos["tick_hi"],
                   "margin_ticks": min(tick - pos["tick_lo"], pos["tick_hi"] - tick)})
    dm = A("dolomite-margin")
    dwei = 0
    try:
        w = words(rpc.eth_call(dm, call_data("getAccountWei((address,uint256),uint256)", wallet, 0, 0), block))
        dwei = u(w[1]) if u(w[0]) == 1 else 0     # (sign, value); market 0 = WETH on Dolomite
    except Exception:
        pass
    if dwei:
        add("Dolomite WETH supply", "options", f"{dwei / 1e18:.6f} WETH", dwei / 1e18 * px, "position")
    total = sum(h["usd"] for h in H)
    buckets = {}
    for h in H:
        buckets[h["bucket"]] = buckets.get(h["bucket"], 0) + h["usd"]
    return {"block": block, "eth_usd": px, "price_source": src, "nav_usd": round(total, 6), "nav_eth": round(total / px, 8),
            "holdings": H, "buckets": {k: round(v, 6) for k, v in buckets.items()}, "lp": lp}

def snapshot(L, rpc, reg, block, quorum=True):
    n = nav_at(rpc, L, reg, block, quorum)
    import json
    from .ledger import now
    ts = rpc.block(block)["timestamp"]
    from .chain import iso
    L.db.execute("INSERT OR REPLACE INTO nav_snapshots VALUES(?,?,?,?,?,?,?)",
                 (block, iso(int(ts, 16)), str(n["nav_usd"]), str(n["nav_eth"]), str(n["eth_usd"]), json.dumps(n), n["price_source"]))
    L.db.commit()
    return n
