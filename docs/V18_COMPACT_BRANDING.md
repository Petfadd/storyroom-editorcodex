# v18 — Compact CTA and watermark controls

Build `2026-11-22-compact-branding-v18` (includes everything in v17).

* The **＋ New** button in the top bar is gone. **Projects → ＋ New production** does the same.
* In the Shot Inspector, **CTA** and **Watermark** now sit side by side in one short row.
  * Each has a small upload tile (＋ Upload, or the uploaded picture). Clicking it opens
    your folder; clicking it again replaces the file.
  * Every long slider became **− value +**. Hold a button to keep stepping. The monitor
    updates at once; the value is saved half a second after the last press.
  * CTA: Opacity, Size, Left ↔ right, Up ↕ down. Watermark: Edge (on, position, Size, Gap)
    and Middle (on, Size, Opacity). Everything else (move on video, preview, timing,
    motion, owner name, remove) is under **More**.
* Frame scale and the narration / clip / music volume stay at the top of the inspector.

Nothing about rendering changed: the same settings are saved and exported as before.
Test: `tests/test_branding_v18.js`.
