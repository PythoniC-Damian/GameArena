"""Decode uploads into bounded, metadata-free tournament artwork."""
import io
import uuid
from PIL import Image, ImageOps, UnidentifiedImageError
from gamearena.extensions import db
from gamearena.models import TournamentArtwork

MAX_FILE_BYTES = 1024 * 1024


def read_artwork(uploads, existing_count=0):
    files = [item for item in uploads if item and item.filename]
    if not files and existing_count == 3:
        return None
    if len(files) != 3:
        raise ValueError('Upload exactly 3 tournament images, or keep the existing 3 when editing.')
    images = []
    for upload in files:
        raw = upload.stream.read(MAX_FILE_BYTES + 1)
        if not raw or len(raw) > MAX_FILE_BYTES:
            raise ValueError('Each tournament image must be 1 MB or smaller.')
        try:
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'} or source.width * source.height > 12_000_000:
                    raise ValueError('Use JPEG, PNG or WebP images up to 12 megapixels.')
                if source.width < 480 or source.height < 270:
                    raise ValueError('Use images at least 480 pixels wide and 270 pixels tall. Landscape images work best.')
                source.load()
                normalized = ImageOps.fit(ImageOps.exif_transpose(source).convert('RGB'), (1280, 720), method=Image.Resampling.LANCZOS)
                output = io.BytesIO()
                normalized.save(output, 'WEBP', quality=80, method=4)
                images.append(output.getvalue())
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise ValueError('One of the images could not be read. Use JPEG, PNG or WebP files.') from error
    return images


def replace_artwork(draft, images):
    if images is None:
        return
    # Delete before inserting the same three positions; rollback restores all on failure.
    draft.artwork.clear()
    db.session.flush()
    draft.artwork = [TournamentArtwork(id=uuid.uuid4().hex, position=i, image=image)
                     for i, image in enumerate(images, 1)]
