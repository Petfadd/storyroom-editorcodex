"""Still pictures in an ffmpeg graph, decoded once (v19).

`-loop 1 -framerate R -i picture` makes ffmpeg read and decode the picture again for
every output frame. For a full-frame 1080p photo that was most of the cost of a piece:
an overlay of one still took three times as long as the footage under it. The `loop`
filter keeps the one decoded frame in memory and repeats it instead, with exactly the
same timestamps.
"""


def frame_tb(rate):
    """The time base one frame long at `rate` ('30/1' -> '1/30', '30000/1001' -> '1001/30000')."""
    from fractions import Fraction
    r = Fraction(str(rate))
    return f'{r.denominator}/{r.numerator}'


def hold(rate, frames, offset_frames=0):
    """Filter text repeating a single decoded picture for `frames` frames at `rate`,
    timed from frame `offset_frames` of the film clock.

    The time base is set to exactly one frame first. A picture's own time base (1/25
    for an image file) cannot hold 1/30 s steps: the timestamps rounded onto each
    other and the overlay lost the last frame of a photo.
    """
    frames = max(1, int(frames))
    return (f'loop=loop=-1:size=1,trim=end_frame={frames},settb={frame_tb(rate)},'
            f'setpts=N+{int(offset_frames)}')


def held_source(rate):
    """Prefix for a still used as the main picture of a shot (same reasoning as hold)."""
    return f'loop=loop=-1:size=1,settb={frame_tb(rate)},setpts=N,'


_BOXES = {}


def opaque_box(path):
    """(x, y, w, h) of the visible part of a transparent layer, even-aligned, or None.

    A name graphic is drawn on a full-frame transparent canvas; overlaying only the
    part that has pixels is the same picture for a fraction of the work.
    """
    from pathlib import Path
    from PIL import Image
    p = Path(path)
    try:
        stat = p.stat()
    except OSError:
        return None
    key = (str(p), stat.st_mtime_ns, stat.st_size)
    if key not in _BOXES:
        with Image.open(p) as im:
            box = im.getchannel('A').getbbox() if im.mode in ('RGBA', 'LA') else None
            size = im.size
        if box:
            x0, y0 = box[0] // 2 * 2, box[1] // 2 * 2
            x1, y1 = min(size[0], -(-box[2] // 2) * 2), min(size[1], -(-box[3] // 2) * 2)
            box = (x0, y0, x1 - x0, y1 - y0)
        _BOXES[key] = box
    return _BOXES[key]
