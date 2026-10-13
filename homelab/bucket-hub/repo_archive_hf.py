"""Hugging Face repo archive handler (metadata, pattern resolution, snapshot, finalise).

Purpose: implement AP-4 ``huggingface_repo`` worker behaviour (spec A4, A5 common + HF).

Inputs: Hub job dict, archive root, runner, mount checker, metadata fetcher.

Outputs: index entry dict and relative ``download_dir`` for the job PATCH.

Side effects: network (metadata via the worker's Gluetun fetcher), docker snapshot,
filesystem under ``<root>/huggingface-daily/<day>/``.

Idempotency: skips the download when the index has an ``archived`` entry for the same
source or today's final folder exists (unless ``options.refresh``).

Gated repos (AP-4.1): a gated repo the token cannot read yet does not fail. The job goes
back to ``queued`` with a ``gate`` record and ``not_before``, and each re-claim only
re-probes access (one HEAD) until Finn accepts the licence on huggingface.co.
Re-checks follow ``HF_GATE_SCHEDULE_S`` (AP-4.2): gaps of 1, 5 and 30 min, then hourly.
"""
from __future__ import annotations

import fnmatch
import logging
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlparse

from index_writer import append_entry, build_hf_entry, file_summary, load_entries  # noqa: F401
from repo_archive_github import (
    TNAS_OFFLINE_MSG,
    _measure_dir,
    get_runner,
    repo_defer_seconds,
    write_provenance_sidecar,
    write_tags_sidecar_job,
)
from repo_archive_paths import (
    dated_folder_brisbane,
    final_hf_dir,
    hf_dated_dir,
    hf_slug,
    partial_dir,
    remove_partial_dir,
    validate_archive_root,
)
from repo_runner import ArchiverError

log = logging.getLogger("bucket-hub.repo_archive_hf")

DEFAULT_MAX_MB = 20480
REPO_TYPES = ("model", "dataset")
# Weight formats dropped when the repo also ships safetensors (spec A5 HF).
NON_SAFETENSORS_WEIGHTS = ("*.bin", "*.pt", "*.pth", "*.ckpt", "*.h5", "*.msgpack")
GATED_MSG = (
    "Gated model: accept the licence on huggingface.co with the account whose token is on ai-server"
)
NOT_FOUND_MSG = "Repository not found or private"
CARD_FIELDS = ("license", "base_model", "datasets", "language", "tags")
GATE_TIMEOUT_MSG = "Licence not accepted within {hours} h"
NEEDS_TOKEN_MSG = "Gated model: add HF_TOKEN to hub-worker.env on ai-server"
# HEAD on /resolve/ without following redirects: LFS files answer 302 to the CDN.
ACCESS_OK = (200, 301, 302, 303, 307, 308)
ACCESS_DENIED = (401, 403)

_fetch_metadata: Callable[[str, str, str], dict[str, Any]] | None = None
_probe_access: Callable[[str], int] | None = None


class HfRepoError(ValueError):
    """Readable error for a URL or repo the handler will not archive."""


def configure(
    fetch_metadata: Callable[[str, str, str], dict[str, Any]] | None = None,
    probe_access: Callable[[str], int] | None = None,
) -> None:
    """Worker wiring.

    ``fetch_metadata(repo_type, repo_id, revision)`` → HF API JSON.
    ``probe_access(url)`` → HTTP status of an authenticated ``HEAD`` (no redirects).
    """
    global _fetch_metadata, _probe_access
    if fetch_metadata is not None:
        _fetch_metadata = fetch_metadata
    if probe_access is not None:
        _probe_access = probe_access


DEFAULT_GATE_SCHEDULE_S = (60, 300, 1800, 3600)


def gate_schedule() -> tuple[int, ...]:
    """Gaps between access checks; the last gap repeats until access or timeout.

    ``HF_GATE_SCHEDULE_S`` (comma list) wins; a lone legacy ``HF_GATE_RECHECK_S`` means
    a fixed gap. Each gap is at least 30 s.
    """
    raw = os.environ.get("HF_GATE_SCHEDULE_S", "").strip()
    if not raw and os.environ.get("HF_GATE_RECHECK_S", "").strip():
        raw = os.environ["HF_GATE_RECHECK_S"]
    gaps: list[int] = []
    for part in raw.split(","):
        try:
            gaps.append(max(30, int(float(part))))
        except ValueError:
            continue
    return tuple(gaps) or DEFAULT_GATE_SCHEDULE_S


def gate_recheck_seconds(checks: int = 1) -> int:
    """Gap after the ``checks``-th failed check (1-based)."""
    sched = gate_schedule()
    return sched[min(max(checks, 1), len(sched)) - 1]


def gate_max_wait_hours() -> float:
    return max(1.0, float(os.environ.get("HF_GATE_MAX_WAIT_H", "168") or 168))


def hf_token() -> str:
    return (os.environ.get("HF_TOKEN", "") or os.environ.get("HUGGING_FACE_HUB_TOKEN", "")).strip()


def repo_web_url(repo_type: str, repo_id: str) -> str:
    """Model or dataset page, where the licence is accepted."""
    if repo_type == "dataset":
        return f"https://huggingface.co/datasets/{repo_id}"
    return f"https://huggingface.co/{repo_id}"


def resolve_url(repo_type: str, repo_id: str, revision: str, filename: str) -> str:
    return f"{repo_web_url(repo_type, repo_id)}/resolve/{quote(revision, safe='')}/{quote(filename, safe='/')}"


def probe_file(meta: dict[str, Any]) -> str | None:
    """File used for the access probe: the card if present, else the smallest file."""
    rows = siblings(meta)
    if not rows:
        return None
    names = [r["rfilename"] for r in rows]
    if "README.md" in names:
        return "README.md"

    def _size(r: dict[str, Any]) -> int:
        size = r.get("size")
        if size is None and isinstance(r.get("lfs"), dict):
            size = r["lfs"].get("size")
        return int(size or 0)

    return min(rows, key=_size)["rfilename"]


def is_gated(meta: dict[str, Any]) -> bool:
    gated = meta.get("gated")
    return gated not in (None, False, "", "false", "False")


def metadata_api_url(repo_type: str, repo_id: str, revision: str) -> str:
    """HF Hub API URL equivalent to ``model_info``/``dataset_info(files_metadata=True)``."""
    from urllib.parse import quote

    plural = "models" if repo_type == "model" else "datasets"
    return f"https://huggingface.co/api/{plural}/{repo_id}/revision/{quote(revision, safe='')}?blobs=true"


# --- parsing --------------------------------------------------------------------


def parse_hf_url(url: str, repo_type_opt: str | None = None) -> tuple[str, str]:
    """Return ``(repo_type, repo_id)`` from a huggingface.co URL (or ``hf:org/name``)."""
    text = str(url or "").strip()
    if text.startswith("hf:"):
        path = text[3:]
    else:
        parsed = urlparse(text)
        if parsed.netloc.lower() not in ("huggingface.co", "www.huggingface.co", "hf.co"):
            raise HfRepoError(f"Not a Hugging Face URL: {text}")
        path = parsed.path
    parts = [p for p in path.strip("/").split("/") if p]
    repo_type = "model"
    if parts and parts[0] == "spaces":
        raise HfRepoError("Hugging Face Spaces are not archived (models and datasets only)")
    if parts and parts[0] in ("datasets", "models"):
        repo_type = "dataset" if parts[0] == "datasets" else "model"
        parts = parts[1:]
    if len(parts) < 2:
        raise HfRepoError(f"Hugging Face URL needs org/name: {text}")
    repo_id = f"{parts[0]}/{parts[1]}"
    if repo_type_opt:
        opt = str(repo_type_opt).strip().lower()
        if opt == "space":
            raise HfRepoError("Hugging Face Spaces are not archived (models and datasets only)")
        if opt not in REPO_TYPES:
            raise HfRepoError(f"repo_type must be model or dataset, got {repo_type_opt!r}")
        # An explicit /datasets/ URL wins over a default "model" option.
        if repo_type == "model":
            repo_type = opt
    return repo_type, repo_id


def source_id_for(repo_type: str, repo_id: str) -> str:
    return f"hf:{repo_type}/{repo_id}"


# --- patterns and sizes ---------------------------------------------------------


def _norm_patterns(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = [value]
    out = []
    for p in value:
        p = str(p).strip()
        if not p:
            continue
        # huggingface_hub treats "dir/" as "dir/*".
        out.append(p + "*" if p.endswith("/") else p)
    return out or None


def resolve_patterns(
    sibling_names: list[str],
    *,
    allow_patterns: Any = None,
    ignore_patterns: Any = None,
    prefer_safetensors: bool = True,
) -> tuple[list[str] | None, list[str] | None]:
    """Final ``(allow, ignore)`` for ``snapshot_download``.

    ``prefer_safetensors`` adds the non-safetensors weight formats to ``ignore`` when any
    ``*.safetensors`` exists. Explicit ``allow_patterns`` override this (the user chose).
    The card is always kept, so ``README.md`` joins an explicit allow list.
    """
    allow = _norm_patterns(allow_patterns)
    ignore = _norm_patterns(ignore_patterns)
    if allow is not None:
        if "README.md" not in allow:
            allow = allow + ["README.md"]
        return allow, ignore
    if prefer_safetensors and any(n.endswith(".safetensors") for n in sibling_names):
        ignore = list(ignore or []) + [p for p in NON_SAFETENSORS_WEIGHTS if p not in (ignore or [])]
    return None, ignore


def filter_names(
    names: list[str],
    allow: list[str] | None,
    ignore: list[str] | None,
) -> list[str]:
    """Same rule as ``huggingface_hub.utils.filter_repo_objects`` (fnmatch on the path)."""
    out = []
    for name in names:
        if allow is not None and not any(fnmatch.fnmatch(name, p) for p in allow):
            continue
        if ignore is not None and any(fnmatch.fnmatch(name, p) for p in ignore):
            continue
        out.append(name)
    return out


def siblings(meta: dict[str, Any]) -> list[dict[str, Any]]:
    rows = meta.get("siblings") or []
    return [r for r in rows if isinstance(r, dict) and r.get("rfilename")]


def selected_size_bytes(meta: dict[str, Any], allow: list[str] | None, ignore: list[str] | None) -> int:
    rows = siblings(meta)
    keep = set(filter_names([r["rfilename"] for r in rows], allow, ignore))
    total = 0
    for r in rows:
        if r["rfilename"] in keep:
            size = r.get("size")
            if size is None and isinstance(r.get("lfs"), dict):
                size = r["lfs"].get("size")
            total += int(size or 0)
    return total


# --- model card -----------------------------------------------------------------

_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)


def _scalar(text: str) -> Any:
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        return t[1:-1]
    if t.startswith("[") and t.endswith("]"):
        return [_scalar(x) for x in t[1:-1].split(",") if x.strip()]
    return t


def _simple_yaml(block: str) -> dict[str, Any]:
    """Top-level ``key: value`` and ``key:`` + ``- item`` lists; enough for card fields."""
    out: dict[str, Any] = {}
    key: str | None = None
    for raw in block.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0] not in " \t-":
            k, _, v = raw.partition(":")
            key = k.strip()
            out[key] = _scalar(v) if v.strip() else []
            continue
        item = raw.strip()
        if key is not None and item.startswith("- ") and isinstance(out.get(key), list):
            out[key].append(_scalar(item[2:]))
    return out


def parse_card(text: str) -> tuple[dict[str, Any], str]:
    """Return ``(front_matter, body)``; body has the YAML block removed."""
    m = _FRONT_MATTER.match(text or "")
    if not m:
        return {}, text or ""
    block = m.group(1)
    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(block) or {}
        if not isinstance(data, dict):
            data = {}
    except Exception:  # noqa: BLE001 - PyYAML missing or odd YAML: fall back
        data = _simple_yaml(block)
    return data, text[m.end():].lstrip("\n")


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v not in (None, "")]
    return [str(value)]


def card_fields(front: dict[str, Any]) -> dict[str, Any]:
    lang = _as_list(front.get("language"))
    lic = front.get("license")
    return {
        "license": str(lic) if lic not in (None, "", []) else None,
        "base_model": _as_list(front.get("base_model")),
        "datasets": _as_list(front.get("datasets")),
        "language": ", ".join(lang) if lang else None,
        "card_tags": _as_list(front.get("tags")),
    }


# --- handler --------------------------------------------------------------------


def _index_path(root: Path) -> Path:
    return root / "download-index.jsonl"


def _free_space_bytes(root: Path) -> int | None:
    """Free bytes on the volume holding ``root`` (AP-4.3 pre-download guard).

    Never raises: an unreadable/offline mount returns ``None`` and the caller
    skips the check rather than blocking on a stat that cannot answer.
    """
    try:
        return shutil.disk_usage(str(root)).free
    except OSError:
        return None


def _find_archived(entries: dict[str, dict[str, Any]], source_id: str) -> dict[str, Any] | None:
    for row in entries.values():
        if row.get("source_id") == source_id and row.get("status") == "archived":
            return row
    return None


def _readable_error(exc: BaseException) -> str:
    if isinstance(exc, ArchiverError):
        if exc.kind == "gated":
            return GATED_MSG
        if exc.kind == "not_found":
            return NOT_FOUND_MSG
    low = str(exc).lower()
    if "gated" in low or "401" in low or "403" in low:
        return GATED_MSG
    if "404" in low or "repository not found" in low:
        return NOT_FOUND_MSG
    return str(exc) or exc.__class__.__name__


def run_huggingface_repo_job(
    job: dict[str, Any],
    *,
    archive_root: str | Path,
    path_ready: Callable[[str], tuple[bool, str]],
    update_job: Callable[..., None],
    now: datetime | None = None,
) -> None:
    """Main ``huggingface_repo`` handler invoked from the worker repo pool."""
    root = validate_archive_root(archive_root)
    jid = str(job["id"])
    opts = dict(job.get("options") or {})
    try:
        repo_type, repo_id = parse_hf_url(str(job.get("url") or ""), opts.get("repo_type"))
    except HfRepoError as exc:
        update_job(jid, status="error", error=str(exc), error_display=str(exc))
        return
    revision = str(opts.get("revision") or "main")
    max_mb = int(opts.get("max_size_mb") or DEFAULT_MAX_MB)
    refresh = bool(opts.get("refresh"))
    source_id = source_id_for(repo_type, repo_id)

    now = now or datetime.now(timezone.utc)
    ok, reason = path_ready(str(root))
    if not ok:
        retry_at = now + timedelta(seconds=repo_defer_seconds())
        update_job(
            jid,
            status="queued",
            error_display=TNAS_OFFLINE_MSG,
            not_before=retry_at.isoformat(),
            progress={"phase": "checking", "note": f"{TNAS_OFFLINE_MSG} ({reason})"},
        )
        return

    day = dated_folder_brisbane(now)
    dated = hf_dated_dir(root, day)
    final_path = final_hf_dir(dated, repo_type, repo_id)
    rel = str(Path("huggingface-daily") / day / hf_slug(repo_type, repo_id))

    prior = _find_archived(load_entries(_index_path(root)), source_id)
    if prior and not refresh:
        note = f"Already archived on {str(prior.get('downloaded_at') or 'unknown')[:10]}"
        update_job(
            jid,
            status="done",
            error=None,
            progress={"phase": "indexing", "note": note},
            download_dir=str(prior.get("rel_path") or rel),
        )
        return
    if final_path.is_dir() and not refresh:
        update_job(
            jid,
            status="done",
            error=None,
            progress={"phase": "indexing", "note": "Already archived today"},
            download_dir=rel,
        )
        return

    update_job(jid, status="running", progress={"phase": "checking", "note": f"Reading {repo_id}"})
    if _fetch_metadata is None:
        raise RuntimeError("fetch_metadata not configured (worker must call configure())")
    try:
        meta = _fetch_metadata(repo_type, repo_id, revision)
    except Exception as exc:  # noqa: BLE001
        msg = _readable_error(exc)
        update_job(jid, status="error", error=msg, error_display=msg)
        return

    gate_wait_s: int | None = None
    if is_gated(meta):
        state = check_gate(meta, repo_type, repo_id)
        if state != "ok":
            _wait_for_gate(job, update_job, state, meta, repo_type, repo_id, now)
            return
        gate_wait_s = _gate_wait_seconds(job, now)
        prev_gate = job.get("gate") if isinstance(job.get("gate"), dict) else None
        if prev_gate:
            # Access exists now: say so while the download runs (cleared on done).
            update_job(
                jid,
                status="running",  # with error_display None the Hub drops the licence note
                gate={
                    **prev_gate,
                    "state": "granted",
                    "granted_at": now.isoformat(),
                    "checks": int(prev_gate.get("checks") or 0) + 1,
                    "next_check": None,
                },
                error_display=None,
                progress={"phase": "checking", "note": "Access granted, starting download"},
            )

    names = [r["rfilename"] for r in siblings(meta)]
    allow, ignore = resolve_patterns(
        names,
        allow_patterns=opts.get("allow_patterns"),
        ignore_patterns=opts.get("ignore_patterns"),
        prefer_safetensors=opts.get("prefer_safetensors", True) is not False,
    )
    source_size = selected_size_bytes(meta, allow, ignore)
    cap_bytes = max_mb * 1024 * 1024
    if source_size > cap_bytes:
        # AP-4.3: the *job* status must read as a skip, not a plain finish — this used to
        # be "done" (status="done"), which looked identical to a successful archive.
        note = f"Skipped: {source_size / 1048576:.0f} MB is over the {max_mb} MB limit"
        entry = build_hf_entry(
            job,
            repo_type=repo_type,
            repo_id=repo_id,
            meta=meta,
            status="skipped_too_large",
            rel_path=rel,
            readme_excerpt="",
            card={},
            source_size_bytes=source_size,
            files=filter_names(names, allow, ignore),
        )
        append_entry(_index_path(root), entry)
        update_job(
            jid,
            status="skipped_too_large",
            error=None,
            progress={"phase": "indexing", "note": note, "source_size_bytes": source_size},
            index_entry=entry,
        )
        return

    # AP-4.3: free-space guard, more load-bearing now that Download anyway can ask for
    # up to HF_MAX_SIZE_CEILING_MB. Headroom covers the 110% post-check plus other jobs.
    needed_bytes = int(source_size * 1.1) + (50 * 1024 * 1024 * 1024)
    free_bytes = _free_space_bytes(root)
    if free_bytes is not None and free_bytes < needed_bytes:
        retry_at = now + timedelta(hours=1)
        needed_gb = needed_bytes / (1024**3)
        free_gb = free_bytes / (1024**3)
        update_job(
            jid,
            status="queued",
            error_display=f"Not enough space on TNAS (needs {needed_gb:.0f} GB, {free_gb:.0f} GB free)",
            not_before=retry_at.isoformat(),
            progress={"phase": "checking", "note": "Deferred: not enough free space on TNAS"},
        )
        return

    partial = partial_dir(dated, jid)
    if partial.is_dir():
        remove_partial_dir(partial, jid)
    partial.mkdir(parents=True, exist_ok=True)

    # Pin the exact commit the size check saw, so the download cannot drift from it.
    revision_sha = str(meta.get("sha") or revision)
    update_job(
        jid,
        status="running",
        progress={"phase": "downloading", "note": f"Downloading {repo_id} ({source_size / 1048576:.0f} MB)"},
    )
    env = {"HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_ENABLE_HF_TRANSFER": "0"}
    token = hf_token()
    if token:
        env["HF_TOKEN"] = token
    try:
        result = get_runner().run_hf_snapshot(
            repo_id=repo_id,
            spec={
                "repo_type": repo_type,
                "revision": revision_sha,
                "allow_patterns": allow,
                "ignore_patterns": ignore,
            },
            work_dir=partial,
            env=env,
        )
    except Exception as exc:  # noqa: BLE001
        remove_partial_dir(partial, jid)
        if is_gated(meta) and isinstance(exc, ArchiverError) and exc.kind == "gated":
            # Access was lost between the probe and the download: wait again, do not fail.
            state = "awaiting_licence" if token else "needs_token"
            _wait_for_gate(job, update_job, state, meta, repo_type, repo_id, now)
            return
        msg = _readable_error(exc)
        update_job(jid, status="error", error=msg, error_display=msg)
        return

    measured = _measure_dir(partial)
    if measured > int(cap_bytes * 1.1):
        remove_partial_dir(partial, jid)
        update_job(
            jid,
            status="error",
            error="Download exceeded the size limit",
            error_display="Download exceeded the size limit",
        )
        return

    card_text = ""
    snap_readme = partial / "snapshot" / "README.md"
    if snap_readme.is_file():
        card_text = snap_readme.read_text(encoding="utf-8", errors="replace")
        (partial / "README.md").write_text(card_text, encoding="utf-8")
    front, body = parse_card(card_text)
    card = card_fields(front)

    dated.mkdir(parents=True, exist_ok=True)
    if final_path.exists():
        shutil.rmtree(final_path)
    partial.rename(final_path)

    on_disk = sorted(
        str(p.relative_to(final_path / "snapshot"))
        for p in (final_path / "snapshot").rglob("*")
        if p.is_file() and ".cache" not in p.relative_to(final_path / "snapshot").parts
    ) if (final_path / "snapshot").is_dir() else []
    entry = build_hf_entry(
        job,
        repo_type=repo_type,
        repo_id=repo_id,
        meta=meta,
        status="archived",
        rel_path=rel,
        readme_excerpt=body[:2000],
        card=card,
        source_size_bytes=source_size,
        size_bytes=measured,
        files=on_disk,
        revision_sha=str(result.get("revision_sha") or meta.get("sha") or ""),
        readme_path=str(Path(rel) / "README.md") if card_text else None,
        licence_accepted_by="user" if is_gated(meta) else None,
        gate_wait_s=gate_wait_s,
    )
    append_entry(_index_path(root), entry)
    write_provenance_sidecar(final_path, jid, entry)
    write_tags_sidecar_job(final_path, job, jid)

    update_job(
        jid,
        status="done",
        error=None,
        gate=None,
        download_dir=rel,
        index_entry=entry,
        resolved={
            "repo_id": repo_id,
            "repo_type": repo_type,
            "revision_sha": entry.get("revision_sha"),
            "likes": meta.get("likes"),
            "source_size_bytes": source_size,
        },
        progress={"phase": "indexing", "note": "Complete"},
    )


# --- gated repos (AP-4.1) -------------------------------------------------------


def check_gate(meta: dict[str, Any], repo_type: str, repo_id: str) -> str:
    """``ok``, ``awaiting_licence`` or ``needs_token`` for a gated repo.

    An inconclusive probe (network error, odd status) returns ``ok`` so the download
    itself decides; a gated failure there comes back through ``_wait_for_gate``.
    """
    if not hf_token():
        return "needs_token"
    filename = probe_file(meta)
    if not filename or _probe_access is None:
        return "ok"
    revision = str(meta.get("sha") or "main")
    try:
        status = int(_probe_access(resolve_url(repo_type, repo_id, revision, filename)))
    except Exception as exc:  # noqa: BLE001
        log.warning("hf access probe failed for %s: %s", repo_id, exc)
        return "ok"
    if status in ACCESS_DENIED:
        return "awaiting_licence"
    return "ok"


def _parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _gate_wait_seconds(job: dict[str, Any], now: datetime) -> int | None:
    gate = job.get("gate") if isinstance(job.get("gate"), dict) else None
    since = _parse_ts(gate.get("since")) if gate else None
    return int((now - since).total_seconds()) if since else None


def gate_note(state: str, gated: Any, url: str) -> str:
    if state == "needs_token":
        return NEEDS_TOKEN_MSG
    if str(gated) == "manual":
        return f"Waiting for the model owner to approve access: {url}"
    return f"Waiting for licence: accept at {url}"


def _wait_for_gate(
    job: dict[str, Any],
    update_job: Callable[..., None],
    state: str,
    meta: dict[str, Any],
    repo_type: str,
    repo_id: str,
    now: datetime,
) -> None:
    """Park the job until access exists, or fail it after ``HF_GATE_MAX_WAIT_H``."""
    jid = str(job["id"])
    prev = job.get("gate") if isinstance(job.get("gate"), dict) else {}
    since = _parse_ts(prev.get("since")) or now
    url = repo_web_url(repo_type, repo_id)
    gated = meta.get("gated")
    hours = gate_max_wait_hours()
    if now - since > timedelta(hours=hours):
        msg = NEEDS_TOKEN_MSG if state == "needs_token" else GATE_TIMEOUT_MSG.format(hours=int(hours))
        update_job(
            jid,
            status="error",
            error=msg,
            error_display=msg,
            gate=None,
            progress={"phase": "checking", "note": msg},
        )
        return
    note = gate_note(state, gated, url)
    checks = int(prev.get("checks") or 0) + 1
    retry_at = now + timedelta(seconds=gate_recheck_seconds(checks))
    update_job(
        jid,
        status="queued",
        error_display=note,
        not_before=retry_at.isoformat(),
        gate={
            "state": state,
            "gated": gated if gated in ("auto", "manual") else "auto",
            "url": url,
            "since": since.isoformat(),
            "checks": checks,
            "next_check": retry_at.isoformat(),
        },
        progress={"phase": "checking", "note": note},
    )
