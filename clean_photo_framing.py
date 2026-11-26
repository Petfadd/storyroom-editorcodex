"""Clean framing of still photos, especially news screen grabs (v17).

A screen grab of a news report usually shows the real photo in the middle, with
side panels around it: black bars, or a blurred copy of the same photo, often
carrying channel logos (FOX 26, KHOU 11, ...), sometimes a ticker along the bottom.

`detect_box` finds the sharp photo inside such a grab by its straight edges and by
the panels around it being flat (black or blurred). Only those panels are cut away.
Nothing is painted over, erased or invented: a logo that sits INSIDE the actual photo
stays. When the edges are not certain, the picture is kept whole, and the person can
set the crop by hand (Adjust crop).

`frame_still` then places the clean photo in the centre of the frame, over a blurred,
darkened copy of that same clean photo, so no news graphics or black bars show.

Crop settings stored with a photo or image asset:
    None / {'mode': 'auto'}            automatic detection (the default)
    {'mode': 'manual', 'box': [x0, y0, x1, y1]}   fractions of the original image
    {'mode': 'none'}                   always the whole image
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

VERSION = 'v20-framed-portrait'
ANALYSIS_SIZE = 480


# ----------------------------------------------------------------------------- detection

def _np():
    try:
        import numpy
        return numpy
    except ImportError:          # numpy comes with OpenCV; without it, keep photos whole
        return None


def _maps(image):
    """Grey levels, colour gradient strength and fine detail at analysis size."""
    np = _np()
    w, h = image.size
    s = min(1.0, ANALYSIS_SIZE / max(w, h))
    small = image.convert('RGB').resize((max(8, round(w * s)), max(8, round(h * s))), Image.Resampling.BOX)
    rgb = np.asarray(small, dtype=np.float32)
    grey = np.asarray(small.convert('L'), dtype=np.float32)
    soft = np.asarray(small.convert('L').filter(ImageFilter.GaussianBlur(1.6)), dtype=np.float32)
    detail = np.abs(grey - soft)
    return small.size, rgb, detail


def _seams(rgb, axis):
    """Per position along `axis`: share of lines crossing a straight edge there.

    axis=1 looks for vertical edges (columns), axis=0 for horizontal edges (rows).
    An edge between positions i-1 and i counts for i. Bilinear-ish downscaling can
    spread one edge over two positions, so neighbouring pairs are merged.
    """
    np = _np()
    diff = np.abs(np.diff(rgb, axis=axis)).max(axis=2)          # strongest channel
    if axis == 0:
        diff = diff.T                                           # rows become columns
    # diff[:, i] is the step between i and i+1 -> edge position i+1
    hit = diff >= 9
    pair = np.zeros(diff.shape[1] + 1, dtype=np.float32)
    strength = np.zeros_like(pair)
    if diff.shape[1] >= 2:
        both = hit[:, :-1] | hit[:, 1:]
        pair[1:-1][:both.shape[1]] = both.mean(axis=0)
        strength[1:-1][:both.shape[1]] = np.maximum(diff[:, :-1], diff[:, 1:]).mean(axis=0)
    return pair, strength


def _detail_profile(detail, axis, lo, hi):
    """Detail per column (axis=1) or row (axis=0), robust to logos: 70th percentile."""
    np = _np()
    band = detail[lo:hi, :] if axis == 1 else detail[:, lo:hi].T
    if band.size == 0:
        return np.zeros(detail.shape[1] if axis == 1 else detail.shape[0], dtype=np.float32)
    return np.percentile(band, 70, axis=0)


def _peaks(score, lo, hi, limit=10, floor=0.30):
    """Local maxima of `score` inside [lo, hi), strongest first."""
    out = []
    for i in range(max(1, lo), min(len(score) - 1, hi)):
        if score[i] >= floor and score[i] >= score[i - 1] and score[i] >= score[i + 1]:
            out.append(i)
    out.sort(key=lambda i: -score[i])
    return out[:limit]


def _flat(profile, a, b):
    """Mean detail over [a, b), or None when that span is empty."""
    if b - a < 1:
        return None
    return float(profile[a:b].mean())


def _uniform(rgb, x0, x1, y0, y1):
    """True when a region is one plain colour (black bar, solid graphic panel)."""
    region = rgb[y0:y1, x0:x1]
    if region.size == 0:
        return False
    return float(region.reshape(-1, 3).std(axis=0).max()) < 7.5


def _columns(rgb, detail):
    """(left, right, score) of the sharp photo between flat side panels, or None.

    Panels on BOTH sides may be black, a plain colour or a blurred copy of the photo
    (the usual news layout). A panel on ONE side only must be plain: a blurred or
    textured strip on one side is too easily part of the real picture.
    """
    np = _np()
    h, w = detail.shape
    seam, _ = _seams(rgb, 1)
    prof = _detail_profile(detail, 1, round(h * .06), round(h * .94))
    margin = max(2, round(w * .012))
    lefts = [0] + _peaks(seam, round(w * .03), round(w * .47))
    rights = [w] + _peaks(seam, round(w * .53), round(w * .975))
    best = None
    for l in lefts:
        for r in rights:
            if l == 0 and r == w:
                continue
            if r - l < w * .24:
                continue
            inside = _flat(prof, l + margin, r - margin)
            if not inside:
                continue
            ok, score, sides = True, 0.0, []
            one_sided = l == 0 or r == w
            # Graphic side panels (stripes, patterns) are not flat, but a photo framed by
            # two dead-straight, full-height edges placed symmetrically is a broadcast
            # inset all the same.
            framed = (not one_sided and seam[l] >= .9 and seam[r] >= .9 and
                      abs((l + r) / 2 - w / 2) <= w * .03 and .25 * w <= r - l <= .75 * w)
            for a, b, edge in ((0, l - margin, l), (r + margin, w, r)):
                if edge in (0, w):
                    continue                                   # photo reaches the frame edge here
                if one_sided and not _uniform(rgb, a, b, round(h * .04), round(h * .96)):
                    ok = False; break
                if b - a < w * .025:
                    ok = False; break                          # a "panel" this thin is not one
                side = _flat(prof, a, b)
                if side is None:
                    ok = False; break
                if not framed and (side > 1.6 or side > inside * .42):
                    ok = False; break                          # real picture continues: not a panel
                if seam[edge] < .42:
                    ok = False; break                          # no straight edge along the photo
                score += seam[edge] + max(0.0, 1 - side / inside)
                sides.append(side)
            if not ok:
                continue
            centre = abs((l + r) / 2 - w / 2) / w
            score -= centre * 1.5
            if best is None or score > best[2]:
                best = (l, r, score, max(sides))
    return best


def _inner(seam, edge, step, reach):
    """Move an edge inwards past a thin frame line drawn around the photo."""
    best = edge
    for k in range(1, reach + 1):
        i = edge + step * k
        if 0 < i < len(seam) - 1 and seam[i] >= .6:
            best = i
    return best


def _rows(rgb, detail, l, r, side_detail=None):
    """(top, bottom) inside columns l..r: drop black bars and banners.

    A bar is plain (letterbox black, a solid strip). A ticker or banner with text is
    accepted only when its straight edge also runs across the side panels, i.e. it
    is laid over the whole broadcast frame. A straight line inside the photo itself
    (a horizon, a table edge) never cuts the picture.
    """
    np = _np()
    h, w = detail.shape
    sub_rgb = rgb[:, l:r]
    seam, _ = _seams(sub_rgb, 0)
    full, _ = _seams(rgb, 0)
    panels = l > 0 or r < w
    margin = max(2, round(h * .012))
    prof = _detail_profile(detail[:, l:r], 0, 0, r - l) if side_detail is not None else None

    def like_panels(a, b):
        # Above/below the photo continues the same blurred surround as the side panels.
        if prof is None or b - a < 1:
            return False
        band = float(prof[a:b].mean())
        return band <= .8 and band <= max(side_detail * 1.3, .35)

    top, bottom = 0, h
    for t in _peaks(seam, round(h * .02), round(h * .30), floor=.55):
        if t - margin >= h * .015 and (_uniform(sub_rgb, 0, r - l, 0, t - margin) or like_panels(0, t - margin) or
                                       (panels and seam[t] >= .9 and full[t] >= .8)):
            top = t; break
    for b in _peaks(seam, round(h * .62), round(h * .985), floor=.55):
        if h - b - margin >= h * .015 and (_uniform(sub_rgb, 0, r - l, b + margin, h) or like_panels(b + margin, h) or
                                           (panels and seam[b] >= .85 and full[b] >= .8)):
            bottom = b; break
    reach = max(1, round(h * .015))
    if top:
        top = _inner(seam, top, 1, reach)
    if bottom < h:
        bottom = _inner(seam, bottom, -1, reach)
    return top, bottom


def detect_box(image):
    """(x0, y0, x1, y1) of the sharp photo inside a screen grab, in original pixels.

    None when no reliable panels or bars were found: the image is then used whole.
    """
    np = _np()
    if np is None:
        return None
    image = image.convert('RGB')
    W, H = image.size
    if W < 120 or H < 90:
        return None
    (w, h), rgb, detail = _maps(image)
    cols = _columns(rgb, detail)
    l, r = (cols[0], cols[1]) if cols else (0, w)
    if cols:
        seam, _ = _seams(rgb, 1)
        reach = max(1, round(w * .01))
        l = _inner(seam, l, 1, reach) if l > 0 else 0
        r = _inner(seam, r, -1, reach) if r < w else w
    t, b = _rows(rgb, detail, l, r, cols[3] if cols else None)
    if (l, r, t, b) == (0, w, 0, h):
        return None
    if (r - l) < w * .22 or (b - t) < h * .5:
        return None
    sx, sy = W / w, H / h
    # Step a little inside every cut edge: keeps a seam's soft pixels, thin outline or
    # shadow out of the picture.
    px = max(2, round((r - l) * sx * .006))
    py = max(2, round((b - t) * sy * .006))
    x0 = round(l * sx) + (px if l > 0 else 0)
    x1 = round(r * sx) - (px if r < w else 0)
    y0 = round(t * sy) + (py if t > 0 else 0)
    y1 = round(b * sy) - (py if b < h else 0)
    if x1 - x0 < 32 or y1 - y0 < 32:
        return None
    return (x0, y0, x1, y1)


# ----------------------------------------------------------------------------- crop

def normalise_crop(crop):
    """A safe crop setting (see module notes), or None for automatic."""
    if not isinstance(crop, dict):
        return None
    mode = crop.get('mode')
    if mode == 'none':
        return {'mode': 'none'}
    if mode == 'manual':
        box = crop.get('box')
        try:
            x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in box)
        except (TypeError, ValueError):
            return None
        if x1 - x0 < .05 or y1 - y0 < .05:
            return None
        return {'mode': 'manual', 'box': [round(x0, 5), round(y0, 5), round(x1, 5), round(y1, 5)]}
    return None


def crop_token(crop):
    """Short text that changes whenever the crop result could change (for cache keys)."""
    c = normalise_crop(crop)
    if c is None:
        return 'auto-' + VERSION
    if c['mode'] == 'none':
        return 'whole'
    return 'manual-' + ','.join(f'{v:.5f}' for v in c['box'])


def clean_portrait(image, crop=None):
    """(photo, metadata). The original pixels are never changed, only selected."""
    photo = ImageOps.exif_transpose(image).convert('RGB')
    c = normalise_crop(crop)
    W, H = photo.size
    if c and c['mode'] == 'none':
        return photo, {'cropped': False, 'mode': 'none', 'reason': 'Whole image chosen by hand'}
    if c and c['mode'] == 'manual':
        x0, y0, x1, y1 = c['box']
        box = (round(x0 * W), round(y0 * H), round(x1 * W), round(y1 * H))
        return photo.crop(box), {'cropped': True, 'mode': 'manual', 'box': box, 'reason': 'Crop set by hand'}
    try:
        box = detect_box(photo)
    except Exception as error:                 # never let a detector problem stop an export
        return photo, {'cropped': False, 'mode': 'auto', 'reason': f'Detection failed: {error}'[:160]}
    if not box:
        return photo, {'cropped': False, 'mode': 'auto', 'reason': 'No news panels or black bars found'}
    return photo.crop(box), {'cropped': True, 'mode': 'auto', 'box': box,
                             'reason': 'Side panels / bars around the photo were cut away'}


def describe(image, crop=None):
    """Crop result as fractions, for the Adjust crop window."""
    photo = ImageOps.exif_transpose(image).convert('RGB')
    W, H = photo.size
    _, meta = clean_portrait(photo, crop)
    box = meta.get('box') or (0, 0, W, H)
    try:
        auto = detect_box(photo)
    except Exception:
        auto = None
    frac = lambda b: [round(b[0] / W, 5), round(b[1] / H, 5), round(b[2] / W, 5), round(b[3] / H, 5)] if b else None
    return {'mode': meta.get('mode', 'auto'), 'cropped': meta['cropped'], 'reason': meta['reason'],
            'box': frac(box), 'auto_box': frac(auto), 'width': W, 'height': H}




# ----------------------------------------------------------------------------- framing

def photo_rect(photo_size, width, height, inset=False):
    """(x, y, w, h) of a photo fitted whole and centred in a canvas.

    ``inset`` is the documentary portrait treatment: the original picture remains
    completely visible inside a clean central card instead of touching the edges.
    """
    w, h = photo_size
    if not inset and abs((w / h) / (width / height) - 1) <= .03:
        return 0, 0, width, height
    max_w = width * (.86 if w / h >= 1.2 else .72)
    max_h = height * .86
    fit = min((max_w if inset else width) / w, (max_h if inset else height) / h)
    pw, ph = max(1, round(w * fit)), max(1, round(h * fit))
    return (width - pw) // 2, (height - ph) // 2, pw, ph


def blur_fill(photo, width, height, focus_y=.5):
    """A blurred, darkened copy of the photo covering the whole frame."""
    w, h = photo.size
    # Blur at a small size: identical look, a fraction of the work.
    small_w = max(64, width // 4); small_h = max(36, height // 4)
    c = max(small_w / w, small_h / h)
    back = photo.resize((max(1, round(w * c)), max(1, round(h * c))), Image.Resampling.BILINEAR)
    left = (back.width - small_w) // 2
    top = round((back.height - small_h) * max(0.0, min(1.0, focus_y)))
    back = back.crop((left, top, left + small_w, top + small_h)).filter(ImageFilter.GaussianBlur(max(4, small_w // 40)))
    back = back.resize((width, height), Image.Resampling.BICUBIC)
    return ImageEnhance.Brightness(back).enhance(.55)


def already_framed(image):
    """True only for an existing 16:9 blurred-backdrop card with a white outline.

    This prevents an already prepared photograph from being placed inside a second
    frame.  The test is deliberately strict: ordinary bright images and white shirts
    do not form two long vertical and two long horizontal border lines.
    """
    np = _np()
    if np is None:
        return False
    image = ImageOps.exif_transpose(image).convert('RGB')
    w, h = image.size
    if w < 320 or h < 180 or abs(w / h - 16 / 9) > .08:
        return False
    small = image.resize((480, 270), Image.Resampling.BILINEAR)
    rgb = np.asarray(small, dtype=np.int16)
    # A 4-6 px keyline becomes roughly one antialiased pixel at analysis size,
    # so accept its grey edge while still requiring four long, straight runs.
    white = (rgb.min(axis=2) >= 180) & ((rgb.max(axis=2) - rgb.min(axis=2)) <= 65)
    col = white.mean(axis=0); row = white.mean(axis=1)
    left = [i for i in range(48, 216) if col[i] >= .52]
    right = [i for i in range(264, 432) if col[i] >= .52]
    top = [i for i in range(8, 108) if row[i] >= .24]
    bottom = [i for i in range(162, 262) if row[i] >= .24]
    if not (left and right and top and bottom):
        return False
    x0, x1, y0, y1 = left[len(left)//2], right[len(right)//2], top[len(top)//2], bottom[len(bottom)//2]
    return x1-x0 >= 100 and y1-y0 >= 120


def frame_still(photo, width, height, focus_y=.5):
    """A clean central photo card over a soft copy of the same source.

    The foreground never stretches or crops.  A restrained white keyline and soft
    shadow separate it from the background, matching the monitor and final export.
    Returns ``(frame, inner_photo_rect)``.
    """
    if already_framed(photo):
        return photo.resize((width, height), Image.Resampling.LANCZOS), (0, 0, width, height)
    x, y, pw, ph = photo_rect(photo.size, width, height, inset=True)
    frame = blur_fill(photo, width, height, focus_y)
    front = photo.resize((pw, ph), Image.Resampling.LANCZOS)
    border = max(2, round(min(width, height) * .0045))
    card = ImageOps.expand(front, border=border, fill=(246, 246, 244))
    card_x, card_y = x - border, y - border
    shadow_pad = max(8, round(min(width, height) * .022))
    shadow = Image.new('RGBA', (card.width + shadow_pad * 2, card.height + shadow_pad * 2), (0, 0, 0, 0))
    mask = Image.new('L', card.size, 170)
    shadow.paste((0, 0, 0, 170), (shadow_pad, shadow_pad), mask)
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(4, shadow_pad // 2)))
    frame = frame.convert('RGBA')
    frame.alpha_composite(shadow, (card_x - shadow_pad + max(2, border), card_y - shadow_pad + max(3, border)))
    frame.paste(card, (card_x, card_y))
    frame = frame.convert('RGB')
    return frame, (x, y, pw, ph)


def framed_image_file(image, destination, width, height, crop=None):
    """Frame an already decoded PIL image without altering its source pixels."""
    dest = Path(destination)
    original = ImageOps.exif_transpose(image).convert('RGB')
    if already_framed(original):
        frame = original.resize((width, height), Image.Resampling.LANCZOS)
        detail = {'cropped': False, 'mode': 'existing-frame',
                  'reason': 'Existing blurred-background photo card preserved'}
    else:
        clean, detail = clean_portrait(original, crop)
        frame, _ = frame_still(clean, width, height)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(dest.stem + '.part.jpg')
    frame.save(temp, format='JPEG', quality=94)
    temp.replace(dest)
    return detail


def framed_still_file(source, destination, width, height, crop=None):
    """Clean + centred still at the output size, as a JPEG (cached by the caller)."""
    dest = Path(destination)
    with Image.open(source) as im:
        return framed_image_file(im, dest, width, height, crop)
