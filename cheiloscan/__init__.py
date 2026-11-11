"""CheiloScan domain package.

This package contains the application domain (database models, repositories,
services). It must never import Flask or the ``app`` package; HTTP concerns
live exclusively in ``app/``. This rule is enforced by
``tests/unit/test_import_rules.py``.
"""

__version__ = "0.1.0"
