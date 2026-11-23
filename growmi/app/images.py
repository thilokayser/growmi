import os
import uuid
from datetime import datetime

from PIL import Image, ImageOps, UnidentifiedImageError
from .i18n import tr

MAX_EDGE = 1600
THUMB_EDGE = 320


def exif_time(fileobj) -> str | None:
    """'YYYY-MM-DDTHH:MM' of the moment the photo was taken (EXIF), None when the file has none."""
    try:
        exif = Image.open(fileobj).getexif()
        raw = exif.get_ifd(0x8769).get(36867) or exif.get(306)  # DateTimeOriginal, else DateTime
        taken = datetime.strptime(str(raw)[:19], "%Y:%m:%d %H:%M:%S") if raw else None
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        taken = None  # save_image reports the broken or oversized file
    fileobj.seek(0)  # save_image reads the file again
    return taken.strftime("%Y-%m-%dT%H:%M") if taken else None


def save_image(data_dir: str, fileobj) -> str:
    """Stores an uploaded picture (max 1600 px) plus a 320 px thumbnail 't_<name>' in <data_dir>/photos."""
    try:
        img = ImageOps.exif_transpose(Image.open(fileobj)).convert("RGB")
    except Image.DecompressionBombError:
        raise ValueError(tr("Das Bild ist zu groß")) from None
    except (UnidentifiedImageError, OSError):
        raise ValueError(tr("Das ist kein Bild")) from None
    folder = os.path.join(data_dir, "photos")
    os.makedirs(folder, exist_ok=True)
    name = f"{uuid.uuid4().hex}.jpg"
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    img.save(os.path.join(folder, name), "JPEG", quality=85)
    thumb = img.copy()
    thumb.thumbnail((THUMB_EDGE, THUMB_EDGE))
    thumb.save(os.path.join(folder, f"t_{name}"), "JPEG", quality=80)
    return name
