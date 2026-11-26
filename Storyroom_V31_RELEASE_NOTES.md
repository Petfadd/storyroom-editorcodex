# Storyroom V31 · Cinematic graphics review

Build: `2026-11-26-cinematic-graphics-review-v31`

## Added

- A **Graphics** button in the Storyroom header.
- A project-specific cinematic graphics design panel with a live preview built from the open project's title and narration cues.
- Editable motion style, speed, background movement, background treatment, accent colour, main and secondary text colours, headline and body fonts, and independent headline/body sizes.
- Optional title and subtitle controls. A blank subtitle produces no underneath text.
- Replay, reset and text-contrast feedback.
- Strict server-side validation and per-project storage of design settings.

## Timing and visual corrections

- Approval videos now start each graphic on the matching spoken phrase and complete the reveal during that phrase.
- Narration pauses and final holds were shortened.
- The demonstration voice uses normal speaking speed.
- The visible training/production footer and the generic legal sidebar were removed.

## Safety gate

Automatic narration analysis, timeline placement and final-export insertion remain disabled until the producer approves the animation quality. Saving a design does not modify narration, SRT, soundbites, scene timings, source media or existing picture assignments.

## Verification

- 13 focused tests passed: 8 frame-renderer tests and 5 Storyroom panel tests.
- Python and JavaScript syntax checks passed.
- The panel was opened and visually checked in the running Storyroom editor.
- All four existing project folders remained present after installation.

The ZIP excludes local projects, media, caches and the virtual environment. After extraction, double-click `START_UPDATED_STORYROOM_8004.bat`; the first run creates its private environment and installs required packages if needed.
