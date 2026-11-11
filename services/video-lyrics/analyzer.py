"""Subtitle / lyric analysis and association with musical structure."""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from pathlib import Path

from mvstudio_shared.models import (
    AudioAnalysis,
    LyricsAnalysis,
    LyricSection,
    RepeatedPhrase,
    SubtitleLine,
)
from mvstudio_shared.srt import (
    clean_subtitle_text,
    flatten_text,
    parse_srt_file_with_warnings,
)
from mvstudio_shared.text import detect_motifs, extract_keywords, infer_mood, lyric_key

GAP_SPLIT_SECONDS = 6.0
MAX_LINES_WITHOUT_AUDIO = 8


def _normalise_line(text: str) -> str:
    return lyric_key(clean_subtitle_text(text))


def _detect_language(lines: list[SubtitleLine]) -> str:
    text = " ".join(clean_subtitle_text(line.text) for line in lines).lower()
    portuguese = {
        "você", "não", "coração", "para", "meu", "minha", "eu", "nós", "estou", "sou",
        "amor", "saudade", "vida", "mundo", "quando", "sempre", "nunca", "dia", "noite",
        "cidade", "estrada", "sonho", "luz", "mar", "é", "tá", "pra", "coisa",
    }
    english = {
        "the", "you", "and", "love", "heart", "night", "day", "never", "always", "when",
        "dream", "light", "world", "city", "road", "life", "my", "your", "we", "i", "me",
    }
    words = set(re.findall(r"[a-zà-ÿ']+", text))
    pt_score = sum(1 for word in portuguese if word in words)
    en_score = sum(1 for word in english if word in words)
    if pt_score > en_score:
        return "pt"
    if en_score > pt_score:
        return "en"
    return "unknown"


def _detect_repeated_phrases(lines: list[SubtitleLine]) -> list[RepeatedPhrase]:
    counts: dict[str, list[int]] = {}
    display: dict[str, str] = {}
    times: dict[str, list[float]] = {}
    for size in range(1, 5):
        for index in range(0, len(lines) - size + 1):
            window = lines[index : index + size]
            keys = [_normalise_line(line.text) for line in window]
            if any(not key for key in keys):
                continue
            key = " ".join(keys)
            if len(key.replace(" ", "")) < 5 or len(key.split()) < (2 if size == 1 else 3):
                continue
            counts.setdefault(key, []).append(index)
            display.setdefault(key, " / ".join(clean_subtitle_text(line.text) for line in window))
            times.setdefault(key, []).append(window[0].start)
    phrases: list[RepeatedPhrase] = []
    seen_keys: set[str] = set()
    ranked = sorted(
        counts.items(),
        key=lambda item: (len(item[1]), len(item[0].split())),
        reverse=True,
    )
    for key, positions in ranked:
        if len(positions) < 2:
            continue
        # Suppress a phrase if it is a contiguous duplicate of a longer selected phrase.
        if any(key in existing or existing in key for existing in seen_keys):
            continue
        seen_keys.add(key)
        occurrences = [lines[position].index for position in positions]
        phrases.append(
            RepeatedPhrase(
                text=display[key],
                normalized=key,
                occurrences=occurrences,
                times=[round(float(value), 3) for value in times[key]],
            )
        )
        if len(phrases) >= 16:
            break
    return phrases


def _line_overlap(line: SubtitleLine, start: float, end: float) -> float:
    return max(0.0, min(line.end, end) - max(line.start, start))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _similarity(left_lines: list[SubtitleLine], right_lines: list[SubtitleLine]) -> float:
    left_text = " ".join(_normalise_line(line.text) for line in left_lines)
    right_text = " ".join(_normalise_line(line.text) for line in right_lines)
    ratio = SequenceMatcher(a=left_text, b=right_text).ratio()
    left_keys = {_normalise_line(line.text) for line in left_lines if _normalise_line(line.text)}
    right_keys = {_normalise_line(line.text) for line in right_lines if _normalise_line(line.text)}
    return max(ratio, _jaccard(left_keys, right_keys))


def _group_without_audio(
    lines: list[SubtitleLine], gap_threshold: float = GAP_SPLIT_SECONDS
) -> list[tuple[float, float, list[SubtitleLine]]]:
    if not lines:
        return []
    groups: list[list[SubtitleLine]] = []
    current: list[SubtitleLine] = [lines[0]]
    for line in lines[1:]:
        gap = line.start - current[-1].end
        if gap >= max(0.5, gap_threshold) or len(current) >= MAX_LINES_WITHOUT_AUDIO:
            groups.append(current)
            current = [line]
        else:
            current.append(line)
    groups.append(current)
    return [(group[0].start, group[-1].end, group) for group in groups]


class LyricsAnalyzer:
    def analyze(
        self,
        srt_path: str | Path,
        *,
        audio_analysis: AudioAnalysis | dict | None = None,
        gap_threshold: float = GAP_SPLIT_SECONDS,
    ) -> LyricsAnalysis:
        lines, warnings = parse_srt_file_with_warnings(srt_path)
        if not lines:
            raise ValueError("No usable lyric lines found in subtitle file")
        audio = AudioAnalysis.model_validate(audio_analysis) if isinstance(audio_analysis, dict) else audio_analysis
        duration = audio.duration if audio else max(line.end for line in lines)
        if not audio:
            warnings.append(
                "No audio analysis supplied: lyric sections are grouped by subtitle timing only, "
                "without musical section association."
            )
        if audio:
            late = [line for line in lines if line.start >= audio.duration - 0.05]
            if late:
                warnings.append(
                    f"{len(late)} subtitle cue(s) start after the audio ends; original timestamps were preserved."
                )

        language = _detect_language(lines)
        repeated_phrases = _detect_repeated_phrases(lines)

        raw_sections: list[tuple[float, float, list[SubtitleLine], int | None]] = []
        if audio and audio.sections:
            assignments: dict[int, list[SubtitleLine]] = {section.id: [] for section in audio.sections}
            for line in lines:
                best_id: int | None = None
                best_overlap = 0.0
                for section in audio.sections:
                    overlap = _line_overlap(line, section.start, section.end)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_id = section.id
                if best_id is None:
                    best_id = audio.sections[-1].id if line.start >= audio.sections[-1].start else audio.sections[0].id
                    warnings.append(
                        f"Subtitle cue #{line.index} lies outside musical sections; attached to section {best_id}."
                    )
                assignments[best_id].append(line)
            for section in audio.sections:
                raw_sections.append(
                    (section.start, section.end, sorted(assignments[section.id], key=lambda item: item.start), section.id)
                )
        else:
            for start, end, group in _group_without_audio(lines, gap_threshold):
                raw_sections.append((start, end, group, None))
            if raw_sections and raw_sections[0][0] > 0.5:
                raw_sections.insert(0, (0.0, raw_sections[0][0], [], None))
            if duration and raw_sections and raw_sections[-1][1] < duration - 0.5:
                raw_sections.append((raw_sections[-1][1], duration, [], None))

        sections: list[LyricSection] = []
        for position, (start, end, section_lines, audio_section_id) in enumerate(raw_sections):
            audio_section = None
            if audio and audio_section_id is not None:
                audio_section = next((item for item in audio.sections if item.id == audio_section_id), None)
            energy = 0.5
            energy_relative = 1.0
            if audio_section:
                energy = audio_section.energy
                energy_relative = audio_section.energy_relative
            elif audio:
                midpoint = (start + end) / 2
                if audio.sections:
                    nearest = min(audio.sections, key=lambda item: abs((item.start + item.end) / 2 - midpoint))
                    energy = nearest.energy
                    energy_relative = nearest.energy_relative

            text = "\n".join(line.text for line in section_lines)
            flat = flatten_text(text)
            repetition_key = (
                hashlib.sha1(" ".join(_normalise_line(line.text) for line in section_lines).encode("utf-8")).hexdigest()[:12]
                if section_lines
                else None
            )
            repeat_of: int | None = None
            is_repeat = False
            if section_lines:
                for previous in sections:
                    if not previous.lines:
                        continue
                    similarity = _similarity(section_lines, previous.lines)
                    if similarity >= 0.82 or (similarity >= 0.62 and len(section_lines) >= 2):
                        repeat_of = previous.repeat_of or previous.id
                        is_repeat = True
                        break
            repeated_line_count = sum(
                1
                for line in section_lines
                if any(line.index in phrase.occurrences for phrase in repeated_phrases)
            )
            repeat_ratio = repeated_line_count / len(section_lines) if section_lines else 0.0

            kind: str = "unknown"
            confidence = 0.45
            if not section_lines:
                kind = "instrumental"
                confidence = 0.7 if audio_section else 0.5
            elif is_repeat and energy_relative >= 0.85:
                kind = "chorus"
                confidence = 0.85
            elif repeat_ratio >= 0.5 and energy_relative >= 0.85:
                kind = "chorus"
                confidence = 0.75
            elif position == 0 and (energy_relative < 1.15 or len(section_lines) <= 2):
                kind = "intro"
                confidence = 0.5
            elif position == len(raw_sections) - 1 and not is_repeat:
                kind = "outro"
                confidence = 0.5
            elif audio_section:
                kind = audio_section.kind
                confidence = min(0.7, audio_section.confidence)
            elif repeat_ratio > 0:
                kind = "chorus"
                confidence = 0.55
            else:
                kind = "verse"
                confidence = 0.4

            motifs = detect_motifs([flat])
            mood = infer_mood([flat], energy=min(1.0, max(0.0, energy)))
            hint_parts = []
            if motifs:
                hint_parts.append(", ".join(motifs[:3]))
            hint_parts.append(mood)
            keywords = extract_keywords([flat], limit=5)
            if keywords:
                hint_parts.append(", ".join(keywords[:4]))

            sections.append(
                LyricSection(
                    id=position + 1,
                    start=round(float(start), 3),
                    end=round(float(end), 3),
                    kind=kind,  # type: ignore[arg-type]
                    lines=section_lines,
                    text=text,
                    energy=round(float(energy), 4),
                    repetition_key=repetition_key,
                    is_repeat=is_repeat,
                    repeat_of=repeat_of,
                    audio_section_id=audio_section_id,
                    visual_hint=" · ".join(hint_parts),
                    confidence=round(float(confidence), 3),
                )
            )

        if len(sections) == 1 and len(lines) > MAX_LINES_WITHOUT_AUDIO and not audio:
            warnings.append(
                "Subtitle file has no long pauses; consider adding audio analysis for better scene structure."
            )

        # Sanity check that every original cue is represented and unchanged.
        if len(sections) > 0:
            represented = {line.index for section in sections for line in section.lines}
            missing = [line.index for line in lines if line.index not in represented]
            if missing:
                warnings.append(
                    "Some cues could not be associated with a lyric section: "
                    + ", ".join(str(index) for index in missing[:10])
                )

        return LyricsAnalysis(
            duration=duration,
            lines=lines,
            sections=sections,
            repeated_phrases=repeated_phrases,
            language=language,
            warnings=warnings,
        )
