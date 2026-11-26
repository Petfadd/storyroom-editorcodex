# Storyroom v26: stickers, CTA fix, tab icon

Build `2026-11-23-stickers-v26`.

## CTA card hanging on the monitor (fixed)

Pressing − / + on the CTA, or uploading a CTA card, switched on "show the card so you
can see the change". Nothing switched it off again, so the card stayed on the monitor
over the whole film, including where the SRT never asks for it. The render was not
affected: it always used the SRT/script windows.

Now the card shows outside its window for 3 seconds after an adjustment (5 after an
upload), then hides. Pressing play always uses the real timing and also ends
"Move on video".

## Tab icon

The SR logo now shows in the browser tab (`static/favicon.svg`, `favicon-32.png`,
`favicon-180.png`, `favicon.ico`, and `/favicon.ico`).

## Stickers

- **Header › Stickers** (where Home was; the back arrow and *Projects* still go home)
  opens the library:
  - *Subscribe*: Subscribe click (animated: the cursor clicks and it turns to
    Subscribed), Like · Subscribe · Bell (animated), Subscribed, Bell (rings), Like,
    Share, Comment;
  - *Arrows & shapes*: two red arrows, a red circle, a REC frame (blinking dot), a
    waveform (moving);
  - *Yours*: upload your own PNG (transparent background works best), WebP or JPG.
    The × on a tile removes it from your library and from the film.
  All built-in stickers are original artwork drawn by `tools/make_stickers.py`.
- **Click a sticker** and it goes on the film at the playhead for 4 seconds (shorter
  if the film ends sooner) and is selected.
- **Shot Inspector › Stickers** (shown when the film has stickers): − / + for Size,
  Left ↔ right, Up ↕ down, Opacity, Starts at and Length; *Jump to it*, *Centre*,
  *Remove*; ✓ when done. Hold a button to keep stepping. The list underneath shows
  every sticker in the film; click one to select it and jump to it.
- **Drag** a sticker on the monitor to move it.
- **Render**: stickers are drawn into the MP4 with the same timing, size and place as
  the monitor: over the picture, name cards and CTA; under the watermark and captions.
  They fade in and out over 0.2 s. The film length, footage, narration, sound bites
  and SRT are unchanged.

## Tested

- Browser: library opens, a sticker is added at the playhead and selected, − / + and
  dragging change and save it, it hides outside its time, the animation frame matches
  the time, uploads work, no page errors.
- Render: a 25 s, 25 fps film with three stickers (animated Subscribe click, arrow,
  uploaded): each appears exactly in its time with the right animation frame; 625
  frames, as before.

## Files

New: `stickers.py`, `static/stickers.js`, `static/stickers/*.png`, `tools/make_stickers.py`,
`static/favicon*`, `tests/test_stickers_v26.py`, `tests/test_stickers_v26.js`,
`tests/test_cta_peek_v26.js`, this file.
Changed: `app.py`, `documentary_final_renderer.py`, `static/channel_cta.js`,
`templates/index.html`, `static/editor.css`, `verified_launch.py`,
`tests/test_cta_drag_v13.js`, `tests/test_home_v22.js`.
