"""Serve stored image assets to the browser.

Assets are immutable (originals are content-addressed and derived files are
per-run), so responses are marked privately cacheable. The internal storage
path is resolved server-side and never included in the response.
"""

from __future__ import annotations

from flask import Blueprint, send_file
from werkzeug.exceptions import NotFound

from ..extensions import get_asset_store, get_database
from cheiloscan.db.repositories import ImageAssetRepository
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

    path = store.resolve(storage_path)
    if not path.is_file():
        raise NotFound("the stored asset file is missing")

    extension = STORAGE_EXTENSIONS.get(image_format, "bin")
    response = send_file(
        path,
        mimetype=MIME_TYPES.get(image_format, "application/octet-stream"),
        download_name=f"{digest}.{extension}",
        conditional=True,
        max_age=31536000,
    )
    response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return response
