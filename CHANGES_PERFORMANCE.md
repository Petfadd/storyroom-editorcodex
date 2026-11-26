# Changes in this build (16 Nov 2026)

Fixes
- app.py: export blockers fixed for approved reuse involving sound bites (scene_beat);
  job queue paused while a final documentary render runs (_hold_queue_during).
- documentary_final_renderer.py: a graphics-card encoder rejected once is skipped for the
  rest of the render (no more double encoding of every shot); per-render timing line in
  projects/<id>/renders/render_timing.log; phase timings.
- proxy.py: valid quality options per hardware encoder (NVENC no longer fails), with a
  software fallback.
- documentary_preview.py: preview parts encoded in parallel.
- static/editor.js: the "Enhance" choice is remembered (default still on).
- footage_downloader.py: yt-dlp timing/format logging; STORYROOM_YTDLP_FRAGMENTS and
  STORYROOM_YTDLP_CHUNK overrides (defaults unchanged).

New
- perflog.py: stage timings to perf_logs/stages.jsonl (STORYROOM_PERF=0 turns it off).
- tools/perf_audit.py: profiler (machine, stages, ytdlp, render, compare, report).
- tests/test_bite_reuse_approval.py: regression test for the export-blocker fix.

Run the editor the same way as before (see README.md / docs/RUN_ON_YOUR_PC.md).

## Update 2 (16 Nov 2026, afternoon)
- documentary_final_renderer.py: a soundtrack that runs under half a frame past the last
  picture frame is accepted only when that overhang is silent (fixes "Picture/audio end
  differs by -0.000162s"). Audible sound is never cut.
- proxy.py: editing copies get a keyframe every 15 frames (was up to 250), so scrubbing
  seeks about 20x faster. Old copies are rebuilt once in the background. Export unaffected.
- app.py: the video endpoint reads the cached project snapshot instead of re-parsing
  project.json on every scrub request.

## Update 3: Cinematic controls, Phase 1 (16 Nov 2026, evening)
Manual camera and transition control per slot. Nothing here moves a cut, a source
range, narration or sound.
- Shot Inspector > Camera: Static, Zoom in/out, Pan left/right/up/down; strength;
  easing; start and end zoom (100-200%); focal point picked by clicking the monitor;
  Preview shot; Remove; Lock; Undo. Acts on the selected slots only.
- Transition into this shot: any library transition, exact length (0.13-3 s), Lock.
  Locked transitions are never changed by Auto, Apply to all, Clear or script reset.
  New "Whip Pan" transition.
- Animated zoom/pan is drawn identically in the monitor, the review preview and the
  final render (cinematic.py and static/cinematic.js, kept in step by a test).
- Full-screen photo cards: Photo motion (still / zoom / pan) with strength; the name
  label stays still while the photo moves. Default is Still, so existing films are
  unchanged.
- Camera moves and locked transitions are kept through a Beat timeline rebuild.
- New: cinematic.py, static/cinematic.js, static/cinematic_ui.js,
  tests/test_cinematic.py, tests/test_cinematic_api.py.

## Update 4: Footage sheet people rows (16 Nov 2026)
- A photo row with one timestamp (| P01 | ... | 00:00:38 |) now takes the video frame at
  that time. Before, every photo row from the same video got that video's thumbnail, so
  several people could get the same picture.
- A title before a name ("Director Brendan Kelly") becomes the role: the name is
  "Brendan Kelly", and "Director" alone no longer counts as saying his name.
- A name with a middle initial ("Cherie L. May") also matches "Cherie May".
