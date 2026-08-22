from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.schemas.creative import CreativeJSON, ProjectInput, ProjectMeta
from app.settings import Settings, get_settings
from app.state_machine import ProjectStatus, assert_transition


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectStore:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.root = self.settings.resolved_projects_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def project_dir(self, project_id: str) -> Path:
        return self.root / project_id

    def create(self, form: ProjectInput) -> ProjectMeta:
        project_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        pdir = self.project_dir(project_id)
        for sub in ("audio", "images", "output", "logs"):
            (pdir / sub).mkdir(parents=True, exist_ok=True)

        meta = ProjectMeta(
            project_id=project_id,
            status=ProjectStatus.CREATED.value,
            aspect=form.aspect,
            subtitles=form.subtitles,
            version=1,
            created_at=_now(),
            updated_at=_now(),
            mock_mode=self.settings.mock_mode,
        )
        self.write_meta(meta)
        self.write_json(pdir / "input.json", form.model_dump())
        return meta

    def list_projects(self) -> list[ProjectMeta]:
        items: list[ProjectMeta] = []
        if not self.root.exists():
            return items
        for d in sorted(self.root.iterdir(), reverse=True):
            if d.is_dir() and (d / "meta.json").exists():
                try:
                    items.append(self.read_meta(d.name))
                except Exception:  # noqa: BLE001
                    continue
        return items

    def read_meta(self, project_id: str) -> ProjectMeta:
        data = self.read_json(self.project_dir(project_id) / "meta.json")
        return ProjectMeta.model_validate(data)

    def write_meta(self, meta: ProjectMeta) -> None:
        meta.updated_at = _now()
        self.write_json(self.project_dir(meta.project_id) / "meta.json", meta.model_dump())

    def set_status(
        self,
        project_id: str,
        new_status: ProjectStatus | str,
        *,
        error: str = "",
        failed_step: str = "",
        **extra: Any,
    ) -> ProjectMeta:
        meta = self.read_meta(project_id)
        assert_transition(meta.status, new_status)
        meta.status = ProjectStatus(new_status).value
        if error:
            meta.last_error = error
            meta.last_failed_step = failed_step or meta.last_failed_step
        elif ProjectStatus(new_status) != ProjectStatus.FAILED:
            meta.last_error = ""
        for k, v in extra.items():
            if hasattr(meta, k):
                setattr(meta, k, v)
        self.write_meta(meta)
        return meta

    def fail(self, project_id: str, step: str, error: str) -> ProjectMeta:
        meta = self.read_meta(project_id)
        # FAILED is reachable from most states
        try:
            assert_transition(meta.status, ProjectStatus.FAILED)
        except Exception:  # noqa: BLE001
            pass
        meta.status = ProjectStatus.FAILED.value
        meta.last_error = error
        meta.last_failed_step = step
        self.write_meta(meta)
        return meta

    def read_input(self, project_id: str) -> ProjectInput:
        data = self.read_json(self.project_dir(project_id) / "input.json")
        return ProjectInput.model_validate(data)

    def creative_path(self, project_id: str, version: Optional[int] = None) -> Path:
        meta = self.read_meta(project_id)
        ver = version if version is not None else meta.creative_version
        return self.project_dir(project_id) / f"creative_v{ver}.json"

    def save_creative(self, project_id: str, creative: CreativeJSON, *, bump: bool = True) -> Path:
        meta = self.read_meta(project_id)
        if meta.creative_version == 0:
            meta.creative_version = 1
        elif bump:
            meta.creative_version += 1
        meta.title = creative.title
        path = self.project_dir(project_id) / f"creative_v{meta.creative_version}.json"
        self.write_json(path, creative.model_dump())
        self.write_json(self.project_dir(project_id) / "creative_latest.json", creative.model_dump())
        self.write_meta(meta)
        return path

    def read_creative(self, project_id: str) -> CreativeJSON:
        meta = self.read_meta(project_id)
        path = self.creative_path(project_id)
        if not path.exists():
            latest = self.project_dir(project_id) / "creative_latest.json"
            if latest.exists():
                path = latest
            else:
                raise FileNotFoundError("尚未生成 creative JSON")
        return CreativeJSON.model_validate(self.read_json(path))

    def update_creative_inplace(self, project_id: str, creative: CreativeJSON) -> Path:
        """Update current creative without bumping version (edit at checkpoint 1)."""
        meta = self.read_meta(project_id)
        if meta.creative_version < 1:
            meta.creative_version = 1
        path = self.project_dir(project_id) / f"creative_v{meta.creative_version}.json"
        self.write_json(path, creative.model_dump())
        self.write_json(self.project_dir(project_id) / "creative_latest.json", creative.model_dump())
        meta.title = creative.title
        self.write_meta(meta)
        return path

    def audio_path(self, project_id: str, version: Optional[int] = None) -> Path:
        meta = self.read_meta(project_id)
        ver = version if version is not None else meta.audio_version
        pdir = self.project_dir(project_id) / "audio"
        for ext in (".wav", ".mp3", ".flac"):
            candidate = pdir / f"v{ver}{ext}"
            if candidate.exists():
                return candidate
        return pdir / f"v{ver}.wav"

    def timeline_path(self, project_id: str, version: Optional[int] = None) -> Path:
        meta = self.read_meta(project_id)
        ver = version if version is not None else meta.audio_version
        return self.project_dir(project_id) / f"timeline_v{ver}.json"

    def output_path(self, project_id: str, version: Optional[int] = None) -> Path:
        meta = self.read_meta(project_id)
        ver = version if version is not None else meta.audio_version
        return self.project_dir(project_id) / "output" / f"final_v{ver}.mp4"

    def bump_audio_version(self, project_id: str) -> int:
        meta = self.read_meta(project_id)
        meta.audio_version += 1
        meta.version = meta.audio_version
        self.write_meta(meta)
        return meta.audio_version

    def cleanup_downstream_for_reroll(self, project_id: str) -> dict[str, Any]:
        """
        Keep creative JSON; delete audio / images / timeline / output for current and prepare next.
        Does not delete creative_vN.json.
        """
        meta = self.read_meta(project_id)
        pdir = self.project_dir(project_id)
        removed: list[str] = []

        def _rm(path: Path) -> None:
            if path.is_file():
                path.unlink()
                removed.append(str(path))
            elif path.is_dir():
                shutil.rmtree(path)
                path.mkdir(parents=True, exist_ok=True)
                removed.append(str(path) + "/")

        # Remove versioned downstream for current audio version and any leftovers
        for pattern in (
            "audio/v*",
            "images/v*",
            "timeline_v*.json",
            "output/final_v*.mp4",
            "output/*.srt",
            "output/*.ass",
        ):
            for match in pdir.glob(pattern):
                if match.is_file():
                    match.unlink()
                    removed.append(str(match))
                elif match.is_dir():
                    shutil.rmtree(match)
                    removed.append(str(match))

        # Ensure dirs exist
        for sub in ("audio", "images", "output"):
            (pdir / sub).mkdir(parents=True, exist_ok=True)

        return {"removed": removed, "creative_version": meta.creative_version, "kept_creative": True}

    def write_log(
        self,
        project_id: str,
        step: str,
        *,
        request: Any = None,
        response: Any = None,
        error: str = "",
    ) -> None:
        logs = self.project_dir(project_id) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"step_{step}_{stamp}"
        if request is not None:
            self.write_json(logs / f"{base}.request.json", request)
        if response is not None:
            self.write_json(logs / f"{base}.response.json", response)
        if error:
            (logs / f"{base}.error.txt").write_text(error, encoding="utf-8")

    def list_logs(self, project_id: str) -> list[str]:
        logs = self.project_dir(project_id) / "logs"
        if not logs.exists():
            return []
        return sorted([p.name for p in logs.iterdir() if p.is_file()], reverse=True)

    @staticmethod
    def read_json(path: Path) -> Any:
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
