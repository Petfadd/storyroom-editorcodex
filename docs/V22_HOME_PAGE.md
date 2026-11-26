# Storyroom v22: home page

Build `2026-11-22-home-page-v22`.

## What you see when Storyroom opens

Storyroom now opens on a home page instead of jumping into the last project.

- **Create project**: the large red banner. It opens the same *New production* setup as
  before (a title, then 16:9 or 9:16). After you press *Create production* you are in
  the editor, with Setup open, exactly as before.
- **Recent videos**: your projects, most recently edited first. Each card shows:
  - a picture: the first shot on the timeline, or the first upload if there is no
    timeline yet. 9:16 projects keep their shape on a blurred background;
  - the film length (the narration clock, the same number the export uses);
  - 16:9 or 9:16, and when it was last edited;
  - a status label:
    - **Exported**: an export exists and it was made from this exact version of the project;
    - **Editing**: there is no export yet, or the project changed after the last export;
    - **Needs setup**: no narration and no media yet.
- Clicking a card opens the project. Its **⋯** menu has *Open*, *Rename*,
  *Open export folder* (shown only when an export exists; it opens the project's
  `renders` folder in Explorer) and *Delete…* (the same permanent delete, with the same
  confirmation, as before).
- **Search** and **sort** (Last edited · Name A–Z · Longest first). The home view shows
  the 10 most recent projects; *All projects* in the sidebar, or *Show all*, lists every one.
- **Sidebar**: Home, All projects, Media Tools, Performance, and a status box showing
  whether FFmpeg, Python and speech recognition are ready. If Python is 3.15 or newer
  and speech recognition is not installed, the box says to rebuild with Python 3.12.

## Getting back to the home page from the editor

- **Back arrow**: the small arrow at the far left of the editor header.
- **Home**: the button beside *Caption* in the header. On narrow windows it shows only
  the house icon.
- **Projects**: the button at the top right now opens the home page. The old project
  switcher pop-up was removed.

If there are unsaved changes, the usual "Leave without saving?" question appears first.
Playback stops when you leave the editor. Refreshing the browser while you are inside a
project keeps you in that project, because the address still names it.

## Other changes

- `tools/install_local_package.py`: when pip fails on Python 3.15 or newer, the message
  in Media Tools now names the cause (the speech engine has no build for that Python
  yet) and the fix (install Python 3.12, delete `.venv`, start Storyroom again).

## Not changed

Narration audio, SRT timing, sound-bite audio, Beat parsing, the film-master clock,
cutaways, the render and every project file are untouched. The home page only reads
`project.json`, the `renders` folder and the export record. Pictures are made once and
cached in `.cache/home` inside each project.

## Files

- New: `static/home.js`, `tests/test_home_page_v22.py`, `tests/test_home_v22.js`, this file.
- Changed: `app.py` (project list fields, `cover.jpg`, `open-export-folder`, build id),
  `templates/index.html`, `static/editor.js`, `static/editor.css`, `static/media_tools.js`,
  `tools/install_local_package.py`, `verified_launch.py`.
