"""Unix-socket signer daemon. Start it with the operator's unlock script; stops signing the moment the password file or allowlist hash changes."""
import hashlib, json, os, socket, sys, pathlib, stat
from . import core

def main():
    d = core.DIR
    allow_path, sha_path = d / "allowlist.json", d / "allowlist.sha256"
    keystore, keyfile, sock = d / "keystore" / "farmv2", d / "receipt.key", d / "signer.sock"
    body = allow_path.read_text()
    if hashlib.sha256(body.encode()).hexdigest() != sha_path.read_text().strip():
        sys.exit("allowlist hash does not match the operator-approved hash; refusing to start")
    allow = json.loads(body)
    key = bytes.fromhex(keyfile.read_text().strip())
    if sock.exists():
        sock.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sock)); os.chmod(sock, 0o600); srv.listen(4)
    print("signer listening", sock, "wallet", allow["wallet"], flush=True)
    while True:
        c, _ = srv.accept()
        try:
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = c.recv(65536)
                if not chunk: break
                buf += chunk
            # re-verify the allowlist on every request: a changed file is refused even if the daemon survived
            cur = (d / "allowlist.json").read_text()
            if hashlib.sha256(cur.encode()).hexdigest() != sha_path.read_text().strip():
                resp = {"ok": False, "code": "ALLOWLIST_CHANGED"}        # file differs from what the operator approved
            else:
                allow = json.loads(cur)                                   # approved hash matches: use the CURRENT approved list
                resp = core.handle(json.loads(buf), allow, key, str(keystore))
        except Exception as e:
            resp = {"ok": False, "code": "ERROR", "detail": str(e)[:200]}
        c.sendall(json.dumps(resp).encode() + b"\n"); c.close()

if __name__ == "__main__":
    main()
