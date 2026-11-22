import json
import logging

from app.pipeline import cache
from app.pipeline.models import Point, Section, Segment, Summary

SUMMARY = Summary(
    tldr="Gist.",
    sections=[Section(title="S", start=0, end=30, points=[Point(t=0, text="p")])],
)
MODEL, VERSION = "model-a", 1
SEGMENTS = [Segment(start=0, end=2, text="hi"), Segment(start=2, end=4, text="there")]


def test_summary_round_trip(tmp_path):
    cache.save_summary("vid", "en", SUMMARY, MODEL, VERSION, cache_dir=tmp_path)
    assert cache.load_summary("vid", "en", MODEL, VERSION, cache_dir=tmp_path) == SUMMARY
    assert (tmp_path / "summaries" / f"vid.en.{MODEL}.json").exists()


def test_summary_keyed_by_language(tmp_path):
    cache.save_summary("vid", "en", SUMMARY, MODEL, VERSION, cache_dir=tmp_path)
    assert cache.load_summary("vid", "es", MODEL, VERSION, cache_dir=tmp_path) is None


def test_summary_miss(tmp_path):
    assert cache.load_summary("nope", "en", MODEL, VERSION, cache_dir=tmp_path) is None


def test_corrupt_summary_is_a_miss(tmp_path, caplog):
    path = tmp_path / "summaries" / f"vid.en.{MODEL}.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    with caplog.at_level(logging.WARNING):
        assert cache.load_summary("vid", "en", MODEL, VERSION, cache_dir=tmp_path) is None
    assert f"vid.en.{MODEL}.json" in caplog.text


def test_transcript_round_trip(tmp_path):
    cache.save_transcript("vid", SEGMENTS, "en", "captions", cache_dir=tmp_path)
    assert cache.load_transcript("vid", cache_dir=tmp_path) == (SEGMENTS, "en", "captions")


def test_transcript_miss(tmp_path):
    assert cache.load_transcript("nope", cache_dir=tmp_path) is None


def test_save_leaves_no_temp_files(tmp_path):
    cache.save_summary("vid", "en", SUMMARY, MODEL, VERSION, cache_dir=tmp_path)
    cache.save_summary("vid", "en", SUMMARY, MODEL, VERSION, cache_dir=tmp_path)
    assert [p.name for p in (tmp_path / "summaries").iterdir()] == [f"vid.en.{MODEL}.json"]


def test_different_model_is_a_miss(tmp_path):
    cache.save_summary("vid", "en", SUMMARY, MODEL, VERSION, cache_dir=tmp_path)
    assert cache.load_summary("vid", "en", "model-b", VERSION, cache_dir=tmp_path) is None


def test_different_prompt_version_is_a_miss(tmp_path):
    cache.save_summary("vid", "en", SUMMARY, MODEL, VERSION, cache_dir=tmp_path)
    assert cache.load_summary("vid", "en", MODEL, VERSION + 1, cache_dir=tmp_path) is None


def test_prompt_version_mismatch_is_overwritten_in_place(tmp_path):
    cache.save_summary("vid", "en", SUMMARY, MODEL, VERSION, cache_dir=tmp_path)
    newer = SUMMARY.model_copy(update={"tldr": "Newer."})
    cache.save_summary("vid", "en", newer, MODEL, VERSION + 1, cache_dir=tmp_path)
    assert cache.load_summary("vid", "en", MODEL, VERSION + 1, cache_dir=tmp_path) == newer
    assert cache.load_summary("vid", "en", MODEL, VERSION, cache_dir=tmp_path) is None
    assert [p.name for p in (tmp_path / "summaries").iterdir()] == [f"vid.en.{MODEL}.json"]


def test_file_records_model_and_prompt_version(tmp_path):
    cache.save_summary("vid", "en", SUMMARY, MODEL, VERSION, cache_dir=tmp_path)
    data = json.loads((tmp_path / "summaries" / f"vid.en.{MODEL}.json").read_text())
    assert (data["model"], data["prompt_version"]) == (MODEL, VERSION)


def test_old_format_file_is_a_miss(tmp_path):
    # Summaries cached before model/prompt_version were recorded.
    path = tmp_path / "summaries" / f"vid.en.{MODEL}.json"
    path.parent.mkdir(parents=True)
    path.write_text(SUMMARY.model_dump_json())
    assert cache.load_summary("vid", "en", MODEL, VERSION, cache_dir=tmp_path) is None


def test_each_model_keeps_its_own_summary(tmp_path):
    other = SUMMARY.model_copy(update={"tldr": "from model b"})
    cache.save_summary("vid", "en", SUMMARY, MODEL, VERSION, cache_dir=tmp_path)
    cache.save_summary("vid", "en", other, "model-b", VERSION, cache_dir=tmp_path)
    assert cache.load_summary("vid", "en", MODEL, VERSION, cache_dir=tmp_path) == SUMMARY
    assert cache.load_summary("vid", "en", "model-b", VERSION, cache_dir=tmp_path) == other


def test_model_name_is_made_filename_safe(tmp_path):
    cache.save_summary("vid", "en", SUMMARY, "org/model:v1", VERSION, cache_dir=tmp_path)
    assert [p.name for p in (tmp_path / "summaries").iterdir()] == ["vid.en.org_model_v1.json"]
    assert cache.load_summary("vid", "en", "org/model:v1", VERSION, cache_dir=tmp_path) == SUMMARY
