# Hardening (optional, needs sudo): real key isolation

At S0 the signer runs as your normal user, so anything running as you (including Hermes agents) could read the
RAM passphrase file while it is unlocked, or the keystore file at rest. The design's fix is a separate OS user:

```bash
sudo adduser --system --group --no-create-home farmv2signer
sudo mkdir -p /var/lib/farmv2signer && sudo chown -R farmv2signer: /var/lib/farmv2signer
# move data/signer to /var/lib/farmv2signer, set FARMV2_SIGNER_DIR and FARMV2_SIGNER_PW (a path only that user can read),
# run the daemon with: sudo -u farmv2signer env PYTHONPATH=... python3 -m signer
# give your user only the socket: group farmv2exec, socket mode 0660.
```

Also remove passwordless sudo from your user (`sudo visudo`), otherwise the separation is cosmetic.

Until then: keep the hot wallet small (it is about $66), lock the signer when not needed (`ops/lock-signer.sh`),
and remember `cast wallet import` briefly shows the key on the process list while `setup-signer.sh` runs.
