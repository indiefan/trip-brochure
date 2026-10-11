"""The depot: where the family's phones get the app's updates. One small server, no database.

Two kinds of thing live here, per app name:
- content: the built app's files, each stored under its SHA-256, and a manifest.json naming a version and every file.
  publish.py sends only the files the depot lacks. A phone fetches manifest.json, then only the files it does not
  already have (the iOS shell does this; the web-app route uses a plain static host instead and never needs this).
- the iOS shell itself: an .ipa plus an install page (itms-services), the way development-signed apps install.

Publishing is open on the LAN (/api/depot/…): keep the port private. Phones read through a secret path
(/d/<APPS_SECRET>/<app>/…) which is what the shell bakes in, so the content is not browsable by strangers.

    APPS_SECRET=<24+ random chars> PUBLIC_URL=https://trips.example.com DEPOT_DATA=/data uvicorn server:app --port 8137
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

SECRET = os.environ.get("APPS_SECRET", "")
DATA = os.environ.get("DEPOT_DATA", "./data")
PUBLIC = os.environ.get("PUBLIC_URL", "http://localhost:8137").rstrip("/")
APP_NAME = re.compile(r"[a-z][a-z0-9-]{1,30}")
SHA = re.compile(r"[0-9a-f]{64}")
VERSION = re.compile(r"[0-9A-Za-z.\-]{1,40}")
KEEP_MANIFESTS = 5

app = FastAPI(title="depot")


def folder(name: str) -> str:
    if not APP_NAME.fullmatch(name or ""):
        raise HTTPException(400, "bad app name")
    return os.path.join(DATA, name)


def public_base(name: str) -> str:
    return f"{PUBLIC}/d/{SECRET}/{name}"


def write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".part", "wb") as f:
        f.write(data)
    os.replace(path + ".part", path)


def read_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def file_path(name: str, sha: str) -> str:
    if not SHA.fullmatch(sha or ""):
        raise HTTPException(400, "bad hash")
    return os.path.join(folder(name), "files", sha[:2], sha)


def prune(name: str) -> None:
    base = folder(name); mdir = os.path.join(base, "manifests")
    names = sorted(os.listdir(mdir), key=lambda n: os.path.getmtime(os.path.join(mdir, n)))
    for n in names[:-KEEP_MANIFESTS]:
        os.remove(os.path.join(mdir, n))
    keep = set()
    for n in os.listdir(mdir):
        keep |= {f["sha256"] for f in (read_json(os.path.join(mdir, n)) or {}).get("files", {}).values()}
    fdir = os.path.join(base, "files")
    for sub in os.listdir(fdir) if os.path.isdir(fdir) else []:
        for sha in os.listdir(os.path.join(fdir, sub)):
            if sha not in keep and not sha.endswith(".part"):
                os.remove(os.path.join(fdir, sub, sha))


# --- publishing (LAN) -------------------------------------------------------------------------------------------------

class Hashes(BaseModel):
    hashes: list[str]


@app.post("/api/depot/{name}/missing")
def missing(name: str, body: Hashes) -> dict:
    return {"missing": [h for h in dict.fromkeys(body.hashes) if SHA.fullmatch(h or "") and not os.path.exists(file_path(name, h))]}


@app.put("/api/depot/{name}/files/{sha}")
async def put_file(name: str, sha: str, request: Request) -> dict:
    data = await request.body()
    if hashlib.sha256(data).hexdigest() != sha:
        raise HTTPException(400, "content does not match its hash")
    write(file_path(name, sha), data)
    return {"ok": True}


@app.put("/api/depot/{name}/manifest")
async def put_manifest(name: str, request: Request) -> dict:
    try:
        m = json.loads(await request.body())
    except ValueError:
        raise HTTPException(400, "not JSON")
    files = m.get("files")
    if not isinstance(files, dict) or not files or not VERSION.fullmatch(str(m.get("version", ""))):
        raise HTTPException(400, "a manifest needs a version and files")
    for fname, f in files.items():
        if fname.startswith("/") or ".." in fname.split("/") or not isinstance(f, dict) or not SHA.fullmatch(f.get("sha256", "")):
            raise HTTPException(400, f"bad entry {fname!r}")
        if not os.path.exists(file_path(name, f["sha256"])):
            raise HTTPException(400, f"{fname} not uploaded yet")
    m = {**m, "app": name, "published": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    data = json.dumps(m, indent=1).encode()
    write(os.path.join(folder(name), "manifests", f"{m['version']}.json"), data)
    write(os.path.join(folder(name), "manifest.json"), data)
    prune(name)
    return {"version": m["version"], "files": len(files)}


@app.put("/api/depot/{name}/ipa")
async def put_ipa(name: str, request: Request, version: str, bundle_id: str, title: str = "") -> dict:
    data = await request.body()
    if not VERSION.fullmatch(version or "") or not re.fullmatch(r"[A-Za-z0-9.\-]{3,100}", bundle_id or "") or data[:2] != b"PK":
        raise HTTPException(400, "an ipa needs a version, a bundle id and its bytes")
    write(os.path.join(folder(name), "app.ipa"), data)
    shell = {"version": version, "bundle_id": bundle_id, "title": (title or name)[:60], "size": len(data), "uploaded": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    write(os.path.join(folder(name), "shell.json"), json.dumps(shell).encode())
    return {**shell, "install": public_base(name) + "/install"}


@app.get("/api/depot/{name}")
def status(name: str) -> dict:
    return {"manifest": manifest(name), "shell": read_json(os.path.join(folder(name), "shell.json")), "public": public_base(name)}


@app.get("/api/depot/{name}/files/{sha}")
def lan_file(name: str, sha: str):
    path = file_path(name, sha)
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="application/octet-stream")


# --- what phones read (secret path) -------------------------------------------------------------------------------------

def manifest(name: str) -> dict | None:
    m = read_json(os.path.join(folder(name), "manifest.json"))
    if m is None:
        return None
    shell = read_json(os.path.join(folder(name), "shell.json"))
    if shell:
        m["shell"] = {"version": shell["version"], "install": public_base(name) + "/install"}
    return m


def check(token: str, name: str) -> None:
    if len(SECRET) < 24 or not hmac.compare_digest(SECRET, token or "") or not APP_NAME.fullmatch(name):
        raise HTTPException(404)


@app.get("/d/{token}/{name}/manifest.json")
def get_manifest(token: str, name: str):
    check(token, name)
    m = manifest(name)
    if m is None:
        raise HTTPException(404)
    return JSONResponse(m, headers={"Cache-Control": "no-cache"})


@app.get("/d/{token}/{name}/files/{sha}")
def get_file(token: str, name: str, sha: str):
    check(token, name)
    path = file_path(name, sha)
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="application/octet-stream", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/d/{token}/{name}/install")
def install(token: str, name: str):
    check(token, name)
    s = read_json(os.path.join(folder(name), "shell.json"))
    if s is None:
        raise HTTPException(404)
    from urllib.parse import quote
    link = "itms-services://?action=download-manifest&url=" + quote(public_base(name) + "/manifest.plist", safe="")
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Install {escape(s['title'])}</title><style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f1e7;color:#1d1b18;font:17px/1.5 -apple-system,system-ui,sans-serif}}
main{{max-width:340px;padding:32px 24px;text-align:center}}h1{{font:600 30px/1.15 ui-serif,Georgia,serif;margin:0 0 6px}}p{{color:#6b645a;margin:0 0 26px}}
a{{display:block;background:#1d1b18;color:#f6f1e7;text-decoration:none;font-weight:600;padding:15px;border-radius:14px}}small{{display:block;margin-top:22px;color:#8b8478;font-size:13px}}</style></head>
<body><main><h1>{escape(s['title'])}</h1><p>Version {escape(s['version'])}</p><a href="{escape(link)}">Install</a>
<small>Open this page in Safari on the iPhone or iPad. If iOS says it cannot verify the developer, trust it under Settings → General → VPN &amp; Device Management.</small></main></body></html>""",
                        headers={"Cache-Control": "no-cache"})


@app.get("/d/{token}/{name}/manifest.plist")
def plist(token: str, name: str):
    check(token, name)
    s = read_json(os.path.join(folder(name), "shell.json"))
    if s is None:
        raise HTTPException(404)
    url = escape(public_base(name) + f"/app.ipa?v={s['version']}")
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>items</key><array><dict>
<key>assets</key><array><dict><key>kind</key><string>software-package</string><key>url</key><string>{url}</string></dict></array>
<key>metadata</key><dict><key>bundle-identifier</key><string>{escape(s['bundle_id'])}</string><key>bundle-version</key><string>{escape(s['version'])}</string>
<key>kind</key><string>software</string><key>title</key><string>{escape(s['title'])}</string></dict>
</dict></array></dict></plist>
"""
    return Response(body, media_type="text/xml", headers={"Cache-Control": "no-cache"})


@app.get("/d/{token}/{name}/app.ipa")
def ipa(token: str, name: str):
    check(token, name)
    path = os.path.join(folder(name), "app.ipa")
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="application/octet-stream", headers={"Cache-Control": "no-cache"})


@app.get("/")
def home() -> dict:
    return {"depot": "ok", "apps": sorted(n for n in os.listdir(DATA) if APP_NAME.fullmatch(n)) if os.path.isdir(DATA) else []}
