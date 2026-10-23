import os
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError
from .i18n import tr

MAX_EDGE = 1600
THUMB_EDGE = 320


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
