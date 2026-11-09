"""Indexer: rebuilds the wallet's full history from raw chain data (no third-party indexer, FR-L2).
Finds each tx by binary-searching the account nonce over archive state, then reads block + receipt."""
import json, datetime
from . import prices
from .abi import T_TRANSFER, T_WETH_DEPOSIT, T_WETH_WITHDRAWAL, addr_topic, addr_of, u, words
from . import registry

ETH = "ETH"
def erc20(a): return "erc20:" + a.lower()
def erc721(a, i): return f"erc721:{a.lower()}#{i}"

def iso(ts: int) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat(timespec="seconds")

def find_nonce_block(rpc, wallet, n, lo, hi):
    """Smallest block b in [lo,hi] with nonce(wallet,b) > n, i.e. the block that included tx #n."""
    while lo < hi:
        mid = (lo + hi) // 2
        if rpc.nonce(wallet, mid) > n:
            hi = mid
        else:
            lo = mid + 1
    return lo

def _tx_events(rpc, wallet, receipt):
    """Decode token movements touching the wallet from receipt logs."""
    w = wallet.lower()
    moves = []
    for lg in receipt["logs"]:
        t = lg["topics"]
        if not t:
            continue
        a = lg["address"].lower()
        if t[0] == T_TRANSFER and len(t) == 3:
            frm, to = addr_of(t[1][2:]), addr_of(t[2][2:])
            if w in (frm, to):
                amt = u(words(lg["data"])[0])
                moves.append({"asset": erc20(a), "amount": amt if to == w else -amt, "cp": frm if to == w else to})
        elif t[0] == T_TRANSFER and len(t) == 4:
            frm, to = addr_of(t[1][2:]), addr_of(t[2][2:])
            if w in (frm, to):
                tid = u(t[3][2:])
                moves.append({"asset": erc721(a, tid), "amount": 1 if to == w else -1, "cp": frm if to == w else to})
        elif t[0] == T_WETH_DEPOSIT and addr_of(t[1][2:]) == w:
            moves.append({"asset": erc20(a), "amount": u(words(lg["data"])[0]), "cp": "wrap"})
        elif t[0] == T_WETH_WITHDRAWAL and addr_of(t[1][2:]) == w:
            moves.append({"asset": erc20(a), "amount": -u(words(lg["data"])[0]), "cp": "unwrap"})
    return moves

def fetch_tx(rpc, wallet, n, block):
    blk = rpc.block(block, True)
    tx = next((t for t in blk["transactions"] if t["from"].lower() == wallet.lower() and int(t["nonce"], 16) == n), None)
    if tx is None:
        raise RuntimeError(f"tx nonce {n} not found in block {block}")
    rc = rpc.receipt(tx["hash"])
    gas_used = int(rc["gasUsed"], 16)
    egp = int(rc["effectiveGasPrice"], 16)
    l1 = int(rc.get("l1Fee", "0x0"), 16)
    return {
        "nonce": n, "tx_hash": tx["hash"], "block": block, "ts": int(blk["timestamp"], 16),
        "to": tx.get("to"), "value_wei": int(tx["value"], 16), "selector": tx["input"][:10],
        "status": int(rc["status"], 16), "gas_used": gas_used, "eff_gas_price": egp, "l1_fee": l1,
        "fee_wei": gas_used * egp + l1, "base_fee": int(blk.get("baseFeePerGas", "0x0"), 16),
        "n_wallet_txs_in_block": sum(1 for t in blk["transactions"] if t["from"].lower() == wallet.lower()),
        "moves": _tx_events(rpc, wallet, rc),
    }

def sync_wallet_txs(L, rpc, reg, head=None):
    """Index wallet-sent transactions into events + journals. Idempotent; returns number of new txs."""
    wallet = reg["wallet"]["address"]
    head = head or rpc.block_number()
    total = rpc.nonce(wallet, head, quorum=True)
    known = {json.loads(e["payload"])["nonce"] for e in L.events("ChainTx")}
    if len(known) >= total:
        return 0
    lo = max((e["block_number"] for e in L.events("ChainTx")), default=0)
    new = 0
    prev_post = None
    for n in range(total):
        if n in known:
            continue
        b = find_nonce_block(rpc, wallet, n, lo, head)
        tx = fetch_tx(rpc, wallet, n, b)
        tx["bal_before"] = rpc.balance(wallet, b - 1)
        tx["bal_after"] = rpc.balance(wallet, b)
        tx["eth_usd"], tx["price_source"] = prices.eth_usd(rpc, reg, b)
        seq = L.append(f"tx:{tx['tx_hash']}", "ChainTx", tx, iso(tx["ts"]), block_number=b, tx_hash=tx["tx_hash"])
        lo = b
        new += 1
    rebuild_journals(L)
    return new

def _label(reg, address):
    for c in reg["contracts"]:
        if c["address"].lower() == address.lower():
            return c["id"]
    return address.lower()

def rebuild_journals(L):
    """Derive double-entry postings from events (idempotent). Opening/external inflows are inferred from balance gaps."""
    from . import registry as R
    reg = R.load()
    wallet = reg["wallet"]["address"]
    wa = "wallet:" + wallet.lower()
    txs = sorted((json.loads(e["payload"]) | {"_seq": e["seq"]} for e in L.events("ChainTx")), key=lambda t: (t["block"], t["nonce"]))
    prev_after, prev_block = 0, None
    for t in txs:
        # External ETH inflow between the previous tx's block and this one (or initial funding).
        gap = t["bal_before"] - prev_after if (prev_block is None or t["block"] != prev_block) else 0
        if gap != 0:
            eid = f"extin:eth:{t['block']}"
            L.append(eid, "ExternalIn", {"asset": ETH, "amount": gap, "block": t["block"] - 1, "eth_usd": t["eth_usd"],
                                         "kind": "funding" if prev_block is None else "inflow", "needs_declaration": True},
                     iso(t["ts"]), block_number=t["block"] - 1)
        prev_after, prev_block = t["bal_after"], t["block"]
        eth_delta = t["bal_after"] - t["bal_before"]
        if t["n_wallet_txs_in_block"] > 1:
            pass  # several wallet txs in one block: delta attributed to the last; see below
        usd = t["eth_usd"]
        fee = t["fee_wei"]
        posts = [(wa, "asset", ETH, eth_delta, f"{eth_delta / 1e18 * usd:.8f}"),
                 ("expense:gas", "expense", ETH, fee, f"{fee / 1e18 * usd:.8f}"),
                 ("cp:eth", "equity", ETH, -(eth_delta + fee), "0")]
        for m in t["moves"]:
            posts.append((wa, "asset", m["asset"], m["amount"], "0"))
            posts.append((f"cp:{_label(reg, m['cp'])}" if m["cp"] in ("wrap", "unwrap") or m["cp"].startswith("0x") else f"cp:{m['cp']}",
                          "equity", m["asset"], -m["amount"], "0"))
        L.post(f"j:tx:{t['tx_hash']}", t["_seq"], posts, memo=f"nonce {t['nonce']} sel {t['selector']}")
    for e in L.events("ExternalIn"):
        p = json.loads(e["payload"])
        L.post(f"j:{e['event_id']}", e["seq"], [(wa, "asset", p["asset"], p["amount"], f"{p['amount'] / 1e18 * p['eth_usd']:.8f}"),
                                                ("equity:contributions", "equity", p["asset"], -p["amount"], "0")], memo=p["kind"])
    for e in L.events("ExternalToken"):
        p = json.loads(e["payload"])
        L.post(f"j:{e['event_id']}", e["seq"], [(wa, "asset", p["asset"], p["amount"], "0"),
                                                ("equity:external", "equity", p["asset"], -p["amount"], "0")], memo=p["kind"])

def sync_tail_eth(L, rpc, reg, head):
    """ETH that arrived after the last indexed tx is recorded as an inflow needing declaration.
    ETH that LEFT without an indexed tx cannot be explained: returns it so the caller halts (unattributed outflow)."""
    wallet = reg["wallet"]["address"]
    chain_eth = rpc.balance(wallet, head, quorum=True)
    led_eth = L.balances("wallet:").get(("wallet:" + wallet.lower(), ETH), 0)
    gap = chain_eth - led_eth
    if gap > 0:
        px, _ = prices.eth_usd(rpc, reg, head)
        ts = int(rpc.block(head)["timestamp"], 16)
        L.append(f"extin:eth:{head}", "ExternalIn", {"asset": ETH, "amount": gap, "block": head, "eth_usd": px, "kind": "inflow",
                                                      "needs_declaration": True}, iso(ts), block_number=head)
        rebuild_journals(L)
        return gap, 0
    return 0, -gap

def tracked_tokens(L, reg):
    """Token contracts the free-tier RPC lets us scan (it requires an address filter). Registry tokens + anything the ledger touched."""
    toks = {c["address"].lower() for c in reg["contracts"] if c["role"] in ("token", "vault", "lp-nft")}
    for (_, asset), _q in L.balances("wallet:").items():
        if asset.startswith("erc20:"):
            toks.add(asset.split(":")[1])
        elif asset.startswith("erc721:"):
            toks.add(asset.split(":")[1].split("#")[0])
    return sorted(toks)

def scan_external_tokens(L, rpc, reg, head, start_block=None, chunk=49_000, pace=0.25):
    """Token transfers of tracked tokens touching the wallet that were NOT in a wallet-sent tx (airdrops, rewards, deposits... or drains).
    Outgoing ones are security signals. Idempotent per (tx, log index). KNOWN LIMIT: unknown tokens are not seen on free-tier RPC."""
    import time
    wallet = reg["wallet"]["address"]
    own = {json.loads(e["payload"])["tx_hash"] for e in L.events("ChainTx")}
    blocks = [e["block_number"] for e in L.events("ChainTx")]
    start = int(start_block or L.kv_get("ext_scan_block") or (min(blocks) - 1 if blocks else head))
    toks = tracked_tokens(L, reg)
    wt = addr_topic(wallet)
    found, out_flags, b = 0, [], start
    while b <= head:
        e = min(b + chunk - 1, head)
        for direction, topics in (("in", [T_TRANSFER, None, wt]), ("out", [T_TRANSFER, wt])):
            logs = rpc.logs(b, e, address=toks, topics=topics)
            time.sleep(pace)
            for lg in logs:
                if lg["transactionHash"] in own:
                    continue
                t = lg["topics"]
                if len(t) == 3:
                    asset, amt = erc20(lg["address"]), u(words(lg["data"])[0])
                elif len(t) == 4:
                    asset, amt = erc721(lg["address"], u(t[3][2:])), 1
                else:
                    continue
                eid = f"exttok:{lg['transactionHash']}:{int(lg['logIndex'], 16)}"
                if L.has_event(eid):
                    continue
                payload = {"asset": asset, "amount": amt if direction == "in" else -amt, "kind": "external-" + direction,
                           "counterparty": addr_of((t[1] if direction == "in" else t[2])[2:]), "tx_hash": lg["transactionHash"]}
                L.append(eid, "ExternalToken", payload, iso(int(rpc.block(int(lg["blockNumber"], 16))["timestamp"], 16)),
                         block_number=int(lg["blockNumber"], 16), tx_hash=lg["transactionHash"])
                found += 1
                if direction == "out":
                    out_flags.append(payload)
        b = e + 1
    L.kv_set("ext_scan_block", head + 1)
    if found:
        rebuild_journals(L)
    return found, out_flags
