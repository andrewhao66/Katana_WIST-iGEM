#!/usr/bin/env python3
"""katana_lock.py — compatibility shim over core.lock, core.hashing and core.parts.

This module WAS the Parts Library integrity core. It is now a thin forwarding layer, so
that `verify_library_v2.py`, `test_seal_gaps.py` and anything outside this repository
that imported it keep working while the implementation lives in one place.

The move is the point. This file was meant to be the shared core and was imported by
exactly two files, both on the verifier path; the build engine, the intake gate, the
finder and four Kagami modules each wrote their own manifest parser. Two of those copies
disagreed about the two things that matter -- whether a row's hash is recomputed before
the root is checked (CODE-REPORT finding A) and whether a Spec's pin or the highest
version number decides which part is loaded (finding B). Nothing forced convergence
until core/ existed.

New code imports core.lock, core.hashing and core.parts directly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.hashing import (FIELDS, HEADER, file_sha256, row_manifest,  # noqa: F401
                          row_sha256, seq_sha256, sha256_hex)
from core.hashing import lock_root as _core_lock_root
from core.lock import LockError, filename_sha12  # noqa: F401
from core.lock import read as _core_read
from core.lock import resolve as _core_resolve
from core.lock import verify_root  # noqa: F401
from core.parts import count_pending, read_sequence, verify_library  # noqa: F401


class ResolveError(LockError):
    """Kept so `except katana_lock.ResolveError` in older callers still catches."""


def sha256_bytes(b):
    return sha256_hex(b)


def parse_sequence(path):
    """The sequence a part file holds, exactly as seq_sha256 was computed over it."""
    return read_sequence(path)


def file_hash(path):
    return file_sha256(path)


def seq_hash(path):
    return seq_sha256(read_sequence(path))


def read_lock(path):
    return _core_read(path)


def lock_root(rows):
    return _core_lock_root(rows)


def resolve(rows, id, version=None, expected_seq_sha12=None):
    """Historic signature: positional `version`, `expected_seq_sha12` as the pin.

    The old implementation REQUIRED a version and refused id-only resolution, which was
    correct and is preserved here: core.lock.resolve accepts a bare id when the library
    holds exactly one version of it, and this wrapper keeps the stricter rule its
    callers were written against.
    """
    if version is None:
        raise ResolveError("id-only resolution is banned (Gap 2): pass a version for '%s'"
                           % id)
    try:
        return _core_resolve(rows, id, pin=expected_seq_sha12, version=version)
    except LockError as exc:
        raise ResolveError(str(exc))
