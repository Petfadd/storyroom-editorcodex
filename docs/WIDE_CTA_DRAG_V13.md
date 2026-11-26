STORYROOM 8004 — LARGE CENTERED CTA + DRAG / RESIZE v13

An IN-PLACE update to your current Python + FFmpeg Storyroom installation.
No PowerShell, no Remotion, and no second editor installation required.

WHAT CHANGED
- New and upgraded projects default to a much larger CTA: 97% of frame width,
  centred both vertically and horizontally (with an equal 97% height safety cap).
- Shot Inspector > Channel CTA includes a Card size slider (20–100%) and
  a Move / resize on video button. Drag the outlined box to move the card,
  or drag its bottom-right handle to change size. Release to autosave.
- Large & center resets the card to 97% width and the centre of the frame.
- Transparent PNG/WebP/JPG, 0–100% opacity, and the automatic on/off timing
  remain unchanged. Saved custom placement applies in preview and export.
- Existing randomized top/bottom and left/right entrance/exit directions
  remain. The card rests at the saved position when animation finishes.
- Original video sound, narration SRT, picture cutaways and still photos
  are unaffected.

INSTALL THE UPDATE TO YOUR EXISTING STORYROOM — CMD ONLY
1. BACK UP important Storyroom projects. Stop the original running editor
   using Ctrl+C in its CMD window.
2. Download and extract Storyroom_8004_Wide_CTA_Drag_Resize_v13_Update.zip.
3. Open the extracted folder (containing UPDATE_EXISTING_STORYROOM.cmd).
4. Double-click UPDATE_EXISTING_STORYROOM.cmd, or open CMD there and type:
       py -3 UPDATE_EXISTING_STORYROOM.py
5. Choose the ORIGINAL installation folder containing the real app.py and
   START_UPDATED_STORYROOM_8004.bat. Do not select the extracted update folder.
6. Type UPDATE to proceed. The script verifies hashes, backs up modified
   source files and leaves your projects, footage, audio and virtualenv intact.
7. Start the ORIGINAL editor using START_UPDATED_STORYROOM_8004.bat and
   refresh http://127.0.0.1:8004/ . Check /api/build-info for:
       2026-11-21-wide-cta-drag-resize-v13

In Shot Inspector, select Move / resize on video. When editing, the CTA
appears even outside its narration window as an editing preview.
Drag the yellow boundary to reposition, the bottom-right square to resize,
then select Done adjusting. Use the 70% opacity slider to see footage beneath.

The final MP4 must be rendered again after changing the card layout.
This package was tested with local Python/Node regression tests and FFmpeg
smoke renders; the complete Windows GUI and a 30–60-minute export have not
been tested on your PC.
