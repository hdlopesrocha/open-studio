"""Pydantic v2 domain models shared by every service and the API gateway."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# ---------------------------------------------------------------------------
# Project configuration
# ---------------------------------------------------------------------------


class SubtitleStyle(StrictModel):
    font_family: str = "DejaVu Sans"
    font_size: int = Field(default=46, ge=12, le=180)
    primary_color: str = "#FFFFFF"
    highlight_color: str = "#FFD166"
    outline_color: str = "#000000"
    outline_width: float = Field(default=2.0, ge=0, le=12)
    shadow: float = Field(default=1.0, ge=0, le=12)
    background: bool = False
    background_opacity: float = Field(default=0.55, ge=0, le=1)
    background_color: str = "#000000"
    position: Literal["bottom", "center", "top"] = "bottom"
    margin_v: int = Field(default=64, ge=0, le=1000)
    max_line_width: int = Field(default=44, ge=10, le=140)
    alignment: Literal["left", "center", "right"] = "center"
    karaoke: bool = False

    @field_validator("primary_color", "highlight_color", "outline_color", "background_color")
    @classmethod
    def _valid_color(cls, value: str) -> str:
        if not HEX_COLOR.match(value):
            raise ValueError("Colour must be a #RRGGBB hex value")
        return value.upper()


class OutputConfig(StrictModel):
    resolution: Literal["720p", "1080p"] = "1080p"
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "16:9"
    fps: Literal[24, 25, 30, 60] = 30
    codec: Literal["h264", "h265"] = "h264"
    quality: Literal["draft", "standard", "high"] = "standard"
    crf: int | None = Field(default=None, ge=0, le=51)
    preset: Literal[
        "ultrafast", "superfast", "veryfast", "faster", "fast",
        "medium", "slow", "slower", "veryslow",
    ] = "medium"
    audio_bitrate: str = "192k"
    burn_subtitles: bool = True
    export_srt: bool = True
    output_filename: str = "final_video.mp4"
    output_dir: str | None = None

    @field_validator("output_filename")
    @classmethod
    def _valid_filename(cls, value: str) -> str:
        value = value.strip()
        if not value.lower().endswith((".mp4", ".mkv")):
            raise ValueError("Output filename must end in .mp4 or .mkv")
        if any(char in value for char in "/\\\0"):
            raise ValueError("Output filename must not contain path separators")
        return value

    @field_validator("audio_bitrate")
    @classmethod
    def _valid_bitrate(cls, value: str) -> str:
        if not re.match(r"^\d{2,4}k$", value):
            raise ValueError("Audio bitrate must look like 192k")
        return value

    @property
    def dimensions(self) -> tuple[int, int]:
        return output_dimensions(self.resolution, self.aspect_ratio)

    @property
    def width(self) -> int:
        return self.dimensions[0]

    @property
    def height(self) -> int:
        return self.dimensions[1]

    @property
    def effective_crf(self) -> int:
        if self.crf is not None:
            return self.crf
        return {"draft": 28, "standard": 21, "high": 16}[self.quality]


def output_dimensions(resolution: str, aspect_ratio: str) -> tuple[int, int]:
    long_edge = 1920 if resolution == "1080p" else 1280
    short_edge = 1080 if resolution == "1080p" else 720
    if aspect_ratio == "16:9":
        return long_edge, short_edge
    if aspect_ratio == "9:16":
        return short_edge, long_edge
    if aspect_ratio == "1:1":
        edge = short_edge
        return edge, edge
    return long_edge, short_edge


class SceneGenerationConfig(StrictModel):
    min_duration: float = Field(default=3.5, ge=1.0, le=60.0)
    max_duration: float = Field(default=16.0, ge=3.0, le=120.0)
    target_duration: float = Field(default=8.0, ge=2.0, le=60.0)
    max_lyric_lines_per_scene: int = Field(default=4, ge=1, le=20)
    style_id: str = "cinematic"
    visual_style_prompt: str = ""
    seed: int = Field(default=1987, ge=0, le=2_147_483_647)
    image_provider: Literal["auto", "procedural", "comfyui", "qvac", "diffusers"] = "auto"
    image_width: int | None = Field(default=None, ge=256, le=4096)
    image_height: int | None = Field(default=None, ge=256, le=4096)
    animation_backend: Literal["ffmpeg", "opencv", "ai"] = "ffmpeg"
    variants: int = Field(default=1, ge=1, le=4)
    generate_depth_maps: bool = False

    @model_validator(mode="after")
    def _check_durations(self) -> "SceneGenerationConfig":
        if self.min_duration > self.max_duration:
            raise ValueError("min_duration cannot exceed max_duration")
        self.target_duration = min(max(self.target_duration, self.min_duration), self.max_duration)
        return self


class AudioReactiveConfig(StrictModel):
    enabled: bool = True
    beat_pulse: bool = True
    bass_pulse: bool = True
    beat_cuts: bool = True
    particles: bool = False
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)


class AIConfig(StrictModel):
    llm_mode: Literal["auto", "ollama", "deterministic"] = "auto"
    marker: str = "optional"
    allow_fallback: bool = True


class ProjectConfig(StrictModel):
    output: OutputConfig = Field(default_factory=OutputConfig)
    subtitles: SubtitleStyle = Field(default_factory=SubtitleStyle)
    scenes: SceneGenerationConfig = Field(default_factory=SceneGenerationConfig)
    audio_reactive: AudioReactiveConfig = Field(default_factory=AudioReactiveConfig)
    ai: AIConfig = Field(default_factory=AIConfig)


# ---------------------------------------------------------------------------
# Audio analysis
# ---------------------------------------------------------------------------


class TimeSeries(StrictModel):
    times: list[float] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)


class BandEnergies(StrictModel):
    times: list[float] = Field(default_factory=list)
    bass: list[float] = Field(default_factory=list)
    mid: list[float] = Field(default_factory=list)
    high: list[float] = Field(default_factory=list)


class BeatEvent(StrictModel):
    time: float
    strength: float = Field(default=0.5, ge=0, le=10)
    downbeat: bool = False
    strong: bool = False


class MusicalSection(StrictModel):
    id: int
    start: float
    end: float
    label: str = "section"
    kind: Literal[
        "intro", "verse", "chorus", "bridge", "breakdown", "instrumental", "outro", "unknown"
    ] = "unknown"
    energy: float = Field(default=0.5, ge=0)
    energy_relative: float = Field(default=1.0, ge=0)
    confidence: float = Field(default=0.5, ge=0, le=1)


class OnsetEvent(StrictModel):
    time: float
    strength: float = 0.5


class AudioAnalysis(StrictModel):
    version: int = 1
    duration: float
    sample_rate: int = 22050
    tempo: float = 0.0
    beat_interval: float = 0.0
    beats: list[BeatEvent] = Field(default_factory=list)
    downbeats: list[float] = Field(default_factory=list)
    sections: list[MusicalSection] = Field(default_factory=list)
    rms: TimeSeries = Field(default_factory=TimeSeries)
    peak: TimeSeries = Field(default_factory=TimeSeries)
    bands: BandEnergies = Field(default_factory=BandEnergies)
    spectral_centroid: TimeSeries = Field(default_factory=TimeSeries)
    onsets: list[OnsetEvent] = Field(default_factory=list)
    loudness_db: float | None = None
    analysis_seconds: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class MusicalEvent(StrictModel):
    time: float
    end: float | None = None
    type: Literal["beat", "downbeat", "section", "onset", "energy_peak"]
    label: str = ""
    energy: float = 0.5


class MusicalEventCollection(StrictModel):
    version: int = 1
    duration: float
    tempo: float
    events: list[MusicalEvent] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Lyrics analysis
# ---------------------------------------------------------------------------


class SubtitleLine(StrictModel):
    index: int
    start: float
    end: float
    text: str

    @model_validator(mode="after")
    def _valid_times(self) -> "SubtitleLine":
        if self.end < self.start:
            raise ValueError(f"Subtitle #{self.index} ends before it starts")
        return self


class LyricSection(StrictModel):
    id: int
    start: float
    end: float
    kind: Literal[
        "intro", "verse", "chorus", "bridge", "breakdown", "instrumental", "outro", "unknown"
    ] = "unknown"
    lines: list[SubtitleLine] = Field(default_factory=list)
    text: str = ""
    energy: float = 0.5
    repetition_key: str | None = None
    is_repeat: bool = False
    repeat_of: int | None = None
    audio_section_id: int | None = None
    visual_hint: str = ""
    confidence: float = Field(default=0.5, ge=0, le=1)


class RepeatedPhrase(StrictModel):
    text: str
    normalized: str
    occurrences: list[int] = Field(default_factory=list)
    times: list[float] = Field(default_factory=list)


class LyricsAnalysis(StrictModel):
    version: int = 1
    duration: float | None = None
    lines: list[SubtitleLine] = Field(default_factory=list)
    sections: list[LyricSection] = Field(default_factory=list)
    repeated_phrases: list[RepeatedPhrase] = Field(default_factory=list)
    language: str = "unknown"
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Story planning
# ---------------------------------------------------------------------------


class CameraMove(StrictModel):
    movement: Literal[
        "slow_forward",
        "slow_backward",
        "pan_left",
        "pan_right",
        "pan_up",
        "pan_down",
        "rotate_cw",
        "rotate_ccw",
        "handheld",
        "parallax",
        "static",
    ] = "slow_forward"
    zoom: float = Field(default=1.08, ge=1.0, le=1.6)
    pan_x: float = Field(default=0.0, ge=-1.0, le=1.0)
    pan_y: float = Field(default=0.0, ge=-1.0, le=1.0)
    rotation: float = Field(default=0.0, ge=-3.0, le=3.0)


class TransitionPlan(StrictModel):
    type: Literal[
        "cut", "crossfade", "dissolve", "fade_to_black", "fade_to_white",
        "slide_left", "slide_right", "slide_up", "wipe_left", "wipe_right", "circle",
    ] = "crossfade"
    duration: float = Field(default=0.6, ge=0.0, le=3.0)


class Character(StrictModel):
    name: str
    role: str = "protagonist"
    description: str
    appearance: str = ""
    accent_color: str = "#F4A261"


class Location(StrictModel):
    name: str
    description: str
    motif: str = ""


class VisualContext(StrictModel):
    style_id: str = "cinematic"
    style_name: str = "Cinematic"
    style_prompt: str = ""
    negative_prompt: str = ""
    palette: list[str] = Field(default_factory=list)
    lighting: str = ""
    art_direction: str = ""
    environment: str = ""
    characters: list[Character] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    motifs: list[str] = Field(default_factory=list)
    seed: int = 1987
    planner: str = "deterministic"


class Scene(StrictModel):
    scene_id: int
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    lyrics: str = ""
    description: str = ""
    visual_prompt: str = ""
    negative_prompt: str = ""
    camera: CameraMove = Field(default_factory=CameraMove)
    transition: TransitionPlan = Field(default_factory=TransitionPlan)
    visual_effects: list[str] = Field(default_factory=list)
    section_id: int | None = None
    section_kind: str = "unknown"
    section_label: str = ""
    subtitle_indices: list[int] = Field(default_factory=list)
    energy: float = Field(default=0.5, ge=0.0, le=1.0)
    seed: int = 1
    image_path: str | None = None
    image_source: Literal["none", "procedural", "comfyui", "qvac", "diffusers", "user"] = "none"
    image_variants: list[str] = Field(default_factory=list)
    depth_map_path: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    status: Literal["planned", "image_ready", "animated", "error"] = "planned"
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _valid_times(self) -> "Scene":
        if self.end <= self.start:
            raise ValueError(f"Scene {self.scene_id} must end after it starts")
        return self

    @computed_field
    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


class SceneDocument(StrictModel):
    version: int = 1
    project_id: str
    scenes: list[Scene] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    planner: str = "deterministic"
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _unique_scene_ids(self) -> "SceneDocument":
        ids = [scene.scene_id for scene in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("Scene IDs must be unique")
        return self


class PlanResult(StrictModel):
    visual_context: VisualContext
    scenes: list[Scene]
    warnings: list[str] = Field(default_factory=list)
    planner: str = "deterministic"


# ---------------------------------------------------------------------------
# Projects and jobs
# ---------------------------------------------------------------------------


ProjectStage = Literal["created", "analyzed", "planned", "assets_ready", "animated", "rendered"]
ProjectStatus = Literal["idle", "processing", "error"]


class Project(StrictModel):
    id: str
    name: str
    title: str = ""
    artist: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    duration: float = 0.0
    audio_path: str = ""
    srt_path: str = ""
    audio_filename: str = ""
    srt_filename: str = ""
    config: ProjectConfig = Field(default_factory=ProjectConfig)
    stage: ProjectStage = "created"
    status: ProjectStatus = "idle"
    warnings: list[str] = Field(default_factory=list)
    last_error: str | None = None
    final_video: str | None = None
    final_video_external: str | None = None
    final_thumbnail: str | None = None
    cover_image: str | None = None
    scene_count: int = 0
    planner: str | None = None

    @computed_field
    @property
    def width(self) -> int:
        return self.config.output.width

    @computed_field
    @property
    def height(self) -> int:
        return self.config.output.height


class JobKind(str, Enum):
    # Public Open Studio video actions.
    analyze = "analyze"
    plan = "plan"
    images = "images"
    animate = "animate"
    render = "render"
    full = "full"
    regenerate = "regenerate"
    # Legacy/reference names kept for persisted projects and compatibility.
    analyze_audio = "analyze_audio"
    analyze_lyrics = "analyze_lyrics"
    generate_images = "generate_images"
    full_pipeline = "full_pipeline"
    regenerate_scene = "regenerate_scene"


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    paused = "paused"
    canceling = "canceling"
    canceled = "canceled"
    completed = "completed"
    failed = "failed"
    interrupted = "interrupted"


class JobLog(StrictModel):
    timestamp: datetime = Field(default_factory=utcnow)
    level: Literal["debug", "info", "warning", "error"] = "info"
    message: str
    scene_id: int | None = None


class Job(StrictModel):
    id: str
    project_id: str
    kind: JobKind
    status: JobStatus = JobStatus.queued
    progress: float = Field(default=0.0, ge=0, le=100)
    stage: str = "queued"
    message: str = ""
    current_scene: int | None = None
    scene_total: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    logs: list[JobLog] = Field(default_factory=list)
    result: dict | None = None
    cancel_requested: bool = False
    pause_requested: bool = False
    options: dict = Field(default_factory=dict)

    @computed_field
    @property
    def is_terminal(self) -> bool:
        return self.status in {
            JobStatus.completed,
            JobStatus.failed,
            JobStatus.canceled,
            JobStatus.interrupted,
        }


# ---------------------------------------------------------------------------
# API request/response helpers
# ---------------------------------------------------------------------------


class ScenePatch(StrictModel):
    description: str | None = None
    visual_prompt: str | None = None
    negative_prompt: str | None = None
    camera: CameraMove | None = None
    transition: TransitionPlan | None = None
    visual_effects: list[str] | None = None
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    lyrics: str | None = None
    depth_map_path: str | None = None
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)


class RetimeRequest(StrictModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class ReorderRequest(StrictModel):
    scene_ids: list[int] = Field(min_length=1)


class SceneRegenerateRequest(StrictModel):
    image: bool = True
    animation: bool = True
    prompt: str | None = None
    variants: int = Field(default=1, ge=1, le=4)


class RenderRequest(StrictModel):
    output: OutputConfig | None = None


class PipelineRequest(StrictModel):
    scene_ids: list[int] | None = None
    force: bool = False
    skip_images: bool = False
    skip_animation: bool = False


class AISettings(StrictModel):
    ollama_url: str = ""
    ollama_model: str = ""
    comfyui_url: str = ""
    image_workflow_path: str = ""
    video_workflow_path: str = ""
    image_provider: Literal["auto", "procedural", "comfyui", "qvac", "diffusers"] = "auto"
    animation_backend: Literal["ffmpeg", "opencv", "ai"] = "ffmpeg"
    image_steps: int = Field(default=28, ge=1, le=200)
    image_cfg: float = Field(default=6.0, ge=0.0, le=30.0)
    image_checkpoint: str = ""
    video_steps: int = Field(default=24, ge=1, le=200)
    video_cfg: float = Field(default=5.0, ge=0.0, le=30.0)
    video_checkpoint: str = ""


class ProjectSummary(StrictModel):
    id: str
    name: str
    title: str = ""
    artist: str = ""
    duration: float = 0.0
    stage: ProjectStage = "created"
    status: ProjectStatus = "idle"
    updated_at: datetime
    cover_image: str | None = None
    scene_count: int = 0
    final_video: str | None = None
    width: int
    height: int


def project_summary(project: Project) -> ProjectSummary:
    return ProjectSummary(
        id=project.id,
        name=project.name,
        title=project.title,
        artist=project.artist,
        duration=project.duration,
        stage=project.stage,
        status=project.status,
        updated_at=project.updated_at,
        cover_image=project.cover_image,
        scene_count=project.scene_count,
        final_video=project.final_video,
        width=project.width,
        height=project.height,
    )
