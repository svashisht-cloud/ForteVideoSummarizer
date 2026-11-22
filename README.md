# Forte video summarizer

Paste a YouTube link, pick a language, and get a summary you can **read, listen to and explore**: a short TL;DR plus timestamped sections that keep every distinct point from the video. It runs on your own computer.

- **Studio layout:** your options and the video player on the left; a calm, distraction-free reading column on the right.
- **Click any timestamp** to play the embedded video from that moment (⌘/Ctrl-click opens YouTube in a new tab).
- **Any language in, your language out:** the summary is written directly in the language you pick (12 languages).
- **Listen:** natural-sounding read-aloud powered by [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), running locally, with a choice of voices and the current line highlighted.
- **Outline, collapsible sections, text size and copy** (as Markdown with timestamp links, or as plain text).
- **Works without captions:** falls back to speech-to-text (local Whisper on Apple Silicon, or OpenAI).
- **Cheap and cached:** the estimated cost is shown under each summary, and repeat visits are free.

---

## Quick start

### 1. Requirements

| Tool | Why | Install |
|---|---|---|
| **Python 3.12** + [**uv**](https://docs.astral.sh/uv/) | Backend | `brew install uv` (or see uv's docs) |
| **Node.js 20+** | Frontend | `brew install node` |
| **ffmpeg** | Only for videos without captions (speech-to-text) | `brew install ffmpeg` |
| **OpenAI API key** | AI summaries | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |

macOS (Apple Silicon recommended) and Linux both work. Local speech-to-text (`STT_ENGINE=local`) needs Apple Silicon; elsewhere use `STT_ENGINE=openai`.

### 2. Clone

```bash
git clone git@github.com:svashisht-cloud/ForteVideoSummarizer.git
cd ForteVideoSummarizer
```

### 3. Start the backend

```bash
cd backend
cp .env.example .env        # then open .env and paste your OPENAI_API_KEY
uv sync                     # installs Python and all dependencies
uv run --env-file .env uvicorn app.api.main:app --reload
```

The API runs at http://localhost:8000 (interactive docs at http://localhost:8000/docs).

### 4. Start the frontend (in a second terminal)

```bash
cd frontend
npm install
npm run dev
```

### 5. Use it

Open **http://localhost:5173**. Use `localhost`, not `127.0.0.1`: the backend only accepts requests from that address.

1. Paste a YouTube link (`youtube.com/watch?v=…`, `youtu.be/…`, Shorts and live links all work).
2. Pick the summary language and model, then press **Summarize**.
3. Read on the right, click timestamps to jump around the video, or press **Listen**.

> **First run:** the first time you press **Listen**, the Kokoro voice model (~350 MB) downloads automatically into `backend/.cache/models/`. The first video without captions downloads the Whisper model, too.

---

## Configuration

Backend settings live in `backend/.env` (copied from `.env.example`). This file is git-ignored; never commit it.

| Variable | Default | What it does |
|---|---|---|
| `OPENAI_API_KEY` | — | Your OpenAI key, used for summaries (and OpenAI speech-to-text). |
| `OPENAI_MODEL` | `gpt-6.1-terra` | Default summary model. Users can pick another one in the app. |
| `STT_ENGINE` | `local` | Speech-to-text for videos without captions: `local` (mlx-whisper, Apple Silicon) or `openai`. |
| `OPENAI_STT_MODEL` | `whisper-1` | OpenAI transcription model when `STT_ENGINE=openai`. |
| `REQUIRE_USER_KEY` | `false` | For a shared or hosted server: `true` makes people enter **their own** OpenAI key in the app. |

Frontend: `frontend/.env` can set `VITE_API_URL` (default `http://localhost:8000`).

**Models and cost.** The app offers GPT-6 Luna, GPT-6.1 Terra, GPT-6.1 Sol and GPT-6 Astra, and shows each one's price. A typical 5–10 minute video costs well under one cent on Terra. Prices are kept in `backend/app/pipeline/pricing.py`.

**Your own key.** Under **Use your own OpenAI API key** you can paste a key. It's sent only to your backend for that request and is never stored on the server.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| **"YouTube is blocking requests from this network"** | YouTube blocks many cloud, VPN and datacenter IPs. Try from a home network, or route captions through a proxy (see `get_transcript` in `backend/app/pipeline/transcript.py`). |
| **"Can't reach the server"** in the app | Is the backend running on port 8000? Did you open `localhost:5173`, not `127.0.0.1`? |
| **"OPENAI_MODEL is not set"** or **"API key was rejected"** | Check `backend/.env`, then restart the backend. |
| **Read-aloud uses a robotic voice** | That's the device fallback, used for German, Korean, Arabic, Russian and Japanese, or when the backend can't generate speech. |
| **Speech-to-text fails on Linux/Intel** | Set `STT_ENGINE=openai` in `backend/.env`. |

---

## Project layout

```
backend/                 FastAPI + the summarizing pipeline (Python, uv)
  app/pipeline/          URL parsing, captions, speech-to-text, summarizing, read-aloud, cache
  app/api/main.py        HTTP API: /jobs, /models, /tts
  scripts/               Small scripts to try pieces by hand (summary, captions, voices)
  tests/                 pytest (no network: OpenAI and YouTube are faked)
frontend/                Vite + React + TypeScript + Tailwind
  src/components/        Sidebar, reader, toolbar, read-aloud, player
```

How it works: URL → captions (or speech-to-text) → ~30 s blocks → ~12 min chunks summarized in parallel → merged into a TL;DR + sections → shown in the reader. More detail, and the design decisions, are in [`CLAUDE.md`](CLAUDE.md).

## Running the tests

```bash
cd backend && uv run pytest
cd frontend && npm test && npm run build && npm run lint
```

Try pieces by hand:

```bash
cd backend
uv run --env-file .env python scripts/try_summary.py "https://youtu.be/<id>" en
uv run python scripts/try_tts.py en "Hello from Forte." af_heart
```
