# On-chain reconciliation report

* Address: `0x3FE04A59Ebd38cF06080a6F60a98D124eb59392A` (Base)
* Window: 2026-11-08T22:30+00:00 → 2026-11-09T04:30+00:00 UTC (blocks 54,933,416 → 55,041,413)
* ETH/USD (Chainlink): 2,125.09 → 2,141.62

## Do the books reconcile?

| Token | Start | End | In | Out | Transfers | Unexplained | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| USDC | 229,101.2712 | 254,303.7990 | 314,023.4897 | 288,820.9618 | 2339 | +0.000000 | **RECONCILES** |
| WETH | 841.3989 | 829.5031 | 141.3069 | 153.2027 | 2342 | +0.000000 | **RECONCILES** |

Native ETH: 0.000000 → 0.000000 (+0.000000). _Native ETH moves through internal calls and gas, which token logs cannot explain; shown for context, not reconciled._

## Largest outflows and counterparties

**USDC**: 2,495.0360 to 0x7c4c7ac39f3db79b10400b17a2f67dd6a4e9fec3 (tx 0x958a1cf2ef…); 1,947.8167 to 0xc67489dbd11f4d980db4313890dcfe4ca3f3ea27 (tx 0x76c4531884…); 1,947.8167 to 0xc67489dbd11f4d980db4313890dcfe4ca3f3ea27 (tx 0x47981223e8…)
  Top counterparties by net flow: 0x51c72848… +78,602.57, 0x7c4c7ac3… -12,198.24, 0xbeeb9eee… -9,191.31, 0x1f012ab1… -8,117.00, 0x32559f73… -8,002.87

**WETH**: 6.8534 to 0x6ed60864fb8fb610a65af5d16cef272548bc64d6 (tx 0x15f10b71c7…); 0.9403 to 0xcaf22ce31298cf2bf1d152862f80216478ad7c67 (tx 0x258e3c0e11…); 0.8690 to 0xc67489dbd11f4d980db4313890dcfe4ca3f3ea27 (tx 0xbc91df0f17…)
  Top counterparties by net flow: 0x51c72848… -36.59, 0x7c4c7ac3… +5.64, 0xbeeb9eee… +4.29, 0x1f012ab1… +3.81, 0x32559f73… +3.74

**Priced holdings at end of window: $2,030,785.98** (tokens without a trusted price feed are shown in units and excluded).

_Read-only: no keys, no signing. Every figure is derived from archive RPC state and event logs and can be re-checked by anyone._
