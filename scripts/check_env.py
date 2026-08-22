"""
Environment self-check for MV Studio.
Usage: python scripts/check_env.py
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return name, ok, detail


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    os.chdir(ROOT)

    from app.settings import get_settings

    get_settings.cache_clear()
    s = get_settings()
    rows: list[tuple[str, bool, str]] = []

    rows.append(check("Python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0]))

    ffmpeg = shutil.which(s.ffmpeg_path) or s.ffmpeg_path
    ffprobe = shutil.which(s.ffprobe_path) or s.ffprobe_path
    try:
        out = subprocess.check_output([ffmpeg, "-version"], text=True, stderr=subprocess.STDOUT)
        rows.append(check("ffmpeg", True, out.splitlines()[0][:80]))
    except Exception as e:  # noqa: BLE001
        rows.append(check("ffmpeg", False, str(e)))

    try:
        out = subprocess.check_output([ffprobe, "-version"], text=True, stderr=subprocess.STDOUT)
        rows.append(check("ffprobe", True, out.splitlines()[0][:80]))
    except Exception as e:  # noqa: BLE001
        rows.append(check("ffprobe", False, str(e)))

    # Port availability (informational)
    sock = socket.socket()
    try:
        sock.bind((s.app_host, s.app_port))
        rows.append(check(f"Port {s.app_port} free", True, s.app_host))
        sock.close()
    except OSError as e:
        rows.append(check(f"Port {s.app_port} free", False, str(e)))
        sock.close()

    # Projects root writable
    root = s.resolved_projects_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        rows.append(check("PROJECTS_ROOT writable", True, str(root)))
    except Exception as e:  # noqa: BLE001
        rows.append(check("PROJECTS_ROOT writable", False, str(e)))

    music_wf = s.workflow_path(s.music_workflow_path)
    image_wf = s.workflow_path(s.image_workflow_path)
    rows.append(check("Music workflow", music_wf.exists(), str(music_wf)))
    rows.append(check("Image workflow", image_wf.exists(), str(image_wf)))

    # DeepSeek key (optional in mock)
    key_ok = bool(s.deepseek_api_key)
    rows.append(
        check(
            "DEEPSEEK_API_KEY",
            key_ok or s.mock_mode,
            "set" if key_ok else ("skip (MOCK_MODE)" if s.mock_mode else "missing"),
        )
    )

    # ComfyUI
    try:
        import httpx

        r = httpx.get(s.comfyui_base_url.rstrip("/") + "/system_stats", timeout=3.0)
        comfy_ok = r.status_code == 200
        detail = f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        comfy_ok = False
        detail = str(e)
    if s.mock_mode:
        rows.append(check("ComfyUI reachable", True, f"skip (MOCK_MODE); probe={detail}"))
    else:
        rows.append(check("ComfyUI reachable", comfy_ok, detail))

    rows.append(check("MOCK_MODE", True, str(s.mock_mode)))

    # Core items for mock DoD
    core_names = {
        "Python >= 3.11",
        "ffmpeg",
        "ffprobe",
        "PROJECTS_ROOT writable",
        "Music workflow",
        "Image workflow",
        "DEEPSEEK_API_KEY",
        "ComfyUI reachable",
    }

    print("=" * 64)
    print("MV Studio environment check")
    print("=" * 64)
    fails = 0
    for name, ok, detail in rows:
        status = "PASS" if ok else "FAIL"
        if not ok and name in core_names:
            fails += 1
        print(f"{status:4}  {name:28}  {detail}")
    print("=" * 64)
    if fails:
        print(f"RESULT: FAIL ({fails} core checks)")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
