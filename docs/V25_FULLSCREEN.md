# Storyroom v25: full-screen monitor

Build `2026-11-23-fullscreen-v25`.

- A full-screen button (four corners) sits under the monitor, at the right end of the
  monitor controls, after *Transitions*.
- Click it: the monitor fills the whole screen. The picture keeps its shape (16:9 fills
  a 16:9 screen; a 9:16 film fills the height, black at the sides). Name cards, the CTA,
  the watermark and captions scale with it.
- **Space** still plays and pauses while in full screen.
- **Esc** (or the button again) returns to the editor.
- View only: it does not change the project, the render or any setting.

Files: `templates/index.html`, `static/editor.js`, `static/editor.css`, `app.py` and
`verified_launch.py` (build id), `tests/test_fullscreen_v25.js`, this file.
