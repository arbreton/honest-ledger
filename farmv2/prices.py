"""ETH/USD from Chainlink at any block (archive), cross-checked against the WETH/USDC pool (R-15)."""
from . import registry
from .abi import call_data, words, u

class PriceError(Exception):
    pass

def chainlink_eth_usd(rpc, reg, block, quorum=False) -> float:
    feed = registry.addr(reg, "chainlink-eth-usd")
    w = words(rpc.eth_call(feed, call_data("latestRoundData()"), block, quorum))
    answer = u(w[1])
    if answer <= 0:
        raise PriceError("non-positive chainlink answer")
    return answer / 1e8

def pool_eth_usd(rpc, reg, block) -> float:
    pool = registry.addr(reg, "aero-cl-weth-usdc")
    sq = u(words(rpc.eth_call(pool, call_data("slot0()"), block))[0])
    return (sq / 2**96) ** 2 * 1e12   # token0=WETH(18), token1=USDC(6)

def eth_usd(rpc, reg, block, max_dev=0.01, quorum=False):
    """Returns (price, source). Raises PriceError when sources disagree beyond max_dev (fail closed)."""
    cl = chainlink_eth_usd(rpc, reg, block, quorum)
    try:
        pl = pool_eth_usd(rpc, reg, block)
    except Exception:
        return cl, "chainlink-only"
    if abs(cl - pl) / cl > max_dev:
        raise PriceError(f"price sources disagree: chainlink {cl:.2f} vs pool {pl:.2f}")
    return cl, "chainlink+pool"
