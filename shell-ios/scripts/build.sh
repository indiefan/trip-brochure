#!/bin/bash
# Build the iOS shell around the newest published content, on a Mac (see HANDBOOK.md → "The native iOS app").
#
#   scripts/build.sh trip              # build/trip/<App>.ipa, and a build/trip/<App>.xcodeproj you can open in Xcode
#   scripts/build.sh trip --upload     # ...and upload it to the depot; phones then install from the depot's /install page
#
# Needs: Xcode signed in to your Apple ID (apps/<app>/app.json names the team), xcodegen (brew install xcodegen),
# python3, and the depot reachable at app.json's "depot_lan" with content already published for this app. The newest
# published content is bundled in, so the app works offline from first launch.
set -euo pipefail
cd "$(dirname "$0")/.."
APP="${1:?usage: scripts/build.sh <app> [--upload]}"
UPLOAD="${2:-}"
CONF="apps/$APP/app.json"
[ -f "$CONF" ] || { echo "no $CONF"; exit 1; }
command -v xcodegen >/dev/null || { echo "installing xcodegen…"; brew install xcodegen; }

OUT="build/$APP"
rm -rf "$OUT"; mkdir -p "$OUT"
python3 scripts/prepare.py "$APP" "$OUT"          # web/ (newest content from the depot), shell.json, assets, project.yml

NAME=$(python3 -c "import json;print(json.load(open('$CONF'))['product'])")
(cd "$OUT" && xcodegen generate --quiet)
xcodebuild -project "$OUT/$NAME.xcodeproj" -scheme "$NAME" -configuration Release -destination "generic/platform=iOS" \
  -archivePath "$OUT/$NAME.xcarchive" -allowProvisioningUpdates archive | tail -5
cat > "$OUT/export.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>method</key><string>debugging</string><key>signingStyle</key><string>automatic</string>
<key>compileBitcode</key><false/></dict></plist>
PLIST
xcodebuild -exportArchive -archivePath "$OUT/$NAME.xcarchive" -exportOptionsPlist "$OUT/export.plist" -exportPath "$OUT/export" \
  -allowProvisioningUpdates | tail -3
IPA=$(ls "$OUT"/export/*.ipa | head -1)
echo "built $IPA"

if [ "$UPLOAD" = "--upload" ]; then
  python3 - "$CONF" "$IPA" <<'PY'
import json, sys, urllib.parse, urllib.request
conf = json.load(open(sys.argv[1])); ipa = open(sys.argv[2], "rb").read()
q = urllib.parse.urlencode({"version": conf["version"], "bundle_id": conf["bundle_id"], "title": conf["title"]})
req = urllib.request.Request(f"{conf['depot_lan']}/ipa?{q}", data=ipa, method="PUT", headers={"Content-Type": "application/octet-stream"})
out = json.load(urllib.request.urlopen(req, timeout=600))
print(f"uploaded {conf['title']} {out['version']} — install on each phone from Safari: {out['install']}")
PY
fi
