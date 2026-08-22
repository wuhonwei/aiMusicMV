from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


def _default_projects_root() -> Path:
    d_root = Path("D:/mv-studio/projects")
    if Path("D:/").exists():
        return d_root
    return Path.home() / "mv-studio" / "projects"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_sec: float = 120.0

    comfyui_base_url: str = "http://127.0.0.1:8188"
    comfyui_timeout_sec: float = 600.0

    app_host: str = "127.0.0.1"
    app_port: int = 8787
    mock_mode: bool = True
    default_aspect: str = "16:9"
    subtitles_default: bool = True

    projects_root: str = ""
    local_token: str = ""

    music_workflow_path: str = "app/workflows/minimax_music3_api.json"
    image_workflow_path: str = "app/workflows/txt2img_api.json"

    image_checkpoint: str = "sd_xl_base_1.0.safetensors"
    image_seed: int = 42
    image_steps: int = 20
    image_cfg: float = 7.0
    image_width_16_9: int = 1920
    image_height_16_9: int = 1080
    image_width_9_16: int = 1080
    image_height_9_16: int = 1920
    image_negative_suffix: str = "blurry, low quality, watermark, text, logo, deformed"

    min_shot_duration_sec: float = 2.0
    shots_per_section_default: int = 1
    subtitle_font: str = "Microsoft YaHei"
    subtitle_font_size: int = 42
    subtitle_margin_v: int = 48

    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    music_prompt_node_id: str = "3"
    music_prompt_input: str = "text"
    txt2img_prompt_node_id: str = "6"
    txt2img_negative_node_id: str = "7"
    txt2img_checkpoint_node_id: str = "4"
    txt2img_seed_node_id: str = "3"
    txt2img_size_node_id: str = "5"

    def resolved_projects_root(self) -> Path:
        if self.projects_root.strip():
            return Path(self.projects_root).expanduser().resolve()
        return _default_projects_root().resolve()

    def workflow_path(self, relative: str) -> Path:
        p = Path(relative)
        if not p.is_absolute():
            p = REPO_ROOT / p
        return p.resolve()

    def image_size(self, aspect: str) -> tuple[int, int]:
        if aspect == "9:16":
            return self.image_width_9_16, self.image_height_9_16
        return self.image_width_16_9, self.image_height_16_9


def _load_yaml_overrides() -> dict[str, Any]:
    cfg_path = REPO_ROOT / "config.yaml"
    if not cfg_path.exists():
        return {}
    with cfg_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    flat: dict[str, Any] = {}
    if "mock_mode" in data:
        flat["mock_mode"] = data["mock_mode"]
    if "default_aspect" in data:
        flat["default_aspect"] = data["default_aspect"]
    if "subtitles_default" in data:
        flat["subtitles_default"] = data["subtitles_default"]
    if "comfyui_base_url" in data:
        flat["comfyui_base_url"] = data["comfyui_base_url"]
    if "projects_root" in data and data["projects_root"]:
        flat["projects_root"] = data["projects_root"]
    if "local_token" in data:
        flat["local_token"] = data["local_token"] or ""
    image = data.get("image") or {}
    if "checkpoint" in image:
        flat["image_checkpoint"] = image["checkpoint"]
    if "seed" in image:
        flat["image_seed"] = image["seed"]
    if "steps" in image:
        flat["image_steps"] = image["steps"]
    if "cfg" in image:
        flat["image_cfg"] = image["cfg"]
    if "negative_suffix" in image:
        flat["image_negative_suffix"] = image["negative_suffix"]
    music = data.get("music") or {}
    if "prompt_node_id" in music:
        flat["music_prompt_node_id"] = str(music["prompt_node_id"])
    if "prompt_input" in music:
        flat["music_prompt_input"] = music["prompt_input"]
    txt2img = data.get("txt2img") or {}
    if "prompt_node_id" in txt2img:
        flat["txt2img_prompt_node_id"] = str(txt2img["prompt_node_id"])
    if "negative_node_id" in txt2img:
        flat["txt2img_negative_node_id"] = str(txt2img["negative_node_id"])
    if "checkpoint_node_id" in txt2img:
        flat["txt2img_checkpoint_node_id"] = str(txt2img["checkpoint_node_id"])
    if "seed_node_id" in txt2img:
        flat["txt2img_seed_node_id"] = str(txt2img["seed_node_id"])
    if "size_node_id" in txt2img:
        flat["txt2img_size_node_id"] = str(txt2img["size_node_id"])
    timeline = data.get("timeline") or {}
    if "min_shot_duration_sec" in timeline:
        flat["min_shot_duration_sec"] = float(timeline["min_shot_duration_sec"])
    if "shots_per_section_default" in timeline:
        flat["shots_per_section_default"] = int(timeline["shots_per_section_default"])
    subtitle = data.get("subtitle") or {}
    if "font" in subtitle:
        flat["subtitle_font"] = subtitle["font"]
    if "font_size" in subtitle:
        flat["subtitle_font_size"] = int(subtitle["font_size"])
    if "margin_v" in subtitle:
        flat["subtitle_margin_v"] = int(subtitle["margin_v"])
    ffmpeg = data.get("ffmpeg") or {}
    if "path" in ffmpeg:
        flat["ffmpeg_path"] = ffmpeg["path"]
    if "ffprobe_path" in ffmpeg:
        flat["ffprobe_path"] = ffmpeg["ffprobe_path"]
    return flat


@lru_cache
def get_settings() -> Settings:
    overrides = _load_yaml_overrides()
    # Env wins over yaml: BaseSettings already loads env; we only fill gaps from yaml
    env_keys = {k.lower() for k in os.environ}
    filtered = {k: v for k, v in overrides.items() if k.upper() not in env_keys and k not in env_keys}
    return Settings(**filtered)


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
