"""Architecture rule: the domain package never imports Flask or the app package."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHEILOSCAN_DIR = REPO_ROOT / "cheiloscan"

FORBIDDEN_PATTERNS = (
    re.compile(r"^\s*import\s+flask\b", re.MULTILINE),
    re.compile(r"^\s*from\s+flask\b", re.MULTILINE),
    re.compile(r"^\s*import\s+app\b", re.MULTILINE),
    re.compile(r"^\s*from\s+app\b", re.MULTILINE),
)


def test_domain_package_files_exist():
    assert (CHEILOSCAN_DIR / "__init__.py").is_file()
    assert (CHEILOSCAN_DIR / "db" / "models.py").is_file()


def test_domain_package_has_no_http_layer_imports():
    offenders: list[str] = []
    for path in sorted(CHEILOSCAN_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(source):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
