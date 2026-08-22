"""
MOCK_MODE full-pipeline smoke test. Exit 0 on success.
Usage: python scripts/smoke_test.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    os.environ["MOCK_MODE"] = "true"
    # isolate smoke projects
    smoke_root = ROOT / ".smoke_projects"
    os.environ["PROJECTS_ROOT"] = str(smoke_root)

    from app.settings import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    settings.mock_mode = True

    from app.schemas.creative import ProjectInput
    from app.services.ffmpeg_mv import ffprobe_duration, ffprobe_video_size
    from app.services.pipeline import Pipeline
    from app.services.projects import ProjectStore
    from app.state_machine import ProjectStatus

    store = ProjectStore(settings)
    pipe = Pipeline(store=store, settings=settings)
    meta = store.create(
        ProjectInput(
            theme="smoke-test-雨夜",
            genre="synth-pop",
            language="zh",
            mood="nostalgic",
            duration_sec_target=60,
            aspect="16:9",
            subtitles=True,
        )
    )
    pid = meta.project_id
    print(f"[1] created {pid}")
    await pipe.generate_lyrics(pid)
    print("[2] lyrics ok")
    await pipe.generate_music(pid)
    audio = store.audio_path(pid)
    print(f"[3] music ok ({audio.name}, {ffprobe_duration(audio):.2f}s)")
    out = await pipe.generate_images_and_assemble(pid)
    assert store.read_meta(pid).status == ProjectStatus.READY.value
    assert out.exists()
    w, h = ffprobe_video_size(out)
    print(f"[4] mv ok {out} {w}x{h} size={out.stat().st_size}")
    if (w, h) != (1920, 1080):
        print("FAIL: unexpected resolution")
        return 1
    print("SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
