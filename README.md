# Storyroom — documentary editor

Release: **V28 · 24 November 2026** (`2026-11-24-clean-header-v28`)

A local, script-driven documentary editor (Python + FFmpeg). It runs on your own
computer at http://127.0.0.1:8004 and never uploads your footage anywhere.

## Start it

Double-click `START_UPDATED_STORYROOM_8004.bat`.

The first start creates a private Python environment (`.venv`) and installs the
libraries. Every start after that checks the libraries again and installs anything
missing, then opens the editor in your browser.

Manual install (any OS), from this folder:

```
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -c requirements-constraints.txt
.venv/Scripts/python verified_launch.py
```

(On macOS/Linux use `.venv/bin/python`.) Always pass `-c requirements-constraints.txt`:
it stops pip from installing the desktop build of OpenCV, which breaks the editor.

## Make a film

1. **＋ New** → name the production.
2. **Setup** → upload the production script, the narration SRT, the narration audio,
   and the footage/photos the script names. The storyboard builds itself.
   A guide, a worked example and a footage sheet are in `production-script-templates/`.
3. **Transitions** → **Auto Suggest** reads every picture cut (speaker changes, time
   jumps, places, reveals, grief, photos arriving) and picks a fitting transition,
   never the same one twice in a row. Change any cut by hand; your choices are kept.
4. **Setup → Featured case people** → add people and their photos. Each photo gets its
   own professional move selected by the Still & photo motion director. Uploaded
   photos, double-photo/Pixmix collages, approved photo-carrier clips and verified
   still intervals receive the same motion system.
5. **Shot Inspector → Channel CTA card** → upload your card. It starts large and centred.
   Use **Opacity** to let the footage show through, and **Move / resize on video** to
   drag it into place or drag any corner to make it bigger or smaller.
6. **Render MP4** → choose 1080p, 2K or 4K. Render again after any change.

## Automatic photo presentation

Every supported still picture is automatically kept whole inside one centred white
frame, placed over a darkened blurred copy with a soft shadow. This includes single
photos, double-photo/Pixmix collages, approved `P##_..._video` photo carriers and
verified static-image intervals from clips. The same composition and selected motion
appear in the monitor and the final rendered MP4. Already-framed Storyroom images are
preserved to avoid a second border. Original source files and source timing are not
changed.

Use the normal **Setup → Case footage & photos → Upload footage or photos** control.
No separate photo preprocessing or one-by-one conversion is required.

## Editor header

Use the back arrow to return to the homepage and choose or create a production. The
duplicate **Projects** button has been removed from the editor header. The production
button reads **Setup** while the timeline is empty and changes to **Edit** after the
current production has timeline material.

## Required libraries

Flask, PyAV (`av`), OpenCV (headless), Pillow, imageio-ffmpeg, psutil and numpy.
PyAV measures every video exactly (frame rate, frame count, timestamps), decodes
sound-bite audio, measures music, and checks the finished MP4 before it is published.

If one is missing, a yellow bar appears at the top of the editor with a
**Repair now** button. You can also run `python dependencies.py` from this folder with
the `.venv` Python.

## Updating

Run `UPDATE_EXISTING_STORYROOM.cmd` from the update package and choose this folder.
It verifies every file, backs up your code, copies the new version in, and installs any
new libraries. Projects, footage and renders are never touched.

## Checks

`RUN_STORYROOM_PREFLIGHT.cmd` checks the installation. `python -m pytest tests` runs the
test suite (needs the same libraries).
