# v17 — Centred, clean stills and the new name graphic

Build `2026-11-22-centred-stills-v17`. Narration audio, SRT timing, sound-bite audio,
Beat parsing and the film-master clock are unchanged. The interview picture-cutaway format
and its checks are unchanged.

## What changed

1. **Every still sits in the middle.** Person photos and cutaway pictures are fitted whole
   and centred, over a blurred, darkened copy of the same photo. The old layout that pushed
   a first-appearance photo to the right is gone, and so are the left/right card positions.
2. **News screen grabs are cleaned.** `clean_photo_framing.detect_box` finds the sharp
   photo inside a grab by its straight edges and the flat (black, plain or blurred) panels
   around it, and cuts those panels away with the channel logos on them (FOX 26, KHOU 11,
   …), plus black bars and a ticker laid across the whole frame. Nothing is painted over or
   invented. A logo that sits *inside* the real photo stays. When the edges are not certain
   the whole picture is used.
3. **Adjust crop.** Every person photo (People list) and every image (media cards) has an
   *Adjust crop* button: Automatic (default), drag your own box, or Whole picture. Before
   and after are shown side by side. Only the selection is saved; the upload is untouched.
4. **New name graphic.** Bold white Montserrat ExtraBold capitals, a red vertical bar, a
   thin red line with a bright glowing centre, over a dark navy fade at the bottom. It sits
   under the left edge of the photo.
5. **Names at the first introduction only.** The "every appearance" option was removed;
   old projects that saved it now show the name once. The legacy "label on every card"
   switch no longer repeats names either.
6. **Two people in one line, side by side.** When one SRT line names two people who both
   have a photo, both photos show side by side, each with its own name if it is that
   person's first introduction. Untick *Two people named in one line* in People to go back
   to one person per line.

Preview = export: the monitor shows the same image files the export overlays
(`/people/<id>/card.png`, `/assets/<id>/clean-frame`).

## How to check

* Upload a news screen grab as a person photo or cutaway image, open *Adjust crop*: the
  red box should hug the real photo, with the logos outside it.
* Play a line that introduces a person: photo centred, name graphic shown. Play their next
  photo: no name.
* A line naming two people shows both side by side.

## Tests

`tests/test_stills_v17.py` (21 grab cases built from real photos when scikit-image is
installed, otherwise from generated textures; framing; names; pairs; a real FFmpeg overlay
render). `tests/test_person_overlays.py` updated for pairs and first-introduction names.
