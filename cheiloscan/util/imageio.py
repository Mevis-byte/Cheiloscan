"""Image decoding, encoding and metadata extraction.

Supported formats are JPEG, PNG and WebP. Format detection is based on
**magic bytes**, never on the client-supplied filename or MIME type: an
upload named ``photo.jpg`` that is really a PNG is accepted as PNG, and an
upload with a supported extension but unknown content is rejected.

Decoding policy:

- OpenCV decodes with ``IMREAD_IGNORE_ORIENTATION`` so the pixel data is
  exactly the stored bytes.
- EXIF orientation is then applied explicitly to the *working copy* (see
  ``apply_exif_orientation``). Originals are never rewritten, so the
  orientation metadata stays intact on disk.
- Recorded width/height are the logical (display-oriented) dimensions,
  which is what all processing operates on. The raw EXIF orientation value
  is retained in the extracted metadata.

Pillow is used only for metadata (EXIF) reading; OpenCV does all pixel work.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

#: Canonical format identifiers used throughout the application.
IMAGE_FORMATS: tuple[str, ...] = ("jpeg", "png", "webp")

#: Upload extensions accepted from clients (case-insensitive).
EXTENSION_FORMATS: dict[str, str] = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".webp": "webp",
}

#: Extension used when writing an asset of a given format to disk.
STORAGE_EXTENSIONS: dict[str, str] = {
    "jpeg": "jpg",
    "png": "png",
    "webp": "webp",
}

#: MIME type used when serving an asset back to a browser.
MIME_TYPES: dict[str, str] = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_RIFF_MAGIC = b"RIFF"
_WEBP_MAGIC = b"WEBP"

_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_LENGTH = 120


class UnsupportedFormatError(ValueError):
    """The uploaded content is not a supported image format."""


class ImageDecodeError(ValueError):
    """The content claims a supported format but cannot be decoded."""


@dataclass(frozen=True)
class DecodedImage:
    """A decoded working copy plus everything intake needs to record."""

    bgr: np.ndarray
    format: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    exif: dict[str, object] = field(default_factory=dict)

    @property
    def orientation(self) -> int:
        value = self.exif.get("orientation", 1)
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1


def sha256_hex(data: bytes) -> str:
    """Lowercase hex SHA-256 digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sniff_format(data: bytes) -> str | None:
    """Return the image format from magic bytes, or ``None`` if unknown."""
    if data.startswith(_JPEG_MAGIC):
        return "jpeg"
    if data.startswith(_PNG_MAGIC):
        return "png"
    if (
        len(data) >= 12
        and data.startswith(_RIFF_MAGIC)
        and data[8:12] == _WEBP_MAGIC
    ):
        return "webp"
    return None


def sanitize_filename(name: str | None) -> str:
    """Return a safe display filename derived from an untrusted upload name.

    The result is never used as a storage path (storage is content-addressed);
    it is retained only as human-readable provenance metadata. Directory
    components, control characters and shell-hostile characters are removed.
    """
    if not name:
        return "upload"
    # Strip any path components from either platform.
    base = re.split(r"[\\/]", name)[-1].strip()
    cleaned = _FILENAME_UNSAFE.sub("_", base).strip("._-")
    if not cleaned:
        return "upload"
    if len(cleaned) > _MAX_FILENAME_LENGTH:
        stem, dot, suffix = cleaned.rpartition(".")
        if dot and len(suffix) <= 10:
            keep = _MAX_FILENAME_LENGTH - len(suffix) - 1
            cleaned = f"{stem[:keep]}.{suffix}"
        else:
            cleaned = cleaned[:_MAX_FILENAME_LENGTH]
    return cleaned


def extract_exif(data: bytes, image_format: str) -> dict[str, object]:
    """Extract a small, JSON-safe EXIF subset. Never raises on bad metadata."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            exif = image.getexif()
            if not exif:
                return {}
            result: dict[str, object] = {}
            mapping = {
                "orientation": 274,
                "datetime_original": 36867,
                "make": 271,
                "model": 272,
                "software": 305,
            }
            for key, tag in mapping.items():
                value = exif.get(tag)
                if value is None:
                    continue
                if key == "orientation":
                    try:
                        result[key] = int(value)
                    except (TypeError, ValueError):
                        continue
                else:
                    text = str(value).strip()
                    if text:
                        result[key] = text[:255]
            return result
    except Exception:  # noqa: BLE001 - metadata must never break intake
        return {}


def apply_exif_orientation(bgr: np.ndarray, orientation: int) -> np.ndarray:
    """Return a copy of ``bgr`` transformed per an EXIF orientation value."""
    if orientation == 2:
        return cv2.flip(bgr, 1)
    if orientation == 3:
        return cv2.rotate(bgr, cv2.ROTATE_180)
    if orientation == 4:
        return cv2.flip(bgr, 0)
    if orientation == 5:  # transpose: rotate 90 CW then mirror horizontally
        return cv2.flip(cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE), 1)
    if orientation == 6:
        return cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE)
    if orientation == 7:  # transverse: rotate 90 CW then mirror vertically
        return cv2.flip(cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE), 0)
    if orientation == 8:
        return cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return bgr


def decode_image(data: bytes) -> DecodedImage:
    """Validate and decode uploaded bytes into a BGR working image.

    Raises ``UnsupportedFormatError`` for unknown magic bytes and
    ``ImageDecodeError`` for empty or undecodable content. The input bytes
    are never modified; the caller keeps them for the immutable original.
    """
    if not data:
        raise ImageDecodeError("file is empty")

    image_format = sniff_format(data)
    if image_format is None:
        raise UnsupportedFormatError(
            "unsupported image format; expected JPEG, PNG or WebP"
        )

    buffer = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(
        buffer, cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION
    )
    if bgr is None or bgr.size == 0:
        raise ImageDecodeError(
            "image data could not be decoded; the file may be corrupt or truncated"
        )

    exif = extract_exif(data, image_format)
    orientation = 1
    try:
        orientation = int(exif.get("orientation", 1))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        orientation = 1
    if orientation != 1:
        bgr = apply_exif_orientation(bgr, orientation)

    height, width = bgr.shape[:2]
    return DecodedImage(
        bgr=bgr,
        format=image_format,
        width=int(width),
        height=int(height),
        size_bytes=len(data),
        sha256=sha256_hex(data),
        exif=exif,
    )


def encode_image(bgr: np.ndarray, image_format: str, *, quality: int = 95) -> bytes:
    """Encode a BGR image to the given format (used for derived assets)."""
    if image_format not in STORAGE_EXTENSIONS:
        raise UnsupportedFormatError(f"cannot encode format {image_format!r}")
    extension = "." + STORAGE_EXTENSIONS[image_format]
    if image_format == "jpeg":
        params = [cv2.IMWRITE_JPEG_QUALITY, int(quality)]
    elif image_format == "webp":
        params = [cv2.IMWRITE_WEBP_QUALITY, int(quality)]
    else:
        params = [cv2.IMWRITE_PNG_COMPRESSION, 6]
    ok, buffer = cv2.imencode(extension, bgr, params)
    if not ok:  # pragma: no cover - encoding of a valid ndarray is reliable
        raise ImageDecodeError(f"failed to encode image as {image_format}")
    return buffer.tobytes()
