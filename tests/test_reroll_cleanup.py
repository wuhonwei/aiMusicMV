from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.creative import ProjectInput
from app.services.deepseek import build_mock_creative
from app.services.projects import ProjectStore
from app.settings import Settings
from app.state_machine import IllegalTransitionError, ProjectStatus, assert_transition


@pytest.fixture()
def store(tmp_path: Path) -> ProjectStore:
    s = Settings(projects_root=str(tmp_path), mock_mode=True)
    return ProjectStore(s)


def test_illegal_transition_rejected():
    with pytest.raises(IllegalTransitionError):
        assert_transition(ProjectStatus.CREATED, ProjectStatus.READY)


def test_legal_transition():
    assert_transition(ProjectStatus.CREATED, ProjectStatus.GENERATING_LYRICS)
    assert_transition(ProjectStatus.AWAIT_LYRICS_REVIEW, ProjectStatus.GENERATING_MUSIC)


def test_reroll_cleanup_keeps_creative(store: ProjectStore, tmp_path: Path):
    meta = store.create(
        ProjectInput(theme="test", aspect="16:9", subtitles=True, duration_sec_target=60)
    )
    pid = meta.project_id
    creative = build_mock_creative(store.read_input(pid))
    store.save_creative(pid, creative, bump=True)
    store.set_status(pid, ProjectStatus.GENERATING_LYRICS)
    store.set_status(pid, ProjectStatus.AWAIT_LYRICS_REVIEW)

    # fake downstream
    ver = store.bump_audio_version(pid)
    audio = store.project_dir(pid) / "audio" / f"v{ver}.wav"
    audio.write_bytes(b"RIFF....")
    img = store.project_dir(pid) / "images" / f"v{ver}_s1.png"
    img.write_bytes(b"PNG")
    (store.project_dir(pid) / f"timeline_v{ver}.json").write_text("{}", encoding="utf-8")
    out = store.project_dir(pid) / "output" / f"final_v{ver}.mp4"
    out.write_bytes(b"mp4")

    result = store.cleanup_downstream_for_reroll(pid)
    assert result["kept_creative"] is True
    assert store.creative_path(pid).exists()
    assert not audio.exists()
    assert not img.exists()
    assert not out.exists()
    assert not (store.project_dir(pid) / f"timeline_v{ver}.json").exists()
