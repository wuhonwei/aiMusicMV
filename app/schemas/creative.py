from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


SectionLabel = Literal["verse", "chorus", "bridge", "intro", "outro", "other"]


class VocalStyle(BaseModel):
    gender: str = ""
    timbre: str = ""


class StyleBlock(BaseModel):
    genre: str = ""
    mood: str = ""
    duration_sec_target: int = Field(default=180, ge=30, le=600)
    vocal: VocalStyle = Field(default_factory=VocalStyle)
    bpm_range: list[int] = Field(default_factory=lambda: [90, 110])
    has_rap: bool = False
    has_chorus: bool = True

    @field_validator("bpm_range")
    @classmethod
    def validate_bpm(cls, v: list[int]) -> list[int]:
        if len(v) != 2:
            raise ValueError("bpm_range 必须是长度为 2 的数组 [min, max]")
        if v[0] > v[1]:
            raise ValueError("bpm_range[0] 不能大于 bpm_range[1]")
        return v


class VisualBible(BaseModel):
    setting: str = ""
    palette: str = ""
    character: str = ""
    camera_style: str = ""
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)


class Section(BaseModel):
    id: str
    label: SectionLabel
    lyrics: str
    visual_prompt: str
    negative_prompt: str = ""
    shot_count: int = Field(default=1, ge=1, le=3)

    @field_validator("lyrics")
    @classmethod
    def lyrics_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("section.lyrics 不能为空")
        return v

    @field_validator("visual_prompt")
    @classmethod
    def visual_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("section.visual_prompt 不能为空")
        return v


class CreativeJSON(BaseModel):
    title: str
    language: str
    style: StyleBlock
    music_description: str
    performance_notes: str = ""
    visual_bible: VisualBible
    sections: list[Section]

    @field_validator("title", "language", "music_description")
    @classmethod
    def non_empty_str(cls, v: str) -> str:
        if not v or not str(v).strip():
            raise ValueError("必填字符串字段不能为空")
        return v

    @model_validator(mode="after")
    def sections_not_empty(self) -> CreativeJSON:
        if not self.sections:
            raise ValueError("sections 不能为空")
        ids = [s.id for s in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("section.id 必须唯一")
        return self


class ProjectInput(BaseModel):
    theme: str = Field(..., min_length=1)
    genre: str = ""
    language: str = "zh"
    mood: str = ""
    duration_sec_target: int = Field(default=180, ge=30, le=600)
    vocal_gender: str = ""
    vocal_timbre: str = ""
    bpm_min: int = 90
    bpm_max: int = 110
    has_rap: bool = False
    has_chorus: bool = True
    aspect: Literal["16:9", "9:16"] = "16:9"
    subtitles: bool = True
    style_notes: str = ""


class ProjectMeta(BaseModel):
    project_id: str
    status: str
    aspect: str = "16:9"
    subtitles: bool = True
    version: int = 1
    creative_version: int = 0
    audio_version: int = 0
    title: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_error: str = ""
    last_failed_step: str = ""
    mock_mode: bool = True
