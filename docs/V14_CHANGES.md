# Storyroom v14 — CTA editing, story-aware transitions, varied photo motion

Build: 2026-11-22-cta-motion-transitions-v14

## Channel CTA card
- Starts large and centred (97% wide). Size can now go to 100%.
- Four corner handles. Dragging any corner resizes evenly about the centre, in any
  direction, and the corner stays under the pointer. (v13 could only shrink when
  dragging up and left together.)
- Drag the card to move it. The saved position is exactly what is on screen.
- New Left↔right and Up↕down sliders; arrow keys nudge, + / − resize.
- Geometry is measured on the video picture, not the letterboxed monitor box, and the
  fade timing matches the export, so preview = export.
- Readable buttons (v13 buttons were light text on light grey).
- After any CTA change the top button switches to "Render again" at once.
- Auto timing now uses the SRT even when the script has no sound bites or narration
  text, and the panel says plainly when no subscribe moment is found.
- The CTA panel sits below the selected shot's own controls.

## Transitions — Auto Suggest reads each moment
Cinematic and Dynamic styles read every real picture cut: speaker in/out, time jumps,
new places, reveals, shocks, grief, tension, photos arriving, opening and closing.
Each moment has a shortlist of professional transitions; the next one never repeats the
one just used, and timing per transition fits the moment (quick flash, slow fade).
Hand-picked and script cuts are kept. Same film, same result.

## Photo motion
Every photo appearance gets its own move: slide in from left/right, drop from the top,
rise from below, fade in — each followed by a slow push in, pull back, drift, pan or
portrait reveal. Two photos in a row never share an entrance or a camera move. The
narration steers it (grief pulls back, an arrest drops in, a first introduction gets a
portrait reveal). Timeline still images use the same rotation. Preview matches export.
Setup → Featured case people → Optional settings → Photo motion / Motion strength.

## Reliability
- Missing libraries (e.g. PyAV) are installed automatically at every launch and by the
  updater; the editor shows a "Repair now" bar instead of server errors.
- The updater accepts v13 installs and checks ports 8003 and 8004.
- Header shows the real build; timeline fits the film on open (+ Fit button); Frame QC
  labels are distinct; clearer export/review wording; quieter background polling.
- Script guide, worked example and footage sheet in production-script-templates/.
- Test suite brought up to date with the current behaviour; retired strict-mode tests
  are marked skipped.
