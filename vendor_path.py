"""vendor_path.py — put the repository's vendored packages on sys.path.

One place, so there is exactly one answer to "where does `import yaml` come from".
Called before any vendored import. Idempotent, and a no-op when a real installed
PyYAML is already importable, so a developer with it in a venv keeps using theirs.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_VENDOR = os.path.join(_HERE, "_vendor")


def ensure():
    """Make the vendored packages importable. Returns the path added, or None."""
    if not os.path.isdir(_VENDOR):
        return None
    if _VENDOR in sys.path:
        return _VENDOR
    # Appended, not prepended: an installed PyYAML wins, so a developer's venv is
    # authoritative and the vendored copy is the fallback that makes a bare machine work.
    sys.path.append(_VENDOR)
    return _VENDOR
