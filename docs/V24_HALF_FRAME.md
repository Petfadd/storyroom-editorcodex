# Storyroom v24: half-frame times

Build `2026-11-22-half-frame-v24`.

## The problem

The film runs at the frame rate that covers most of the picture. In the NOLADINKINS
project that is 25 fps (one frame = 40 ms), because of the long Russo interview.
The production script times are written in 20 ms steps, so 146 of them land exactly
half a frame between two frames at 25 fps (for example Beat 006, 00:01:16,900 =
frame 1922.5). The editor refused every such time with "time is exactly halfway between
frame boundaries; choose a boundary". That blocked Render MP4 and every cutaway approval.
It did not name the Beat or the time.

## The fix

On the documentary film clock, and for the source frames of each Beat, a time exactly
half a frame between two frames now rounds to the later frame. That is the same rule
cutaways and name cards already used.

- Both sides of a cut are the same time, so they round to the same frame: no gap, no
  overlap, nothing dropped or repeated. Each affected cut moves by at most half a frame
  (20 ms at 25 fps).
- Narration audio, sound-bite audio, SRT timing and Beat parsing are unchanged. Audio is
  placed by time, not by these frame numbers.
- The older strict script-review check (`/strict-cut-check`) still reports a half-frame
  time, now with the time and frame rate in the message.

## Cutaway approval

If the picture plan itself has a problem that no cutaway can fix, Approve selected now
says so once at the top ("No cutaway can be approved until the picture plan is fixed
(Render MP4 needs this too): …"). Before, v23 showed it on every row.

## Tested

- A real Beat-built project with all footage at 25 fps and a cut at 8.020 s
  (frame 200.5). v23: "time is exactly halfway…", no picture plan. v24: plan OK, cuts
  contiguous (the cut lands on frame 201 on both sides), final render 625 frames at 25 fps = 25.0 s.
- The same project with cutaways at 25 fps: the photo and the video cutaway inside the
  sound bite were approved; the one outside it was refused with its reason; the render
  completed.

## Files

Changed: `strict_cuts.py`, `documentary_render_plan.py`, `documentary_frame_audit.py`,
`documentary_strict.py`, `app.py`, `verified_launch.py`, `tests/test_cutaway_approve_v23.py`.
New: `tests/test_half_frame_v24.py`, this file.
