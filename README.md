# MV Studio — 本地个人音乐 MV 生成平台

仅绑定 `127.0.0.1` 的单体应用：DeepSeek 生成词曲/分镜 JSON → ComfyUI MiniMax Music 3 出歌 → 段落静帧 + Ken Burns + 烧录字幕 → ffmpeg 合成可下载 MP4。

支持 **Mock 模式**（无 GPU / 无权重也可跑通 UI 与全管线）。

---

## 系统要求

| 项目 | 说明 |
|------|------|
| OS | Windows 11 |
| Python | 3.11+（已在 3.12 验证） |
| ffmpeg / ffprobe | 需在 PATH 中 |
| GPU | 真实模式建议 NVIDIA（如 5090D）；Mock 不需要 |
| 磁盘 | 项目落盘默认 `D:\mv-studio\projects`（无 D: 则回退到 `%USERPROFILE%\mv-studio\projects`） |
| ComfyUI | 真实模式需本机可访问，且已装 MiniMax Music 3 + 出图 checkpoint |

---

## 安装（约 10–30 分钟，不含大模型下载）

```powershell
cd D:\Develop\aiMusicMV
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
copy .env.example .env
copy config.yaml.example config.yaml
```

编辑 `.env`：

- `MOCK_MODE=true`：先跑通（推荐）
- 填入 `DEEPSEEK_API_KEY`（真实词曲；Mock 下可留空）
- 按需改 `PROJECTS_ROOT`、`COMFYUI_BASE_URL`

确认 ffmpeg：

```powershell
ffmpeg -version
ffprobe -version
```

环境自检：

```powershell
python scripts/check_env.py
```

Mock 下核心项应为 **PASS**（ComfyUI / DeepSeek Key 在 Mock 下可跳过）。

---

## 启动

```powershell
cd D:\Develop\aiMusicMV
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8787
```

浏览器打开：http://127.0.0.1:8787

---

## Mock vs Real

### Mock（默认）

```env
MOCK_MODE=true
```

- 词曲：本地模板 JSON（无 Key 也可）
- 音乐：短旋律 WAV
- 出图：渐变 PNG
- 成片：真实 ffmpeg Ken Burns + 字幕烧录

### Real

1. 启动 ComfyUI（默认 `http://127.0.0.1:8188`）
2. 安装 MiniMax Music 3 节点与权重，导出 **API format** workflow，覆盖或对齐：
   - `app/workflows/minimax_music3_api.json`
   - 节点 ID 在 `config.yaml` 的 `music.prompt_node_id` / `music.prompt_input`
3. 出图：将 txt2img API workflow 放到 `app/workflows/txt2img_api.json`，对齐 `txt2img.*` 节点 ID；设置 `IMAGE_CHECKPOINT`
4. `.env`：

```env
MOCK_MODE=false
DEEPSEEK_API_KEY=sk-...
COMFYUI_BASE_URL=http://127.0.0.1:8188
```

5. `python scripts/check_env.py` 全绿后再在 UI 跑真实项目

**验证 ComfyUI API：**

```powershell
curl http://127.0.0.1:8188/system_stats
```

---

## 测试与冒烟

```powershell
pytest -q
python scripts/smoke_test.py
python scripts/e2e_mock_test.py
python scripts/check_env.py
```

DoD：`pytest` 全绿、`smoke_test.py` 退出码 0、Mock 下 `check_env` 核心 PASS。

---

## 使用流程

1. 首页填写主题/风格/画幅/字幕 → **创建并生成词曲 JSON**
2. **卡点①**：编辑分段歌词与 visual_prompt → 确认生成音乐
3. **卡点②**：试听；可「保留词重 roll」或改 `music_description` 后再生成 → 确认生成 MV
4. 结果页播放/下载 MP4；「打开文件夹」查看 `meta.json`、日志等
5. 全局**单任务队列**：第二任务返回 **409**，UI 提示忙碌

状态机：  
`created → generating_lyrics → await_lyrics_review → generating_music → await_music_review → generating_images → assembling → ready | failed`

---

## 目录说明

```
app/           FastAPI + 服务 + HTMX 轻前端 + ComfyUI workflows
scripts/       check_env / smoke_test / e2e_mock_test
tests/         pytest
mocks/         Mock 说明（夹具运行时生成）
```

项目落盘：

```
<PROJECTS_ROOT>/<project_id>/
  meta.json, input.json, creative_vN.json
  audio/vN.wav, images/vN_s*.png
  timeline_vN.json, output/final_vN.mp4
  logs/step_*.request.json | .response.json | .error.txt
```

---

## 验收清单

### MOCK_MODE=true

- [ ] 仅监听 127.0.0.1
- [ ] 新建 → 卡点①改词 → 出音频 → 卡点②可重 roll → 出 MP4 → 可下载播放
- [ ] 字幕默认开，成片可见歌词；关闭后重装成片无字幕
- [ ] 9:16 与 16:9 各一条，分辨率分别为 1080×1920 / 1920×1080
- [ ] 故意错误 ComfyURL（Real 或关 Mock）失败可重试且上游保留，日志可下载

### MOCK_MODE=false

- [ ] `check_env` 全绿
- [ ] 真实生成至少 1 首 ≤ 目标时长的歌 + MV 可播放下载

---

## 常见故障

| 现象 | 处理 |
|------|------|
| 显存不足 / 卡住 | 确认单任务队列；关闭其它占 GPU 进程；勿并行 |
| 8188 未开 | 先启动 ComfyUI；或 `MOCK_MODE=true` |
| JSON 解析失败 | 下载 `logs/step_lyrics_*.response.json`；卡点①可手改后继续 |
| 字幕滤镜 / 字体 | 设置页改为系统已装字体（默认 `Microsoft YaHei`）；确认 ffmpeg 带 libass |
| 端口占用 | 改 `.env` 的 `APP_PORT` |
| D: 不存在 | 自动回退到用户目录；设置页可改 `PROJECTS_ROOT` |

---

## 已知限制（v1）

- 不做全片 I2V、双画幅一次导出、WhisperX 对齐（接口已预留）
- Music3 / 出图依赖你本机 ComfyUI workflow 节点名与 ID，需按 `config.yaml` 映射对齐
- 画面为静帧 Ken Burns，允许粗糙，但端到端可下载
