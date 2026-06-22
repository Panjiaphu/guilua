from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import secrets

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import BASE_DIR, get_settings


ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


@dataclass(frozen=True)
class SavedImage:
    url: str
    relative_url: str
    original_bytes: int
    compressed_bytes: int
    width: int
    height: int
    filename: str


def save_uploaded_image(
    *,
    content: bytes,
    original_filename: str,
    folder: str = "posts",
    name_hint: str = "image",
) -> SavedImage:
    settings = get_settings()
    suffix = Path(original_filename or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("unsupported_image_type")
    max_bytes = settings.upload_max_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ValueError("image_too_large")
    if settings.upload_storage_backend != "local":
        raise ValueError("unsupported_upload_storage")

    try:
        image = Image.open(BytesIO(content))
        image = ImageOps.exif_transpose(image)
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("invalid_image") from exc

    max_width = max(settings.upload_image_max_width, 320)
    max_height = max_width * 2
    image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

    buffer = BytesIO()
    save_kwargs = {
        "format": "WEBP",
        "quality": max(45, min(settings.upload_image_quality, 92)),
        "method": 6,
    }
    image.save(buffer, **save_kwargs)
    output = buffer.getvalue()

    now = datetime.now(timezone.utc)
    safe_hint = _safe_slug(name_hint or Path(original_filename or "image").stem)
    filename = f"{safe_hint}-{now.strftime('%Y%m%d%H%M%S')}-{secrets.token_urlsafe(5)}.webp"
    relative_dir = Path("uploads") / folder / now.strftime("%Y") / now.strftime("%m")
    output_dir = BASE_DIR / "app" / "static" / relative_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / filename
    target.write_bytes(output)

    relative_url = f"/static/{relative_dir.as_posix()}/{filename}"
    public_base = settings.public_base_url.rstrip("/")
    return SavedImage(
        url=f"{public_base}{relative_url}",
        relative_url=relative_url,
        original_bytes=len(content),
        compressed_bytes=len(output),
        width=image.width,
        height=image.height,
        filename=filename,
    )


def _safe_slug(value: str) -> str:
    normalized = value.lower().strip().replace(" ", "-")
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in normalized)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return (cleaned or "image")[:42]
