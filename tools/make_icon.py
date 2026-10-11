"""Draw the Fitness Tracker icon, in every look the app can wear.

The drawing is a kettlebell on a square. The app's Look settings offer seven
colours (green, blue, teal, violet, rose, amber, graphite) and a light or dark
theme, and the home-screen icon follows that choice, so this writes one icon
set per look: a light set (the colour as the background, a cream kettlebell)
and a dark set (the dark theme's tinted background, the kettlebell in the
theme's lighter accent). The green light set is the one the app ships with.

Writes:
  tools\\icon.ico                      the .exe and taskbar icon (green)
  icon-180.png, icon-192.png, icon-512.png, icon-maskable-512.png
                                      the default set at the project root, for the laptop edition
  phone\\icons\\<look>-{180,192,512,maskable-512}.png
                                      the fourteen sets for the web app
  phone\\manifest-<look>.webmanifest  one manifest per set, pointing at it
  android\\...\\res\\drawable\\fg_<look>.png, mipmap-anydpi-v26\\ic_launcher_<look>.xml and
  android\\...\\res\\values\\icon_colours.xml
                                      the Android launcher icons, one activity alias each

The colour maths mirrors accentPalette in app.html so the icon matches the
buttons. Needs Pillow: python -m pip install pillow
"""

import json
import os
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("Pillow is missing. Run: python -m pip install pillow")
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PHONE = os.path.join(ROOT, "phone")
RES = os.path.join(ROOT, "android", "app", "src", "main", "res")

# The seven swatches in app.html, in the same order.
SWATCHES = [("green", "#3E6B48"), ("blue", "#3B64A8"), ("teal", "#2B7C76"), ("violet", "#6B51B5"),
            ("rose", "#B2466E"), ("amber", "#B5651D"), ("graphite", "#4B5661")]
CREAM = (242, 241, 236)      # the page background and the kettlebell on a coloured square
LIGHT_PLANE = "#F2F1EC"      # the light theme's page background
DARK_PLANE = "#171C1A"       # the dark theme's page background, retinted to each hue


# ----------------------------------------------------------------- colour maths, as in app.html

def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_hex(rgb):
    return "#" + "".join("%02X" % max(0, min(255, int(round(x)))) for x in rgb)


def rgb_hsl(rgb):
    r, g, b = (x / 255 for x in rgb)
    mx, mn = max(r, g, b), min(r, g, b)
    l = (mx + mn) / 2
    if mx == mn:
        return 0.0, 0.0, l
    d = mx - mn
    s = d / (2 - mx - mn) if l > .5 else d / (mx + mn)
    if mx == r:
        h = (g - b) / d + (6 if g < b else 0)
    elif mx == g:
        h = (b - r) / d + 2
    else:
        h = (r - g) / d + 4
    return h * 60, s, l


def hsl_rgb(h, s, l):
    def f(n):
        k = (n + h / 30) % 12
        a = s * min(l, 1 - l)
        return 255 * (l - a * max(-1, min(k - 3, 9 - k, 1)))
    return f(0), f(8), f(4)


def luminance(rgb):
    def c(x):
        x /= 255
        return x / 12.92 if x <= .03928 else ((x + .055) / 1.055) ** 2.4
    return .2126 * c(rgb[0]) + .7152 * c(rgb[1]) + .0722 * c(rgb[2])


def contrast(a, b):
    return (max(a, b) + .05) / (min(a, b) + .05)


def accent_palette(hex_colour, dark):
    """The accent the app draws for a swatch in the light or the dark theme (accentPalette in app.html)."""
    h, s, l = rgb_hsl(hex_rgb(hex_colour))
    s = min(s, .8)
    l = min(max(l, .58), .74) if dark else min(max(l, .26), .42)
    on = hsl_rgb(h, min(s, .35), .09) if dark else (255, 255, 255)
    rgb = hsl_rgb(h, s, l)
    for _ in range(20):
        if contrast(luminance(rgb), luminance(on)) >= 4.2:
            break
        l += .02 if dark else -.02
        rgb = hsl_rgb(h, s, l)
    return rgb_hex(rgb)


def tinted(neutral_hex, hue):
    """A neutral token with its hue turned to the accent's, as applyAccent does for the page."""
    _, s, l = rgb_hsl(hex_rgb(neutral_hex))
    return rgb_hex(hsl_rgb(hue, s, l))


def looks():
    """Every icon set: key, background, kettlebell colour, highlight, theme colour and page background."""
    out = []
    for name, swatch in SWATCHES:
        hue = rgb_hsl(hex_rgb(swatch))[0]
        bg = hex_rgb(swatch)
        out.append({"key": f"{name}_light", "bg": bg, "body": CREAM, "highlight": tuple(int(x * .75) for x in bg),
                    "theme": swatch, "plane": LIGHT_PLANE if name == "green" else tinted(LIGHT_PLANE, hue)})
        dark_bg = hex_rgb(DARK_PLANE if name == "green" else tinted(DARK_PLANE, hue))
        body = hex_rgb("#86BE94") if name == "green" else hex_rgb(accent_palette(swatch, True))   # the stylesheet's own dark green
        out.append({"key": f"{name}_dark", "bg": dark_bg, "body": body, "highlight": tuple(int(x * .72) for x in body),
                    "theme": rgb_hex(dark_bg), "plane": rgb_hex(dark_bg)})
    return out


# ----------------------------------------------------------------- drawing

def glyph(d, s, pad, body, highlight):
    """The kettlebell inside a box of side s - 2 * pad."""
    box = s - 2 * pad
    cx = s / 2
    body_r = box * 0.30
    body_cy = pad + box * 0.62
    d.ellipse([cx - body_r, body_cy - body_r, cx + body_r, body_cy + body_r], fill=body)
    handle_w = box * 0.40
    handle_h = box * 0.36
    stroke = int(box * 0.085)
    top = pad + box * 0.16
    d.arc([cx - handle_w, top, cx + handle_w, top + handle_h * 2], start=200, end=340, fill=body, width=stroke)
    leg_top = top + handle_h * 0.55
    d.line([cx - handle_w * 0.94, leg_top, cx - handle_w * 0.62, body_cy - body_r * 0.55], fill=body, width=stroke)
    d.line([cx + handle_w * 0.94, leg_top, cx + handle_w * 0.62, body_cy - body_r * 0.55], fill=body, width=stroke)
    hl = body_r * 0.22
    d.ellipse([cx - body_r * 0.45 - hl, body_cy - body_r * 0.45 - hl, cx - body_r * 0.45 + hl, body_cy - body_r * 0.45 + hl], fill=highlight)


def draw(size, look, pad_frac=0.0, rounded=True, background=True):
    """One frame at the given pixel size. pad_frac shrinks the drawing for the maskable icon."""
    s = size * 4                                   # draw large, then shrink for smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background:
        r = int(s * 0.22) if rounded else 0
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=look["bg"])
    glyph(d, s, s * pad_frac, look["body"], look["highlight"])
    return img.resize((size, size), Image.LANCZOS)


def save(img, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, optimize=True)


def write_set(look, folder, prefix):
    save(draw(192, look), os.path.join(folder, f"{prefix}-192.png"))
    save(draw(180, look, rounded=False), os.path.join(folder, f"{prefix}-180.png"))   # iPhone rounds it itself
    save(draw(512, look), os.path.join(folder, f"{prefix}-512.png"))
    save(draw(512, look, pad_frac=0.12, rounded=False), os.path.join(folder, f"{prefix}-maskable-512.png"))


def write_manifest(look):
    with open(os.path.join(PHONE, "manifest.webmanifest"), encoding="utf-8") as fh:
        m = json.load(fh)
    m["theme_color"] = look["theme"]
    m["background_color"] = look["plane"]
    m["icons"] = [{"src": f"./icons/{look['key']}-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": f"./icons/{look['key']}-512.png", "sizes": "512x512", "type": "image/png"},
                  {"src": f"./icons/{look['key']}-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]
    with open(os.path.join(PHONE, f"manifest-{look['key']}.webmanifest"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(m, fh, indent=2)
        fh.write("\n")


def write_android(all_looks):
    for look in all_looks:
        # The adaptive icon's foreground layer: 108 dp with the drawing kept inside the 66 dp safe zone.
        save(draw(432, look, pad_frac=0.25, rounded=False, background=False), os.path.join(RES, "drawable", f"fg_{look['key']}.png"))
        with open(os.path.join(RES, "mipmap-anydpi-v26", f"ic_launcher_{look['key']}.xml"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write('<?xml version="1.0" encoding="utf-8"?>\n<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
                     f'    <background android:drawable="@color/bg_{look["key"]}" />\n    <foreground android:drawable="@drawable/fg_{look["key"]}" />\n</adaptive-icon>\n')
    with open(os.path.join(RES, "values", "icon_colours.xml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="utf-8"?>\n<!-- Generated by tools/make_icon.py: the launcher icon backgrounds, one per look. -->\n<resources>\n')
        for look in all_looks:
            fh.write(f'    <color name="bg_{look["key"]}">{rgb_hex(look["bg"])}</color>\n')
        fh.write("</resources>\n")


def main():
    all_looks = looks()
    default = all_looks[0]
    frames = {sz: draw(sz, default) for sz in (16, 24, 32, 48, 64, 128, 256)}
    frames[256].save(os.path.join(HERE, "icon.ico"), format="ICO", sizes=[(sz, sz) for sz in frames], append_images=[frames[sz] for sz in sorted(frames) if sz != 256])
    write_set(default, ROOT, "icon")
    for look in all_looks:
        write_set(look, os.path.join(PHONE, "icons"), look["key"])
        write_manifest(look)
    write_android(all_looks)
    if "--table" in sys.argv:
        for look in all_looks:
            print(look["key"], rgb_hex(look["bg"]), rgb_hex(look["body"]), look["theme"], look["plane"])
    print(f"Wrote tools\\icon.ico, the default icons, {len(all_looks)} icon sets under phone\\icons, their manifests and the Android launcher icons")
    return 0


if __name__ == "__main__":
    sys.exit(main())
