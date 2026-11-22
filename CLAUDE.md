# YouTube Summarizer

Paste a YouTube URL, pick a language, get a summary in that language: a 2–3 sentence TL;DR plus timestamped sections that keep every distinct point from the video. Runs locally on macOS (Apple Silicon, M4 Pro). Built one step at a time from PROMPTS.md.

## Pipeline

```
URL → video ID → transcript segments → normalize (~30s blocks) → chunk (~12 min)
    → map: points per chunk (parallel) → merge: TL;DR + sections → API → React UI
```

## Decisions (do not change without asking me)

**Running**
- Local first, deploy later. All transcript fetching goes through one function, `get_transcript(video_id)`, so the fetcher can be swapped for a proxy or hosted API at deploy time.

**Transcript**
- Captions first (`youtube-transcript-api`). Fall back to speech-to-text **only** when the video has no captions.
- If YouTube blocks the request (`RequestBlocked` / `IpBlocked`), raise a clear `YouTubeBlocked` error. Do **not** fall back: yt-dlp will usually be blocked too.
- Picking a caption track: the auto-generated track's language is the spoken language. Prefer a human-made track in that language, else the auto-generated one. If no auto-generated track exists, use the first human-made track. Never use YouTube's caption translation.
  - Auto-dubbed videos have one auto-generated track per dub language. When there's more than one auto-generated track, get the original language from yt-dlp metadata (`video_language`, no download) and use that track. A blocked lookup raises `YouTubeBlocked`.
- Speech-to-text: audio-only download with `yt-dlp`, then one interface `transcribe(audio_path) -> (list[Segment], language)` with two engines picked by the `STT_ENGINE` env var:
  - `local`: `mlx-whisper`, model `mlx-community/whisper-large-v3-turbo`
  - `openai`: OpenAI transcription API. Use a current, non-deprecated model that returns segment timestamps. Compress audio (mono, low bitrate) to fit the upload limit; split and offset timestamps if still too big.
    - Model comes from `OPENAI_STT_MODEL` (default `whisper-1`). As of 2026-11, `gpt-transcribe` is the only non-deprecated model but returns text only (rejects `verbose_json`/`srt`/`vtt`), so `whisper-1` with `verbose_json` is used. `whisper-1` shuts down 2027-02-26: revisit before then.

**Segments**
- `Segment(start: float, end: float, text: str)`: a Pydantic model, times in seconds, validated (`end >= start`, non-empty text after stripping).
- `normalize(segments, window=30.0)` merges consecutive raw segments into ~30s blocks. Format times as `m:ss` / `h:mm:ss` only for display and prompts.

**Translation**
- No separate translation step. The LLM reads the original-language transcript and writes the summary directly in the target language.

**LLM**
- OpenAI or Anthropic (Claude), chosen by the model. Every LLM call goes through `llm.py` (`OpenAILLM`: Responses API + `text_format`; `AnthropicLLM`: Messages API + `output_format`, effort `medium`, streamed) behind `summarize(segments, target_lang, on_progress=None)`. Check each SDK's installed API before changing calls.
- The user picks the model in the UI from the allowlist in `pricing.py` (`PRICES`, each with a `provider`: GPT-6 Luna, GPT-6.1 Terra, GPT-6.1 Sol, GPT-6 Astra; Claude Haiku 5.5, Sonnet 5.5, Opus 5.5). Defaults: `OPENAI_MODEL`, and `ANTHROPIC_MODEL` (default `claude-opus-5-5`); `OPENAI_MODEL` is always allowed. Add a model only after checking it with `models.list()` and a structured-output call.
- Token usage from every LLM call is summed into `Summary.usage` (cached with the summary) and priced from `PRICES` (USD per 1M tokens). A model with no price shows tokens with no dollar figure. Speech-to-text cost isn't included.
- Users may send their own key for the model's provider in the `X-LLM-Key` header (`X-OpenAI-Key` still accepted). It is used only to build that job's clients and is never stored, logged, cached, or returned; an OpenAI key also powers OpenAI speech-to-text. A key is required (for anything that isn't a full cache hit) when `REQUIRE_USER_KEY=true` or the server has no key for that provider (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`). `POST /keys/check` validates a key with a free `models.list` call. Never put a key in a URL.
- The frontend keeps keys per provider in `localStorage` by default (opt out: session only) and shows a first-visit welcome (Free vs AI cards, key step for AI when needed) before the Studio; the link bar moves into the sidebar with a View Transition.
- Structured outputs with Pydantic models. The LLM returns timestamps as the **exact `m:ss` string** from the `[m:ss]` markers it was given; code parses them to seconds and snaps each one to the nearest block start.

**Free mode (no AI)**
- `mode: "free"` on `POST /jobs`: captions only (`get_transcript(allow_stt=False)` raises `CaptionsRequired`), no LLM, no key, ignores `REQUIRE_USER_KEY`.
- Key moments: TextRank over the normalized blocks (`extract.py`: TF-IDF + cosine graph + PageRank, char bigrams for zh/ja), quoted in the original language. Sections are the YouTube chapters (yt-dlp metadata, cached) when there are 2+, else windows of `duration/6` clamped to 1–5 min. Same `Summary` shape with `method="extractive"`.
- Bump `EXTRACT_VERSION` whenever the algorithm or its settings change.
- The UI defaults to Free on first visit; free results offer "Get AI summary".

**Long videos: map-reduce**
- Chunks of ~12 minutes of normalized blocks, no overlap.
- Map: one call per chunk → `ChunkPoints { points: [{ts, text}] }`. Run in parallel, max 4 concurrent.
- Merge: one call → `Summary { tldr, sections: [{title, start, end, points: [{t, text}]}] }`. It groups points by topic, keeps chronological order, removes duplicates across chunks, and keeps every distinct point.
- If there is only one chunk, make a single call that returns the `Summary` shape directly (no merge).
- Log a warning if any chunk returns zero points.

**Storage**
- Cache as JSON files in `backend/.cache/`: transcripts keyed by `video_id`, summaries by `(video_id, lang, model)` (file `{video_id}.{lang}.{model}.json`; free ones are `{video_id}.orig.extractive.json`, versioned by `EXTRACT_VERSION`). Video metadata (title, language, chapters) in `metadata/{video_id}.json`.
- Each cached summary records the model and `PROMPT_VERSION` (in `summarize.py`) that made it. A mismatch is a cache miss and the file is overwritten. Bump `PROMPT_VERSION` whenever prompts or post-processing change.

**API (FastAPI)**
- `GET /models` → `{default, require_user_key, models: [{id, label, input, cached_input, output, cached_is_estimate}]}`.
- `POST /jobs {url, lang, model?}` (optional `X-OpenAI-Key` header) → `{job_id}`. Returns 400 on a bad URL, an unknown model, or a missing key when `REQUIRE_USER_KEY` is set.
- `GET /jobs/{id}` → `{status, stage, progress, result, error}`
  - status: `queued | running | done | error`
  - stage: `fetching_captions | downloading_audio | transcribing | summarizing | merging`
  - progress: `{done, total}` while summarizing
  - result: summary, normalized transcript blocks, video_id, language, source (`captions | stt-local | stt-openai`)
- Jobs run as background tasks, kept in memory. Run blocking work (yt-dlp, mlx-whisper) with `asyncio.to_thread`.
- CORS allows the Vite dev server origin (`http://localhost:5173`).

**Frontend**
- Vite + React + TypeScript + Tailwind in `frontend/`. Polls the job every 1s.
- "Studio" layout: left pane (options form, then an embedded YouTube player + outline), right pane = reading column with a sticky toolbar (Summary/Transcript, Listen, A−/A+, Collapse, Copy as Markdown/text). Below 1024px the panes stack.
- Timestamps are links to `https://www.youtube.com/watch?v=<id>&t=<seconds>s`; a plain click seeks the embedded player instead (YouTube IFrame API, `youtube-nocookie.com` host), ⌘/Ctrl-click opens the link.
- Read aloud: one clip per TL;DR / section title / point (`src/speech.ts`), with the current part highlighted.
  - Natural voice: **Kokoro-82M** (Apache 2.0) on the backend via `kokoro-onnx`, phonemes from `misaki` for English and Chinese (espeak sounds robotic there) and espeak for es/fr/hi/it/pt. `POST /tts {text, lang, voice?}` → WAV, cached in `backend/.cache/audio/`. Model files (~350 MB) download once to `backend/.cache/models/kokoro/`. The frontend prefetches the next 2 clips; speed is `playbackRate` client-side.
  - Users pick a voice from a shortlist per language (`tts.LANGUAGES`, default first), with a preview; the choice is remembered per language.
  - German, Korean, Arabic, Russian and Japanese (espeak can't read kanji) use the browser voice, which is also the fallback if `/tts` fails.

**Branding**
- Product name: **Forte video summarizer**. The header is "forte" (Sora 600) / "video summarizer", as in Forte Resume Builder (`resume-builder/components/PublicHeader.tsx`).
- Colors: light "Paper" (Forte paper `#F7F6F3`, serif Literata for reading) and dark "Calm charcoal" (Inter), with Forte periwinkle only for interactive things. CSS variables in `frontend/src/index.css`, mapped to Tailwind (`bg-background`, `bg-sidebar`, `text-muted`, `text-dim`, `bg-accent`, `font-reading`, …). Light/dark follows the system. Use the tokens, not raw Tailwind colors.
- Fonts: Inter (body), Sora (wordmark), JetBrains Mono (timestamps). Favicons: `public/brand/forte-icon-sora-{dark,light}.svg`, copied from Resume Builder.

## Conventions

- Python is managed with `uv` inside `backend/`. Add deps with `uv add`. Run things with `uv run --env-file .env ...`.
- Secrets live in `backend/.env` (`OPENAI_API_KEY`, `OPENAI_MODEL`, `STT_ENGINE`). Never commit `.env`. Keep `backend/.env.example` up to date.
- `app/pipeline/` must never import from `app/api/`. The pipeline works without FastAPI.
- Pure functions (URL parsing, normalize, chunk, timestamp formatting/parsing) get pytest tests, written before the code. Unit tests never hit the network; mock the OpenAI client.
- Network and LLM code is checked with small scripts in `backend/scripts/`.
- Library APIs change. Check the installed version's actual API (`youtube-transcript-api` v1.x uses instance methods; the OpenAI SDK's structured-output method) instead of relying on memory.
- Work one build step at a time. When a step's check passes, stop and summarize what changed and how to run it.

## Layout

```
backend/
  app/
    pipeline/
      models.py       # Segment, ChunkPoints, Summary
      url.py          # parse_video_id
      normalize.py    # normalize, chunk, format_ts, parse_ts, to_prompt_text
      captions.py     # fetch_captions
      stt.py          # download_audio, transcribe engines
      transcript.py   # get_transcript: captions → fallback
      summarize.py    # map / merge orchestration
      llm.py          # OpenAI + Claude adapters, key check
      tts.py          # Kokoro text-to-speech, voice shortlist
      extract.py      # free mode: TextRank key moments
      cache.py
      errors.py       # NoCaptions, YouTubeBlocked, VideoUnavailable, InvalidURL
    api/
      main.py
  scripts/
  tests/
frontend/
```
