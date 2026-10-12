#!/usr/bin/env python3
"""Design the trip's app: a designer agent gives it its name, its icon, its colours and its cover words.

    export ANTHROPIC_API_KEY=…
    pip install anthropic playwright pillow && playwright install chromium
    python3 pipeline/design.py mytrip/                        # writes mytrip/icon.png and the design into trip.json
    python3 pipeline/design.py mytrip/ --shell-app trip       # also shell-ios/apps/trip/icon.png and its app.json name
    python3 pipeline/design.py mytrip/ --again                # reconsider an earlier design (after the trip changed)

Claude studies the trip (where, when, what is planned, who is going) and works like a designer at a desk: it draws
three different icon concepts as SVG, sees them rendered side by side and at real size on an iPhone home screen,
judges them by four tests (reads in a blink at 60 pt; unmistakably this trip, not a weather or banking app; crafted;
holds its own beside the finest apps), refines the strongest, and hands over: the app's name (app.title, at most 12
characters), the trip's title and the cover's title_html, a seal in the local script, the opening line (intro, with
{nights} and {cities} filled in by the app), a send-off in the local language (farewell), the accent colour for light
and dark mode, a colour per city, and which event's photograph makes the cover (cover_match). Everything it is told
about taste is the house style (style.py). It takes three to five minutes and costs roughly $1–3 with Claude Opus.

Look at icon.png and the words before you build; run it again (or edit trip.json) if something is off. With --again,
the designer sees its earlier design and keeps the icon and names unless they now misrepresent the trip (a new
icon or name means reinstalling the native app); the words and colours are brought up to date either way.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MODEL, Trip, claude, say                                     # noqa: E402
from style import HOUSE                                                         # noqa: E402

MAX_RENDERS = 8
PAPER, PAPER_DARK = "#f4efe6", "#15130f"


def _svg(svg: str) -> str:
    """The designer's SVG, filling its box whatever size it says."""
    svg = svg.strip()
    svg = re.sub(r"^<\?xml[^>]*>\s*", "", svg)
    return re.sub(r"<svg\b([^>]*)>", lambda m: "<svg" + re.sub(r'\s(width|height)="[^"]*"', "", m.group(1)) + ' width="100%" height="100%">', svg, count=1)


def _shoot(html: str, width: int, height: int, scale: float = 1.0) -> bytes:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=scale).new_page()
            page.set_content(html, wait_until="networkidle", timeout=30000)
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(150)
            return page.screenshot(type="png")
        finally:
            browser.close()


def render_icon(svg: str, size: int) -> bytes:
    """The icon as the app gets it: square, opaque, `size` px."""
    return _shoot(f"<!doctype html><html><body style='margin:0;background:#000;width:{size}px;height:{size}px;overflow:hidden'>{_svg(svg)}</body></html>", size, size)


HOME = """<!doctype html><html><head><style>
body{{margin:0;width:390px;height:150px;overflow:hidden;font:500 12px/1.2 -apple-system,"Inter","Helvetica Neue",Arial,sans-serif;
background:radial-gradient(120% 140% at 15% 0%,{w1},{w2} 55%,{w3});display:flex;gap:27px;justify-content:center;padding-top:22px;box-sizing:border-box}}
.a{{width:64px;text-align:center;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.35)}}
.i{{width:64px;height:64px;border-radius:14.4px;overflow:hidden;margin-bottom:5px;box-shadow:0 1px 3px rgba(0,0,0,.18)}}
.i svg{{display:block}} .l{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.g1{{background:linear-gradient(#5ac8fa,#007aff)}} .g2{{background:linear-gradient(#fff,#e5e5ea)}} .g3{{background:linear-gradient(#34c759,#248a3d)}}
</style></head><body>
<div class="a"><div class="i g1"></div><div class="l">Weather</div></div>
<div class="a"><div class="i">{svg}</div><div class="l">{label}</div></div>
<div class="a"><div class="i g2"></div><div class="l">Photos</div></div>
<div class="a"><div class="i g3"></div><div class="l">Messages</div></div>
</body></html>"""


def render_home(svg: str, label: str, dark: bool = False) -> bytes:
    """The icon at its real size among others on an iPhone home screen (3x), its name under it as iOS shows it."""
    from html import escape
    w = ("#1c2331", "#2b2f45", "#121418") if dark else ("#f3c9a6", "#c98a9a", "#6f6fa8")
    return _shoot(HOME.format(svg=_svg(svg), label=escape(label or ""), w1=w[0], w2=w[1], w3=w[2]), 390, 150, 3)


SHEET = """<!doctype html><html><head><style>
body{{margin:0;background:#e9e4da;font:600 22px -apple-system,"Inter",Arial,sans-serif;color:#555}}
.g{{display:flex;flex-wrap:wrap;gap:24px;padding:24px;width:{w}px}} .c{{width:400px}} .c div{{width:400px;height:400px;overflow:hidden}} .c p{{margin:8px 0 0}}
</style></head><body><div class="g">{cells}</div></body></html>"""

ROW = """<!doctype html><html><head><style>
body{{margin:0;width:{w}px;height:150px;overflow:hidden;font:500 12px/1.2 -apple-system,"Inter","Helvetica Neue",Arial,sans-serif;
background:radial-gradient(120% 140% at 15% 0%,#f3c9a6,#c98a9a 55%,#6f6fa8);display:flex;gap:27px;justify-content:center;padding-top:22px;box-sizing:border-box}}
.a{{width:64px;text-align:center;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.35)}}
.i{{width:64px;height:64px;border-radius:14.4px;overflow:hidden;margin-bottom:5px;box-shadow:0 1px 3px rgba(0,0,0,.18)}} .i svg{{display:block}}
.l{{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
</style></head><body>{cells}</body></html>"""


def render_sheet(svgs: list[str]) -> bytes:
    """Several drafts side by side at 400 px, numbered: for choosing between concepts."""
    cells = "".join(f'<div class="c"><div>{_svg(x)}</div><p>{i}</p></div>' for i, x in enumerate(svgs, 1))
    w = 24 + 424 * min(len(svgs), 2)
    return _shoot(SHEET.format(cells=cells, w=w), w, 24 + 470 * ((len(svgs) + 1) // 2), 1)


def render_row(svgs: list[str], label: str) -> bytes:
    """Several drafts at real size on a home screen, each with the name under it (3x)."""
    from html import escape
    cells = "".join(f'<div class="a"><div class="i">{_svg(x)}</div><div class="l">{i} {escape(label or "")}</div></div>' for i, x in enumerate(svgs, 1))
    w = max(390, 91 * len(svgs) + 40)
    return _shoot(ROW.format(cells=cells, w=w), w, 150, 3)


def _small(png: bytes, width: int) -> bytes:
    """A render cut down for the designer's eyes (fewer tokens, same judgement)."""
    import io
    try:
        from PIL import Image
    except ImportError:
        return png
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return out.getvalue()


BRIEF = """You are the designer of a family's private iPhone travel app: one app per trip, made for this trip alone. \
Today is {today}.

""" + HOUSE + """

THE TRIP
{facts}

{current}WHAT TO DESIGN
1. The app icon: an SVG, viewBox="0 0 1024 1024", that fills the square edge to edge with an opaque background (iOS \
rounds the corners itself: keep everything that matters inside the middle 820 px). One memorable idea that could only \
be this trip: a motif, a landscape reduced to its essence, a local emblem, a play on the destination's script or \
colours. Refined and confident, like a great app icon or a luxury hotel's monogram: flat or gently dimensional, a \
deliberate palette of two to four colours, nothing fussy. It must read instantly at 60 pt among other icons: no thin \
lines (strokes under 10 px vanish), no small details, no clip-art, no emoji, no photographs, no generic globe, \
suitcase, plane or pin. Text only if it is the idea itself (one bold glyph or a very short word), never a caption. \
For a glyph you may load a Google Font with <style>@import url('https://fonts.googleapis.com/css2?family=…');</style> \
inside the SVG.
2. Its name: `app_title`, the label under the icon on the home screen (at most 12 characters, so iOS never cuts it), \
and `title`, the trip's name in lists and on the cover ("Maui", "Paris & London", "Iceland"); `product`, the app's \
internal name, letters only in CamelCase ending in Trip ("MauiTrip").
3. The brochure's words and colours: `title_html`, the cover's title with <i>…</i> on one word or the ampersand for \
an italic accent and <br> where the line should break (only those two tags; e.g. "Japan <i>&amp;</i><br>Korea"); \
`seal`, one character or a very short word in the destination's own script or language, set like a stamp in the \
cover's corner (旅 for Japan: "journey"), or "" when nothing is apt; `intro`, the brochure's first sentence or two \
about the arc of this trip, in the house voice, using only facts given (it may use {{nights}} and {{cities}}, which \
the app fills in with numbers, as in "{{nights}} nights, {{cities}} cities", and <em> on one place name; places are named \
as English speakers name them); more may still be booked, so write it to stay true as the trip fills \
in (no claims about proportions or about what is not planned); `farewell_native`, a send-off as locals would say it to someone \
setting out (いってらっしゃい), "" where English is spoken, and `farewell_english` ("Have a wonderful trip."); \
`accent`, the one accent colour (links, buttons, the seal; at least 4.5:1 on the paper {paper}) and \
`accent_dark` (the same hue lighter, at least 4.5:1 on {paper_dark}); `colors`, one muted, distinct colour per \
stop and one for {home}, harmonious with the accent, each dark enough for white text on it (4.5:1), keyed by the \
stop names exactly as given under "Stop names"; `cover_match`, a few words from the title of the event whose photograph should be the cover \
(the trip's most iconic image, ideally a tall subject), or ""; `why`, two sentences on the idea.

HOW TO WORK
First explore: draw three genuinely different concepts (different ideas, not variations of one) and `render` them \
together, which shows them side by side at full size and at real size on a home screen with the name. Judge them \
hard, as a demanding art director would, by four tests: (1) at 60 pt, does it read in a blink? (2) would someone who \
knows the place feel it is this trip, or could it pass for a weather, swimming, music or banking app? If it could, \
it is not distinctive enough; (3) is it crafted: proportions, optical balance, the drawing of every curve, a \
confident palette? (4) would it hold its own beside the finest apps on a home screen? Choose the strongest, then \
refine it alone, rendering after each change, until it passes all four (at most {renders} renders in all). Then call \
`finish` once, with the final SVG exactly as last rendered."""

CURRENT = """THE CURRENT DESIGN (the family may already have this app on their phones)
{theme}
The trip's places have changed since it was made. Keep the icon and the names (finish with keep=true, the current \
svg, title, app_title and product) unless they now misrepresent the trip, e.g. they name or depict one country of a \
trip that now spans two; changing them means a new app install. The words and colours (title_html, seal, intro, \
farewell, accent, colors, cover_match) cost nothing to change: bring them up to date with the trip either way. You \
need not render when you keep the icon.

"""

FINISH_FIELDS = {
    "keep": {"type": "boolean", "description": "true: the current design still fits; nothing changes"},
    "svg": {"type": "string", "description": "the final icon SVG, exactly as last rendered"},
    "title": {"type": "string"}, "app_title": {"type": "string"}, "product": {"type": "string"}, "title_html": {"type": "string"},
    "seal": {"type": "string"}, "intro": {"type": "string"}, "farewell_native": {"type": "string"}, "farewell_english": {"type": "string"},
    "accent": {"type": "string"}, "accent_dark": {"type": "string"},
    "colors": {"type": "object", "additionalProperties": {"type": "string"}, "description": "stop name → #rrggbb"},
    "cover_match": {"type": "string"}, "why": {"type": "string"},
}
TOOLS = [
    {"name": "render", "description": "Render one to four icon drafts: returns them at full size (numbered) and at real size on an iPhone home screen with the name.",
     "input_schema": {"type": "object", "properties": {"svgs": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4},
                                                       "app_title": {"type": "string", "description": "the label to show under it"}},
                      "required": ["svgs", "app_title"]}},
    {"name": "finish", "description": "Hand over the finished design.",
     "input_schema": {"type": "object", "properties": FINISH_FIELDS, "required": list(FINISH_FIELDS)}},
]


def facts(t: Trip) -> str:
    d = t.data
    home = d.get("home") or "home"
    lines = [f"Working name: {d.get('name', 'the trip')}", f"Dates: {d['start']} to {d['end']}",
             f"Travellers: {', '.join(d.get('people') or [])} ({d.get('family') or 'a family'}), from {home}"]
    if t.hotels:
        lines.append("Stays so far: " + "; ".join(f"{h['city']}{', ' + h['country'] if h.get('country') else ''} "
                                                  f"({(date.fromisoformat(h['end']) - date.fromisoformat(h['start'])).days} nights, {h.get('name', '')})" for h in t.hotels))
    cities = list(dict.fromkeys(h["city"] for h in t.hotels)) or list(d.get("cities") or {})
    lines.append("Stop names: " + "; ".join(cities + [home]))
    plans = [f"{e['date']} {e['title']}" + (f" ({e['place']})" if e.get("place") else "") for e in t.events][:40]
    lines.append("Plans:\n" + "\n".join("  - " + p for p in plans))
    return "\n".join(lines)


def _check_colour(c: str) -> bool:
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", c or ""))


def _problems(out: dict, renders: int) -> list[str]:
    p = []
    if renders == 0:
        p.append("render the icon at least once before finishing")
    if "<svg" not in (out.get("svg") or ""):
        p.append("svg must be the icon's SVG")
    if not (out.get("app_title") or "").strip() or len(out["app_title"].strip()) > 14:
        p.append("app_title must be 1 to 12 characters")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,30}", out.get("product") or ""):
        p.append("product must be letters (CamelCase), e.g. MauiTrip")
    for k in ("accent", "accent_dark"):
        if not _check_colour(out.get(k)):
            p.append(f"{k} must be #rrggbb")
    bad = [k for k, v in (out.get("colors") or {}).items() if not _check_colour(v)]
    if bad:
        p.append("colors must be #rrggbb: " + ", ".join(bad))
    if re.search(r"<(?!/?(i|br)\b)[a-z]", out.get("title_html") or "", re.I):
        p.append("title_html may use only <i> and <br>")
    return p


def design(t: Trip, client, current: dict | None) -> dict:
    """Run the designer to its finish; returns the finish tool's input (plus 'renders')."""
    cur = ""
    if current:
        cur = CURRENT.format(theme=json.dumps({k: v for k, v in current.items() if k != "svg"}, ensure_ascii=False, indent=1)) + \
            (f"Its icon SVG:\n{current.get('svg', '')[:6000]}\n\n" if current.get("svg") else "")
    prompt = BRIEF.format(today=date.today().isoformat(), facts=facts(t), current=cur, paper=PAPER, paper_dark=PAPER_DARK,
                          home=t.data.get("home") or "home", renders=MAX_RENDERS)
    messages: list = [{"role": "user", "content": prompt}]
    renders = 0
    for _ in range(MAX_RENDERS + 5):
        with client.messages.stream(model=MODEL, max_tokens=32000, thinking={"type": "adaptive"}, tools=TOOLS, messages=messages) as stream:
            r = stream.get_final_message()
        messages.append({"role": "assistant", "content": r.content})
        uses = [b for b in r.content if getattr(b, "type", "") == "tool_use"]
        if not uses:
            messages.append({"role": "user", "content": "Use the tools: render your drafts, then finish."})
            continue
        results = []
        for u in uses:
            if u.name == "finish":
                out = dict(u.input)
                problems = [] if (out.get("keep") and current) else _problems(out, renders)
                if not problems:
                    return {**out, "renders": renders}
                results.append({"type": "tool_result", "tool_use_id": u.id, "is_error": True, "content": "Not finished yet: " + "; ".join(problems)})
            elif u.name == "render" and renders >= MAX_RENDERS:
                results.append({"type": "tool_result", "tool_use_id": u.id, "is_error": True, "content": "No renders left: finish with your best draft now."})
            elif u.name == "render":
                renders += 1
                svgs = [x for x in (u.input.get("svgs") or []) if x][:4]
                say(f"  render {renders}: {len(svgs)} draft{'s' if len(svgs) != 1 else ''}")
                try:
                    if len(svgs) == 1:
                        full, home = _small(render_icon(svgs[0], 1024), 512), _small(render_home(svgs[0], u.input.get("app_title", "")), 780)
                    else:
                        full, home = _small(render_sheet(svgs), 900), _small(render_row(svgs, u.input.get("app_title", "")), 900)
                    img = lambda b: {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(b).decode()}}   # noqa: E731
                    results.append({"type": "tool_result", "tool_use_id": u.id, "content": [
                        {"type": "text", "text": f"Render {renders} of at most {MAX_RENDERS}. Full size:"}, img(full),
                        {"type": "text", "text": "On a home screen, real size (60 pt at 3x), with its name:"}, img(home)]})
                except Exception as e:                                       # noqa: BLE001 - a broken SVG: say so, let it fix it
                    results.append({"type": "tool_result", "tool_use_id": u.id, "is_error": True, "content": f"Could not render it: {type(e).__name__}: {str(e)[:300]}"})
            else:
                results.append({"type": "tool_result", "tool_use_id": u.id, "is_error": True, "content": "no such tool"})
        messages.append({"role": "user", "content": results})
    sys.exit("the designer did not finish")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("trip")
    ap.add_argument("--again", action="store_true", help="reconsider the design already in trip.json")
    ap.add_argument("--shell-app", help="also write shell-ios/apps/<name>/icon.png and the name into its app.json")
    a = ap.parse_args()
    t = Trip(a.trip)
    d0 = t.data
    current = ({**d0["design"], **{k: d0.get(k) for k in ("title_html", "seal", "intro", "farewell", "accent", "accent_dark", "cover_match")},
                "colors": {k: v.get("color") for k, v in (d0.get("cities") or {}).items() if v.get("color")}} if a.again and d0.get("design") else None)
    say("designing… (three to five minutes)")
    out = design(t, claude(), current)
    d = t.data
    if out.get("keep") and current:
        say("kept the icon and names; words and colours brought up to date")
    else:
        icon = render_icon(out["svg"], 1024)
        (t.dir / "icon.png").write_bytes(icon)
        d["name"] = out["title"].strip()
        d.setdefault("app", {}).update({"title": out["app_title"].strip()[:14], "product": out["product"]})
        d["design"] = {"svg": out["svg"], "why": out.get("why", "").strip(), "title": out["title"].strip(), "app_title": out["app_title"].strip(), "product": out["product"]}
        if a.shell_app:
            shell = Path(__file__).resolve().parent.parent / "shell-ios" / "apps" / a.shell_app
            shell.mkdir(parents=True, exist_ok=True)
            (shell / "icon.png").write_bytes(icon)
            conf = json.loads((shell / "app.json").read_text()) if (shell / "app.json").exists() else {}
            conf.update({"title": d["app"]["title"], "product": out["product"]})
            (shell / "app.json").write_text(json.dumps(conf, indent=2, ensure_ascii=False))
            say(f"  wrote {shell}/icon.png and app.json (bump its version to install the new name or icon)")
    d.update({"title_html": out["title_html"].strip(), "seal": out["seal"].strip(), "intro": out["intro"].strip(),
              "farewell": {"native": out["farewell_native"].strip(), "english": out["farewell_english"].strip()},
              "accent": out["accent"], "accent_dark": out["accent_dark"], "cover_match": out.get("cover_match", "").strip()})
    cities = d.setdefault("cities", {})
    names = list(dict.fromkeys([h["city"] for h in t.hotels] + list(cities)))
    for k, v in (out.get("colors") or {}).items():
        hit = next((n for n in names if k.strip().lower() == n.lower() or k.strip().lower().startswith(n.lower())), None) or k.split(",")[0].strip()
        cities.setdefault(hit, {})["color"] = v
    t.save()
    say(f"designed “{d['name']}” ({out.get('renders')} renders): {out.get('why', '')}")
    say(f"look at {t.dir / 'icon.png'}, then build")


if __name__ == "__main__":
    main()
