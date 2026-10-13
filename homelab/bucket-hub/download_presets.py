"""Download presets and segments (AP-UX-1).

The only place a "type of download → where it lands" rule lives. The form,
Firefox capture, Requests approvals and API callers all resolve through
``resolve()``. Every preset maps onto a job kind the worker already runs; this
module never creates folders and never touches Sonarr/Radarr/aria2 config.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SEGMENTS: tuple[dict[str, str], ...] = (
    {"id": "tv", "label": "TV & film"},
    {"id": "repo", "label": "Repo archive"},
    {"id": "website", "label": "Websites"},
    {"id": "other", "label": "Other"},
)

# ``targets`` are tried in order: (drive role, folder key). Archive-root presets
# have no targets; the worker writes under HUB_REPO_ARCHIVE_ROOT. ``fixed``
# presets ignore capture-folders.json: Sonarr/Radarr import from torrents/ only.
PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "tv",
        "segment": "tv",
        "label": "TV episode or season",
        "kinds": ("magnet", "http"),
        "accepts": ("magnet", "http"),
        "default_kind": "magnet",
        "targets": (("expansion_movies", "torrents"),),
        "fixed": True,
        "note": "Sonarr files it under TV",
    },
    {
        "id": "film",
        "segment": "tv",
        "label": "Film",
        "kinds": ("magnet", "http"),
        "accepts": ("magnet", "http"),
        "default_kind": "magnet",
        "targets": (("expansion_movies", "torrents"),),
        "fixed": True,
        "note": "Radarr files it under Films",
    },
    {
        "id": "github_repo",
        "segment": "repo",
        "label": "GitHub repo",
        "kinds": ("github_repo", "github_release"),
        "accepts": ("github_repo", "github_release", "github"),
        "default_kind": "github_repo",
        "archive_root": "github-daily",
    },
    {
        "id": "hf_repo",
        "segment": "repo",
        "label": "Hugging Face model or dataset",
        "kinds": ("huggingface_repo",),
        "accepts": ("huggingface_repo", "hf"),
        "default_kind": "huggingface_repo",
        "archive_root": "huggingface-daily",
        # AP-4.3: the form's size-tier chip; keep in sync with hfSizeChips in form.html
        # and HF_MAX_SIZE_CEILING_MB (app.py) / DEFAULT_MAX_MB (repo_archive_hf.py).
        "size_limits_mb": (20480, 71680, 204800),
    },
    {
        "id": "hf_files",
        "segment": "repo",
        "label": "Hugging Face: selected files",
        "kinds": ("hf",),
        "accepts": ("huggingface_repo", "hf"),
        "default_kind": "hf",
        "targets": (("nas", "ai_language"),),
        "note": "selected files only",
    },
    {
        "id": "website",
        "segment": "website",
        "label": "Website copy",
        "kinds": ("website_archive",),
        "default_kind": "website_archive",
        "targets": (("nas", "website_backups"), ("expansion_movies", "nas_staging")),
        "note": "adds a <domain>/ folder",
    },
    {
        "id": "video",
        "segment": "other",
        "label": "Video (YouTube etc.)",
        "kinds": ("video",),
        "default_kind": "video",
        "targets": (("nas", "media_archive"), ("media_hdd", "videos")),
    },
    {
        "id": "file",
        "segment": "other",
        "label": "File (direct link)",
        "kinds": ("http",),
        "default_kind": "http",
        "targets": (("nas", "inbox"), ("media_hdd", "inbox")),
    },
)

PRESETS_BY_ID: dict[str, dict[str, Any]] = {p["id"]: p for p in PRESETS}
SEGMENT_IDS = frozenset(s["id"] for s in SEGMENTS)

ROLE_LABELS = {
    "expansion_movies": "Expansion HDD",
    "nas": "TNAS",
    "media_hdd": "Media HDD",
}

# Old capture-folders.json ``type_folder_map`` keys → preset ids. ``magnet``
# (now a fixed preset) and ``website`` (it meant "direct file found on a web
# page", not a site copy) are deliberately not carried over.
LEGACY_MAP_KEYS = {
    "media": "video",
    "video": "video",
    "http": "file",
    "hf": "hf_files",
}


class PresetError(ValueError):
    """Unknown preset id or a kind the preset does not run."""


def _norm(text: Any) -> str:
    s = str(text or "").strip().lower().lstrip("_")
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def resolve_drive(lib: dict[str, Any], role: str) -> str | None:
    """Find the library drive id that plays ``role`` (same rules as the form had)."""
    drives = (lib or {}).get("drives") or {}
    if not isinstance(drives, dict):
        return None
    for did, d in drives.items():
        root = str(d.get("root") or "").rstrip("/")
        label = str(d.get("label") or "").lower()
        if role == "expansion_movies":
            if did in ("ext_movies", "movies_usb") or root.endswith("/external/movies"):
                return did
            if "movies" in label and "external" in root:
                return did
        elif role == "nas":
            if did == "nas" or root == "/mnt/tnas" or root.startswith("/mnt/tnas/"):
                return did
        elif role == "media_hdd":
            if did in ("media_hdd", "media") or root == "/mnt/media":
                return did
    return None


def _find_folder(drive: dict[str, Any], key: str) -> dict[str, Any] | None:
    want = _norm(key)
    for f in drive.get("folders") or []:
        if want in (_norm(f.get("id")), _norm(f.get("rel")), _norm(f.get("name"))):
            return f
    return None


def _abs_path(drive: dict[str, Any], folder: dict[str, Any]) -> str:
    rel = str(folder.get("rel") or "")
    root = Path(str(drive.get("root") or ""))
    return str(root if rel in ("", ".") else root / rel)


def load_overrides(path: Path | None) -> dict[str, dict[str, str]]:
    """``capture-folders.json`` → ``{preset_id: {drive_id, folder_id}}``.

    Accepts the new ``preset_folder_map`` and the old ``type_folder_map`` keys.
    """
    if not path or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for section, keymap in (("type_folder_map", LEGACY_MAP_KEYS), ("preset_folder_map", None)):
        raw = data.get(section)
        if not isinstance(raw, dict):
            continue
        for key, row in raw.items():
            if not isinstance(row, dict):
                continue
            k = str(key).strip().lower()
            pid = keymap.get(k) if keymap is not None else k
            if pid not in PRESETS_BY_ID:
                continue
            if PRESETS_BY_ID[pid].get("archive_root") or PRESETS_BY_ID[pid].get("fixed"):
                continue
            did = str(row.get("drive_id") or "").strip()
            fid = str(row.get("folder_id") or "").strip()
            if did and fid:
                out[pid] = {"drive_id": did, "folder_id": fid}
    return out


def _usable(drive: dict[str, Any] | None, folder: dict[str, Any] | None) -> bool:
    return bool(drive) and drive.get("mounted") is not False and bool(folder) and folder.get("present") is not False


def resolve(
    lib: dict[str, Any],
    preset_id: str,
    *,
    overrides: dict[str, dict[str, str]] | None = None,
    archive_root: str = "",
) -> dict[str, Any]:
    """Where a job for ``preset_id`` lands right now.

    Returns ``{preset, segment, label, available, reason, destination, saves_to,
    fallback_used}``. ``destination`` is ``{drive_id, folder_id, folder_name,
    path, label}`` or ``{archive_root, subdir}``; ``None`` when unavailable.
    """
    p = PRESETS_BY_ID.get(preset_id)
    if not p:
        raise PresetError(f"Unknown preset: {preset_id}")
    out: dict[str, Any] = {
        "preset": p["id"],
        "segment": p["segment"],
        "label": p["label"],
        "available": False,
        "reason": "",
        "destination": None,
        "saves_to": "",
        "fallback_used": False,
    }
    if p.get("archive_root"):
        out["available"] = True
        out["destination"] = {"archive_root": archive_root, "subdir": p["archive_root"]}
        out["saves_to"] = f"TNAS repo archive › {p['archive_root']}"
        return out

    drives = (lib or {}).get("drives") or {}
    candidates: list[tuple[str | None, str, str]] = []
    ov = None if p.get("fixed") else (overrides or {}).get(p["id"])
    if ov:
        candidates.append((ov["drive_id"], ov["folder_id"], "override"))
    for role, folder_key in p["targets"]:
        candidates.append((resolve_drive(lib, role), folder_key, role))

    reasons: list[str] = []
    for idx, (did, folder_key, role) in enumerate(candidates):
        role_label = ROLE_LABELS.get(role, did or role)
        drive = drives.get(did) if did else None
        if not drive:
            reasons.append(f"{role_label} is not in the library")
            continue
        if drive.get("mounted") is False:
            reasons.append(f"{drive.get('label') or role_label} is not mounted on the worker")
            continue
        folder = _find_folder(drive, folder_key)
        if not _usable(drive, folder):
            reasons.append(f"{drive.get('label') or role_label} has no {folder_key}/ folder")
            continue
        assert folder is not None
        drive_label = drive.get("label") or role_label
        out["available"] = True
        # The first table target is the normal place; anything after it is a fallback.
        out["fallback_used"] = role != "override" and idx > (1 if ov else 0)
        out["destination"] = {
            "drive_id": did,
            "folder_id": folder["id"],
            "folder_name": folder.get("name") or folder_key,
            "path": _abs_path(drive, folder),
            "label": f"{drive_label} › {folder.get('name') or folder_key}",
        }
        note = f" ({p['note']})" if p.get("note") else ""
        out["saves_to"] = f"{out['destination']['label']}{note}"
        out["reason"] = "; ".join(reasons)
        return out
    out["reason"] = "; ".join(reasons) or "No destination configured"
    return out


def list_presets(
    lib: dict[str, Any],
    *,
    overrides: dict[str, dict[str, str]] | None = None,
    archive_root: str = "",
) -> dict[str, Any]:
    rows = []
    for p in PRESETS:
        r = resolve(lib, p["id"], overrides=overrides, archive_root=archive_root)
        r["id"] = p["id"]
        r["kinds"] = list(p["kinds"])
        rows.append(r)
    return {"segments": [dict(s) for s in SEGMENTS], "presets": rows}


def suggest(url: str, detected_kind: str, *, torrent_category: str = "") -> str:
    """Pick a preset for a pasted URL (the user can switch before queueing)."""
    k = (detected_kind or "").strip().lower()
    cat = (torrent_category or "").strip().lower()
    if k in ("github_repo", "github_release", "github"):
        return "github_repo"
    if k == "huggingface_repo":
        return "hf_repo"
    if k == "hf":
        return "hf_files"
    if k == "website_archive":
        return "website"
    if k == "video":
        return "video"
    if k == "magnet":
        return "film" if cat in ("movies", "movie", "film", "films") else "tv"
    return "file"


def job_kind_for(preset_id: str, detected_kind: str, explicit_kind: str = "") -> str:
    """Job kind a preset runs. An explicit kind must be one the preset accepts."""
    p = PRESETS_BY_ID.get(preset_id)
    if not p:
        raise PresetError(f"Unknown preset: {preset_id}")
    ek = (explicit_kind or "").strip().lower()
    if ek and ek != "auto":
        if ek not in p["kinds"]:
            raise PresetError(f"Preset {preset_id} does not run {ek} jobs")
        return ek
    dk = (detected_kind or "").strip().lower()
    accepts = p.get("accepts")
    if accepts is not None and dk and dk not in accepts:
        raise PresetError(f"This link does not look like a {p['label']} link")
    if dk in p["kinds"]:
        return dk
    return p["default_kind"]


def segment_for_kind(kind: str) -> str:
    """Segment for jobs created before presets existed (queue filter)."""
    k = (kind or "").strip().lower()
    if k in ("magnet",):
        return "tv"
    if k in ("github", "hf", "github_repo", "huggingface_repo", "github_release"):
        return "repo"
    if k == "website_archive":
        return "website"
    return "other"
