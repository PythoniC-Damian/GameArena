"""Generate responsive WebP derivatives without changing source images.

Requires Pillow; run with python scripts/optimize_images.py.
"""
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent


def main():
    destination = ROOT / 'static/images/optimized'
    destination.mkdir(parents=True, exist_ok=True)
    for source in (ROOT / 'static/images').iterdir():
        if source.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
            continue
        with Image.open(source) as original:
            original = ImageOps.exif_transpose(original).convert('RGB')
            for width in (480, 960, 1440):
                image = original.copy()
                image.thumbnail((width, width * 2))
                filename = f'{source.stem.replace(" ", "_")}-{width}.webp'
                image.save(destination / filename, 'WEBP', quality=78, method=6)
    print('Responsive image derivatives generated.')


if __name__ == '__main__':
    main()
