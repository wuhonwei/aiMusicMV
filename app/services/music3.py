from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Any, Optional

from app.services.comfyui import ComfyUIClient, ComfyUIError
from app.settings import Settings, get_settings


def write_mock_wav(dest: Path, duration_sec: float = 12.0, bpm: int = 100) -> Path:
    """Generate a short melodic (sine arpeggio) wav for mock mode."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 44100
    n_samples = int(sample_rate * duration_sec)
    freqs = [261.63, 329.63, 392.00, 523.25]  # C major arpeggio
    beat = 60.0 / max(bpm, 60)
    with wave.open(str(dest), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            t = i / sample_rate
            note_idx = int(t / beat) % len(freqs)
            freq = freqs[note_idx]
            # soft envelope per beat
            phase = (t % beat) / beat
            env = math.sin(math.pi * min(phase, 1.0)) * 0.35
            # fade out
            if t > duration_sec - 1.0:
                env *= max(0.0, duration_sec - t)
            val = int(32767 * env * math.sin(2 * math.pi * freq * t))
            frames += struct.pack("<h", val)
        wf.writeframes(frames)
    return dest


class Music3Service:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.comfy = ComfyUIClient(self.settings)

    async def generate(
        self,
        music_description: str,
        dest: Path,
        *,
        duration_hint_sec: int = 180,
        extra: Optional[dict[str, Any]] = None,
    ) -> Path:
        if self.settings.mock_mode:
            # Cap mock audio for fast tests; real mode uses model length
            dur = min(float(duration_hint_sec), 20.0)
            if duration_hint_sec <= 30:
                dur = max(8.0, float(duration_hint_sec))
            else:
                dur = 16.0
            return write_mock_wav(dest.with_suffix(".wav"), duration_sec=dur)

        workflow_path = self.settings.workflow_path(self.settings.music_workflow_path)
        workflow = self.comfy.load_workflow(workflow_path)
        self.comfy.set_node_input(
            workflow,
            self.settings.music_prompt_node_id,
            self.settings.music_prompt_input,
            music_description,
        )
        if extra:
            for node_id, inputs in extra.items():
                for k, v in inputs.items():
                    self.comfy.set_node_input(workflow, str(node_id), k, v)

        prompt_id = await self.comfy.queue_prompt(workflow)
        history = await self.comfy.wait_history(prompt_id)
        files = self.comfy.collect_outputs(history)
        audio_files = [f for f in files if f["kind"] == "audio" or f["filename"].lower().endswith((".wav", ".mp3", ".flac"))]
        if not audio_files:
            # some custom nodes put audio under images key incorrectly — take any
            audio_files = files
        if not audio_files:
            raise ComfyUIError("Music3 完成但未找到音频输出")
        f0 = audio_files[0]
        ext = Path(f0["filename"]).suffix or ".wav"
        out = dest.with_suffix(ext)
        await self.comfy.download_output(f0["filename"], f0["subfolder"], f0["type"], out)
        if out.stat().st_size == 0:
            raise ComfyUIError("下载的音频文件为空")
        return out
