from __future__ import annotations

from enum import Enum


class ProjectStatus(str, Enum):
    CREATED = "created"
    GENERATING_LYRICS = "generating_lyrics"
    AWAIT_LYRICS_REVIEW = "await_lyrics_review"
    GENERATING_MUSIC = "generating_music"
    AWAIT_MUSIC_REVIEW = "await_music_review"
    GENERATING_IMAGES = "generating_images"
    ASSEMBLING = "assembling"
    READY = "ready"
    FAILED = "failed"


# Allowed transitions: from -> set of to
TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
    ProjectStatus.CREATED: {ProjectStatus.GENERATING_LYRICS, ProjectStatus.FAILED},
    ProjectStatus.GENERATING_LYRICS: {
        ProjectStatus.AWAIT_LYRICS_REVIEW,
        ProjectStatus.FAILED,
    },
    ProjectStatus.AWAIT_LYRICS_REVIEW: {
        ProjectStatus.GENERATING_MUSIC,
        ProjectStatus.GENERATING_LYRICS,  # re-generate lyrics
        ProjectStatus.FAILED,
    },
    ProjectStatus.GENERATING_MUSIC: {
        ProjectStatus.AWAIT_MUSIC_REVIEW,
        ProjectStatus.FAILED,
    },
    ProjectStatus.AWAIT_MUSIC_REVIEW: {
        ProjectStatus.GENERATING_MUSIC,  # re-roll
        ProjectStatus.GENERATING_IMAGES,
        ProjectStatus.FAILED,
    },
    ProjectStatus.GENERATING_IMAGES: {
        ProjectStatus.ASSEMBLING,
        ProjectStatus.FAILED,
    },
    ProjectStatus.ASSEMBLING: {
        ProjectStatus.READY,
        ProjectStatus.FAILED,
    },
    ProjectStatus.READY: {
        ProjectStatus.GENERATING_MUSIC,  # re-roll from ready
        ProjectStatus.GENERATING_IMAGES,  # re-assemble images/MV
        ProjectStatus.ASSEMBLING,
        ProjectStatus.FAILED,
    },
    ProjectStatus.FAILED: {
        # retry current step: restore to the step that failed via retry endpoints
        ProjectStatus.GENERATING_LYRICS,
        ProjectStatus.GENERATING_MUSIC,
        ProjectStatus.GENERATING_IMAGES,
        ProjectStatus.ASSEMBLING,
        ProjectStatus.AWAIT_LYRICS_REVIEW,
        ProjectStatus.AWAIT_MUSIC_REVIEW,
        ProjectStatus.CREATED,
    },
}


class IllegalTransitionError(ValueError):
    pass


def assert_transition(current: ProjectStatus | str, new: ProjectStatus | str) -> None:
    cur = ProjectStatus(current)
    nxt = ProjectStatus(new)
    if cur == nxt:
        return
    allowed = TRANSITIONS.get(cur, set())
    if nxt not in allowed:
        raise IllegalTransitionError(f"非法状态迁移: {cur.value} → {nxt.value}")
