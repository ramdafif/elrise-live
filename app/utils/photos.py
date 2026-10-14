import base64
import binascii
import os
import warnings
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from flask import current_app
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from app.utils.validation import ValidationError


def decode_selfie(value, timestamp, latitude, longitude):
    limit = current_app.config["MAX_PHOTO_BYTES"]
    if not isinstance(value, str) or not value.startswith("data:image/jpeg;base64,") or len(value) > ((limit + 2) // 3) * 4 + 40:
        raise ValidationError("Selfie JPEG wajib diambil melalui kamera dan maksimal 1 MB.")
    try:
        content = base64.b64decode(value.split(",", 1)[1], validate=True)
        if not content or len(content) > limit:
            raise ValidationError("Selfie kosong atau melewati batas ukuran.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format != "JPEG" or not (240 <= image.width <= 2000 and 240 <= image.height <= 2000) or image.width * image.height > 4000000:
                    raise ValidationError("Selfie harus JPEG dengan dimensi 240-2000 piksel.")
                image.verify()
            with Image.open(BytesIO(content)) as original:
                image = ImageOps.exif_transpose(original).convert("RGB")
                image.thumbnail((960, 960))
                draw = ImageDraw.Draw(image)
                draw.rectangle((0, image.height - 40, image.width, image.height), fill="#102f40")
                draw.text((10, image.height - 34), f"ELRISE | {timestamp:%Y-%m-%d %H:%M:%S} WIB", fill="white")
                draw.text((10, image.height - 18), f"GPS {latitude:.7f}, {longitude:.7f} | lokasi dilaporkan browser", fill="white")
                output = BytesIO()
                image.save(output, format="JPEG", quality=82, optimize=True)
                if output.tell() > limit:
                    raise ValidationError("Selfie terlalu besar setelah kompresi.")
                return output.getvalue()
    except ValidationError:
        raise
    except (binascii.Error, ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ValidationError("Selfie tidak dapat dibaca. Ambil ulang melalui kamera.") from None


def private_path(relative):
    root = Path(current_app.config["PRIVATE_UPLOAD_DIR"]).resolve()
    path = (root / relative).resolve()
    if root not in path.parents:
        raise ValidationError("Path foto tidak valid.")
    return path


def save_selfie(content, client_id, employee_id):
    relative = f"{client_id}/{employee_id}/{uuid4().hex}.jpg"
    path = private_path(relative)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return relative


def remove_selfie(relative):
    if relative:
        private_path(relative).unlink(missing_ok=True)
