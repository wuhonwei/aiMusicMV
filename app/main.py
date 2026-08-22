from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import router as api_router
from app.settings import get_settings
from app.services.projects import ProjectStore

APP_DIR = Path(__file__).resolve().parent


def create_app() -> FastAPI:
    settings = get_settings()
    settings.resolved_projects_root().mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="MV Studio", version="1.0.0", docs_url="/docs")
    app.include_router(api_router, prefix="/api")

    static_dir = APP_DIR / "static"
    templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        store = ProjectStore(get_settings())
        projects = store.list_projects()[:20]
        s = get_settings()
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "projects": projects,
                "settings": s,
                "default_aspect": s.default_aspect,
                "subtitles_default": s.subtitles_default,
                "queue": __import__("app.queue", fromlist=["task_queue"]).task_queue.snapshot(),
            },
        )

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    async def project_page(request: Request, project_id: str):
        store = ProjectStore(get_settings())
        try:
            meta = store.read_meta(project_id)
        except Exception:  # noqa: BLE001
            return RedirectResponse("/", status_code=302)
        creative = None
        try:
            creative = store.read_creative(project_id)
        except Exception:  # noqa: BLE001
            pass
        return templates.TemplateResponse(
            "project.html",
            {
                "request": request,
                "meta": meta,
                "creative": creative,
                "path": str(store.project_dir(project_id)),
                "logs": store.list_logs(project_id)[:40],
                "audio_exists": store.audio_path(project_id).exists() if meta.audio_version else False,
                "output_exists": store.output_path(project_id).exists() if meta.audio_version else False,
                "queue": __import__("app.queue", fromlist=["task_queue"]).task_queue.snapshot(),
                "settings": get_settings(),
            },
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        s = get_settings()
        from app.services.comfyui import ComfyUIClient

        comfy = await ComfyUIClient(s).health()
        return templates.TemplateResponse(
            "settings.html",
            {
                "request": request,
                "settings": s,
                "projects_root": str(s.resolved_projects_root()),
                "comfy": comfy,
            },
        )

    return app


app = create_app()
