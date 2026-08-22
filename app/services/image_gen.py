from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageDraw

from app.services.comfyui import ComfyUIClient, ComfyUIError
from app.settings import Settings, get_settings


def write_mock_image(dest: Path, width: int, height: int, label: str, color: tuple[int, int, int]) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)
    # gradient overlay
    for y in range(height):
        alpha = int(40 * (y / max(height, 1)))
        draw.line([(0, y), (width, y)], fill=(min(255, color[0] + alpha), color[1], min(255, color[2] + alpha // 2)))
    # label
    text = label[:80]
    draw.rectangle([40, height // 2 - 40, width - 40, height // 2 + 40], fill=(0, 0, 0))
    draw.text((60, height // 2 - 10), text, fill=(255, 255, 255))
    img.save(dest, format="PNG")
    return dest


_MOCK_COLORS = [
    (20, 40, 80),
    (80, 20, 60),
    (20, 70, 50),
    (60, 40, 20),
    (40, 20, 70),
]


class ImageGenService:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.comfy = ComfyUIClient(self.settings)

    async def generate(
        self,
        prompt: str,
        negative_prompt: str,
        dest: Path,
        *,
        aspect: str = "16:9",
        seed: Optional[int] = None,
        section_index: int = 0,
    ) -> Path:
        width, height = self.settings.image_size(aspect)
        seed = self.settings.image_seed if seed is None else seed
        # per-section seed offset for variety while staying reproducible
        seed = int(seed) + section_index * 17

        neg = negative_prompt or ""
        if self.settings.image_negative_suffix:
            neg = (neg + ", " if neg else "") + self.settings.image_negative_suffix

        if self.settings.mock_mode:
            color = _MOCK_COLORS[section_index % len(_MOCK_COLORS)]
            return write_mock_image(dest, width, height, f"{section_index}:{prompt[:40]}", color)

        workflow_path = self.settings.workflow_path(self.settings.image_workflow_path)
        workflow = self.comfy.load_workflow(workflow_path)
        s = self.settings
        self.comfy.set_node_input(workflow, s.txt2img_prompt_node_id, "text", prompt)
        self.comfy.set_node_input(workflow, s.txt2img_negative_node_id, "text", neg)
        self.comfy.set_node_input(workflow, s.txt2img_checkpoint_node_id, "ckpt_name", s.image_checkpoint)
        self.comfy.set_node_input(workflow, s.txt2img_seed_node_id, "seed", seed)
        self.comfy.set_node_input(workflow, s.txt2img_size_node_id, "width", width)
        self.comfy.set_node_input(workflow, s.txt2img_size_node_id, "height", height)
        # common sampler fields if present
        try:
            self.comfy.set_node_input(workflow, s.txt2img_seed_node_id, "steps", s.image_steps)
            self.comfy.set_node_input(workflow, s.txt2img_seed_node_id, "cfg", s.image_cfg)
        except ComfyUIError:
            pass

        prompt_id = await self.comfy.queue_prompt(workflow)
        history = await self.comfy.wait_history(prompt_id)
        files = [f for f in self.comfy.collect_outputs(history) if f["kind"] == "images"]
        if not files:
            raise ComfyUIError("出图完成但未找到图片输出")
        f0 = files[0]
        out = dest.with_suffix(".png")
        await self.comfy.download_output(f0["filename"], f0["subfolder"], f0["type"], out)
        if out.stat().st_size == 0:
            raise ComfyUIError("下载的图片为空")
        return out
