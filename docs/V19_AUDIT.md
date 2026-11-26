# v19 — Full audit: rendering, timeline speed, dead code, dead-end prompts

Build `2026-11-22-fast-render-audit-v19` (includes v14–v18). Narration audio, SRT
timing, sound-bite audio, Beat parsing and the film-master clock are unchanged.

## 1. How a documentary renders (end to end)

1. **Plan and frame check** — the saved Beat timeline is turned into *spans* (one per
   shot, cutaway or still) on the film's 30 fps clock. Nothing renders if a span does
   not fit its source.
2. **Soundtrack** — narration, every sound bite and music are mixed into one WAV whose
   length is checked against the picture to the sample.
3. **Pieces** — every span is encoded on its own (x264 `veryfast`, CRF 20, or the
   graphics card when it passes a test encode), several at a time, at low priority.
   Everything drawn over the picture is added in the same pass: person photos and
   names, the CTA card, the watermark, script captions, subtitles, fades. Transitions
   are their own short pieces. Every piece is checked for exact frame count and rate.
4. **Join** — pieces are joined without re-encoding; timestamps are rebuilt from frame
   numbers so no drift can creep in.
5. **Mux** — the soundtrack goes in beside the picture (AAC 192k, faststart, owner name).
6. **Verify** — frame count, frame rate and audio length of the finished MP4 are checked
   before it replaces the previous render.

## 2. What was slow or wrong, and what changed

| Finding | Effect | v19 change |
|---|---|---|
| Every still (person photo, name layer, CTA card, watermark, cutaway picture) was read with `-loop 1`, which **decodes the picture again for every frame**. | A full-frame photo cost 3× the footage under it; the watermark taxed every frame of the film. | Each still is decoded once and repeated in memory (`still_layers.hold`). |
| Overlays were drawn in RGBA, converting the picture to RGB and back. | Slower; transitions picked up a visible colour shift. | Drawn in YUV with an alpha plane. Transitions now match the source colour (measured chroma error halved). |
| Name layer was a full-frame transparent image. | Most of the overlay work was on empty pixels. | Only the visible part is drawn. |
| Timestamps of held stills used the image's own 1/25 s time base. | (Found while testing the change) the last frame of a photo could fall through to footage. | Time base set to exactly one frame. |
| Transitions into or out of a still picture had one frame to blend. | The transition silently became a hard cut (or a black frame). | Stills now blend like footage. |
| Parallel pieces were capped at 4. | A 12–16-thread PC left half its cores idle. | Up to 8, bounded by free memory per frame size (≈0.6 GB at 1080p, 1.6 GB at 4K). `STORYROOM_RENDER_WORKERS` still overrides. |

**Measured** (same 25 s, 1080p test film with photos, names, CTA, watermark and five
transitions, 2-core test machine): 34.4 s → 25.3 s total, piece encoding 30.9 s → 22.6 s.
On photo-heavy films the gain is larger: one full-frame photo with name went from
9.1 s → 3.0 s per 10 s of film; a photo with a camera move 25.4 s → 15.6 s. More cores
add the worker change on top. Output: same frame count and duration, deterministic,
all other frames within 43 dB of v18.

Not changed on purpose: the encoder preset/quality, the exact frame checks, and the
final verification (already a fast packet scan).

## 3. Timeline responsiveness

Measured in the editor with a simulated 60-minute film (864 shots, 720 SRT lines):

| Action | v18 | v19 |
|---|---|---|
| Dragging the zoom slider (per step) | 255 ms | 2 ms (stretch preview; one redraw after you stop) |
| Zoom − / + buttons, Fit | 255 / 114 ms | 70 / 31 ms |
| Full timeline draw | 285 ms | 65 ms |
| Redraw when nothing changed | 28 ms | 8 ms |
| Waveform redraw after a change | 129 ms | under 1 ms (drawn as clips come into view) |

Causes fixed: a search through every SRT line for every shot on each redraw
(~600,000 steps at an hour), all waveform canvases redrawn on every redraw, the whole
timeline rebuilt for every slider step, and off-screen clips painted.

## 4. Dead code removed (≈3,300 lines of app code)

* **Subject-following reframe** (7 modules, 5 API routes, its UI): its controls were only
  reachable from a panel that no longer rendered. An old project set to "follow the
  subject" now renders like "auto".
* **Visual plan** (planner, 7 API routes): its panel was removed in v14; only the
  b-roll catalogue it shares with person photos is kept.
* API routes nothing in the editor called: selected-slot camera, cinematic undo,
  picture-tools, person-overlays view, block-map editor/remove, approve-all assets,
  approval policy, native-static review, moving review, bundle.json, shot index.
* Editor functions never called: shot candidates, source understanding panel, rebuild
  here, export framing/upscaler/quality pickers, picture enhancement switch, and the
  CTA slider commits replaced in v18.
* Leftovers: the v8.3 preflight CLI, unused helpers (`clean_file`, `_lower_third`,
  `exact_duplicates`, `_cinematic_auto`, `audit_beats`).

Tests that only covered removed code were removed or narrowed. Old copies of removed
files left on an updated PC are not loaded and are harmless.

## 5. Prompts that led nowhere (fixed)

* Beat picture plan offered **"Use a different uploaded video"** for a blocked
  **sound bite**; the choice did nothing. It now says what fixes it (upload the full
  file again with the same name, or correct the Beat's Source IN/OUT).
* Delivery said **"Build the storyboard from the imported SRT"** and **"Add at least one
  sound bite"** for a Beat project whose timeline simply had not been built. It now says
  the Beat timeline has not been built, where to build it, and what it is waiting on.
* Project health named only the **first** short video; it now names all of them.
* **"Planned picture 29.6 min"** (the sum of every scripted range) is now **Film length**
  = narration + sound bites.
* "Picture enhancement … choose it on the Render MP4 page" — there was no such control.
  Removed.
* "Use Review & export to start a render" / "Open Review / export checks" — no such
  button. Now "Press Render MP4 (top right)".
* YouTube importer: "the visual plan puts it on the narration lines" — the visual plan
  no longer exists. Now "kept in the media pool, ready to place".

## 6. Not tested here (check on your PC)

The Windows window, a graphics-card encoder (NVIDIA/Intel/AMD), and a real 30–60 minute
render. The render changes were verified frame by frame on the test film; long-film
timing was measured with a simulated timeline in a headless browser.
EOF
git add docs/V19_AUDIT.md && git -c user.name=a -c user.email=a@b commit -qm "v19: faster render (stills decoded once, YUVA overlays, more workers), faster timeline, dead code and dead-end prompts removed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_016RJHQYwdB44RbmYiuydvYY" && git log --oneline | head -2