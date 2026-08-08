# Talk With Anyone

A **local-first voice chat agent**: the entire pipeline runs locally with low hardware requirements — smooth on 8 GB VRAM. You speak → ASR transcribes → LLM replies → TTS reads it aloud. Fully offline-capable. **Mobile-friendly**: once it runs on your PC, open it from a phone/tablet browser on the same network for convenient access anywhere.

**English** | [简体中文](./README.md)

---

## ✨ Features

- 🎙️ **Real-time voice chat (Phone mode)**: full-duplex voice pipeline over WebSocket — low latency, speak-and-reply
- 🧠 **Multiple LLM backends**: local `llama-server` (llama.cpp), `Ollama`, or any **OpenAI-compatible API**
- 🗣️ **Swappable TTS engines**:
  - `edge` — Edge-TTS, free online synthesis, no local model required
  - `moss` — MOSS-TTS-Nano, local multilingual (zh/en/ja) voices (storyteller, radio host, casual banter, etc., 18 voices), supports voice cloning
  - `qwen3` — Qwen3-TTS-12Hz, local multilingual (zh/en/ja/ko) with multiple built-in voices
  - `qwen3-clone` — **voice cloning**: record 5–20 seconds of audio to create a new voice
- 👂 **Local ASR**: SenseVoice Small — 50+ languages (incl. zh/en/ja/ko/Cantonese), voice input & audio-to-text, automatic punctuation, runs on CPU (no GPU needed)
- 🎚️ **Text-to-speech studio**: synthesize text to speech with custom voices for audio/video creation
- 🧬 **Voice cloning & custom voices**: upload/reference audio to generate cloned voices
- 🎭 **Character system**: custom AI characters (system prompt, avatar, name, dedicated voice), one-click switch
- 💬 **Conversation management**: multi-session, full-text search, rename, clear, delete — persisted in SQLite
- 🔍 **Web tools**: web search, current time, weather & news lookups, page fetch, file read/write
- 🌐 **Bilingual UI**: Chinese / English one-click toggle (auto-detects browser language)
- 📱 **Mobile-friendly**: left/right sidebars can be collapsed/expanded with one click and auto-collapse on narrow screens (phones/tablets); the input box wraps and grows with its content; use every feature from a phone/tablet browser
- 📞 **Phone mode**: an immersive voice-call UI with full-duplex real-time conversation; use it from a phone/tablet browser that can reach the server (HTTPS required)
- 🤖 **Auto chat**: start it with a click and the AI keeps chatting on its own to spark novel/script ideas
- 🔊 **Continuous history read-aloud**: start reading from any message and listen continuously

## 🛠 Tech Stack

| Layer | Tech |
| --- | --- |
| Backend | Python 3.10–3.12 · FastAPI · uvicorn · SQLite (built-in `sqlite3`) |
| Frontend | Vanilla HTML / CSS / JavaScript, no build step |
| TTS | edge-tts · onnxruntime (MOSS-TTS-Nano) · faster-qwen3-tts (Qwen3) |
| ASR | funasr + SenseVoice Small |

## 🚀 Quick Start

### 1. Requirements

- Python 3.10 ~ 3.12 (3.12 recommended)
- Works without a GPU using **Edge-TTS + remote/local LLM**;
  local MOSS-TTS-Nano / Qwen3-TTS / SenseVoice are best with an NVIDIA GPU (CUDA).

### 2. Install dependencies

```bash
git clone <repo-url> talk-with-anyone
cd talk-with-anyone

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Install PyTorch (required for Qwen3-TTS / voice cloning)

CUDA build (recommended for GPU users):

```bash
pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu124
pip install torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
```

CPU build (works, but slower):

```bash
pip install torch torchaudio
```

### 4. Create the config

```bash
cp config.example.json config.json   # Windows: copy config.example.json config.json
```

Edit `config.json` as needed (see "Configuration" below).

### 5. Run

```bash
python main.py
```

Open <http://localhost:7862> in your browser. If `tts_engine` is set to `qwen3`, the model is preloaded on startup.

> For users in mainland China, `main.py` automatically falls back to the `hf-mirror.com` mirror for model downloads.

### 📱 Mobile access & microphone (HTTPS)

Mobile browsers only allow the microphone (`getUserMedia`) on a **secure context (HTTPS)**, so accessing the app over `http://IP:7862` from a phone will not enable voice input. Enable HTTPS in two steps:

```bash
python generate_cert.py      # creates a self-signed cert including your LAN IP
python main.py               # starts with HTTPS automatically when cert.pem/key.pem exist
```

- Connect the phone and PC to the same Wi-Fi, then open `https://<PC-LAN-IP>:7862` in the phone browser
- The self-signed cert shows a "connection is not private" warning — tap **Advanced → Proceed**, then allow the microphone
- On the PC itself, also use `https://localhost:7862` (accept the same cert warning)
- Delete `cert.pem` / `key.pem` and restart to go back to plain HTTP

> Use a reasonably recent browser for the microphone. Very old Chrome (e.g. 71 or earlier) does not support the 16 kHz `AudioContext` sample-rate option, so the phone mic stays silent — use up-to-date Chrome, Edge, Safari, Firefox, or your phone's built-in browser.

## ⚙️ Configuration (config.json)

| Field | Description |
| --- | --- |
| `llm_backend` | `local` / `ollama` / `openai` — which LLM backend to use |
| `llm_url` / `llm_api_key` / `llm_model` | Backend URL, API key, model name (`local` uses `llm_profiles.local`) |
| `llm_profiles` | Per-backend presets: `url` / `api_key` / `model` |
| `ai_role_prompt` / `user_role_prompt` | AI persona and user persona prompts |
| `ai_display_name` / `user_name` | Display names in chat |
| `ai_voice` / `user_voice` | Read-aloud voices for AI / user messages |
| `tts_read_ai` / `tts_read_user` | Whether to read AI / user messages aloud |
| `tts_engine` | `edge` / `moss` / `qwen3` / `qwen3-clone` |
| `engine_voices` | Default voice per engine |
| `moss_model_dir` | MOSS-TTS-Nano model directory (ONNX) |
| `qwen3_model_name` | Qwen3-TTS model (HF repo id or local directory) |
| `qwen3_clone_model_name` | Base model for voice cloning (e.g. `Qwen/Qwen3-TTS-12Hz-0.6B-Base`) |
| `qwen3_device` / `qwen3_language` | Qwen3 inference device & language |
| `current_character_id` | Default character id |
| `user_avatar` | User avatar (base64, empty = default) |
| `web_search_enabled` | Enable web search |
| `asr_engine` / `asr_device` | ASR engine & device (default `sensevoice` / `cuda`) |

## 📥 Model Download Guide (optional, local engines only)

All engines except Edge-TTS need a local model. Models are downloaded primarily from **Hugging Face** — just point to an HF repo id and it will be cached on first use. For users in mainland China, `main.py` also enables the `hf-mirror.com` mirror as a fallback.

### MOSS-TTS-Nano (local multilingual zh/en/ja voices, ONNX)

```bash
# Download openmoss/MOSS-TTS-Nano-100M-ONNX to a local folder, e.g.:
# D:/models/MOSS-TTS-Nano/
# Then in config.json:
#   "moss_model_dir": "D:/models/MOSS-TTS-Nano/models/openmoss--MOSS-TTS-Nano-100M-ONNX/snapshots/master"
```

### Qwen3-TTS (multilingual, custom speakers)

```bash
# Default: Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice
# Voice-cloning base model: Qwen/Qwen3-TTS-12Hz-0.6B-Base
# High-end GPU: set env QWEN3_TTS_CLONE_MODEL=Qwen/Qwen3-TTS-12Hz-1.7B-Base
#
# Use an HF repo id (auto-download) or a local directory:
#   "qwen3_model_name": "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
#   "qwen3_clone_model_name": "D:/models/Qwen3-TTS-12Hz-0.6B-Base"
```

### SenseVoice (ASR)

Downloaded automatically by `funasr` (ModelScope source) on first use — no manual setup.

## 📁 Project Layout

```
talk-with-anyone/
├── agent/            # Chat core: LLM calls, conversation context
├── asr/              # Speech recognition (SenseVoice)
├── auto_chat/        # Auto-chat engine
├── routes/           # FastAPI routers (chat / tts / stt / voice / conversations / characters / tools ...)
├── static/           # Frontend pages & assets (vanilla JS, no build)
├── tts/              # Speech synthesis (edge / moss / qwen3 / qwen3-clone / custom voice mgmt)
├── main.py           # Entry point (port 7862)
├── state.py          # Global state (config, TTS/ASR managers, database)
├── models.py         # Data models
├── requirements.txt  # Python dependencies
├── config.example.json / characters.example.json  # Config templates
└── LICENSE
```

## 🤝 FAQ

**Q: Can I chat right after installing dependencies?**
Yes. Default is Edge-TTS + local `http://localhost:8082` (llama-server). Point `llm_backend` at your Ollama or any OpenAI-compatible service instead.

**Q: Torch / CUDA errors?**
Torch is only required when switching to the `qwen3` / `qwen3-clone` engines — install it per step 3 above.

**Q: How do I change the port?**
Edit the port in `uvicorn.run(app, host="0.0.0.0", port=7862)` at the end of `main.py`.

**Q: Slow model downloads / garbled text?**
`main.py` falls back to the `hf-mirror.com` mirror. If issues persist, set `HF_ENDPOINT=https://hf-mirror.com` yourself.

**Q: TTS engines are slow on first use?**
Except for `edge` (cloud synthesis), `moss` / `qwen3` load their models on first use, which takes a while. You can warm them up by synthesizing a short text in the Reading Toolbox on the right sidebar.

**Q: Microphone is slow on first use?**
Scenarios that use the mic (phone mode, voice input) load the speech-recognition model on first use, which also takes some time.

**Q: How do I use auto chat?**
Type a message in the input box and click **Auto Chat**. It stops when you click stop or when the maximum chat rounds are reached.

**Q: How do I read a conversation aloud continuously?**
Right-click a conversation and choose **Read aloud** to read continuously from there until the end, or until you click stop.

**Q: How do I expand/collapse the sidebars on a portrait phone browser?**
Next to the language toggle in the top bar are buttons to expand/collapse the left (◧) and right (◨) sidebars. On portrait phones the sidebars collapse by default to leave the chat full width; tap the button to expand, and tap the dimmed overlay outside the sidebar (or the button again) to collapse.

**Q: How do I rename a character?**
Hover over the character name in the **character selector** dropdown, right-click it, and choose **Rename** from the menu.

**Q: Which voice does the Reading Toolbox use?**
The Reading Toolbox synthesizes with the **character's current voice**, not the user's voice.

**Q: How do I get the best out of a voice?**
Each voice usually suits a particular writing style. To get the best result, match the text style to the voice — both the model's replies and the text you synthesize should fit the style of the chosen voice.

## 📄 License

[MIT](./LICENSE) © wangguanghua

---

> A personal learning project. Respect each model's and dataset's original licenses.
