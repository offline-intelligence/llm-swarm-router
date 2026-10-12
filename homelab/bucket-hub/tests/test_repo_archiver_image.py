"""Archiver image entry and Docker runner argv (AP-3 §T2 deferred, AP-3.1)."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

HUB_ROOT = Path(__file__).resolve().parents[1]


def _entry_mod():
    path = HUB_ROOT / "docker" / "repo-archiver" / "repo_archiver_entry.py"
    spec = importlib.util.spec_from_file_location("repo_archiver_entry", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    ("names", "want"),
    [
        (["LICENSE", "README"], "README"),
        (["README.md", "README.txt"], "README.md"),
        (["Readme.MD", "src"], "Readme.MD"),
        (["readme.rst"], "readme.rst"),
        (["README.txt", "README"], "README"),
        (["README.adoc"], "README.adoc"),
        (["docs", "LICENSE"], None),
    ],
)
def test_pick_readme(names, want):
    assert _entry_mod().pick_readme(names) == want


def test_entry_mirror_and_readme_copy(tmp_path, monkeypatch):
    """Mirror argv, ls-tree lookup, README copied as README.md whatever its source name."""
    mod = _entry_mod()
    work = tmp_path / "work"
    real_path = mod.Path
    monkeypatch.setattr(mod, "Path", lambda p: real_path(str(p).replace("/work", str(work), 1)))
    runs: list[list[str]] = []

    def fake_run(cmd, check=True, env=None):
        runs.append(cmd)
        assert env["GIT_LFS_SKIP_SMUDGE"] == "1"
        assert env["GIT_TERMINAL_PROMPT"] == "0"

    def fake_check_output(cmd, text=True, stderr=None, errors=None):
        if "ls-tree" in cmd:
            return "LICENSE\nREADME\n"
        if "show" in cmd:
            assert cmd[-1] == "HEAD:README"
            return "Hello World!\n"
        if "rev-parse" in cmd:
            return "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d\n"
        raise AssertionError(cmd)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.subprocess, "check_output", fake_check_output)
    result = mod.github_mirror("https://github.com/octocat/Hello-World.git")
    assert runs[0][:3] == ["git", "clone", "--mirror"]
    assert runs[0][3] == "https://github.com/octocat/Hello-World.git"
    assert "--recurse-submodules" not in runs[0]
    assert (work / "README.md").read_text(encoding="utf-8") == "Hello World!\n"
    assert result["readme_source"] == "README"
    assert result["readme_text"] == "Hello World!\n"


def test_docker_runner_argv_uses_gluetun_and_env_file(tmp_path, monkeypatch):
    import repo_runner

    seen: dict = {}

    def fake_run(cmd, capture_output=True, text=True, timeout=None):
        seen["cmd"] = cmd
        env_file = cmd[cmd.index("--env-file") + 1]
        seen["env_file"] = env_file
        seen["env_mode"] = oct(os.stat(env_file).st_mode & 0o777)
        seen["env_text"] = Path(env_file).read_text(encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"ok": True}) + "\n", stderr="")

    monkeypatch.setattr(repo_runner.subprocess, "run", fake_run)
    runner = repo_runner.DockerRepoRunner(image="bucket-hub-repo-archiver:2")
    out = runner.run_github_mirror(
        clone_url="https://github.com/octocat/Hello-World.git",
        work_dir=tmp_path / ".partial-j1",
        env={"GITHUB_TOKEN": "ghp_secretvalue123", "GIT_TERMINAL_PROMPT": "0"},
    )
    cmd = seen["cmd"]
    assert out == {"ok": True}
    assert "--network=container:gluetun" in cmd
    assert cmd[-3:] == [
        "bucket-hub-repo-archiver:2",
        "github_mirror",
        "https://github.com/octocat/Hello-World.git",
    ]
    assert f"{(tmp_path / '.partial-j1').resolve()}:/work" in cmd
    assert not any("ghp_secretvalue123" in part for part in cmd)
    assert "GITHUB_TOKEN=ghp_secretvalue123" in seen["env_text"]
    assert seen["env_mode"] == "0o600"
    assert not os.path.exists(seen["env_file"])


def test_docker_runner_deletes_env_file_on_failure(tmp_path, monkeypatch):
    import repo_runner

    seen: dict = {}

    def fake_run(cmd, capture_output=True, text=True, timeout=None):
        seen["env_file"] = cmd[cmd.index("--env-file") + 1]
        return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: repository not found")

    monkeypatch.setattr(repo_runner.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="repository not found"):
        repo_runner.DockerRepoRunner(image="x").run_github_mirror(
            clone_url="https://github.com/a/b.git", work_dir=tmp_path / "w", env={"GITHUB_TOKEN": "t"}
        )
    assert not os.path.exists(seen["env_file"])
