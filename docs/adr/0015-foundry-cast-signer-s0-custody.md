# ADR-0015: Sign with Foundry `cast` from an encrypted keystore; S0 custody limits stated honestly

*Architecture Decision Record*

**Status:** Accepted (implemented) · **Date:** 2026-11-08 · **Decider:** Operator

## Context
v2 needs a signer that (a) never imports core code, (b) re-checks limits independently, and (c) uses no hand-written
cryptography. Python's standard library has no secp256k1 or AES. Foundry 1.8.6 is already installed and used by v1.
The operator chose to reuse the v1 hot-wallet key rather than create a new wallet, and the machine has no second OS user.

## Decision
- The signer is a separate process (`python3 -m signer`) that listens on a 0600 Unix socket and imports nothing from `farmv2`.
- Signing is `cast mktx` with every field given explicitly (offline), from an **encrypted Foundry keystore**.
- The passphrase is typed by the operator at unlock, held only in a RAM file (`/dev/shm`, mode 0600), and never written to disk. After reboot the signer is locked and v2 is read-only.
- The signer verifies an HMAC **decision receipt** (plan hash, expiry, single use), a static **allowlist whose sha256 the operator approved**, recipient rules decoded from calldata (deposit/redeem receivers must be the wallet; approve spenders from a short list), per-tx/day caps and an absolute gas-price cap.
- The v1 key is imported by an operator-run script that first proves the key controls the registered wallet. No LLM session reads the key or passphrase.

## Consequences
- No custom cryptography and no new dependencies. Every refusal path is unit-tested; a real signature is verified by recovery.
- **Limit (S0):** the daemon runs as the same OS user as everything else, so a process running as that user could read the RAM passphrase file while unlocked. Bounded by keeping the wallet small (about $66) and locking when idle. `ops/HARDENING.md` gives the sudo steps for a separate user. At S1 the Safe + on-chain Roles module replaces this.
- `cast wallet import` briefly exposes the key on the process list during setup.
- The receipt HMAC key is shared by core and signer (same user), so a compromised core could mint receipts; the signer's independent allowlist, recipient rules and caps are the second layer.

## Alternatives rejected
Pure-Python secp256k1 (hand-rolled crypto); `web3.py`/`eth-account` (new dependency tree in the money path); keeping the key in `.env` (the v1 flaw).
