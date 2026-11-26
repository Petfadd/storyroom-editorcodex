# Storyroom v11 — Cinematic name-only first introductions

**Purpose:** A restrained documentary person introduction that preserves the uploaded verified photograph. Show only the supplied person's name — no labels such as victim, suspect, murderer, charges, location, or other generated claims.

- Applies at the first **actual approved photo appearance** for each person, not every SRT name mention. Subsequent 1–5 rotating photos contain no automatic nameplate.
- Blurred side fill uses a copy of the uploaded image; its pixel content is not generated or altered to invent evidence.
- Short red accent, faint red glow, subtle dark lower gradient, clear white type. No solid black television-style lower third.
- Graphic has a separate alpha layer and fades on/off while the photo continues; compatible with existing gentle movement.
- Applies to real documentary narration only. Soundbites and picture cutaways remain controlled by existing source-audio protections.
- UI: Setup > Featured case people > Automatic photo storytelling. Advanced option `Cinematic name introduction (first appearance only)` can be switched off.
- `show_label` remains available in saved projects for backwards compatibility but is superseded by this new first-appearance design unless the new setting is explicitly turned off.
- Crop and photo identity: source images must be verified. This feature **does not erase embedded broadcaster logos** or synthesize faces. Choose a cleaner source photo or crop manually before import if a logo is within the image.
- Per-project settings and source files are preserved; changing a photo/label does not require a Beat rebuild, but existing exported videos need to be re-rendered.

## Local verification

Run `python -m unittest -q tests.test_cinematic_name_intro_v11 tests.test_multi_person_photo_sets tests.test_shared_person_photos` from the source folder. Actual final 30–60-minute Windows exports are not proven by these tests.
