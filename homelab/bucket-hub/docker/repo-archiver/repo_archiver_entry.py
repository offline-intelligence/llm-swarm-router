#!/usr/bin/env python3
"""Repo archiver container entry (GitHub mirror and Hugging Face snapshot modes).

``github_mirror <clone_url>`` or ``hf_snapshot <repo_id> <spec-json>``. Prints one JSON
line on stdout; on a known failure prints ``{"ok": false, "error_kind", "error"}`` and
exits 3. Tokens come from the environment (``--env-file``), never argv.

The archive is a bare repo holding branches and tags only. ``git clone --mirror``
also copies GitHub's ``refs/pull/*`` (every PR head, including fork commits), which
the API size check does not count and which made popular repos blow the size cap.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Preferred README names, most specific first. Matching is case-insensitive.
README_PREFERENCE = (
    "readme.md",
    "readme.markdown",
    "readme",
    "readme.rst",
    "readme.txt",
)


def pick_readme(names: list[str]) -> str | None:
    """Return the top-level README path to copy, or None.

    ``names`` is the output of ``git ls-tree --name-only HEAD`` (top level only).
    Any ``README.*`` not in the preference list is a last resort.
    """
    by_lower = {n.lower(): n for n in names}
    for want in README_PREFERENCE:
        if want in by_lower:
            return by_lower[want]
    others = sorted(n for n in names if n.lower().startswith("readme."))
    return others[0] if others else None


# Branches and tags only: no refs/pull/*, refs/changes/* or other host-side refs.
FETCH_REFSPECS = (
    "+refs/heads/*:refs/heads/*",
    "+refs/tags/*:refs/tags/*",
)


def remote_head(clone_url: str, env: dict) -> str | None:
    """Return the remote default branch ref (``refs/heads/<name>``), or None."""
    out = subprocess.check_output(
        ["git", "ls-remote", "--symref", clone_url, "HEAD"],
        text=True,
        env=env,
    )
    for line in out.splitlines():
        if line.startswith("ref: ") and line.endswith("\tHEAD"):
            return line[len("ref: "):].split("\t", 1)[0]
    return None


def github_mirror(clone_url: str) -> dict:
    work = Path("/work")
    work.mkdir(parents=True, exist_ok=True)
    dest = work / "repo.git"
    env = {
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    run_env = {**env, **dict(os.environ)}
    git_dir = ["git", "--git-dir", str(dest)]
    subprocess.run(["git", "init", "--bare", "--quiet", str(dest)], check=True, env=run_env)
    subprocess.run([*git_dir, "config", "remote.origin.url", clone_url], check=True, env=run_env)
    subprocess.run([*git_dir, "config", "remote.origin.fetch", FETCH_REFSPECS[0]], check=True, env=run_env)
    for spec in FETCH_REFSPECS[1:]:
        subprocess.run([*git_dir, "config", "--add", "remote.origin.fetch", spec], check=True, env=run_env)
    subprocess.run([*git_dir, "fetch", "--prune", "--quiet", "origin"], check=True, env=run_env)
    head = remote_head(clone_url, run_env)
    if head:
        subprocess.run([*git_dir, "symbolic-ref", "HEAD", head], check=True, env=run_env)
    readme = ""
    readme_source = None
    try:
        listing = subprocess.check_output(
            ["git", "--git-dir", str(dest), "ls-tree", "--name-only", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        readme_source = pick_readme(listing.splitlines())
        if readme_source:
            readme = subprocess.check_output(
                ["git", "--git-dir", str(dest), "show", f"HEAD:{readme_source}"],
                text=True,
                errors="replace",
                stderr=subprocess.DEVNULL,
            )
            # Always saved as README.md beside repo.git (spec A3), whatever the source name.
            (work / "README.md").write_text(readme, encoding="utf-8")
    except subprocess.CalledProcessError:
        readme = ""
        readme_source = None
    sha = subprocess.check_output(
        ["git", "--git-dir", str(dest), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    return {
        "ok": True,
        "commit_sha": sha,
        "readme_text": readme,
        "readme_source": readme_source,
    }


def _hf_error_kind(exc: BaseException) -> str:
    """Map huggingface_hub errors to ``gated`` / ``not_found`` / ``failed`` by class name."""
    names = {c.__name__ for c in type(exc).__mro__}
    if "GatedRepoError" in names:
        return "gated"
    if names & {"RepositoryNotFoundError", "RevisionNotFoundError", "EntryNotFoundError"}:
        return "not_found"
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in (401, 403):
        return "gated"
    if status == 404:
        return "not_found"
    return "failed"


def hf_snapshot(repo_id: str, spec: dict) -> dict:
    """``snapshot_download`` into ``/work/snapshot`` and copy the card to ``/work/README.md``."""
    from huggingface_hub import snapshot_download

    work = Path("/work")
    work.mkdir(parents=True, exist_ok=True)
    snap = work / "snapshot"
    snapshot_download(
        repo_id=repo_id,
        repo_type=spec.get("repo_type") or "model",
        revision=spec.get("revision") or "main",
        local_dir=str(snap),
        allow_patterns=spec.get("allow_patterns"),
        ignore_patterns=spec.get("ignore_patterns"),
        token=os.environ.get("HF_TOKEN") or None,
    )
    card = snap / "README.md"
    if card.is_file():
        (work / "README.md").write_text(card.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return {"ok": True, "revision_sha": spec.get("revision"), "card": card.is_file()}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "github_mirror":
        print(json.dumps(github_mirror(sys.argv[2])))
        return 0
    if mode == "hf_snapshot":
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
        try:
            result = hf_snapshot(sys.argv[2], json.loads(sys.argv[3]))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"ok": False, "error_kind": _hf_error_kind(exc), "error": str(exc)[:500]}))
            return 3
        print(json.dumps(result))
        return 0
    print(json.dumps({"ok": False, "error": f"unknown mode {mode}"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
