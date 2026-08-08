# Talk With Anyone · 跟谁都能聊，万物皆可语

本地优先的语音聊天智能体：可实现全流程本地运行，硬件配置要求低，8G 显存即可流畅运行。支持移动端适配——电脑启动项目后，手机/平板浏览器即可访问，使用更便利。

[English](./README.en.md) | **简体中文**

---

## ✨ 功能特性

- 🎙️ **电话模式的实时语音对话**：基于 WebSocket 的全双工语音链路，延迟低
- 🧠 **多 LLM 后端**：本地 `llama-server`（llama.cpp）、`Ollama`、以及任意 **OpenAI 兼容 API**
- 🗣️ **多 TTS 引擎，可随时切换**：
  - `edge` — Edge-TTS，免费在线合成，无需本地模型
  - `moss` — MOSS-TTS-Nano，本地多语种多音色（说书、电台、胡同闲聊等 18 种），支持音色克隆
  - `qwen3` — Qwen3-TTS-12Hz，本地多语种（中/英/日/韩），多音色
  - `qwen3-clone` — **声音克隆**，5–20 秒音频即可克隆出新音色
- 👂 **本地 ASR**：SenseVoice Small，支持中英日韩粤语等 50+ 语种识别，支持语音输入文本、音频转文本，自动标点；CPU 运行，不依赖显卡
- 🎚️ **本地 TTS（文本合成语音）**：支持自定义音色合成语音，让音频、视频创作更加得心应手
- 🧬 **声音克隆与自定义音色**：上传/录制参考音频，实时生成克隆声音
- 🎭 **角色系统**：自定义 AI 角色（人设 prompt、头像、名字、专属声音），一键切换，体验talk with anyone
- 💬 **会话管理**：多会话、全文搜索、重命名、清空、删除，SQLite 本地持久化
- 🔍 **联网工具**：网页搜索、当前时间、天气查询、新闻事件查询
- 🌐 **双语界面**：中文 / English 一键切换（含浏览器语言自动检测）
- 📱 **移动端适配**：左右侧边栏可一键收起/展开，窄屏（手机/平板）自动收起，界面自动换行、随内容增高的输入框；手机/平板浏览器访问服务器即可使用全部功能
- 📞 **电话模式**：沉浸式语音通话界面，点击即开启全双工实时对话；手机/平板浏览器访问服务器即可使用（需 HTTPS）
- 🤖 **AI 自聊**：输入内容一键启动，AI 自动持续对话，为小说、剧本创作提供灵感
- 🔊 **历史对话连续朗读**：从任意一条消息开始连续朗读，沉浸式重温历史对话

## 🛠 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.10–3.12 · FastAPI · uvicorn · SQLite（内置 `sqlite3`） |
| 前端 | 原生 HTML / CSS / JavaScript，无构建步骤 |
| TTS | edge-tts · onnxruntime（MOSS-TTS-Nano）· faster-qwen3-tts（Qwen3） |
| ASR | funasr + SenseVoice Small |

## 🚀 快速开始

### 1. 环境要求

- Python 3.10 ~ 3.12（推荐 3.12）
- 只要「Edge-TTS + 远程/本地 LLM」即可无 GPU 运行；
  使用本地 MOSS-TTS-Nano / Qwen3-TTS / SenseVoice 建议配备 NVIDIA GPU（CUDA）。

### 2. 安装依赖

```bash
git clone <仓库地址> talk-with-anyone
cd talk-with-anyone

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. 安装 PyTorch（使用 Qwen3-TTS / 声音克隆时需要）

CUDA 版（推荐 GPU 用户）：

```bash
pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124
pip install torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
```

CPU 版（能跑，但较慢）：

```bash
pip install torch torchaudio
```

### 4. 创建配置

```bash
cp config.example.json config.json   # Windows: copy config.example.json config.json
```

按需修改 `config.json`（字段见下方「配置说明」）。

### 5. 启动

```bash
python main.py
```

浏览器打开 <http://localhost:7862>。启动时若配置为 `qwen3` 引擎会自动预加载模型。

> 国内网络会自动使用 `hf-mirror.com` 镜像下载模型（`main.py` 已内置设置）。

### 📱 手机访问 & 麦克风（HTTPS）

手机浏览器要求麦克风（`getUserMedia`）必须在 **HTTPS** 下才能调用，局域网内通过 `http://IP:7862` 访问时无法使用语音功能。启用 HTTPS 只需两步：

```bash
python generate_cert.py      # 生成本机自签证书（自动包含局域网 IP）
python main.py               # 检测到 cert.pem/key.pem 后自动以 HTTPS 启动
```

- 手机与电脑连同一 WiFi，浏览器打开 `https://<本机局域网IP>:7862`
- 自签名证书会提示"不是私密连接"，点 **高级 → 继续前往** 即可；之后授权麦克风
- 电脑本机也用 `https://localhost:7862` 访问（同样接受证书提示）
- 删除 `cert.pem` / `key.pem` 后重启即回到纯 HTTP

> 麦克风需使用较新的浏览器。很老的 Chrome（如 71 及更早）不支持 `AudioContext` 的 16kHz 采样率选项，手机麦克风会无声无响应——请使用新版 Chrome、Edge、Safari、Firefox 或手机自带浏览器。

## ⚙️ 配置说明（config.json）

| 字段 | 说明 |
| --- | --- |
| `llm_backend` | `local` / `ollama` / `openai`，切换 LLM 后端 |
| `llm_url` / `llm_api_key` / `llm_model` | 后端地址、密钥、模型名（`local` 走 `llm_profiles.local`） |
| `llm_profiles` | 各后端预设：`url` / `api_key` / `model` |
| `ai_role_prompt` / `user_role_prompt` | AI 人设与用户人设 prompt |
| `ai_display_name` / `user_name` | 对话显示名 |
| `ai_voice` / `user_voice` | AI 与用户各自的朗读声音 |
| `tts_read_ai` / `tts_read_user` | 是否朗读 AI / 用户消息 |
| `tts_engine` | `edge` / `moss` / `qwen3` / `qwen3-clone` |
| `engine_voices` | 每个引擎默认使用的音色 |
| `moss_model_dir` | MOSS-TTS-Nano 模型目录（ONNX） |
| `qwen3_model_name` | Qwen3-TTS 模型（HF 仓库名或本地目录） |
| `qwen3_clone_model_name` | 声音克隆基础模型（如 `Qwen/Qwen3-TTS-12Hz-0.6B-Base`） |
| `qwen3_device` / `qwen3_language` | Qwen3 推理设备与语言 |
| `current_character_id` | 默认角色 ID |
| `user_avatar` | 用户头像（base64，留空则使用默认） |
| `web_search_enabled` | 是否启用联网搜索 |
| `asr_engine` / `asr_device` | ASR 引擎与设备（默认 `sensevoice` / `cuda`） |

## 📥 语音模型下载指引（可选，默认均为本地路径）

除 Edge-TTS 外，本地引擎需先下载模型。以下仓库均可通过 Hugging Face 下载；
`main.py` 已默认启用 `hf-mirror.com` 镜像，直接指定 HF 仓库名即可自动缓存下载。

### MOSS-TTS-Nano（中英日多语种多音色，ONNX）

```bash
# 下载 openmoss/MOSS-TTS-Nano-100M-ONNX 到本地目录，例如：
# D:/models/MOSS-TTS-Nano/
# 然后 config.json 中设置：
#   "moss_model_dir": "D:/models/MOSS-TTS-Nano/models/openmoss--MOSS-TTS-Nano-100M-ONNX/snapshots/master"
```

### Qwen3-TTS（多语种，含自定义说话人）

```bash
# 普通使用（默认）：Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice
# 声音克隆基础模型：Qwen/Qwen3-TTS-12Hz-0.6B-Base
# 高配可换 1.7B：环境变量 QWEN3_TTS_CLONE_MODEL=Qwen/Qwen3-TTS-12Hz-1.7B-Base
#
# 可指定 HF 仓库名（自动下载）或本地目录：
#   "qwen3_model_name": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
#   "qwen3_clone_model_name": "D:/models/Qwen3-TTS-12Hz-0.6B-Base"
```

### SenseVoice（ASR 语音识别）

由 `funasr` 自动下载（ModelScope 源），首次识别时自动拉取，无需手动配置。

## 📁 目录结构

```
talk-with-anyone/
├── agent/            # 对话核心：LLM 调用、会话上下文管理
├── asr/              # 语音识别（SenseVoice）
├── auto_chat/        # 自动聊天引擎
├── routes/           # FastAPI 路由（chat / tts / stt / voice / conversations / characters / tools ...）
├── static/           # 前端页面与资源（原生 JS，无需构建）
├── tts/              # 语音合成（edge / moss / qwen3 / qwen3-clone / 自定义音色管理）
├── main.py           # 入口（端口 7862）
├── state.py          # 全局状态（配置、TTS/ASR 管理器、数据库）
├── models.py         # 数据模型
├── requirements.txt  # Python 依赖
├── config.example.json / characters.example.json  # 配置模板
└── LICENSE
```

## 🤝 常见问题

**Q：只装依赖后能直接聊吗？**
能。默认 Edge-TTS + 本地 `http://localhost:8082`（llama-server）。把 `llm_backend` 指向你的 Ollama 或任意 OpenAI 兼容服务即可。

**Q：提示缺少 torch / CUDA 相关报错？**
只在切换到 `qwen3` / `qwen3-clone` 引擎时才需要 torch，按上文第 3 步安装即可。

**Q：如何修改端口？**
改 `main.py` 末尾 `uvicorn.run(app, host="0.0.0.0", port=7862)` 中的端口号。

**Q：中文乱码 / 模型下载慢？**
`main.py` 已内置 `hf-mirror.com` 镜像；如仍有问题，可自行设置环境变量 `HF_ENDPOINT=https://hf-mirror.com`。

**Q：TTS 引擎首次使用速度慢？**
除 `edge` 为云端在线合成外，`moss` / `qwen3` 首次使用时需要加载模型，会有一段等待时间。可在右侧边栏朗读工具箱输入短文本点击朗读，完成首次加载。

**Q：麦克风首次使用速度慢？**
涉及麦克风的场景（电话模式、语音输入）中，语音识别引擎首次使用也需要加载模型，需要一定等待时间。

**Q：AI 自聊如何使用？**
在输入框输入内容后点击「AI 自聊」即可启动；可手动停止，或达到最大聊天轮次后自动停止。

**Q：历史对话如何连续语音朗读？**
选择一条对话，鼠标右键点击「朗读」，即可从这条对话开始连续朗读，直到对话结束或点击停止朗读。

**Q：手机竖屏浏览器如何展开/收起左右侧边栏？**
顶栏右侧、中英文语言切换按钮旁边，有左右侧边栏的展开/收起按钮（◧ 左栏 / ◨ 右栏）。竖屏时侧栏默认收起，为聊天区留出完整宽度；点击按钮即可展开，展开后点击侧栏外侧的半透明遮罩（或再次点击按钮）即可收起。

**Q：角色如何重命名？**
将鼠标悬停在「角色选择」下拉框的角色名称上，右键点击，在菜单中选择「重命名」即可。

**Q：朗读工具箱的朗读音色是什么？**
朗读工具箱合成语音时使用的是**角色当前音色**，而非用户音色。

**Q：如何发挥音色的最佳效果？**
每种音色通常都有与之契合的文字风格。要发挥最佳效果，需要让文字风格与音色相匹配——无论是模型回复的文字内容，还是待合成语音的文字，都应尽量贴合所选音色的风格。

## 📄 License

[MIT](./LICENSE) © wangguanghua

---

> 本项目为个人学习项目，模型与数据请遵守各自原始 License。
