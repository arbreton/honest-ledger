"""Read-only yield discovery from DeFiLlama (FR-D1). Produces CANDIDATES for the operator: it never creates intents.
A new protocol still needs: registry entry + code pin + evidence + human approval (R-20)."""
import json, urllib.request, pathlib, time
ROOT = pathlib.Path(__file__).resolve().parents[1]
URL = "https://yields.llama.fi/pools"
CACHE = ROOT / "data" / "yields_base_usdc.json"

def fetch(min_tvl=3_000_000, chain="Base", ttl_s=6 * 3600, force=False):
    if CACHE.exists() and not force and time.time() - CACHE.stat().st_mtime < ttl_s:
        return json.loads(CACHE.read_text())
    req = urllib.request.Request(URL, headers={"User-Agent": "farmv2/0.1"})
    pools = json.loads(urllib.request.urlopen(req, timeout=60).read())["data"]
    rows = []
    for p in pools:
        sym = (p.get("symbol") or "")
        if p.get("chain") != chain or (p.get("tvlUsd") or 0) < min_tvl or "USDC" not in sym.upper() or p.get("ilRisk") != "no": continue
        rows.append({"project": p["project"], "symbol": sym, "tvl_usd": round(p["tvlUsd"]), "apy": p.get("apy"), "apy_base": p.get("apyBase"),
                     "apy_reward": p.get("apyReward"), "apy_mean_30d": p.get("apyMean30d")})
    rows.sort(key=lambda r: -(r["apy_base"] or 0))
    out = {"fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rows": rows}
    CACHE.parent.mkdir(parents=True, exist_ok=True); CACHE.write_text(json.dumps(out))
    return out

def llama_apy_for_held_vault(rows, tvl_hint_usd=401e6):
    """DeFiLlama's base APY for the Gauntlet USDC Prime vault we hold (matched by project/symbol/TVL, not by address)."""
    m = [r for r in rows if r["project"] == "morpho-blue" and r["symbol"] == "GTUSDCP" and abs(r["tvl_usd"] - tvl_hint_usd) / tvl_hint_usd < 0.25]
    return (m[0]["apy_base"] or 0) / 100 if m else None
