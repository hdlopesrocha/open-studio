"""DJ mix scene controls for segment count and target duration."""

from __future__ import annotations

import json

from services.dj.mixscene import plan_scene


def _track(track_id: str, index: int) -> dict:
    sections = [
        {"scene_id": "a", "role": "intro", "label": "Intro", "start": 0, "end": 20, "energy": 20},
        {"scene_id": "b", "role": "groove", "label": "Groove", "start": 20, "end": 50, "energy": 60},
        {"scene_id": "c", "role": "drop", "label": "Drop", "start": 50, "end": 80, "energy": 95},
        {"scene_id": "d", "role": "outro", "label": "Outro", "start": 80, "end": 100, "energy": 25},
    ]
    return {
        "id": track_id,
        "title": f"Track {index}",
        "path": f"{track_id}.wav",
        "duration": 100.0,
        "bpm": 120 + index,
        "key": "A minor",
        "camelot": "8A",
        "style": "House",
        "energy": 0.7,
        "analysis_json": json.dumps({"version": 3, "sections": sections}),
    }


def test_scene_respects_segment_count_and_target_duration():
    tracks = [_track(f"t{index}", index) for index in range(5)]
    scene = plan_scene(tracks, master_bpm=124, transition_beats=8, use_sections=True, segments=4, target_duration=90)
    assert len(scene["tracks"]) <= 4
    assert scene["duration"] <= 95
    assert any("Target duration" in note for note in scene["notes"])
