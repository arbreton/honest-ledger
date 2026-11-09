"""ABI helpers: encode calls, decode words. Selectors are derived with keccak, never hand-typed."""
from .keccak import selector, topic

def word(v) -> str:
    if isinstance(v, str):
        return v.lower().removeprefix("0x").rjust(64, "0")
    return format(v & ((1 << 256) - 1), "064x")

def call_data(sig: str, *args) -> str:
    return selector(sig) + "".join(word(a) for a in args)

def words(hexdata: str):
    d = hexdata.removeprefix("0x")
    return [d[i:i + 64] for i in range(0, len(d), 64)]

def u(w: str) -> int:
    return int(w, 16)

def s(w: str, bits=256) -> int:
    v = int(w, 16)
    return v - (1 << 256) if v >> 255 else v

def sint(v: int, bits: int) -> int:
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v

def addr_of(w: str) -> str:
    return "0x" + w[-40:]

T_TRANSFER = topic("Transfer(address,address,uint256)")
T_WETH_DEPOSIT = topic("Deposit(address,uint256)")
T_WETH_WITHDRAWAL = topic("Withdrawal(address,uint256)")
T_ERC4626_DEPOSIT = topic("Deposit(address,address,uint256,uint256)")

def addr_topic(a: str) -> str:
    return "0x" + a.lower().removeprefix("0x").rjust(64, "0")
