"""Importable worker helpers (flat module for tests and SSH smoke).

Purpose: expose repo-archive primitives without importing ``hub-worker.py``.

Side effects: none at import; ``safe_clone`` delegates to the configured runner.
"""
from __future__ import annotations

from repo_archive_github import safe_clone

__all__ = ["safe_clone"]
