import sys, pathlib, unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from demo import treasury_report as tr
class Fake:
    """Minimal RPC double: lets us test the reconciliation arithmetic and the report without a network."""
    def __init__(self, balances, logs): self.b, self.l = balances, logs
    def logs(self, a, b, address=None, topics=None):
        want_in = topics[1] is None
        return [x for x in self.l if x["dir"] == ("in" if want_in else "out")]
class Tests(unittest.TestCase):
    def test_reconciles_when_balance_change_equals_flows(self):
        who = "0x" + "11" * 20; tok = {"address": "0x" + "22" * 20, "symbol": "USDC", "decimals": 6}
        mk = lambda d, amt, other: {"dir": d, "topics": [tr.T_TRANSFER, "0x" + "00" * 12 + other, "0x" + "00" * 12 + who[2:]] if d == "in" else [tr.T_TRANSFER, "0x" + "00" * 12 + who[2:], "0x" + "00" * 12 + other],
                                    "data": "0x" + format(amt, "064x"), "transactionHash": "0x" + "ab" * 32}
        rpc = Fake({}, [mk("in", 5_000_000, "33" * 20), mk("in", 1_000_000, "44" * 20), mk("out", 2_500_000, "55" * 20)])
        inn, out, n, outs, cp = tr.flows(rpc, who, tok, 0, 10, pace=0)
        self.assertEqual((inn, out, n), (6_000_000, 2_500_000, 3)); self.assertEqual(outs[0][0], 2_500_000)
        self.assertEqual((8_000_000 - 4_500_000) - (inn - out), 0)             # start 4.5 USDC, end 8.0 USDC: exactly explained
        self.assertNotEqual((8_000_001 - 4_500_000) - (inn - out), 0)           # a single base unit of drift must be caught
    def test_markdown_flags_a_mismatch_loudly(self):
        rep = {"address": "0xabc", "from_block": 1, "to_block": 2, "from": "a", "to": "b", "eth_usd_start": 2000, "eth_usd_end": 2000, "eth": {"start": 1, "end": 1, "delta": 0, "note": "n"},
               "tokens": [{"symbol": "X", "address": "0x1", "start": 1, "end": 5, "in": 2, "out": 0, "transfers": 1, "unexplained": 2.0, "reconciled": False, "usd_end": float("nan"), "usd_start": float("nan"), "largest_outflows": [], "top_counterparties": []}]}
        self.assertIn("MISMATCH: investigate", tr.to_markdown(rep))
if __name__ == "__main__": unittest.main()
