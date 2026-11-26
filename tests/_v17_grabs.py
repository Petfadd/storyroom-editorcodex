"""Synthetic broadcast screen grabs built from real photos (skimage sample data).

Each case: (name, PIL image, expected box or None). Box is (x0, y0, x1, y1) of the
sharp photo inside the grab; None means the image must be left whole.
"""
import io
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
try:
    from skimage import data
except ImportError:                       # not installed on every PC: use built-in detail
    data = None

FONT = str(__import__('pathlib').Path(__file__).resolve().parents[1] / 'static' / 'fonts' / 'Montserrat-ExtraBold.ttf')


def photo(name):
    if data is None:
        # Natural-looking texture: soft shapes at several scales plus fine grain.
        sizes = {'astronaut': (512, 512), 'coffee': (600, 400), 'chelsea': (451, 300), 'camera': (512, 512), 'rocket': (640, 427)}
        w, h = sizes[name]
        rng = np.random.default_rng(sum(map(ord, name)))
        img = np.zeros((h, w, 3), np.float32) + rng.uniform(60, 160, 3)
        for scale, amp in ((64, 70), (16, 40), (4, 25)):
            small = rng.normal(0, 1, (max(2, h // scale), max(2, w // scale), 3))
            layer = np.asarray(Image.fromarray(((small - small.min()) / (np.ptp(small) + 1e-6) * 255).astype(np.uint8))
                               .resize((w, h), Image.BICUBIC), np.float32) / 255 - .5
            img += layer * amp * 2
        img += rng.normal(0, 6, (h, w, 3))
        return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    arr = getattr(data, name)()
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, -1)
    return Image.fromarray(arr[..., :3]).convert('RGB')


def portrait(img, ratio=0.78):
    w, h = img.size
    nw = int(h * ratio)
    if nw <= w:
        x = (w - nw) // 2
        return img.crop((x, 0, x + nw, h))
    nh = int(w / ratio)
    return img.crop((0, 0, w, nh))


def logo(d, xy, text, colour, size=46):
    f = ImageFont.truetype(FONT, size)
    x, y = xy
    tw = d.textlength(text, font=f)
    d.rounded_rectangle((x - 14, y - 10, x + tw + 14, y + size + 14), 8, fill=colour)
    d.text((x, y), text, font=f, fill='white')


def jpeg(im, q=82):
    b = io.BytesIO(); im.save(b, 'JPEG', quality=q); b.seek(0)
    return Image.open(b).convert('RGB')


def grab(src, W=1920, H=1080, sides='blur', inset_h=1.0, logos=(), ticker=False, border=0, offset=0, top_bar=0):
    ph = int(H * inset_h)
    pw = int(ph * src.width / src.height)
    sharp = src.resize((pw, ph), Image.LANCZOS)
    if sides == 'black':
        canvas = Image.new('RGB', (W, H), (4, 4, 6))
    elif sides == 'blur':
        s = max(W / src.width, H / src.height) * 1.25
        big = src.resize((int(src.width * s), int(src.height * s)), Image.LANCZOS)
        x, y = (big.width - W) // 2, (big.height - H) // 2
        canvas = big.crop((x, y, x + W, y + H)).filter(ImageFilter.GaussianBlur(40))
        canvas = ImageEnhance.Brightness(canvas).enhance(.7)
    else:  # solid graphic panel
        canvas = Image.new('RGB', (W, H), sides)
    x0 = (W - pw) // 2 + offset
    y0 = (H - ph) // 2 + top_bar // 2
    canvas.paste(sharp, (x0, y0))
    d = ImageDraw.Draw(canvas)
    if border:
        d.rectangle((x0 - border, y0 - border, x0 + pw + border - 1, y0 + ph + border - 1), outline=(235, 235, 235), width=border)
    for (lx, ly, text, colour) in logos:
        logo(d, (lx, ly), text, colour)
    box = [x0, y0, x0 + pw, y0 + ph]
    if ticker:
        th = int(H * .14)
        d.rectangle((0, H - th, W, H), fill=(16, 40, 120))
        d.rectangle((0, H - th, W, H - th + 6), fill=(220, 30, 30))
        d.text((60, H - th + 30), 'BREAKING: SUSPECT ARRESTED IN HOUSTON CASE', font=ImageFont.truetype(FONT, 50), fill='white')
        box[3] = min(box[3], H - th)
    return jpeg(canvas), tuple(box)


def cases():
    out = []
    astro = portrait(photo('astronaut'))
    coffee = portrait(photo('coffee'), .7)
    cat = portrait(photo('chelsea'), .8)
    cam = portrait(photo('camera'), .8)
    rocket = portrait(photo('rocket'), .75)
    L = [(70, 930, 'FOX 26', (120, 40, 170)), (1560, 930, 'KHOU 11', (20, 90, 190))]
    out.append(('blur_sides_logos', *grab(astro, logos=L)))
    out.append(('black_sides_logo', *grab(cam, sides='black', logos=[(1600, 960, 'KHOU 11', (20, 90, 190))])))
    out.append(('blur_sides_cat', *grab(cat, logos=[(80, 70, 'ISIAH', (200, 30, 40))])))
    out.append(('black_sides_coffee', *grab(coffee, sides='black')))
    out.append(('blur_sides_ticker', *grab(rocket, ticker=True, logos=[(70, 60, 'CH 2', (200, 120, 0))])))
    out.append(('border_blur', *grab(astro, border=5, inset_h=.9)))
    out.append(('offcentre_black', *grab(cat, sides='black', offset=-260)))
    out.append(('panel_graphic', *grab(cam, sides=(30, 60, 140), logos=[(80, 80, 'CASE FILE', (200, 30, 40))])))
    out.append(('small_grab_720', *[(lambda im, b: (im.resize((1280, 720), Image.LANCZOS), tuple(round(v * 2 / 3) for v in b)))(*grab(astro))][0]))
    # Must be left whole.
    out.append(('plain_landscape', jpeg(photo('astronaut').resize((1600, 1600)).crop((0, 300, 1600, 1200))), None))
    out.append(('plain_portrait', jpeg(astro), None))
    out.append(('plain_coffee', jpeg(photo('coffee')), None))
    wall = np.asarray(cam)
    wall = np.pad(wall, ((0, 0), (300, 300), (0, 0)), mode='edge')
    out.append(('flat_wall_extension', jpeg(Image.fromarray(wall)), None))
    out.append(('plain_rocket', jpeg(photo('rocket')), None))
    out.append(('plain_cat', jpeg(photo('chelsea')), None))
    return out


def horizon_portrait(w=780, h=1000, seed=3):
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), np.float32)
    hz = int(h * .42)
    sky = np.linspace(200, 150, hz)[:, None, None] * np.array([.75, .88, 1.0])
    img[:hz] = sky + rng.normal(0, 1.2, (hz, w, 3))
    sea = np.array([60, 110, 150]) + rng.normal(0, 18, (h - hz, w, 3))
    img[hz:] = sea
    im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(.6))
    figure = portrait(photo('astronaut'), .78).resize((420, 540))
    im.paste(figure, ((w - 420) // 2, h - 540))
    return im


def more_cases():
    out = []
    hp = horizon_portrait()
    out.append(('horizon_blur_sides', *grab(hp, logos=[(70, 930, 'FOX 26', (120, 40, 170))])))
    sd = photo('astronaut').resize((1440, 1080))
    out.append(('pillarbox_4x3', *grab(sd, sides='black')))
    im, box = grab(portrait(photo('chelsea'), .8), inset_h=.82)
    out.append(('blur_all_round', im, box))
    im, box = grab(portrait(photo('coffee'), .7), logos=[(70, 930, 'FOX 26', (120, 40, 170))])
    out.append(('low_quality_960', jpeg(im.resize((960, 540)), 55), tuple(round(v / 2) for v in box)))
    out.append(('plain_horizon', jpeg(hp), None))
    out.append(('plain_horizon_wide', jpeg(horizon_portrait(1600, 900, 5)), None))
    return out
