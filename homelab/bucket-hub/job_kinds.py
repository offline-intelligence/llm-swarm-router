"""Shared job-kind routing. A missing kind must never be treated as a torrent."""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("bucket-hub.job_kinds")

ARIA2_KINDS = frozenset({"http", "magnet"})
VIDEO_KINDS = frozenset({"video"})
VIDEO_WORKERS = frozenset({"metube"})
REPO_KINDS = frozenset(
    {
        "github",
        "hf",
        "github_repo",
        "huggingface_repo",
        "github_release",
    }
)
# Kinds the worker writes under ``HUB_REPO_ARCHIVE_ROOT``; the Pi ignores drive/folder.
# Legacy ``github``/``hf`` stay drive-based (they need ``destination_path``).
ARCHIVE_ROOT_KINDS = frozenset({"github_repo", "huggingface_repo", "github_release"})
REPO_META_KINDS = frozenset(
    {
        "github_stars_sync",
        "huggingface_likes_sync",
        "github_releases_sync",
    }
)


def is_repo_download_kind(kind: str) -> bool:
    return str(kind or "").strip().lower() in REPO_KINDS


def is_archive_root_kind(kind: str) -> bool:
    return str(kind or "").strip().lower() in ARCHIVE_ROOT_KINDS


def is_repo_meta_kind(kind: str) -> bool:
    return str(kind or "").strip().lower() in REPO_META_KINDS


def is_aria2_job(job: dict[str, Any]) -> bool:
    """True only when worker is aria2, or worker is missing and kind is http/magnet."""
    worker = str(job.get("worker") or "").strip()
    if worker == "aria2":
        return True
    if worker:
        return False
    kind = str(job.get("kind") or "").strip().lower()
    if not kind:
        log.warning("job %s has neither worker nor kind; not treating as aria2", job.get("id"))
        return False
    return kind in ARIA2_KINDS


def dispatch_route(job: dict[str, Any]) -> str:
    """Return ``aria2``, ``video``, ``repo``, ``repo_meta`` or ``process``."""
    if is_aria2_job(job):
        return "aria2"
    kind = str(job.get("kind") or "").strip().lower()
    worker = str(job.get("worker") or "").strip()
    if kind in REPO_KINDS or worker == "repo":
        return "repo"
    if kind in REPO_META_KINDS:
        return "repo_meta"
    if kind in VIDEO_KINDS or worker in VIDEO_WORKERS:
        return "video"
    return "process"
