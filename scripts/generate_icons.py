"""Generate GameArena PWA app icons using Pillow.

Creates emerald "G" icons in the required sizes and placements.
"""
import os
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join('static', 'icons')
os.makedirs(OUT_DIR, exist_ok=True)

# Brand colors
BG_DARK = (2, 6, 23)        # slate-950
EMERALD = (16, 185, 129)    # emerald-500


def draw_icon(size, maskable=False):
    """Draw a rounded-square emerald 'G' icon."""
    # Higher-res canvas for smooth edges
    scale = 4
    canvas = size * scale
    img = Image.new('RGBA', (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background
    radius = 0 if maskable else int(canvas * 0.22)
    draw.rounded_rectangle(
        [0, 0, canvas - 1, canvas - 1],
        radius=radius,
        fill=BG_DARK
    )

    # Emerald ring
    ring_pad = int(canvas * (0.06 if maskable else 0.10))
    ring_width = int(canvas * 0.05)
    draw.rounded_rectangle(
        [ring_pad, ring_pad, canvas - ring_pad, canvas - ring_pad],
        radius=int(canvas * 0.16),
        outline=EMERALD,
        width=ring_width
    )

    # Letter "G"
    try:
        # Try common font paths
        font_paths = [
            'C:/Windows/Fonts/arialbd.ttf',
            'C:/Windows/Fonts/Arial.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        ]
        font = None
        for fp in font_paths:
            if os.path.exists(fp):
                font = ImageFont.truetype(fp, int(canvas * 0.55))
                break
        if font is None:
            font = ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()

    text = "G"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (canvas - tw) / 2 - bbox[0]
    ty = (canvas - th) / 2 - bbox[1] - int(canvas * 0.02)
    draw.text((tx, ty), text, font=font, fill=EMERALD)

    # Downscale for crisp rendering
    img = img.resize((size, size), Image.LANCZOS)
    return img


def main():
    draw_icon(192).save(os.path.join(OUT_DIR, 'icon-192.png'))
    draw_icon(512).save(os.path.join(OUT_DIR, 'icon-512.png'))
    draw_icon(512, maskable=True).save(os.path.join(OUT_DIR, 'icon-512-maskable.png'))
    draw_icon(180).save(os.path.join(OUT_DIR, 'apple-touch-icon.png'))
    print('Icons generated in', OUT_DIR)


if __name__ == '__main__':
    main()
