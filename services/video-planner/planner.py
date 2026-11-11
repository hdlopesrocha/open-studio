"""Deterministic, structure-aware story planning with optional local LLM enhancement."""

from __future__ import annotations

import json
import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any

from mvstudio_shared.models import (
    AISettings,
    AudioAnalysis,
    CameraMove,
    Character,
    Location,
    LyricsAnalysis,
    LyricSection,
    PlanResult,
    ProjectConfig,
    Scene,
    SubtitleLine,
    TransitionPlan,
    VisualContext,
)
from mvstudio_shared.srt import clean_subtitle_text, flatten_text
from mvstudio_shared.styles import get_style
from mvstudio_shared.text import (
    detect_motifs,
    extract_keywords,
    infer_mood,
    mood_lighting,
    motif_location,
)

from .ollama import OllamaPlanner, OllamaUnavailable

logger = logging.getLogger("mvstudio.planner")

MOTION_BY_SECTION = {
    "intro": ["slow_forward", "pan_right"],
    "verse": ["pan_left", "slow_forward", "pan_right", "slow_backward"],
    "chorus": ["slow_forward", "pan_right", "slow_forward", "pan_left"],
    "bridge": ["slow_backward", "handheld", "pan_up"],
    "breakdown": ["slow_backward", "handheld", "pan_left"],
    "instrumental": ["pan_right", "slow_forward", "pan_left"],
    "outro": ["slow_backward", "pan_up"],
    "unknown": ["slow_forward", "pan_left", "pan_right"],
}

SHOTS_HIGH = [
    "Sweeping aerial shot",
    "Low-angle tracking shot",
    "Wide dramatic shot",
    "Intimate handheld close-up",
]
SHOTS_MID = [
    "Wide establishing shot",
    "Medium tracking shot",
    "Cinematic dolly shot",
    "Reflection shot",
]
SHOTS_LOW = [
    "Wide establishing shot",
    "Still medium shot",
    "Slow dolly shot",
    "Quiet profile shot",
]

MOOD_PHRASES = {
    "romantic": "tender and intimate",
    "melancholic": "quiet and aching",
    "epic": "vast and mythic",
    "hopeful": "open and luminous",
    "dark": "uneasy and shadowed",
    "dreamy": "weightless and surreal",
    "energetic": "kinetic and electric",
    "introspective": "still and contemplative",
}

ACTIONS = {
    "intro": ["steps into the edge of the frame", "pauses at the beginning of the road"],
    "verse": ["walks slowly", "looks toward the horizon", "moves quietly through the scene"],
    "chorus": ["stands against the light", "turns to face the sky", "opens both arms to the wind"],
    "bridge": ["waits in the stillness", "traces a path through the shadows"],
    "breakdown": ["sits with the silence", "drifts through the half-light"],
    "outro": ["walks away into the distance", "fades toward the horizon"],
    "instrumental": ["moves through the landscape", "stands small against the scale of the world"],
    "unknown": ["moves through the landscape"],
}

SUPPORTED_EFFECTS = {
    "vignette",
    "film_grain",
    "subtle_film_grain",
    "bloom",
    "soft_focus",
    "light_leak",
    "chromatic_aberration",
    "letterbox",
    "shake",
    "particles",
    "beat_pulse",
    "bass_pulse",
}


@dataclass
class SectionSpan:
    start: float
    end: float
    kind: str
    label: str
    energy: float
    energy_relative: float
    lines: list[SubtitleLine] = field(default_factory=list)
    lyric_section_id: int | None = None
    repeat_of: int | None = None


@dataclass
class RawScene:
    start: float
    end: float
    span: SectionSpan


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _rng(seed: int, *parts: Any) -> random.Random:
    return random.Random(":".join([str(seed), *[str(part) for part in parts]]))


def _character_for(motifs: list[str], mood: str, palette: list[str]) -> Character:
    name = {
        "romantic": "The Lover",
        "epic": "The Wanderer",
        "melancholic": "The Traveller",
        "hopeful": "The Dreamer",
        "dark": "The Stranger",
        "dreamy": "The Dreamer",
        "energetic": "The Dancer",
        "introspective": "The Observer",
    }.get(mood, "The Wanderer")
    if "journey" in motifs:
        name = "The Wanderer"
    elif "ocean" in motifs:
        name = "The Sailor"
    elif "dance" in motifs:
        name = "The Dancer"
    elif "city" in motifs and mood in {"dark", "energetic", "introspective"}:
        name = "The Nightwalker"
    elif "war" in motifs:
        name = "The Survivor"
    coat = palette[1] if len(palette) > 1 else "#1C2541"
    accent = palette[-2] if len(palette) > 1 else "#F4A261"
    hair = palette[0] if palette else "#0B132B"
    return Character(
        name=name,
        role="protagonist",
        description=(
            "The recurring protagonist whose inner journey mirrors the emotional arc of the song. "
            "The face may stay partially in shadow, but the silhouette, clothing and posture must remain identical."
        ),
        appearance=(
            f"an androgynous adult with dark hair, a long weathered coat in deep tones of {coat}, "
            f"a scarf in {accent}, and a quiet, searching posture. Hair and coat silhouettes echo {hair}. "
            "The same person appears in every scene."
        ),
        accent_color=accent,
    )


def _companion_for(palette: list[str], mood: str) -> Character:
    accent = palette[2] if len(palette) > 2 else "#C86B85"
    return Character(
        name="The Beloved",
        role="companion",
        description=(
            "The person the song is addressed to; a presence that anchors the emotional stakes. "
            "Never recast or change their appearance between scenes."
        ),
        appearance=(
            f"a soft-featured adult in flowing clothes, with a signature detail in {accent}. "
            "Their silhouette is warm and recognisable even at a distance."
        ),
        accent_color=accent,
    )


class StoryPlanner:
    def __init__(self, ollama: OllamaPlanner | None = None):
        self.ollama = ollama

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def plan(
        self,
        *,
        project_id: str,
        project_name: str,
        title: str = "",
        audio: AudioAnalysis | None,
        lyrics: LyricsAnalysis,
        config: ProjectConfig,
        ai_settings: AISettings | None = None,
    ) -> PlanResult:
        duration = float(audio.duration if audio else (lyrics.duration or 0.0))
        if duration <= 0:
            duration = max((line.end for line in lyrics.lines), default=10.0)
        if duration <= 0:
            raise ValueError("Cannot plan a video without a positive duration")

        warnings: list[str] = []
        warnings.extend(audio.warnings if audio else [])
        warnings.extend(lyrics.warnings)

        visual_context = self._build_visual_context(
            project_name=project_name,
            project_id=project_id,
            title=title,
            lyrics=lyrics,
            audio=audio,
            config=config,
        )
        spans = self._build_spans(audio, lyrics, duration, config)
        if not spans:
            raise ValueError("No usable musical or lyric sections to plan scenes from")

        raw_scenes = self._split_into_scenes(spans, lyrics.lines, audio, config)
        scenes = self._materialise_scenes(
            raw_scenes,
            lyrics=lyrics,
            audio=audio,
            context=visual_context,
            config=config,
            duration=duration,
        )
        scenes = self._assign_transitions(scenes, config, audio)
        self._validate_scenes(scenes, duration, warnings)

        planner_name = "deterministic"
        planner_mode = config.ai.llm_mode
        if planner_mode != "deterministic":
            settings = ai_settings or AISettings()
            model = settings.ollama_model or "llama3.2"
            base_url = settings.ollama_url or "http://127.0.0.1:11434"
            ollama = self.ollama or OllamaPlanner(base_url, model)
            available, detail = ollama.available()
            if not available:
                message = f"{detail} Deterministic scene planning was used; no AI text was invented."
                if planner_mode == "ollama" and not config.ai.allow_fallback:
                    raise RuntimeError(message)
                warnings.append(message)
            else:
                prompt = self._build_llm_prompt(scenes, visual_context, project_name, title)
                try:
                    enhancement = ollama.enhance(prompt)
                    scene_by_id = {scene.scene_id: scene for scene in scenes}
                    valid_updates = [
                        update for update in enhancement.scenes if update.scene_id in scene_by_id
                    ]
                    if len(valid_updates) >= max(1, len(scenes) // 3):
                        for update in valid_updates:
                            scene = scene_by_id[update.scene_id]
                            scene.description = update.description.strip()
                            scene.visual_prompt = update.visual_prompt.strip()
                        planner_name = "ollama"
                        if enhancement.art_direction.strip():
                            visual_context.art_direction = enhancement.art_direction.strip()
                        if enhancement.visual_style_prompt.strip():
                            style_part = enhancement.visual_style_prompt.strip()
                            visual_context.style_prompt = (
                                f"{visual_context.style_prompt}. {style_part}"[:2000]
                            )
                        visual_context.planner = "ollama"
                        warnings.append(
                            f"Scene descriptions enhanced with local Ollama model '{model}'. "
                            f"{len(scenes) - len(valid_updates)} scene(s) kept deterministic text."
                        )
                    else:
                        warnings.append(
                            "Ollama returned too few usable scene updates; deterministic descriptions were kept."
                        )
                except OllamaUnavailable as exc:
                    message = f"{exc} Deterministic scene planning was used."
                    if planner_mode == "ollama" and not config.ai.allow_fallback:
                        raise RuntimeError(message)
                    warnings.append(message)

        scenes = self._renumber_and_validate(scenes, duration, warnings)
        visual_context.planner = planner_name
        visual_context.seed = config.scenes.seed
        return PlanResult(
            visual_context=visual_context,
            scenes=scenes,
            warnings=warnings,
            planner=planner_name,
        )

    # ------------------------------------------------------------------
    # Visual context
    # ------------------------------------------------------------------
    def _build_visual_context(
        self,
        *,
        project_name: str,
        project_id: str,
        title: str,
        lyrics: LyricsAnalysis,
        audio: AudioAnalysis | None,
        config: ProjectConfig,
    ) -> VisualContext:
        style = get_style(config.scenes.style_id)
        texts = [clean_subtitle_text(line.text) for line in lyrics.lines if line.text.strip()]
        motifs = detect_motifs(texts, limit=6)
        if not motifs:
            motifs = ["journey"]
        energy_values = [beat.strength for beat in audio.beats] if audio and audio.beats else [0.5]
        mean_energy = sum(energy_values) / max(1, len(energy_values))
        mood = infer_mood(texts, energy=mean_energy)

        palette = list(style.palette)
        characters = [_character_for(motifs, mood, palette)]
        lowered = " ".join(texts).lower()
        second_person = any(
            token in lowered
            for token in (" you ", " your ", " você", " teu ", " tua ", " we ", " nós ", " our ", " nos ")
        )
        if second_person or mood == "romantic":
            characters.append(_companion_for(palette, mood))

        locations: list[Location] = []
        for motif in motifs[:4]:
            name = motif.replace("_", " ").title()
            description = motif_location(motif)
            if all(location.name != name for location in locations):
                locations.append(Location(name=name, description=description, motif=motif))
        if not locations:
            locations.append(
                Location(
                    name="Open Landscape",
                    description="a wide, cinematic landscape open to the sky",
                    motif="journey",
                )
            )

        custom = config.scenes.visual_style_prompt.strip()
        style_prompt = style.prompt_suffix + (f". {custom}" if custom else "")
        negative = style.negative_prompt + ", inconsistent character, changing face, text, watermark, logo"
        return VisualContext(
            style_id=style.id,
            style_name=style.name,
            style_prompt=style_prompt,
            negative_prompt=negative,
            palette=palette,
            lighting=f"{mood_lighting(mood)}; {style.lighting}",
            art_direction=f"{style.art_direction}; emotional register: {mood}",
            environment="; ".join(location.description for location in locations),
            characters=characters,
            locations=locations,
            motifs=motifs,
            seed=config.scenes.seed,
            planner="deterministic",
        )

    # ------------------------------------------------------------------
    # Musical / lyric structure
    # ------------------------------------------------------------------
    def _lyric_section_for(self, lyrics: LyricsAnalysis, start: float, end: float) -> LyricSection | None:
        best: LyricSection | None = None
        best_overlap = 0.0
        for section in lyrics.sections:
            overlap = max(0.0, min(end, section.end) - max(start, section.start))
            if overlap > best_overlap:
                best_overlap = overlap
                best = section
        return best

    def _build_spans(
        self,
        audio: AudioAnalysis | None,
        lyrics: LyricsAnalysis,
        duration: float,
        config: ProjectConfig,
    ) -> list[SectionSpan]:
        spans: list[SectionSpan] = []
        if audio and audio.sections:
            for section in audio.sections:
                start = _clip(float(section.start), 0.0, duration)
                end = _clip(float(section.end), 0.0, duration)
                if end - start < 0.05:
                    continue
                lyric_section = self._lyric_section_for(lyrics, start, end)
                section_lines = [
                    line
                    for line in lyrics.lines
                    if start - 0.02 <= line.start < end - 0.02
                ]
                spans.append(
                    SectionSpan(
                        start=start,
                        end=end,
                        kind=section.kind,
                        label=section.label,
                        energy=section.energy,
                        energy_relative=section.energy_relative,
                        lines=section_lines,
                        lyric_section_id=lyric_section.id if lyric_section else None,
                        repeat_of=lyric_section.repeat_of if lyric_section else None,
                    )
                )
        elif lyrics.sections:
            for section in lyrics.sections:
                start = _clip(float(section.start), 0.0, duration)
                end = _clip(float(section.end), 0.0, duration)
                if end - start < 0.05:
                    continue
                spans.append(
                    SectionSpan(
                        start=start,
                        end=end,
                        kind=section.kind,
                        label=section.kind.replace("_", " ").title(),
                        energy=section.energy,
                        energy_relative=1.0,
                        lines=list(section.lines),
                        lyric_section_id=section.id,
                        repeat_of=section.repeat_of,
                    )
                )
        if not spans:
            spans = [
                SectionSpan(
                    start=0.0,
                    end=duration,
                    kind="unknown",
                    label="Full song",
                    energy=0.5,
                    energy_relative=1.0,
                    lines=list(lyrics.lines),
                    lyric_section_id=lyrics.sections[0].id if lyrics.sections else None,
                )
            ]

        spans.sort(key=lambda span: (span.start, span.end))
        # Fill any gaps and extend to the full duration. Instrumental gaps become
        # their own visual beats rather than being silently swallowed.
        normalized: list[SectionSpan] = []
        cursor = 0.0
        for span in spans:
            start = max(0.0, span.start)
            end = min(duration, span.end)
            if end <= start:
                continue
            if start > cursor + 0.12:
                normalized.append(
                    SectionSpan(
                        start=cursor,
                        end=start,
                        kind="instrumental",
                        label="Instrumental transition",
                        energy=min(0.45, span.energy),
                        energy_relative=0.8,
                    )
                )
            start = max(start, cursor)
            if end <= start + 0.05:
                continue
            span.start, span.end = start, end
            normalized.append(span)
            cursor = end
        if cursor < duration - 0.12:
            normalized.append(
                SectionSpan(
                    start=cursor,
                    end=duration,
                    kind="outro",
                    label="Closing instrumental",
                    energy=0.3,
                    energy_relative=0.7,
                )
            )
        elif normalized and normalized[-1].end < duration:
            normalized[-1].end = duration

        # Merge extremely short spans so they do not become unusable micro-scenes.
        min_merge = max(0.8, config.scenes.min_duration * 0.55)
        merged: list[SectionSpan] = []
        for span in normalized:
            if merged and span.end - span.start < min_merge:
                merged[-1].end = span.end
                merged[-1].lines.extend(span.lines)
                merged[-1].energy = max(merged[-1].energy, span.energy)
                continue
            if merged and merged[-1].end - merged[-1].start < min_merge:
                span.start = merged[-1].start
                span.lines = merged[-1].lines + span.lines
                span.energy = max(span.energy, merged[-1].energy)
                merged[-1] = span
                continue
            merged.append(span)
        if len(merged) > 1 and merged[0].end - merged[0].start < min_merge:
            merged[1].start = merged[0].start
            merged[1].lines = merged[0].lines + merged[1].lines
            merged = merged[1:]
        if merged:
            merged[0].start = 0.0
            merged[-1].end = duration
        return merged

    def _candidate_cuts(
        self,
        span: SectionSpan,
        audio: AudioAnalysis | None,
        lines: list[SubtitleLine],
        config: ProjectConfig,
    ) -> list[tuple[float, float]]:
        candidates: list[tuple[float, float]] = []
        # Lyric starts are strong narrative boundaries.
        for line in lines:
            if span.start + 0.2 < line.start < span.end - 0.2:
                candidates.append((line.start, 0.45 if span.kind in {"verse", "intro", "outro"} else 0.2))
        if audio:
            for beat in audio.beats:
                if span.start + 0.2 < beat.time < span.end - 0.2:
                    bonus = 0.12
                    if beat.strong:
                        bonus += 0.12
                    if beat.downbeat:
                        bonus += 0.18
                    if span.kind == "chorus":
                        bonus += 0.12
                    if config.audio_reactive.enabled and config.audio_reactive.beat_cuts and beat.downbeat:
                        bonus += 0.12
                    candidates.append((beat.time, bonus))
        deduped: dict[float, float] = {}
        for time, bonus in candidates:
            key = round(time, 2)
            deduped[key] = max(deduped.get(key, 0.0), bonus)
        return sorted(deduped.items())

    def _choose_cut(
        self,
        *,
        cursor: float,
        end: float,
        span: SectionSpan,
        candidates: list[tuple[float, float]],
        all_lines: list[SubtitleLine],
        config: ProjectConfig,
        threshold: float,
    ) -> float:
        remaining = end - cursor
        if remaining <= config.scenes.max_duration and remaining <= threshold:
            return end
        desired = cursor + config.scenes.target_duration
        lower = cursor + config.scenes.min_duration
        upper = min(end - config.scenes.min_duration * 0.55, cursor + config.scenes.max_duration)
        if upper <= lower:
            return min(end, cursor + config.scenes.max_duration)
        best_time: float | None = None
        best_score = math.inf
        for time, bonus in candidates:
            if time < lower or time > upper:
                continue
            distance = abs(time - desired) / max(1.0, config.scenes.target_duration)
            score = distance - bonus
            # Avoid cutting through the middle of a subtitle line.
            for line in all_lines:
                if line.start + 0.12 < time < line.end - 0.12:
                    score += 1.3
                    break
            # Prefer stronger boundaries later in the scene if distances tie.
            if score < best_score:
                best_score = score
                best_time = time
        cut = best_time if best_time is not None else min(max(desired, lower), upper)
        if end - cut < config.scenes.min_duration:
            cut = end
        if cut - cursor < config.scenes.min_duration * 0.9:
            cut = min(end, cursor + config.scenes.max_duration)
        if cut >= end - 0.05:
            cut = end
        return cut

    def _split_into_scenes(
        self,
        spans: list[SectionSpan],
        all_lines: list[SubtitleLine],
        audio: AudioAnalysis | None,
        config: ProjectConfig,
    ) -> list[RawScene]:
        raw_scenes: list[RawScene] = []
        threshold = max(
            config.scenes.target_duration * 1.35,
            config.scenes.min_duration * 1.7,
        )
        for span in spans:
            span_lines = [
                line for line in all_lines if span.start - 0.03 <= line.start < span.end - 0.03
            ]
            candidates = self._candidate_cuts(span, audio, span_lines, config)
            cursor = span.start
            guard = 0
            while cursor < span.end - 0.02 and guard < 200:
                guard += 1
                cut = self._choose_cut(
                    cursor=cursor,
                    end=span.end,
                    span=span,
                    candidates=candidates,
                    all_lines=all_lines,
                    config=config,
                    threshold=threshold,
                )
                if cut <= cursor + 0.05:
                    cut = min(span.end, cursor + max(1.0, config.scenes.min_duration))
                raw_scenes.append(RawScene(start=round(cursor, 3), end=round(cut, 3), span=span))
                cursor = cut
        # Guarantee full coverage and strict ordering.
        for index, raw in enumerate(raw_scenes):
            raw.start = max(0.0, raw.start)
            raw.end = max(raw.start + 0.05, raw.end)
            if index > 0:
                raw.start = max(raw.start, raw_scenes[index - 1].end)
        if raw_scenes:
            raw_scenes[-1].end = max(raw_scenes[-1].start + 0.1, spans[-1].end)
        return [raw for raw in raw_scenes if raw.end - raw.start > 0.03]

    # ------------------------------------------------------------------
    # Scene materialisation
    # ------------------------------------------------------------------
    def _assign_lines(
        self, raw_scenes: list[RawScene], lines: list[SubtitleLine]
    ) -> dict[int, list[SubtitleLine]]:
        assignment: dict[int, list[SubtitleLine]] = {index: [] for index in range(len(raw_scenes))}
        for line in lines:
            chosen: int | None = None
            for index, raw in enumerate(raw_scenes):
                if raw.start - 0.02 <= line.start < raw.end - 0.02:
                    chosen = index
                    break
            if chosen is None:
                best_overlap = 0.0
                for index, raw in enumerate(raw_scenes):
                    overlap = max(0.0, min(line.end, raw.end) - max(line.start, raw.start))
                    if overlap > best_overlap:
                        best_overlap = overlap
                        chosen = index
            if chosen is not None:
                assignment[chosen].append(line)
        return assignment

    def _scene_energy(
        self, raw: RawScene, audio: AudioAnalysis | None
    ) -> float:
        if not audio or not audio.rms.values:
            return _clip(raw.span.energy_relative * 0.6, 0.1, 1.0)
        times = audio.rms.times
        values = audio.rms.values
        window = [value for time, value in zip(times, values) if raw.start <= time <= raw.end]
        if not window:
            return 0.5
        mean = sum(window) / len(window)
        return _clip(0.25 + mean * 0.85, 0.05, 1.0)

    def _choose_location(
        self,
        span: SectionSpan,
        span_lines: list[SubtitleLine],
        context: VisualContext,
        state: dict[str, Any],
    ) -> Location:
        if span.lyric_section_id and span.lyric_section_id in state["section_locations"]:
            return state["section_locations"][span.lyric_section_id]
        if span.repeat_of and span.repeat_of in state["section_locations"]:
            location = state["section_locations"][span.repeat_of]
            if span.lyric_section_id:
                state["section_locations"][span.lyric_section_id] = location
            return location
        section_motifs = detect_motifs(
            [clean_subtitle_text(line.text) for line in span_lines],
            limit=4,
        )
        if not section_motifs:
            section_motifs = context.motifs
        chosen = context.locations[0] if context.locations else Location(name="Landscape", description="a cinematic landscape")
        for motif in section_motifs:
            match = next((location for location in context.locations if location.motif == motif), None)
            if match:
                chosen = match
                break
        if span.lyric_section_id:
            state["section_locations"][span.lyric_section_id] = chosen
        return chosen

    def _materialise_scenes(
        self,
        raw_scenes: list[RawScene],
        *,
        lyrics: LyricsAnalysis,
        audio: AudioAnalysis | None,
        context: VisualContext,
        config: ProjectConfig,
        duration: float,
    ) -> list[Scene]:
        assignment = self._assign_lines(raw_scenes, lyrics.lines)
        style = get_style(config.scenes.style_id)
        base_mood = infer_mood(
            [clean_subtitle_text(line.text) for line in lyrics.lines],
            energy=0.55,
        )
        state: dict[str, Any] = {
            "section_locations": {},
            "section_scenes": {},
            "first_scene_by_section": {},
        }
        scenes: list[Scene] = []
        protagonist = context.characters[0] if context.characters else None
        companion = context.characters[1] if len(context.characters) > 1 else None
        for index, raw in enumerate(raw_scenes):
            scene_lines = sorted(assignment.get(index, []), key=lambda line: line.start)
            span = raw.span
            lyrics_text = " / ".join(
                flatten_text(clean_subtitle_text(line.text)) for line in scene_lines
            )
            lyrics_text = lyrics_text[:800]
            section_text = [
                clean_subtitle_text(line.text)
                for line in (span.lines or scene_lines)
                if line.text.strip()
            ]
            energy = self._scene_energy(raw, audio)
            section_mood = infer_mood(section_text, energy=energy) if section_text else base_mood
            rng = _rng(config.scenes.seed, raw.start, raw.end, index)
            location = self._choose_location(span, scene_lines or span.lines, context, state)
            reference_scene: int | None = None
            reference_section = span.repeat_of
            if reference_section and reference_section in state["first_scene_by_section"]:
                reference_scene = state["first_scene_by_section"][reference_section]
            scene_keywords = extract_keywords(
                [clean_subtitle_text(line.text) for line in scene_lines], limit=5
            )
            if not scene_keywords:
                scene_keywords = context.motifs[:3]

            high = energy >= 0.62 or span.kind == "chorus"
            low = energy < 0.35 or span.kind in {"breakdown", "outro"}
            shots = SHOTS_HIGH if high else SHOTS_LOW if low else SHOTS_MID
            shot = shots[index % len(shots)]
            subject_name = protagonist.name if protagonist else "the lone figure"
            action = ACTIONS.get(span.kind, ACTIONS["unknown"])[index % len(ACTIONS.get(span.kind, ACTIONS["unknown"]))]
            location_phrase = location.description
            mood_phrase = MOOD_PHRASES.get(section_mood, "cinematic and unresolved")
            if scene_lines:
                description = (
                    f"{shot} of {subject_name} who {action} in {location_phrase}, "
                    f"a visual meditation on {', '.join(scene_keywords[:3])}. "
                    f"The moment is {mood_phrase}, carrying the song's {section_mood} undertone."
                )
            else:
                description = (
                    f"{shot} of {location_phrase}, {mood_phrase}, with {subject_name} small in the frame. "
                    f"An instrumental breath that lets the landscape carry the emotion."
                )
            if companion and section_mood == "romantic" and scene_lines:
                description += f" {companion.name} is present in the composition, held in the same light."
            if reference_scene:
                description += (
                    f" The image deliberately echoes the visual language of scene {reference_scene}, "
                    "returning to the same place with a changed emotional intensity."
                )
            description = description[:900]

            character_clause = ""
            if protagonist:
                character_clause = (
                    f"Recurring protagonist: {protagonist.name}, {protagonist.appearance}. "
                )
                if companion and section_mood == "romantic":
                    character_clause += (
                        f"Recurring companion: {companion.name}, {companion.appearance}. "
                    )
            reference_clause = (
                f"Visual continuity with scene {reference_scene}: same character, location and palette, "
                if reference_scene
                else ""
            )
            visual_prompt = (
                f"{description} {reference_clause}{character_clause}"
                f"Location continuity: {location.name} — {location.description}. "
                f"Art direction: {context.art_direction}. Lighting: {context.lighting}. "
                f"Colour palette: {', '.join(context.palette)}. "
                f"Style: {context.style_prompt}. "
                f"Visual motifs: {', '.join(scene_keywords)}. "
                "Cinematic widescreen composition, consistent character design and environment "
                "across the entire video, no text, no watermark."
            )[:3000]
            camera = self._camera_for(index, span, energy, rng)
            effects = self._effects_for(index, span, energy, style.default_effects, config, rng)
            scene = Scene(
                scene_id=index + 1,
                start=round(raw.start, 3),
                end=round(raw.end, 3),
                lyrics=lyrics_text,
                description=description,
                visual_prompt=visual_prompt,
                negative_prompt=context.negative_prompt,
                camera=camera,
                transition=TransitionPlan(type="cut", duration=0.0),
                visual_effects=effects,
                section_id=span.lyric_section_id,
                section_kind=span.kind,
                section_label=span.label,
                subtitle_indices=[line.index for line in scene_lines],
                energy=round(energy, 3),
                seed=(config.scenes.seed + (index + 1) * 997) % 2_147_483_647,
            )
            if span.lyric_section_id:
                state["section_scenes"].setdefault(span.lyric_section_id, []).append(index + 1)
                state["first_scene_by_section"].setdefault(span.lyric_section_id, index + 1)
            scenes.append(scene)
        return scenes

    def _camera_for(
        self,
        index: int,
        span: SectionSpan,
        energy: float,
        rng: random.Random,
    ) -> CameraMove:
        motions = MOTION_BY_SECTION.get(span.kind, MOTION_BY_SECTION["unknown"])
        movement = motions[index % len(motions)]
        if index % 9 == 7:
            movement = rng.choice(["rotate_cw", "rotate_ccw"])
        zoom = _clip(1.025 + energy * 0.13 + rng.uniform(0.0, 0.022), 1.02, 1.28)
        pan_x = 0.0
        pan_y = 0.0
        if movement == "pan_left":
            pan_x = -rng.uniform(0.22, 0.42)
        elif movement == "pan_right":
            pan_x = rng.uniform(0.22, 0.42)
        elif movement == "pan_up":
            pan_y = -rng.uniform(0.2, 0.36)
        elif movement == "pan_down":
            pan_y = rng.uniform(0.2, 0.36)
        elif movement in {"slow_forward", "slow_backward"}:
            pan_x = rng.uniform(-0.09, 0.09)
            pan_y = rng.uniform(-0.06, 0.06)
        rotation = 0.0
        if movement == "rotate_cw":
            rotation = rng.uniform(0.35, 0.8)
        elif movement == "rotate_ccw":
            rotation = -rng.uniform(0.35, 0.8)
        return CameraMove(
            movement=movement,  # type: ignore[arg-type]
            zoom=round(zoom, 3),
            pan_x=round(pan_x, 3),
            pan_y=round(pan_y, 3),
            rotation=round(rotation, 3),
        )

    def _effects_for(
        self,
        index: int,
        span: SectionSpan,
        energy: float,
        style_effects: tuple[str, ...],
        config: ProjectConfig,
        rng: random.Random,
    ) -> list[str]:
        effects = [effect for effect in style_effects if effect in SUPPORTED_EFFECTS]
        if energy < 0.35 and "soft_focus" not in effects and rng.random() < 0.45:
            effects.append("soft_focus")
        if energy >= 0.62:
            if rng.random() < 0.6:
                effects.append("bloom")
            if rng.random() < 0.3:
                effects.append("light_leak")
        if span.kind in {"chorus", "bridge"} and rng.random() < 0.4:
            effects.append("shake")
        if config.audio_reactive.enabled:
            if config.audio_reactive.beat_pulse and span.kind in {"chorus", "bridge"} and rng.random() < 0.72:
                effects.append("beat_pulse")
            if config.audio_reactive.bass_pulse and (span.kind == "chorus" or energy > 0.6) and rng.random() < 0.65:
                effects.append("bass_pulse")
            if (
                config.audio_reactive.particles
                and energy > 0.55
                and rng.random() < 0.5
                and index % 3 != 0
            ):
                effects.append("particles")
        if config.output.aspect_ratio == "16:9" and index % 7 == 3:
            effects.append("letterbox")
        # Keep render cost and visual noise reasonable.
        deduped = list(dict.fromkeys(effect for effect in effects if effect in SUPPORTED_EFFECTS))
        return deduped[:5]

    # ------------------------------------------------------------------
    # Transitions and validation
    # ------------------------------------------------------------------
    def _assign_transitions(
        self, scenes: list[Scene], config: ProjectConfig, audio: AudioAnalysis | None
    ) -> list[Scene]:
        if not scenes:
            return scenes
        style = get_style(config.scenes.style_id)
        reactive = config.audio_reactive.enabled and config.audio_reactive.beat_cuts
        rng = _rng(config.scenes.seed, "transitions")
        for index in range(len(scenes) - 1):
            current = scenes[index]
            following = scenes[index + 1]
            section_change = current.section_id != following.section_id
            boundary = current.end
            near_strong = False
            if audio:
                near_strong = any(
                    abs(beat.time - boundary) <= 0.18 and (beat.strong or beat.downbeat)
                    for beat in audio.beats
                )
            high = current.energy >= 0.6
            if section_change:
                choices = list(style.preferred_transitions)
                kind = choices[index % len(choices)]
                duration = 0.8 if not high else 0.5
                if high and reactive and near_strong:
                    kind = "cut"
                    duration = 0.0
            elif reactive and near_strong and high:
                kind = rng.choice(["cut", "cut", "crossfade", "slide_left"])
                duration = 0.0 if kind == "cut" else rng.uniform(0.18, 0.32)
            elif high:
                kind = rng.choice(["cut", "crossfade", "crossfade", "slide_left"])
                duration = 0.0 if kind == "cut" else rng.uniform(0.22, 0.42)
            elif current.energy < 0.32:
                kind = rng.choice(["crossfade", "dissolve", "fade_to_black"])
                duration = rng.uniform(0.65, 1.1)
            else:
                kind = rng.choice(["crossfade", "dissolve", "wipe_left", "crossfade"])
                duration = rng.uniform(0.38, 0.72)
            maximum = min(1.25, current.duration * 0.35, following.duration * 0.35)
            duration = round(min(duration, max(0.0, maximum)), 2)
            if duration <= 0.02:
                kind = "cut"
                duration = 0.0
            current.transition = TransitionPlan(type=kind, duration=duration)  # type: ignore[arg-type]
        scenes[-1].transition = TransitionPlan(type="cut", duration=0.0)
        return scenes

    def _validate_scenes(self, scenes: list[Scene], duration: float, warnings: list[str]) -> None:
        if not scenes:
            return
        for index, scene in enumerate(scenes):
            if index == 0 and scene.start > 0.05:
                scene.start = 0.0
            if index > 0 and abs(scene.start - scenes[index - 1].end) > 0.02:
                scene.start = scenes[index - 1].end
            scene.end = min(scene.end, duration)
            if scene.end <= scene.start:
                scene.end = min(duration, scene.start + 0.25)
        scenes[-1].end = duration
        for scene in scenes:
            if scene.end - scene.start < 0.5:
                warnings.append(f"Scene {scene.scene_id} is very short ({scene.duration:.2f}s).")

    def _renumber_and_validate(
        self, scenes: list[Scene], duration: float, warnings: list[str]
    ) -> list[Scene]:
        scenes.sort(key=lambda scene: (scene.start, scene.scene_id))
        for index, scene in enumerate(scenes):
            scene.scene_id = index + 1
        if scenes:
            scenes[0].start = 0.0
            scenes[-1].end = duration
            for index in range(1, len(scenes)):
                scenes[index].start = scenes[index - 1].end
            for index, scene in enumerate(scenes[:-1]):
                scenes[index].end = scenes[index + 1].start
        self._validate_scenes(scenes, duration, warnings)
        return scenes

    # ------------------------------------------------------------------
    # Optional LLM enhancement
    # ------------------------------------------------------------------
    def _build_llm_prompt(
        self,
        scenes: list[Scene],
        context: VisualContext,
        project_name: str,
        title: str,
    ) -> str:
        skeleton = [
            {
                "scene_id": scene.scene_id,
                "start": scene.start,
                "end": scene.end,
                "section": scene.section_kind,
                "lyrics": scene.lyrics,
                "existing_description": scene.description,
            }
            for scene in scenes
        ]
        characters = "\n".join(
            f"- {character.name} ({character.role}): {character.description} Appearance: {character.appearance}"
            for character in context.characters
        )
        locations = "\n".join(
            f"- {location.name}: {location.description}" for location in context.locations
        )
        return (
            f"Project: {project_name}. Song title: {title or 'untitled'}.\n"
            f"Global visual style: {context.style_prompt}\n"
            f"Art direction: {context.art_direction}\n"
            f"Palette: {', '.join(context.palette)}\n"
            f"Characters:\n{characters}\nLocations:\n{locations}\n\n"
            "Rewrite the descriptions and image prompts for the scenes below. Rules:\n"
            "1. Keep every scene_id, timing and lyric association exactly as supplied.\n"
            "2. Build one coherent visual story that follows the lyric meaning and intensity.\n"
            "3. Reuse the same characters, locations and palette; describe them identically each time.\n"
            "4. Repeated choruses should return to earlier visual concepts rather than inventing new ones.\n"
            "5. Prompts must be self-contained English text for a text-to-image model, with no text/watermarks.\n"
            "6. Do not invent identity details that contradict the supplied character descriptions.\n"
            "Return a JSON object with: scenes (array of scene_id, description, visual_prompt), "
            "art_direction (string, optional), visual_style_prompt (string, optional).\n\n"
            f"Scene skeleton:\n{json.dumps(skeleton, ensure_ascii=False)}"
        )
