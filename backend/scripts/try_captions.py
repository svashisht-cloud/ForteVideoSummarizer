"""Fetch captions for a video and show what the pipeline sees.

Usage: uv run python scripts/try_captions.py <youtube-url-or-id>
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.pipeline.captions import fetch_caption_track  # noqa: E402
from app.pipeline.errors import PipelineError  # noqa: E402
from app.pipeline.normalize import normalize, to_prompt_text  # noqa: E402
from app.pipeline.url import parse_video_id  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    try:
        video_id = parse_video_id(sys.argv[1])
        track = fetch_caption_track(video_id)
    except PipelineError as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1

    blocks = normalize(track.segments)
    print(f"video id:      {video_id}")
    print(f"language:      {track.language}")
    print(f"track type:    {'auto' if track.is_generated else 'manual'}")
    print(f"raw segments:  {len(track.segments)}")
    print(f"blocks:        {len(blocks)}")
    print()
    print(to_prompt_text(blocks[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
