"""Generate Howl mobile app icon, adaptive icon, splash, and notification icon.

Twilight palette (mobile/src/theme.ts): bg #0D0B1A, bgBrand #2D1B69,
gold #C9A84C. Mark: a geometric wolf-head silhouette set against a gold moon.

Usage: python generate_assets.py
Output: mobile/assets/{icon,adaptive-icon,splash-icon,notification-icon}.png
"""

from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)

BG_TOP = (45, 27, 105)      # #2D1B69 bgBrand
BG_BOTTOM = (13, 11, 26)    # #0D0B1A bg
GOLD = (201, 168, 76)       # #C9A84C gold
GOLD_GLOW = (232, 200, 78)  # #E8C84E goldHover
WOLF = (8, 6, 18)           # near-black silhouette

# Geometric wolf head, front-facing, on a 1000x1000 design grid.
# Two ear triangles at top, narrowing to a snout point at the bottom.
WOLF_POINTS = [
    (160, 110),   # left ear tip
    (390, 400),   # left ear inner base / head top-left
    (500, 310),   # notch between ears
    (610, 400),   # right ear inner base / head top-right
    (840, 110),   # right ear tip
    (730, 470),   # right side of head
    (650, 700),   # right jaw
    (500, 900),   # snout tip
    (350, 700),   # left jaw
    (270, 470),   # left side of head
]

EYE_RADIUS = 32
EYE_LEFT = (400, 520)
EYE_RIGHT = (600, 520)

MOON_CENTER = (500, 360)
MOON_RADIUS = 330
MOON_GLOW_RADIUS = 400


def vertical_gradient(size, top, bottom):
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)
    for y in range(size):
        t = y / (size - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (size, y)], fill=color)
    return img


def scale_points(points, scale, offset):
    return [(x * scale + offset, y * scale + offset) for x, y in points]


def draw_mark(draw, scale, offset, eyes=True, glow=True, eye_color=None):
    """Draw moon + wolf head (+ optional eyes) at the given scale/offset."""
    cx = MOON_CENTER[0] * scale + offset
    cy = MOON_CENTER[1] * scale + offset
    r = MOON_RADIUS * scale
    gr = MOON_GLOW_RADIUS * scale
    if glow:
        draw.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], fill=GOLD_GLOW + (50,))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GOLD + (255,))
    draw.polygon(scale_points(WOLF_POINTS, scale, offset), fill=WOLF + (255,))
    if eyes:
        er = EYE_RADIUS * scale
        for ex, ey in (EYE_LEFT, EYE_RIGHT):
            ex, ey = ex * scale + offset, ey * scale + offset
            draw.ellipse([ex - er, ey - er, ex + er, ey + er], fill=eye_color + (255,))


def make_icon():
    """Full-bleed app icon (iOS + Android fallback)."""
    size = 1024
    img = vertical_gradient(size, BG_TOP, BG_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")
    draw_mark(draw, scale=size / 1000, offset=0, eye_color=GOLD)
    img.convert("RGB").save(OUT / "icon.png")


def make_adaptive_icon():
    """Android adaptive icon foreground: transparent, content in safe zone (~66%)."""
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    scale = 620 / 1000
    offset = (size - 1000 * scale) / 2
    draw_mark(draw, scale, offset, eye_color=GOLD)
    img.save(OUT / "adaptive-icon.png")


def make_splash_icon():
    """Centered mark for the splash screen (transparent, contained)."""
    size = 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    scale = 560 / 1000
    offset = (size - 1000 * scale) / 2
    draw_mark(draw, scale, offset, eye_color=GOLD)
    img.save(OUT / "splash-icon.png")


def make_notification_icon():
    """Flat white silhouette on transparent, per Android notification icon rules."""
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    scale = 230 / 1000
    offset = (size - 1000 * scale) / 2
    draw_mark(draw, scale, offset, eyes=False, glow=False, eye_color=None)
    img.save(OUT / "notification-icon.png")


if __name__ == "__main__":
    make_icon()
    make_adaptive_icon()
    make_splash_icon()
    make_notification_icon()
    print(f"Wrote assets to {OUT}")
