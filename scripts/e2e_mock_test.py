"""
HTTP-level e2e mock test using TestClient (no browser).
Usage: python scripts/e2e_mock_test.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    os.environ["MOCK_MODE"] = "true"
    os.environ["PROJECTS_ROOT"] = str(ROOT / ".e2e_projects")

    from app.settings import get_settings

    get_settings.cache_clear()

    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.queue import task_queue

    task_queue._current = None
    app = create_app()
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200 and r.json()["mock_mode"] is True, r.text
        print("[1] health ok")

        r = client.post(
            "/api/projects",
            json={
                "theme": "e2e mock",
                "language": "zh",
                "genre": "pop",
                "duration_sec_target": 60,
                "aspect": "9:16",
                "subtitles": True,
            },
        )
        assert r.status_code == 200, r.text
        pid = r.json()["project_id"]
        print(f"[2] project {pid}")

        r = client.post(f"/api/projects/{pid}/actions/generate-lyrics")
        assert r.status_code == 200, r.text
        print("[3] lyrics")

        r = client.post(f"/api/projects/{pid}/actions/confirm-lyrics")
        assert r.status_code == 200, r.text
        print("[4] music")

        # force busy -> 409
        from app.queue import JobInfo

        task_queue._current = JobInfo(job_id="busy", project_id=pid, step="x", status="running")
        r = client.post(f"/api/projects/{pid}/actions/reroll-music")
        assert r.status_code == 409, r.text
        task_queue._current = None
        print("[5] mutex 409 ok")

        r = client.post(f"/api/projects/{pid}/actions/confirm-music")
        assert r.status_code == 200, r.text
        print("[6] mv")

        r = client.get(f"/api/projects/{pid}")
        body = r.json()
        assert body["status"] == "ready" and body["output_exists"], body
        r = client.get(f"/api/projects/{pid}/download/video")
        assert r.status_code == 200 and len(r.content) > 1000
        print(f"[7] download {len(r.content)} bytes")

    print("E2E MOCK PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
