"""Test display_subtitle_tracks with SubRip/SRT codec format."""


def test_display_subtitle_tracks_subrip_srt_format(capsys):
    """Should recognize SubRip/SRT codec as supported (not mark as unsupported)."""
    from subtrans.processing.subtitles import display_subtitle_tracks
    from subtrans.core.models import SubtitleTrack

    # Create tracks with different codec formats, including SubRip/SRT
    tracks = [
        SubtitleTrack(
            track_id=1,
            language="eng",
            name="British",
            codec="S_TEXT/UTF8",
            forced=False,
            sdh=False,
            entry_count=1329,
        ),
        SubtitleTrack(
            track_id=2,
            language="eng",
            name="British | Forced",
            codec="SubRip/SRT",
            forced=True,
            sdh=False,
            entry_count=22,
        ),
        SubtitleTrack(
            track_id=3,
            language="eng",
            name="British | SDH",
            codec="SubRip/SRT",
            forced=False,
            sdh=True,
            entry_count=1585,
        ),
    ]

    # Select the full track
    selected_track = tracks[0]

    # Display tracks
    display_subtitle_tracks(tracks, selected_track, "en")

    captured = capsys.readouterr()

    # Verify that SubRip/SRT codec tracks are NOT marked as unsupported
    assert "Unsupported format" not in captured.out

    # Verify the format column shows "SRT" for both S_TEXT/UTF8 and SubRip/SRT
    assert "SRT" in captured.out

    # Verify all tracks are displayed (no skipped due to being unsupported)
    assert "   1   │" in captured.out  # Track 1 in table
    assert "   2   │" in captured.out  # Track 2 in table
    assert "   3   │" in captured.out  # Track 3 in table


def test_display_subtitle_tracks_s_text_utf8_format(capsys):
    """Should recognize S_TEXT/UTF8 codec as supported."""
    from subtrans.processing.subtitles import display_subtitle_tracks
    from subtrans.core.models import SubtitleTrack

    # Create tracks with S_TEXT/UTF8 format
    tracks = [
        SubtitleTrack(
            track_id=1,
            language="eng",
            name="English",
            codec="S_TEXT/UTF8",
            forced=False,
            sdh=False,
            entry_count=1000,
        ),
    ]

    display_subtitle_tracks(tracks, tracks[0], "en")

    captured = capsys.readouterr()

    # Should not show unsupported format
    assert "Unsupported format" not in captured.out

    # Format column should show "SRT" after transformation
    assert "SRT" in captured.out
