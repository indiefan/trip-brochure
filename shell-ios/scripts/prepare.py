#!/usr/bin/env python3
"""Lay out build/<app>/ for xcodegen: the shell's sources, the newest content from the depot, shell.json, the asset
catalog (icon, launch colour) and project.yml. Run by build.sh; standard library only."""

import hashlib
import json
import os
import shutil
import sys
import urllib.request

app, out = sys.argv[1], sys.argv[2]
here = os.path.dirname(os.path.abspath(__file__))
repo = os.path.dirname(here)                      # shell-ios/
conf = json.load(open(os.path.join(repo, "apps", app, "app.json")))


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as r:
        return r.read()


# the content: the depot's newest manifest and its files, checked against their hashes
status = json.loads(get(conf["depot_lan"]))
manifest = status.get("manifest")
if not manifest:
    sys.exit(f"the depot has no content for {app} yet: publish it first")
web = os.path.join(out, "web")
for name, f in manifest["files"].items():
    data = get(f"{conf['depot_lan']}/files/{f['sha256']}")
    if hashlib.sha256(data).hexdigest() != f["sha256"]:
        sys.exit(f"{name} arrived damaged")
    path = os.path.join(web, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(data)
manifest.pop("shell", None)
json.dump(manifest, open(os.path.join(web, "manifest.json"), "w"))
print(f"content {manifest['version']}: {len(manifest['files'])} files")

shutil.copytree(os.path.join(repo, "Sources"), os.path.join(out, "Sources"))
json.dump({"app": app, "title": conf["title"], "depot": status.get("public"), "background": conf["background"]},
          open(os.path.join(out, "shell.json"), "w"))

# assets: the icon (one 1024 px PNG, no transparency) and the launch screen's colour
assets = os.path.join(out, "Assets.xcassets")
os.makedirs(os.path.join(assets, "AppIcon.appiconset"))
shutil.copy(os.path.join(repo, "apps", app, "icon.png"), os.path.join(assets, "AppIcon.appiconset", "icon.png"))
json.dump({"images": [{"filename": "icon.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}], "info": {"author": "xcode", "version": 1}},
          open(os.path.join(assets, "AppIcon.appiconset", "Contents.json"), "w"))
json.dump({"info": {"author": "xcode", "version": 1}}, open(os.path.join(assets, "Contents.json"), "w"))
hexc = conf["background"].lstrip("#")
r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4))
os.makedirs(os.path.join(assets, "LaunchBackground.colorset"))
json.dump({"colors": [{"idiom": "universal", "color": {"color-space": "srgb", "components": {"red": f"{r:.3f}", "green": f"{g:.3f}", "blue": f"{b:.3f}", "alpha": "1.000"}}}],
           "info": {"author": "xcode", "version": 1}}, open(os.path.join(assets, "LaunchBackground.colorset", "Contents.json"), "w"))

template = open(os.path.join(repo, "project.yml")).read()
for k, v in {"PRODUCT": conf["product"], "BUNDLE_ID": conf["bundle_id"], "TEAM": conf["team"], "VERSION": conf["version"],
             "BUILD": manifest["version"].replace(".", ""), "TITLE": conf["title"]}.items():
    template = template.replace("${" + k + "}", str(v))
open(os.path.join(out, "project.yml"), "w").write(template)
