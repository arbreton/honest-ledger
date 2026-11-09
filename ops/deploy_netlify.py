"""Optional: deploy ./site to your own Netlify site (id and token are yours; nothing personal is committed)."""
import json, os, io, zipfile, pathlib, urllib.request
ROOT = pathlib.Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
from farmv2 import registry
SITE_ID = registry.local_settings().get("netlify_site_id")      # set in registry-data/local.json (git-ignored)

def deploy(site_dir=ROOT / "site") -> str:
    if not SITE_ID: raise RuntimeError("no netlify_site_id in registry-data/local.json: dashboard deploy is optional and disabled")
    tok = json.load(open(os.path.expanduser("~/.config/netlify/config.json")))
    token = list(tok["users"].values())[0]["auth"]["token"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(pathlib.Path(site_dir).glob("*")):
            if p.is_file():
                z.write(p, p.name)
    req = urllib.request.Request(f"https://api.netlify.com/api/v1/sites/{SITE_ID}/deploys", data=buf.getvalue(),
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/zip"})
    out = json.loads(urllib.request.urlopen(req, timeout=90).read())
    return out.get("state", "unknown")

if __name__ == "__main__":
    print("deploy:", deploy())
