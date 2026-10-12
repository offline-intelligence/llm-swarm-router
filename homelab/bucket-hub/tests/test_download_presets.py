"""AP-UX-1 download presets and segments (P1–P10, P13)."""
from __future__ import annotations

import copy
import json

import pytest

import download_presets as dp

LIB = {
    "drives": {
        "ext_movies": {
            "label": "Expansion HDD",
            "root": "/mnt/external/movies",
            "mounted": True,
            "folders": [
                {"id": "torrents", "name": "torrents", "rel": "torrents", "present": True},
                {"id": "movies", "name": "movies", "rel": "movies", "present": True},
                {"id": "nas_staging", "name": "_nas_staging", "rel": "_nas_staging", "present": True},
            ],
        },
        "nas": {
            "label": "TNAS",
            "root": "/mnt/tnas",
            "mounted": True,
            "folders": [
                {"id": "inbox", "name": "inbox", "rel": "inbox", "present": True},
                {"id": "media_archive", "name": "Media Archive", "rel": "media-archive", "present": True},
                {"id": "website_backups", "name": "Website Backups", "rel": "website-backups", "present": True},
                {"id": "ai_language", "name": "AI Language", "rel": "ai/language", "present": True},
            ],
        },
        "media_hdd": {
            "label": "Media HDD",
            "root": "/mnt/media",
            "mounted": True,
            "folders": [
                {"id": "inbox", "name": "inbox", "rel": "inbox", "present": True},
                {"id": "videos", "name": "videos", "rel": "videos", "present": True},
            ],
        },
    }
}

MAGNET = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Show.S01"


def _lib(**changes):
    lib = copy.deepcopy(LIB)
    for path, value in changes.items():
        drive, _, key = path.partition("__")
        lib["drives"][drive][key] = value
    return lib


@pytest.fixture()
def presets_client(hub_client, monkeypatch):
    client, jobs_dir, app_mod = hub_client
    (jobs_dir / "library.json").write_text(json.dumps(LIB), encoding="utf-8")
    # /mnt/media is not a mount in tests; the aria2 rule itself is covered elsewhere.
    monkeypatch.setattr(app_mod, "validate_aria2_destination", lambda dest: None)
    return client, jobs_dir, app_mod


def _job(jobs_dir, job_id):
    return json.loads((jobs_dir / "jobs" / f"{job_id}.json").read_text(encoding="utf-8"))


# P1
@pytest.mark.parametrize(
    "preset,drive_id,folder_id,path",
    [
        ("tv", "ext_movies", "torrents", "/mnt/external/movies/torrents"),
        ("film", "ext_movies", "torrents", "/mnt/external/movies/torrents"),
        ("video", "nas", "media_archive", "/mnt/tnas/media-archive"),
        ("file", "nas", "inbox", "/mnt/tnas/inbox"),
        ("hf_files", "nas", "ai_language", "/mnt/tnas/ai/language"),
        ("website", "nas", "website_backups", "/mnt/tnas/website-backups"),
    ],
)
def test_p1_each_preset_resolves(preset, drive_id, folder_id, path):
    r = dp.resolve(LIB, preset)
    assert r["available"] is True
    assert r["destination"]["drive_id"] == drive_id
    assert r["destination"]["folder_id"] == folder_id
    assert r["destination"]["path"] == path
    assert r["saves_to"].startswith(r["destination"]["label"])
    assert r["fallback_used"] is False


def test_p1_every_preset_has_a_known_segment():
    assert {p["segment"] for p in dp.PRESETS} == dp.SEGMENT_IDS
    assert [s["id"] for s in dp.SEGMENTS] == ["tv", "repo", "website", "other"]


# P2
def test_p2_expansion_unmounted(presets_client):
    client, jobs_dir, _ = presets_client
    lib = _lib(ext_movies__mounted=False)
    for pid in ("tv", "film"):
        r = dp.resolve(lib, pid)
        assert r["available"] is False
        assert "not mounted" in r["reason"]
    (jobs_dir / "library.json").write_text(json.dumps(lib), encoding="utf-8")
    resp = client.post("/api/jobs", json={"url": MAGNET, "preset": "tv"})
    assert resp.status_code == 503
    assert "not mounted" in resp.text
    assert not list((jobs_dir / "jobs").glob("*.json"))


# P3
def test_p3_website_falls_back_to_staging():
    lib = copy.deepcopy(LIB)
    lib["drives"]["nas"]["folders"] = [
        f for f in lib["drives"]["nas"]["folders"] if f["id"] != "website_backups"
    ]
    r = dp.resolve(lib, "website")
    assert r["available"] is True
    assert r["destination"]["drive_id"] == "ext_movies"
    assert r["destination"]["folder_id"] == "nas_staging"
    assert r["fallback_used"] is True


def test_p3_tnas_asleep_video_falls_back_to_media_hdd():
    r = dp.resolve(_lib(nas__mounted=False), "video")
    assert r["destination"]["drive_id"] == "media_hdd"
    assert r["destination"]["folder_id"] == "videos"
    assert "TNAS is not mounted" in r["reason"]


# P4
def test_p4_manual_path(presets_client):
    client, jobs_dir, _ = presets_client
    resp = client.post(
        "/api/jobs",
        json={
            "url": MAGNET,
            "preset": "tv",
            "manual_path": True,
            "drive_id": "ext_movies",
            "folder_id": "movies",
        },
    )
    assert resp.status_code == 200, resp.text
    job = _job(jobs_dir, resp.json()["job"]["id"])
    assert job["destination_source"] == "manual"
    assert job["folder_id"] == "movies"
    assert job["segment"] == "tv"


# P5
def test_p5_preset_ignores_stray_drive(presets_client):
    client, jobs_dir, _ = presets_client
    resp = client.post(
        "/api/jobs",
        json={"url": MAGNET, "preset": "tv", "drive_id": "media_hdd", "folder_id": "inbox"},
    )
    assert resp.status_code == 200, resp.text
    job = _job(jobs_dir, resp.json()["job"]["id"])
    assert job["destination_source"] == "preset"
    assert job["drive_id"] == "ext_movies"
    assert job["destination_path"] == "/mnt/external/movies/torrents"


# P6
def test_p6_old_client_drive_and_folder(presets_client):
    client, jobs_dir, _ = presets_client
    resp = client.post(
        "/api/jobs", json={"url": MAGNET, "drive_id": "media_hdd", "folder_id": "inbox"}
    )
    assert resp.status_code == 200, resp.text
    job = _job(jobs_dir, resp.json()["job"]["id"])
    assert job["destination_source"] == "legacy"
    assert job["destination_path"] == "/mnt/media/inbox"
    assert "preset" not in job


# P7
def test_p7_bare_magnet_uses_tv_inbox(presets_client):
    client, jobs_dir, _ = presets_client
    resp = client.post("/api/jobs", json={"url": MAGNET})
    assert resp.status_code == 200, resp.text
    job = _job(jobs_dir, resp.json()["job"]["id"])
    assert job["preset"] == "tv"
    assert job["destination_path"] == "/mnt/external/movies/torrents"


def test_p7_movies_category_picks_film(presets_client):
    client, jobs_dir, _ = presets_client
    resp = client.post("/api/jobs", json={"url": MAGNET, "torrent_meta": {"category": "movies"}})
    job = _job(jobs_dir, resp.json()["job"]["id"])
    assert job["preset"] == "film"


def test_p7_capture_magnet_matches_form(presets_client, monkeypatch):
    client, jobs_dir, app_mod = presets_client
    monkeypatch.setattr(app_mod, "_capture_token_valid", lambda token: True)
    resp = client.post("/api/capture", json={"url": MAGNET}, headers={"X-Capture-Token": "t"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["job"]["preset"] == "tv"
    job = _job(jobs_dir, resp.json()["job"]["id"])
    assert job["destination_path"] == "/mnt/external/movies/torrents"
    assert job["requested_by"] == "firefox-capture"
    assert job["options"]["captured_via"] == "firefox"


def test_capture_github_goes_to_repo_archive(presets_client, monkeypatch):
    client, jobs_dir, app_mod = presets_client
    monkeypatch.setattr(app_mod, "_capture_token_valid", lambda token: True)
    resp = client.post(
        "/api/capture",
        json={"url": "https://github.com/octocat/Hello-World", "kind": "github"},
        headers={"X-Capture-Token": "t"},
    )
    assert resp.status_code == 200, resp.text
    job = _job(jobs_dir, resp.json()["job"]["id"])
    assert job["kind"] == "github_repo"
    assert job["segment"] == "repo"
    assert "destination_path" not in job


def test_capture_website_keeps_single_page(presets_client, monkeypatch):
    client, jobs_dir, app_mod = presets_client
    monkeypatch.setattr(app_mod, "_capture_token_valid", lambda token: True)
    resp = client.post(
        "/api/capture",
        json={"url": "https://example.com/page", "kind": "website"},
        headers={"X-Capture-Token": "t"},
    )
    job = _job(jobs_dir, resp.json()["job"]["id"])
    assert job["kind"] == "http"
    assert job["preset"] == "file"
    assert "website" in job["tags"]


# P8
def test_p8_capture_folders_override(tmp_path):
    f = tmp_path / "capture-folders.json"
    f.write_text(
        json.dumps({"type_folder_map": {"media": {"drive_id": "media_hdd", "folder_id": "videos"}}}),
        encoding="utf-8",
    )
    ov = dp.load_overrides(f)
    assert ov == {"video": {"drive_id": "media_hdd", "folder_id": "videos"}}
    r = dp.resolve(LIB, "video", overrides=ov)
    assert r["destination"]["drive_id"] == "media_hdd"
    assert r["fallback_used"] is False


def test_p8_override_ignored_for_archive_root(tmp_path):
    f = tmp_path / "capture-folders.json"
    f.write_text(
        json.dumps({"preset_folder_map": {"github_repo": {"drive_id": "nas", "folder_id": "inbox"}}}),
        encoding="utf-8",
    )
    assert dp.load_overrides(f) == {}


# P9
@pytest.mark.parametrize(
    "url,preset",
    [
        ("https://github.com/octocat/Hello-World", "github_repo"),
        ("https://huggingface.co/hf-internal-testing/tiny-random-gpt2", "hf_repo"),
        (MAGNET, "tv"),
        ("https://www.youtube.com/watch?v=abc", "video"),
        ("https://example.com/file.iso", "file"),
    ],
)
def test_p9_resolve_endpoint(presets_client, url, preset):
    client, jobs_dir, _ = presets_client
    resp = client.post("/api/presets/resolve", json={"url": url})
    assert resp.status_code == 200, resp.text
    assert resp.json()["preset"] == preset
    assert not list((jobs_dir / "jobs").glob("*.json"))


def test_p9_list_endpoint(presets_client):
    client, _, _ = presets_client
    data = client.get("/api/presets").json()
    assert [s["id"] for s in data["segments"]] == ["tv", "repo", "website", "other"]
    ids = [p["id"] for p in data["presets"]]
    assert set(ids) == set(dp.PRESETS_BY_ID)
    assert all(p["available"] for p in data["presets"])


# P10
def test_p10_archive_root_presets(presets_client):
    client, jobs_dir, app_mod = presets_client
    r = dp.resolve(LIB, "hf_repo", archive_root="/mnt/tnas/repo-archive")
    assert r["destination"] == {"archive_root": "/mnt/tnas/repo-archive", "subdir": "huggingface-daily"}
    (jobs_dir / "library.json").write_text('{"drives": {}}', encoding="utf-8")
    resp = client.post(
        "/api/jobs",
        json={"url": "https://huggingface.co/hf-internal-testing/tiny-random-gpt2", "preset": "hf_repo"},
    )
    assert resp.status_code == 200, resp.text
    job = _job(jobs_dir, resp.json()["job"]["id"])
    assert job["kind"] == "huggingface_repo"
    assert job["segment"] == "repo"
    assert "drive_id" not in job


def test_preset_rejects_wrong_link(presets_client):
    client, _, _ = presets_client
    resp = client.post(
        "/api/jobs", json={"url": "https://www.youtube.com/watch?v=abc", "preset": "tv"}
    )
    assert resp.status_code == 400
    assert "does not look like" in resp.text


# P13
def test_p13_segment_stored_and_filtered(presets_client):
    client, jobs_dir, _ = presets_client
    client.post("/api/jobs", json={"url": MAGNET})
    client.post("/api/jobs", json={"url": "https://github.com/octocat/Hello-World"})
    client.post("/api/jobs", json={"url": "https://example.com/a.zip"})
    tv = client.get("/api/jobs?segment=tv").json()["jobs"]
    repo = client.get("/api/jobs?segment=repo").json()["jobs"]
    other = client.get("/api/jobs?segment=other").json()["jobs"]
    assert [j["preset"] for j in tv] == ["tv"]
    assert [j["preset"] for j in repo] == ["github_repo"]
    assert [j["preset"] for j in other] == ["file"]


def test_p13_old_jobs_get_a_segment(presets_client):
    client, jobs_dir, _ = presets_client
    old = {
        "id": "old1",
        "kind": "http",
        "status": "done",
        "destination_path": "/mnt/external/movies/torrents",
        "created_at": "2026-10-01T00:00:00+00:00",
    }
    (jobs_dir / "jobs" / "old1.json").write_text(json.dumps(old), encoding="utf-8")
    jobs = client.get("/api/jobs?segment=tv").json()["jobs"]
    assert [j["id"] for j in jobs] == ["old1"]


# Requests (Lilly) approve + link mode
def test_request_link_without_drive_uses_preset(presets_client):
    client, jobs_dir, _ = presets_client
    resp = client.post("/api/requests", json={"mode": "link", "url": MAGNET, "requested_by": "lilly"})
    assert resp.status_code == 200, resp.text
    job = _job(jobs_dir, resp.json()["job_id"])
    assert job["preset"] == "tv"
    assert job["requested_by"] == "lilly"
    assert job["options"]["captured_via"] == "phone"


def test_approve_note_moves_to_preset(presets_client):
    client, jobs_dir, _ = presets_client
    resp = client.post("/api/requests", json={"mode": "note", "text": "The Office S02"})
    jid = resp.json()["job_id"]
    assert _job(jobs_dir, jid)["destination_path"].startswith("/mnt/tnas/inbox")
    resp = client.post(f"/api/jobs/{jid}/approve", json={"url": MAGNET})
    assert resp.status_code == 200, resp.text
    job = _job(jobs_dir, jid)
    assert job["status"] == "queued"
    assert job["preset"] == "tv"
    assert job["destination_path"] == "/mnt/external/movies/torrents"
    assert job["worker"] == "aria2"


def test_approve_github_link_goes_to_repo_lane(presets_client):
    client, jobs_dir, _ = presets_client
    jid = client.post("/api/requests", json={"mode": "note", "text": "hello"}).json()["job_id"]
    client.post(f"/api/jobs/{jid}/approve", json={"url": "https://github.com/octocat/Hello-World"})
    job = _job(jobs_dir, jid)
    assert job["kind"] == "github_repo"
    assert job["worker"] == "repo"
    assert "destination_path" not in job
