"""GitHub repo archive handler (metadata, safe clone, finalise).

Purpose: implement AP-3 ``github_repo`` worker behaviour (spec A5 GitHub).

Inputs: Hub job dict, archive root, runner, mount checker, metadata fetcher.

Outputs: index entry dict and relative ``download_dir`` for the job PATCH.

Side effects: network (metadata), docker clone, filesystem under archive root.

Idempotency: skips clone when index or same-day final folder exists (unless refresh).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from index_writer import append_entry, build_github_entry, load_entries
from repo_archive_paths import (
    final_github_dir,
    github_dated_dir,
    github_slug,
    partial_dir,
    parse_github_full_name,
    remove_partial_dir,
    validate_archive_root,
)
from repo_runner import DockerRepoRunner, RecordingRepoRunner, RepoRunner

log = logging.getLogger("bucket-hub.repo_archive_github")

TNAS_OFFLINE_MSG = "TNAS offline, will retry"
DEFAULT_MAX_MB = 2048
DEFAULT_DEFER_S = 120


def repo_defer_seconds() -> int:
    """Seconds a TNAS-deferred job waits before it can be claimed again (``HUB_REPO_DEFER_S``)."""
    try:
        return max(0, int(os.environ.get("HUB_REPO_DEFER_S", DEFAULT_DEFER_S)))
    except ValueError:
        return DEFAULT_DEFER_S


_runner: RepoRunner | None = None
_fetch_metadata: Callable[[str], dict[str, Any]] | None = None
_fetch_readme: Callable[[str], str] | None = None


def configure(
    runner: RepoRunner | None = None,
    fetch_metadata: Callable[[str], dict[str, Any]] | None = None,
    fetch_readme: Callable[[str], str] | None = None,
) -> None:
    global _runner, _fetch_metadata, _fetch_readme
    if runner is not None:
        _runner = runner
    if fetch_metadata is not None:
        _fetch_metadata = fetch_metadata
    if fetch_readme is not None:
        _fetch_readme = fetch_readme


def fetch_readme_fallback(full_name: str) -> str:
    """README text from the GitHub API when the archiver left none; "" on any failure."""
    if _fetch_readme is None:
        return ""
    try:
        return str(_fetch_readme(full_name) or "")
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("readme fallback failed for %s: %s", full_name, exc)
        return ""


def get_runner() -> RepoRunner:
    global _runner
    if _runner is None:
        image = os.environ.get("REPO_ARCHIVER_IMAGE", "bucket-hub-repo-archiver:2")
        _runner = DockerRepoRunner(image=image)
    return _runner


def github_full_name_from_url(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if "/" not in path:
        raise ValueError(f"not a GitHub repo URL: {url}")
    return path


def fetch_repo_metadata(full_name: str) -> dict[str, Any]:
    if _fetch_metadata is None:
        raise RuntimeError("fetch_metadata not configured (worker must call configure())")
    return _fetch_metadata(full_name)


def safe_clone(
    *,
    job_id: str,
    clone_url: str,
    partial: Path,
    runner: RepoRunner,
    env: dict[str, str],
) -> dict[str, Any]:
    """Clone into ``partial`` via the archiver image (temp dir before rename).

    The caller must create ``partial`` as ``.partial-<job_id>/`` under the dated folder.
    On success the runner leaves ``repo.git/`` and ``README.md`` inside ``partial``.
    """
    partial.mkdir(parents=True, exist_ok=True)
    return runner.run_github_mirror(clone_url=clone_url, work_dir=partial, env=env)


def _index_path(root: Path) -> Path:
    return root / "download-index.jsonl"


def _find_archived_entry(
    entries: dict[str, dict[str, Any]],
    source_id: str,
) -> dict[str, Any] | None:
    for row in entries.values():
        if row.get("source_id") == source_id and row.get("status") == "archived":
            return row
    return None


def _measure_dir(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def run_github_repo_job(
    job: dict[str, Any],
    *,
    archive_root: str | Path,
    path_ready: Callable[[str], tuple[bool, str]],
    update_job: Callable[..., None],
    now: datetime | None = None,
) -> None:
    """Main ``github_repo`` handler invoked from the worker repo pool."""
    root = validate_archive_root(archive_root)
    jid = str(job["id"])
    opts = dict(job.get("options") or {})
    max_mb = int(opts.get("max_size_mb") or DEFAULT_MAX_MB)
    refresh = bool(opts.get("refresh"))
    url = str(job.get("url") or "")
    full_name = github_full_name_from_url(url)
    source_id = f"github:{full_name}"

    now = now or datetime.now(timezone.utc)
    ok, reason = path_ready(str(root))
    if not ok:
        # Back off so a dead mount does not get re-claimed every worker tick.
        retry_at = now + timedelta(seconds=repo_defer_seconds())
        update_job(
            jid,
            status="queued",
            error_display=TNAS_OFFLINE_MSG,
            not_before=retry_at.isoformat(),
            progress={"phase": "checking", "note": TNAS_OFFLINE_MSG},
        )
        return

    from repo_archive_paths import dated_folder_brisbane

    day = dated_folder_brisbane(now)
    dated = github_dated_dir(root, day)
    final_path = final_github_dir(dated, full_name)
    index_entries = load_entries(_index_path(root))
    prior = _find_archived_entry(index_entries, full_name)

    if prior and not refresh:
        note = f"Already archived on {prior.get('downloaded_at', 'unknown')[:10]}"
        update_job(
            jid,
            status="done",
            error=None,
            progress={"phase": "indexing", "note": note},
            download_dir=str(Path("github-daily") / day / github_slug(full_name)),
        )
        return

    if final_path.is_dir() and not refresh:
        update_job(
            jid,
            status="done",
            error=None,
            progress={"phase": "indexing", "note": "Already archived today"},
            download_dir=str(Path("github-daily") / day / github_slug(full_name)),
        )
        return

    meta = fetch_repo_metadata(full_name)
    size_kb = int(meta.get("size") or 0)
    size_mb = size_kb / 1024
    if size_mb > max_mb:
        note = f"Skipped: {size_mb:.0f} MB is over the {max_mb} MB limit"
        entry = build_github_entry(
            job,
            full_name=full_name,
            meta=meta,
            status="skipped_too_large",
            rel_path=str(Path("github-daily") / day / github_slug(full_name)),
            readme_excerpt="",
        )
        append_entry(_index_path(root), entry)
        update_job(
            jid,
            status="done",
            progress={"phase": "indexing", "note": note},
            index_entry=entry,
        )
        return

    partial = partial_dir(dated, jid)
    if partial.is_dir():
        remove_partial_dir(partial, jid)

    update_job(
        jid,
        status="running",
        progress={"phase": "cloning", "note": f"Cloning {full_name}"},
    )
    clone_url = f"https://github.com/{full_name}.git"
    env = {
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    token = os.environ.get("HUB_GITHUB_TOKEN", "").strip()
    if token:
        env["GITHUB_TOKEN"] = token

    try:
        result = safe_clone(
            job_id=jid,
            clone_url=clone_url,
            partial=partial,
            runner=get_runner(),
            env=env,
        )
    except Exception as exc:
        if partial.is_dir():
            remove_partial_dir(partial, jid)
        update_job(jid, status="error", error=str(exc), error_display=str(exc))
        return

    measured = _measure_dir(partial)
    cap_bytes = int(max_mb * 1024 * 1024 * 1.1)
    if measured > cap_bytes:
        remove_partial_dir(partial, jid)
        update_job(
            jid,
            status="error",
            error="Download exceeded the size limit",
            error_display="Download exceeded the size limit",
        )
        return

    readme = str(result.get("readme_text") or "")
    readme_file = partial / "README.md"
    if not readme and readme_file.is_file():
        readme = readme_file.read_text(encoding="utf-8", errors="replace")
    if not readme_file.is_file():
        # Older archiver images only read HEAD:README.md; fall back to the API (spec A5).
        readme = readme or fetch_readme_fallback(full_name)
        if readme:
            readme_file.write_text(readme, encoding="utf-8")

    # Atomic promote: partial → final folder (same filesystem).
    dated.mkdir(parents=True, exist_ok=True)
    if final_path.exists():
        shutil.rmtree(final_path)
    partial.rename(final_path)

    rel = str(Path("github-daily") / day / github_slug(full_name))
    entry = build_github_entry(
        job,
        full_name=full_name,
        meta=meta,
        status="archived",
        rel_path=rel,
        readme_excerpt=readme[:2000],
        commit_sha=str(result.get("commit_sha") or ""),
        size_bytes=measured,
    )
    append_entry(_index_path(root), entry)
    write_provenance_sidecar(final_path, jid, entry)
    write_tags_sidecar_job(final_path, job, jid)

    update_job(
        jid,
        status="done",
        error=None,
        download_dir=rel,
        index_entry=entry,
        resolved={
            "full_name": full_name,
            "default_branch": meta.get("default_branch"),
            "commit_sha": result.get("commit_sha"),
            "stars": meta.get("stargazers_count"),
            "size_kb": size_kb,
        },
        progress={"phase": "indexing", "note": "Complete"},
    )


def write_provenance_sidecar(final: Path, job_id: str, entry: dict[str, Any]) -> None:
    path = final / f".hub-provenance-{job_id}.json"
    path.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")


def write_tags_sidecar_job(final: Path, job: dict[str, Any], job_id: str) -> None:
    tags = job.get("tags") or []
    path = final / f".hub-tags-{job_id}.json"
    path.write_text(json.dumps({"tags": tags}, indent=2) + "\n", encoding="utf-8")
