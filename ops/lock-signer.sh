#!/bin/bash
# OPERATOR-RUN. Locks the signer immediately: removes the passphrase file and stops the daemon.
rm -f /dev/shm/farmv2-signer.pw; pkill -f "python3 -m signer" 2>/dev/null || true; echo "signer locked"
