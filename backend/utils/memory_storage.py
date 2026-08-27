"""Operasi storage Memory Journal yang dibatasi ke satu direktori aman."""
import os
import re

from PIL import Image

from utils.memory_journal_images import journal_upload_dir, validated_journal_path

PHOTO_RE_TEMPLATE = r"^memory_{child_id}_[0-9a-f]{{32}}\.webp$"


def child_photo_pattern(child_id):
    return re.compile(PHOTO_RE_TEMPLATE.format(child_id=child_id))


def safe_child_files(child_id):
    root = journal_upload_dir()
    pattern = child_photo_pattern(child_id)
    files = []
    for candidate in root.iterdir():
        if not pattern.fullmatch(candidate.name) or candidate.is_symlink() or not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved.parent == root:
            files.append(candidate)
    return files


def optimize_photo_file(filename):
    original = journal_upload_dir() / filename
    if original.is_symlink():
        raise ValueError("File symlink tidak diizinkan")
    path = validated_journal_path(filename)
    if not path or not path.is_file():
        raise ValueError("File foto tidak tersedia atau tidak aman")
    before = path.stat().st_size
    temp = path.with_suffix(".optimize.tmp")
    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
            width, height = image.size
            image.save(temp, format="WEBP", quality=72, method=6, exif=b"")
        after = temp.stat().st_size
        if after >= before:
            return before, before, width, height, False
        os.replace(temp, path)
        return before, after, width, height, True
    finally:
        temp.unlink(missing_ok=True)
