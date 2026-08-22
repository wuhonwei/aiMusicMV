from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from app.settings import Settings, get_settings


class FFmpegError(RuntimeError):
    pass


def run_cmd(cmd: list[str], *, timeout: Optional[float] = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        raise FFmpegError(f"命令未找到: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise FFmpegError(f"命令超时: {' '.join(cmd[:3])}...") from e


def ffprobe_duration(path: Path, ffprobe: str = "ffprobe") -> float:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    proc = run_cmd(cmd, timeout=60)
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe 失败: {proc.stderr.strip()}")
    data = json.loads(proc.stdout or "{}")
    dur = float((data.get("format") or {}).get("duration") or 0)
    if dur <= 0:
        raise FFmpegError(f"无法读取音频时长: {path}")
    return dur


def ffprobe_video_size(path: Path, ffprobe: str = "ffprobe") -> tuple[int, int]:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "json",
        str(path),
    ]
    proc = run_cmd(cmd, timeout=60)
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe 视频信息失败: {proc.stderr.strip()}")
    streams = (json.loads(proc.stdout or "{}").get("streams") or [{}])
    w = int(streams[0].get("width") or 0)
    h = int(streams[0].get("height") or 0)
    return w, h


def _sec_to_ts(sec: float) -> str:
    if sec < 0:
        sec = 0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def write_srt(shots: list[dict[str, Any]], dest: Path) -> Path:
    lines: list[str] = []
    for i, shot in enumerate(shots, start=1):
        text = (shot.get("lyrics") or "").strip()
        if not text:
            continue
        # SRT uses blank line between cues; within cue use space/newline
        body = text.replace("\r\n", "\n").strip()
        lines.append(str(i))
        lines.append(f"{_sec_to_ts(float(shot['start']))} --> {_sec_to_ts(float(shot['end']))}")
        lines.append(body)
        lines.append("")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def _escape_subtitles_path(path: Path) -> str:
    # ffmpeg subtitles filter on Windows: escape drive colon and backslashes
    s = str(path.resolve()).replace("\\", "/")
    s = s.replace(":", "\\:")
    s = s.replace("'", "\\'")
    return s


def assemble_mv(
    *,
    shots: list[dict[str, Any]],
    image_paths: dict[str, Path],
    audio_path: Path,
    output_path: Path,
    aspect: str = "16:9",
    subtitles: bool = True,
    srt_path: Optional[Path] = None,
    settings: Optional[Settings] = None,
) -> Path:
    """
    Still images + Ken Burns (zoompan) + audio + optional hard subs → H.264/AAC MP4.
    """
    settings = settings or get_settings()
    ffmpeg = settings.ffmpeg_path
    width, height = settings.image_size(aspect)
    fps = 30

    if not shots:
        raise FFmpegError("shots 为空，无法合成")
    if not audio_path.exists():
        raise FFmpegError(f"音频不存在: {audio_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="mvstudio_"))
    try:
        clip_paths: list[Path] = []
        for idx, shot in enumerate(shots):
            key = shot["image_key"]
            img = image_paths.get(key)
            if img is None or not img.exists():
                raise FFmpegError(f"缺少镜头图片: {key}")
            dur = max(float(shot["duration"]), 0.1)
            frames = max(int(dur * fps), 1)
            # Ken Burns: slow zoom in
            z_end = 1.12
            zoompan = (
                f"scale={width * 2}:{height * 2},"
                f"zoompan=z='min(zoom+0.0008\\,{z_end})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d={frames}:s={width}x{height}:fps={fps},"
                f"format=yuv420p"
            )
            clip = work / f"clip_{idx:03d}.mp4"
            cmd = [
                ffmpeg,
                "-y",
                "-loop",
                "1",
                "-i",
                str(img),
                "-vf",
                zoompan,
                "-t",
                f"{dur:.4f}",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                str(clip),
            ]
            proc = run_cmd(cmd, timeout=300)
            if proc.returncode != 0:
                raise FFmpegError(f"镜头合成失败 #{idx}: {proc.stderr[-800:]}")
            clip_paths.append(clip)

        concat_list = work / "concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{p.resolve().as_posix()}'" for p in clip_paths) + "\n",
            encoding="utf-8",
        )
        silent_video = work / "video_silent.mp4"
        proc = run_cmd(
            [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                str(silent_video),
            ],
            timeout=300,
        )
        if proc.returncode != 0:
            raise FFmpegError(f"拼接视频失败: {proc.stderr[-800:]}")

        # Mux audio
        with_audio = work / "with_audio.mp4"
        proc = run_cmd(
            [
                ffmpeg,
                "-y",
                "-i",
                str(silent_video),
                "-i",
                str(audio_path),
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(with_audio),
            ],
            timeout=300,
        )
        if proc.returncode != 0:
            raise FFmpegError(f"音视频合并失败: {proc.stderr[-800:]}")

        if subtitles:
            if srt_path is None:
                srt_path = output_path.with_suffix(".srt")
                write_srt(shots, srt_path)
            style = (
                f"FontName={settings.subtitle_font},"
                f"FontSize={settings.subtitle_font_size},"
                f"PrimaryColour=&H00FFFFFF,"
                f"OutlineColour=&H00000000,"
                f"BorderStyle=1,Outline=2,Shadow=0,"
                f"MarginV={settings.subtitle_margin_v}"
            )
            sub_path = _escape_subtitles_path(srt_path)
            # Prefer fontsdir on Windows for system fonts
            fontsdir = ""
            windir = os.environ.get("WINDIR", r"C:\Windows")
            fonts_path = Path(windir) / "Fonts"
            if fonts_path.is_dir():
                fontsdir = f":fontsdir='{_escape_subtitles_path(fonts_path)}'"
            vf = f"subtitles='{sub_path}'{fontsdir}:force_style='{style}'"
            proc = run_cmd(
                [
                    ffmpeg,
                    "-y",
                    "-i",
                    str(with_audio),
                    "-vf",
                    vf,
                    "-c:a",
                    "copy",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    str(output_path),
                ],
                timeout=600,
            )
            if proc.returncode != 0:
                # Retry without custom font style (still burn SRT)
                vf2 = f"subtitles='{sub_path}'{fontsdir}"
                proc2 = run_cmd(
                    [
                        ffmpeg,
                        "-y",
                        "-i",
                        str(with_audio),
                        "-vf",
                        vf2,
                        "-c:a",
                        "copy",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-preset",
                        "veryfast",
                        "-crf",
                        "20",
                        str(output_path),
                    ],
                    timeout=600,
                )
                if proc2.returncode != 0:
                    raise FFmpegError(
                        f"烧录字幕失败（请检查字体「{settings.subtitle_font}」或 libass）:\n"
                        f"{proc.stderr[-500:]}\n---\n{proc2.stderr[-500:]}"
                    )
        else:
            shutil.copy2(with_audio, output_path)

        return output_path
    finally:
        shutil.rmtree(work, ignore_errors=True)
