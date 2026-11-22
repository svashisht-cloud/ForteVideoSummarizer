"""Speak a sentence with Kokoro, save it as a WAV and print timings.

Usage: uv run python scripts/try_tts.py <lang> "<text>" [voice] [--out file.wav]
       uv run python scripts/try_tts.py --voices
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline import tts  # noqa: E402
from app.pipeline.errors import PipelineError  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("lang", nargs="?")
    ap.add_argument("text", nargs="?")
    ap.add_argument("voice", nargs="?")
    ap.add_argument("--out", type=Path, default=Path("tts-sample.wav"))
    ap.add_argument("--voices", action="store_true", help="list languages and voices")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.voices:
        print(json.dumps(tts.voice_catalog(), indent=1))
        return 0
    if not (args.lang and args.text):
        ap.error("lang and text are required")

    tmp = Path(__file__).resolve().parents[1] / ".cache" / "tts-try"  # separate cache dir: always synthesize
    t0 = time.perf_counter()
    try:
        data = tts.synthesize(args.text, args.lang, args.voice, cache_dir=tmp)
    except PipelineError as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    took = time.perf_counter() - t0
    args.out.write_bytes(data)
    seconds = (len(data) - 44) / 2 / 24000
    print(f"{args.out}: {seconds:.1f}s of audio in {took:.2f}s (includes model load on first run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
