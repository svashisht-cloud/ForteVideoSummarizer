import re
from urllib.parse import parse_qs, urlsplit

from app.pipeline.errors import InvalidURL

_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com"}
_SHORT_HOSTS = {"youtu.be"}
_PATH_KINDS = {"shorts", "live", "embed"}
_ID_RULE = "expected 11 characters of A-Z, a-z, 0-9, _ or -"


def _check_id(candidate: str) -> str:
    if not _ID.fullmatch(candidate):
        raise InvalidURL(f"invalid video ID {candidate!r} ({_ID_RULE})")
    return candidate


def parse_video_id(url: str) -> str:
    """Extract the 11-character video ID from a YouTube URL or a bare ID.

    Raises InvalidURL with a message saying what was wrong.
    """
    text = url.strip()
    if not text:
        raise InvalidURL("empty URL")

    if _ID.fullmatch(text):
        return text
    if "/" not in text and "." not in text:
        raise InvalidURL(f"{text!r} is not a URL or an 11-character video ID")

    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)

    if parts.scheme.lower() not in ("http", "https"):
        raise InvalidURL(f"unsupported scheme {parts.scheme!r}; use http or https")

    host = (parts.hostname or "").lower().removeprefix("www.")
    segments = [p for p in parts.path.split("/") if p]

    if host in _SHORT_HOSTS:
        if not segments:
            raise InvalidURL("youtu.be link has no video ID")
        if len(segments) > 1:
            raise InvalidURL(f"unsupported youtu.be URL path {parts.path!r}")
        return _check_id(segments[0])

    if host not in _YOUTUBE_HOSTS:
        raise InvalidURL(f"not a YouTube URL (host {parts.hostname!r})")

    if segments == ["watch"]:
        values = parse_qs(parts.query).get("v")
        if not values or not values[0]:
            raise InvalidURL("watch URL is missing the v= parameter")
        return _check_id(values[0])

    if segments and segments[0] in _PATH_KINDS:
        if len(segments) == 1:
            raise InvalidURL(f"/{segments[0]}/ URL has no video ID")
        if len(segments) == 2:
            return _check_id(segments[1])

    raise InvalidURL(
        f"unsupported YouTube URL path {parts.path or '/'!r}; "
        "expected /watch?v=, /shorts/, /live/ or /embed/"
    )
