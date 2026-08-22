from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx

from app.settings import Settings, get_settings


class ComfyUIError(RuntimeError):
    pass


class ComfyUIClient:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.base = self.settings.comfyui_base_url.rstrip("/")

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base}/system_stats")
                if resp.status_code == 200:
                    return {"ok": True, "status_code": 200, "data": resp.json()}
                # some builds use /object_info
                resp2 = await client.get(f"{self.base}/object_info")
                return {
                    "ok": resp2.status_code == 200,
                    "status_code": resp2.status_code,
                }
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    async def queue_prompt(self, workflow: dict[str, Any], client_id: Optional[str] = None) -> str:
        client_id = client_id or str(uuid.uuid4())
        payload = {"prompt": workflow, "client_id": client_id}
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{self.base}/prompt", json=payload)
            if resp.status_code != 200:
                raise ComfyUIError(f"提交 prompt 失败 HTTP {resp.status_code}: {resp.text[:500]}")
            data = resp.json()
            if "error" in data:
                raise ComfyUIError(f"ComfyUI 错误: {data['error']}")
            prompt_id = data.get("prompt_id")
            if not prompt_id:
                raise ComfyUIError(f"未返回 prompt_id: {data}")
            return prompt_id

    async def wait_history(
        self,
        prompt_id: str,
        *,
        timeout_sec: Optional[float] = None,
        poll_interval: float = 1.5,
    ) -> dict[str, Any]:
        timeout_sec = timeout_sec or self.settings.comfyui_timeout_sec
        elapsed = 0.0
        async with httpx.AsyncClient(timeout=30.0) as client:
            while elapsed < timeout_sec:
                resp = await client.get(f"{self.base}/history/{prompt_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    if prompt_id in data:
                        return data[prompt_id]
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
        raise ComfyUIError(f"等待 ComfyUI history 超时（{timeout_sec}s），prompt_id={prompt_id}")

    async def download_output(self, filename: str, subfolder: str, folder_type: str, dest: Path) -> Path:
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(f"{self.base}/view", params=params)
            if resp.status_code != 200:
                raise ComfyUIError(f"下载输出失败 HTTP {resp.status_code}: {filename}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return dest

    def collect_outputs(self, history: dict[str, Any]) -> list[dict[str, str]]:
        outputs = history.get("outputs") or {}
        files: list[dict[str, str]] = []
        for _node_id, node_out in outputs.items():
            for key in ("images", "audio", "gifs"):
                for item in node_out.get(key) or []:
                    files.append(
                        {
                            "filename": item["filename"],
                            "subfolder": item.get("subfolder", ""),
                            "type": item.get("type", "output"),
                            "kind": key,
                        }
                    )
        return files

    def load_workflow(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise ComfyUIError(f"Workflow 不存在: {path}")
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def set_node_input(workflow: dict[str, Any], node_id: str, input_name: str, value: Any) -> None:
        node = workflow.get(str(node_id))
        if not node:
            raise ComfyUIError(f"Workflow 缺少节点 ID {node_id}")
        node.setdefault("inputs", {})[input_name] = value
