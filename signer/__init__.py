"""Standalone signer. Imports NOTHING from farmv2 (ADR-0001). Verifies a signed decision receipt, re-checks hard limits
from its own static allowlist, and signs with Foundry's `cast mktx` from an encrypted keystore. Never touches the network."""
