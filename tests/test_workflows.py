"""Tests for workflow helpers."""

from pathlib import Path

from subtrans.workflows import load_and_validate_subtitle

SRT_BODY = (
    "1\n00:00:01,000 --> 00:00:03,000\nWho are you, really?\n\n"
    "2\n00:00:04,000 --> 00:00:06,000\nI can't tell you.\n\n"
)


def test_load_strips_utf8_bom(tmp_path: Path) -> None:
    """A BOM-prefixed SRT (as mkvextract can produce) must parse index 1 as int."""
    srt_path = tmp_path / "bom.srt"
    srt_path.write_bytes(b"\xef\xbb\xbf" + SRT_BODY.encode("utf-8"))

    subs, count = load_and_validate_subtitle(
        srt_path, min_subtitle_count=1, strict_validation=False
    )

    assert subs is not None
    assert count == 2
    assert subs[0].index == 1
    assert not [e for e in subs.validate() if e.error_type == "sequence"]


def test_load_without_bom(tmp_path: Path) -> None:
    srt_path = tmp_path / "plain.srt"
    srt_path.write_text(SRT_BODY, encoding="utf-8")

    subs, count = load_and_validate_subtitle(
        srt_path, min_subtitle_count=1, strict_validation=False
    )

    assert subs is not None
    assert count == 2
    assert subs[0].index == 1


SHORT_SRT = (
    "1\n00:00:01,000 --> 00:00:03,000\nAnd thank you.\n\n"
    "2\n00:00:04,000 --> 00:00:06,000\n.\n\n"
    "3\n00:00:07,000 --> 00:00:09,000\n♪\n\n"
    "4\n00:00:10,000 --> 00:00:12,000\nGood night.\n\n"
)


def test_find_short_entries_respects_allow_list(tmp_path: Path) -> None:
    import pysrt

    from subtrans.workflows import find_short_positions

    subs = pysrt.from_string(SHORT_SRT)

    assert find_short_positions(subs, min_text_length=2) == [1]


def test_phase1_short_lines_are_not_fatal(tmp_path: Path) -> None:
    """A lone '.' entry is reported, not treated as a validation failure."""
    from unittest.mock import patch

    from subtrans.core.models import Movie
    from subtrans.workflows import ShortLineReport, process_phase1
    from tests.test_cli import _make_config

    srt_path = tmp_path / "test.en.srt"
    srt_path.write_text(SHORT_SRT, encoding="utf-8")
    movie = Movie(
        radarr_id=1,
        title="Test Movie",
        year=2024,
        path=str(tmp_path / "test.mkv"),
        missing_subtitles=["fi"],
        existing_subtitles=[],
    )
    config = _make_config(
        validate_subtitles=True,
        min_duration_ms=500,
        max_duration_secs=10.0,
        min_text_length=2,
        max_text_length=500,
    )
    reports: list[ShortLineReport] = []

    with patch(
        "subtrans.workflows.get_source_subtitle", return_value=(srt_path, False)
    ):
        result = process_phase1(
            movie,
            client=None,
            config=config,
            extract_only=True,
            short_line_reports=reports,
        )

    assert result is True
    assert len(reports) == 1
    assert reports[0].srt_path == srt_path
    assert reports[0].positions == [1]


def test_context_groups_merges_overlapping_windows() -> None:
    from subtrans.workflows import context_groups

    # 0..4 and 3..7 overlap -> merged; 20 is separate; edges clamp to bounds
    assert context_groups([2, 5, 20], length=22) == [range(8), range(18, 22)]
    # adjacent windows (stop == next start) merge too
    assert context_groups([2, 7], length=20) == [range(10)]
    assert context_groups([2, 8], length=20) == [range(5), range(6, 11)]


def test_print_short_line_reports_shows_context(tmp_path: Path) -> None:
    import pysrt

    from subtrans.core.utils import console
    from subtrans.workflows import ShortLineReport, print_short_line_reports

    lines = [f"Line {i}" for i in range(1, 13)]
    lines[5] = "."  # index 6
    srt = "".join(
        f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},500\n{text}\n\n"
        for i, text in enumerate(lines, start=1)
    )
    subs = pysrt.from_string(srt)
    report = ShortLineReport("Movie [2026]", tmp_path / "x [WEBDL].srt", subs, [5])

    with console.capture() as capture:
        print_short_line_reports([report])
    out = capture.get()

    assert "Short subtitle lines: 1 in 1 file(s)" in out
    assert "Movie [2026]" in out
    assert "x [WEBDL].srt" in out
    shown = [
        ln.strip() for ln in out.splitlines() if ln.strip().startswith(("#", "-->"))
    ]
    assert len(shown) == 5
    assert shown[2].startswith("--> #6") and "'.'" in shown[2]
    assert shown[0].startswith("#4") and shown[-1].startswith("#8")
    assert "Line 3" not in out and "Line 9" not in out


def test_print_short_line_reports_silent_when_empty() -> None:
    from subtrans.core.utils import console
    from subtrans.workflows import print_short_line_reports

    with console.capture() as capture:
        print_short_line_reports([])

    assert capture.get() == ""
