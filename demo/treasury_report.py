"""treasury_report: a READ-ONLY, evidence-first report for any address on Base.
It never needs keys. It rebuilds balances at historical blocks, sums token transfers in/out over the same window, and checks the two agree
exactly (the 'books reconcile to the chain' test). A mismatch is reported loudly, never smoothed over.

    python3 -m demo.treasury_report 0xADDRESS [--days 1] [--token 0xTOKEN ...] [--out report.md]
"""
import argparse, datetime, json, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from farmv2 import registry, prices, timeutil
from farmv2.abi import call_data, words, u, T_TRANSFER, addr_topic, addr_of
from farmv2.keccak import is_valid_address
from farmv2.rpc import Rpc

def token_info(rpc, addr, block):
    code = rpc.call("eth_getCode", [addr, "latest"])
    if code in ("0x", None): raise ValueError(f"{addr} has no contract code on Base")
    def s(sig):
        try: return words(rpc.eth_call(addr, call_data(sig), block))
        except Exception: return None
    dec = s("decimals()"); sym = s("symbol()")
    symbol = bytes.fromhex(sym[-1].rstrip("0") if sym and len(sym) == 1 else "").decode(errors="ignore") if sym and len(sym) == 1 else ""
    if sym and len(sym) >= 3:                                              # dynamic string encoding
        n = u(sym[1]); symbol = bytes.fromhex("".join(sym[2:])[:n * 2]).decode(errors="ignore")
    return {"address": addr, "symbol": symbol or addr[:8], "decimals": u(dec[0]) if dec else 18}

def balance(rpc, who, tok, block):
    return u(words(rpc.eth_call(tok["address"], call_data("balanceOf(address)", who), block))[0])

def flows(rpc, who, tok, b0, b1, chunk=49_000, pace=0.25):
    """All Transfer logs touching `who` in (b0, b1]. Returns (in_sum, out_sum, n, outflows[list], counterparties{addr: signed units})."""
    wt = addr_topic(who); inn = out = n = 0; outs = []; cp = {}
    b = b0 + 1
    while b <= b1:
        e = min(b + chunk - 1, b1)
        for direction, topics in (("in", [T_TRANSFER, None, wt]), ("out", [T_TRANSFER, wt])):
            for lg in rpc.logs(b, e, address=[tok["address"]], topics=topics):
                if len(lg["topics"]) != 3: continue
                amt = u(words(lg["data"])[0]); n += 1
                other = addr_of((lg["topics"][1] if direction == "in" else lg["topics"][2])[2:])
                if direction == "in": inn += amt; cp[other] = cp.get(other, 0) + amt
                else: out += amt; outs.append((amt, other, lg["transactionHash"])); cp[other] = cp.get(other, 0) - amt
            time.sleep(pace)
        b = e + 1
    return inn, out, n, sorted(outs, reverse=True), cp

def build(rpc, who, token_addrs, days=1, log=print):
    head = rpc.block_number() - 3
    b0 = timeutil.block_at_age(rpc, head, int(days * 86400)); t0, t1 = timeutil.ts(rpc, b0), timeutil.ts(rpc, head)
    reg = registry.load(); names = {c["address"].lower(): c["id"] for c in reg["contracts"]}
    toks = [token_info(rpc, a, head) for a in token_addrs]
    px1, px0 = prices.chainlink_eth_usd(rpc, reg, head), prices.chainlink_eth_usd(rpc, reg, b0)
    usd = lambda tok, amt, p: (amt / 10 ** tok["decimals"]) * (p if tok["symbol"].upper() in ("WETH", "ETH") else 1.0 if tok["symbol"].upper() in ("USDC", "USDT", "DAI", "USDBC") else float("nan"))
    rep = {"address": who, "from_block": b0, "to_block": head, "from": datetime.datetime.fromtimestamp(t0, datetime.timezone.utc).isoformat(timespec="minutes"),
           "to": datetime.datetime.fromtimestamp(t1, datetime.timezone.utc).isoformat(timespec="minutes"), "eth_usd_start": px0, "eth_usd_end": px1, "tokens": []}
    e0, e1 = rpc.balance(who, b0), rpc.balance(who, head)
    rep["eth"] = {"start": e0 / 1e18, "end": e1 / 1e18, "delta": (e1 - e0) / 1e18, "note": "Native ETH moves through internal calls and gas, which token logs cannot explain; shown for context, not reconciled."}
    for tok in toks:
        s0, s1 = balance(rpc, who, tok, b0), balance(rpc, who, tok, head)
        log(f"  scanning {tok['symbol']} transfers {b0:,} -> {head:,} ...")
        inn, out, n, outs, cp = flows(rpc, who, tok, b0, head)
        diff = (s1 - s0) - (inn - out)
        top_cp = sorted(cp.items(), key=lambda kv: -abs(kv[1]))[:5]
        sc = 10 ** tok["decimals"]
        rep["tokens"].append({"symbol": tok["symbol"], "address": tok["address"], "start": s0 / sc, "end": s1 / sc, "in": inn / sc, "out": out / sc, "transfers": n,
                              "unexplained": diff / sc, "reconciled": diff == 0, "usd_end": usd(tok, s1, px1), "usd_start": usd(tok, s0, px0),
                              "largest_outflows": [{"amount": a / sc, "to": names.get(o, o), "tx": h[:12] + "…"} for a, o, h in outs[:3]],
                              "top_counterparties": [{"who": names.get(a, a[:10] + "…"), "net": v / sc} for a, v in top_cp]})
    return rep

def to_markdown(r):
    L = [f"# On-chain reconciliation report", "", f"* Address: `{r['address']}` (Base)", f"* Window: {r['from']} → {r['to']} UTC (blocks {r['from_block']:,} → {r['to_block']:,})",
         f"* ETH/USD (Chainlink): {r['eth_usd_start']:,.2f} → {r['eth_usd_end']:,.2f}", "", "## Do the books reconcile?", "",
         "| Token | Start | End | In | Out | Transfers | Unexplained | Result |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    for t in r["tokens"]:
        L.append(f"| {t['symbol']} | {t['start']:,.4f} | {t['end']:,.4f} | {t['in']:,.4f} | {t['out']:,.4f} | {t['transfers']} | {t['unexplained']:+.6f} | {'**RECONCILES**' if t['reconciled'] else '**MISMATCH: investigate**'} |")
    e = r["eth"]; L += ["", f"Native ETH: {e['start']:,.6f} → {e['end']:,.6f} ({e['delta']:+,.6f}). _{e['note']}_", "", "## Largest outflows and counterparties", ""]
    for t in r["tokens"]:
        L.append(f"**{t['symbol']}**: " + ("; ".join(f"{o['amount']:,.4f} to {o['to']} (tx {o['tx']})" for o in t["largest_outflows"]) or "no outflows in window"))
        L.append("  Top counterparties by net flow: " + (", ".join(f"{c['who']} {c['net']:+,.2f}" for c in t["top_counterparties"]) or "none")); L.append("")
    tot = sum(t["usd_end"] for t in r["tokens"] if t["usd_end"] == t["usd_end"]) + e["end"] * r["eth_usd_end"]
    L += [f"**Priced holdings at end of window: ${tot:,.2f}** (tokens without a trusted price feed are shown in units and excluded).", "",
          "_Read-only: no keys, no signing. Every figure is derived from archive RPC state and event logs and can be re-checked by anyone._"]
    return "\n".join(L) + "\n"

def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("address"); ap.add_argument("--days", type=float, default=1.0); ap.add_argument("--token", action="append", default=[]); ap.add_argument("--out")
    a = ap.parse_args(argv)
    if not is_valid_address(a.address): sys.exit("not a valid (checksummed) address")
    reg = registry.load(); toks = [registry.addr(reg, "usdc"), registry.addr(reg, "weth")] + a.token
    for t in a.token:
        if not is_valid_address(t): sys.exit(f"bad token address {t}")
    rep = build(Rpc(), a.address, toks, a.days); md = to_markdown(rep)
    if a.out: pathlib.Path(a.out).write_text(md); pathlib.Path(a.out).with_suffix(".json").write_text(json.dumps(rep, indent=1))
    print(md); return 0 if all(t["reconciled"] for t in rep["tokens"]) else 2

if __name__ == "__main__": sys.exit(main())
