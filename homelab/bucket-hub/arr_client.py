"""Sonarr / Radarr API client for the host worker (OPS-ARR2).

Sonarr and Radarr share Gluetun's network namespace. From the host they are reached on
the ports Gluetun publishes (``SONARR_URL`` / ``RADARR_URL``, default ``127.0.0.1``).
When that path is broken (2026-10-12: ``Connection reset by peer``), set
``SONARR_VIA_DOCKER=sonarr`` / ``RADARR_VIA_DOCKER=radarr`` and the worker calls the API
from inside the container with ``docker exec <name> curl``. The API key goes to curl on
stdin, never in argv or logs.

Errors are split so the Hub can tell them apart:

- ``ArrUnreachable``: no answer (reset, refused, timeout, container or curl missing).
- ``ArrHTTPError``: the API answered with an HTTP error (bad key, bad payload).

``python3 arr_client.py --check`` prints one JSON line per service and exits 1 when a
configured service is unreachable: the worker doctor and the OPS-ARR2 smoke use it, so
they test the same path the worker uses after a torrent completes. Stdlib only.
"""
from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

DEFAULT_PORTS = {"sonarr": 8989, "radarr": 7878}

# curl exit codes that mean "nothing answered" (resolve, connect, timeout, empty reply, recv).
_CURL_UNREACHABLE = {6, 7, 28, 52, 55, 56}
# docker exec: 125 daemon/container error, 126 cannot run, 127 command not found.
_DOCKER_UNREACHABLE = {125, 126, 127}
_STATUS_MARK = "\n__ARR_HTTP_STATUS__"


class ArrError(Exception):
    """Base class; ``code`` is the short value stored in ``media_pipeline``."""

    code = "add_failed"


class ArrUnreachable(ArrError):
    code = "api_unreachable"


class ArrHTTPError(ArrError):
    code = "add_failed"

    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(f"HTTP {status}{': ' + message if message else ''}")
        self.status = status


@dataclass(frozen=True)
class ArrTarget:
    name: str
    url: str
    api_key: str
    via_docker: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def transport(self) -> str:
        return f"docker:{self.via_docker}" if self.via_docker else "http"

    @property
    def port(self) -> int:
        return urlparse(self.url).port or DEFAULT_PORTS.get(self.name, 80)


def target(name: str, env: dict[str, str] | None = None) -> ArrTarget:
    e = os.environ if env is None else env
    up = name.upper()
    return ArrTarget(
        name=name,
        url=(e.get(f"{up}_URL") or f"http://127.0.0.1:{DEFAULT_PORTS[name]}").rstrip("/"),
        api_key=e.get(f"{up}_API_KEY", ""),
        via_docker=(e.get(f"{up}_VIA_DOCKER") or "").strip(),
    )


def classify(exc: BaseException) -> str:
    """``media_pipeline`` code for an exception raised while talking to *arr."""
    if isinstance(exc, ArrError):
        return exc.code
    if _is_unreachable(exc):
        return ArrUnreachable.code
    return "add_failed"


def _is_unreachable(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        return isinstance(reason, (OSError, socket.timeout)) or "timed out" in str(reason)
    return isinstance(exc, (ConnectionError, TimeoutError, socket.timeout, http.client.RemoteDisconnected, OSError))


def _decode(raw: str) -> Any:
    raw = raw.strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"text": raw[:500]}


def _http(t: ArrTarget, method: str, path: str, body: Any, timeout: float) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    hdrs = {"Accept": "application/json", "X-Api-Key": t.api_key, "User-Agent": "bucket-hub-worker/2.0"}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{t.url}{path}", data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _decode(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raise ArrHTTPError(exc.code, str(exc.reason or "")) from None
    except Exception as exc:  # noqa: BLE001
        if _is_unreachable(exc):
            raise ArrUnreachable(f"{t.name} {t.transport}: {type(exc).__name__}: {exc}") from None
        raise


def _curl_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return '"' + escaped + '"'


def curl_config(t: ArrTarget, method: str, path: str, body: Any, timeout: float) -> str:
    """curl ``-K -`` config: the key and body travel on stdin, not in argv."""
    lines = [
        f"url = {_curl_quote(f'http://127.0.0.1:{t.port}{path}')}",
        f"request = {_curl_quote(method)}",
        f"header = {_curl_quote('X-Api-Key: ' + t.api_key)}",
        f"header = {_curl_quote('Accept: application/json')}",
        f"max-time = {int(max(1, timeout))}",
        "silent",
        "show-error",
        f"write-out = {_curl_quote(_STATUS_MARK + '%{http_code}')}",
    ]
    if body is not None:
        lines.append(f"header = {_curl_quote('Content-Type: application/json')}")
        lines.append(f"data-raw = {_curl_quote(json.dumps(body))}")
    return "\n".join(lines) + "\n"


def _docker(t: ArrTarget, method: str, path: str, body: Any, timeout: float) -> Any:
    cmd = ["docker", "exec", "-i", t.via_docker, "curl", "-K", "-"]
    try:
        proc = subprocess.run(
            cmd,
            input=curl_config(t, method, path, body, timeout),
            capture_output=True,
            text=True,
            timeout=timeout + 15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ArrUnreachable(f"{t.name} {t.transport}: {type(exc).__name__}") from None
    if proc.returncode in _DOCKER_UNREACHABLE or proc.returncode in _CURL_UNREACHABLE:
        detail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        raise ArrUnreachable(f"{t.name} {t.transport}: exit {proc.returncode} {detail[0][:200]}")
    out, mark, status = (proc.stdout or "").rpartition(_STATUS_MARK)
    if not mark or not status.strip().isdigit():
        raise ArrUnreachable(f"{t.name} {t.transport}: exit {proc.returncode}, no HTTP status")
    code = int(status.strip())
    if code == 0:
        raise ArrUnreachable(f"{t.name} {t.transport}: no HTTP response")
    if code >= 400:
        raise ArrHTTPError(code)
    return _decode(out)


def request(t: ArrTarget, method: str, path: str, body: Any = None, *, timeout: float = 30.0) -> Any:
    """Call the *arr API; raises ``ArrUnreachable`` or ``ArrHTTPError``."""
    if t.via_docker:
        return _docker(t, method, path, body, timeout)
    return _http(t, method, path, body, timeout)


def check(t: ArrTarget) -> dict[str, Any]:
    """One status probe the way the worker calls the API. Never includes the key."""
    row: dict[str, Any] = {"service": t.name, "transport": t.transport, "url": t.url}
    if not t.configured:
        row.update(ok=False, code="not_configured")
        return row
    started = time.monotonic()
    try:
        status = request(t, "GET", "/api/v3/system/status", timeout=10.0)
        row.update(ok=True, code="ok", version=(status or {}).get("version") if isinstance(status, dict) else None)
    except ArrHTTPError as exc:
        row.update(ok=False, code=f"http_{exc.status}", error=str(exc)[:200])
    except ArrError as exc:
        row.update(ok=False, code=exc.code, error=str(exc)[:200])
    row["ms"] = int((time.monotonic() - started) * 1000)
    return row


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args != ["--check"]:
        print("usage: arr_client.py --check", file=sys.stderr)
        return 2
    rows = [check(target(name)) for name in ("sonarr", "radarr")]
    for row in rows:
        print(json.dumps(row, sort_keys=True))
    return 0 if all(r["ok"] or r["code"] == "not_configured" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
