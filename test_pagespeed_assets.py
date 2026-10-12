"""Responsive image/cache accuracy and stylesheet consolidation contracts."""
import re
from pathlib import Path
from urllib.parse import urlparse, unquote
from PIL import Image
from app import app, asset_url, responsive_image_srcset
from gamearena.assets import STYLE_SOURCES, stylesheet_bundle, stylesheet_source_digest
from test_interface_contracts import event

def test_homepage_uses_one_complete_versioned_stylesheet():
    with app.app_context():
        event()
        viewer=app.test_client();page=viewer.get('/')
        links=re.findall(r'<link rel="stylesheet" href="([^"]+)"',page.text)
        assert len(links)==1 and '/css/site.css?v=' in links[0]
        response=viewer.get(links[0])
        assert 'immutable' in response.headers['Cache-Control']
        for selector in ['.ga-master-badge','.ga-policy-links','html[data-theme=light]']:
            assert selector in response.text

def test_responsive_images_use_actual_widths_and_own_fingerprints():
    with app.test_request_context():
        candidates=responsive_image_srcset(asset_url('images/optimized/efootball_2-1440.webp'))
        widths=[]
        for candidate in candidates.split(', '):
            url, descriptor=candidate.rsplit(' ',1);width=int(descriptor[:-1]);widths.append(width)
            filename=unquote(urlparse(url).path).removeprefix('/static/')
            with Image.open(Path(app.static_folder)/filename) as image:assert image.width==width
            response=app.test_client().get(url)
            assert response.status_code==200 and 'immutable' in response.headers['Cache-Control']
        assert 384 in widths and 768 in widths and max(widths)==1024
        assert responsive_image_srcset('https://example.com/photo.jpg')==''

def test_stale_bundle_falls_back_and_line_endings_do_not_change_digest(tmp_path,monkeypatch):
    for name in STYLE_SOURCES:
        target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(b'.sample { color: red; }\r\n')
    digest=stylesheet_source_digest(tmp_path)
    bundle=tmp_path/'css/site.css';bundle.write_text(f'/* GameArena styles: {digest} */\n',encoding='utf-8')
    monkeypatch.setattr(app,'static_folder',str(tmp_path))
    with app.app_context():
        assert stylesheet_bundle()=='css/site.css'
        (tmp_path/STYLE_SOURCES[0]).write_bytes(b'.sample { color: red; }\n')
        assert stylesheet_source_digest(tmp_path)==digest
        assert stylesheet_bundle()=='css/site.css'
        (tmp_path/STYLE_SOURCES[0]).write_text('.sample { color: blue; }',encoding='utf-8')
        assert stylesheet_bundle() is None
