"""Inject PWA meta tags and service worker registration into all templates.

Adds, idempotently (won't duplicate if already present):
  1. PWA meta tags + manifest link into <head> (after <title>)
  2. Service worker registration near </body>
"""
import os
import re

TEMPLATES_DIR = 'templates'

META_INCLUDE = "{% include '_pwa_meta.html' %}"
REGISTER_INCLUDE = "{% include '_pwa_register.html' %}"


def process_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    changed = False

    # 1. Inject meta tags into <head> after the <title> line
    # Skip if the manifest link is already present (either via include or inline)
    if 'manifest.json' not in content:
        title_match = re.search(r'(<title>.*?</title>\s*)', content, re.IGNORECASE | re.DOTALL)
        if title_match:
            insertion = title_match.group(1) + '\n' + META_INCLUDE + '\n'
            content = content[:title_match.start()] + insertion + content[title_match.end():]
            changed = True

    # 2. Inject service worker registration before </body>
    if REGISTER_INCLUDE not in content and 'static/sw.js' not in content:
        body_close = content.rfind('</body>')
        if body_close != -1:
            content = content[:body_close] + REGISTER_INCLUDE + '\n' + content[body_close:]
            changed = True

    if changed:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'Updated: {path}')
        return True
    else:
        print(f'No change: {path}')
        return False


def main():
    for fname in sorted(os.listdir(TEMPLATES_DIR)):
        if fname.endswith('.html'):
            process_file(os.path.join(TEMPLATES_DIR, fname))


if __name__ == '__main__':
    main()
