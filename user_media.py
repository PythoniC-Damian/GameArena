"""Validate profile photos and store them locally or in configured Supabase Storage."""
import io
import os
import uuid
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
import requests


def store_avatar(upload, app):
    data = upload.stream.read(4 * 1024 * 1024 + 1)
    if not data or len(data) > 4 * 1024 * 1024:
        raise ValueError('Choose a photo smaller than 4 MB.')
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {'JPEG', 'PNG', 'WEBP'} or image.width * image.height > 16_000_000:
                raise ValueError('Choose a JPEG, PNG, or WebP photo up to 16 megapixels.')
            image.load()
            image = ImageOps.fit(ImageOps.exif_transpose(image).convert('RGB'), (384, 384))
            output = io.BytesIO(); image.save(output, 'WEBP', quality=85)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('That file could not be read as a photo.') from error
    filename = f'{uuid.uuid4().hex}.webp'
    supabase_url = os.environ.get('SUPABASE_URL', '').rstrip('/')
    service_key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
    if supabase_url and service_key:
        from urllib.parse import urlparse
        if urlparse(supabase_url).scheme != 'https':
            raise ValueError('Photo storage is not configured correctly.')
        bucket = os.environ.get('SUPABASE_AVATAR_BUCKET', 'avatars')
        if not bucket.replace('-', '').replace('_', '').isalnum():
            raise ValueError('Photo storage is not configured correctly.')
        try:
            response = requests.post(f'{supabase_url}/storage/v1/object/{bucket}/{filename}',
                headers={'Authorization':f'Bearer {service_key}', 'apikey':service_key,
                         'Content-Type':'image/webp', 'x-upsert':'false'},
                data=output.getvalue(), timeout=(5, 15))
            response.raise_for_status()
        except requests.RequestException as error:
            raise ValueError('Photo storage is unavailable. Please try again.') from error
        return f'{supabase_url}/storage/v1/object/public/{bucket}/{filename}'
    folder = os.environ.get('AVATAR_UPLOAD_DIR')
    if not folder and (os.environ.get('RENDER') or os.environ.get('FLASK_ENV') == 'production'):
        raise ValueError('Profile photo storage is being set up. Please try again later.')
    destination = Path(folder or Path(app.instance_path) / 'avatars')
    try:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / filename).write_bytes(output.getvalue())
    except OSError as error:
        raise ValueError('Photo storage is unavailable. Please try again.') from error
    return f'/media/avatars/{filename}'
