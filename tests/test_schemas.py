from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.creative import CreativeJSON
from app.services.deepseek import build_mock_creative
from app.schemas.creative import ProjectInput


def _valid_payload(**overrides):
    base = {
        "title": "Test Song",
        "language": "zh",
        "style": {
            "genre": "pop",
            "mood": "sad",
            "duration_sec_target": 120,
            "vocal": {"gender": "female", "timbre": "soft"},
            "bpm_range": [90, 110],
            "has_rap": False,
            "has_chorus": True,
        },
        "music_description": "A soft pop ballad",
        "performance_notes": "gentle",
        "visual_bible": {
            "setting": "city",
            "palette": "blue",
            "character": "singer",
            "camera_style": "wide",
            "must_include": ["neon"],
            "must_avoid": ["logo"],
        },
        "sections": [
            {
                "id": "s1",
                "label": "verse",
                "lyrics": "一行歌词",
                "visual_prompt": "night street",
                "negative_prompt": "",
                "shot_count": 1,
            }
        ],
    }
    base.update(overrides)
    return base


def test_schema_ok():
    c = CreativeJSON.model_validate(_valid_payload())
    assert c.title == "Test Song"
    assert len(c.sections) == 1


def test_schema_missing_sections():
    with pytest.raises(ValidationError):
        CreativeJSON.model_validate(_valid_payload(sections=[]))


def test_schema_illegal_label():
    payload = _valid_payload()
    payload["sections"][0]["label"] = "hook"
    with pytest.raises(ValidationError):
        CreativeJSON.model_validate(payload)


def test_schema_empty_lyrics():
    payload = _valid_payload()
    payload["sections"][0]["lyrics"] = "   "
    with pytest.raises(ValidationError):
        CreativeJSON.model_validate(payload)


def test_schema_missing_title():
    payload = _valid_payload()
    payload["title"] = ""
    with pytest.raises(ValidationError):
        CreativeJSON.model_validate(payload)


def test_mock_creative_builds():
    form = ProjectInput(theme="雨夜", genre="pop", language="zh")
    c = build_mock_creative(form)
    assert c.sections
    assert c.music_description
