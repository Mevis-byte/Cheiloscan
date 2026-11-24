"""Mirror the vanilla frontend in ``public/`` for Vercel's static CDN.

The application source of truth remains ``web/``. Run this script after editing
any HTML/CSS/JS file, then commit both trees.
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "web"
TARGET = ROOT / "public"


def main() -> None:
    if TARGET.exists():
        shutil.rmtree(TARGET)
    shutil.copytree(SOURCE, TARGET)
    # Python package marker is not a browser asset.
    (TARGET / "__init__.py").unlink(missing_ok=True)
    print(f"Mirrored {SOURCE.relative_to(ROOT)} -> {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
