"""Deploy the website to Firebase Hosting via the REST API (no Node / Firebase CLI needed).

Reads ../firebase.json (public dir, ignore globs, rewrites, headers) so it stays the single
source of truth, uploads only files Hosting doesn't already have, then releases the version.

    cd backend && python -m scripts.deploy_hosting --project <gcp-project> [--site <site-id>]
"""

import argparse
import fnmatch
import gzip
import hashlib
import json
from pathlib import Path

import google.auth
from google.auth.transport.requests import AuthorizedSession

API = "https://firebasehosting.googleapis.com/v1beta1"
REPO = Path(__file__).resolve().parents[2]


def hosting_config(cfg: dict) -> dict:
    """firebase.json `hosting` -> REST ServingConfig (source -> glob, headers list -> map)."""
    out = {}
    if cfg.get("rewrites"):
        out["rewrites"] = [{"glob": r["source"], **{k: v for k, v in r.items() if k != "source"}}
                           for r in cfg["rewrites"]]
    if cfg.get("headers"):
        out["headers"] = [{"glob": h["source"], "headers": {x["key"]: x["value"] for x in h["headers"]}}
                          for h in cfg["headers"]]
    return out


def collect_files(public: Path, ignore: list[str]) -> dict[str, bytes]:
    files = {}
    for path in sorted(public.rglob("*")):
        rel = path.relative_to(public).as_posix()
        if path.is_dir() or any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(path.name, g.split("/")[-1]) for g in ignore):
            continue
        files[f"/{rel}"] = gzip.compress(path.read_bytes(), mtime=0)  # deterministic hash
    return files


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--project", required=True)
    p.add_argument("--site", help="Hosting site id (default: the project's default site)")
    args = p.parse_args()
    site = args.site or args.project

    cfg = json.loads((REPO / "firebase.json").read_text())["hosting"]
    public = REPO / cfg["public"]
    files = collect_files(public, cfg.get("ignore", []))
    hashes = {path: hashlib.sha256(blob).hexdigest() for path, blob in files.items()}
    print(f"{len(files)} files from {public.relative_to(REPO)}")

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform",
                                           "https://www.googleapis.com/auth/firebase"])
    if hasattr(creds, "with_quota_project"):
        creds = creds.with_quota_project(args.project)
    s = AuthorizedSession(creds)

    def ok(resp):
        if resp.status_code >= 300:
            raise SystemExit(f"{resp.request.method} {resp.url} -> {resp.status_code}: {resp.text[:400]}")
        return resp.json() if resp.content else {}

    version = ok(s.post(f"{API}/sites/{site}/versions", json={"config": hosting_config(cfg)}))["name"]
    pop = ok(s.post(f"{API}/{version}:populateFiles", json={"files": hashes}))
    required = set(pop.get("uploadRequiredHashes", []))
    by_hash = {h: files[path] for path, h in hashes.items()}
    for h in required:
        ok(s.post(f"{pop['uploadUrl']}/{h}", data=by_hash[h], headers={"Content-Type": "application/octet-stream"}))
    print(f"uploaded {len(required)} new/changed files")

    ok(s.patch(f"{API}/{version}?update_mask=status", json={"status": "FINALIZED"}))
    release = ok(s.post(f"{API}/sites/{site}/releases?versionName={version}", json={}))
    print(f"released {release.get('name', version)}")
    print(f"live at https://{site}.web.app")


if __name__ == "__main__":
    main()
