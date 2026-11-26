"""Conservative motion suggestions for verified still-image shots in a Beat documentary.

The documentary script remains authoritative. This module does not identify people,
detect visual content, change an image, or infer that an image is authentic. A camera
suggestion may only change how an existing, independently approved still is framed.
"""
from __future__ import annotations

import re

import cinematic
import transitions

EXCLUDE_WORDS = ('charging document', 'court document', 'text message', 'screenshot',
                 'photo grid', 'photo panel', 'protected minor', 'juvenile', 'evidence exhibit',
                 'headline', 'graphic', 'diagram', 'map', 'nameplate')

PHOTO_CARRIER = re.compile(r'^P\d{2,}_.+_video\.(?:mp4|mov)$', re.I)


def still_visual_kind(asset, shot=None):
    """Classify an existing visual that should receive restrained photo motion.

    This is metadata-based and never claims to recognise picture content. V11.7
    permits original images, P##_..._video photo carriers, and explicitly mapped
    native static intervals to receive the same lossless timeline camera move.
    """
    kind = str((asset or {}).get('kind') or '').lower()
    if kind in ('image', 'photo'):
        return 'uploaded_photo'
    if kind != 'video':
        return ''
    name = str((asset or {}).get('original_name') or (asset or {}).get('name') or '')
    if PHOTO_CARRIER.fullmatch(name):
        return 'photo_carrier_video'
    rows = [(scene.get('plan_row') or {}) for scene in (shot or [])]
    if rows and all(row.get('native_static_interval') for row in rows):
        return 'native_static_interval'
    return ''


def suggest_still_cameras(project):
    """Continuous motion on photos, photo-carrier clips and native still intervals."""
    return suggest_story_cameras(project, 'cinematic', only_stills=True)


def suggest_story_cameras(project, style='cinematic', only_stills=False):
    """Auto direct picture motion across eligible narration shots.

    The map contains one independent entry per SRT-derived scene. Its segments
    are sampled from ONE shot-wide curve, so each subtitle start resumes exactly
    where the preceding segment ended. Neither the source file nor its range,
    picture subject, film timing, audio, approval, or SRT is changed.

    No semantic image recognition is claimed: motion is conservative and avoided
    for soundbite audio, sensitive documents, and any manually directed shot.
    """
    if style in ('truecrime', 'restrained') and not only_stills:
        return suggest_still_cameras(project)
    scenes = project.get('scenes') or []
    assets = {a.get('id'): a for a in project.get('assets') or []}
    cuts = transitions.documentary_cuts(scenes)
    starts = [0] + [i + 1 for i in cuts]
    ends = [i + 1 for i in cuts] + [len(scenes)]
    result = {}
    eligible = []   # still-photo shots, in film order, for the varied photo sequence
    for start, end in zip(starts, ends):
        shot = scenes[start:end]
        if not shot or any(transitions.scene_kind(s) != 'narration' for s in shot):
            continue
        asset = assets.get(shot[0].get('asset_id')) or {}
        kind = asset.get('kind')
        still_kind = still_visual_kind(asset, shot)
        if kind not in ('video', 'image', 'photo') or (only_stills and not still_kind):
            continue
        # Do not rewrite a human-specified, locked, or script-specific camera.
        if any(s.get('camera_locked') or s.get('script_camera') or
               (s.get('camera') and (s['camera'].get('origin') != 'auto' or s['camera'].get('locked')))
               or s.get('motion') not in (None, 'auto', 'static') for s in shot):
            continue
        duration_frames = sum(max(0, int(s.get('frame_out') or 0) - int(s.get('frame_in') or 0)) for s in shot)
        duration = duration_frames / 30.0
        if duration < (2.5 if still_kind else 2.0) or duration > (90 if still_kind else 28):
            continue
        text = ' '.join(transitions._story_text(s) for s in shot)
        if any(word in text for word in EXCLUDE_WORDS) or transitions._has_any(
                text, ('document', 'exhibit', 'screenshot', 'bodycam text', 'caption', 'subtitles',
                       'police interview', 'interviewee', 'talking head', 'court hearing', 'court record')):
            continue
        # Only mildly reframe existing news footage: original source moving video
        # can already be active. Even dynamic mode never zooms a source > ~7%.
        strong = style == 'dynamic' and bool(still_kind)
        strength = 'medium' if strong else 'subtle'
        if still_kind:
            # Stills are chosen together below, so neighbours never move the same way.
            eligible.append((shot, text, duration_frames, strength))
            continue
        pool = ('zoom_in', 'zoom_out', 'push_right', 'push_left')
        # Stable choice based on the source and narration rather than random motion.
        import hashlib
        seed = (str(shot[0].get('asset_id')) + '|' + str(shot[0].get('frame_in')) +
                '|' + text[:160]).encode('utf-8')
        direction = pool[hashlib.sha256(seed).digest()[0] % len(pool)]
        _apply_shot_camera(result, shot, direction, strength, duration_frames)
    if eligible:
        import photo_motion
        from person_overlays import settings as photo_settings
        conf = photo_settings(project)
        strength = conf.get('photo_motion_intensity') or 'medium'
        moves = photo_motion.plan_moves(
            [{'text': text, 'duration_ms': frames * 1000 // 30} for _, text, frames, _ in eligible],
            seed=str(project.get('id') or ''), fixed_camera=_fixed_camera(project), intensity=strength)
        for (shot, text, frames, _), move in zip(eligible, moves):
            direction = move.get('camera_preset')
            if direction:
                _apply_shot_camera(result, shot, direction, strength, frames,
                                   reason=f"Photo move: {move['label']}.")
    return result


def _fixed_camera(project):
    from person_overlays import settings as photo_settings
    mode = photo_settings(project).get('photo_motion') or 'auto_story'
    if mode == 'none':
        mode = 'auto_story'
    return None if mode == 'auto_story' else mode


def _apply_shot_camera(result, shot, direction, strength, duration_frames, reason=None):
    try:
        cam = cinematic.normalise(cinematic.preset(direction, strength))
    except ValueError:
        return
    cam['origin'] = 'auto'
    cam['reason'] = reason or 'Shot-wide, SRT-synchronized cinematic move; picture identity not inferred.'
    # Finish an intentional move, then hold its final composition. Stretching a
    # tiny pan across a long cue reads as generic dragging and lagging.
    import photo_motion
    moving_frames = photo_motion.active_frames(duration_frames, strength)
    cam['reason'] += f' {strength.title()} move settles in {moving_frames / 30:.2f}s.'
    # Piecewise interpolation of ONE shot-wide curve. The exact same endpoint is
    # assigned to both sides of each cue split: no reset or subtitle-boundary jump.
    offset = 0
    for scene in shot:
        n = int(scene['frame_out']) - int(scene['frame_in'])
        p0 = cinematic.progress(offset, moving_frames)
        p1 = cinematic.progress(offset + n - 1, moving_frames)
        z0,x0,y0 = cinematic.window(cam,p0)
        z1,x1,y1 = cinematic.window(cam,p1)
        # If the move completes inside this scene, record the exact local point
        # where it finishes so preview and export hold the final composition.
        remaining = moving_frames - 1 - offset
        local_motion_end = min(1.0, max(0.05, remaining / max(1, n - 1))) if 0 <= remaining < n - 1 else 1.0
        part = cinematic.normalise({'zoom_start':round(z0*100, 2), 'zoom_end':round(z1*100, 2),
            'x_start':x0,'y_start':y0,'x_end':x1,'y_end':y1,
            'easing':'linear','origin':'auto',
            **({'motion_end':local_motion_end} if local_motion_end < 1 else {}),
            **({'preset':direction} if direction != 'portrait_reveal' else {}),
            'reason':cam['reason']})
        result[scene['id']] = part
        offset += n

