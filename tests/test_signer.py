import json, os, sys, shutil, subprocess, tempfile, pathlib, unittest, time
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CAST = str(pathlib.Path.home() / ".foundry" / "bin" / "cast")
TMP = pathlib.Path(tempfile.mkdtemp(prefix="signertest-"))
os.environ["FARMV2_SIGNER_DIR"] = str(TMP); os.environ["FARMV2_HALT_DIR"] = str(TMP / "halt"); os.environ["FARMV2_SIGNER_PW"] = str(TMP / "pw")
from signer import core
from farmv2.keccak import selector

def setUpModule():
    # own our paths explicitly: other test modules reload signer.core with their own temp dirs
    TMP.mkdir(exist_ok=True)
    core.DIR = TMP; core.HALT_FLAG = TMP / "halt" / "HALT"; core.PW_FILE = TMP / "pw"

TEST_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"   # public anvil dev key: worthless
TEST_ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
USDC, VAULT, OTHER = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913", "0xee8f4ec5672f09119b96ab6fb59c27e1b7e44b61", "0x1111111111111111111111111111111111111111"
def w(v): return format(int(v, 16) if isinstance(v, str) else v, "064x")

ALLOW = {"chain_id": 8453, "wallet": TEST_ADDR.lower(),
         "limits": {"max_value_wei": "10000000000000000", "max_gas_limit": 800000, "max_fee_gwei": 0.05, "daily_tx": 3, "daily_value_wei": "20000000000000000", "receipt_ttl_s": 900},
         "targets": {USDC: {"id": "usdc", "spenders": [VAULT], "max_approve": "25000000", "selectors": {selector("approve(address,uint256)"): {"sig": "approve", "args": {"0": "spender", "1": "max_approve"}}}},
                     VAULT: {"id": "vault", "spenders": [], "selectors": {selector("deposit(uint256,address)"): {"sig": "deposit", "args": {"1": "wallet"}}}}}}
KEY = bytes.fromhex("11" * 32)

def tx(to=USDC, data=None, **kw):
    t = {"chain_id": 8453, "nonce": 0, "to": to, "value": 0, "gas": 100000, "max_fee_per_gas": 10_000_000, "max_priority_fee_per_gas": 1_000_000,
         "data": data or selector("approve(address,uint256)") + w(VAULT) + w(2_000_000)}
    t.update(kw); return t
def rc(t, **kw):
    r = core.make_receipt(KEY, t, "intent-1", 900, kw.pop("rid", "r1")); r.update(kw); return r
def chk(t, r=None, spent=None, used=()):
    return core.check(t, r or rc(t), ALLOW, KEY, spent or {"count": 0, "value": 0}, set(used))[:2]

class SignerChecks(unittest.TestCase):
    def test_valid_approve(self): self.assertEqual(chk(tx()), (True, "OK"))
    def test_valid_deposit_to_self(self):
        t = tx(to=VAULT, data=selector("deposit(uint256,address)") + w(2_000_000) + w(TEST_ADDR)); self.assertEqual(chk(t), (True, "OK"))
    def test_deposit_to_stranger_refused(self):
        t = tx(to=VAULT, data=selector("deposit(uint256,address)") + w(2_000_000) + w(OTHER)); self.assertEqual(chk(t)[1], "RECIPIENT")
    def test_unlimited_approval_refused(self):
        t = tx(data=selector("approve(address,uint256)") + w(VAULT) + w((1 << 256) - 1)); self.assertEqual(chk(t)[1], "LIMIT")
    def test_approve_to_unknown_spender_refused(self):
        t = tx(data=selector("approve(address,uint256)") + w(OTHER) + w(1)); self.assertEqual(chk(t)[1], "RECIPIENT")
    def test_unknown_target_and_selector(self):
        self.assertEqual(chk(tx(to=OTHER))[1], "NOT_ALLOWLISTED")
        self.assertEqual(chk(tx(data=selector("transfer(address,uint256)") + w(OTHER) + w(1)))[1], "NOT_ALLOWLISTED")
    def test_contract_creation_refused(self): self.assertEqual(chk(tx(to=""), rc(tx()))[1], "CREATE")
    def test_gas_price_above_cap_refused(self): self.assertEqual(chk(tx(max_fee_per_gas=8_000_000_000))[1], "LIMIT")   # v1's 8 gwei
    def test_gas_limit_and_value_caps(self):
        self.assertEqual(chk(tx(gas=900000))[1], "LIMIT"); self.assertEqual(chk(tx(value=10**17))[1], "LIMIT")
    def test_wrong_chain(self): self.assertEqual(chk(tx(chain_id=1))[1], "CHAIN")
    def test_tampered_tx_breaks_plan_hash(self):
        t = tx(); r = rc(t); t2 = dict(t, nonce=1); self.assertEqual(chk(t2, r)[1], "BAD_RECEIPT")
    def test_forged_receipt(self):
        t = tx(); r = rc(t); r["sig"] = "00" * 32; self.assertEqual(chk(t, r)[1], "BAD_RECEIPT")
    def test_receipt_from_wrong_key(self):
        t = tx(); r = core.make_receipt(b"\x22" * 32, t, "i", 900, "rx"); self.assertEqual(chk(t, r)[1], "BAD_RECEIPT")
    def test_expired(self):
        t = tx(); r = core.make_receipt(KEY, t, "i", -5, "rx"); self.assertEqual(chk(t, r)[1], "EXPIRED")
    def test_replay(self): self.assertEqual(chk(tx(), used={"r1"})[1], "REPLAY")
    def test_daily_cap(self): self.assertEqual(chk(tx(), spent={"count": 3, "value": 0})[1], "LIMIT")
    def test_halt_blocks(self):
        (TMP / "halt").mkdir(exist_ok=True); core.HALT_FLAG.write_text("{}")
        try: self.assertEqual(chk(tx())[1], "HALTED")
        finally: core.HALT_FLAG.unlink()

def _real_allow():
    """The shipped allowlist, rebuilt for the throwaway wallet, so the tests exercise the real selectors and arg rules."""
    import copy
    from farmv2 import registry, policy
    reg = copy.deepcopy(registry.load()); reg["wallet"]["address"] = TEST_ADDR
    return reg, policy.build(reg)

class LpCallRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from farmv2 import registry
        cls.reg, cls.allow = _real_allow()
        cls.npm, cls.router = registry.addr(cls.reg, "aero-cl-npm").lower(), registry.addr(cls.reg, "aero-cl-swap-router").lower()
        cls.weth, cls.usdc = registry.addr(cls.reg, "weth").lower(), registry.addr(cls.reg, "usdc").lower()
    def ok(self, to, data):
        t = tx(to=to, data=data, gas=600000); return core.check(t, rc(t), self.allow, KEY, {"count": 0, "value": 0}, set())[:2]
    def test_mint_recipient_must_be_wallet(self):
        sig = "mint((address,address,int24,int24,int24,uint256,uint256,uint256,uint256,address,uint256,uint160))"
        f = lambda rcpt: selector(sig) + w(self.weth) + w(self.usdc) + w(50) + w(2**256 - 199000) + w(2**256 - 198000) + w(10**15) + w(10**6) + w(0) + w(0) + w(rcpt) + w(2**40) + w(0)
        self.assertEqual(self.ok(self.npm, f(TEST_ADDR)), (True, "OK"))
        self.assertEqual(self.ok(self.npm, f(OTHER))[1], "RECIPIENT")
    def test_collect_recipient_must_be_wallet(self):
        sig = "collect((uint256,address,uint128,uint128))"
        f = lambda rcpt: selector(sig) + w(123) + w(rcpt) + w(2**128 - 1) + w(2**128 - 1)
        self.assertEqual(self.ok(self.npm, f(TEST_ADDR)), (True, "OK")); self.assertEqual(self.ok(self.npm, f(OTHER))[1], "RECIPIENT")
    def test_swap_recipient_must_be_wallet(self):
        sig = "exactInputSingle((address,address,int24,address,uint256,uint256,uint256,uint160))"
        f = lambda rcpt: selector(sig) + w(self.weth) + w(self.usdc) + w(50) + w(rcpt) + w(2**40) + w(10**15) + w(1) + w(0)
        self.assertEqual(self.ok(self.router, f(TEST_ADDR)), (True, "OK")); self.assertEqual(self.ok(self.router, f(OTHER))[1], "RECIPIENT")
    def test_approvals_only_to_registered_spenders_with_caps(self):
        ap = selector("approve(address,uint256)")
        self.assertEqual(self.ok(self.usdc, ap + w(self.router) + w(10_000_000)), (True, "OK"))
        self.assertEqual(self.ok(self.weth, ap + w(self.npm) + w(10**16)), (True, "OK"))
        self.assertEqual(self.ok(self.usdc, ap + w(OTHER) + w(1))[1], "RECIPIENT")
        self.assertEqual(self.ok(self.usdc, ap + w(self.router) + w(46_000_000))[1], "LIMIT")        # above the $45 cap
        self.assertEqual(self.ok(self.weth, ap + w(self.router) + w((1 << 256) - 1))[1], "LIMIT")     # unlimited
    def test_nft_transfer_and_token_transfer_still_impossible(self):
        for sig, args in (("transferFrom(address,address,uint256)", w(TEST_ADDR) + w(OTHER) + w(1)), ("safeTransferFrom(address,address,uint256)", w(TEST_ADDR) + w(OTHER) + w(1)),
                          ("setApprovalForAll(address,bool)", w(OTHER) + w(1)), ("transfer(address,uint256)", w(OTHER) + w(1))):
            self.assertEqual(self.ok(self.npm, selector(sig) + args)[1], "NOT_ALLOWLISTED", sig)
            self.assertEqual(self.ok(self.usdc, selector(sig) + args)[1], "NOT_ALLOWLISTED", sig)

class SignerEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ks = TMP / "keystore"; cls.ks.mkdir(exist_ok=True)
        subprocess.run([CAST, "wallet", "import", "farmv2", "--keystore-dir", str(cls.ks), "--private-key", TEST_KEY, "--unsafe-password", "test-pass"], check=True, capture_output=True)
    def test_locked_until_password_present(self):
        t = tx(); r = {"op": "sign", "tx": t, "receipt": rc(t)}
        core.PW_FILE.unlink(missing_ok=True)
        self.assertEqual(core.handle(r, ALLOW, KEY, str(self.ks / "farmv2"))["code"], "LOCKED")
    def test_signs_valid_and_signature_recovers_to_wallet(self):
        core.PW_FILE.write_text("test-pass"); os.chmod(core.PW_FILE, 0o600)
        t = tx(nonce=7); out = core.handle({"op": "sign", "tx": t, "receipt": rc(t, rid="e2e-1")}, ALLOW, KEY, str(self.ks / "farmv2"))
        self.assertTrue(out["ok"], out)
        dec = subprocess.run([CAST, "decode-tx", out["raw"], "--json"], capture_output=True, text=True).stdout
        d = json.loads(dec)["data"]
        self.assertEqual(d["signer"].lower(), TEST_ADDR.lower()); self.assertEqual(d["to"].lower(), USDC)
        self.assertEqual(int(d["nonce"], 16), 7); self.assertEqual(int(d["chainId"], 16), 8453); self.assertEqual(int(d["maxFeePerGas"], 16), 10_000_000)
        again = core.handle({"op": "sign", "tx": t, "receipt": rc(t, rid="e2e-1")}, ALLOW, KEY, str(self.ks / "farmv2"))
        self.assertEqual(again["code"], "REPLAY")   # single-use receipts
    @classmethod
    def tearDownClass(cls): core.PW_FILE.unlink(missing_ok=True); shutil.rmtree(TMP, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
