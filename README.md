# Forte video summarizer

Paste a YouTube link and get a summary you can **read, listen to and explore**: a short TL;DR plus timestamped sections, with the video right next to it. It runs on your own computer, works with **OpenAI or Claude**, and has a **free mode that needs no API key at all**.

- **Studio layout:** your options and the video player on the left; a calm, distraction-free reading column on the right.
- **Click any timestamp** to play the embedded video from that moment (⌘/Ctrl-click opens YouTube in a new tab).
- **Any language in, your language out:** the summary is written directly in the language you pick (12 languages).
- **Listen:** natural-sounding read-aloud powered by [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M), running locally, with a choice of voices and the current line highlighted.
- **Outline, collapsible sections, text size and copy** (as Markdown with timestamp links, or as plain text).
- **Works without captions:** falls back to speech-to-text (local Whisper on Apple Silicon, or OpenAI).
- **Cheap and cached:** the estimated cost is shown under each summary, and repeat visits are free.

## Free or AI summary

Switch between the two at the top of the sidebar.

| | **Free** | **AI summary** |
|---|---|---|
| Cost | Nothing: no AI calls at all | Roughly a cent per video or less, on your own key |
| Needs an API key | No | Yes: OpenAI **or** Anthropic (Claude) |
| What you get | **Key moments**: the most representative parts of the video, picked by a classic ranking algorithm (TextRank) and quoted in the video's own words | A written TL;DR plus sections that cover every point, rewritten clearly |
| Sections | The video's own YouTube chapters, or short time windows | Grouped by topic |
| Language | The video's original language | Any of 12 languages you pick |
| Videos without captions | Not supported | Transcribed with speech-to-text |
| Player, timestamps, outline, read-aloud, copy | ✓ | ✓ |

Free results have a **Get AI summary →** button that switches to AI mode with the same link.

---

## Quick start

### 1. Requirements

| Tool | Why | Install |
|---|---|---|
| **Python 3.12** + [**uv**](https://docs.astral.sh/uv/) | Backend | `brew install uv` (or see uv's docs) |
| **Node.js 20+** | Frontend | `brew install node` |
| **ffmpeg** | Only for videos without captions (speech-to-text) | `brew install ffmpeg` |
| **OpenAI or Anthropic API key** | Only for AI summaries (Free mode works without one) | [OpenAI](https://platform.openai.com/api-keys) · [Anthropic](https://console.anthropic.com/settings/keys) |

macOS (Apple Silicon recommended) and Linux both work. Local speech-to-text (`STT_ENGINE=local`) needs Apple Silicon; elsewhere use `STT_ENGINE=openai`.

### 2. Clone

```bash
git clone git@github.com:svashisht-cloud/ForteVideoSummarizer.git
cd ForteVideoSummarizer
```

### 3. Start the backend

```bash
cd backend
cp .env.example .env        # optional: paste OPENAI_API_KEY and/or ANTHROPIC_API_KEY (or enter keys in the app)
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

1. **First visit:** a welcome screen asks how you'd like to summarize. Pick **Free** or **AI summary**. For AI, choose OpenAI or Claude and paste your key; it's checked with a free call and remembered on this device. The link bar then moves to the sidebar, and the right side shows how to copy a YouTube link (or try an example). Later you can switch at the top of the sidebar, or press **?** to see the welcome again.
2. Paste a YouTube link (`youtube.com/watch?v=…`, `youtu.be/…`, Shorts and live links all work).
3. In AI mode, pick the summary language and model. Then press **Get key moments** or **Summarize**.
4. Read on the right, click timestamps to jump around the video, or press **Listen**.

> **First run:** the first time you press **Listen**, the Kokoro voice model (~350 MB) downloads automatically into `backend/.cache/models/`. The first video without captions downloads the Whisper model, too.

---

## Configuration

Backend settings live in `backend/.env` (copied from `.env.example`). This file is git-ignored; never commit it.

| Variable | Default | What it does |
|---|---|---|
| `OPENAI_API_KEY` | — | Server-side OpenAI key for summaries (and OpenAI speech-to-text). Optional: users can enter their own in the app. |
| `ANTHROPIC_API_KEY` | — | Server-side Anthropic key for Claude models. Optional, as above. |
| `ANTHROPIC_MODEL` | `claude-opus-5-5` | Default Claude model. |
| `OPENAI_MODEL` | `gpt-6.1-terra` | Default summary model. Users can pick another one in the app. |
| `STT_ENGINE` | `local` | Speech-to-text for videos without captions: `local` (mlx-whisper, Apple Silicon) or `openai`. |
| `OPENAI_STT_MODEL` | `whisper-1` | OpenAI transcription model when `STT_ENGINE=openai`. |
| `REQUIRE_USER_KEY` | `false` | For a shared or hosted server: `true` makes people enter **their own** OpenAI or Claude key in the app. |

Frontend: `frontend/.env` can set `VITE_API_URL` (default `http://localhost:8000`).

**Models and cost.** In AI mode, pick a provider and a model: **OpenAI** (GPT-6 Luna, GPT-6.1 Terra, GPT-6.1 Sol, GPT-6 Astra) or **Claude** (Haiku 5.5, Sonnet 5.5, Opus 5.5). Each shows its price. A typical 5–10 minute video costs well under one cent on Terra. Prices are kept in `backend/app/pipeline/pricing.py`.

**Your own key.** Keys are kept per provider in your browser (remembered on this device unless you untick it) and shown masked, with **Change** and **Forget**. A key is sent only to your backend with each request and is never stored, logged or cached there. If the backend has its own key for a provider, the app uses it unless you add yours.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| **"YouTube is blocking requests from this network"** | YouTube blocks many cloud, VPN and datacenter IPs. Try from a home network, or route captions through a proxy (see `get_transcript` in `backend/app/pipeline/transcript.py`). |
| **"Can't reach the server"** in the app | Is the backend running on port 8000? Did you open `localhost:5173`, not `127.0.0.1`? |
| **"OPENAI_MODEL is not set"** or **"API key was rejected"** | Check `backend/.env`, then restart the backend. |
| **Read-aloud uses a robotic voice** | That's the device fallback, used for German, Korean, Arabic, Russian and Japanese, or when the backend can't generate speech. |
| **Speech-to-text fails on Linux/Intel** | Set `STT_ENGINE=openai` in `backend/.env`. |
| **"Free mode only uses captions"** | The video has no captions. Use AI summary, which transcribes the audio. |

---

## Project layout

```
backend/                 FastAPI + the summarizing pipeline (Python, uv)
  app/pipeline/          URL parsing, captions, speech-to-text, summarizing, read-aloud, cache
  app/api/main.py        HTTP API: /jobs, /models, /tts
  scripts/               Small scripts to try pieces by hand (summary, captions, voices)
  tests/                 pytest (no network: OpenAI, Claude and YouTube are faked)
frontend/                Vite + React + TypeScript + Tailwind
  src/components/        Sidebar, reader, toolbar, read-aloud, player
```

How it works: **Free**: URL → captions → ~30 s blocks → TextRank picks the key blocks per chapter. **AI**: URL → captions (or speech-to-text) → ~30 s blocks → ~12 min chunks summarized in parallel → merged into a TL;DR + sections → shown in the reader. More detail, and the design decisions, are in [`CLAUDE.md`](CLAUDE.md).

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
