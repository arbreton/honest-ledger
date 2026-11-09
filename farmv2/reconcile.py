"""Ledger vs chain. Strict on wallet-held assets (exact base units); positions are valued, not reconciled (FR-L5)."""
import json
from . import registry
from .abi import call_data, words, u
from .ledger import now

def chain_wallet_balances(rpc, reg, block, L):
    """Chain-side balance for every asset the ledger knows the wallet touched."""
    wallet = reg["wallet"]["address"]
    out = {"ETH": rpc.balance(wallet, block, quorum=True)}
    for (acct, asset), _ in L.balances("wallet:").items():
        if asset == "ETH" or asset in out:
            continue
        if asset.startswith("erc20:"):
            tok = asset.split(":")[1]
            out[asset] = u(words(rpc.eth_call(tok, call_data("balanceOf(address)", wallet), block, quorum=True))[0])
        elif asset.startswith("erc721:"):
            tok, tid = asset.split(":")[1].split("#")
            try:
                owner = words(rpc.eth_call(tok, call_data("ownerOf(uint256)", int(tid)), block, quorum=True))[0][-40:]
                out[asset] = 1 if owner == wallet.lower().removeprefix("0x") else 0
            except Exception:
                out[asset] = 0   # burned / reverted ownerOf
    return out

def reconcile(L, rpc, reg, block):
    chain = chain_wallet_balances(rpc, reg, block, L)
    ledger = {a: q for (_, a), q in L.balances("wallet:").items()}
    diffs = {}
    for a in set(chain) | set(ledger):
        d = ledger.get(a, 0) - chain.get(a, 0)
        if d != 0:
            diffs[a] = {"ledger": ledger.get(a, 0), "chain": chain.get(a, 0), "delta": d}
    status = "OK" if not diffs else "BREACH"
    detail = json.dumps({"assets_checked": len(set(chain) | set(ledger)), "diffs": diffs}, sort_keys=True)
    L.db.execute("INSERT INTO reconciliations(ts,block_number,status,detail) VALUES(?,?,?,?)", (now(), block, status, detail))
    L.db.commit()
    return status, diffs
