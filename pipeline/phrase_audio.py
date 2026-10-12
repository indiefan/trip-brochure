#!/usr/bin/env python3
"""The phrasebook's sound: each phrase in phrases.json said by Gemini's text-to-speech in its language's own voice,
checked by ear (another Gemini model listens), and kept as small AAC files the app plays offline.

    export GEMINI_API_KEY=…                      # aistudio.google.com → Get API key
    python3 pipeline/phrase_audio.py mytrip/     # only phrases without sound yet; --force for all

Two recordings per phrase: said naturally, and said slowly with every sound exaggerated, for learning. Written to
mytrip/audio/: <key>.m4a (natural: played on the card you hold up for someone) and <key>-learn.m4a (natural, slow,
natural again, with short pauses: played when the phrase is tapped). phrases.json gets each file's path. Needs
ffmpeg (brew install ffmpeg). A recording the listener rejects is made again, twice at most, the last in another voice.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import httpx

TTS = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
JUDGE = os.environ.get("GEMINI_JUDGE_MODEL", "gemini-3.6-flash")
INTERACTIONS = "https://generativelanguage.googleapis.com/v1beta/interactions"
# The voice and where the speaker is from, per language; any other language gets a neutral standard accent, unless
# phrases.json gives the language a "voice_style" (phrases.py writes one for the place you are going: Mexican Spanish).
VOICES = {
    "ja": ("Leda", "from Tokyo, natural standard Japanese"), "ko": ("Kore", "from Seoul, natural standard Seoul Korean"),
    "zh": ("Leda", "from Beijing, natural standard Mandarin"), "th": ("Kore", "from Bangkok, natural standard Thai"),
    "vi": ("Kore", "from Hanoi, natural northern Vietnamese"), "fr": ("Aoede", "from Paris, natural standard French"),
    "es": ("Aoede", "from Madrid, natural standard Spanish"), "it": ("Aoede", "from Rome, natural standard Italian"),
    "de": ("Kore", "from Berlin, natural standard German"), "pt": ("Aoede", "from Lisbon, natural European Portuguese"),
    "el": ("Kore", "from Athens, natural standard Greek"),
}
STYLES: dict[str, str] = {}      # a language's own speaking style, from phrases.json ("voice_style", as phrases.py writes)
SLOW = ("speaking very slowly, syllable by syllable, exaggerating the pronunciation of every sound clearly so a learner "
        "can hear and copy each one, with a small pause between words, still natural and kind")


def say(*a):
    print(*a, file=sys.stderr, flush=True)


def style(lang: str, name: str, slow: bool) -> str:
    pace = SLOW if slow else "speaking clearly and a little slowly"
    if STYLES.get(lang):                                     # "a native Spanish speaker from Mexico City, …, speaking clearly and a little slowly, …"
        return STYLES[lang].replace("speaking clearly and a little slowly", pace)
    where = VOICES.get(lang, ("Kore", f"natural standard {name}"))[1]
    return f"a native {name} speaker {where}, warm and polite, {pace}, as if helping a visitor"


def speak(key: str, text: str, lang: str, name: str, slow: bool, voice: str | None, http: httpx.Client) -> bytes:
    r = http.post(INTERACTIONS, headers={"x-goog-api-key": key}, timeout=120, json={
        "model": TTS, "response_modalities": ["audio"],
        "input": [{"type": "text", "text": text, "annotations": [{"type": "speech_metadata", "style": style(lang, name, slow)}]}],
        "generation_config": {"speech_config": [{"voice": voice or VOICES.get(lang, ("Kore",))[0]}]}})
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini text-to-speech failed ({r.status_code}): {r.text[:200]}")
    def find(x):
        if isinstance(x, dict):
            if isinstance(x.get("data"), str) and ("mime_type" in x or "mimeType" in x):
                return base64.b64decode(x["data"]), x.get("mime_type") or x.get("mimeType") or ""
            x = list(x.values())
        if isinstance(x, list):
            for v in x:
                got = find(v) if isinstance(v, (dict, list)) else None
                if got:
                    return got
        return None
    got = find(r.json())
    if not got:
        raise RuntimeError("Gemini answered without audio")
    data, mime = got
    if not data.startswith(b"RIFF"):
        rate = int((re.search(r"rate=(\d+)", mime) or [None, "24000"])[1])
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(data)
        data = buf.getvalue()
    return data


def ffmpeg(args: list[str], stdin: bytes | None = None) -> None:
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-y"] + args, input=stdin, capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr.decode(errors="replace")[:200])


def aac(wav: bytes, out: Path) -> bytes:
    ffmpeg(["-f", "wav", "-i", "pipe:0", "-af", "silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse,apad=pad_dur=0.15",
            "-ac", "1", "-ar", "44100", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)], wav)
    return out.read_bytes()


def check(key: str, clip: bytes, text: str, name: str, slow: bool, http: httpx.Client) -> dict:
    how = " slowly and with exaggerated pronunciation, for a learner," if slow else ""
    prompt = (f"This audio should be a native {name} speaker saying{how} exactly: 「{text}」. Listen carefully. Answer as JSON: "
              "{\"heard\": what is said, in the language's own script; \"match\": true when it is that phrase with natural pronunciation "
              "and nothing else spoken, else false; \"note\": a short reason when false}.")
    r = http.post(f"https://generativelanguage.googleapis.com/v1beta/models/{JUDGE}:generateContent", headers={"x-goog-api-key": key}, timeout=120, json={
        "contents": [{"parts": [{"inlineData": {"mimeType": "audio/mp4", "data": base64.b64encode(clip).decode()}}, {"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"}})
    try:
        return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    except Exception:                                                    # noqa: BLE001
        return {"match": None, "note": f"check failed ({r.status_code})"}


def recording(key: str, text: str, lang: str, name: str, slow: bool, tmp: Path, http: httpx.Client) -> tuple[bytes, dict]:
    best = None
    for attempt, voice in enumerate([None, None, "Aoede" if VOICES.get(lang, ("Kore",))[0] != "Aoede" else "Kore"]):
        clip = aac(speak(key, text, lang, name, slow, voice, http), tmp / f"{'s' if slow else 'n'}{attempt}.m4a")
        c = check(key, clip, text, name, slow, http); c["attempt"] = attempt + 1
        if best is None or (c.get("match") and not best[1].get("match")):
            best = (clip, c)
        if c.get("match") is not False:
            break
        say(f"    {'slow' if slow else 'natural'} attempt {attempt + 1}: {c.get('note')}")
    return best


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("trip"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    key = os.environ.get("GEMINI_API_KEY") or sys.exit("set GEMINI_API_KEY (aistudio.google.com → Get API key)")
    root = Path(a.trip).resolve()
    path = root / "phrases.json"
    book = json.loads(path.read_text(encoding="utf-8"))
    (root / "audio").mkdir(exist_ok=True)
    STYLES.update({lang: info["voice_style"] for lang, info in book["languages"].items() if info.get("voice_style")})
    http = httpx.Client(timeout=120)
    for sec in book["sections"]:
        for ph in sec["phrases"]:
            for lang, info in book["languages"].items():
                x = ph.get(lang)
                if not x:
                    continue
                if isinstance(x, list):                                    # ["text", "roman", "note"] → an object
                    x = ph[lang] = {"text": x[0], "roman": x[1] if len(x) > 1 else "", **({"note": x[2]} if len(x) > 2 else {})}
                if x.get("learn") and not a.force and (root / x["learn"]).exists():
                    continue
                k = hashlib.sha1(f"{TTS}|{lang}|{x['text']}".encode()).hexdigest()[:16]
                say(f"  {lang} {x['text']}")
                with tempfile.TemporaryDirectory() as t:
                    tmp = Path(t)
                    normal, nc = recording(key, x["text"], lang, info["name"], False, tmp, http)
                    slow, sc = recording(key, x["text"], lang, info["name"], True, tmp, http)
                    (tmp / "n.m4a").write_bytes(normal); (tmp / "s.m4a").write_bytes(slow)
                    out = root / "audio" / f"{k}-learn.m4a"
                    ffmpeg(["-i", str(tmp / "n.m4a"), "-i", str(tmp / "s.m4a"), "-filter_complex",
                            "anullsrc=r=44100:cl=mono,atrim=0:0.7[p1];anullsrc=r=44100:cl=mono,atrim=0:0.7[p2];[0:a]asplit=2[n1][n2];[n1][p1][1:a][p2][n2]concat=n=5:v=0:a=1[o]",
                            "-map", "[o]", "-ac", "1", "-ar", "44100", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(out)])
                (root / "audio" / f"{k}.m4a").write_bytes(normal)
                x["audio"], x["learn"] = f"audio/{k}.m4a", f"audio/{k}-learn.m4a"
                if nc.get("match") is False or sc.get("match") is False:
                    say(f"    the listener was not sure: {nc.get('note') or sc.get('note')} — have a listen")
                path.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    say("phrase audio: done")


if __name__ == "__main__":
    main()
