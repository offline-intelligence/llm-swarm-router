"""Repo archive path helpers (AP-3 §T2 paths)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from repo_archive_paths import (
    ArchiveRootError,
    assert_removable_partial,
    dated_folder_brisbane,
    final_github_dir,
    github_dated_dir,
    github_slug,
    partial_dir,
    remove_partial_dir,
    validate_archive_root,
)


@pytest.mark.parametrize(
    "root",
    [
        "/mnt/external/movies/x",
        "/mnt/external/movies/torrents/x",
        "/mnt/media/x",
    ],
)
def test_root_under_media_refused(root):
    with pytest.raises(ArchiveRootError):
        validate_archive_root(root)


def test_slug():
    assert github_slug("karpathy/nanoGPT") == "karpathy__nanoGPT"
    assert github_slug("a b/c:d") == "a-b__c-d"


def test_dated_folder_brisbane():
    ts = datetime(2026, 10, 10, 23, 30, tzinfo=timezone.utc)
    assert dated_folder_brisbane(ts) == "2026-10-11"


def test_partial_guard(tmp_path):
    partial = tmp_path / "github-daily" / "2026-10-11" / ".partial-j1"
    partial.mkdir(parents=True)
    assert_removable_partial(partial, "j1")
    with pytest.raises(ValueError):
        assert_removable_partial(tmp_path / "github-daily" / "2026-10-11", "j1")
    other = tmp_path / "github-daily" / "2026-10-11" / ".partial-j2"
    other.mkdir()
    with pytest.raises(ValueError):
        remove_partial_dir(other, "j1")


def test_final_paths(archive_root):
    day = "2026-10-11"
    dated = github_dated_dir(archive_root, day)
    assert final_github_dir(dated, "octocat/Hello-World").name == "octocat__Hello-World"
    assert partial_dir(dated, "job-1").name == ".partial-job-1"
