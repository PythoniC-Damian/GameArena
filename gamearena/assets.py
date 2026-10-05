"""Optional Vite manifest integration with a working no-build fallback."""
import json
from pathlib import Path
from flask import current_app, url_for


def frontend_assets(entry='frontend/carousels.ts'):
    manifest = Path(current_app.static_folder) / 'build/.vite/manifest.json'
    try:
        value = json.loads(manifest.read_text(encoding='utf-8')).get(entry, {})
        files = [value['file'], *value.get('css', [])]
        base = Path(current_app.static_folder) / 'build'
        if any(Path(name).is_absolute() or '..' in Path(name).parts or not (base / name).is_file() for name in files):
            return None
        return {'script': url_for('static', filename='build/' + value['file']),
                'styles': [url_for('static', filename='build/' + name) for name in value.get('css', [])]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def is_built_asset(filename):
    if not filename.startswith('build/'):
        return False
    manifest = Path(current_app.static_folder) / 'build/.vite/manifest.json'
    try:
        entries = json.loads(manifest.read_text(encoding='utf-8')).values()
        files = {name for entry in entries for name in [entry.get('file'), *entry.get('css', [])] if isinstance(name, str)}
        return filename[6:] in files
    except (OSError, ValueError, TypeError, AttributeError):
        return False
