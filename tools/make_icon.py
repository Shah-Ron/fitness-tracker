"""Draw the Fitness Tracker icon.

Writes tools\\icon.ico for the .exe and the taskbar, and three PNGs at the
project root for the phone's home screen: icon-192.png, icon-512.png and
icon-maskable-512.png (the last one keeps the drawing inside the safe zone so
Android can crop it to any shape).

The drawing is a kettlebell on a deep green square, in the app's colours.
Needs Pillow: python -m pip install pillow
"""

import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow is missing. Run: python -m pip install pillow")
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

GREEN = (62, 107, 72)        # the app's accent
GREEN_DARK = (46, 82, 55)
CREAM = (242, 241, 236)      # the page background
INK = (30, 42, 38)


def draw(size, pad_frac=0.0, rounded=True):
    """One frame at the given pixel size. pad_frac shrinks the drawing for the maskable icon."""
    s = size * 4                                   # draw large, then shrink for smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(s * 0.22) if rounded else 0
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=GREEN)

    pad = s * pad_frac
    box = s - 2 * pad
    cx = s / 2
    # Kettlebell body: a circle sitting low in the frame.
    body_r = box * 0.30
    body_cy = pad + box * 0.62
    d.ellipse([cx - body_r, body_cy - body_r, cx + body_r, body_cy + body_r], fill=CREAM)
    # Handle: a thick arc above the body.
    handle_w = box * 0.40
    handle_h = box * 0.36
    stroke = int(box * 0.085)
    top = pad + box * 0.16
    d.arc([cx - handle_w, top, cx + handle_w, top + handle_h * 2], start=200, end=340, fill=CREAM, width=stroke)
    # Legs of the handle down into the body.
    leg_top = top + handle_h * 0.55
    d.line([cx - handle_w * 0.94, leg_top, cx - handle_w * 0.62, body_cy - body_r * 0.55], fill=CREAM, width=stroke)
    d.line([cx + handle_w * 0.94, leg_top, cx + handle_w * 0.62, body_cy - body_r * 0.55], fill=CREAM, width=stroke)
    # A small highlight so the body reads as round.
    hl = body_r * 0.22
    d.ellipse([cx - body_r * 0.45 - hl, body_cy - body_r * 0.45 - hl, cx - body_r * 0.45 + hl, body_cy - body_r * 0.45 + hl], fill=GREEN_DARK)
    return img.resize((size, size), Image.LANCZOS)


def main():
    frames = {sz: draw(sz) for sz in (16, 24, 32, 48, 64, 128, 256)}
    ico_path = os.path.join(HERE, "icon.ico")
    frames[256].save(ico_path, format="ICO", sizes=[(sz, sz) for sz in frames], append_images=[frames[sz] for sz in sorted(frames) if sz != 256])
    draw(192).save(os.path.join(ROOT, "icon-192.png"))
    draw(512).save(os.path.join(ROOT, "icon-512.png"))
    draw(512, pad_frac=0.12, rounded=False).save(os.path.join(ROOT, "icon-maskable-512.png"))
    print("Wrote tools\\icon.ico, icon-192.png, icon-512.png and icon-maskable-512.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
