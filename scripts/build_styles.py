"""Combine existing styles in cascade order; preserve all declarations."""
import sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from gamearena.assets import STYLE_SOURCES, stylesheet_source_digest

def main():
    folder = root / 'static'
    digest = stylesheet_source_digest(folder)
    contents = f'/* GameArena styles: {digest} */\n' + '\n'.join(
        f'/* {name} */\n' + (folder / name).read_text(encoding='utf-8') for name in STYLE_SOURCES)
    target = folder / 'css/site.css'
    if '--check' in sys.argv:
        if not target.exists() or target.read_text(encoding='utf-8') != contents:
            raise SystemExit('Stylesheet bundle needs rebuilding.')
    else:
        target.write_text(contents, encoding='utf-8')
    print('Stylesheet bundle is current.')

if __name__ == '__main__': main()
