# Storyroom v16 — Channel watermark

Build: 2026-11-22-channel-watermark-v16 (built on v15; everything from v14 and v15 stays).

Shot Inspector › Channel watermark:
- Upload your logo once per project (transparent PNG recommended; WebP/JPG accepted —
  a JPG shows its background box). Empty transparent borders are trimmed automatically.
- Edge logo: tick it, choose Top left / Top right / Bottom left / Bottom right / Top
  centre / Bottom centre, set Size (4–40% of the picture width) and Distance from edge.
  It is always 100% solid — no opacity control, by design.
- Middle logo: tick it, set Size (10–95%) and Opacity (0–100%, default 12%).
- Tick both to use both. Both stay on every frame from the first to the last: narration,
  interviews, photos, cutaways and the CTA card. They sit over the picture and the CTA,
  under captions and subtitles.
- Optional owner name is written into the MP4's information (copyright, artist, comment).
- The preview shows both logos live at the exported size and position. Changing the
  watermark switches the top button to "Render again"; nothing else changes (timing,
  audio, SRT, the film-master clock are untouched).

How to check it: upload a logo, tick Edge + Middle, move the sliders and watch the
monitor; render; scrub the MP4 start, an interview, a photo, the CTA and the last frame.
