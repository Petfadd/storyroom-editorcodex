"""Draw Storyroom's built-in stickers (original artwork) into static/stickers/*.png.

Run once when the designs change:  python tools/make_stickers.py
Every sticker is a transparent PNG drawn at 4x and reduced, so edges stay clean.
"""
from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'static' / 'stickers'
FONT = str(ROOT / 'static' / 'fonts' / 'Montserrat-ExtraBold.ttf')
S = 4  # supersampling
RED = (232, 33, 39, 255); GREY = (96, 96, 96, 255); WHITE = (255, 255, 255, 255)
BLUE = (38, 120, 235, 255); YELLOW = (255, 196, 30, 255); DARK = (20, 20, 22, 255)


def canvas(w, h):
    return Image.new('RGBA', (w * S, h * S), (0, 0, 0, 0))


def font(px):
    return ImageFont.truetype(FONT, int(px * S))


def finish(im, name):
    im = im.resize((im.width // S, im.height // S), Image.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    im.save(OUT / name, optimize=True)


def shadow(im, radius=6, alpha=110, offset=(0, 4)):
    """A soft drop shadow under everything drawn so far (stickers sit on any picture)."""
    a = im.getchannel('A').point(lambda v: v * alpha // 255)
    sh = Image.new('RGBA', im.size, (0, 0, 0, 0)); sh.putalpha(a)
    sh = sh.filter(ImageFilter.GaussianBlur(radius * S))
    base = Image.new('RGBA', im.size, (0, 0, 0, 0)); base.alpha_composite(sh, (offset[0] * S, offset[1] * S))
    base.alpha_composite(im)
    return base


def bell(d, cx, cy, size, fill, ring=False, outline=None):
    s = size * S; cx *= S; cy *= S
    body = [(cx - s * .42, cy + s * .28), (cx - s * .34, cy - s * .05), (cx - s * .30, cy - s * .28),
            (cx - s * .16, cy - s * .43), (cx, cy - s * .47), (cx + s * .16, cy - s * .43), (cx + s * .30, cy - s * .28),
            (cx + s * .34, cy - s * .05), (cx + s * .42, cy + s * .28)]
    d.polygon(body, fill=fill, outline=outline)
    d.rounded_rectangle((cx - s * .5, cy + s * .22, cx + s * .5, cy + s * .34), radius=s * .06, fill=fill)
    d.ellipse((cx - s * .11, cy + s * .34, cx + s * .11, cy + s * .52), fill=fill)
    d.ellipse((cx - s * .07, cy - s * .58, cx + s * .07, cy - s * .44), fill=fill)
    if ring:
        for side in (-1, 1):
            for k, r in enumerate((.62, .78)):
                box = (cx - s * r, cy - s * r * .9, cx + s * r, cy + s * r * .9)
                start, end = (200, 240) if side < 0 else (300, 340)
                d.arc(box, start, end, fill=fill, width=int(s * .07))


def thumb(d, cx, cy, size, fill):
    s = size * S; cx *= S; cy *= S
    d.rounded_rectangle((cx - s * .5, cy - s * .05, cx - s * .26, cy + s * .48), radius=s * .05, fill=fill)
    pts = [(cx - s * .2, cy - s * .05), (cx - s * .02, cy - s * .48), (cx + s * .1, cy - s * .5), (cx + s * .14, cy - s * .38),
           (cx + s * .08, cy - s * .12), (cx + s * .42, cy - s * .12), (cx + s * .5, cy - s * .02), (cx + s * .44, cy + s * .14),
           (cx + s * .47, cy + s * .24), (cx + s * .38, cy + s * .34), (cx + s * .36, cy + s * .48), (cx - s * .2, cy + s * .48)]
    d.polygon(pts, fill=fill)


def cursor(d, x, y, size):
    s = size * S; x *= S; y *= S
    pts = [(x, y), (x, y + s), (x + s * .27, y + s * .76), (x + s * .45, y + s * 1.12), (x + s * .6, y + s * 1.05),
           (x + s * .43, y + s * .7), (x + s * .75, y + s * .7)]
    d.polygon(pts, fill=WHITE, outline=DARK, width=int(S * 2.2))


def share_icon(d, cx, cy, size, fill):
    s = size * S; cx *= S; cy *= S
    pts = [(cx - s * .5, cy + s * .42), (cx - s * .42, cy - s * .05), (cx - s * .1, cy - s * .18), (cx + s * .12, cy - s * .18),
           (cx + s * .12, cy - s * .48), (cx + s * .55, cy - s * .02), (cx + s * .12, cy + s * .44), (cx + s * .12, cy + s * .14),
           (cx - s * .12, cy + s * .14), (cx - s * .36, cy + s * .22)]
    d.polygon(pts, fill=fill)


def pill(d, box, fill, text, size, color=WHITE):
    x0, y0, x1, y1 = [v * S for v in box]
    d.rounded_rectangle((x0, y0, x1, y1), radius=(y1 - y0) / 2, fill=fill)
    d.text(((x0 + x1) / 2, (y0 + y1) / 2 + S), text, font=font(size), fill=color, anchor='mm')


def subscribe(pressed):
    im = canvas(560, 170); d = ImageDraw.Draw(im)
    pill(d, (10, 30, 400, 130), GREY if pressed else RED, 'SUBSCRIBED' if pressed else 'SUBSCRIBE', 40 if pressed else 44)
    d.ellipse((418 * S, 30 * S, 518 * S, 130 * S), fill=WHITE)
    bell(d, 468, 82, 62, GREY if pressed else DARK, ring=pressed)
    if not pressed:
        cursor(d, 338, 100, 58)
    finish(shadow(im), f"subscribe_{'b' if pressed else 'a'}.png")


def like_sub_bell(pressed):
    im = canvas(660, 160); d = ImageDraw.Draw(im)
    d.rounded_rectangle((8 * S, 14 * S, 652 * S, 146 * S), radius=24 * S, fill=WHITE)
    thumb(d, 80, 80, 74, (18, 82, 190, 255) if pressed else BLUE)
    pill(d, (148, 40, 520, 120), GREY if pressed else RED, 'SUBSCRIBED' if pressed else 'SUBSCRIBE', 36 if pressed else 40)
    bell(d, 590, 82, 70, YELLOW, ring=pressed)
    if not pressed:
        cursor(d, 96, 92, 58)
    finish(shadow(im), f"like_sub_bell_{'b' if pressed else 'a'}.png")


def subscribed_row():
    im = canvas(600, 150); d = ImageDraw.Draw(im)
    d.rounded_rectangle((8 * S, 20 * S, 592 * S, 130 * S), radius=20 * S, fill=RED)
    thumb(d, 70, 75, 62, WHITE)
    d.text((300 * S, 77 * S), 'SUBSCRIBED', font=font(40), fill=WHITE, anchor='mm')
    bell(d, 532, 76, 62, WHITE)
    finish(shadow(im), 'subscribed.png')


def share():
    im = canvas(420, 150); d = ImageDraw.Draw(im)
    d.rounded_rectangle((8 * S, 22 * S, 412 * S, 128 * S), radius=53 * S, fill=WHITE)
    share_icon(d, 112, 76, 60, (70, 70, 74, 255))
    d.text((262 * S, 78 * S), 'SHARE', font=font(42), fill=(40, 40, 44, 255), anchor='mm')
    finish(shadow(im), 'share.png')


def comment():
    im = canvas(520, 190); d = ImageDraw.Draw(im)
    d.rounded_rectangle((10 * S, 20 * S, 510 * S, 140 * S), radius=34 * S, fill=WHITE)
    d.polygon([(70 * S, 136 * S), (64 * S, 182 * S), (118 * S, 136 * S)], fill=WHITE)
    for k in range(3):
        d.ellipse(((58 + k * 34) * S, 70 * S, (78 + k * 34) * S, 90 * S), fill=BLUE)
    d.text((330 * S, 82 * S), 'COMMENT', font=font(42), fill=(30, 30, 34, 255), anchor='mm')
    finish(shadow(im), 'comment.png')


def like():
    im = canvas(200, 200); d = ImageDraw.Draw(im)
    d.ellipse((10 * S, 10 * S, 190 * S, 190 * S), fill=BLUE)
    thumb(d, 100, 102, 96, WHITE)
    finish(shadow(im), 'like.png')


def bell_ring(tilt):
    im = canvas(220, 220); d = ImageDraw.Draw(im)
    d.ellipse((12 * S, 12 * S, 208 * S, 208 * S), fill=YELLOW)
    layer = canvas(220, 220); bell(ImageDraw.Draw(layer), 110, 112, 104, WHITE, ring=False)
    layer = layer.rotate(tilt, resample=Image.BICUBIC, center=(110 * S, 50 * S))
    im.alpha_composite(layer)
    finish(shadow(im), f'bell_{"l" if tilt > 0 else "r"}.png')


def rec(on):
    im = canvas(640, 360); d = ImageDraw.Draw(im)
    w = int(9 * S); L = 70 * S
    for (x, y, dx, dy) in ((14, 14, 1, 1), (626, 14, -1, 1), (14, 346, 1, -1), (626, 346, -1, -1)):
        x *= S; y *= S
        d.line((x, y, x + dx * L, y), fill=WHITE, width=w); d.line((x, y, x, y + dy * L), fill=WHITE, width=w)
    if on:
        d.ellipse((60 * S, 52 * S, 96 * S, 88 * S), fill=RED)
    d.text((110 * S, 72 * S), 'REC', font=font(38), fill=WHITE, anchor='lm')
    finish(shadow(im, radius=3, alpha=90, offset=(0, 2)), f'rec_{"on" if on else "off"}.png')


def scribble_arrow(name, flip):
    im = canvas(420, 300); d = ImageDraw.Draw(im)
    pts = []
    for i in range(61):
        t = i / 60
        x = 40 + 300 * t; y = 250 - 190 * math.sin(t * math.pi * .55) - 20 * t
        pts.append((x * S, y * S))
    d.line(pts, fill=RED, width=int(17 * S), joint='curve')
    ex, ey = pts[-1]; px, py = pts[-6]
    ang = math.atan2(ey - py, ex - px)
    for side in (-1, 1):
        a = ang + math.pi - side * .55
        d.line((ex, ey, ex + math.cos(a) * 80 * S, ey + math.sin(a) * 80 * S), fill=RED, width=int(17 * S))
    d.ellipse((ex - 8.5 * S, ey - 8.5 * S, ex + 8.5 * S, ey + 8.5 * S), fill=RED)
    for p in (pts[0],):
        d.ellipse((p[0] - 8.5 * S, p[1] - 8.5 * S, p[0] + 8.5 * S, p[1] + 8.5 * S), fill=RED)
    if flip:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    finish(shadow(im, radius=4, alpha=80, offset=(0, 3)), name)


def circle():
    im = canvas(520, 340); d = ImageDraw.Draw(im)
    for k, (dx, dy, r) in enumerate(((0, 0, 0), (10, -6, 4))):
        box = ((30 + dx) * S, (30 + dy) * S, (490 - dx) * S, (310 + dy) * S)
        d.arc(box, 200 + r * 3, 200 + 350 - r * 5, fill=RED, width=int(12 * S))
    finish(shadow(im, radius=3, alpha=70, offset=(0, 2)), 'circle.png')


def waveform(phase):
    im = canvas(600, 200); d = ImageDraw.Draw(im)
    n = 31
    for i in range(n):
        x = 30 + i * 18
        h = 20 + 150 * abs(math.sin(i * .55 + phase)) * (.4 + .6 * math.sin(math.pi * i / (n - 1)))
        d.rounded_rectangle((x * S, (100 - h / 2) * S, (x + 9) * S, (100 + h / 2) * S), radius=4.5 * S, fill=WHITE)
    finish(shadow(im, radius=3, alpha=90, offset=(0, 2)), f'wave_{int(phase * 10)}.png')


if __name__ == '__main__':
    for pressed in (False, True):
        subscribe(pressed); like_sub_bell(pressed)
    subscribed_row(); share(); comment(); like()
    bell_ring(14); bell_ring(-14)
    rec(True); rec(False)
    scribble_arrow('arrow_right.png', False); scribble_arrow('arrow_left.png', True)
    circle()
    for ph in (0.0, 1.0, 2.0):
        waveform(ph)
    print('stickers written to', OUT)
