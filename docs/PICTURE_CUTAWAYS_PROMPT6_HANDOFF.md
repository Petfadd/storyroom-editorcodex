# Storyroom V8.9 → 8004 v10: Approved soundbite picture-cutaway handoff

**This addendum supersedes the older V8.9 statements that selective picture-only cutaways are not implemented, but ONLY when the installed Storyroom build reports `2026-11-21-picture-cutaways-v10` or later.** Older editor builds must retain the native speaker shot throughout the soundbite.

## Non-negotiable documentary rules

1. Keep every approved long interview, press briefing or testimony as one continuous `DOCUMENTARY SOUND BITE` Beat with its real original source video, IN/OUT and **uninterrupted, unmodified original speech**. Do not create extra audio or VO Beats for B-roll inserts.
2. Prepare case-specific cutaways only at meaningful, evidenced visual references. The original speaker is the default picture. Select the actual verified footage/photo and source-local IN/OUT; mute the cutaway's own audio. Return to the speaker at the stated film-master OUT. Never cover an entire interview with unrelated B-roll.
3. Provide ONE separate companion file named `CUTAWAY_PICTURE_HANDOFF.json` in the Prompt 6 final package alongside the authoritative production script, final footage inventory and source map. It is imported via **Documentary tools → Interview picture cutaways**. The main script stays valid under the existing Beat parser.
4. `timeline_in`, `timeline_out` are **film-master** timestamps, not narrator-only SRT, source-video time, or extracted B## local time. `source_in`, `source_out` are times **inside the uploaded cutaway picture file**. MP4 ranges must cover the full picture window. For a JPG/PNG/WebP, omit picture IN/OUT or mark N/A.
5. The `soundbite_beat` must be the Beat number of the genuine audio-bearing source. Set `speaker_source` to that Beat's exact `S##.mp4` filename as an additional identity check.
6. `picture_source` must match exactly the **actual uploaded** filename, e.g., S13.mp4 or B07.jpg. Never use a URL in place of a local filename. Use original inspected footage, not the benchmark's unverified pictures, generic stock or invented reenactments.
7. Set `approved: false` on every proposed row until the source picture, case context, rights/provenance, timecodes and return-to-speaker interval have been reviewed. The user may activate them in Storyroom singly or together. A user-approved false row remains the original speaking video; this is not an export failure.
8. Picture-only cutaways must NOT interrupt interviews, change narration pauses, alter the film duration, duck audio, insert soundtrack, overwrite subtitles, or trigger a full Beat rebuild.
9. Validate in a short accurate MP4 preview that the speaker → source picture → speaker sequence appears in the intended film-clock positions while the original speaker audio stays continuous. **Code-level passing tests do not independently verify the user's real clips or rights.**

## Canonical JSON for Prompt 6

```json
{
  "version": 1,
  "cutaways": [
    {
      "id": "CUTAWAY-001",
      "soundbite_beat": "028",
      "speaker_source": "S_SPEAKER.mp4",
      "timeline_in": "00:03:00.000",
      "timeline_out": "00:03:08.000",
      "picture_source": "S_VERIFIED_PICTURE.mp4",
      "source_in": "00:00:20.000",
      "source_out": "00:00:28.000",
      "reason": "EXAMPLE ONLY — exact verified quote/claim and visual proof required",
      "approved": false
    }
  ]
}
```

**The example above contains placeholders; do NOT import it as real approved footage.**

### Optional Markdown table accepted by Storyroom

`| ID | Soundbite Beat | Speaker File | Film IN | Film OUT | Picture File | Picture IN | Picture OUT | Approved | Reason |`

A still photo uses `N/A` in both Picture IN and Picture OUT. The corresponding JSON key for speaker file is `speaker_source`.

### Final Prompt 6 QA checklist

- Every cutaway overlaps **exactly one** actual soundbite Beat, never narration.
- All picture sources exist in the approved, uploaded filename inventory; dates and people match the claim.
- The picture clip duration matches its film-master placement, allowing only normal output-frame quantization; source bounds never exceed source video.
- Explicit human sign-off has been recorded and the original uninterrupted source audio checked by listening across at least one cutaway.
- The rendered film's frame count and audio duration are unchanged when the cutaway schedule is enabled.
- Missing, unsuitable or unverified picture sources remain `MISSING` or unapproved; the real speaker remains visible.
- Original soundbite replay later is allowed, but a distinct film-clock cutaway must be supplied for each playback position where desired.
