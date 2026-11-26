# Storyroom v15 — photos on whole subtitle lines, narration-end tolerance, CTA guards

Build: 2026-11-22-photo-cues-cta-guards-v15 (built on v14; everything from v14 stays).
Unchanged: narration audio, SRT timing, sound-bite audio, Beat parsing, film-master clock,
and the interview picture-cutaway format and checks.

## Person photos snap to whole SRT cues (timing "whole SRT line", the default)
- A photo starts on the first frame of the cue that names the person and ends only on a
  cue boundary, never mid-line. Boundaries are snapped to the 30 fps frame grid.
- One person per cue: the first-named person who can be shown holds the whole cue. A
  second person named in the same cue waits for the next cue that names them, or is
  skipped; either way it is listed in Notes.
- The photo holds through following cues that name the same person (pauses included),
  and through following cues that name nobody until the picture underneath changes, up
  to the start of the next cue that names someone else. Silences longer than the merge
  gap (1.5 s) end the photo.
- Maximum length ends on the cue boundary at or after it.
- Never crosses into a sound bite; mugshot-only people still wait for the arrest; photos
  still need opt-in. Preview and export use the same planned windows.
- A window shorter than the minimum is reported, not flashed.
- Setup › Featured case people shows every window: person, cue numbers, film IN → OUT.

## Name and photo style
- Name display: First appearance only (default) | Every appearance.
- The name stays for the whole photo window and arrives/leaves with the photo.
- Photo style: Slides & zooms (v14 varied moves, default) | Clean cut (still photo) |
  Clean cut with a short 150 ms dissolve (still photo). Applies to timeline stills too.

## Narration end
- Narration length is measured from the decoded audio (MP3/AAC encoder delay and
  padding removed) and shown in the Beat picture plan beside the file's own figure.
- A pause within one output frame (33 ms) of the narration end is clamped to it and
  listed in the build record (pause_clamps).
- A pause really outside the narration names the Beat, the script value, the decoded
  and clock lengths and the difference, and offers "Clamp to narration end" (reviewed).

## Channel CTA
- Shot Inspector › Channel CTA lists every narration line that triggered the card, with
  film-master IN → OUT.
- More than one CTA moment: a warning, and only the first is used unless "Show the card
  at every moment" is ticked.
- Sound-bite dialogue (Exact Spoken Dialogue) never triggers the card (tested).

## Setup › 08 Interview picture cutaways
Uploads the same cutaway handoff (JSON or Markdown table) as Documentary tools, after the
storyboard is built. Rows are not approved from Setup; approve them in Documentary tools.

## How to check it in the preview
1. Setup › Featured case people: open "photo windows on the film". Each row should start
   and end on the listed cue times; two names in one line show only the first.
2. Play across a line that names someone: the photo appears on the line's first frame,
   stays through the pause to the next line, and the name stays until the photo leaves.
3. Switch Photo style to Clean cut, then Short dissolve, and replay the same line.
4. Shot Inspector › Channel CTA: open "Narration lines that trigger the card".
5. Open the Beat picture plan: the narration length line shows decoded vs file length.
6. Render MP4 and compare the same moments in the file.
