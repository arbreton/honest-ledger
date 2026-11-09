"""Minimal JSON-RPC client, stdlib only. Multi-provider reads with agreement (NFR-A3, R-16)."""
import json, time, urllib.request, urllib.error

DEFAULT_URLS = ["https://base.publicnode.com", "https://1rpc.io/base", "https://mainnet.base.org"]
UA = "farmv2/0.1 (+self-hosted portfolio ledger)"

class RpcError(Exception):
    pass

class NoQuorum(RpcError):
    pass

def hx(n: int) -> str:
    return hex(n)

class Rpc:
    def __init__(self, urls=None, timeout=25, retries=2, quorum_need=2):
        self.urls = list(urls or DEFAULT_URLS)
        self.quorum_need = quorum_need   # production = 2; only tests against a single local fork set 1
        self.timeout, self.retries = timeout, retries
        self._id = 0

    def _post(self, url, method, params):
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            out = json.loads(r.read())
        if "error" in out:
            raise RpcError(f"{url} {method}: {out['error']}")
        return out["result"]

    def call(self, method, params, urls=None):
        """First provider that answers; transient errors retried with backoff."""
        last = None
        for url in (urls or self.urls):
            for attempt in range(self.retries + 1):
                try:
                    return self._post(url, method, params)
                except (urllib.error.URLError, TimeoutError, RpcError, json.JSONDecodeError, OSError) as e:
                    last = e
                    if isinstance(e, RpcError) and "429" not in str(e) and "rate" not in str(e).lower():
                        break  # deterministic error from this provider: try the next one
                    time.sleep(0.4 * (attempt + 1))
        raise RpcError(f"all providers failed for {method}: {last}")

    def agree(self, method, params, need=None):
        need = need or self.quorum_need
        """Same answer from >= need independent providers, else NoQuorum. Params MUST pin a block."""
        answers = {}
        for url in self.urls:
            try:
                res = self._post(url, method, params)
            except Exception:
                continue
            key = json.dumps(res, sort_keys=True)
            answers.setdefault(key, []).append(url)
            if len(answers[key]) >= need:
                return json.loads(key)
        raise NoQuorum(f"no {need}-provider agreement for {method} {params}")

    # --- convenience ---
    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def balance(self, addr, block, quorum=False) -> int:
        f = self.agree if quorum else self.call
        return int(f("eth_getBalance", [addr, hx(block)]), 16)

    def nonce(self, addr, block, quorum=False) -> int:
        f = self.agree if quorum else self.call
        return int(f("eth_getTransactionCount", [addr, hx(block)]), 16)

    def eth_call(self, to, data, block, quorum=False) -> str:
        f = self.agree if quorum else self.call
        return f("eth_call", [{"to": to, "data": data}, hx(block)])

    def block(self, number, full=False):
        return self.call("eth_getBlockByNumber", [hx(number), full])

    def receipt(self, tx_hash):
        return self.call("eth_getTransactionReceipt", [tx_hash])

    def logs(self, from_block, to_block, address=None, topics=None):
        p = {"fromBlock": hx(from_block), "toBlock": hx(to_block)}
        if address:
            p["address"] = address
        if topics:
            p["topics"] = topics
        return self.call("eth_getLogs", [p])
