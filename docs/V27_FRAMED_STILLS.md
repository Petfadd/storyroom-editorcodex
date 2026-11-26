# Storyroom V27 — framed stills and collage presentation

Build: `2026-11-24-framed-stills-v27`  
Release date: 24 November 2026

## Included

- Automatic centred photo card with a white/off-white border, soft shadow and a
  darkened blurred copy of the complete image behind it.
- One-card treatment for single photos and double-photo/Pixmix collages. Collage
  panels stay together and retain their original relationship.
- Shared treatment for uploaded JPG/JPEG/PNG/WebP images, approved
  `P##_..._video` photo carriers and source intervals explicitly classified as
  `native_static_interval`.
- One Still & photo motion director for uploaded images and still imagery carried
  inside clips. Automatic mode uses varied reveals, pushes, pull-backs and short
  diagonal moves with a controlled settle instead of a continuous generic drag.
- The monitor, documentary timeline and final MP4 renderer use the same framed
  still generator.
- Existing Storyroom-framed 16:9 images are detected and are not framed twice.

## Preserved

- Original media files and pixels remain available unchanged.
- Narration, soundbite dialogue, source IN/OUT ranges, Beat order and runtime are
  not changed by photo framing.
- Interview audio stays uninterrupted during approved picture-only cutaways.
- Moving footage is not converted into a still unless an interval is explicitly
  classified as static.

## Installation

Extract the ZIP to a normal writable folder, then double-click
`START_UPDATED_STORYROOM_8004.bat`. The first start creates `.venv` locally and may
need internet access to install Python dependencies. Keep private projects and case
media outside distributed release archives.

## Verification boundary

Automated checks cover syntax, build alignment, framing, collage preservation and
narration-clock defaults. A newly rendered documentary still requires full-resolution
local playback to confirm crop, picture identity, motion cadence, transitions and
compression for that particular production.
