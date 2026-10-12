"""Docker-backed repo archiver runner (testable via ``RecordingRepoRunner``).

Purpose: run ``bucket-hub-repo-archiver`` in Gluetun's network namespace.

Inputs: mode (``github_mirror``), work directory mount, env dict (tokens).

Outputs: parsed JSON result dict from the container entry script.

Side effects: ``docker run``, temporary env-file on disk (always deleted).

Idempotency: each call is independent; no global state.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class RepoRunner(Protocol):
    def run_github_mirror(
        self,
        *,
        clone_url: str,
        work_dir: Path,
        env: dict[str, str],
    ) -> dict[str, Any]:
        ...


@dataclass
class RecordingRepoRunner:
    """Fake runner for unit tests; records calls and can simulate success/failure."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    payload_bytes: int = 1024
    raise_error: str | None = None

    def run_github_mirror(
        self,
        *,
        clone_url: str,
        work_dir: Path,
        env: dict[str, str],
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "mode": "github_mirror",
                "clone_url": clone_url,
                "work_dir": str(work_dir),
                "env_keys": sorted(env.keys()),
            }
        )
        if self.raise_error:
            raise RuntimeError(self.raise_error)
        work_dir.mkdir(parents=True, exist_ok=True)
        git_dir = work_dir / "repo.git"
        git_dir.mkdir(parents=True, exist_ok=True)
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        readme = work_dir / "README.md"
        readme.write_text("# fixture\n", encoding="utf-8")
        # Simulate payload size for post-check tests.
        (work_dir / "payload.bin").write_bytes(b"x" * self.payload_bytes)
        return {
            "ok": True,
            "commit_sha": "deadbeef",
            "readme_text": readme.read_text(encoding="utf-8"),
        }


def container_name_for(work_dir: Path) -> str:
    """Stable container name per job (``hub-repo-partial-<job_id>``) so orphans can be removed."""
    return "hub-repo-" + work_dir.name.lstrip(".")


def remove_container(name: str) -> bool:
    """``docker rm -f <name>``; True if a container was removed. Never raises."""
    try:
        proc = subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception:  # noqa: BLE001
        return False
    return proc.returncode == 0


class DockerRepoRunner:
    def __init__(
        self,
        image: str,
        gluetun_container: str = "gluetun",
    ) -> None:
        self.image = image
        self.gluetun_container = gluetun_container

    def run_github_mirror(
        self,
        *,
        clone_url: str,
        work_dir: Path,
        env: dict[str, str],
    ) -> dict[str, Any]:
        work_dir.mkdir(parents=True, exist_ok=True)
        name = container_name_for(work_dir)
        # A container left by a killed worker would race this clone for the same partial dir.
        remove_container(name)
        env_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                prefix="hub-repo-env-",
                delete=False,
            ) as fh:
                env_path = fh.name
                for key, val in env.items():
                    fh.write(f"{key}={val}\n")
            os.chmod(env_path, 0o600)
            cmd = [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                f"--network=container:{self.gluetun_container}",
                "--env-file",
                env_path,
                "-v",
                f"{work_dir.resolve()}:/work",
                self.image,
                "github_mirror",
                clone_url,
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=4 * 3600,
            )
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr or proc.stdout or "repo archiver failed")
            line = (proc.stdout or "").strip().splitlines()[-1]
            return json.loads(line)
        finally:
            if env_path and os.path.isfile(env_path):
                os.unlink(env_path)
