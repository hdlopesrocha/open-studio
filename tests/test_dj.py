"""DJ planner, style model and renderer smoke tests."""

from __future__ import annotations

import numpy as np

from services.dj import analysis, planner, synth
from services.dj.mixscene import plan_scene
from services.dj.mixer import EMOTION_PRESETS, EFFECT_PRESETS, apply_effects
from services.dj.model import train_model


def test_planner_builds_contiguous_arrangement():
    plan = planner.plan_structure(style="House", duration=120, prompt="dark warehouse peak time", energy=0.8, seed=4)
    sections = plan["sections"]
    assert sections
    assert sections[0]["start"] == 0
    for previous, current in zip(sections, sections[1:]):
        assert current["start"] == previous["end"]
        assert current["bars"] >= 1
    assert sections[-1]["end"] <= 121
    assert {section["role"] for section in sections} & {"intro", "drop", "outro"}
    assert plan["bpm"] == 124


def test_normalise_structure_repairs_user_edits():
    sections = [
        {"role": "intro", "label": "Intro", "bars": 8, "energy": 30},
        {"role": "drop", "label": "Drop", "bars": 16, "energy": 95},
    ]
    cleaned = planner.normalise_structure(sections, bpm=120, duration=60, style="House")
    assert cleaned[0]["start"] == 0
    assert cleaned[1]["start"] == cleaned[0]["end"]
    assert cleaned[-1]["end"] <= 61


def test_style_classifier_and_key_helpers():
    style, confidence, tags = analysis.classify_style(
        bpm=124,
        energy=0.7,
        danceability=0.86,
        low=0.34,
        mid=0.44,
        high=0.22,
        percussiveness=0.62,
        centroid=0.43,
    )
    assert style == "House"
    assert 0 < confidence <= 1
    assert tags
    assert analysis.camelot_for("A", "minor") == "8A"
    assert analysis.key_name(9, "minor") == "A minor"


def test_style_model_learns_from_analyses():
    tracks = [
        {
            "bpm": 124,
            "energy": 0.7,
            "key": "A minor",
            "analysis_json": '{"waveform":[0.2,0.4,0.6,0.8],"spectral":{"low":0.3,"mid":0.4,"high":0.3,"centroid_normalised":0.4,"percussiveness":0.6}}',
        },
        {
            "bpm": 126,
            "energy": 0.8,
            "key": "A minor",
            "analysis_json": '{"waveform":[0.1,0.3,0.7,0.9],"spectral":{"low":0.35,"mid":0.4,"high":0.25,"centroid_normalised":0.45,"percussiveness":0.65}}',
        },
    ]
    model = train_model("House", tracks)
    assert model["trained"] is True
    assert model["tracks"] == 2
    assert 124 <= model["bpm"] <= 126
    assert model["key"] == "A minor"
    assert len(model["section_curve"]) == 16


def test_mix_scene_plans_transitions_and_effects():
    tracks = [
        {"id": "a", "title": "A", "path": "a.wav", "duration": 180, "bpm": 124, "key": "A minor", "camelot": "8A", "style": "House", "energy": 0.6},
        {"id": "b", "title": "B", "path": "b.wav", "duration": 180, "bpm": 132, "key": "F minor", "camelot": "4A", "style": "Techno", "energy": 0.85},
    ]
    scene = plan_scene(tracks, prompt="dark warehouse", master_bpm=126, transition_beats=16, seed=3)
    assert scene["tracks"][0]["start"] == 0
    assert scene["tracks"][1]["start"] < scene["tracks"][0]["timeline_duration"]
    assert scene["tracks"][0]["transition"]["type"] in {"crossfade", "filter_sweep", "bass_swap", "echo_out", "cut"}
    assert any(track["effects"] for track in scene["tracks"])
    assert scene["duration"] > 0


def test_effect_rack_and_renderer_smoke():
    assert any(effect["id"] == "tape_stop" for effect in EFFECT_PRESETS)
    assert any(effect["id"] == "dark" for effect in EMOTION_PRESETS)
    audio = np.random.default_rng(7).standard_normal((44100 * 2, 2)).astype(np.float32) * 0.05
    processed = apply_effects(
        audio,
        [
            {"type": "filter_sweep", "from_hz": 18000, "to_hz": 400, "amount": 0.8, "start": 0, "end": 2},
            {"type": "drive", "amount": 0.3},
            {"type": "chorus", "amount": 0.2, "start": 0, "end": 1},
        ],
        beat_seconds=0.5,
    )
    assert processed.shape == audio.shape
    assert processed.dtype == np.float32

    plan = planner.plan_structure(style="House", duration=20, bpm=124, seed=2)
    result = synth.render_track(
        style="House",
        bpm=124,
        key="A minor",
        duration=20,
        sections=plan["sections"],
        seed=2,
        energy=0.7,
        brightness=0.5,
    )
    assert result["mix"].shape[1] == 2
    assert len(result["mix"]) >= 20 * synth.SR
    assert float(np.max(np.abs(result["mix"]))) > 0.1


def test_dj_analysis_extracts_structural_scenes():
    import numpy as np
    from services.dj.analysis import _sections

    bpm = 120.0
    duration = 128.0
    hop = 512
    sample_rate = 22050
    frames = int(np.ceil(duration * sample_rate / hop)) + 1
    frame_times = np.arange(frames) * hop / sample_rate
    levels = np.zeros(frames)
    for index, value in enumerate(frame_times):
        levels[index] = (
            0.18 if value < 16 else
            0.85 if value < 40 else
            0.30 if value < 56 else
            0.95 if value < 96 else
            0.72 if value < 112 else
            0.25
        )
    rms = 0.05 * levels + 0.005
    chroma = np.zeros((12, frames))
    mfcc = np.zeros((13, frames))
    for index, value in enumerate(frame_times):
        segment = int(value // 16)
        chroma[:, index] = np.roll(np.arange(12) == (segment % 12), index % 12)
        mfcc[:, index] = np.sin(np.arange(13) * 0.4 + segment)
    sections = _sections(
        duration=duration,
        bpm=bpm,
        rms=rms,
        frame_times=frame_times,
        valence=0.6,
        style="House",
        downbeats=[index * 2.0 for index in range(64)],
        mfcc=mfcc,
        chroma=chroma,
        centroid=np.full(frames, 1800.0),
        bandwidth=np.full(frames, 1200.0),
        flatness=np.full(frames, 0.15),
        onset_env=np.ones(frames),
    )
    assert len(sections) >= 5
    assert sections[0]["role"] == "intro"
    assert sections[-1]["role"] == "outro"
    assert any(section["role"] == "drop" for section in sections)
    assert all(section["scene_id"] and section["summary"] and section["bars"] > 0 for section in sections)
    for previous, current in zip(sections, sections[1:]):
        assert previous["end"] == current["start"]
    assert sections[0]["start"] == 0
    assert sections[-1]["end"] <= duration + 0.01


def test_mix_scene_can_use_multiple_sections_per_track():
    import json
    from services.dj.mixscene import plan_scene

    def track(track_id: str, title: str, base: int, energy: float) -> dict:
        sections = [
            {"scene_id": "scene-1", "role": "intro", "label": "Intro", "start": 0.0, "end": 20.0, "energy": 30},
            {"scene_id": "scene-2", "role": "breakdown", "label": "Breakdown", "start": 20.0, "end": 40.0, "energy": 45},
            {"scene_id": "scene-3", "role": "drop", "label": "Drop", "start": 40.0, "end": 80.0, "energy": 95},
            {"scene_id": "scene-4", "role": "outro", "label": "Outro", "start": 80.0, "end": 100.0, "energy": 25},
        ]
        return {
            "id": track_id,
            "title": title,
            "path": f"{track_id}.wav",
            "duration": 100.0,
            "bpm": base,
            "key": "A minor",
            "camelot": "8A",
            "style": "House",
            "energy": energy,
            "analysis_json": json.dumps({"version": 3, "sections": sections, "rhythm": {"downbeats": []}}),
        }

    scene = plan_scene(
        [track("a", "A", 124, 0.6), track("b", "B", 128, 0.8)],
        prompt="peak time",
        master_bpm=126,
        transition_beats=8,
        seed=2,
        use_sections=True,
    )
    assert len(scene["tracks"]) > 2
    assert all(entry.get("section_label") for entry in scene["tracks"])
    source_ids = [entry.get("source_track_id") for entry in scene["tracks"]]
    assert any(left == right for left, right in zip(source_ids, source_ids[1:]))
    assert any(
        left.get("transition", {}).get("type") == "cut"
        for left, right in zip(scene["tracks"], scene["tracks"][1:])
        if left.get("source_track_id") == right.get("source_track_id")
    )
    assert scene["duration"] > 0
