# Storyroom v23: cutaway approval

Build `2026-11-22-cutaway-approve-v23`.

## Why "Activate all reviewed picture cutaways" did nothing

Two problems together:

1. **Photo cutaways could never be approved.** The cutaway check only accepted files from
   the project's `sources` folder, which is where uploaded videos are kept. Uploaded
   photographs are kept in `assets`, so any row with a `.jpg`/`.png` picture
   (for example B03.jpg, B04.jpg) was refused with "only a genuinely uploaded picture
   file can be a cutaway". The test data had put its photo in `sources`, so the tests
   never caught it.
2. **All or nothing.** "Activate all" sent every row in one request. One refused row
   refused the whole request, so not a single row was activated. The reason only
   appeared in a toast, which was easy to miss.

## What changed

- Photos are accepted from `assets` (videos still from `sources`; files outside the
  project are still refused).
- Documentary tools › Interview picture cutaways:
  - each row has a tick box. Ticking only selects the row; it no longer approves it
    on its own;
  - a **Select all** box at the top (it shows a dash when only some rows are ticked);
  - **Approve selected (N)**: one confirmation, then every ticked row that passes the
    checks is approved;
  - a row that cannot be approved stays off and stays ticked, with the reason in red
    under it (for example "picture range is 3.000s but film window is 5.000s;
    correct IN/OUT");
  - **Turn off selected** puts the speaker's picture back for the ticked rows;
  - *Clear cutaway plan* is unchanged.
- New route `POST /api/projects/<id>/documentary-cutaways/approve` with
  `{"ids": [...], "approved": true|false}`. It tries all ticked rows at once. If any row
  fails, it adds them one at a time in film order and keeps each one that passes. If the
  picture plan itself has a problem that blocks every cutaway, it says so once instead of
  blaming each row.

## Not changed

The cutaway file format, the import, the checks (same Beat, inside one sound bite, file
present, picture range equals film window, no overlaps), the interview audio, the
narration, the SRT and the film clock.

## Files

- Changed: `documentary_cutaways.py`, `app.py`, `static/documentary.js`, `static/editor.css`,
  `verified_launch.py`.
- New: `tests/test_cutaway_approve_v23.py`, `tests/test_cutaway_select_v23.js`, this file.
