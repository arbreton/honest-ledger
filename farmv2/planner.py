"""Builds exact calldata from the registry. Strategies name protocols by registry id, never by raw address (FR-R, LLD §1)."""
from dataclasses import dataclass, field
from . import registry
from .abi import call_data
from .keccak import selector

@dataclass
class Call:
    to: str
    data: str
    value: int = 0
    sig: str = ""
    note: str = ""
    @property
    def selector(self): return self.data[:10].lower()

@dataclass
class Plan:
    calls: list
    expect_delta: dict = field(default_factory=dict)    # asset -> (min, max) wallet change (ETH excluded: fees are checked separately)
    allowance_zero: list = field(default_factory=list)  # [(token, spender)] must be 0 after the plan
    notional_usd: float = 0.0
    approvals: list = field(default_factory=list)       # [{"spender", "amount"}]
    probe: object = None                                # callable(fork, wallet)->(ok,msg): post-simulation state check
    internal: bool = False                              # value stays within the wallet's own positions (all recipients = wallet)
    est_cost_usd: float = 0.0                           # swap fees + slippage allowance, beyond gas

def approve_exact(token, spender, amount):
    return Call(token, call_data("approve(address,uint256)", spender, amount), 0, "approve(address,uint256)", f"approve {amount}")

def vault_deposit(reg, vault_id, assets, usdc_id="usdc", min_shares=1):
    vault, usdc, wallet = registry.addr(reg, vault_id), registry.addr(reg, usdc_id), reg["wallet"]["address"]
    calls = [approve_exact(usdc, vault, assets), Call(vault, call_data("deposit(uint256,address)", assets, wallet), 0, "deposit(uint256,address)", "vault deposit")]
    return Plan(calls, {"erc20:" + usdc.lower(): (-assets, -assets), "erc20:" + vault.lower(): (min_shares, 1 << 200)},
                [(usdc, vault)], assets / 1e6, [{"spender": vault, "amount": assets}])

def vault_redeem(reg, vault_id, shares, usdc_id="usdc"):
    vault, usdc, wallet = registry.addr(reg, vault_id), registry.addr(reg, usdc_id), reg["wallet"]["address"]
    return Plan([Call(vault, call_data("redeem(uint256,address,address)", shares, wallet, wallet), 0, "redeem(uint256,address,address)", "vault redeem")],
                {"erc20:" + vault.lower(): (-shares, -shares), "erc20:" + usdc.lower(): (1, 1 << 200)})

def weth_wrap(reg, wei):
    weth = registry.addr(reg, "weth")
    return Plan([Call(weth, call_data("deposit()"), wei, "deposit()", "wrap")], {"erc20:" + weth.lower(): (wei, wei)})

def weth_unwrap(reg, wei):
    weth = registry.addr(reg, "weth")
    return Plan([Call(weth, call_data("withdraw(uint256)", wei), 0, "withdraw(uint256)", "unwrap")], {"erc20:" + weth.lower(): (-wei, -wei)})

def build(reg, action, params):
    if action == "vault_deposit": return vault_deposit(reg, params["vault"], int(params["assets"]))
    if action == "vault_redeem": return vault_redeem(reg, params["vault"], int(params["shares"]))
    if action == "weth_wrap": return weth_wrap(reg, int(params["wei"]))
    if action == "weth_unwrap": return weth_unwrap(reg, int(params["wei"]))
    raise ValueError(f"unknown action {action}")
