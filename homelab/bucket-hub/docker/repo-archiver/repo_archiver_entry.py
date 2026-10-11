#!/usr/bin/env python3
"""Repo archiver container entry (GitHub mirror mode).

Reads mode from argv[1], clone URL from argv[2]. Prints one JSON line on stdout.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def github_mirror(clone_url: str) -> dict:
    work = Path("/work")
    work.mkdir(parents=True, exist_ok=True)
    dest = work / "repo.git"
    env = {
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    subprocess.run(
        ["git", "clone", "--mirror", clone_url, str(dest)],
        check=True,
        env={**env, **dict(__import__("os").environ)},
    )
    readme = ""
    try:
        text = subprocess.check_output(
            ["git", "--git-dir", str(dest), "show", "HEAD:README.md"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        readme = text
        (work / "README.md").write_text(text, encoding="utf-8")
    except subprocess.CalledProcessError:
        pass
    sha = subprocess.check_output(
        ["git", "--git-dir", str(dest), "rev-parse", "HEAD"],
        text=True,
    ).strip()
    return {"ok": True, "commit_sha": sha, "readme_text": readme}


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
