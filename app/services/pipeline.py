from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from app.schemas.creative import CreativeJSON
from app.services.deepseek import DeepSeekClient
from app.services.ffmpeg_mv import assemble_mv, ffprobe_duration, write_srt
from app.services.image_gen import ImageGenService
from app.services.music3 import Music3Service
from app.services.projects import ProjectStore
from app.services.timeline import build_timeline
from app.settings import Settings, get_settings
from app.state_machine import ProjectStatus


class Pipeline:
    def __init__(
        self,
        store: Optional[ProjectStore] = None,
        settings: Optional[Settings] = None,
    ):
        self.settings = settings or get_settings()
        self.store = store or ProjectStore(self.settings)
        self.deepseek = DeepSeekClient(self.settings)
        self.music = Music3Service(self.settings)
        self.images = ImageGenService(self.settings)

    async def generate_lyrics(self, project_id: str) -> CreativeJSON:
        self.store.set_status(project_id, ProjectStatus.GENERATING_LYRICS)
        form = self.store.read_input(project_id)
        try:
            creative, raw = await self.deepseek.generate_creative(form)
            self.store.write_log(project_id, "lyrics", request=form.model_dump(), response=raw)
            self.store.save_creative(project_id, creative, bump=True)
            self.store.set_status(project_id, ProjectStatus.AWAIT_LYRICS_REVIEW, title=creative.title)
            return creative
        except Exception as e:  # noqa: BLE001
            self.store.write_log(project_id, "lyrics", request=form.model_dump(), error=str(e))
            self.store.fail(project_id, "generating_lyrics", str(e))
            raise

    async def generate_music(self, project_id: str, *, reroll: bool = False) -> Path:
        if reroll:
            self.store.cleanup_downstream_for_reroll(project_id)
        self.store.set_status(project_id, ProjectStatus.GENERATING_MUSIC)
        creative = self.store.read_creative(project_id)
        version = self.store.bump_audio_version(project_id)
        dest = self.store.project_dir(project_id) / "audio" / f"v{version}.wav"
        req = {
            "music_description": creative.music_description,
            "performance_notes": creative.performance_notes,
            "duration_sec_target": creative.style.duration_sec_target,
            "version": version,
            "reroll": reroll,
        }
        try:
            path = await self.music.generate(
                creative.music_description,
                dest,
                duration_hint_sec=creative.style.duration_sec_target,
            )
            # normalize filename if extension differs
            if path != dest and path.exists():
                # keep whatever extension music service used
                pass
            self.store.write_log(project_id, "music", request=req, response={"path": str(path)})
            self.store.set_status(project_id, ProjectStatus.AWAIT_MUSIC_REVIEW)
            return path
        except Exception as e:  # noqa: BLE001
            self.store.write_log(project_id, "music", request=req, error=str(e))
            self.store.fail(project_id, "generating_music", str(e))
            raise

    async def generate_images_and_assemble(self, project_id: str) -> Path:
        meta = self.store.read_meta(project_id)
        creative = self.store.read_creative(project_id)
        version = meta.audio_version
        audio = self.store.audio_path(project_id, version)
        if not audio.exists():
            raise FileNotFoundError(f"音频不存在: {audio}")

        # Images
        self.store.set_status(project_id, ProjectStatus.GENERATING_IMAGES)
        image_paths: dict[str, Path] = {}
        try:
            for i, sec in enumerate(creative.sections):
                count = max(1, min(3, sec.shot_count or 1))
                for shot_i in range(count):
                    key = f"v{version}_{sec.id}" + (f"_{shot_i}" if count > 1 else "")
                    dest = self.store.project_dir(project_id) / "images" / f"{key}.png"
                    # Inherit visual bible in prompt
                    bible = creative.visual_bible
                    prompt = (
                        f"{sec.visual_prompt}. "
                        f"Setting: {bible.setting}. Palette: {bible.palette}. "
                        f"Character: {bible.character}. Camera: {bible.camera_style}. "
                        f"Must include: {', '.join(bible.must_include)}. "
                        f"Style consistent music video still."
                    )
                    path = await self.images.generate(
                        prompt,
                        sec.negative_prompt,
                        dest,
                        aspect=meta.aspect,
                        section_index=i * 3 + shot_i,
                    )
                    image_paths[key] = path
            self.store.write_log(
                project_id,
                "images",
                request={"sections": len(creative.sections), "version": version},
                response={"images": [str(p) for p in image_paths.values()]},
            )
        except Exception as e:  # noqa: BLE001
            self.store.write_log(project_id, "images", error=str(e))
            self.store.fail(project_id, "generating_images", str(e))
            raise

        # Timeline + assemble
        self.store.set_status(project_id, ProjectStatus.ASSEMBLING)
        try:
            duration = ffprobe_duration(audio, self.settings.ffprobe_path)
            timeline = build_timeline(
                creative,
                duration,
                min_shot_duration=self.settings.min_shot_duration_sec,
                version=version,
                shots_per_section_default=self.settings.shots_per_section_default,
            )
            self.store.write_json(self.store.timeline_path(project_id, version), timeline)
            out = self.store.output_path(project_id, version)
            srt = self.store.project_dir(project_id) / "output" / f"subs_v{version}.srt"
            if meta.subtitles:
                write_srt(timeline["shots"], srt)
            assemble_mv(
                shots=timeline["shots"],
                image_paths=image_paths,
                audio_path=audio,
                output_path=out,
                aspect=meta.aspect,
                subtitles=meta.subtitles,
                srt_path=srt if meta.subtitles else None,
                settings=self.settings,
            )
            self.store.write_log(
                project_id,
                "assemble",
                request={"version": version, "subtitles": meta.subtitles},
                response={"output": str(out)},
            )
            self.store.set_status(project_id, ProjectStatus.READY)
            return out
        except Exception as e:  # noqa: BLE001
            self.store.write_log(project_id, "assemble", error=str(e))
            self.store.fail(project_id, "assembling", str(e))
            raise

    async def reassemble_only(self, project_id: str) -> Path:
        """Re-run ffmpeg with existing images/audio (e.g. subtitle toggle)."""
        meta = self.store.read_meta(project_id)
        version = meta.audio_version
        audio = self.store.audio_path(project_id, version)
        timeline_path = self.store.timeline_path(project_id, version)
        if not timeline_path.exists():
            raise FileNotFoundError("缺少 timeline，请重新生成 MV")
        timeline = self.store.read_json(timeline_path)
        image_paths: dict[str, Path] = {}
        for shot in timeline["shots"]:
            key = shot["image_key"]
            p = self.store.project_dir(project_id) / "images" / f"{key}.png"
            if not p.exists():
                raise FileNotFoundError(f"缺少图片 {key}")
            image_paths[key] = p
        self.store.set_status(project_id, ProjectStatus.ASSEMBLING)
        out = self.store.output_path(project_id, version)
        srt = self.store.project_dir(project_id) / "output" / f"subs_v{version}.srt"
        if meta.subtitles:
            write_srt(timeline["shots"], srt)
        try:
            assemble_mv(
                shots=timeline["shots"],
                image_paths=image_paths,
                audio_path=audio,
                output_path=out,
                aspect=meta.aspect,
                subtitles=meta.subtitles,
                srt_path=srt if meta.subtitles else None,
                settings=self.settings,
            )
            self.store.set_status(project_id, ProjectStatus.READY)
            return out
        except Exception as e:  # noqa: BLE001
            self.store.fail(project_id, "assembling", str(e))
            raise
