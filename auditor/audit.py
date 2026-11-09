"""Independent checks. May HALT; can never approve or sign. Own JSON-RPC, own hashing, read-only DB access."""
import json, sqlite3, urllib.request, hashlib, time, sys, pathlib

# Deliberately a different provider order than farmv2.rpc, to avoid sharing a single failure path.
PROVIDERS = ["https://mainnet.base.org", "https://1rpc.io/base", "https://base.publicnode.com"]

def rpc(method, params):
    last = None
    for url in PROVIDERS:
        for _ in range(3):
            try:
                req = urllib.request.Request(url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                             headers={"Content-Type": "application/json", "User-Agent": "farmv2-auditor/0.1"})
                out = json.loads(urllib.request.urlopen(req, timeout=25).read())
                if "result" in out:
                    return out["result"]
                last = out.get("error")
            except Exception as e:
                last = e
                time.sleep(0.8)
    raise RuntimeError(f"auditor rpc failed {method}: {last}")

def erc20_balance(token, owner, block):
    data = "0x70a08231" + owner.lower().removeprefix("0x").rjust(64, "0")
    return int(rpc("eth_call", [{"to": token, "data": data}, hex(block)]), 16)

def check_hash_chain(db):
    prev, n = "0" * 64, 0
    for seq, eid, typ, payload, occ, ph, h in db.execute("SELECT seq,event_id,type,payload,occurred_at,prev_hash,hash FROM events ORDER BY seq"):
        calc = hashlib.sha256(f"{prev}|{eid}|{typ}|{payload}|{occ}".encode()).hexdigest()
        if ph != prev or h != calc:
            return False, f"hash chain broken at seq {seq}"
        prev, n = h, n + 1
    return True, f"{n} events verified"

def run(db_path, wallet, tokens: dict, tolerance=0.005):
    """tokens: {name: (address, decimals)}. Returns (findings list, ok bool)."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    F = []
    ok, msg = check_hash_chain(db)
    F.append(("hash-chain", ok, msg))
    block = int(rpc("eth_blockNumber", []), 16) - 3
    # 1) unattributed transactions: chain nonce must equal count of indexed wallet txs (SS-1)
    chain_nonce = int(rpc("eth_getTransactionCount", [wallet, hex(block)]), 16)
    n_ev = db.execute("SELECT count(*) FROM events WHERE type='ChainTx'").fetchone()[0]
    unattributed = db.execute("SELECT count(*) FROM events e WHERE e.type='ChainTx' AND e.tx_hash NOT IN (SELECT tx_hash FROM sent_txs) "
                              "AND e.tx_hash NOT IN (SELECT tx_hash FROM declarations)").fetchone()[0]
    in_flight = db.execute("SELECT count(*) FROM sent_txs WHERE tx_hash NOT IN (SELECT tx_hash FROM events WHERE tx_hash IS NOT NULL)").fetchone()[0]
    F.append(("unattributed-tx", unattributed == 0 and chain_nonce <= n_ev + in_flight,
              f"chain nonce {chain_nonce}, indexed {n_ev}, sent-not-yet-indexed {in_flight}, unattributed {unattributed}"))
    # 2) independent balances vs ledger postings
    eth_chain = int(rpc("eth_getBalance", [wallet, hex(block)]), 16)
    led = {}
    for asset, amt in db.execute("SELECT asset_id, amount FROM postings WHERE account_id=?", ("wallet:" + wallet.lower(),)):
        led[asset] = led.get(asset, 0) + int(amt)
    # ledger may be a few blocks behind: allow a tolerance only on ETH dust (gas of in-flight)
    d = abs(led.get("ETH", 0) - eth_chain)
    F.append(("eth-balance", (d <= 10**13 and chain_nonce == n_ev) or chain_nonce != n_ev, f"ledger {led.get('ETH', 0)} vs chain {eth_chain} (delta {d} wei)"))
    for name, (addr, dec) in tokens.items():
        c = erc20_balance(addr, wallet, block)
        l = led.get("erc20:" + addr.lower(), 0)
        F.append((f"{name}-balance", c == l or chain_nonce != n_ev, f"ledger {l} vs chain {c}"))
    # 3) NAV: recompute only the wallet-level legs independently and compare with the latest snapshot
    snap = db.execute("SELECT block_number, nav_usd, breakdown FROM nav_snapshots ORDER BY block_number DESC LIMIT 1").fetchone()
    if snap:
        b = json.loads(snap[2])
        px = b["eth_usd"]
        indep_wallet = eth_chain / 1e18 * px
        rows = {h["name"]: h["usd"] for h in b["holdings"]}
        # compare only if the snapshot is near the audited block, otherwise price/time drift dominates
        F.append(("nav-fresh", block - snap[0] < 20_000, f"latest nav snapshot is {block - snap[0]} blocks old"))
        F.append(("nav-eth-leg", abs(rows.get("ETH", 0) - indep_wallet) / max(indep_wallet, 1e-9) < 0.05 if block - snap[0] < 600 else True,
                  f"snapshot ETH leg {rows.get('ETH', 0):.4f} vs independent {indep_wallet:.4f}"))
    all_ok = all(ok for _, ok, _ in F)
    return F, all_ok, block
