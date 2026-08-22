from __future__ import annotations

from app.schemas.creative import CreativeJSON
from app.services.timeline import build_timeline


def _creative(n_sections: int = 3) -> CreativeJSON:
    sections = []
    lyrics_lens = ["短", "这是一段比较长的主歌歌词内容啊啊啊", "副歌副歌副歌副歌"]
    labels = ["verse", "chorus", "outro", "bridge", "intro"]
    for i in range(n_sections):
        sections.append(
            {
                "id": f"s{i+1}",
                "label": labels[i % len(labels)],
                "lyrics": lyrics_lens[i % len(lyrics_lens)],
                "visual_prompt": f"prompt {i}",
                "negative_prompt": "",
                "shot_count": 1,
            }
        )
    return CreativeJSON.model_validate(
        {
            "title": "t",
            "language": "zh",
            "style": {
                "genre": "pop",
                "mood": "m",
                "duration_sec_target": 60,
                "vocal": {"gender": "f", "timbre": "t"},
                "bpm_range": [90, 100],
                "has_rap": False,
                "has_chorus": True,
            },
            "music_description": "desc",
            "performance_notes": "",
            "visual_bible": {
                "setting": "s",
                "palette": "p",
                "character": "c",
                "camera_style": "cam",
                "must_include": [],
                "must_avoid": [],
            },
            "sections": sections,
        }
    )


def test_timeline_sum_equals_duration():
    tl = build_timeline(_creative(3), 30.0, min_shot_duration=2.0, version=1)
    total = sum(s["duration"] for s in tl["shots"])
    assert abs(total - 30.0) < 1e-6
    assert tl["shots"][0]["start"] == 0.0
    assert abs(tl["shots"][-1]["end"] - 30.0) < 1e-6


def test_timeline_min_duration():
    tl = build_timeline(_creative(3), 30.0, min_shot_duration=2.0)
    for s in tl["shots"]:
        assert s["duration"] >= 2.0 - 1e-6


def test_timeline_extreme_short_audio():
    # 3 shots, min 2s would need 6s; audio is 3s → cannot enforce min
    tl = build_timeline(_creative(3), 3.0, min_shot_duration=2.0)
    total = sum(s["duration"] for s in tl["shots"])
    assert abs(total - 3.0) < 1e-6
    assert len(tl["shots"]) == 3


def test_timeline_alignment_placeholder():
    tl = build_timeline(_creative(2), 10.0)
    assert tl["alignment"]["status"] == "not_implemented_v1"
