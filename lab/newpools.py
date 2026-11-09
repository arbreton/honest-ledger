"""Micro-cap / new-pool study (research only, nothing is bought): for pools created on the Aerodrome Slipstream factory in the last N days,
simulate 'buy 10 minutes after creation, sell after 1h / 6h / 24h' with realistic costs, and measure how often it is a win, a wipe-out or a rug.
Prices come from archive reads of each pool's slot0 and Chainlink ETH/USD. Honeypots (cannot sell) cannot be detected here, so results are an UPPER bound."""
import json, sys, time, pathlib, statistics
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from farmv2.rpc import Rpc
from farmv2.abi import call_data, words, u, sint
from farmv2.keccak import topic
from farmv2 import registry, prices

OUT = pathlib.Path(__file__).resolve().parent / "results" / "newpools.json"
ROUND_TRIP_COST = 0.03        # pool fees + price impact for a ~$50 round trip (conservative guess for thin new pools)
HORIZONS = {"1h": 3600, "6h": 6 * 3600, "24h": 24 * 3600}
ENTRY_DELAY = 600

def block_map(rpc, head, days):
    t_head = int(rpc.block(head)["timestamp"], 16); pts = [(head, t_head)]; b = head
    while True:
        b -= 50_000
        if b < 1: break
        t = int(rpc.block(b)["timestamp"], 16); pts.append((b, t)); time.sleep(0.03)
        if t_head - t > days * 86400 + 7200: break
    pts.sort(); return pts

def block_for_ts(pts, ts):
    for (b0, t0), (b1, t1) in zip(pts, pts[1:]):
        if t0 <= ts <= t1: return int(b0 + (b1 - b0) * (ts - t0) / max(1, t1 - t0))
    return None

def price_in_quote(rpc, pool, x_is_token0, d0, d1, block):
    sq = u(words(rpc.eth_call(pool, call_data("slot0()"), block))[0])
    if sq == 0: return None
    p = (sq / 2**96) ** 2 * 10 ** (d0 - d1)               # token1 per token0
    return p if x_is_token0 else (1 / p if p > 0 else None)

def run(days=4, max_pools=120, log=print):
    rpc = Rpc(); reg = registry.load(); head = rpc.block_number() - 5
    factory = "0x" + words(rpc.eth_call(registry.addr(reg, "aero-cl-weth-usdc"), call_data("factory()"), head))[0][-40:]   # verified: the factory of OUR pool
    weth, usdc = registry.addr(reg, "weth").lower(), registry.addr(reg, "usdc").lower()
    pts = block_map(rpc, head, days + 2); t_head = pts[-1][1]
    start_b = block_for_ts(pts, t_head - days * 86400) or head - 1_000_000
    sig = topic("PoolCreated(address,address,int24,address)"); logs = []; b = start_b
    while b < head:
        e = min(b + 48_999, head)
        logs += rpc.logs(b, e, address=factory, topics=[sig]); b = e + 1; time.sleep(0.2)
    log(f"{len(logs)} pools created in the last {days} days on factory {factory[:10]}...")
    pools = []
    for lg in logs:
        t0, t1 = "0x" + lg["topics"][1][-40:], "0x" + lg["topics"][2][-40:]
        pool = "0x" + lg["data"][-40:]; blk = int(lg["blockNumber"], 16)
        if weth in (t0, t1) and not ({t0, t1} & {usdc}) or usdc in (t0, t1) and not ({t0, t1} & {weth}):
            pools.append({"pool": pool, "t0": t0, "t1": t1, "block": blk})
    log(f"{len(pools)} are X/WETH or X/USDC pairs (others skipped: no way to price them)")
    step = max(1, len(pools) // max_pools); pools = pools[::step][:max_pools]
    dec_cache = {}
    def dec(a):
        if a not in dec_cache:
            try: dec_cache[a] = u(words(rpc.eth_call(a, call_data("decimals()"), head))[0])
            except Exception: dec_cache[a] = None
        return dec_cache[a]
    res = []
    for i, p in enumerate(pools):
        try:
            quote = weth if weth in (p["t0"], p["t1"]) else usdc
            x_is_t0 = p["t0"] != quote; d0, d1 = dec(p["t0"]), dec(p["t1"])
            if d0 is None or d1 is None: continue
            t_create = next(t for (bb, t) in pts if bb >= p["block"]) if False else None
            tc = int(rpc.block(p["block"])["timestamp"], 16)
            ent_b = block_for_ts(pts, tc + ENTRY_DELAY)
            if ent_b is None or ent_b >= head: continue
            def usd(price_q, blk):
                if price_q is None: return None
                return price_q * (1.0 if quote == usdc else prices.chainlink_eth_usd(rpc, reg, blk))
            liq0 = u(words(rpc.eth_call(p["pool"], call_data("liquidity()"), ent_b))[0])
            p0 = usd(price_in_quote(rpc, p["pool"], x_is_t0, d0, d1, ent_b), ent_b)
            row = {"pool": p["pool"][:10], "liq0": liq0 > 0, "returns": {}}
            if liq0 == 0 or not p0: row["status"] = "no liquidity at entry"; res.append(row); continue
            for h, secs in HORIZONS.items():
                hb = block_for_ts(pts, tc + ENTRY_DELAY + secs)
                if hb is None or hb >= head: continue
                p1 = usd(price_in_quote(rpc, p["pool"], x_is_t0, d0, d1, hb), hb)
                liq1 = u(words(rpc.eth_call(p["pool"], call_data("liquidity()"), hb))[0])
                if p1 is None: continue
                gross = p1 / p0 - 1; rug = liq1 < 0.25 * liq0 or p1 < 0.2 * p0
                row["returns"][h] = {"gross": gross, "net": (1 + gross) * (1 - ROUND_TRIP_COST) - 1, "rug": bool(rug)}
            res.append(row)
        except Exception as e:
            continue
        if i % 20 == 0: log(f"  processed {i}/{len(pools)}")
    summ = {}
    for h in HORIZONS:
        nets = [r["returns"][h]["net"] for r in res if h in r["returns"]]
        if not nets: continue
        rugs = [r["returns"][h]["rug"] for r in res if h in r["returns"]]
        summ[h] = {"n": len(nets), "median_net": statistics.median(nets), "mean_net": sum(nets) / len(nets), "pct_positive": sum(x > 0 for x in nets) / len(nets),
                   "pct_lost_over_50": sum(x < -0.5 for x in nets) / len(nets), "pct_rug_flag": sum(rugs) / len(rugs),
                   "best": max(nets), "worst": min(nets), "p90": sorted(nets)[int(0.9 * (len(nets) - 1))]}
    out = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "days": days, "created": len(logs), "priced_pairs": len(pools), "no_liquidity": sum(1 for r in res if r.get("status")),
           "round_trip_cost": ROUND_TRIP_COST, "summary": summ,
           "caveat": "Upper bound: cannot detect honeypots (tokens you can buy but not sell), and sells of thin pools move the price more than the flat 3% assumed."}
    OUT.parent.mkdir(exist_ok=True); OUT.write_text(json.dumps(out, indent=1)); log("done")
    return out

if __name__ == "__main__":
    run(days=int(sys.argv[1]) if len(sys.argv) > 1 else 4)
