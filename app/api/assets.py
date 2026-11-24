"""Serve stored image assets to the browser.

Assets are immutable (originals are content-addressed and derived files are
per-run), but they are biometric-adjacent research images: responses are marked
``private, no-store`` so browsers do not retain them on shared machines. The
internal storage key is resolved server-side and never included in the response.

Bytes are streamed rather than buffered so the route also works on Vercel,
whose buffered response-body limit is much smaller than a typical image.
"""

from __future__ import annotations

from flask import Blueprint, Response, stream_with_context
from werkzeug.exceptions import NotFound

from ..extensions import get_asset_store, get_database
from cheiloscan.db.repositories import ImageAssetRepository
from cheiloscan.storage.asset_store import StorageError
from cheiloscan.util.imageio import MIME_TYPES, STORAGE_EXTENSIONS

assets_bp = Blueprint("assets", __name__, url_prefix="/api/assets")


@assets_bp.get("/<asset_id>/file")
def serve_asset(asset_id: str):
    database = get_database()
    store = get_asset_store()
    with database.session() as session:
        asset = ImageAssetRepository(session).get(asset_id)
        if asset is None:
            raise NotFound(f"asset {asset_id!r} does not exist")
        storage_path = asset.storage_path
        image_format = asset.format
        digest = asset.sha256
        size_bytes = int(asset.size_bytes)

    try:
        if not store.exists(storage_path):
            raise NotFound("the stored asset file is missing")
    except StorageError as exc:
        # Never expose the stored path or containment failure details.
        raise NotFound("the stored asset file is unavailable") from exc

    extension = STORAGE_EXTENSIONS.get(image_format, "bin")
    mimetype = MIME_TYPES.get(image_format, "application/octet-stream")

    def chunks():
        try:
            yield from store.iter_read(storage_path)
        except (FileNotFoundError, StorageError):
            # The client has already received headers; stop cleanly rather than
            # turning a mid-stream storage error into an HTML 500 response.
            return

    response = Response(stream_with_context(chunks()), mimetype=mimetype)
    response.headers["Content-Disposition"] = (
        f"attachment; filename={digest}.{extension}"
    )
    response.headers["Content-Length"] = str(size_bytes)
    response.headers["Cache-Control"] = "private, no-store"
    return response
