from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

from app.schemas.creative import CreativeJSON, Section


@dataclass
class Shot:
    section_id: str
    label: str
    shot_index: int
    start: float
    end: float
    duration: float
    lyrics: str
    visual_prompt: str
    image_key: str  # e.g. v1_s1


def _weight(section: Section) -> float:
    """Prefer character count; fall back to line count."""
    text = section.lyrics.strip()
    chars = len(text.replace(" ", "").replace("\n", ""))
    if chars > 0:
        return float(chars)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return float(max(len(lines), 1))


def build_timeline(
    creative: CreativeJSON,
    audio_duration: float,
    *,
    min_shot_duration: float = 2.0,
    version: int = 1,
    shots_per_section_default: int = 1,
) -> dict[str, Any]:
    """
    Allocate section durations proportionally by lyric weight.
    Ensures sum(durations) == audio_duration (within float rounding on last shot).
    Enforces min_shot_duration when total length allows; otherwise scales down.
    """
    if audio_duration <= 0:
        raise ValueError("audio_duration 必须 > 0")

    sections = creative.sections
    if not sections:
        raise ValueError("sections 为空")

    # Expand shots per section
    units: list[tuple[Section, int]] = []
    for sec in sections:
        count = sec.shot_count or shots_per_section_default
        count = max(1, min(3, count))
        for i in range(count):
            units.append((sec, i))

    n = len(units)
    raw_weights = []
    for sec, shot_i in units:
        w = _weight(sec) / max(sec.shot_count or 1, 1)
        raw_weights.append(max(w, 1.0))

    total_w = sum(raw_weights)
    min_total = min_shot_duration * n

    if audio_duration >= min_total:
        # Assign floor first, distribute remainder by weight
        remainder = audio_duration - min_total
        durations = [
            min_shot_duration + remainder * (w / total_w) for w in raw_weights
        ]
    else:
        # Extreme short audio: proportional only
        durations = [audio_duration * (w / total_w) for w in raw_weights]

    # Fix rounding so sum == audio_duration exactly
    durations = [round(d, 4) for d in durations]
    drift = audio_duration - sum(durations)
    durations[-1] = round(durations[-1] + drift, 4)

    shots: list[Shot] = []
    t = 0.0
    for (sec, shot_i), dur in zip(units, durations):
        start = round(t, 4)
        end = round(t + dur, 4)
        shots.append(
            Shot(
                section_id=sec.id,
                label=sec.label,
                shot_index=shot_i,
                start=start,
                end=end,
                duration=round(end - start, 4),
                lyrics=sec.lyrics,
                visual_prompt=sec.visual_prompt,
                image_key=f"v{version}_{sec.id}" + (f"_{shot_i}" if (sec.shot_count or 1) > 1 else ""),
            )
        )
        t = end

    return {
        "audio_duration": audio_duration,
        "version": version,
        "min_shot_duration": min_shot_duration,
        "shots": [asdict(s) for s in shots],
        # reserved for whisperX alignment later
        "alignment": {"provider": None, "status": "not_implemented_v1"},
    }


def shots_from_timeline(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    return list(timeline.get("shots") or [])
