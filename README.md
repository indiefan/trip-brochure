# Trip Brochure

An offline itinerary app for a family trip, built as a static web page that looks like a printed travel brochure, with
every confirmation built in, and shipped to phones as a web app (Android, iPhone, iPad; no developer account) or as a
native iOS app (Xcode, over-the-air updates).

**Start with [HANDBOOK.md](HANDBOOK.md).** It is the whole story: a tour of the app with screenshots, how to run the
sample in five minutes, how to describe your own trip, which optional pieces need which keys, and step-by-step
instructions for getting it onto phones, including installing Xcode and setting up an Apple developer account.

```
app/          the app itself (index.html, app.css, app.js, sw.js, fonts)        — edit to restyle
build.py      trip folder → dist/ (resizes photos, renders documents, writes data.js + manifest.json)
sample/       a complete sample trip (trip.json, photos, documents): build it, open it, copy it
pipeline/     optional: Claude writes the copy and translates emails; Google Maps pins the exact places
depot/        optional: a small update server (Docker) for the native iOS route
shell-ios/    optional: the native iOS shell (Swift + xcodegen) and its Mac build script
docs/         screenshots used by the handbook
```

Quick start (Python 3.10+):

```
pip install pillow pymupdf beautifulsoup4 requests
python3 build.py sample/
cd sample/dist && python3 -m http.server 8000     # open http://localhost:8000 — narrow the window to phone width
```
