#!/usr/bin/env python3
"""Render icon.html (one character on a coloured field) to a 1024×1024 icon.png: python3 make-icon.py [out.png]
Needs playwright (pip install playwright && playwright install chromium). Edit icon.html for another character or colour."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
here = Path(__file__).resolve().parent
out = sys.argv[1] if len(sys.argv) > 1 else str(here / "apps" / "trip" / "icon.png")
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1024, "height": 1024})
    pg.goto((here / "icon.html").as_uri()); pg.wait_for_timeout(800)
    pg.screenshot(path=out); b.close()
from PIL import Image
Image.open(out).convert("RGB").save(out)       # no alpha: App Store icons must be opaque
print("wrote", out)
