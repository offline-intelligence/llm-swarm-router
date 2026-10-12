"""TNAS repo-archive path helpers (dated folders, slugs, partial guards).

Purpose: compute safe paths under ``HUB_REPO_ARCHIVE_ROOT`` for GitHub/HF archives.

Inputs: archive root, Brisbane calendar date, owner/repo slug, job id.

Outputs: ``Path`` objects for dated dirs, partial work dirs, and final item dirs.

Side effects: none in pure helpers; ``remove_partial_dir`` deletes one directory.

Idempotency: final path helpers are deterministic; partial dirs are per job id.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BRISBANE = ZoneInfo("Australia/Brisbane")
_SLUG_BAD = re.compile(r"[^A-Za-z0-9._-]+")

FORBIDDEN_ROOT_PREFIXES = (
    "/mnt/external/movies",
    "/mnt/media",
    "/mnt/torrents",
)


class ArchiveRootError(ValueError):
    """Archive root is missing or under a media/torrent path."""


def validate_archive_root(root: str | Path) -> Path:
    """Reject archive roots that overlap media or torrent storage."""
    p = Path(root).resolve()
    text = str(p)
    for prefix in FORBIDDEN_ROOT_PREFIXES:
        if text == prefix or text.startswith(prefix + "/"):
            raise ArchiveRootError(f"repo archive root must not be under {prefix}")
    return p


def github_slug(full_name: str) -> str:
    """``owner/repo`` → ``owner__repo`` with unsafe characters normalised."""
    owner, repo = parse_github_full_name(full_name)
    return f"{slug_segment(owner)}__{slug_segment(repo)}"


def slug_segment(text: str) -> str:
    return _SLUG_BAD.sub("-", text.strip()).strip("-") or "unknown"


def parse_github_full_name(full_name: str) -> tuple[str, str]:
    parts = str(full_name).strip().strip("/").split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"invalid GitHub full_name: {full_name!r}")
    return parts[0], parts[1]


def dated_folder_brisbane(now: datetime) -> str:
    """Return ``YYYY-MM-DD`` for the Brisbane local calendar day."""
    local = now.astimezone(BRISBANE)
    return local.strftime("%Y-%m-%d")


def github_dated_dir(root: Path, day: str) -> Path:
    return root / "github-daily" / day


def hf_dated_dir(root: Path, day: str) -> Path:
    return root / "huggingface-daily" / day


def hf_slug(repo_type: str, repo_id: str) -> str:
    """``model``, ``org/name`` → ``models__org__name`` (spec A3)."""
    org, name = parse_github_full_name(repo_id)
    return f"{slug_segment(repo_type)}s__{slug_segment(org)}__{slug_segment(name)}"


def final_hf_dir(dated: Path, repo_type: str, repo_id: str) -> Path:
    return dated / hf_slug(repo_type, repo_id)


DAILY_ROOTS = ("github-daily", "huggingface-daily")


def partial_dir(dated: Path, job_id: str) -> Path:
    return dated / f".partial-{job_id}"


def final_github_dir(dated: Path, full_name: str) -> Path:
    return dated / github_slug(full_name)


def assert_removable_partial(path: Path, job_id: str) -> None:
    """Guard: only ``.partial-<job_id>`` directly under a dated github/huggingface folder."""
    name = path.name
    expected = f".partial-{job_id}"
    if name != expected:
        raise ValueError(f"refusing to remove non-partial path: {path}")
    parent = path.parent
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", parent.name):
        raise ValueError(f"partial parent must be a dated folder: {parent}")
    if parent.parent.name not in DAILY_ROOTS:
        raise ValueError(f"partial must live under {' or '.join(DAILY_ROOTS)}: {parent}")


def remove_partial_dir(path: Path, job_id: str) -> None:
    assert_removable_partial(path, job_id)
    if path.is_dir():
        import shutil

        shutil.rmtree(path)
