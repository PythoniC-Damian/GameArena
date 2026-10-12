"""Generate correctly labelled responsive WebP variants; retain source images."""
import json
import sys
from pathlib import Path
from PIL import Image, ImageOps
ROOT = Path(__file__).resolve().parent.parent
WIDTHS = (384,480,640,768,960,1200,1440)

def main():
    destination = ROOT / 'static/images/optimized'
    destination.mkdir(parents=True, exist_ok=True)
    catalogue = {}
    only_new = '--only-new' in sys.argv
    for source in sorted((ROOT / 'static/images').iterdir()):
        if source.suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}: continue
        with Image.open(source) as original:
            original = ImageOps.exif_transpose(original).convert('RGB')
            stem = source.stem.replace(' ', '_')
            entries = []
            for width in sorted({min(width, original.width) for width in WIDTHS}):
                image = original.copy()
                image.thumbnail((width, original.height))
                filename = f'{stem}-{image.width}.webp'
                target = destination / filename
                if not only_new or not target.exists(): image.save(target,'WEBP',quality=78,method=6)
                entries.append({'file':f'images/optimized/{filename}','width':image.width})
            catalogue[stem] = entries
    (destination / 'manifest.json').write_text(json.dumps(catalogue,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print('Responsive image variants and exact-width manifest generated.')

if __name__ == '__main__': main()
