"""Independent auditor (ADR-0013). Recomputes from raw chain data with its OWN RPC code; shares no logic with farmv2's
NAV/ledger code. Exception: canaries deliberately call the real Risk Gate (farmv2.rules) because that is what they test."""
