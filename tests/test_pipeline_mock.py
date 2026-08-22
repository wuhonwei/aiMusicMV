from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.queue import BusyError, SingleTaskQueue
from app.schemas.creative import ProjectInput
from app.services.ffmpeg_mv import ffprobe_duration, ffprobe_video_size
from app.services.pipeline import Pipeline
from app.services.projects import ProjectStore
from app.settings import Settings
from app.state_machine import ProjectStatus


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        projects_root=str(tmp_path / "projects"),
        mock_mode=True,
        min_shot_duration_sec=1.0,
        subtitle_font="Microsoft YaHei",
    )


@pytest.mark.asyncio
async def test_mock_pipeline_end_to_end(settings: Settings):
    store = ProjectStore(settings)
    pipe = Pipeline(store=store, settings=settings)
    meta = store.create(
        ProjectInput(
            theme="霓虹雨夜",
            genre="synth-pop",
            language="zh",
            mood="nostalgic",
            duration_sec_target=60,
            aspect="16:9",
            subtitles=True,
        )
    )
    pid = meta.project_id

    await pipe.generate_lyrics(pid)
    assert store.read_meta(pid).status == ProjectStatus.AWAIT_LYRICS_REVIEW.value

    await pipe.generate_music(pid, reroll=False)
    assert store.read_meta(pid).status == ProjectStatus.AWAIT_MUSIC_REVIEW.value
    audio = store.audio_path(pid)
    assert audio.exists()
    dur = ffprobe_duration(audio, settings.ffprobe_path)
    assert dur > 1.0

    out = await pipe.generate_images_and_assemble(pid)
    assert store.read_meta(pid).status == ProjectStatus.READY.value
    assert out.exists()
    assert out.stat().st_size > 1000
    w, h = ffprobe_video_size(out, settings.ffprobe_path)
    assert (w, h) == (1920, 1080)


@pytest.mark.asyncio
async def test_mock_pipeline_9_16(settings: Settings):
    store = ProjectStore(settings)
    pipe = Pipeline(store=store, settings=settings)
    meta = store.create(
        ProjectInput(theme="竖屏", language="zh", aspect="9:16", subtitles=False, duration_sec_target=45)
    )
    pid = meta.project_id
    await pipe.generate_lyrics(pid)
    await pipe.generate_music(pid)
    out = await pipe.generate_images_and_assemble(pid)
    w, h = ffprobe_video_size(out, settings.ffprobe_path)
    assert (w, h) == (1080, 1920)


@pytest.mark.asyncio
async def test_queue_mutual_exclusion():
    q = SingleTaskQueue()

    async def slow():
        await asyncio.sleep(0.3)

    async def starter():
        return await q.run("p1", "step", slow)

    t1 = asyncio.create_task(starter())
    await asyncio.sleep(0.05)
    with pytest.raises(BusyError):
        await q.run("p2", "other", slow)
    await t1
