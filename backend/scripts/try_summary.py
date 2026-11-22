"""Get a transcript (captions, else speech-to-text), summarize, and print the result.

Usage: uv run --env-file .env python scripts/try_summary.py <url> <lang> [--no-cache]
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import cache  # noqa: E402
from app.pipeline.errors import PipelineError  # noqa: E402
from app.pipeline.normalize import chunk, format_ts, normalize  # noqa: E402
from app.pipeline.summarize import PROMPT_VERSION, resolve_model, summarize  # noqa: E402
from app.pipeline.transcript import get_transcript  # noqa: E402
from app.pipeline.url import parse_video_id  # noqa: E402


class StageTimer:
    """Records when each stage starts, so stage durations can be reported."""

    def __init__(self):
        self.starts: dict[str, float] = {}
        self.order: list[str] = []

    def __call__(self, stage: str) -> None:
        self.starts[stage] = time.perf_counter()
        self.order.append(stage)
        print(f"  … {stage}", file=sys.stderr, flush=True)

    def duration(self, stage: str, end: float) -> float | None:
        if stage not in self.starts:
            return None
        i = self.order.index(stage)
        nxt = self.starts[self.order[i + 1]] if i + 1 < len(self.order) else end
        return nxt - self.starts[stage]


def on_progress(stage: str, done: int, total: int) -> None:
    print(f"  … {stage} {done}/{total}", file=sys.stderr, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("url")
    ap.add_argument("lang")
    ap.add_argument("--no-cache", action="store_true", help="ignore and overwrite cached transcript and summary")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "openai", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    stages = StageTimer()
    t0 = time.perf_counter()
    try:
        video_id = parse_video_id(args.url)
        segments, language, source = get_transcript(video_id, stages, use_cache=not args.no_cache)
        t_transcript = time.perf_counter()
        blocks = normalize(segments)
        chunks = chunk(blocks)

        model = resolve_model()
        summary = None if args.no_cache else cache.load_summary(video_id, args.lang, model, PROMPT_VERSION)
        hit = summary is not None
        if summary is None:
            summary = asyncio.run(summarize(segments, args.lang, on_progress, model=model))
            cache.save_summary(video_id, args.lang, summary, model, PROMPT_VERSION)
    except PipelineError as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    t_end = time.perf_counter()

    transcribing = stages.duration("transcribing", t_transcript)
    downloading = stages.duration("downloading_audio", t_transcript)
    print(f"video id:      {video_id}")
    print(f"source:        {source}" + (f" (STT_ENGINE={os.environ.get('STT_ENGINE', 'local')})" if source.startswith("stt") else ""))
    print(f"transcript:    {language}, {len(segments)} segments -> {len(blocks)} blocks, ends {format_ts(blocks[-1].end)}")
    if not stages.order:
        print("transcript t:  cached")
    else:
        print(f"transcript t:  {t_transcript - t0:.1f}s total", end="")
        if downloading is not None:
            print(f" (download {downloading:.1f}s, transcription {transcribing:.1f}s)", end="")
        print()
    print(f"chunks:        {len(chunks)} ({'single call' if len(chunks) == 1 else 'map-reduce'})")
    print(f"summary:       {'cached' if hit else f'{t_end - t_transcript:.1f}s'} ({model}, prompts v{PROMPT_VERSION})")
    print(f"total time:    {t_end - t0:.1f}s")
    print()
    print("TL;DR:", summary.tldr)
    for s in summary.sections:
        print(f"\n[{format_ts(s.start)}–{format_ts(s.end)}] {s.title}")
        for p in s.points:
            print(f"    [{format_ts(p.t)}] {p.text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
