from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.queue import task_queue
from app.settings import Settings, get_settings, reload_settings


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("PROJECTS_ROOT", str(tmp_path / "projects"))
    monkeypatch.setenv("APP_HOST", "127.0.0.1")
    get_settings.cache_clear()
    # reset queue state
    task_queue._current = None
    app = create_app()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["mock_mode"] is True


def test_api_mutex_409(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    # create project
    r = client.post(
        "/api/projects",
        json={"theme": "mutex", "language": "zh", "aspect": "16:9", "subtitles": True},
    )
    assert r.status_code == 200
    pid = r.json()["project_id"]

    # hold the queue
    release = asyncio.Event()

    async def blocker():
        await release.wait()

    async def hold():
        await task_queue.run(pid, "hold", blocker)

    loop = asyncio.new_event_loop()

    async def start_hold():
        task = asyncio.create_task(hold())
        await asyncio.sleep(0.05)
        return task

    # Use TestClient's app with a sync busy check by setting current manually
    from app.queue import JobInfo

    task_queue._current = JobInfo(job_id="x", project_id=pid, step="hold", status="running")
    r2 = client.post(f"/api/projects/{pid}/actions/generate-lyrics")
    assert r2.status_code == 409
    task_queue._current = None


def test_e2e_http_mock_flow(client: TestClient):
    r = client.post(
        "/api/projects",
        json={
            "theme": "HTTP冒烟",
            "genre": "pop",
            "language": "zh",
            "mood": "warm",
            "duration_sec_target": 60,
            "aspect": "16:9",
            "subtitles": True,
            "has_chorus": True,
        },
    )
    assert r.status_code == 200
    pid = r.json()["project_id"]

    r = client.post(f"/api/projects/{pid}/actions/generate-lyrics")
    assert r.status_code == 200, r.text

    r = client.get(f"/api/projects/{pid}/creative")
    assert r.status_code == 200
    creative = r.json()
    creative["title"] = "已编辑标题"
    r = client.put(f"/api/projects/{pid}/creative", json={"creative": creative})
    assert r.status_code == 200

    r = client.post(f"/api/projects/{pid}/actions/confirm-lyrics")
    assert r.status_code == 200, r.text

    r = client.get(f"/api/projects/{pid}")
    assert r.json()["status"] == "await_music_review"
    assert r.json()["audio_exists"] is True

    r = client.post(f"/api/projects/{pid}/actions/confirm-music")
    assert r.status_code == 200, r.text

    r = client.get(f"/api/projects/{pid}")
    assert r.json()["status"] == "ready"
    assert r.json()["output_exists"] is True

    r = client.get(f"/api/projects/{pid}/download/video")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("video/")
    assert len(r.content) > 1000
