"""Subtitle formatting and alignment tests that do not require Whisper."""

from __future__ import annotations

from services.srt.aligner import (
    align_lyrics,
    extract_words,
    parse_lyric_lines,
    proportional_cues_from_lines,
    suggested_total_duration,
    tokenize,
)
from services.srt.formats import (
    build_subtitles,
    detect_format,
    distribute_window,
    enforce_gap,
    parse_subtitles,
    split_text_for_cues,
    wrap_text,
)


CUES = [
    {"start": 0.0, "end": 2.25, "text": "A cidade fecha os olhos"},
    {"start": 2.25, "end": 5.5, "text": "Eu conto os passos"},
]


def test_srt_vtt_and_ass_roundtrip():
    srt = build_subtitles(CUES, "srt")
    vtt = build_subtitles(CUES, "vtt")
    ass = build_subtitles(CUES, "ass")

    assert detect_format(srt) == "srt"
    assert detect_format(vtt) == "vtt"
    assert detect_format(ass) == "ass"

    for text in (srt, vtt, ass):
        cues = parse_subtitles(text)
        assert [cue["text"] for cue in cues] == [cue["text"] for cue in CUES]
    assert [cue["start"] for cue in parse_subtitles(vtt)] == [0.0, 2.25]
    assert "00:00:02,250 --> 00:00:05,500" in srt
    assert "00:00:02.250 --> 00:00:05.500" in vtt
    assert "0:00:02.25,0:00:05.50" in ass


def test_vtt_parser_accepts_mm_ss_and_cue_settings():
    cues = parse_subtitles(
        "WEBVTT\n\nNOTE generated\n\ncue-1\n01:02.500 --> 01:04.000 align:start\nHello\nthere\n",
        "vtt",
    )
    assert len(cues) == 1
    assert cues[0]["start"] == 62.5
    assert cues[0]["end"] == 64.0
    assert cues[0]["text"] == "Hello\nthere"


def test_wrap_and_split_respect_line_limits():
    wrapped = wrap_text("one two three four five six seven eight nine ten", max_line_chars=16, max_lines=2)
    assert len(wrapped) <= 2
    assert all(len(line) <= 16 for line in wrapped[:-1])

    text = "This is a deliberately long lyric line, with punctuation, that must be broken into readable cues."
    chunks = split_text_for_cues(text, max_line_chars=24, max_lines=2)
    assert len(chunks) > 1
    assert all(chunk for chunk in chunks)
    joined = " ".join(chunk.replace("\n", " ") for chunk in chunks)
    assert "deliberately long lyric" in joined

    assert split_text_for_cues("   ") == []
    assert wrap_text("", 10, 2) == []


def test_enforce_gap_clamps_overlap_and_orders_cues():
    cues = enforce_gap(
        [
            {"start": 0.0, "end": 4.0, "text": "first"},
            {"start": 1.0, "end": 3.0, "text": "second"},
            {"start": 5.0, "end": 9.0, "text": "third"},
        ],
        gap=0.05,
        duration=8.0,
    )
    assert [cue["index"] for cue in cues] == [1, 2, 3]
    assert cues[0]["end"] <= cues[1]["start"] - 0.05 + 1e-9
    assert cues[-1]["end"] == 8.0
    assert cues[0]["start"] == 0.0


def test_distribute_window_covers_requested_span():
    times = distribute_window(10.0, 20.0, [1, 2, 1], gap=0.5)
    assert len(times) == 3
    assert times[0][0] == 10.0
    assert times[-1][1] == 20.0
    assert all(end > start for start, end in times)
    assert all(next_start >= end for (_, end), (next_start, _) in zip(times, times[1:]))


def test_parse_lyric_lines_supports_lrc_sections_and_metadata():
    lyrics = """[ar:Someone]
# comment
[Verse 1]
[00:01.50]First line
[00:04.00]Second line

[Chorus]
Loud line
"""
    lines = parse_lyric_lines(lyrics)
    assert [line.text for line in lines] == ["First line", "Second line", "Loud line"]
    assert [line.explicit_start for line in lines] == [1.5, 4.0, None]


def test_tokenize_handles_accents_and_cjk():
    assert tokenize("Ó mar, não 'voltes'") == ["o", "mar", "nao", "voltes"]
    assert tokenize("東京の夜") == ["東", "京", "の", "夜"]


def test_extract_words_approximates_missing_word_timestamps():
    words, approximated = extract_words(
        [{"start": 2.0, "end": 3.0, "text": "hello world"}]
    )
    assert approximated is True
    assert [word.text for word in words] == ["hello", "world"]
    assert words[0].start == 2.0
    assert words[-1].end <= 3.0

    words, approximated = extract_words(
        [{"start": 0, "end": 1, "text": "hi", "words": [{"word": "hi", "start": 0.1, "end": 0.4}]}]
    )
    assert approximated is False
    assert words[0].start == 0.1 and words[0].end == 0.4


def test_align_lyrics_anchors_lines_to_asr_words():
    segments = [
        {
            "start": 0.0,
            "end": 4.0,
            "text": "a cidade fecha os olhos eu conto os passos",
            "words": [
                {"word": "a", "start": 0.0, "end": 0.1},
                {"word": "cidade", "start": 0.1, "end": 0.5},
                {"word": "fecha", "start": 0.5, "end": 0.8},
                {"word": "os", "start": 0.8, "end": 0.9},
                {"word": "olhos", "start": 0.9, "end": 1.2},
                {"word": "eu", "start": 1.4, "end": 1.5},
                {"word": "conto", "start": 1.5, "end": 1.8},
                {"word": "os", "start": 1.8, "end": 1.9},
                {"word": "passos", "start": 1.9, "end": 2.3},
            ],
        }
    ]
    cues, stats = align_lyrics(
        "A cidade fecha os olhos\nEu conto os passos",
        segments,
        duration=5.0,
    )

    assert len(cues) == 2
    assert stats.lines == 2
    assert stats.matched_ratio > 0.9
    assert cues[0]["start"] == 0.0
    assert cues[0]["end"] <= cues[1]["start"] + 1e-6
    assert cues[1]["text"].startswith("Eu conto")


def test_proportional_cues_and_duration_estimate_without_model():
    text = "First line here\nSecond line here\nThird line here"
    cues = proportional_cues_from_lines(text, duration=12.0, start=1.0)
    assert len(cues) == 3
    assert cues[0]["start"] == 1.0
    assert cues[-1]["end"] <= 13.0
    assert all(cue["end"] > cue["start"] for cue in cues)
    assert suggested_total_duration(text) > 0
