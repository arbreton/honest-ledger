"""Time <-> block conversion from real block timestamps. Base's block time has changed (2s -> 0.2s); NEVER assume blocks/day."""
def ts(rpc, block):
    return int(rpc.block(block)["timestamp"], 16)

def block_at_age(rpc, head, seconds_ago, cache=None):
    """Last block whose timestamp is <= head_ts - seconds_ago, by bisection over real timestamps."""
    target = ts(rpc, head) - seconds_ago
    lo, hi = max(1, head - int(seconds_ago * 6) - 10_000), head      # >5 blocks/s upper bound on rate
    if ts(rpc, lo) > target:
        lo = max(1, lo // 2)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ts(rpc, mid) <= target: lo = mid
        else: hi = mid - 1
    return lo
