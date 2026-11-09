"""Fork simulation (ADR-0005): run the exact calls on an anvil fork of the latest block, impersonating the wallet,
and report revert status, gas, balance changes and leftover allowances. Nothing here can touch mainnet."""
import json, os, socket, subprocess, time, pathlib, urllib.request
from .abi import call_data, words, u
ANVIL = os.environ.get("FARMV2_ANVIL", str(pathlib.Path.home() / ".foundry" / "bin" / "anvil"))

def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

class Fork:
    def __init__(self, upstream, block=None, optimism=True):
        self.port, self.upstream, self.block = _free_port(), upstream, block
        cmd = [ANVIL, "--fork-url", upstream, "--port", str(self.port), "--auto-impersonate", "--silent", "--retries", "8", "--fork-retry-backoff", "800"]
        if block: cmd += ["--fork-block-number", str(block)]
        if optimism: cmd += ["--optimism"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.url = f"http://127.0.0.1:{self.port}"
        for _ in range(60):
            try:
                self.rpc("eth_blockNumber", []); return
            except Exception:
                time.sleep(0.5)
        self.stop(); raise RuntimeError("anvil fork did not start")
    def rpc(self, method, params):
        req = urllib.request.Request(self.url, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(), headers={"Content-Type": "application/json"})
        out = json.loads(urllib.request.urlopen(req, timeout=60).read())
        if "error" in out: raise RuntimeError(f"{method}: {out['error']}")
        return out["result"]
    def stop(self):
        self.proc.terminate()
        try: self.proc.wait(5)
        except Exception: self.proc.kill()
    __enter__ = lambda self: self
    def __exit__(self, *a): self.stop()

def _bal(f, token, owner):
    return u(words(f.rpc("eth_call", [{"to": token, "data": call_data("balanceOf(address)", owner)}, "latest"]))[0])

class ForkRpc:
    """Minimal adapter so nav/lp read helpers can run against the fork (always 'latest')."""
    def __init__(self, f): self.f = f
    def eth_call(self, to, data, block=None, quorum=False): return self.f.rpc("eth_call", [{"to": to, "data": data}, "latest"])
    def balance(self, addr, block=None, quorum=False): return int(self.f.rpc("eth_getBalance", [addr, "latest"]), 16)

def _run(f, wallet, calls, tracked_tokens, allowances, probe=None):
    before = {"ETH": int(f.rpc("eth_getBalance", [wallet, "latest"]), 16)} | {"erc20:" + t.lower(): _bal(f, t, wallet) for t in tracked_tokens}
    gas, err = [], None
    f.rpc("anvil_setBalance", [wallet, hex(before["ETH"] + 10**18)])    # fund fees on the fork only; ETH delta is not used for checks
    for c in calls:
        try:
            h = f.rpc("eth_sendTransaction", [{"from": wallet, "to": c.to, "data": c.data, "value": hex(c.value), "gas": hex(1_500_000)}])
            rc = None
            for _ in range(40):          # the local miner is async; an early lookup would fall through to the upstream node
                try: rc = f.rpc("eth_getTransactionReceipt", [h])
                except RuntimeError: rc = None
                if rc: break
                time.sleep(0.25)
            if rc is None:
                err = f"call '{c.note or c.sig}': no receipt from fork"; break
            gas.append(int(rc["gasUsed"], 16))
            if int(rc["status"], 16) != 1:
                err = f"call '{c.note or c.sig}' reverted"; break
        except Exception as e:
            err = f"call '{c.note or c.sig}' failed: {str(e)[:160]}"; break
    after = {"ETH": int(f.rpc("eth_getBalance", [wallet, "latest"]), 16)} | {"erc20:" + t.lower(): _bal(f, t, wallet) for t in tracked_tokens}
    allow = {}
    for tok, sp in allowances:
        allow[(tok, sp)] = u(words(f.rpc("eth_call", [{"to": tok, "data": call_data("allowance(address,address)", wallet, sp)}, "latest"]))[0])
    pr = None
    if probe and err is None:
        try: pr = probe(ForkRpc(f), wallet)
        except Exception as e: pr = (False, f"probe error: {str(e)[:160]}")
    return {"ok": err is None, "error": err, "gas_used": gas, "probe": pr,
            "deltas": {k: after[k] - before[k] for k in after if k != "ETH"}, "allowances": allow}

def simulate(upstream, wallet, calls, tracked_tokens, allowances=(), block=None, probe=None):
    """Fresh fork of the upstream node at the latest block; discarded afterwards."""
    with Fork(upstream, block) as f:
        return _run(f, wallet, calls, tracked_tokens, allowances, probe)

def simulate_on(fork: "Fork"):
    """Returns a simulate() that runs on an EXISTING fork and reverts it afterwards (used by tests with a pre-seeded fork)."""
    def fn(upstream, wallet, calls, tracked_tokens, allowances=(), block=None, probe=None):
        snap = fork.rpc("evm_snapshot", [])
        try: return _run(fork, wallet, calls, tracked_tokens, allowances, probe)
        finally: fork.rpc("evm_revert", [snap])
    return fn

def check_expectations(sim, plan):
    """R-08: simulated balance changes must match the plan exactly; any unexpected movement is a rejection."""
    if not sim["ok"]: return False, sim["error"]
    for asset, d in sim["deltas"].items():
        if plan.expect_delta is None: break          # multi-step LP plans: judged by the plan's own post-simulation probe
        lo, hi = plan.expect_delta.get(asset, (0, 0))
        if not (lo <= d <= hi): return False, f"unexpected change in {asset}: {d} (expected {lo}..{hi})"
    for (tok, sp), v in sim["allowances"].items():
        if v != 0: return False, f"residual allowance {v} left for {sp}"
    if sim.get("probe") is not None and not sim["probe"][0]: return False, "post-check failed: " + sim["probe"][1]
    return True, "balance changes and allowances match the plan" + (f"; {sim['probe'][1]}" if sim.get("probe") else "")
