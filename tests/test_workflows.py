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
