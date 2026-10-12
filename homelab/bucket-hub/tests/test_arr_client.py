"""OPS-ARR2: worker → Sonarr/Radarr transport and the api_unreachable / add_failed split."""
from __future__ import annotations

import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

import arr_client
from arr_client import ArrHTTPError, ArrUnreachable, target
from job_health import evaluate_job_health

HUB_ROOT = Path(__file__).resolve().parents[1]
KEY = "k-test-0123456789"


def _worker_mod():
    sys.path.insert(0, str(HUB_ROOT))
    if "hub-worker" in sys.modules:
        return importlib.reload(sys.modules["hub-worker"])
    return importlib.import_module("hub-worker")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def fake_arr():
    seen: list[dict] = []

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body):
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802
            seen.append({"path": self.path, "headers": dict(self.headers)})
            if self.headers.get("X-Api-Key") != KEY:
                return self._send(401, {"error": "unauthorised"})
            self._send(200, {"version": "4.0.0"})

        def log_message(self, *a):  # quiet
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", seen
    srv.shutdown()


def test_a1_target_from_env():
    t = target("sonarr", {})
    assert (t.url, t.port, t.transport, t.configured) == ("http://127.0.0.1:8989", 8989, "http", False)
    t = target("radarr", {"RADARR_URL": "http://10.0.0.5:7000/", "RADARR_API_KEY": KEY, "RADARR_VIA_DOCKER": " radarr "})
    assert (t.url, t.port, t.transport, t.configured) == ("http://10.0.0.5:7000", 7000, "docker:radarr", True)


def test_a2_classify():
    reset = urllib.error.URLError(ConnectionResetError(104, "Connection reset by peer"))
    assert arr_client.classify(reset) == "api_unreachable"
    assert arr_client.classify(ConnectionRefusedError()) == "api_unreachable"
    assert arr_client.classify(TimeoutError()) == "api_unreachable"
    assert arr_client.classify(ArrHTTPError(400)) == "add_failed"
    assert arr_client.classify(ValueError("bad payload")) == "add_failed"


def test_a3_http_ok_401_and_refused(fake_arr):
    url, seen = fake_arr
    t = target("sonarr", {"SONARR_URL": url, "SONARR_API_KEY": KEY})
    assert arr_client.request(t, "GET", "/api/v3/system/status") == {"version": "4.0.0"}
    assert "X-Worker-Token" not in seen[-1]["headers"]  # the Hub worker token never goes to *arr
    bad = target("sonarr", {"SONARR_URL": url, "SONARR_API_KEY": "wrong"})
    with pytest.raises(ArrHTTPError) as e:
        arr_client.request(bad, "GET", "/api/v3/system/status")
    assert e.value.status == 401 and e.value.code == "add_failed"
    dead = target("sonarr", {"SONARR_URL": f"http://127.0.0.1:{_free_port()}", "SONARR_API_KEY": KEY})
    with pytest.raises(ArrUnreachable):
        arr_client.request(dead, "GET", "/api/v3/system/status", timeout=2)


def _fake_run(returncode=0, stdout="", stderr=""):
    calls: list[dict] = []

    def run(cmd, **kw):
        calls.append({"cmd": cmd, "input": kw.get("input")})
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    return run, calls


def test_a4_docker_transport_key_on_stdin_only(monkeypatch):
    run, calls = _fake_run(stdout='[{"id": 3}]' + arr_client._STATUS_MARK + "201")
    monkeypatch.setattr(arr_client.subprocess, "run", run)
    t = target("sonarr", {"SONARR_API_KEY": KEY, "SONARR_VIA_DOCKER": "sonarr"})
    out = arr_client.request(t, "POST", "/api/v3/command", {"name": "DownloadedEpisodesScan", "path": '/data/torrents/a "b"'})
    assert out == [{"id": 3}]
    cmd, cfg = calls[0]["cmd"], calls[0]["input"]
    assert cmd == ["docker", "exec", "-i", "sonarr", "curl", "-K", "-"]
    assert KEY not in " ".join(cmd) and KEY in cfg
    assert 'url = "http://127.0.0.1:8989/api/v3/command"' in cfg
    body = {"name": "DownloadedEpisodesScan", "path": '/data/torrents/a "b"'}
    assert f"data-raw = {arr_client._curl_quote(json.dumps(body))}" in cfg  # quotes escaped for curl -K


@pytest.mark.parametrize(
    "rc,stdout,exc",
    [
        (7, "", ArrUnreachable),  # curl: connection refused inside the container
        (125, "", ArrUnreachable),  # docker: no such container
        (127, "", ArrUnreachable),  # curl missing from the image
        (0, "{}" + arr_client._STATUS_MARK + "000", ArrUnreachable),
        (0, "{}" + arr_client._STATUS_MARK + "404", ArrHTTPError),
    ],
)
def test_a5_docker_errors(monkeypatch, rc, stdout, exc):
    run, _calls = _fake_run(returncode=rc, stdout=stdout, stderr="curl: (7) Failed to connect")
    monkeypatch.setattr(arr_client.subprocess, "run", run)
    t = target("radarr", {"RADARR_API_KEY": KEY, "RADARR_VIA_DOCKER": "radarr"})
    with pytest.raises(exc):
        arr_client.request(t, "GET", "/api/v3/movie")


def test_a6_check_and_cli(fake_arr, monkeypatch, capsys):
    url, _seen = fake_arr
    for k in ("SONARR_URL", "SONARR_API_KEY", "SONARR_VIA_DOCKER", "RADARR_URL", "RADARR_API_KEY", "RADARR_VIA_DOCKER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SONARR_URL", url)
    monkeypatch.setenv("SONARR_API_KEY", KEY)
    assert arr_client.main(["--check"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(r["service"], r["code"]) for r in rows] == [("sonarr", "ok"), ("radarr", "not_configured")]
    monkeypatch.setenv("RADARR_URL", f"http://127.0.0.1:{_free_port()}")
    monkeypatch.setenv("RADARR_API_KEY", KEY)
    assert arr_client.main(["--check"]) == 1
    out = capsys.readouterr().out
    assert KEY not in out and '"code": "api_unreachable"' in out


def _tv_job():
    return {"id": "tv1", "title": "The.Office.US.S03.1080p.BluRay.x265-RARBG", "tags": ["tv"], "status": "running"}


def test_w1_ensure_series_reports_api_unreachable(monkeypatch):
    mod = _worker_mod()
    monkeypatch.setattr(mod, "SONARR_API_KEY", KEY)

    def boom(*_a, **_k):
        raise ArrUnreachable("sonarr http: ConnectionResetError")

    monkeypatch.setattr(mod.arr_client, "request", boom)
    assert mod.ensure_sonarr_series_for_job(_tv_job()) == "api_unreachable"


def _notify(monkeypatch, mod, tmp_path, request):
    folder = tmp_path / "The.Office.US.S03"
    folder.mkdir(exist_ok=True)
    patched: dict = {}
    monkeypatch.setattr(mod, "SONARR_API_KEY", KEY)
    monkeypatch.setattr(mod, "JELLYFIN_API_KEY", "")
    monkeypatch.setattr(mod, "_aria2_host_download_dir", lambda gid: folder)
    monkeypatch.setattr(mod, "update_job", lambda jid, **kw: patched.update(kw))
    monkeypatch.setattr(mod.arr_client, "request", request)
    mod.notify_media_libraries_after_torrent(_tv_job(), "gid1")
    return patched["media_pipeline"]


def test_w2_unreachable_skips_scan(monkeypatch, tmp_path):
    mod = _worker_mod()
    calls: list[str] = []

    def request(t, method, path, body=None, **_k):
        calls.append(path)
        raise ArrUnreachable("reset")

    mp = _notify(monkeypatch, mod, tmp_path, request)
    assert mp == {"sonarr": "api_unreachable", "sonarr_scan": "api_unreachable", "jellyfin_refreshed": False}
    assert not any(p == "/api/v3/command" for p in calls)


def test_w3_scan_refused_is_failed_and_ok_is_requested(monkeypatch, tmp_path):
    mod = _worker_mod()

    def refused(t, method, path, body=None, **_k):
        if path == "/api/v3/command":
            raise ArrHTTPError(500)
        return []  # lookup finds nothing

    mp = _notify(monkeypatch, mod, tmp_path, refused)
    assert (mp["sonarr"], mp["sonarr_scan"]) == ("lookup_failed", "failed")

    def ok(t, method, path, body=None, **_k):
        return {} if path == "/api/v3/command" else []

    mp = _notify(monkeypatch, mod, tmp_path, ok)
    assert mp["sonarr_scan"] == "requested"


def test_h1_job_health_codes():
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    job = _tv_job()
    job.update(
        worker="aria2",
        aria2_gid="g1",
        started_at=(now - timedelta(minutes=10)).isoformat(),
        progress={"phase": "complete", "completed": "100", "total": "100", "seeders": "1", "connections": "1"},
    )
    job["media_pipeline"] = {"sonarr": "api_unreachable", "sonarr_scan": "api_unreachable"}
    review = evaluate_job_health(job, now=now)
    assert review and review["code"] == "sonarr_unreachable"
    assert any("arr_client.py --check" in step for step in review["playbook"])
    job["media_pipeline"] = {"sonarr": "add_failed", "sonarr_scan": "requested"}
    assert evaluate_job_health(job, now=now)["code"] == "sonarr_import_failed"


@pytest.mark.skipif(not shutil.which("curl"), reason="curl not installed")
def test_a7_docker_config_runs_in_real_curl(fake_arr, tmp_path, monkeypatch):
    """The curl -K config (escapes, write-out status line) works with real curl via a docker shim."""
    url, seen = fake_arr
    shim = tmp_path / "docker"
    shim.write_text('#!/bin/sh\nshift 3\nexec "$@"\n')  # drop "exec -i <name>", run curl here
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    t = target("sonarr", {"SONARR_URL": url, "SONARR_API_KEY": KEY, "SONARR_VIA_DOCKER": "sonarr"})
    assert arr_client.request(t, "GET", "/api/v3/system/status") == {"version": "4.0.0"}
    assert seen[-1]["headers"].get("X-Api-Key") == KEY
