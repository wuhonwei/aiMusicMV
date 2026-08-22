from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.queue import BusyError, task_queue
from app.schemas.creative import CreativeJSON, ProjectInput
from app.services.comfyui import ComfyUIClient
from app.services.pipeline import Pipeline
from app.services.projects import ProjectStore
from app.settings import get_settings, reload_settings
from app.state_machine import ProjectStatus

router = APIRouter()


def get_store() -> ProjectStore:
    return ProjectStore(get_settings())


def get_pipeline() -> Pipeline:
    return Pipeline(settings=get_settings())


async def optional_token(
    x_local_token: Optional[str] = Header(default=None),
) -> None:
    settings = get_settings()
    if settings.local_token:
        if x_local_token != settings.local_token:
            raise HTTPException(401, "无效的 local token")


class UpdateSubtitlesBody(BaseModel):
    subtitles: bool


class UpdateCreativeBody(BaseModel):
    creative: CreativeJSON


class SettingsUpdateBody(BaseModel):
    projects_root: Optional[str] = None
    comfyui_base_url: Optional[str] = None
    mock_mode: Optional[bool] = None
    subtitle_font: Optional[str] = None


@router.get("/health")
async def health(_: None = Depends(optional_token)) -> dict[str, Any]:
    s = get_settings()
    comfy = await ComfyUIClient(s).health()
    return {
        "ok": True,
        "mock_mode": s.mock_mode,
        "host": s.app_host,
        "port": s.app_port,
        "projects_root": str(s.resolved_projects_root()),
        "queue": task_queue.snapshot(),
        "comfyui": comfy,
        "deepseek_key_set": bool(s.deepseek_api_key),
    }


@router.get("/queue")
async def queue_status(_: None = Depends(optional_token)) -> dict[str, Any]:
    return task_queue.snapshot()


@router.get("/projects")
async def list_projects(store: ProjectStore = Depends(get_store), _: None = Depends(optional_token)):
    return [m.model_dump() for m in store.list_projects()]


@router.post("/projects")
async def create_project(
    form: ProjectInput,
    store: ProjectStore = Depends(get_store),
    _: None = Depends(optional_token),
):
    meta = store.create(form)
    return meta.model_dump()


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    store: ProjectStore = Depends(get_store),
    _: None = Depends(optional_token),
):
    try:
        meta = store.read_meta(project_id)
    except FileNotFoundError:
        raise HTTPException(404, "项目不存在") from None
    data = meta.model_dump()
    data["path"] = str(store.project_dir(project_id))
    data["logs"] = store.list_logs(project_id)[:30]
    data["queue"] = task_queue.snapshot()
    try:
        data["has_creative"] = store.creative_path(project_id).exists() or (
            store.project_dir(project_id) / "creative_latest.json"
        ).exists()
    except Exception:  # noqa: BLE001
        data["has_creative"] = False
    data["audio_path"] = str(store.audio_path(project_id)) if meta.audio_version else ""
    data["audio_exists"] = store.audio_path(project_id).exists() if meta.audio_version else False
    data["output_path"] = str(store.output_path(project_id)) if meta.audio_version else ""
    data["output_exists"] = store.output_path(project_id).exists() if meta.audio_version else False
    return data


@router.get("/projects/{project_id}/creative")
async def get_creative(
    project_id: str,
    store: ProjectStore = Depends(get_store),
    _: None = Depends(optional_token),
):
    try:
        return store.read_creative(project_id).model_dump()
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e


@router.put("/projects/{project_id}/creative")
async def put_creative(
    project_id: str,
    body: UpdateCreativeBody,
    store: ProjectStore = Depends(get_store),
    _: None = Depends(optional_token),
):
    meta = store.read_meta(project_id)
    if meta.status not in (
        ProjectStatus.AWAIT_LYRICS_REVIEW.value,
        ProjectStatus.FAILED.value,
        ProjectStatus.AWAIT_MUSIC_REVIEW.value,
    ):
        # allow edit mainly at lyrics review; also allow before music confirm for description
        if meta.status not in (
            ProjectStatus.AWAIT_LYRICS_REVIEW.value,
            ProjectStatus.AWAIT_MUSIC_REVIEW.value,
            ProjectStatus.READY.value,
            ProjectStatus.FAILED.value,
        ):
            raise HTTPException(400, f"当前状态不可编辑 creative: {meta.status}")
    store.update_creative_inplace(project_id, body.creative)
    return {"ok": True, "creative": body.creative.model_dump()}


@router.patch("/projects/{project_id}/subtitles")
async def patch_subtitles(
    project_id: str,
    body: UpdateSubtitlesBody,
    store: ProjectStore = Depends(get_store),
    _: None = Depends(optional_token),
):
    meta = store.read_meta(project_id)
    meta.subtitles = body.subtitles
    store.write_meta(meta)
    return meta.model_dump()


async def _run_job(project_id: str, step: str, factory):
    try:
        job = await task_queue.run(project_id, step, factory)
        return {"ok": True, "job": job.__dict__}
    except BusyError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(e),
                "current": e.current.__dict__,
            },
        ) from e


@router.post("/projects/{project_id}/actions/generate-lyrics")
async def action_generate_lyrics(
    project_id: str,
    pipeline: Pipeline = Depends(get_pipeline),
    _: None = Depends(optional_token),
):
    return await _run_job(
        project_id, "generate_lyrics", lambda: pipeline.generate_lyrics(project_id)
    )


@router.post("/projects/{project_id}/actions/confirm-lyrics")
async def action_confirm_lyrics(
    project_id: str,
    pipeline: Pipeline = Depends(get_pipeline),
    store: ProjectStore = Depends(get_store),
    _: None = Depends(optional_token),
):
    meta = store.read_meta(project_id)
    if meta.status not in (ProjectStatus.AWAIT_LYRICS_REVIEW.value, ProjectStatus.FAILED.value):
        raise HTTPException(400, f"当前状态不能确认歌词: {meta.status}")

    return await _run_job(
        project_id, "generate_music", lambda: pipeline.generate_music(project_id, reroll=False)
    )


@router.post("/projects/{project_id}/actions/reroll-music")
async def action_reroll_music(
    project_id: str,
    pipeline: Pipeline = Depends(get_pipeline),
    _: None = Depends(optional_token),
):
    return await _run_job(
        project_id, "reroll_music", lambda: pipeline.generate_music(project_id, reroll=True)
    )


@router.post("/projects/{project_id}/actions/confirm-music")
async def action_confirm_music(
    project_id: str,
    pipeline: Pipeline = Depends(get_pipeline),
    store: ProjectStore = Depends(get_store),
    _: None = Depends(optional_token),
):
    meta = store.read_meta(project_id)
    if meta.status not in (
        ProjectStatus.AWAIT_MUSIC_REVIEW.value,
        ProjectStatus.FAILED.value,
        ProjectStatus.READY.value,
    ):
        raise HTTPException(400, f"当前状态不能确认成曲: {meta.status}")

    return await _run_job(
        project_id,
        "generate_mv",
        lambda: pipeline.generate_images_and_assemble(project_id),
    )


@router.post("/projects/{project_id}/actions/reassemble")
async def action_reassemble(
    project_id: str,
    pipeline: Pipeline = Depends(get_pipeline),
    _: None = Depends(optional_token),
):
    return await _run_job(
        project_id, "reassemble", lambda: pipeline.reassemble_only(project_id)
    )


@router.post("/projects/{project_id}/actions/retry")
async def action_retry(
    project_id: str,
    pipeline: Pipeline = Depends(get_pipeline),
    store: ProjectStore = Depends(get_store),
    _: None = Depends(optional_token),
):
    meta = store.read_meta(project_id)
    step = meta.last_failed_step or ""
    if meta.status != ProjectStatus.FAILED.value and not step:
        raise HTTPException(400, "没有可重试的失败步骤")

    async def work():
        if step in ("generating_lyrics", "lyrics"):
            await pipeline.generate_lyrics(project_id)
        elif step in ("generating_music", "music"):
            await pipeline.generate_music(project_id, reroll=False)
        elif step in ("generating_images", "images", "assembling", "assemble"):
            imgs = list(
                (store.project_dir(project_id) / "images").glob(f"v{meta.audio_version}_*")
            )
            if step in ("assembling", "assemble") and store.timeline_path(project_id).exists() and imgs:
                try:
                    await pipeline.reassemble_only(project_id)
                    return
                except Exception:  # noqa: BLE001
                    pass
            await pipeline.generate_images_and_assemble(project_id)
        else:
            await pipeline.generate_lyrics(project_id)

    return await _run_job(project_id, f"retry_{step or 'unknown'}", work)

@router.get("/projects/{project_id}/audio")
async def get_audio(project_id: str, store: ProjectStore = Depends(get_store)):
    path = store.audio_path(project_id)
    if not path.exists():
        raise HTTPException(404, "音频不存在")
    media = "audio/wav" if path.suffix == ".wav" else "audio/mpeg"
    return FileResponse(path, media_type=media, filename=path.name)


@router.get("/projects/{project_id}/video")
async def get_video(project_id: str, store: ProjectStore = Depends(get_store)):
    path = store.output_path(project_id)
    if not path.exists():
        raise HTTPException(404, "视频不存在")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.get("/projects/{project_id}/download/video")
async def download_video(project_id: str, store: ProjectStore = Depends(get_store)):
    path = store.output_path(project_id)
    if not path.exists():
        raise HTTPException(404, "视频不存在")
    return FileResponse(path, media_type="video/mp4", filename=path.name, content_disposition_type="attachment")


@router.get("/projects/{project_id}/logs/{filename}")
async def download_log(project_id: str, filename: str, store: ProjectStore = Depends(get_store)):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "非法文件名")
    path = store.project_dir(project_id) / "logs" / filename
    if not path.exists():
        raise HTTPException(404, "日志不存在")
    return FileResponse(path, filename=filename, content_disposition_type="attachment")


@router.post("/projects/{project_id}/open-folder")
async def open_folder(project_id: str, store: ProjectStore = Depends(get_store)):
    path = store.project_dir(project_id)
    if not path.exists():
        raise HTTPException(404, "项目目录不存在")
    if os.name == "nt":
        subprocess.Popen(["explorer", str(path)])  # noqa: S603
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603
    return {"ok": True, "path": str(path)}


@router.get("/settings")
async def get_app_settings(_: None = Depends(optional_token)):
    s = get_settings()
    return {
        "projects_root": str(s.resolved_projects_root()),
        "comfyui_base_url": s.comfyui_base_url,
        "mock_mode": s.mock_mode,
        "subtitle_font": s.subtitle_font,
        "default_aspect": s.default_aspect,
        "subtitles_default": s.subtitles_default,
        "deepseek_model": s.deepseek_model,
        "deepseek_key_set": bool(s.deepseek_api_key),
        "image_checkpoint": s.image_checkpoint,
    }


@router.post("/settings")
async def update_app_settings(body: SettingsUpdateBody, _: None = Depends(optional_token)):
    """Persist overrides into config.yaml (env still wins for secrets)."""
    import yaml
    from app.settings import REPO_ROOT

    cfg_path = REPO_ROOT / "config.yaml"
    data: dict[str, Any] = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if body.projects_root is not None:
        data["projects_root"] = body.projects_root
    if body.comfyui_base_url is not None:
        data["comfyui_base_url"] = body.comfyui_base_url
    if body.mock_mode is not None:
        data["mock_mode"] = body.mock_mode
    if body.subtitle_font is not None:
        data.setdefault("subtitle", {})
        if isinstance(data["subtitle"], dict):
            data["subtitle"]["font"] = body.subtitle_font
    cfg_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    # Also update process env for mock/comfy so reload picks them if not in OS env
    if body.mock_mode is not None and "MOCK_MODE" not in os.environ:
        os.environ["MOCK_MODE"] = "true" if body.mock_mode else "false"
    if body.comfyui_base_url is not None and "COMFYUI_BASE_URL" not in os.environ:
        os.environ["COMFYUI_BASE_URL"] = body.comfyui_base_url
    if body.projects_root is not None and "PROJECTS_ROOT" not in os.environ:
        os.environ["PROJECTS_ROOT"] = body.projects_root
    s = reload_settings()
    return {
        "ok": True,
        "projects_root": str(s.resolved_projects_root()),
        "comfyui_base_url": s.comfyui_base_url,
        "mock_mode": s.mock_mode,
        "subtitle_font": s.subtitle_font,
    }
