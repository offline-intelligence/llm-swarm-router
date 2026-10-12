#!/usr/bin/env python3
"""Repo archiver container entry (GitHub mirror mode).

Reads mode from argv[1], clone URL from argv[2]. Prints one JSON line on stdout.

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


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode != "github_mirror":
        print(json.dumps({"ok": False, "error": f"unknown mode {mode}"}))
        return 2
    url = sys.argv[2]
    result = github_mirror(url)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
