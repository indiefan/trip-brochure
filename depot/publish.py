#!/usr/bin/env python3
"""Publish a folder of web content to the depot as a new version (only files the depot lacks are sent).

    python3 depot/publish.py <app> <folder> [--depot http://depot.local:8137] [--version V]

The folder needs an index.html; everything it uses must be inside it, by relative URL. Phones running the app's
shell pick the new version up the next time they open it (or on pull-to-refresh). Standard library only.
"""

import argparse
import hashlib
import json
import os
import time
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("app"); ap.add_argument("folder")
ap.add_argument("--depot", default=os.environ.get("DEPOT_URL", "http://localhost:8137"))
ap.add_argument("--version", default=time.strftime("%Y%m%d.%H%M%S", time.gmtime()))
a = ap.parse_args()


def call(method, path, body=None, ctype="application/json"):
    req = urllib.request.Request(f"{a.depot}/api/depot/{a.app}{path}", data=body, method=method, headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


files = {}
for d, _, names in os.walk(a.folder):
    for n in names:
        p = os.path.join(d, n)
        rel = os.path.relpath(p, a.folder).replace(os.sep, "/")
        if rel == "manifest.json" or n.startswith("."):
            continue
        files[rel] = p
if "index.html" not in files:
    raise SystemExit("the folder has no index.html")
manifest = {"version": a.version, "entry": "index.html", "files": {}}
by_hash = {}
for rel, p in sorted(files.items()):
    data = open(p, "rb").read()
    h = hashlib.sha256(data).hexdigest()
    manifest["files"][rel] = {"sha256": h, "size": len(data)}
    by_hash[h] = p
missing = call("POST", "/missing", json.dumps({"hashes": list(by_hash)}).encode())["missing"]
for h in missing:
    call("PUT", f"/files/{h}", open(by_hash[h], "rb").read(), "application/octet-stream")
out = call("PUT", "/manifest", json.dumps(manifest).encode())
print(f"published {a.app} {out['version']}: {len(missing)} new of {len(by_hash)} files")
