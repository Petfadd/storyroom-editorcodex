# Storyroom v12 — Wide centered CTA & clean original-photo framing

This module retains Python, FFmpeg and all Storyroom clocks. No Remotion.

## Channel CTA

- Upload the user's channel CTA design (transparent PNG/WebP/JPG) in Shot Inspector.
- CTA plan is computed from narrator script/SRT as before. Any manually specified
  film-clock IN/OUT remains respected.
- Default geometry: **centered, 90% width, max 90% height** in any selected output
  aspect ratio. Saved legacy corner-position and small-width settings are upgraded
  transparently, without altering the uploaded card.
- Default motion **Automatic variety**, stable per unique video/project and CTA
  appearance. Available directional pairs: enter top/leave bottom; enter left/leave
  right; enter right/leave left; optional fade-only. Preview uses the same resolved
  variant and timings as export.
- Opacity remains a user-controlled overlay from 0–100%; original footage and audio
  stay underneath. A 70% default is used on new projects.
- The supplied Homicide Recap card example is in `docs/` for voluntary uploading.
  No brand or image is silently attached to a different channel/project.

## Still-photo framing

- Feature person photos and image cutaways now pass through a conservative
  central-photo boundary detector. If a clear, balanced pair of vertical inset
  boundaries is found, use only the central original-photo pixels as the foreground
  and as the blurred side background.
- The original file remains untouched and retains source provenance in the media bin.
- If no confident boundary exists, the original is used (no automatic erasing,
  synthesis or cropping of faces). A logo embedded within the actual portrait cannot
  be removed reliably by border detection; upload a cleaner source or review a manual
  crop in such cases.
- Normal studio stills, natural landscapes and already clean photos are not cropped.
- This derivative is shown in the direct still-image monitor, in enabled person-photo
  overlays, in the continuous clip preview, and when still picture cutaways are
  exported. QC/original-media views retain the original source.
- The editor never edits source footage, obscures evidence by inpainting, changes
  source-audio timing, or substitutes photos for a different person.

## Testing

A short FFmpeg regression suite covers all three slide pairs and a dissolve option,
checks master-clock frame counts, and checks safe crop/preservation conditions. The
complete Windows GUI session, your exact original photo source files and 60-minute
production export require testing on the local PC before final delivery.
