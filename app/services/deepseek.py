from __future__ import annotations

import json
import re
from typing import Any, Optional

import httpx
from pydantic import ValidationError

from app.schemas.creative import CreativeJSON, ProjectInput
from app.settings import Settings, get_settings

CREATIVE_JSON_SCHEMA_HINT = """
返回严格 JSON（不要 markdown 代码块，不要解释），结构如下：
{
  "title": "string",
  "language": "zh|en|...",
  "style": {
    "genre": "",
    "mood": "",
    "duration_sec_target": 180,
    "vocal": { "gender": "", "timbre": "" },
    "bpm_range": [90, 110],
    "has_rap": false,
    "has_chorus": true
  },
  "music_description": "喂给 Music3 的自然语言 caption，英文优先，含曲风/情绪/乐器/人声",
  "performance_notes": "演唱细节、情绪、咬字、动态等",
  "visual_bible": {
    "setting": "",
    "palette": "",
    "character": "",
    "camera_style": "",
    "must_include": [],
    "must_avoid": []
  },
  "sections": [
    {
      "id": "s1",
      "label": "verse|chorus|bridge|intro|outro|other",
      "lyrics": "多行歌词",
      "visual_prompt": "继承 visual_bible 的出图提示（英文或中文）",
      "negative_prompt": "",
      "shot_count": 1
    }
  ]
}
要求：
1) sections 至少 3 段，包含至少 1 个 chorus（若 has_chorus=true）
2) 每段 visual_prompt 必须体现 visual_bible 的 setting/palette/character/camera_style
3) music_description 完整可读，适合音乐生成模型
4) 歌词语种与 language 一致
"""


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        return json.loads(m.group(0))


def build_mock_creative(form: ProjectInput) -> CreativeJSON:
    lang = form.language or "zh"
    title = f"{form.theme[:20]}之歌" if lang.startswith("zh") else f"Song of {form.theme[:30]}"
    if lang.startswith("zh"):
        sections = [
            {
                "id": "s1",
                "label": "intro",
                "lyrics": f"夜色轻轻落下\n{form.theme}在心里发芽",
                "visual_prompt": f"cinematic night city intro, mood {form.mood or 'dreamy'}, theme {form.theme}",
                "negative_prompt": "blurry, watermark",
                "shot_count": 1,
            },
            {
                "id": "s2",
                "label": "verse",
                "lyrics": "走过无人的街道\n霓虹把影子拉长\n心跳跟着节拍\n诉说未完的话",
                "visual_prompt": f"lonely neon street, walking figure, theme {form.theme}, {form.mood or 'melancholy'}",
                "negative_prompt": "blurry, watermark",
                "shot_count": 1,
            },
            {
                "id": "s3",
                "label": "chorus",
                "lyrics": f"唱出{form.theme}\n在光里盛开\n不怕风吹雨打\n我们都会抵达",
                "visual_prompt": f"wide emotional chorus shot, glowing lights, theme {form.theme}",
                "negative_prompt": "blurry, watermark",
                "shot_count": 1,
            },
            {
                "id": "s4",
                "label": "outro",
                "lyrics": "灯火渐渐远去\n旋律留在心底",
                "visual_prompt": f"soft fading city lights outro, theme {form.theme}",
                "negative_prompt": "blurry, watermark",
                "shot_count": 1,
            },
        ]
    else:
        sections = [
            {
                "id": "s1",
                "label": "intro",
                "lyrics": f"Soft lights fall\n{form.theme} calls",
                "visual_prompt": f"cinematic intro about {form.theme}, mood {form.mood or 'dreamy'}",
                "negative_prompt": "blurry, watermark",
                "shot_count": 1,
            },
            {
                "id": "s2",
                "label": "verse",
                "lyrics": "Empty streets and neon glow\nEchoes of a story we know",
                "visual_prompt": f"neon street verse scene, theme {form.theme}",
                "negative_prompt": "blurry, watermark",
                "shot_count": 1,
            },
            {
                "id": "s3",
                "label": "chorus",
                "lyrics": f"Sing {form.theme}\nRise and shine\nThrough the storm\nWe'll be fine",
                "visual_prompt": f"emotional chorus wide shot, theme {form.theme}",
                "negative_prompt": "blurry, watermark",
                "shot_count": 1,
            },
        ]

    data = {
        "title": title,
        "language": lang,
        "style": {
            "genre": form.genre or "pop",
            "mood": form.mood or "emotional",
            "duration_sec_target": form.duration_sec_target,
            "vocal": {"gender": form.vocal_gender or "female", "timbre": form.vocal_timbre or "warm"},
            "bpm_range": [form.bpm_min, form.bpm_max],
            "has_rap": form.has_rap,
            "has_chorus": form.has_chorus,
        },
        "music_description": (
            f"A {form.duration_sec_target}s {form.genre or 'pop'} song in {lang}, "
            f"mood {form.mood or 'emotional'}, BPM {form.bpm_min}-{form.bpm_max}, "
            f"{form.vocal_gender or 'female'} vocals, timbre {form.vocal_timbre or 'warm'}. "
            f"Theme: {form.theme}. "
            f"{'Include rap section. ' if form.has_rap else ''}"
            f"{'Strong chorus hook. ' if form.has_chorus else ''}"
            f"{form.style_notes}"
        ).strip(),
        "performance_notes": "Clear diction, emotional dynamics, soft verse and powerful chorus.",
        "visual_bible": {
            "setting": "neo-noir city at night with reflective wet streets",
            "palette": "cyan, magenta, deep navy",
            "character": "a solitary young singer silhouette",
            "camera_style": "cinematic anamorphic, slow push-in",
            "must_include": ["consistent character silhouette", "neon reflections"],
            "must_avoid": ["logos", "readable modern text", "gore"],
        },
        "sections": sections,
    }
    return CreativeJSON.model_validate(data)


class DeepSeekClient:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    def _system_prompt(self) -> str:
        return (
            "你是专业的词曲与 MV 分镜策划。只输出符合 schema 的 JSON。"
            + CREATIVE_JSON_SCHEMA_HINT
        )

    def _user_prompt(self, form: ProjectInput) -> str:
        return (
            f"主题：{form.theme}\n"
            f"曲风：{form.genre}\n语种：{form.language}\n情绪：{form.mood}\n"
            f"目标时长秒：{form.duration_sec_target}\n"
            f"人声：{form.vocal_gender} / {form.vocal_timbre}\n"
            f"BPM：{form.bpm_min}-{form.bpm_max}\n"
            f"说唱：{form.has_rap} 合唱感副歌：{form.has_chorus}\n"
            f"补充：{form.style_notes}\n"
            f"画幅仅供参考（视频侧）：{form.aspect}\n"
            "请生成完整 creative JSON。"
        )

    async def generate_creative(self, form: ProjectInput) -> tuple[CreativeJSON, dict[str, Any]]:
        """Returns (validated creative, raw log dict). Retries once on validation failure."""
        if self.settings.mock_mode or not self.settings.deepseek_api_key:
            creative = build_mock_creative(form)
            raw = {"mode": "mock", "creative": creative.model_dump()}
            return creative, raw

        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self._user_prompt(form)},
        ]
        request_payload = {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        }
        last_raw: dict[str, Any] = {"request": request_payload}
        last_error: Optional[Exception] = None

        for attempt in range(2):
            try:
                content = await self._chat(messages if attempt == 0 else messages + [
                    {"role": "assistant", "content": last_raw.get("content", "")},
                    {
                        "role": "user",
                        "content": (
                            f"上一次 JSON 校验失败：{last_error}。"
                            "请修复并只返回合法 JSON。"
                        ),
                    },
                ])
                last_raw["content"] = content
                last_raw["attempt"] = attempt + 1
                data = _extract_json(content)
                last_raw["parsed"] = data
                creative = CreativeJSON.model_validate(data)
                return creative, last_raw
            except (ValidationError, json.JSONDecodeError, ValueError) as e:
                last_error = e
                last_raw["error"] = str(e)
                continue

        raise ValueError(
            f"DeepSeek JSON 校验失败（已重试 1 次）：{last_error}"
        ) from last_error

    async def _chat(self, messages: list[dict[str, str]]) -> str:
        url = self.settings.deepseek_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.deepseek_model,
            "messages": messages,
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=self.settings.deepseek_timeout_sec) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
