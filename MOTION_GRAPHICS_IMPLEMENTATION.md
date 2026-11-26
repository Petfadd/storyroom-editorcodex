# Intelligent Cinematic Motion Graphics Engine — Implementation Summary

## Overview

A professional, narration-synchronised kinetic typography layer for investigative
documentaries, integrated non-destructively into the existing Storyroom editor.
Four context-aware templates produce genuinely animated per-frame renders driven
by Pillow and composited by FFmpeg, following the exact same overlay-chain pattern
used by person cards, stickers, CTA cards and watermarks.

## Modified Files

| File | Change |
|------|--------|
| `app.py` | Added 5 new endpoints for motion graphics (GET/PATCH settings, analyse, preview, stream). Inserted after the existing `cinematic-graphics` endpoints (~line 985). |
| `documentary_final_renderer.py` | Added motion graphics overlay layer in the `overlays()` closure between stickers and watermark. Overlay chain is now `[p] → [base] → [cards] → [cta] → [stk] → [mg] → [wm] → captions → [out]`. |
| `templates/index.html` | Added Motion button in toolbar, `#motion-graphics-dialog` dialog, and `<script>` include for `motion_graphics.js`. |
| `static/editor.css` | Added `.motion-graphics-dialog`, `.mg-*` styles for the full editor panel. |

## New Files

| File | Purpose |
|------|---------|
| `motion_graphics.py` | Core engine: settings, validation, context analysis (act detection, exclusion patterns, template scoring), suggestion generation, signature hashing. |
| `motion_templates.py` | Four templates (Investigative Findings, Chronological Timeline, Contradictory Statements, Legal Outcome) producing `Sequence` objects with per-element animation definitions. Animation primitives: mask_wipe, fade, slide, rise, scale_in, divider_expand. Easing: cubic/quartic out, in-out cubic. |
| `motion_render.py` | Pillow per-frame RGBA rendering, FFmpeg encoding to alpha-preserving video (ffv1/yuva420p), content-addressed caching by SHA-256, `render_filters()` integration matching the existing overlay module pattern. |
| `static/motion_graphics.js` | Editor UI: enable/disable, analyse, suggestions with accept/reject, preview video with seeking, design controls (background, colours, motion style), sequence editing and removal. |
| `tests/test_motion_graphics.py` | 35 unit tests covering settings, analysis, all four templates, animation states, frame rendering, caching, integration, performance. |

## New Dependencies

**None.** The engine uses only libraries already in `requirements.txt`:
- `Pillow` (frame rendering)
- `imageio-ffmpeg` (bundled ffmpeg binary, video encoding)
- `fractions`, `json`, `hashlib`, `pathlib` (stdlib)

## Four Templates

### A. Investigative Findings
Small investigative heading → bold cinematic title → animated accent divider
(expanding from centre) → sequential bullet reveals (rise animation). Previously
revealed bullets remain visible as new ones appear.

### B. Chronological Timeline
Title kicker → vertical timeline line that grows over the sequence duration →
sequentially revealed date markers (scale_in), date labels (fade), and event
descriptions (rise) along the timeline.

### C. Contradictory Statements
Title → verified panel with left accent bar → animated horizontal divider →
conflicting panel with accent-colour bar and italic styling. Clean visual
separation between the two statements.

### D. Legal Outcome
Heading → court name → sequential charge reveals → animated divider → verdict
(scale_in emphasis) → sentencing. Clear distinction between charges, verdict and
sentencing.

## Context Analysis

The engine reads the full production script and narration SRT before suggesting
placements. Three-tier parsing:
1. `documentary_beats.read_beats()` for standard production scripts
2. SRT blocks as fallback when beats are unavailable
3. Raw script text extraction as last resort

**Act detection:** scans for Act/Chapter markers (I–VIII, 1–8), focuses on Acts
3–6. Falls back to temporal thirds when no markers exist.

**Hard exclusions:** cold opens, victim introductions, family interviews, witness
testimony, police briefings, courtroom soundbites, tributes, emotional closings,
CTA sequences. Each uses regex patterns matched against narration and visual
direction text.

**Template scoring:** combines act affinity (0–40 points) with keyword evidence
(0–30 points) and template-specific cues (0–25 points). Minimum score threshold
of 40 to be suggested.

## Narration Synchronisation

Every element has a `t_in` (reveal time) and optional `t_out` (exit time). The
animation state is a pure function of `(t - t_in) / anim_in_dur` with no
cross-frame state. Elements animate independently — a later reveal does not
affect an earlier one.

## Non-Destructive Integration

- **Disabled by default:** `motion_graphics.enabled = False` until the user
  explicitly enables it.
- **Separate overlay layer:** composited between stickers and watermark using
  FFmpeg's overlay filter with `enable='between(t,...)'` — never modifies
  underlying footage pixels.
- **Original data preserved:** narration, SRT, source timestamps, footage IDs,
  clip ranges and reuse are never touched.
- **Removing restores original:** disabling or removing sequences gives back
  exactly the film that was there before.

## Performance

| Metric | Value |
|--------|-------|
| 1080p frame render time | ~42 ms (Pillow) |
| 15s sequence at 1080p/30fps | ~19 s render time (450 frames) |
| Peak memory per frame | < 50 MB |
| 720p demo render (4 templates) | ~117 s total |
| Cache | SHA-256 content-addressed; identical inputs skip re-render |
| Background rendering | Preview renders run in daemon threads |
| UI responsiveness | No blocking; preview polled asynchronously |

## Testing

35 tests, all passing:
- **Settings (7):** defaults disabled, normalisation, validation, catalogue, signature
- **Analysis (4):** candidate detection, exclusion, legal scoring, suggestion generation
- **Templates (5):** all four templates produce valid structures, unknown raises
- **Animation (6):** hidden before t_in, revealed at t_in, mid-animation, independent elements, mask_wipe progression, divider expansion
- **Rendering (5):** RGBA output, all templates render, colour resolution
- **Cache (3):** same inputs → same sig, different content/resolution → different sig
- **Integration (4):** disabled=no filters, enabled=sequences, original untouched, roundtrip
- **Performance (1):** 5-frame benchmark < 5s

## Editor UI

The **Motion** button (toolbar, next to Graphics) opens a panel with:
- Enable/disable toggle
- Auto/manual mode selector
- Analyse button (runs context analysis)
- Suggestions with Accept/Reject/Preview buttons
- Approved sequences list with Preview/Edit/Remove
- Design panel: background, accent colour, text colour, motion style
- Video preview with playback controls and seeking

## Usage

1. Open a project in Storyroom
2. Click **Motion** in the toolbar
3. Enable motion graphics
4. Click **Analyse documentary** (requires production script or SRT imported)
5. Review suggestions → **Accept** the ones you want
6. **Preview** each to verify the animation
7. **Edit** text if needed
8. **Save design** for your preferred visual style
9. Export as normal — motion graphics are composited automatically

## Known Limitations

- Preview uses a flattened dark plate (no underlying footage) for simplicity
- Font library uses the existing bundled fonts; custom fonts require manual addition to `static/fonts/`
- Background radial glow uses per-point drawing (acceptable at 1080p, could be optimised with gradient image for 4K)
- Act detection is heuristic; explicit Act/Chapter markers in the script give better results
- No word-level timestamp alignment yet; relies on SRT cue boundaries
