"""Validasi dan kompresi foto Memory Journal tanpa menyimpan metadata asli."""
from io import BytesIO
import os
from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_INPUT_BYTES = 5 * 1024 * 1024
MAX_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_DIMENSION = 1600
MAX_SOURCE_PIXELS = 25_000_000


class JournalImageError(ValueError):
    pass


def journal_upload_dir():
    configured = current_app.config.get("MEMORY_JOURNAL_UPLOAD_DIR")
    path = Path(configured) if configured else Path(current_app.root_path) / "uploads" / "memory"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def validated_journal_path(filename):
    if not filename or Path(filename).name != filename:
        return None
    root = journal_upload_dir()
    candidate = (root / filename).resolve()
    return candidate if candidate.parent == root else None


def process_journal_image(file_storage, child_id):
    if not file_storage or not file_storage.filename:
        raise JournalImageError("Pilih satu foto terlebih dahulu")
    raw = file_storage.stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise JournalImageError("Ukuran foto maksimal 5 MB")
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > MAX_SOURCE_PIXELS:
                raise JournalImageError("Resolusi foto terlalu besar")
            source.verify()
        with Image.open(BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
            if image.mode != "RGB":
                background = Image.new("RGB", image.size, "white")
                if "A" in image.getbands():
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image.convert("RGB"))
                image = background
            width, height = image.size
            filename = f"memory_{child_id}_{uuid4().hex}.webp"
            target = journal_upload_dir() / filename
            temp = target.with_suffix(".tmp")
            try:
                image.save(temp, format="WEBP", quality=82, method=6, exif=b"")
                size = temp.stat().st_size
                if size > MAX_OUTPUT_BYTES:
                    image.save(temp, format="WEBP", quality=68, method=6, exif=b"")
                    size = temp.stat().st_size
                if size > MAX_OUTPUT_BYTES:
                    raise JournalImageError("Foto terlalu kompleks untuk disimpan. Coba foto lain.")
                os.replace(temp, target)
                return filename, size, width, height
            finally:
                temp.unlink(missing_ok=True)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise JournalImageError("File bukan foto yang valid")
