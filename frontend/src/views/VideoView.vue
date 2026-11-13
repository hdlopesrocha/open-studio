<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRoute } from "vue-router";
import {
  Activity,
  AlertTriangle,
  Archive,
  ArrowDown,
  ArrowUp,
  Captions,
  Check,
  ChevronRight,
  Clapperboard,
  Clock,
  Download,
  Eye,
  FileImage,
  FileText,
  FileVideo,
  Film,
  FolderOpen,
  Image as ImageIcon,
  Layers,
  Music2,
  Palette,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Save,
  Sparkles,
  Upload,
  Wand2,
  X as XIcon,
  Zap,
} from "lucide-vue-next";
import { api, downloadUrl, fileUrl, formatBytes, formatDuration, relativeTime } from "@/lib/api";
import type { Job } from "@/lib/types";
import { DEMO } from "@/lib/types";
import { demoCues, demoImagePaths, demoScenes, demoVideoCatalog, demoVideoProject } from "@/lib/demo";
import { useJobsStore } from "@/stores/jobs";
import { useSystemStore } from "@/stores/system";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import QvacView from "@/views/QvacView.vue";
import ServiceNotice from "@/components/ServiceNotice.vue";
import BaseModal from "@/components/BaseModal.vue";
import FilePicker from "@/components/FilePicker.vue";
import AudioPlayer from "@/components/AudioPlayer.vue";
import JobCard from "@/components/JobCard.vue";
import TabsBar from "@/components/TabsBar.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import EmptyState from "@/components/EmptyState.vue";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type AnyRecord = Record<string, any>;

interface Option {
  value: string;
  label: string;
  description?: string;
  requires?: string[];
}

interface EffectOption {
  id: string;
  label: string;
  description?: string;
}

interface CatalogStyle {
  id: string;
  name: string;
  description: string;
  palette: string[];
  lighting?: string;
  art_direction?: string;
  prompt_suffix?: string;
  negative_prompt?: string;
  default_effects?: string[];
  preferred_transitions?: string[];
}

interface OutputConfig {
  resolution: string;
  aspect_ratio: string;
  fps: number;
  codec: string;
  quality: string;
  crf: number | null;
  preset: string;
  audio_bitrate: string;
  burn_subtitles: boolean;
  export_srt: boolean;
  output_filename: string;
  output_dir: string | null;
}

interface SubtitleConfig {
  font_family: string;
  font_size: number;
  primary_color: string;
  highlight_color: string;
  outline_color: string;
  outline_width: number;
  shadow: number;
  background: boolean;
  background_opacity: number;
  background_color: string;
  position: string;
  margin_v: number;
  max_line_width: number;
  alignment: string;
  karaoke: boolean;
}

interface SceneGenConfig {
  min_duration: number;
  max_duration: number;
  target_duration: number;
  max_lyric_lines_per_scene: number;
  style_id: string;
  visual_style_prompt: string;
  seed: number;
  image_provider: string;
  image_width: number | null;
  image_height: number | null;
  animation_backend: string;
  variants: number;
  generate_depth_maps: boolean;
}

interface AudioReactiveConfig {
  enabled: boolean;
  beat_pulse: boolean;
  bass_pulse: boolean;
  beat_cuts: boolean;
  particles: boolean;
  intensity: number;
}

interface AIConfig {
  llm_mode: string;
  marker?: string;
  allow_fallback: boolean;
}

interface ProjectConfig {
  output: OutputConfig;
  subtitles: SubtitleConfig;
  scenes: SceneGenConfig;
  audio_reactive: AudioReactiveConfig;
  ai: AIConfig;
}

interface VideoProject {
  id: string;
  name: string;
  title: string;
  artist: string;
  duration: number;
  scene_count: number;
  stage: string;
  status?: string;
  updated_at: string;
  final_video?: string | null;
  final_thumbnail?: string | null;
  final_video_external?: string | null;
  cover_image?: string | null;
  audio_path?: string | null;
  srt_path?: string | null;
  width: number;
  height: number;
  planner?: string | null;
  warnings: string[];
  config: ProjectConfig;
}

interface VideoScene {
  scene_id: number;
  start: number;
  end: number;
  duration: number;
  kind: string;
  section_kind: string;
  section_label: string;
  description: string;
  visual_prompt: string;
  negative_prompt: string;
  camera: { movement: string; zoom: number; pan_x: number; pan_y: number; rotation: number };
  transition: { type: string; duration: number };
  visual_effects: string[];
  lyrics: string;
  status: string;
  image_path: string | null;
  thumbnail_path: string | null;
  image_source: string;
  image_variants: string[];
  depth_map_path: string | null;
  video_path: string | null;
  subtitle_indices: number[];
  seed: number;
  energy: number;
  warnings: string[];
}

interface Cue {
  index?: number;
  start: number;
  end: number;
  text: string;
}

interface VideoAsset {
  path: string;
  name?: string;
  kind?: string;
  size?: number;
  modified_at?: string;
  url?: string;
}

interface VideoCatalog {
  styles: CatalogStyle[];
  cameras: Option[];
  transitions: Option[];
  effects: EffectOption[];
  providers: Option[];
  backends: Option[];
  resolutions: Option[];
  aspects: Option[];
  fps: number[];
  codecs: Option[];
  qualities: Option[];
  presets: string[];
  audioBitrates: string[];
  subtitleFonts: string[];
  subtitlePositions: string[];
  subtitleAlignments: string[];
  plannerModes: Option[];
  defaults: { project: ProjectConfig };
  comfyui: AnyRecord;
  ollama: AnyRecord;
  aiSettings: AnyRecord;
  limits: AnyRecord;
}

interface SceneForm {
  description: string;
  visual_prompt: string;
  negative_prompt: string;
  lyrics: string;
  camera: string;
  zoom: number;
  pan_x: number;
  pan_y: number;
  rotation: number;
  transition: string;
  transition_duration: number;
  start: number;
  end: number;
  effects: string[];
  seed: number;
}

interface NewProjectDraft {
  name: string;
  title: string;
  artist: string;
  audio_path: string;
  audio_name: string;
  srt_path: string;
  srt_name: string;
  config: ProjectConfig;
  comfyui_url: string;
  image_workflow_path: string;
  video_workflow_path: string;
  image_steps: number;
  image_cfg: number;
  image_checkpoint: string;
  video_steps: number;
  video_cfg: number;
  video_checkpoint: string;
  ollama_url: string;
  ollama_model: string;
}

// ---------------------------------------------------------------------------
// Constants and helpers
// ---------------------------------------------------------------------------

const FALLBACK_CONFIG: ProjectConfig = {
  output: {
    resolution: "1080p",
    aspect_ratio: "16:9",
    fps: 30,
    codec: "h264",
    quality: "standard",
    crf: null,
    preset: "medium",
    audio_bitrate: "192k",
    burn_subtitles: true,
    export_srt: true,
    output_filename: "final_video.mp4",
    output_dir: null,
  },
  subtitles: {
    font_family: "DejaVu Sans",
    font_size: 46,
    primary_color: "#FFFFFF",
    highlight_color: "#FFD166",
    outline_color: "#000000",
    outline_width: 2,
    shadow: 1,
    background: false,
    background_opacity: 0.55,
    background_color: "#000000",
    position: "bottom",
    margin_v: 64,
    max_line_width: 44,
    alignment: "center",
    karaoke: false,
  },
  scenes: {
    min_duration: 3.5,
    max_duration: 16,
    target_duration: 8,
    max_lyric_lines_per_scene: 4,
    style_id: "cinematic",
    visual_style_prompt: "",
    seed: 1987,
    image_provider: "auto",
    image_width: null,
    image_height: null,
    animation_backend: "ffmpeg",
    variants: 1,
    generate_depth_maps: false,
  },
  audio_reactive: {
    enabled: true,
    beat_pulse: true,
    bass_pulse: true,
    beat_cuts: true,
    particles: false,
    intensity: 0.5,
  },
  ai: {
    llm_mode: "auto",
    marker: "optional",
    allow_fallback: true,
  },
};

const ACTIVE_STATUSES = new Set(["queued", "running", "canceling"]);

const STAGE_LABELS: Record<string, string> = {
  created: "Created",
  analyzed: "Analyzed",
  planned: "Planned",
  assets_ready: "Assets ready",
  animated: "Animated",
  rendered: "Rendered",
};

const ACTION_LABELS: Record<string, string> = {
  analyze: "Analyze audio & lyrics",
  plan: "Plan scenes",
  images: "Generate scene images",
  animate: "Animate scenes",
  render: "Render final video",
  full: "Full pipeline",
  regenerate: "Regenerate scene",
};

const ACTION_STEPS: Record<string, Array<{ at: number; stage: string; message: string }>> = {
  analyze: [
    { at: 0, stage: "analysis", message: "Reading the waveform and tempo grid" },
    { at: 36, stage: "analysis", message: "Detecting beats, sections and energy" },
    { at: 74, stage: "lyrics", message: "Matching lyric cues to the song" },
  ],
  plan: [
    { at: 0, stage: "planning", message: "Mapping musical sections to story beats" },
    { at: 44, stage: "planning", message: "Composing scene descriptions and camera moves" },
    { at: 78, stage: "planning", message: "Balancing pacing, palette and transitions" },
  ],
  images: [
    { at: 0, stage: "images", message: "Preparing prompts and reference palette" },
    { at: 30, stage: "images", message: "Painting scene artwork" },
    { at: 76, stage: "images", message: "Creating thumbnails and variants" },
  ],
  animate: [
    { at: 0, stage: "animation", message: "Preparing camera paths" },
    { at: 30, stage: "animation", message: "Rendering scene motion with FFmpeg" },
    { at: 78, stage: "animation", message: "Applying grain, bloom and audio pulses" },
  ],
  render: [
    { at: 0, stage: "render", message: "Assembling scene clips and transitions" },
    { at: 34, stage: "render", message: "Burning subtitles and mixing the soundtrack" },
    { at: 76, stage: "render", message: "Encoding the final master" },
  ],
  full: [
    { at: 0, stage: "analysis", message: "Analyzing audio, beats and lyric structure" },
    { at: 16, stage: "planning", message: "Planning the visual story" },
    { at: 36, stage: "images", message: "Generating scene artwork" },
    { at: 62, stage: "animation", message: "Animating camera moves and effects" },
    { at: 84, stage: "render", message: "Assembling transitions, subtitles and audio" },
  ],
  regenerate: [
    { at: 0, stage: "images", message: "Refreshing the selected scene artwork" },
    { at: 42, stage: "animation", message: "Re-rendering the scene motion" },
    { at: 82, stage: "finalizing", message: "Refreshing thumbnails and scene metadata" },
  ],
};

const PIPELINE_STEPS = [
  { key: "created", label: "Source & direction", detail: "Audio, SRT and project config" },
  { key: "analyzed", label: "Audio analysis", detail: "Tempo, beats, sections and cues" },
  { key: "planned", label: "Story plan", detail: "Scenes, prompts and camera language" },
  { key: "assets_ready", label: "Artwork", detail: "Procedural, ComfyUI, QVAC or Diffusers" },
  { key: "animated", label: "Animation", detail: "FFmpeg, OpenCV or AI image-to-video" },
  { key: "rendered", label: "Final render", detail: "Transitions, subtitles and master" },
];

const SUBTITLE_PRESETS = [
  {
    id: "clean",
    name: "Clean",
    description: "White, lightly outlined and centered.",
    style: { font_family: "DejaVu Sans", font_size: 46, primary_color: "#FFFFFF", highlight_color: "#FFD166", outline_color: "#000000", outline_width: 2, shadow: 1, background: false, karaoke: false, position: "bottom", alignment: "center" },
  },
  {
    id: "karaoke",
    name: "Karaoke",
    description: "Warm highlight with a stronger outline.",
    style: { font_family: "DejaVu Sans", font_size: 50, primary_color: "#FFFFFF", highlight_color: "#FFD166", outline_color: "#08060E", outline_width: 3, shadow: 2, background: false, karaoke: true, position: "bottom", alignment: "center" },
  },
  {
    id: "cinematic",
    name: "Cinematic",
    description: "Serif lettering with a soft shadow.",
    style: { font_family: "DejaVu Serif", font_size: 42, primary_color: "#FFF8EA", highlight_color: "#F4A261", outline_color: "#000000", outline_width: 1.5, shadow: 2, background: false, karaoke: false, position: "bottom", alignment: "center" },
  },
  {
    id: "bold",
    name: "Bold",
    description: "Larger type with a translucent box.",
    style: { font_family: "Noto Sans", font_size: 56, primary_color: "#FFFFFF", highlight_color: "#22D3EE", outline_color: "#000000", outline_width: 3, shadow: 1, background: true, background_opacity: 0.5, karaoke: false, position: "bottom", alignment: "center" },
  },
];

const IMAGE_SIZE_PRESETS = [
  { id: "auto", label: "Match the video frame", width: null as number | null, height: null as number | null },
  { id: "1024x576", label: "1024 × 576 · wide", width: 1024, height: 576 },
  { id: "1024x1024", label: "1024 × 1024 · square", width: 1024, height: 1024 },
  { id: "832x1216", label: "832 × 1216 · portrait", width: 832, height: 1216 },
  { id: "custom", label: "Custom size", width: null, height: null },
];

const CAMERA_DEMO_LABELS: Record<string, string> = {
  slow_push: "Slow push in",
  pull_back: "Slow pull out",
  slow_forward: "Slow push in",
  slow_backward: "Slow pull out",
  pan_left: "Pan left",
  pan_right: "Pan right",
  tilt_up: "Tilt up",
  pan_up: "Tilt up",
  tilt_down: "Tilt down",
  pan_down: "Tilt down",
  rotate_cw: "Slow rotate clockwise",
  rotate_ccw: "Slow rotate counter-clockwise",
  orbit: "Orbit",
  parallax: "Depth parallax",
  handheld: "Handheld drift",
  static: "Static",
};

const EFFECT_LABELS: Record<string, string> = {
  vignette: "Vignette",
  subtle_film_grain: "Subtle grain",
  film_grain: "Film grain",
  bloom: "Bloom",
  soft_focus: "Soft focus",
  light_leak: "Light leak",
  chromatic_aberration: "Chromatic aberration",
  letterbox: "Letterbox",
  shake: "Camera shake",
  particles: "Particles",
  beat_pulse: "Beat pulse",
  bass_pulse: "Bass pulse",
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function isObject(value: unknown): value is AnyRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function deepMerge<T>(base: T, patch: unknown): T {
  if (patch === undefined || patch === null) return clone(base);
  if (isObject(base) && isObject(patch)) {
    const output: AnyRecord = { ...base };
    for (const [key, value] of Object.entries(patch)) {
      output[key] = key in output ? deepMerge(output[key], value) : clone(value);
    }
    return output as T;
  }
  return clone(patch as T);
}

function titleCase(value: string): string {
  return String(value || "")
    .replace(/[_-]+/g, " ")
    .replace(/\b[a-z]/g, (letter) => letter.toUpperCase());
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

function mediaUrl(path?: string | null): string {
  if (!path) return "";
  if (/^(?:https?:|data:|blob:|\/api\/|\/demo\/)/.test(path)) return path;
  return fileUrl(path);
}

function formatClock(seconds?: number | null, decimals = 1): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(Number(seconds))) return "0:00";
  const total = Math.max(0, Number(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  const secs = remainder.toFixed(decimals).padStart(decimals > 0 ? 4 : 2, "0");
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, "0")}:${secs}` : `${minutes}:${secs}`;
}

function basename(path?: string | null): string {
  if (!path) return "";
  return path.split("/").filter(Boolean).pop() || path;
}

function hexToRgba(hex: string, alpha: number): string {
  const fallback = `rgba(0, 0, 0, ${alpha})`;
  if (!/^#[0-9a-fA-F]{6}$/.test(hex)) return fallback;
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function outputDimensions(resolution: string, aspect: string): { width: number; height: number } {
  const longEdge = resolution === "1080p" ? 1920 : 1280;
  const shortEdge = resolution === "1080p" ? 1080 : 720;
  if (aspect === "9:16") return { width: shortEdge, height: longEdge };
  if (aspect === "1:1") return { width: shortEdge, height: shortEdge };
  return { width: longEdge, height: shortEdge };
}

function aspectFromSize(width: number, height: number): string {
  if (!width || !height) return "16:9";
  const ratio = width / height;
  if (Math.abs(ratio - 1) < 0.08) return "1:1";
  if (ratio < 0.85) return "9:16";
  return "16:9";
}

function stageLabel(stage?: string | null): string {
  return STAGE_LABELS[String(stage || "created")] || titleCase(String(stage || "created"));
}

function stageTone(stage?: string | null): string {
  if (stage === "rendered") return "success";
  if (stage === "animated") return "running";
  if (stage === "planned") return "warn";
  return "";
}

function sceneTone(status?: string | null): string {
  if (status === "animated") return "success";
  if (status === "image_ready") return "running";
  if (status === "error") return "failed";
  return "queued";
}

function sectionColor(kind?: string | null): string {
  const colors: Record<string, string> = {
    intro: "#22d3ee",
    verse: "#8b5cf6",
    chorus: "#f59e0b",
    bridge: "#fb7185",
    breakdown: "#f472b6",
    instrumental: "#34d399",
    outro: "#94a3b8",
    unknown: "#64748b",
  };
  return colors[String(kind || "unknown")] || colors.unknown;
}

function cameraLabel(value?: string | null): string {
  if (!value) return "Static";
  return CAMERA_DEMO_LABELS[value] || titleCase(value.replace(/^slow_/, "slow "));
}

function transitionLabel(value?: string | null): string {
  return titleCase(String(value || "cut"));
}

function providerLabel(value?: string | null): string {
  if (value === "comfyui") return "ComfyUI";
  if (value === "qvac") return "QVAC";
  return titleCase(value || "auto");
}

function backendLabel(value?: string | null): string {
  if (value === "ffmpeg") return "FFmpeg motion";
  if (value === "opencv") return "OpenCV parallax";
  if (value === "ai") return "AI image-to-video";
  return titleCase(value || "FFmpeg");
}

// ---------------------------------------------------------------------------
// Catalog
// ---------------------------------------------------------------------------

function makeOption(value: string, label?: string, description?: string): Option {
  return { value, label: label || titleCase(value), description: description || "" };
}

function normalizeOptions(input: unknown, fallback: Option[]): Option[] {
  const items = Array.isArray(input) && input.length ? input : fallback;
  return items
    .map((item: any) => {
      if (typeof item === "string") return makeOption(item);
      const value = String(item?.value ?? item?.id ?? item?.name ?? "");
      return {
        value,
        label: String(item?.label ?? item?.name ?? titleCase(value)),
        description: String(item?.description ?? ""),
        requires: Array.isArray(item?.requires) ? item.requires.map(String) : undefined,
      };
    })
    .filter((item) => Boolean(item.value));
}

function normalizeEffects(input: unknown, fallback: EffectOption[]): EffectOption[] {
  const items = Array.isArray(input) && input.length ? input : fallback;
  return items
    .map((item: any) => {
      if (typeof item === "string") return { id: item, label: EFFECT_LABELS[item] || titleCase(item) };
      const id = String(item?.id ?? item?.value ?? "");
      return { id, label: String(item?.label ?? EFFECT_LABELS[id] ?? titleCase(id)), description: String(item?.description ?? "") };
    })
    .filter((item) => Boolean(item.id));
}

function normalizeStyles(input: unknown): CatalogStyle[] {
  const fallback: CatalogStyle[] = demoVideoCatalog.styles.map((style) => ({
    id: style.id,
    name: style.name,
    description: style.description,
    palette: [...style.palette],
  }));
  const items = Array.isArray(input) && input.length ? input : fallback;
  return items.map((item: any) => ({
    id: String(item?.id ?? item?.name ?? ""),
    name: String(item?.name ?? titleCase(String(item?.id ?? ""))),
    description: String(item?.description ?? ""),
    palette: Array.isArray(item?.palette) ? item.palette.map(String) : [],
    lighting: item?.lighting ? String(item.lighting) : "",
    art_direction: item?.art_direction ? String(item.art_direction) : "",
    prompt_suffix: item?.prompt_suffix ? String(item.prompt_suffix) : "",
    negative_prompt: item?.negative_prompt ? String(item.negative_prompt) : "",
    default_effects: Array.isArray(item?.default_effects) ? item.default_effects.map(String) : [],
    preferred_transitions: Array.isArray(item?.preferred_transitions) ? item.preferred_transitions.map(String) : [],
  }));
}

function demoCatalog(): VideoCatalog {
  const cameras = normalizeOptions(demoVideoCatalog.camera_moves, [
    makeOption("slow_forward"),
    makeOption("slow_backward"),
    makeOption("pan_left"),
    makeOption("pan_right"),
  ]).map((option) => ({ ...option, label: CAMERA_DEMO_LABELS[option.value] || option.label }));
  const effects = normalizeEffects(demoVideoCatalog.effects, []);
  const fallbackStyles = normalizeStyles(demoVideoCatalog.styles);
  return {
    styles: fallbackStyles.length ? fallbackStyles : normalizeStyles([]),
    cameras,
    transitions: normalizeOptions(demoVideoCatalog.transitions, [makeOption("cut"), makeOption("fade"), makeOption("dissolve")]),
    effects,
    providers: normalizeOptions(demoVideoCatalog.image_providers, [
      makeOption("auto", "Auto", "Best configured provider with procedural fallback."),
      makeOption("procedural", "Procedural", "Deterministic Pillow artwork. No model required."),
      makeOption("comfyui", "ComfyUI", "User-managed workflow and checkpoint."),
      makeOption("qvac", "QVAC", "Local QVAC diffusion."),
      makeOption("diffusers", "Diffusers", "Local Hugging Face pipeline."),
    ]).map((option) => ({
      ...option,
      label: { auto: "Auto", procedural: "Procedural", comfyui: "ComfyUI", qvac: "QVAC", diffusers: "Diffusers" }[option.value] || option.label,
      description: {
        auto: "Use the best configured provider, with procedural fallback when available.",
        procedural: "Deterministic Pillow artwork. No AI model or network required.",
        comfyui: "Your ComfyUI workflow, checkpoint and sampler settings.",
        qvac: "Local QVAC diffusion through the shared image service.",
        diffusers: "Local Hugging Face diffusers pipeline.",
      }[option.value] || option.description,
    })),
    backends: normalizeOptions(demoVideoCatalog.animation_backends, [makeOption("ffmpeg"), makeOption("opencv")]).map((option) => ({
      ...option,
      label: { ffmpeg: "FFmpeg", opencv: "OpenCV", ai: "AI image-to-video" }[option.value] || option.label,
      description: {
        ffmpeg: "Fast CPU camera moves, filters and audio-reactive effects.",
        opencv: "Frame-based animation with optional depth-map parallax.",
        ai: "Optional ComfyUI video workflow with FFmpeg fallback.",
      }[option.value] || option.description,
    })),
    resolutions: [
      makeOption("720p", "720p · 1280 × 720"),
      makeOption("1080p", "1080p · 1920 × 1080"),
    ],
    aspects: [
      { value: "16:9", label: "16:9 landscape" },
      { value: "9:16", label: "9:16 vertical" },
      { value: "1:1", label: "1:1 square" },
    ],
    fps: [24, 25, 30, 60],
    codecs: [makeOption("h264", "H.264 · compatibility"), makeOption("h265", "H.265 · smaller files")],
    qualities: [makeOption("draft", "Draft"), makeOption("standard", "Standard"), makeOption("high", "High")],
    presets: ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"],
    audioBitrates: ["128k", "192k", "256k", "320k"],
    subtitleFonts: ["DejaVu Sans", "DejaVu Serif", "Noto Sans", "Noto Serif", "Liberation Sans", "Liberation Serif", "Arial", "Helvetica", "Verdana", "Georgia"],
    subtitlePositions: ["bottom", "center", "top"],
    subtitleAlignments: ["left", "center", "right"],
    plannerModes: [
      { value: "auto", label: "Auto · use Ollama when available" },
      { value: "deterministic", label: "Deterministic planner · no LLM" },
      { value: "ollama", label: "Require Ollama" },
    ],
    defaults: { project: { ...clone(FALLBACK_CONFIG), scenes: { ...clone(FALLBACK_CONFIG.scenes), target_duration: 8 } } },
    comfyui: {
      url: "",
      image_workflow_path: "",
      video_workflow_path: "",
      image_steps: 28,
      image_cfg: 6,
      image_checkpoint: "",
      video_steps: 24,
      video_cfg: 5,
      video_checkpoint: "",
    },
    ollama: { url: "", model: "", description: "Optional local LLM for richer scene descriptions." },
    aiSettings: {
      ollama_url: "",
      ollama_model: "",
      comfyui_url: "",
      image_workflow_path: "",
      video_workflow_path: "",
      image_provider: "auto",
      animation_backend: "ffmpeg",
      image_steps: 28,
      image_cfg: 6,
      image_checkpoint: "",
      video_steps: 24,
      video_cfg: 5,
      video_checkpoint: "",
    },
    limits: { min_scene_duration: 1, max_scene_duration: 120, image_variants: 4, max_upload_mb: 512, max_concurrent_jobs: 2 },
  };
}

function normalizeCatalog(raw: AnyRecord): VideoCatalog {
  const demo = demoCatalog();
  const defaultsProject = deepMerge(FALLBACK_CONFIG, raw?.defaults?.project || {});
  if (isObject(raw?.defaults?.output)) defaultsProject.output = deepMerge(defaultsProject.output, raw.defaults.output);
  if (isObject(raw?.defaults?.scenes)) defaultsProject.scenes = deepMerge(defaultsProject.scenes, raw.defaults.scenes);
  if (isObject(raw?.defaults?.subtitles)) defaultsProject.subtitles = deepMerge(defaultsProject.subtitles, raw.defaults.subtitles);
  if (isObject(raw?.defaults?.audio_reactive)) defaultsProject.audio_reactive = deepMerge(defaultsProject.audio_reactive, raw.defaults.audio_reactive);
  if (isObject(raw?.defaults?.ai)) defaultsProject.ai = deepMerge(defaultsProject.ai, raw.defaults.ai);
  if (isObject(raw?.subtitle_styles?.defaults)) defaultsProject.subtitles = deepMerge(defaultsProject.subtitles, raw.subtitle_styles.defaults);
  if (isObject(raw?.audio_reactive?.defaults)) defaultsProject.audio_reactive = deepMerge(defaultsProject.audio_reactive, raw.audio_reactive.defaults);

  return {
    styles: normalizeStyles(raw?.styles),
    cameras: normalizeOptions(raw?.camera_moves, demo.cameras),
    transitions: normalizeOptions(raw?.transitions, demo.transitions),
    effects: normalizeEffects(raw?.effects, demo.effects),
    providers: normalizeOptions(raw?.image_providers, demo.providers),
    backends: normalizeOptions(raw?.animation_backends, demo.backends),
    resolutions: normalizeOptions(raw?.resolutions, demo.resolutions),
    aspects: normalizeOptions(raw?.aspect_ratios, demo.aspects),
    fps: Array.isArray(raw?.fps) && raw.fps.length ? raw.fps.map(Number) : demo.fps,
    codecs: normalizeOptions(raw?.codecs, demo.codecs),
    qualities: normalizeOptions(raw?.qualities, demo.qualities),
    presets: Array.isArray(raw?.presets) && raw.presets.length ? raw.presets.map(String) : demo.presets,
    audioBitrates: Array.isArray(raw?.audio_bitrates) && raw.audio_bitrates.length ? raw.audio_bitrates.map(String) : demo.audioBitrates,
    subtitleFonts: Array.isArray(raw?.subtitle_styles?.fonts) && raw.subtitle_styles.fonts.length ? raw.subtitle_styles.fonts.map(String) : demo.subtitleFonts,
    subtitlePositions: Array.isArray(raw?.subtitle_styles?.positions) && raw.subtitle_styles.positions.length ? raw.subtitle_styles.positions.map(String) : demo.subtitlePositions,
    subtitleAlignments: Array.isArray(raw?.subtitle_styles?.alignments) && raw.subtitle_styles.alignments.length ? raw.subtitle_styles.alignments.map(String) : demo.subtitleAlignments,
    plannerModes: normalizeOptions(raw?.planner_modes, demo.plannerModes),
    defaults: { project: defaultsProject },
    comfyui: isObject(raw?.comfyui) ? raw.comfyui : demo.comfyui,
    ollama: isObject(raw?.ollama) ? raw.ollama : demo.ollama,
    aiSettings: isObject(raw?.ai_settings) ? raw.ai_settings : demo.aiSettings,
    limits: isObject(raw?.limits) ? raw.limits : demo.limits,
  };
}

// ---------------------------------------------------------------------------
// Normalisation
// ---------------------------------------------------------------------------

function normalizeScene(raw: AnyRecord): VideoScene {
  const cameraInput = raw?.camera;
  const camera =
    typeof cameraInput === "string"
      ? { movement: cameraInput, zoom: 1.08, pan_x: 0, pan_y: 0, rotation: 0 }
      : {
          movement: String(cameraInput?.movement ?? "slow_forward"),
          zoom: Number(cameraInput?.zoom ?? 1.08),
          pan_x: Number(cameraInput?.pan_x ?? 0),
          pan_y: Number(cameraInput?.pan_y ?? 0),
          rotation: Number(cameraInput?.rotation ?? 0),
        };
  const transitionInput = raw?.transition;
  const transition =
    typeof transitionInput === "string"
      ? { type: transitionInput, duration: 0.6 }
      : {
          type: String(transitionInput?.type ?? "crossfade"),
          duration: Number(transitionInput?.duration ?? 0.6),
        };
  const start = Number(raw?.start ?? 0);
  const end = Number(raw?.end ?? start + Number(raw?.duration ?? 0));
  const effects = Array.isArray(raw?.visual_effects) ? raw.visual_effects.map(String).map((item) => (item === "grain" ? "film_grain" : item)) : [];
  const sectionKind = String(raw?.section_kind ?? raw?.kind ?? raw?.section_label ?? "unknown");
  return {
    scene_id: Number(raw?.scene_id ?? raw?.id ?? 0),
    start,
    end,
    duration: Number(raw?.duration ?? Math.max(0, end - start)),
    kind: String(raw?.kind ?? sectionKind),
    section_kind: sectionKind,
    section_label: String(raw?.section_label ?? titleCase(sectionKind)),
    description: String(raw?.description ?? ""),
    visual_prompt: String(raw?.visual_prompt ?? ""),
    negative_prompt: String(raw?.negative_prompt ?? ""),
    camera,
    transition,
    visual_effects: effects,
    lyrics: String(raw?.lyrics ?? ""),
    status: String(raw?.status ?? (raw?.video_path ? "animated" : raw?.image_path ? "image_ready" : "planned")),
    image_path: raw?.image_path ? String(raw.image_path) : null,
    thumbnail_path: raw?.thumbnail_path ? String(raw.thumbnail_path) : null,
    image_source: String(raw?.image_source ?? "none"),
    image_variants: Array.isArray(raw?.image_variants) ? raw.image_variants.map(String) : [],
    depth_map_path: raw?.depth_map_path ? String(raw.depth_map_path) : null,
    video_path: raw?.video_path ? String(raw.video_path) : null,
    subtitle_indices: Array.isArray(raw?.subtitle_indices) ? raw.subtitle_indices.map(Number) : [],
    seed: Number(raw?.seed ?? 1987),
    energy: Number(raw?.energy ?? 0.5),
    warnings: Array.isArray(raw?.warnings) ? raw.warnings.map(String) : [],
  };
}

function normalizeProject(raw: AnyRecord): VideoProject {
  const rawConfig = isObject(raw?.config) ? raw.config : {};
  const config: ProjectConfig = {
    output: deepMerge(FALLBACK_CONFIG.output, rawConfig.output || {}),
    subtitles: deepMerge(FALLBACK_CONFIG.subtitles, rawConfig.subtitles || {}),
    scenes: deepMerge(FALLBACK_CONFIG.scenes, rawConfig.scenes || {}),
    audio_reactive: deepMerge(FALLBACK_CONFIG.audio_reactive, rawConfig.audio_reactive || {}),
    ai: deepMerge(FALLBACK_CONFIG.ai, rawConfig.ai || {}),
  };
  if (!isObject(rawConfig.output)) {
    const summaryWidth = Number(rawConfig.width ?? raw?.width ?? 1920);
    const summaryHeight = Number(rawConfig.height ?? raw?.height ?? 1080);
    config.output.fps = Number(rawConfig.fps ?? config.output.fps);
    config.output.codec = String(rawConfig.codec ?? config.output.codec);
    config.output.resolution = Math.max(summaryWidth, summaryHeight) >= 1920 || Math.min(summaryWidth, summaryHeight) >= 1080 ? "1080p" : "720p";
    config.output.aspect_ratio = aspectFromSize(summaryWidth, summaryHeight);
  }
  if (!isObject(rawConfig.scenes)) {
    if (rawConfig.style_id) config.scenes.style_id = String(rawConfig.style_id);
    if (rawConfig.visual_style_prompt) config.scenes.visual_style_prompt = String(rawConfig.visual_style_prompt);
    if (rawConfig.scene_target_seconds) config.scenes.target_duration = Number(rawConfig.scene_target_seconds);
    if (rawConfig.image_provider) config.scenes.image_provider = String(rawConfig.image_provider);
    if (rawConfig.animation_backend) config.scenes.animation_backend = String(rawConfig.animation_backend);
  }
  if (!isObject(rawConfig.subtitles) && rawConfig.subtitle_style === "karaoke") {
    config.subtitles.karaoke = true;
    config.subtitles.highlight_color = "#FFD166";
    config.subtitles.font_size = 50;
  }
  if (isObject(rawConfig.audio_reactive)) {
    config.audio_reactive = deepMerge(FALLBACK_CONFIG.audio_reactive, rawConfig.audio_reactive);
  }
  const dims = outputDimensions(config.output.resolution, config.output.aspect_ratio);
  const width = Number(raw?.width ?? dims.width);
  const height = Number(raw?.height ?? dims.height);
  return {
    id: String(raw?.id ?? ""),
    name: String(raw?.name ?? raw?.id ?? ""),
    title: String(raw?.title || raw?.name || raw?.id || "Untitled video"),
    artist: String(raw?.artist ?? ""),
    duration: Number(raw?.duration ?? 0),
    scene_count: Number(raw?.scene_count ?? (Array.isArray(raw?.scenes) ? raw.scenes.length : 0)),
    stage: String(raw?.stage ?? "created"),
    status: String(raw?.status ?? "idle"),
    updated_at: String(raw?.updated_at ?? new Date().toISOString()),
    final_video: raw?.final_video ? String(raw.final_video) : null,
    final_thumbnail: raw?.final_thumbnail ? String(raw.final_thumbnail) : null,
    final_video_external: raw?.final_video_external ? String(raw.final_video_external) : null,
    cover_image: raw?.cover_image ? String(raw.cover_image) : null,
    audio_path: raw?.audio_path ? String(raw.audio_path) : null,
    srt_path: raw?.srt_path ? String(raw.srt_path) : null,
    width,
    height,
    planner: raw?.planner ? String(raw.planner) : null,
    warnings: Array.isArray(raw?.warnings) ? raw.warnings.map(String) : [],
    config,
  };
}

function normalizeCues(input: unknown): Cue[] {
  const lines = Array.isArray(input) ? input : Array.isArray((input as AnyRecord)?.lines) ? (input as AnyRecord).lines : [];
  return lines
    .map((line: AnyRecord, index: number) => ({
      index: Number(line?.index ?? index + 1),
      start: Number(line?.start ?? 0),
      end: Number(line?.end ?? 0),
      text: String(line?.text ?? ""),
    }))
    .filter((line: Cue) => Number.isFinite(line.start) && Number.isFinite(line.end) && line.end >= line.start)
    .sort((a: Cue, b: Cue) => a.start - b.start);
}

// ---------------------------------------------------------------------------
// Stores and local state
// ---------------------------------------------------------------------------

const jobs = useJobsStore();
const system = useSystemStore();
const toasts = useToastStore();

const catalog = ref<VideoCatalog>(demoCatalog());
const projects = ref<VideoProject[]>([]);
const loadingProjects = ref(true);
const currentProject = ref<VideoProject | null>(null);
const loadingProject = ref(false);
const scenes = ref<VideoScene[]>([]);
const subtitleLines = ref<Cue[]>([]);
const videoAssets = ref<VideoAsset[]>([]);
const demoProjectCache = new Map<string, { project: VideoProject; scenes: VideoScene[]; cues: Cue[]; assets: VideoAsset[] }>();
const selectedSceneId = ref<number | null>(null);
const route = useRoute();
const initialTab = typeof route.query.tab === "string" ? route.query.tab : "projects";
const tab = ref(initialTab);
watch(
  () => route.query.tab,
  (next) => {
    if (typeof next === "string" && next && next !== tab.value) tab.value = next;
  },
);
const refreshing = ref(false);

const newProjectOpen = ref(false);
const creating = ref(false);
const audioPickerOpen = ref(false);
const srtPickerOpen = ref(false);
const subtitlePreset = ref("clean");
const imageSizePreset = ref("auto");
const providerSnapshot = ref("");
const archivePath = ref("");
const archiveBusy = ref(false);

const actionBusy = ref("");
const uploadingScene = ref(false);
const reorderingScene = ref(false);
const savingScene = ref(false);
const savingConfig = ref(false);
const regenProvider = ref("auto");
const regenVariants = ref(1);

const previewTime = ref(0);
const previewPlaying = ref(false);
const imageInput = ref<HTMLInputElement | null>(null);
const depthInput = ref<HTMLInputElement | null>(null);
let previewTimer: number | null = null;
let demoJobTimer: number | null = null;

const exportForm = ref<ProjectConfig>(clone(FALLBACK_CONFIG));
const sceneForm = reactive<SceneForm>({
  description: "",
  visual_prompt: "",
  negative_prompt: "",
  lyrics: "",
  camera: "slow_forward",
  zoom: 1.08,
  pan_x: 0,
  pan_y: 0,
  rotation: 0,
  transition: "crossfade",
  transition_duration: 0.6,
  start: 0,
  end: 8,
  effects: [],
  seed: 1987,
});
let sceneBaseline = "";

const newDraft = reactive<NewProjectDraft>({
  name: "",
  title: "",
  artist: "",
  audio_path: "",
  audio_name: "",
  srt_path: "",
  srt_name: "",
  config: clone(FALLBACK_CONFIG),
  comfyui_url: "",
  image_workflow_path: "",
  video_workflow_path: "",
  image_steps: 28,
  image_cfg: 6,
  image_checkpoint: "",
  video_steps: 24,
  video_cfg: 5,
  video_checkpoint: "",
  ollama_url: "",
  ollama_model: "",
});

// ---------------------------------------------------------------------------
// Catalog, project and asset loading
// ---------------------------------------------------------------------------

async function loadCatalog(showError = false): Promise<void> {
  if (DEMO) {
    catalog.value = demoCatalog();
    return;
  }
  try {
    const raw = await api.get<AnyRecord>("/video/catalog");
    catalog.value = normalizeCatalog(raw || {});
  } catch (error: any) {
    if (showError) toasts.error(error?.message || "Could not load the video catalog");
  }
}

async function loadProjects(showError = true): Promise<void> {
  loadingProjects.value = true;
  try {
    if (DEMO) {
      const existingExtras = projects.value.filter((project) => project.id !== demoVideoProject.id);
      projects.value = [normalizeProject(demoVideoProject as AnyRecord), ...existingExtras];
      return;
    }
    const raw = await api.get<AnyRecord[]>("/video/projects");
    projects.value = (raw || []).map((item) => normalizeProject(item));
  } catch (error: any) {
    if (showError) toasts.error(error?.message || "Could not load video projects");
  } finally {
    loadingProjects.value = false;
  }
}

function applySceneDocument(data: any): void {
  const rawScenes = data?.scene_document?.scenes ?? data?.scenes ?? [];
  scenes.value = (Array.isArray(rawScenes) ? rawScenes : [])
    .map((scene: AnyRecord) => normalizeScene(scene))
    .sort((a, b) => a.start - b.start);
  if (selectedSceneId.value !== null && scenes.value.some((scene) => scene.scene_id === selectedSceneId.value)) {
    // Keep the user's selection when the scene still exists.
  } else {
    selectedSceneId.value = scenes.value[0]?.scene_id ?? null;
  }
  resetSceneForm();
}

async function loadAssets(projectId?: string): Promise<void> {
  const target = projectId || currentProject.value?.id;
  if (!target) {
    videoAssets.value = [];
    return;
  }
  if (DEMO) {
    videoAssets.value = demoAssets(currentProject.value);
    return;
  }
  try {
    const data = await api.get<{ items?: VideoAsset[] }>(`/video/projects/${target}/assets`);
    videoAssets.value = Array.isArray(data?.items) ? data.items : [];
  } catch {
    videoAssets.value = [];
  }
}

function cacheCurrentDemoProject(): void {
  const project = currentProject.value;
  if (!DEMO || !project) return;
  demoProjectCache.set(project.id, {
    project: clone(project),
    scenes: clone(scenes.value),
    cues: clone(subtitleLines.value),
    assets: clone(videoAssets.value),
  });
}

async function openProject(projectId: string, switchTab = true): Promise<void> {
  if (!projectId) return;
  if (DEMO && currentProject.value?.id === projectId) {
    if (switchTab) tab.value = "editor";
    return;
  }
  loadingProject.value = true;
  try {
    if (DEMO) {
      cacheCurrentDemoProject();
      const cached = demoProjectCache.get(projectId);
      let project: VideoProject;
      let projectScenes: VideoScene[];
      let projectCues: Cue[];
      let projectAssets: VideoAsset[];
      if (cached) {
        project = clone(cached.project);
        projectScenes = clone(cached.scenes);
        projectCues = clone(cached.cues);
        projectAssets = clone(cached.assets);
      } else {
        const summary = projects.value.find((item) => item.id === projectId);
        project = summary
          ? normalizeProject(summary as AnyRecord)
          : normalizeProject(demoVideoProject as AnyRecord);
        const demoPreview = buildDemoEditorPreview(project);
        project.scene_count = demoPreview.scenes.length;
        projectScenes = demoPreview.scenes;
        projectCues = demoPreview.cues;
        projectAssets = demoAssets(project);
      }
      currentProject.value = project;
      scenes.value = projectScenes;
      subtitleLines.value = projectCues;
      selectedSceneId.value = scenes.value[0]?.scene_id ?? null;
      exportForm.value = clone(project.config);
      regenProvider.value = project.config.scenes.image_provider || "auto";
      regenVariants.value = Math.max(1, Number(project.config.scenes.variants || 1));
      archivePath.value = "";
      videoAssets.value = projectAssets;
      resetSceneForm();
      previewTime.value = scenes.value[0]?.start ?? 0;
      if (switchTab) tab.value = "editor";
      syncProjectRecord();
      return;
    }

    const previousSelection = selectedSceneId.value;
    const [projectResult, scenesResult, lyricsResult, assetsResult] = await Promise.allSettled([
      api.get<AnyRecord>(`/video/projects/${projectId}`),
      api.get<AnyRecord>(`/video/projects/${projectId}/scenes`),
      api.get<AnyRecord>(`/video/projects/${projectId}/analysis/lyrics`),
      api.get<{ items?: VideoAsset[] }>(`/video/projects/${projectId}/assets`),
    ]);
    if (projectResult.status !== "fulfilled") {
      throw projectResult.reason;
    }
    const project = normalizeProject(projectResult.value);
    currentProject.value = project;
    const rawScenes = scenesResult.status === "fulfilled" ? scenesResult.value?.scenes ?? [] : [];
    scenes.value = (Array.isArray(rawScenes) ? rawScenes : []).map((scene: AnyRecord) => normalizeScene(scene)).sort((a, b) => a.start - b.start);
    subtitleLines.value = lyricsResult.status === "fulfilled" ? normalizeCues(lyricsResult.value as AnyRecord) : [];
    videoAssets.value = assetsResult.status === "fulfilled" && Array.isArray(assetsResult.value?.items) ? assetsResult.value.items || [] : [];
    selectedSceneId.value = scenes.value.some((scene) => scene.scene_id === previousSelection)
      ? previousSelection
      : scenes.value[0]?.scene_id ?? null;
    exportForm.value = clone(project.config);
    regenProvider.value = project.config.scenes.image_provider || "auto";
    regenVariants.value = Math.max(1, Number(project.config.scenes.variants || 1));
    archivePath.value = "";
    resetSceneForm();
    previewTime.value = selectedScene.value?.start ?? 0;
    if (switchTab) tab.value = "editor";
    syncProjectRecord();
  } catch (error: any) {
    toasts.error(error?.message || "Could not open the video project");
  } finally {
    loadingProject.value = false;
  }
}

function syncProjectRecord(): void {
  const project = currentProject.value;
  if (!project) return;
  const index = projects.value.findIndex((item) => item.id === project.id);
  if (index >= 0) projects.value[index] = project;
  else projects.value = [project, ...projects.value];
}

async function refreshAll(): Promise<void> {
  refreshing.value = true;
  try {
    await jobs.refresh();
    if (DEMO) {
      toasts.success("Video studio refreshed");
      return;
    }
    await loadCatalog(true);
    await loadProjects(false);
    if (currentProject.value) await openProject(currentProject.value.id, false);
    else if (projects.value[0]) await openProject(projects.value[0].id, false);
    toasts.success("Video studio refreshed");
  } catch (error: any) {
    toasts.error(error?.message || "Refresh failed");
  } finally {
    refreshing.value = false;
  }
}

// ---------------------------------------------------------------------------
// Derived project metadata
// ---------------------------------------------------------------------------

const videoService = computed(() => system.service("video"));
const videoWorkerOnline = computed(() => DEMO || !system.status || videoService.value?.online === true);
const qvacService = computed(() => system.service("qvac"));
const qvacOnline = computed(() => DEMO || !system.status || qvacService.value?.online === true);

const tabs = computed(() => [
  ...(videoWorkerOnline.value ? [
    { id: "projects", label: "Projects", count: projects.value.length },
    { id: "editor", label: "Editor" },
    { id: "render", label: "Render queue", count: videoJobs.value.filter((job) => ACTIVE_STATUSES.has(job.status)).length },
  ] : []),
  ...(qvacOnline.value ? [{ id: "qvac", label: "QVAC" }] : []),
]);
const selectedScene = computed<VideoScene | null>(() => {
  if (!scenes.value.length) return null;
  return scenes.value.find((scene) => scene.scene_id === selectedSceneId.value) || scenes.value[0] || null;
});

const selectedSceneIndex = computed(() => (selectedScene.value ? scenes.value.findIndex((scene) => scene.scene_id === selectedScene.value?.scene_id) : -1));
const videoJobs = computed(() => jobs.items.filter((job) => job.component === "video").sort((a, b) => b.created_at.localeCompare(a.created_at)));
// Keep this after videoJobs: immediate tab evaluation reads the job-derived count.
watch(tabs, (items) => {
  if (!items.some((item) => item.id === tab.value)) tab.value = items[0]?.id || "projects";
}, { immediate: true });
const projectVideoJobs = computed(() => {
  const project = currentProject.value;
  if (!project) return [];
  return videoJobs.value.filter((job) => String(job.params?.project_id ?? job.params?.projectId ?? "") === project.id);
});
const currentJob = computed<Job | null>(() => {
  const active = projectVideoJobs.value.find((job) => ACTIVE_STATUSES.has(job.status));
  return active || projectVideoJobs.value[0] || null;
});
const isCurrentJobActive = computed(() => Boolean(currentJob.value && ACTIVE_STATUSES.has(currentJob.value.status)));
const actionsDisabled = computed(() => Boolean(actionBusy.value) || (!DEMO && isCurrentJobActive.value));
const editorLocked = computed(() => !DEMO && isCurrentJobActive.value);

const videoQueue = computed<AnyRecord | null>(() => {
  const found = jobs.queues.find((queue: AnyRecord) => queue.component === "video");
  return found || null;
});

const videoJobStats = computed(() => ({
  queued: videoJobs.value.filter((job) => job.status === "queued").length,
  running: videoJobs.value.filter((job) => job.status === "running" || job.status === "canceling").length,
  completed: videoJobs.value.filter((job) => job.status === "completed").length,
  failed: videoJobs.value.filter((job) => job.status === "failed" || job.status === "canceled").length,
}));

const queueMetrics = computed(() => ({
  concurrency: Number(videoQueue.value?.concurrency ?? 2),
  queued: Number(videoQueue.value?.queued ?? videoJobStats.value.queued),
  running: Number(videoQueue.value?.running ?? videoJobStats.value.running),
  completed: Number(videoQueue.value?.completed ?? videoJobStats.value.completed),
  failed: Number(videoQueue.value?.failed ?? videoJobStats.value.failed),
}));

const queueUtilization = computed(() => {
  const metrics = queueMetrics.value;
  const capacity = Math.max(1, metrics.concurrency);
  return Math.min(100, Math.round(((metrics.running + metrics.queued) / capacity) * 100));
});

const projectStats = computed(() => ({
  projects: projects.value.length,
  scenes: projects.value.reduce((sum, project) => sum + (project.scene_count || 0), 0),
  rendered: projects.value.filter((project) => project.stage === "rendered" || Boolean(project.final_video)).length,
  active: videoJobs.value.filter((job) => ACTIVE_STATUSES.has(job.status)).length,
}));

function demoPosterFor(projectId: string): string {
  if (projectId === demoVideoProject.id) return "/demo/film-01.jpg";
  let hash = 0;
  for (let index = 0; index < projectId.length; index += 1) hash = (hash * 31 + projectId.charCodeAt(index)) | 0;
  return demoImagePaths[Math.abs(hash) % demoImagePaths.length] || "/demo/film-01.jpg";
}

const failedPosters = ref<Record<string, boolean>>({});

function cardPoster(project: VideoProject): string {
  if (failedPosters.value[project.id]) return "";
  if (DEMO) return demoPosterFor(project.id);
  if (project.cover_image) return mediaUrl(project.cover_image);
  if (project.final_thumbnail) return mediaUrl(project.final_thumbnail);
  return "";
}

function markPosterFailed(project: VideoProject): void {
  failedPosters.value = { ...failedPosters.value, [project.id]: true };
}

function projectProgress(project: VideoProject): number {
  const index = PIPELINE_STEPS.findIndex((step) => step.key === project.stage);
  const safeIndex = index < 0 ? 0 : index;
  return Math.round((safeIndex / Math.max(1, PIPELINE_STEPS.length - 1)) * 100);
}

function currentStyleNameFor(project: VideoProject): string {
  return catalog.value.styles.find((style) => style.id === project.config.scenes.style_id)?.name || titleCase(project.config.scenes.style_id || "cinematic");
}

function cameraHint(value: string): string {
  return catalog.value.cameras.find((camera) => camera.value === value)?.description || "Camera movement is applied to the still artwork during animation.";
}

const projectStageIndex = computed(() => {
  const stage = currentProject.value?.stage || "created";
  const index = PIPELINE_STEPS.findIndex((step) => step.key === stage);
  return index < 0 ? 0 : index;
});

const currentStyle = computed<CatalogStyle | null>(() => {
  const styleId = (currentProject.value?.config.scenes.style_id || exportForm.value.scenes.style_id || "").toString();
  return catalog.value.styles.find((style) => style.id === styleId) || catalog.value.styles[0] || null;
});

const currentStyleName = computed(() => currentStyle.value?.name || titleCase(currentProject.value?.config.scenes.style_id || "cinematic"));
const currentProviderLabel = computed(() => catalog.value.providers.find((provider) => provider.value === (currentProject.value?.config.scenes.image_provider || "auto"))?.label || providerLabel(currentProject.value?.config.scenes.image_provider));
const currentBackendLabel = computed(() => catalog.value.backends.find((backend) => backend.value === (currentProject.value?.config.scenes.animation_backend || "ffmpeg"))?.label || backendLabel(currentProject.value?.config.scenes.animation_backend));

const projectPoster = computed(() => {
  const project = currentProject.value;
  if (!project) return "";
  if (DEMO) return demoPosterFor(project.id);
  if (project.final_thumbnail) return mediaUrl(project.final_thumbnail);
  if (project.cover_image) return mediaUrl(project.cover_image);
  const firstSceneImage = scenes.value.find((scene) => Boolean(scene.image_path))?.image_path;
  return firstSceneImage ? mediaUrl(firstSceneImage) : "";
});

const previewStageStyle = computed(() => {
  const aspect = exportForm.value.output.aspect_ratio || currentProject.value?.config.output.aspect_ratio || "16:9";
  if (aspect === "9:16") return { aspectRatio: "9 / 16", maxWidth: "340px", margin: "0 auto" };
  if (aspect === "1:1") return { aspectRatio: "1 / 1", maxWidth: "520px", margin: "0 auto" };
  return { aspectRatio: "16 / 9" };
});

const previewDuration = computed(() => Math.max(1, Number(currentProject.value?.duration || 0)));
const showFinalVideo = computed(() => !DEMO && Boolean(currentProject.value?.final_video));
const finalVideoSrc = computed(() => fileUrl(currentProject.value?.final_video || ""));
const currentThumbnail = computed(() => (DEMO ? "" : currentProject.value?.final_thumbnail ? mediaUrl(currentProject.value.final_thumbnail) : ""));
const audioSource = computed(() => currentProject.value?.audio_path || (DEMO ? "music/nocturno/master/nocturno-master.wav" : ""));
const audioDownloadPath = computed(() => currentProject.value?.audio_path || null);

const previewActiveCue = computed<Cue | null>(() => {
  const time = previewTime.value;
  const active = subtitleLines.value.find((cue) => time >= cue.start && time <= cue.end);
  if (active) return active;
  return DEMO ? subtitleLines.value[0] || null : null;
});

const previewLine = computed(() => {
  if (previewActiveCue.value?.text) return previewActiveCue.value.text;
  if (selectedScene.value?.lyrics) return selectedScene.value.lyrics;
  return DEMO ? "A cidade fecha os olhos devagar" : "";
});

const subtitleProgress = computed(() => {
  const cue = previewActiveCue.value;
  if (!cue) return 0;
  if (previewTime.value < cue.start || previewTime.value > cue.end) return 0;
  return Math.max(0, Math.min(1, (previewTime.value - cue.start) / Math.max(0.1, cue.end - cue.start)));
});

const previewSubtitleStyle = computed(() => {
  const style = exportForm.value.subtitles;
  return {
    color: style.karaoke ? style.highlight_color : style.primary_color,
    fontFamily: style.font_family,
    fontSize: `${Math.max(15, Math.min(34, Number(style.font_size || 46) * 0.54))}px`,
    WebkitTextStroke: `${Math.max(0.5, Number(style.outline_width || 0) * 0.45)}px ${style.outline_color}`,
    textShadow: Number(style.shadow || 0) > 0 ? `0 2px ${Math.max(4, Number(style.shadow) * 5)}px rgba(0,0,0,.85)` : "none",
    background: style.background ? hexToRgba(style.background_color, Number(style.background_opacity || 0.55)) : "transparent",
    padding: style.background ? "6px 13px" : "0",
    borderRadius: style.background ? "8px" : "0",
  };
});

const subtitlePositionClass = computed(() => `subtitle-${exportForm.value.subtitles.position || "bottom"}`);

const sceneFormDuration = computed(() => Math.max(0, Number(sceneForm.end) - Number(sceneForm.start)));
const maxSceneEnd = computed(() => {
  const scene = selectedScene.value;
  if (!scene) return previewDuration.value;
  const index = selectedSceneIndex.value;
  const next = index >= 0 ? scenes.value[index + 1] : undefined;
  return next ? Math.max(scene.start + 0.5, next.end - 0.5) : Math.max(scene.start + 0.5, previewDuration.value);
});

const sceneBaselineValue = computed(() => JSON.stringify(buildScenePatch()));
const sceneDirty = computed(() => Boolean(selectedScene.value) && sceneBaselineValue.value !== sceneBaseline);
const sceneVariants = computed(() => {
  const scene = selectedScene.value;
  if (!scene) return [] as string[];
  return Array.from(new Set([scene.image_path, ...(scene.image_variants || [])].filter(Boolean) as string[]));
});
const maxSceneVariants = computed(() => Number(catalog.value.limits?.image_variants ?? 4));

const selectedSceneImage = computed(() => (selectedScene.value ? mediaUrl(selectedScene.value.image_path || selectedScene.value.thumbnail_path) : ""));
const editorCover = computed(() => projectPoster.value || mediaUrl(currentProject.value?.cover_image) || "");

const currentJobWarnings = computed(() => {
  const combined = [...(currentJob.value?.warnings || []), ...(currentProject.value?.warnings || [])];
  return Array.from(new Set(combined.filter(Boolean)));
});

const currentJobLogs = computed<Array<{ level: string; message: string; timestamp?: string }>>(() => {
  const job = currentJob.value;
  if (!job) return [];
  const rawLogs = (job as any).logs;
  if (Array.isArray(rawLogs) && rawLogs.length) {
    return rawLogs.slice(-24).map((entry: AnyRecord) => ({
      level: String(entry.level ?? "info"),
      message: String(entry.message ?? ""),
      timestamp: entry.timestamp ? String(entry.timestamp) : undefined,
    }));
  }
  const lines: Array<{ level: string; message: string; timestamp?: string }> = [];
  if (job.created_at) lines.push({ level: "info", message: `Job ${job.id} created`, timestamp: job.created_at });
  if (job.started_at) lines.push({ level: "info", message: `${ACTION_LABELS[job.action] || titleCase(job.action)} started`, timestamp: job.started_at });
  if (job.message) lines.push({ level: job.error ? "error" : "info", message: `${job.stage || "working"} — ${job.message}` });
  for (const warning of job.warnings || []) lines.push({ level: "warning", message: warning });
  if (job.error) lines.push({ level: "error", message: job.error });
  if (job.finished_at && job.status === "completed") lines.push({ level: "success", message: "Assets written to shared storage", timestamp: job.finished_at });
  return lines;
});

// ---------------------------------------------------------------------------
// Timeline and preview
// ---------------------------------------------------------------------------

const timelineMarkers = computed(() => {
  const total = previewDuration.value;
  return [0, 0.25, 0.5, 0.75, 1].map((ratio) => ({ ratio, label: formatClock(total * ratio, 0) }));
});

const previewPercent = computed(() => Math.min(100, (previewTime.value / previewDuration.value) * 100));
const previewCuePercent = computed(() => Math.max(4, subtitleProgress.value * 100));

function sceneLeft(scene: VideoScene): string {
  return `${Math.max(0, (scene.start / previewDuration.value) * 100)}%`;
}

function sceneWidth(scene: VideoScene): string {
  return `${Math.max(0.5, ((scene.end - scene.start) / previewDuration.value) * 100)}%`;
}

function cueLeft(cue: Cue): string {
  return `${Math.max(0, (cue.start / previewDuration.value) * 100)}%`;
}

function cueWidth(cue: Cue): string {
  return `${Math.max(0.25, ((cue.end - cue.start) / previewDuration.value) * 100)}%`;
}

function selectScene(sceneId: number): void {
  selectedSceneId.value = sceneId;
  const scene = scenes.value.find((item) => item.scene_id === sceneId);
  if (scene) previewTime.value = scene.start;
}

function startPreview(): void {
  if (showFinalVideo.value) return;
  stopPreview();
  previewPlaying.value = true;
  previewTimer = window.setInterval(() => {
    const next = previewTime.value + 0.18;
    if (next >= previewDuration.value) {
      previewTime.value = 0;
      stopPreview();
      return;
    }
    previewTime.value = next;
  }, 120);
}

function stopPreview(): void {
  previewPlaying.value = false;
  if (previewTimer !== null) {
    window.clearInterval(previewTimer);
    previewTimer = null;
  }
}

function togglePreview(): void {
  if (previewPlaying.value) stopPreview();
  else startPreview();
}

function seekPreview(value: number): void {
  previewTime.value = Math.max(0, Math.min(previewDuration.value, Number(value) || 0));
}

function onPreviewScrub(event: Event): void {
  seekPreview(Number((event.target as HTMLInputElement).value));
}

function onTimelineClick(event: MouseEvent): void {
  const target = event.currentTarget as HTMLElement;
  const rect = target.getBoundingClientRect();
  if (!rect.width) return;
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  previewTime.value = ratio * previewDuration.value;
}

function sceneTimeRange(scene: VideoScene): string {
  return `${formatClock(scene.start, 1)} – ${formatClock(scene.end, 1)}`;
}

function logTime(timestamp?: string): string {
  if (!timestamp) return "—";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function setExportCrf(event: Event): void {
  const value = (event.target as HTMLInputElement).value;
  exportForm.value.output.crf = value === "" ? null : Number(value);
}

// ---------------------------------------------------------------------------
// Scene editor
// ---------------------------------------------------------------------------

function buildScenePatch(): AnyRecord {
  return {
    description: sceneForm.description,
    visual_prompt: sceneForm.visual_prompt,
    negative_prompt: sceneForm.negative_prompt,
    lyrics: sceneForm.lyrics,
    camera: {
      movement: sceneForm.camera,
      zoom: Number(sceneForm.zoom || 1.08),
      pan_x: Number(sceneForm.pan_x || 0),
      pan_y: Number(sceneForm.pan_y || 0),
      rotation: Number(sceneForm.rotation || 0),
    },
    transition: {
      type: sceneForm.transition,
      duration: Number(sceneForm.transition_duration || 0),
    },
    visual_effects: [...sceneForm.effects],
    end: Number(sceneForm.end || 0),
    seed: Number(sceneForm.seed || 0),
  };
}

function resetSceneForm(): void {
  const scene = selectedScene.value;
  if (!scene) {
    sceneBaseline = "";
    return;
  }
  sceneForm.description = scene.description;
  sceneForm.visual_prompt = scene.visual_prompt;
  sceneForm.negative_prompt = scene.negative_prompt;
  sceneForm.lyrics = scene.lyrics;
  sceneForm.camera = scene.camera?.movement || "slow_forward";
  sceneForm.zoom = Number(scene.camera?.zoom ?? 1.08);
  sceneForm.pan_x = Number(scene.camera?.pan_x ?? 0);
  sceneForm.pan_y = Number(scene.camera?.pan_y ?? 0);
  sceneForm.rotation = Number(scene.camera?.rotation ?? 0);
  sceneForm.transition = scene.transition?.type || "crossfade";
  sceneForm.transition_duration = Number(scene.transition?.duration ?? 0.6);
  sceneForm.start = Number(scene.start || 0);
  sceneForm.end = Number(scene.end || scene.start + 8);
  sceneForm.effects = [...(scene.visual_effects || [])];
  sceneForm.seed = Number(scene.seed || 1987);
  sceneBaseline = JSON.stringify(buildScenePatch());
}

function toggleEffect(effectId: string): void {
  const index = sceneForm.effects.indexOf(effectId);
  if (index >= 0) sceneForm.effects.splice(index, 1);
  else sceneForm.effects.push(effectId);
}

function replaceScene(updated: VideoScene): void {
  scenes.value = scenes.value.map((scene) => (scene.scene_id === updated.scene_id ? updated : scene)).sort((a, b) => a.start - b.start);
  selectedSceneId.value = updated.scene_id;
  resetSceneForm();
}

async function saveScene(silent = false): Promise<boolean> {
  const project = currentProject.value;
  const scene = selectedScene.value;
  if (!project || !scene || savingScene.value) return false;
  if (sceneForm.end <= sceneForm.start + 0.4) {
    if (!silent) toasts.error("A scene must last at least 0.4 seconds");
    return false;
  }
  if (sceneForm.end > maxSceneEnd.value + 0.001) {
    if (!silent) toasts.error("The scene would overlap the next scene. Shorten it slightly.");
    return false;
  }
  savingScene.value = true;
  try {
    if (DEMO) {
      const updated: VideoScene = {
        ...scene,
        description: sceneForm.description,
        visual_prompt: sceneForm.visual_prompt,
        negative_prompt: sceneForm.negative_prompt,
        lyrics: sceneForm.lyrics,
        camera: buildScenePatch().camera,
        transition: buildScenePatch().transition,
        visual_effects: [...sceneForm.effects],
        end: Number(sceneForm.end),
        duration: Number(sceneForm.end) - Number(sceneForm.start),
        seed: Number(sceneForm.seed),
      };
      replaceScene(updated);
      if (currentProject.value) {
        currentProject.value = { ...project, stage: project.stage === "rendered" ? "rendered" : "assets_ready", status: "idle", updated_at: new Date().toISOString() };
        syncProjectRecord();
      }
      if (!silent) toasts.success(`Scene ${scene.scene_id} saved`);
      return true;
    }
    const response = await api.put<AnyRecord>(`/video/projects/${project.id}/scenes/${scene.scene_id}`, buildScenePatch());
    applySceneDocument(response);
    currentProject.value = { ...project, stage: "assets_ready", status: "idle", updated_at: new Date().toISOString() };
    syncProjectRecord();
    if (!silent) toasts.success(`Scene ${scene.scene_id} saved`);
    return true;
  } catch (error: any) {
    if (!silent) toasts.error(error?.message || "Could not save the scene");
    return false;
  } finally {
    savingScene.value = false;
  }
}

async function moveScene(direction: -1 | 1): Promise<void> {
  const project = currentProject.value;
  const scene = selectedScene.value;
  if (!project || !scene || reorderingScene.value) return;
  const ordered = [...scenes.value].sort((a, b) => a.start - b.start);
  const index = ordered.findIndex((item) => item.scene_id === scene.scene_id);
  const targetIndex = index + direction;
  if (index < 0 || targetIndex < 0 || targetIndex >= ordered.length) return;
  const swappedIds = ordered.map((item) => item.scene_id);
  [swappedIds[index], swappedIds[targetIndex]] = [swappedIds[targetIndex], swappedIds[index]];
  reorderingScene.value = true;
  try {
    if (DEMO) {
      const first = ordered[index];
      const second = ordered[targetIndex];
      const contentKeys: Array<keyof VideoScene> = [
        "description", "visual_prompt", "negative_prompt", "lyrics", "image_path", "thumbnail_path",
        "image_source", "image_variants", "depth_map_path", "video_path", "status", "camera", "transition",
        "visual_effects", "seed", "section_kind", "section_label", "kind", "warnings",
      ];
      const firstCopy = { ...first };
      for (const key of contentKeys) {
        (first as AnyRecord)[key] = (second as AnyRecord)[key];
        (second as AnyRecord)[key] = (firstCopy as AnyRecord)[key];
      }
      scenes.value = ordered;
      resetSceneForm();
      toasts.success("Scene content reordered");
      return;
    }
    const response = await api.post<AnyRecord>(`/video/projects/${project.id}/scenes/reorder`, { scene_ids: swappedIds });
    applySceneDocument(response);
    currentProject.value = { ...project, stage: "assets_ready", status: "idle", updated_at: new Date().toISOString() };
    syncProjectRecord();
    toasts.success("Scene content reordered");
  } catch (error: any) {
    toasts.error(error?.message || "Could not reorder scenes");
  } finally {
    reorderingScene.value = false;
  }
}

async function chooseVariant(path: string): Promise<void> {
  const project = currentProject.value;
  const scene = selectedScene.value;
  if (!project || !scene) return;
  if (DEMO) {
    replaceScene({
      ...scene,
      image_path: path,
      thumbnail_path: null,
      image_source: "user",
      status: scene.video_path ? scene.status : "image_ready",
    });
    toasts.success("Scene image selected");
    return;
  }
  try {
    const response = await api.post<AnyRecord>(`/video/projects/${project.id}/scenes/${scene.scene_id}/select-image`, { path });
    applySceneDocument(response);
    currentProject.value = { ...project, stage: "assets_ready", status: "idle", updated_at: new Date().toISOString() };
    syncProjectRecord();
    toasts.success("Scene image selected");
  } catch (error: any) {
    toasts.error(error?.message || "Could not select the image");
  }
}

function requestImageUpload(): void {
  if (!selectedScene.value || uploadingScene.value) return;
  imageInput.value?.click();
}

function requestDepthUpload(): void {
  if (!selectedScene.value || uploadingScene.value) return;
  depthInput.value?.click();
}

async function uploadSceneImage(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  const project = currentProject.value;
  const scene = selectedScene.value;
  if (!file || !project || !scene) return;
  if (DEMO) {
    const url = URL.createObjectURL(file);
    replaceScene({
      ...scene,
      image_path: url,
      thumbnail_path: null,
      image_source: "user",
      image_variants: [url, ...(scene.image_variants || [])],
      status: "image_ready",
    });
    toasts.success("Image uploaded to the scene");
    return;
  }
  uploadingScene.value = true;
  try {
    const form = new FormData();
    form.append("image", file);
    const response = await api.post<AnyRecord>(`/video/projects/${project.id}/scenes/${scene.scene_id}/image`, form);
    applySceneDocument(response);
    currentProject.value = { ...project, stage: "assets_ready", status: "idle" };
    syncProjectRecord();
    toasts.success("Scene image uploaded");
  } catch (error: any) {
    toasts.error(error?.message || "Could not upload the image");
  } finally {
    uploadingScene.value = false;
  }
}

async function uploadSceneDepth(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  const project = currentProject.value;
  const scene = selectedScene.value;
  if (!file || !project || !scene) return;
  if (DEMO) {
    replaceScene({ ...scene, depth_map_path: file.name });
    toasts.success("Depth map uploaded");
    return;
  }
  uploadingScene.value = true;
  try {
    const form = new FormData();
    form.append("image", file);
    const response = await api.post<AnyRecord>(`/video/projects/${project.id}/scenes/${scene.scene_id}/depth-map`, form);
    applySceneDocument(response);
    currentProject.value = { ...project, stage: "assets_ready", status: "idle", updated_at: new Date().toISOString() };
    syncProjectRecord();
    toasts.success("Depth map uploaded");
  } catch (error: any) {
    toasts.error(error?.message || "Could not upload the depth map");
  } finally {
    uploadingScene.value = false;
  }
}

// ---------------------------------------------------------------------------
// Job submission
// ---------------------------------------------------------------------------

function demoAssets(project: VideoProject | null): VideoAsset[] {
  if (!project) return [];
  const prefix = `video/projects/${project.id}`;
  const hasMaster = Boolean(project.final_video) || project.stage === "rendered";
  const assets: VideoAsset[] = [];
  if (hasMaster) {
    assets.push(
      {
        path: project.final_video || `${prefix}/output/final_video.mp4`,
        name: basename(project.final_video) || "final_video.mp4",
        kind: "video",
        size: 184_549_376,
      },
      {
        path: `${prefix}/output/subtitles.srt`,
        name: "subtitles.srt",
        kind: "subtitle",
        size: 3120,
      },
      {
        path: project.final_thumbnail || `${prefix}/output/thumbnail.jpg`,
        name: "thumbnail.jpg",
        kind: "image",
        size: 182_400,
      },
      {
        path: `${prefix}/output/${project.id}-deliverables.zip`,
        name: `${project.id}-deliverables.zip`,
        kind: "archive",
        size: 184_711_000,
      },
    );
  }
  for (const scene of scenes.value.slice(0, 6)) {
    const image = scene.image_path;
    if (!image) continue;
    assets.push({
      path: image,
      name: basename(image),
      kind: "image",
      size: 2_400_000 + scene.scene_id * 24_000,
    });
  }
  return assets;
}

function demoFrameFor(action: string, progress: number): { stage: string; message: string } {
  const frames = ACTION_STEPS[action] || ACTION_STEPS.full;
  let current = frames[0];
  for (const frame of frames) {
    if (progress >= frame.at) current = frame;
  }
  return { stage: current.stage, message: current.message };
}

function clearDemoJobTimer(): void {
  if (demoJobTimer !== null) {
    window.clearInterval(demoJobTimer);
    demoJobTimer = null;
  }
}

function finishDemoAction(action: string): void {
  const project = currentProject.value;
  if (!project) return;
  if (action === "analyze") project.stage = "analyzed";
  else if (action === "plan") project.stage = "planned";
  else if (action === "images" || action === "regenerate") project.stage = project.stage === "rendered" ? "rendered" : "assets_ready";
  else if (action === "animate") project.stage = "animated";
  else if (action === "render" || action === "full") {
    project.stage = "rendered";
    project.final_video = project.final_video || `video/projects/${project.id}/output/final_video.mp4`;
    project.final_thumbnail = project.final_thumbnail || `video/projects/${project.id}/output/thumbnail.jpg`;
  }
  project.updated_at = new Date().toISOString();
  project.status = "idle";
  if (action === "images" || action === "regenerate") {
    scenes.value = scenes.value.map((scene) => ({ ...scene, status: scene.video_path ? scene.status : "image_ready" }));
  }
  if (action === "animate" || action === "full") {
    scenes.value = scenes.value.map((scene) => ({ ...scene, status: "animated" }));
  }
  if (action === "plan") {
    project.scene_count = scenes.value.length;
  }
  project.scene_count = scenes.value.length;
  currentProject.value = project;
  syncProjectRecord();
  videoAssets.value = demoAssets(project);
}

function simulateJob(action: string, options: AnyRecord): void {
  const project = currentProject.value;
  if (!project) return;
  clearDemoJobTimer();
  for (const item of jobs.items) {
    if (item.component === "video" && ACTIVE_STATUSES.has(item.status)) {
      jobs.upsert({ ...item, status: "canceled", stage: "Replaced", message: "Replaced by a new demo job", finished_at: new Date().toISOString(), updated_at: new Date().toISOString() });
    }
  }
  const now = new Date().toISOString();
  const jobId = `job_demo_${Date.now().toString(36)}`;
  const job: Job = {
    id: jobId,
    component: "video",
    action,
    title: `${project.title || project.name} · ${ACTION_LABELS[action] || titleCase(action)}`,
    status: "running",
    stage: "starting",
    message: "Preparing the local pipeline",
    progress: 1,
    params: { project_id: project.id, options },
    result: null,
    error: null,
    warnings: action === "full" ? ["Demo mode: this is a simulated local job. Connect the video service for real renders."] : [],
    artifacts: [],
    cancel_requested: false,
    attempts: 1,
    created_at: now,
    started_at: now,
    finished_at: null,
    updated_at: now,
  };
  jobs.upsert(job);
  jobs.connected = true;
  let progress = 1;
  demoJobTimer = window.setInterval(() => {
    const existing = jobs.byId(jobId);
    if (!existing || existing.status !== "running") {
      clearDemoJobTimer();
      return;
    }
    progress = Math.min(100, progress + 2.5 + Math.random() * 6.5);
    const frame = demoFrameFor(action, progress);
    if (progress >= 100) {
      const finishedAt = new Date().toISOString();
      jobs.upsert({
        ...existing,
        progress: 100,
        status: "completed",
        stage: "Complete",
        message: `${ACTION_LABELS[action] || titleCase(action)} complete`,
        finished_at: finishedAt,
        updated_at: finishedAt,
        result: {
          project_id: project.id,
          action,
          video_path: project.final_video,
          thumbnail_path: project.final_thumbnail,
          subtitles_path: `video/projects/${project.id}/output/subtitles.srt`,
          scene_count: scenes.value.length,
          duration: project.duration,
        },
        artifacts: [
          { path: project.final_video || `video/projects/${project.id}/output/final_video.mp4`, name: "final_video.mp4", kind: "video", size: 184_549_376 },
          { path: `video/projects/${project.id}/output/subtitles.srt`, name: "subtitles.srt", kind: "subtitle", size: 3120 },
        ],
      });
      if (currentProject.value?.id === project.id) finishDemoAction(action);
      clearDemoJobTimer();
      toasts.success(`${ACTION_LABELS[action] || titleCase(action)} completed`);
      return;
    }
    jobs.upsert({
      ...existing,
      progress,
      stage: frame.stage,
      message: `${frame.message}${action === "full" && progress > 36 && progress < 62 ? ` · scene ${Math.min(scenes.value.length, Math.max(1, Math.round((progress - 36) / 2)))}/${scenes.value.length}` : ""}`,
      updated_at: new Date().toISOString(),
    });
  }, 720);
  toasts.info(`${ACTION_LABELS[action] || titleCase(action)} started — simulated local job`);
}

async function runAction(action: string, options: AnyRecord = {}): Promise<void> {
  const project = currentProject.value;
  if (!project) {
    toasts.error("Open a video project first");
    return;
  }
  if (action === "regenerate" && !selectedScene.value) {
    toasts.error("Select a scene before regenerating");
    return;
  }
  if (actionBusy.value) return;
  actionBusy.value = action;
  try {
    if (DEMO) {
      simulateJob(action, options);
      return;
    }
    const job = await api.post<Job>(`/video/projects/${project.id}/run`, { action, options });
    jobs.upsert(job);
    jobs.connect();
    toasts.success(`${ACTION_LABELS[action] || titleCase(action)} queued as ${job.id}`);
  } catch (error: any) {
    toasts.error(error?.message || `Could not start ${action}`);
  } finally {
    actionBusy.value = "";
  }
}

async function triggerFullPipeline(): Promise<void> {
  await runAction("full", {
    force: true,
    skip_images: false,
    skip_animation: false,
    config: clone(exportForm.value),
    output: clone(exportForm.value.output),
  });
}

async function triggerRender(): Promise<void> {
  if (!currentProject.value) {
    toasts.error("Open a video project first");
    return;
  }
  if (exportDirty.value) {
    const saved = await saveProjectConfig(true);
    if (!saved) return;
  }
  await runAction("render", { output: clone(exportForm.value.output) });
}

async function triggerRegenerate(image: boolean, animation: boolean): Promise<void> {
  const scene = selectedScene.value;
  if (!scene) {
    toasts.error("Select a scene first");
    return;
  }
  if (sceneDirty.value) {
    const saved = await saveScene(true);
    if (!saved) return;
  }
  await runAction("regenerate", {
    scene_ids: [scene.scene_id],
    force: true,
    image,
    animation,
    variants: Math.max(1, Math.min(Number(maxSceneVariants.value || 4), Number(regenVariants.value || 1))),
    prompt: sceneForm.visual_prompt,
    negative_prompt: sceneForm.negative_prompt,
    camera: buildScenePatch().camera,
    transition: buildScenePatch().transition,
    visual_effects: [...sceneForm.effects],
    seed: Number(sceneForm.seed || 0),
    image_provider: regenProvider.value,
  });
}

async function cancelJob(jobId: string): Promise<void> {
  if (DEMO) {
    clearDemoJobTimer();
    for (const item of jobs.items) {
      if (item.component === "video" && ACTIVE_STATUSES.has(item.status)) {
        jobs.upsert({ ...item, status: "canceled", stage: "Cancelled", message: "Cancelled in demo mode", cancel_requested: true, finished_at: new Date().toISOString(), updated_at: new Date().toISOString() });
      }
    }
    toasts.info("Demo job cancelled");
    return;
  }
  try {
    await jobs.cancel(jobId);
    toasts.info("Cancellation requested");
  } catch (error: any) {
    toasts.error(error?.message || "Could not cancel the job");
  }
}

async function retryJob(jobId: string): Promise<void> {
  const job = jobs.byId(jobId);
  if (!job) return;
  if (DEMO) {
    simulateJob(job.action, job.params?.options || {});
    return;
  }
  try {
    await jobs.retry(jobId);
    toasts.success("Job restarted");
  } catch (error: any) {
    toasts.error(error?.message || "Could not retry the job");
  }
}

async function removeJob(jobId: string): Promise<void> {
  if (DEMO) {
    jobs.items = jobs.items.filter((item) => item.id !== jobId);
    toasts.success("Demo job record removed");
    return;
  }
  try {
    await jobs.remove(jobId);
    toasts.success("Job record removed");
  } catch (error: any) {
    toasts.error(error?.message || "Could not remove the job");
  }
}

// ---------------------------------------------------------------------------
// Export configuration
// ---------------------------------------------------------------------------

const exportDirty = computed(() => Boolean(currentProject.value) && JSON.stringify(exportForm.value) !== JSON.stringify(currentProject.value?.config));
const exportDimensions = computed(() => outputDimensions(exportForm.value.output.resolution, exportForm.value.output.aspect_ratio));

const deliverableVideo = computed(() => currentProject.value?.final_video || videoAssets.value.find((asset) => isVideoAsset(asset))?.path || "");
const deliverableSrt = computed(() => videoAssets.value.find((asset) => String(asset.path).toLowerCase().endsWith("subtitles.srt"))?.path || currentProject.value?.srt_path || "");
const deliverableThumbnail = computed(() => currentProject.value?.final_thumbnail || videoAssets.value.find((asset) => String(asset.path).toLowerCase().endsWith("thumbnail.jpg"))?.path || currentProject.value?.cover_image || "");
const deliverableZip = computed(() => archivePath.value || videoAssets.value.find((asset) => String(asset.path).toLowerCase().endsWith(".zip"))?.path || "");

const latestRenderJob = computed(() => videoJobs.value.find((job) => job.status === "completed") || null);

function isVideoAsset(asset: VideoAsset): boolean {
  const kind = String(asset.kind || "").toLowerCase();
  const path = String(asset.path || "").toLowerCase();
  return kind === "video" || path.endsWith(".mp4") || path.endsWith(".mkv") || path.endsWith(".webm") || path.endsWith(".mov");
}

function assetKind(asset: VideoAsset): string {
  const kind = String(asset.kind || "").toLowerCase();
  const path = String(asset.path || "").toLowerCase();
  if (kind === "video" || [".mp4", ".mkv", ".webm", ".mov"].some((suffix) => path.endsWith(suffix))) return "video";
  if (kind === "image" || kind === "images" || kind === "thumbnail" || [".png", ".jpg", ".jpeg", ".webp"].some((suffix) => path.endsWith(suffix))) return "image";
  if (kind === "subtitle" || kind === "subtitles" || path.endsWith(".srt") || path.endsWith(".ass") || path.endsWith(".vtt")) return "subtitle";
  if (kind === "audio" || [".mp3", ".wav", ".flac", ".m4a"].some((suffix) => path.endsWith(suffix))) return "audio";
  if (path.endsWith(".zip")) return "archive";
  return kind || "file";
}

function assetIcon(asset: VideoAsset): any {
  const kind = assetKind(asset);
  if (kind === "video") return FileVideo;
  if (kind === "image") return FileImage;
  if (kind === "subtitle") return FileText;
  if (kind === "archive") return Archive;
  if (kind === "audio") return Music2;
  return FileText;
}

function assetKindLabel(asset: VideoAsset): string {
  const kind = assetKind(asset);
  if (kind === "archive") return "ZIP archive";
  if (kind === "image") return "Image";
  if (kind === "video") return "Video";
  if (kind === "subtitle") return "Subtitle";
  if (kind === "audio") return "Audio";
  return titleCase(kind);
}

function assetName(asset: VideoAsset): string {
  return asset.name || basename(asset.path);
}

function demoDownload(label: string): void {
  toasts.info(`Demo mode — ${label} is ready in the live studio. Connect the video worker to download it.`);
}

async function createArchive(): Promise<void> {
  const project = currentProject.value;
  if (!project || archiveBusy.value) return;
  if (DEMO) {
    archivePath.value = `video/projects/${project.id}/output/${project.id}-deliverables.zip`;
    toasts.success("Demo archive prepared");
    return;
  }
  archiveBusy.value = true;
  try {
    const paths = videoAssets.value.map((asset) => asset.path).filter(Boolean);
    if (!paths.length) {
      toasts.error("No project assets to archive yet");
      return;
    }
    const result = await api.post<{ path: string }>("/files/zip", {
      paths,
      output: `video/projects/${project.id}/output/${project.id}-deliverables.zip`,
    });
    archivePath.value = result.path;
    toasts.success(`Archive created: ${basename(result.path)}`);
    await loadAssets(project.id);
  } catch (error: any) {
    toasts.error(error?.message || "Could not create the project archive");
  } finally {
    archiveBusy.value = false;
  }
}

async function saveProjectConfig(silent = false): Promise<boolean> {
  const project = currentProject.value;
  if (!project || savingConfig.value) return false;
  savingConfig.value = true;
  try {
    const config = clone(exportForm.value);
    config.output.output_dir = config.output.output_dir?.trim() || null;
    config.output.output_filename = config.output.output_filename?.trim() || "final_video.mp4";
    if (!/\.(mp4|mkv)$/i.test(config.output.output_filename)) config.output.output_filename = `${config.output.output_filename}.mp4`;
    if (DEMO) {
      currentProject.value = { ...project, config, updated_at: new Date().toISOString() };
      exportForm.value = clone(config);
      syncProjectRecord();
      if (!silent) toasts.success("Export settings saved");
      return true;
    }
    const updated = await api.patch<AnyRecord>(`/video/projects/${project.id}`, { config });
    currentProject.value = normalizeProject(updated);
    exportForm.value = clone(currentProject.value.config);
    syncProjectRecord();
    if (!silent) toasts.success("Export settings saved");
    return true;
  } catch (error: any) {
    if (!silent) toasts.error(error?.message || "Could not save export settings");
    return false;
  } finally {
    savingConfig.value = false;
  }
}

// ---------------------------------------------------------------------------
// New project
// ---------------------------------------------------------------------------

const canCreate = computed(() => Boolean(newDraft.name.trim() && newDraft.audio_path && newDraft.srt_path));
const draftOutputDimensions = computed(() => outputDimensions(newDraft.config.output.resolution, newDraft.config.output.aspect_ratio));
const estimatedScenes = computed(() => Math.max(4, Math.round(196 / Math.max(4, Number(newDraft.config.scenes.target_duration || 8)))));

function syncProviderFields(): void {
  const comfy = catalog.value.comfyui || {};
  const ollama = catalog.value.ollama || {};
  const ai = catalog.value.aiSettings || {};
  newDraft.comfyui_url = String(comfy.url ?? ai.comfyui_url ?? "");
  newDraft.image_workflow_path = String(comfy.image_workflow_path ?? ai.image_workflow_path ?? "");
  newDraft.video_workflow_path = String(comfy.video_workflow_path ?? ai.video_workflow_path ?? "");
  newDraft.image_steps = Number(comfy.image_steps ?? ai.image_steps ?? 28);
  newDraft.image_cfg = Number(comfy.image_cfg ?? ai.image_cfg ?? 6);
  newDraft.image_checkpoint = String(comfy.image_checkpoint ?? ai.image_checkpoint ?? "");
  newDraft.video_steps = Number(comfy.video_steps ?? ai.video_steps ?? 24);
  newDraft.video_cfg = Number(comfy.video_cfg ?? ai.video_cfg ?? 5);
  newDraft.video_checkpoint = String(comfy.video_checkpoint ?? ai.video_checkpoint ?? "");
  newDraft.ollama_url = String(ollama.url ?? ai.ollama_url ?? "");
  newDraft.ollama_model = String(ollama.model ?? ai.ollama_model ?? "");
  providerSnapshot.value = JSON.stringify(providerFields());
}

function providerFields(): AnyRecord {
  return {
    comfyui_url: newDraft.comfyui_url,
    image_workflow_path: newDraft.image_workflow_path,
    video_workflow_path: newDraft.video_workflow_path,
    image_steps: newDraft.image_steps,
    image_cfg: newDraft.image_cfg,
    image_checkpoint: newDraft.image_checkpoint,
    video_steps: newDraft.video_steps,
    video_cfg: newDraft.video_cfg,
    video_checkpoint: newDraft.video_checkpoint,
    ollama_url: newDraft.ollama_url,
    ollama_model: newDraft.ollama_model,
  };
}

function resetDraft(): void {
  Object.assign(newDraft, {
    name: "",
    title: "",
    artist: "",
    audio_path: "",
    audio_name: "",
    srt_path: "",
    srt_name: "",
    config: clone(catalog.value.defaults.project || FALLBACK_CONFIG),
    comfyui_url: "",
    image_workflow_path: "",
    video_workflow_path: "",
    image_steps: 28,
    image_cfg: 6,
    image_checkpoint: "",
    video_steps: 24,
    video_cfg: 5,
    video_checkpoint: "",
    ollama_url: "",
    ollama_model: "",
  });
  subtitlePreset.value = newDraft.config.subtitles.karaoke ? "karaoke" : "clean";
  imageSizePreset.value = newDraft.config.scenes.image_width || newDraft.config.scenes.image_height ? "custom" : "auto";
  syncProviderFields();
}

function openNewProject(): void {
  resetDraft();
  newProjectOpen.value = true;
}

function applySubtitlePreset(presetId: string): void {
  const preset = SUBTITLE_PRESETS.find((item) => item.id === presetId);
  if (!preset) return;
  Object.assign(newDraft.config.subtitles, clone(preset.style));
  subtitlePreset.value = presetId;
}

function applyImageSizePreset(presetId: string): void {
  imageSizePreset.value = presetId;
  const preset = IMAGE_SIZE_PRESETS.find((item) => item.id === presetId);
  if (!preset) return;
  newDraft.config.scenes.image_width = preset.width;
  newDraft.config.scenes.image_height = preset.height;
}

function onImageSizePresetChange(event: Event): void {
  applyImageSizePreset((event.target as HTMLSelectElement).value);
}

function setDraftImageWidth(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value);
  newDraft.config.scenes.image_width = Number.isFinite(value) && value > 0 ? Math.round(value) : null;
  imageSizePreset.value = "custom";
}

function setDraftImageHeight(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value);
  newDraft.config.scenes.image_height = Number.isFinite(value) && value > 0 ? Math.round(value) : null;
  imageSizePreset.value = "custom";
}

function setDraftCrf(event: Event): void {
  const raw = (event.target as HTMLInputElement).value;
  const value = Number(raw);
  newDraft.config.output.crf = raw !== "" && Number.isFinite(value) && value >= 0 && value <= 51 ? Math.round(value) : null;
}

function chooseDraftAudio(): void {
  if (DEMO) {
    newDraft.audio_path = "music/nocturno/master/nocturno-master.wav";
    newDraft.audio_name = "nocturno-master.wav";
    toasts.info("Demo audio selected. Choose a real upload when connected to the video worker.");
    return;
  }
  audioPickerOpen.value = true;
}

function chooseDraftSrt(): void {
  if (DEMO) {
    newDraft.srt_path = "subtitles/67c9de20/nocturno.srt";
    newDraft.srt_name = "nocturno.srt";
    toasts.info("Demo SRT selected. Timed lyrics are preserved exactly.");
    return;
  }
  srtPickerOpen.value = true;
}

function onAudioSelected(path: string): void {
  newDraft.audio_path = path;
  newDraft.audio_name = basename(path);
  audioPickerOpen.value = false;
}

function onSrtSelected(path: string): void {
  if (!path.toLowerCase().endsWith(".srt")) {
    toasts.error("The video studio requires an .srt subtitle file");
    return;
  }
  newDraft.srt_path = path;
  newDraft.srt_name = basename(path);
  srtPickerOpen.value = false;
}

async function persistProviderSettings(): Promise<void> {
  if (DEMO || JSON.stringify(providerFields()) === providerSnapshot.value) return;
  const payload = {
    ...(catalog.value.aiSettings || {}),
    ...providerFields(),
    image_provider: newDraft.config.scenes.image_provider,
    animation_backend: newDraft.config.scenes.animation_backend,
    image_steps: Number.isFinite(Number(newDraft.image_steps)) && Number(newDraft.image_steps) > 0 ? Number(newDraft.image_steps) : 28,
    image_cfg: Number.isFinite(Number(newDraft.image_cfg)) ? Number(newDraft.image_cfg) : 6,
    video_steps: Number.isFinite(Number(newDraft.video_steps)) && Number(newDraft.video_steps) > 0 ? Number(newDraft.video_steps) : 24,
    video_cfg: Number.isFinite(Number(newDraft.video_cfg)) ? Number(newDraft.video_cfg) : 5,
  };
  await api.put("/video/settings/ai", payload);
}

function buildDemoCues(duration: number): Cue[] {
  const base = normalizeCues(demoCues);
  if (!base.length) return [];
  const span = Math.max(1, Math.max(...base.map((cue) => cue.end)) - Math.min(...base.map((cue) => cue.start)));
  const loops = Math.max(1, Math.ceil(duration / span));
  const cues: Cue[] = [];
  let index = 0;
  for (let loop = 0; loop < loops; loop += 1) {
    const offset = loop * span;
    for (const cue of base) {
      const start = cue.start + offset;
      if (start >= duration) break;
      cues.push({
        index: ++index,
        start,
        end: Math.min(duration, cue.end + offset),
        text: cue.text,
      });
    }
  }
  return cues;
}

function buildDemoEditorPreview(project: VideoProject): { scenes: VideoScene[]; cues: Cue[] } {
  const bases = demoScenes.map((scene) => normalizeScene(scene as AnyRecord)).sort((a, b) => a.start - b.start);
  const lastEnd = Math.max(1, ...bases.map((scene) => scene.end));
  const duration = Number(project.duration || lastEnd);
  const scale = duration / lastEnd;
  const split = 3;
  const expanded: VideoScene[] = [];
  let sceneId = 1;
  bases.forEach((base, baseIndex) => {
    const span = (base.end - base.start) / split;
    for (let part = 0; part < split; part += 1) {
      const start = base.start + part * span;
      const end = part === split - 1 ? base.end : start + span;
      const image = demoImagePaths[(baseIndex * split + part) % demoImagePaths.length];
      const variant = demoImagePaths[(baseIndex * split + part + 3) % demoImagePaths.length];
      expanded.push({
        ...base,
        scene_id: sceneId,
        start: Number((start * scale).toFixed(3)),
        end: Number((end * scale).toFixed(3)),
        duration: Number(((end - start) * scale).toFixed(3)),
        description: base.description,
        visual_prompt: base.visual_prompt || `${base.description} Cinematic anamorphic frame with deep shadows, practical light and atmospheric haze.`,
        image_path: image,
        thumbnail_path: null,
        image_source: "procedural",
        image_variants: [image, variant],
        video_path: `video/projects/${project.id}/assets/videos/scene_${String(sceneId).padStart(3, "0")}.mp4`,
        status: "animated",
        camera: { ...base.camera, zoom: Number((base.camera.zoom + part * 0.015).toFixed(3)) },
        transition: part === split - 1 ? { ...base.transition } : { type: "cut", duration: 0.15 },
      });
      sceneId += 1;
    }
  });
  return { scenes: expanded, cues: buildDemoCues(duration) };
}

function buildDemoScenes(projectId: string, total: number, target: number): VideoScene[] {
  const definitions = [
    { kind: "intro", description: "Rain on an empty avenue, neon signs dissolving out of focus.", camera: "slow_push", transition: "fade", effects: ["film_grain", "bloom"] },
    { kind: "verse", description: "A lone figure under a street light, breath visible in the cold.", camera: "pan_left", transition: "dissolve", effects: ["vignette", "particles"] },
    { kind: "chorus", description: "The city opens up, traffic streaks and reflections bloom across glass.", camera: "orbit", transition: "zoom_blur", effects: ["bloom", "beat_pulse"] },
    { kind: "verse", description: "Close-up of hands on a rain-soaked railing, holding the moment.", camera: "tilt_up", transition: "cut", effects: ["film_grain"] },
    { kind: "chorus", description: "A wide bridge, the river carrying the city lights toward the sea.", camera: "pull_back", transition: "dissolve", effects: ["bloom", "light_leak"] },
    { kind: "outro", description: "An empty apartment at dawn, curtains moving, a final breath.", camera: "handheld", transition: "fade", effects: ["grain", "chromatic_aberration"] },
  ];
  const count = Math.max(4, Math.min(18, Math.round(total / Math.max(4, target))));
  const span = total / count;
  return Array.from({ length: count }, (_, index) => {
    const definition = definitions[index % definitions.length];
    const image = demoImagePaths[index % demoImagePaths.length];
    return normalizeScene({
      id: index + 1,
      scene_id: index + 1,
      start: index * span,
      end: (index + 1) * span,
      kind: definition.kind,
      section_kind: definition.kind,
      section_label: titleCase(definition.kind),
      description: definition.description,
      visual_prompt: `${definition.description} — cinematic anamorphic frame, deep shadows, warm sodium light against teal night.`,
      negative_prompt: "text, watermark, logo, deformed hands, extra limbs, low quality, blurry",
      camera: definition.camera,
      transition: definition.transition,
      visual_effects: definition.effects,
      image_path: image,
      image_source: "procedural",
      image_variants: [image, demoImagePaths[(index + 3) % demoImagePaths.length]],
      video_path: `video/projects/${projectId}/assets/videos/scene_${String(index + 1).padStart(3, "0")}.mp4`,
      status: "animated",
      seed: 1987 + index * 37,
    });
  });
}

async function createProject(startPipeline = false): Promise<void> {
  if (!canCreate.value || creating.value) return;
  creating.value = true;
  try {
    const config = clone(newDraft.config);
    config.output.output_dir = config.output.output_dir?.trim() || null;
    config.output.output_filename = config.output.output_filename?.trim() || "final_video.mp4";
    if (!/\.(mp4|mkv)$/i.test(config.output.output_filename)) config.output.output_filename = `${config.output.output_filename}.mp4`;
    config.output.crf = config.output.crf === null || config.output.crf === undefined ? null : Number(config.output.crf);
    config.scenes.image_width = config.scenes.image_width ? Math.max(256, Math.min(4096, Math.round(Number(config.scenes.image_width)))) : null;
    config.scenes.image_height = config.scenes.image_height ? Math.max(256, Math.min(4096, Math.round(Number(config.scenes.image_height)))) : null;
    config.scenes.target_duration = Math.max(4, Math.min(14, Number(config.scenes.target_duration || 8)));
    config.scenes.min_duration = Math.max(1, Math.min(Number(config.scenes.min_duration || 3.5), config.scenes.target_duration));
    config.scenes.max_duration = Math.max(config.scenes.target_duration, Number(config.scenes.max_duration || 16));
    if (DEMO) {
      cacheCurrentDemoProject();
      const baseId = slugify(newDraft.name) || `video-${Date.now().toString(36)}`;
      let id = baseId;
      let suffix = 2;
      while (projects.value.some((item) => item.id === id)) {
        id = `${baseId}-${suffix}`;
        suffix += 1;
      }
      const total = 196.4;
      const demoScenes = buildDemoScenes(id, total, config.scenes.target_duration);
      const project: VideoProject = {
        id,
        name: slugify(newDraft.name) || id,
        title: newDraft.title.trim() || newDraft.name.trim(),
        artist: newDraft.artist.trim() || "Open Studio",
        duration: total,
        scene_count: demoScenes.length,
        stage: "animated",
        status: "idle",
        updated_at: new Date().toISOString(),
        final_video: null,
        final_thumbnail: null,
        final_video_external: null,
        cover_image: null,
        audio_path: newDraft.audio_path,
        srt_path: newDraft.srt_path,
        width: outputDimensions(config.output.resolution, config.output.aspect_ratio).width,
        height: outputDimensions(config.output.resolution, config.output.aspect_ratio).height,
        planner: null,
        warnings: [],
        config,
      };
      projects.value = [project, ...projects.value.filter((item) => item.id !== project.id)];
      currentProject.value = project;
      scenes.value = demoScenes;
      subtitleLines.value = buildDemoCues(total);
      selectedSceneId.value = demoScenes[0]?.scene_id ?? null;
      exportForm.value = clone(config);
      regenProvider.value = config.scenes.image_provider;
      regenVariants.value = config.scenes.variants;
      archivePath.value = "";
      videoAssets.value = demoAssets(project);
      resetSceneForm();
      previewTime.value = demoScenes[0]?.start ?? 0;
      cacheCurrentDemoProject();
      tab.value = "editor";
      newProjectOpen.value = false;
      toasts.success("Demo project created");
      if (startPipeline) runAction("full", { force: true, config: clone(config), output: clone(config.output) });
      return;
    }

    const projectPayload = {
      name: newDraft.name.trim(),
      title: newDraft.title.trim() || newDraft.name.trim(),
      artist: newDraft.artist.trim(),
      audio_path: newDraft.audio_path,
      srt_path: newDraft.srt_path,
      config,
    };
    const created = await api.post<AnyRecord>("/video/projects", projectPayload);
    try {
      await persistProviderSettings();
    } catch (error: any) {
      toasts.error(`Project created, but provider settings could not be saved: ${error?.message || "unknown error"}`);
    }
    newProjectOpen.value = false;
    toasts.success("Video project created");
    await loadProjects(false);
    await openProject(String(created.id), true);
    if (startPipeline) {
      await runAction("full", { force: true, config: clone(config), output: clone(config.output) });
    }
  } catch (error: any) {
    toasts.error(error?.message || "Could not create the video project");
  } finally {
    creating.value = false;
  }
}

// ---------------------------------------------------------------------------
// Watchers and lifecycle
// ---------------------------------------------------------------------------

watch(selectedSceneId, () => {
  resetSceneForm();
  stopPreview();
  if (selectedScene.value) previewTime.value = selectedScene.value.start;
});

watch(
  () => `${currentJob.value?.id || ""}:${currentJob.value?.status || ""}`,
  async (next, previous) => {
    if (DEMO || !currentProject.value) return;
    if (next.endsWith(":completed") && next !== previous) {
      await openProject(currentProject.value.id, false);
    }
  },
);

watch(
  () => currentProject.value?.id,
  () => {
    stopPreview();
    if (!currentProject.value) return;
    regenProvider.value = currentProject.value.config.scenes.image_provider || "auto";
    regenVariants.value = Math.max(1, Number(currentProject.value.config.scenes.variants || 1));
  },
);

watch(
  () => tab.value,
  async (value) => {
    if (value === "editor" && !currentProject.value && projects.value.length) {
      await openProject(projects.value[0].id, false);
    }
    if (value === "render" && !jobs.items.length) {
      await jobs.refresh();
    }
  },
);

onMounted(async () => {
  if (!system.status) system.load();
  await Promise.allSettled([loadCatalog(true), jobs.refresh()]);
  await loadProjects(true);
  jobs.connect();
  if (DEMO) {
    if (!["projects", "editor", "render", "qvac"].includes(tab.value)) tab.value = "editor";
    await openProject(demoVideoProject.id, false);
  } else if (projects.value.length) {
    await openProject(projects.value[0].id, false);
  }
});

onBeforeUnmount(() => {
  stopPreview();
  clearDemoJobTimer();
});
</script>

<template>
  <div class="page video-page">
    <PageHeader
      eyebrow="Video studio"
      title="Video"
      subtitle="Turn a song and its timed SRT lyrics into a finished film — scene planning, procedural or ComfyUI/QVAC artwork, FFmpeg/OpenCV animation, styled subtitles and the final render, all on your machine."
    >
      <template #actions>
        <button class="btn btn-primary" @click="openNewProject"><Plus :size="15" /> New video</button>
        <button class="btn" :disabled="refreshing" @click="refreshAll">
          <RefreshCw :size="14" :class="{ spin: refreshing }" /> Refresh
        </button>
      </template>
    </PageHeader>

    <div class="video-toolbar">
      <TabsBar v-model="tab" :tabs="tabs" />
      <div class="video-toolbar-meta">
        <span class="chip" :class="{ success: videoWorkerOnline }">
          <span class="dot" :class="videoWorkerOnline ? 'online' : 'offline'" />
          Video worker {{ videoWorkerOnline ? "online" : "offline" }}
        </span>
        <span class="chip"><Music2 :size="11" /> Audio + SRT</span>
        <span class="chip"><Captions :size="11" /> Burn-in subtitles</span>
        <span v-if="DEMO" class="chip active"><Sparkles :size="11" /> Demo studio</span>
      </div>
    </div>

    <ServiceNotice
      :services="[
        { name: 'video', label: 'Video Studio' },
        { name: 'qvac', label: 'QVAC' },
        { name: 'imagegen', label: 'Picture Studio' },
      ]"
      title="Some video features are unavailable"
    />

    <section v-if="qvacOnline && tab === 'qvac'" class="stack">
      <QvacView embedded />
    </section>

    <!-- ================================================================= -->
    <!-- Projects                                                           -->
    <!-- ================================================================= -->
    <section v-if="videoWorkerOnline && tab === 'projects'" class="stack">
      <div class="stat-grid">
        <div class="stat">
          <div class="stat-label">Video projects</div>
          <div class="stat-value">{{ projectStats.projects }}</div>
          <div class="stat-sub">Each project keeps its own song, SRT and scene plan</div>
        </div>
        <div class="stat">
          <div class="stat-label">Planned scenes</div>
          <div class="stat-value">{{ projectStats.scenes }}</div>
          <div class="stat-sub">Structure-aware shots with camera and transition data</div>
        </div>
        <div class="stat">
          <div class="stat-label">Rendered masters</div>
          <div class="stat-value">{{ projectStats.rendered }}</div>
          <div class="stat-sub">MP4 masters with burned-in subtitles</div>
        </div>
        <div class="stat">
          <div class="stat-label">Active video jobs</div>
          <div class="stat-value">{{ projectStats.active }}</div>
          <div class="stat-sub">{{ queueMetrics.running }} running · {{ queueMetrics.queued }} queued</div>
        </div>
      </div>

      <div class="video-projects-layout">
        <div class="stack">
          <div v-if="loadingProjects" class="video-projects-grid">
            <div v-for="index in 2" :key="index" class="panel video-project-card skeleton-card">
              <div class="skeleton" style="aspect-ratio: 16 / 9; border-radius: 0" />
              <div class="video-project-body">
                <div class="skeleton" style="height: 14px; width: 56%" />
                <div class="skeleton" style="height: 10px; width: 36%; margin-top: 9px" />
              </div>
            </div>
          </div>

          <div v-else-if="projects.length" class="video-projects-grid">
            <article v-for="project in projects" :key="project.id" class="panel video-project-card" @click="openProject(project.id)">
              <div class="video-project-poster">
                <img v-if="cardPoster(project)" :src="cardPoster(project)" :alt="project.title" loading="lazy" @error="markPosterFailed(project)" />
                <div v-else class="video-poster-fallback"><Clapperboard :size="34" /></div>
                <div class="video-poster-shade" />
                <div class="video-poster-top">
                  <span class="badge" :class="stageTone(project.stage)">{{ stageLabel(project.stage) }}</span>
                  <span v-if="project.final_video" class="badge success"><Play :size="9" /> Final</span>
                  <span v-if="DEMO" class="badge warn">Demo</span>
                </div>
                <div class="video-poster-play"><Play :size="20" /></div>
                <div class="video-poster-caption">
                  <span class="video-poster-kicker">{{ project.artist || "Open Studio" }}</span>
                  <h2>{{ project.title }}</h2>
                  <p>{{ project.scene_count }} scenes · {{ formatDuration(project.duration) }}</p>
                </div>
              </div>
              <div class="video-project-body">
                <div class="row-between">
                  <span class="small muted">{{ project.width }} × {{ project.height }} · {{ project.config.output.fps }} fps · {{ project.config.output.codec.toUpperCase() }}</span>
                  <span class="small muted">{{ relativeTime(project.updated_at) }}</span>
                </div>
                <div class="progress thin"><span :style="{ width: `${projectProgress(project)}%` }" /></div>
                <div class="row-between">
                  <span class="small muted">{{ currentStyleNameFor(project) }} · {{ project.config.scenes.image_provider }}</span>
                  <span class="video-project-open">Open editor <ChevronRight :size="13" /></span>
                </div>
              </div>
            </article>

            <button class="video-new-project-card" type="button" @click="openNewProject">
              <span class="video-new-project-icon"><Plus :size="22" /></span>
              <strong>Start a new music video</strong>
              <p>Bring a song and its SRT lyrics. The studio handles analysis, story, artwork, motion and export.</p>
              <span class="video-new-project-tags">
                <span class="chip">Procedural</span>
                <span class="chip">ComfyUI</span>
                <span class="chip">QVAC</span>
              </span>
            </button>
          </div>

          <EmptyState
            v-else
            :icon="Clapperboard"
            title="No video projects yet"
            message="Start with a track and its SRT lyrics. The studio can build a complete video with procedural artwork and camera motion, even without AI models."
          >
            <button class="btn btn-primary" @click="openNewProject"><Plus :size="14" /> Create your first video</button>
          </EmptyState>

          <div class="video-feature-band">
            <article class="video-feature">
              <span class="video-feature-icon"><Music2 :size="18" /></span>
              <h3>Structure-aware scenes</h3>
              <p>Beats, sections and timed lyrics become a visual plan with pacing that follows the song instead of a blind fixed grid.</p>
              <div class="tag-list"><span class="chip">Tempo</span><span class="chip">Sections</span><span class="chip">SRT timing</span></div>
            </article>
            <article class="video-feature">
              <span class="video-feature-icon"><ImageIcon :size="18" /></span>
              <h3>Artwork for every look</h3>
              <p>Procedural stills work with no model at all. ComfyUI, QVAC and Diffusers plug into the same scene pipeline when configured.</p>
              <div class="tag-list"><span class="chip">Procedural</span><span class="chip">ComfyUI</span><span class="chip">QVAC</span><span class="chip">Diffusers</span></div>
            </article>
            <article class="video-feature">
              <span class="video-feature-icon"><Clapperboard :size="18" /></span>
              <h3>Camera language</h3>
              <p>Pushes, pans, parallax and handheld drift are rendered by FFmpeg or OpenCV, with depth maps and optional AI video.</p>
              <div class="tag-list"><span class="chip">FFmpeg</span><span class="chip">OpenCV</span><span class="chip">Depth parallax</span></div>
            </article>
            <article class="video-feature">
              <span class="video-feature-icon"><Captions :size="18" /></span>
              <h3>Subtitle craft</h3>
              <p>Style the burn-in, choose karaoke emphasis, keep original timestamps and export the SRT beside the final master.</p>
              <div class="tag-list"><span class="chip">Burn-in</span><span class="chip">SRT export</span><span class="chip">Karaoke</span></div>
            </article>
          </div>
        </div>

        <aside class="stack">
          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Production pipeline</h3>
                <p>Every stage is resumable and writes to shared storage.</p>
              </div>
              <span class="chip">{{ currentProject ? stageLabel(currentProject.stage) : "Ready" }}</span>
            </div>
            <div class="panel-body video-pipeline">
              <div
                v-for="(step, index) in PIPELINE_STEPS"
                :key="step.key"
                class="video-pipeline-row"
                :class="{ done: index < projectStageIndex || (currentProject?.stage === 'rendered' && index === PIPELINE_STEPS.length - 1), active: index === projectStageIndex && currentProject?.stage !== 'rendered' }"
              >
                <span class="video-pipeline-marker">
                  <Check v-if="index < projectStageIndex || (currentProject?.stage === 'rendered' && index === PIPELINE_STEPS.length - 1)" :size="11" />
                  <span v-else>{{ index + 1 }}</span>
                </span>
                <div class="video-pipeline-copy">
                  <strong>{{ step.label }}</strong>
                  <span>{{ step.detail }}</span>
                </div>
              </div>
            </div>
            <div class="panel-footer">
              <button class="btn btn-sm" @click="tab = 'editor'"><Film :size="12" /> Open editor</button>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Studio defaults</h3>
                <p>{{ catalog.styles.length }} art directions · {{ catalog.providers.length }} image providers</p>
              </div>
              <Palette :size="16" class="muted" />
            </div>
            <div class="panel-body stack" style="gap: 12px">
              <div class="video-capability">
                <span class="file-icon"><Palette :size="14" /></span>
                <div><span>Art direction</span><strong>{{ currentStyleName }}</strong></div>
                <div class="video-palette">
                  <i v-for="color in (currentStyle?.palette || []).slice(0, 5)" :key="color" :style="{ background: color }" />
                </div>
              </div>
              <div class="video-capability">
                <span class="file-icon"><ImageIcon :size="14" /></span>
                <div><span>Scene artwork</span><strong>{{ currentProviderLabel }}</strong></div>
              </div>
              <div class="video-capability">
                <span class="file-icon"><Clapperboard :size="14" /></span>
                <div><span>Animation</span><strong>{{ currentBackendLabel }}</strong></div>
              </div>
              <div class="video-capability">
                <span class="file-icon"><Captions :size="14" /></span>
                <div><span>Subtitles</span><strong>{{ exportForm.subtitles.karaoke ? "Karaoke emphasis" : "Styled burn-in" }}</strong></div>
              </div>
              <div class="video-capability">
                <span class="file-icon"><Zap :size="14" /></span>
                <div><span>Music reactivity</span><strong>{{ exportForm.audio_reactive.enabled ? `Beat + bass · ${Math.round(exportForm.audio_reactive.intensity * 100)}%` : "Off" }}</strong></div>
              </div>
              <div class="alert">
                <Sparkles :size="12" style="vertical-align: -2px; color: var(--accent-2)" />
                Procedural artwork and FFmpeg motion work fully offline. ComfyUI, QVAC, Diffusers and Ollama are optional.
              </div>
            </div>
          </section>
        </aside>
      </div>

    </section>

    <!-- ================================================================= -->
    <!-- Editor                                                             -->
    <!-- ================================================================= -->
    <section v-else-if="videoWorkerOnline && tab === 'editor'" class="stack">
      <div v-if="loadingProject && !currentProject" class="panel">
        <div class="panel-body stack">
          <div class="skeleton" style="height: 92px" />
          <div class="skeleton" style="height: 260px" />
        </div>
      </div>

      <EmptyState
        v-else-if="!currentProject"
        :icon="Clapperboard"
        title="Choose a project to edit"
        message="Open a video project from the projects tab, or create a new one with a song and timed SRT lyrics."
      >
        <button class="btn btn-primary" @click="openNewProject"><Plus :size="14" /> New video</button>
        <button class="btn" style="margin-left: 8px" @click="tab = 'projects'">Browse projects</button>
      </EmptyState>

      <template v-else>
        <header class="panel video-editor-head">
          <div class="video-editor-identity">
            <div class="video-editor-cover" @click="tab = 'projects'">
              <img v-if="editorCover" :src="editorCover" :alt="currentProject.title" />
              <span v-else class="video-editor-cover-fallback"><Clapperboard :size="20" /></span>
              <span class="video-editor-cover-count">{{ scenes.length }}</span>
            </div>
            <div class="video-editor-copy">
              <div class="video-editor-chips">
                <span class="badge" :class="stageTone(currentProject.stage)">{{ stageLabel(currentProject.stage) }}</span>
                <span class="chip"><Clock :size="11" /> {{ formatDuration(currentProject.duration) }}</span>
                <span class="chip"><Layers :size="11" /> {{ scenes.length }} scenes</span>
                <span class="chip"><Film :size="11" /> {{ currentProject.width }} × {{ currentProject.height }} · {{ exportForm.output.fps }} fps</span>
                <span class="chip"><Palette :size="11" /> {{ currentStyleName }}</span>
                <span v-if="currentProject.planner" class="chip"><Wand2 :size="11" /> {{ titleCase(currentProject.planner) }}</span>
                <span v-if="DEMO" class="chip active"><Sparkles :size="11" /> Demo</span>
              </div>
              <h2>{{ currentProject.title }}</h2>
              <p>
                {{ currentProject.artist || "Unknown artist" }}
                <span class="video-dot">·</span>
                {{ currentProject.name }}
                <span class="video-dot">·</span>
                updated {{ relativeTime(currentProject.updated_at) }}
              </p>
            </div>
          </div>

          <div class="video-editor-actions">
            <button class="btn btn-sm" :disabled="actionsDisabled" title="Analyse audio and lyrics" @click="runAction('analyze', { force: true })">
              <Activity :size="13" :class="{ spin: actionBusy === 'analyze' }" /> Analyze
            </button>
            <button class="btn btn-sm" :disabled="actionsDisabled" title="Plan scenes" @click="runAction('plan', { force: true })">
              <Layers :size="13" :class="{ spin: actionBusy === 'plan' }" /> Plan
            </button>
            <button class="btn btn-sm" :disabled="actionsDisabled" title="Generate scene images" @click="runAction('images', { force: true, variant: 0, variants: exportForm.scenes.variants })">
              <ImageIcon :size="13" :class="{ spin: actionBusy === 'images' }" /> Generate images
            </button>
            <button class="btn btn-sm" :disabled="actionsDisabled" title="Animate every scene" @click="runAction('animate', { force: true })">
              <Clapperboard :size="13" :class="{ spin: actionBusy === 'animate' }" /> Animate
            </button>
            <button class="btn btn-sm" :disabled="actionsDisabled" title="Render the final video" @click="triggerRender">
              <Film :size="13" :class="{ spin: actionBusy === 'render' }" /> Render
            </button>
            <button class="btn btn-sm btn-primary" :disabled="actionsDisabled" title="Run the complete pipeline" @click="triggerFullPipeline">
              <Sparkles :size="13" :class="{ spin: actionBusy === 'full' }" /> Full pipeline
            </button>
            <button class="btn btn-sm" :disabled="actionsDisabled || !selectedScene" title="Regenerate the selected scene" @click="triggerRegenerate(true, true)">
              <RefreshCw :size="13" :class="{ spin: actionBusy === 'regenerate' }" /> Regenerate scene
            </button>
          </div>
        </header>

        <section v-if="currentJob" class="panel video-live-job">
          <div class="panel-head">
            <div>
              <h3>Production status</h3>
              <p>{{ ACTION_LABELS[currentJob.action] || titleCase(currentJob.action) }} · {{ currentJob.status }}</p>
            </div>
            <span class="chip" :class="{ success: currentJob.status === 'completed', warn: currentJob.status === 'running' }">
              <Clock :size="11" /> {{ currentJob.stage || "Queued" }}
            </span>
          </div>
          <div class="panel-body video-live-job-grid">
            <JobCard :job="currentJob" @cancel="cancelJob" @retry="retryJob" @remove="removeJob" />
            <div class="video-job-context">
              <div class="video-job-facts">
                <div><span>Action</span><strong>{{ ACTION_LABELS[currentJob.action] || titleCase(currentJob.action) }}</strong></div>
                <div><span>Progress</span><strong>{{ Math.round(currentJob.progress) }}%</strong></div>
                <div><span>Job id</span><strong class="mono">{{ currentJob.id }}</strong></div>
                <div><span>Started</span><strong>{{ currentJob.started_at ? relativeTime(currentJob.started_at) : relativeTime(currentJob.created_at) }}</strong></div>
              </div>
              <div v-if="currentJobWarnings.length" class="video-job-warnings">
                <div v-for="warning in currentJobWarnings.slice(-3)" :key="warning" class="alert warn">
                  <AlertTriangle :size="12" style="vertical-align: -2px" /> {{ warning }}
                </div>
              </div>
              <div v-else class="alert">
                <Sparkles :size="12" style="vertical-align: -2px; color: var(--accent-2)" />
                Live progress streams from the shared job system. Assets appear here as soon as they are written.
              </div>
            </div>
          </div>
        </section>

        <div class="video-editor-grid">
          <!-- Scene rail -->
          <section class="panel video-scene-rail">
            <div class="panel-head">
              <div>
                <h3>Scenes</h3>
                <p>{{ scenes.length }} planned · select to inspect</p>
              </div>
              <span class="chip">{{ selectedScene ? `${selectedSceneIndex + 1}/${scenes.length}` : "—" }}</span>
            </div>
            <div class="video-scene-list">
              <button
                v-for="(scene, index) in scenes"
                :key="scene.scene_id"
                class="video-scene-item"
                :class="{ active: scene.scene_id === selectedScene?.scene_id }"
                type="button"
                @click="selectScene(scene.scene_id)"
              >
                <span class="video-scene-thumb">
                  <img v-if="scene.thumbnail_path || scene.image_path" :src="mediaUrl(scene.thumbnail_path || scene.image_path)" :alt="`Scene ${index + 1}`" loading="lazy" />
                  <span v-else class="video-scene-thumb-empty"><ImageIcon :size="16" /></span>
                  <span class="video-scene-number">{{ index + 1 }}</span>
                  <span v-if="scene.video_path" class="video-scene-film"><Film :size="9" /></span>
                </span>
                <span class="video-scene-info">
                  <span class="row-between">
                    <strong>{{ scene.section_label || titleCase(scene.section_kind) }}</strong>
                    <span class="badge" :class="sceneTone(scene.status)">{{ (scene.status || "planned").replace("_", " ") }}</span>
                  </span>
                  <span class="video-scene-time">{{ sceneTimeRange(scene) }} · {{ scene.duration.toFixed(1) }}s</span>
                  <span class="video-scene-meta">{{ cameraLabel(scene.camera.movement) }} · {{ transitionLabel(scene.transition.type) }}</span>
                </span>
              </button>
              <div v-if="!scenes.length" class="video-rail-empty">
                <Layers :size="22" />
                <strong>No scenes yet</strong>
                <p>Plan the story to populate the timeline and inspector.</p>
                <button class="btn btn-sm" :disabled="actionsDisabled" @click="runAction('plan', { force: true })"><Layers :size="12" /> Plan scenes</button>
              </div>
            </div>
            <div class="panel-footer video-rail-footer">
              <button class="btn btn-sm btn-ghost" @click="tab = 'projects'"><FolderOpen :size="12" /> Projects</button>
              <button class="btn btn-sm" :disabled="actionsDisabled" @click="runAction('plan', { force: true })"><Layers :size="12" /> Re-plan</button>
            </div>
          </section>

          <!-- Preview and timeline -->
          <div class="stack">
            <section class="panel video-preview-panel">
              <div class="panel-head">
                <div>
                  <h3>Preview</h3>
                  <p>{{ showFinalVideo ? "Final master with burned-in subtitles" : "Artwork, camera language and subtitle styling" }}</p>
                </div>
                <span class="chip" :class="{ success: showFinalVideo }"><Eye :size="11" /> {{ showFinalVideo ? "Final video" : "Scene preview" }}</span>
              </div>

              <div class="video-preview-stage" :class="{ 'is-playing': previewPlaying }" :style="previewStageStyle">
                <video
                  v-if="showFinalVideo"
                  class="video-final-player"
                  :src="finalVideoSrc"
                  :poster="currentThumbnail || undefined"
                  controls
                  playsinline
                />
                <template v-else>
                  <img v-if="projectPoster" class="video-preview-poster" :src="projectPoster" :alt="currentProject.title" />
                  <div v-else class="video-poster-fallback"><Clapperboard :size="38" /></div>
                  <div class="video-preview-vignette" />
                  <div class="video-preview-top">
                    <div class="row" style="gap: 6px">
                      <span class="badge success"><Eye :size="9" /> Preview</span>
                      <span class="badge">{{ currentProject.config.output.aspect_ratio }}</span>
                      <span v-if="exportForm.audio_reactive.enabled" class="badge warn"><Zap :size="9" /> Reactive</span>
                    </div>
                    <span class="video-preview-resolution">{{ currentProject.width }} × {{ currentProject.height }} · {{ exportForm.output.fps }} fps</span>
                  </div>

                  <button class="video-preview-play" type="button" :title="previewPlaying ? 'Pause' : 'Play preview'" @click="togglePreview">
                    <Pause v-if="previewPlaying" :size="22" />
                    <Play v-else :size="22" />
                  </button>

                  <div class="video-preview-now">
                    <span class="video-preview-now-dot" />
                    <span v-if="selectedScene">Scene {{ selectedScene.scene_id }} · {{ titleCase(selectedScene.section_kind) }}</span>
                    <span v-else>{{ currentStyleName }}</span>
                    <span class="mono">{{ formatClock(previewTime) }}</span>
                  </div>

                  <div class="video-preview-subtitle-zone" :class="subtitlePositionClass">
                    <div v-if="previewLine" class="video-preview-subtitle" :style="previewSubtitleStyle">
                      {{ previewLine }}
                      <span v-if="exportForm.subtitles.karaoke" class="video-preview-karaoke" :style="{ width: `${previewCuePercent}%` }" />
                    </div>
                  </div>

                  <div class="video-preview-progress"><span :style="{ width: `${previewPercent}%` }" /></div>
                </template>
              </div>

              <div v-if="!showFinalVideo" class="video-preview-controls">
                <button class="video-preview-control-btn" type="button" :title="previewPlaying ? 'Pause' : 'Play'" @click="togglePreview">
                  <Pause v-if="previewPlaying" :size="14" />
                  <Play v-else :size="14" />
                </button>
                <input class="video-preview-scrub" type="range" min="0" :max="previewDuration" step="0.05" :value="previewTime" @input="onPreviewScrub" />
                <span class="mono small nowrap">{{ formatClock(previewTime) }} / {{ formatClock(previewDuration) }}</span>
                <span class="video-preview-control-detail"><Clapperboard :size="11" /> {{ selectedScene ? cameraLabel(selectedScene.camera.movement) : currentBackendLabel }}</span>
              </div>
              <div v-else class="video-preview-controls">
                <span class="video-preview-control-detail"><Captions :size="12" /> Subtitles are burned into the final video.</span>
                <span class="grow" />
                <a v-if="deliverableVideo && !DEMO" class="btn btn-sm btn-ghost" :href="downloadUrl(deliverableVideo)"><Download :size="12" /> Download master</a>
                <button v-else class="btn btn-sm btn-ghost" @click="demoDownload('The final video')"><Download :size="12" /> Download master</button>
              </div>
            </section>

            <section class="panel video-timeline-panel">
              <div class="panel-head">
                <div>
                  <h3>Timeline</h3>
                  <p>{{ scenes.length }} scenes · {{ subtitleLines.length }} subtitle cues · click to seek</p>
                </div>
                <span class="chip mono">{{ formatClock(previewTime) }}</span>
              </div>
              <div class="panel-body">
                <div class="video-timeline-composite" @click="onTimelineClick">
                  <div class="video-timeline-ruler">
                    <span v-for="marker in timelineMarkers" :key="marker.ratio" :style="{ left: `${marker.ratio * 100}%` }">{{ marker.label }}</span>
                  </div>
                  <div class="video-timeline-scenes">
                    <button
                      v-for="(scene, index) in scenes"
                      :key="scene.scene_id"
                      class="video-timeline-scene"
                      :class="{ active: scene.scene_id === selectedScene?.scene_id }"
                      type="button"
                      :style="{
                        left: sceneLeft(scene),
                        width: sceneWidth(scene),
                        background: `linear-gradient(135deg, ${sectionColor(scene.section_kind)}, ${sectionColor(scene.section_kind)}55)`,
                      }"
                      :title="`Scene ${index + 1} · ${sceneTimeRange(scene)} · ${cameraLabel(scene.camera.movement)}`"
                      @click.stop="selectScene(scene.scene_id)"
                    >
                      <span class="video-timeline-scene-index">{{ index + 1 }}</span>
                      <span class="video-timeline-scene-kind">{{ scene.section_kind }}</span>
                      <Film v-if="scene.video_path" :size="9" class="video-timeline-scene-film" />
                    </button>
                    <div v-if="!scenes.length" class="video-timeline-empty">No scenes planned</div>
                  </div>
                  <div class="video-timeline-cues">
                    <span
                      v-for="cue in subtitleLines"
                      :key="`${cue.index}-${cue.start}`"
                      class="video-timeline-cue"
                      :style="{ left: cueLeft(cue), width: cueWidth(cue) }"
                      :title="cue.text"
                    />
                  </div>
                  <div class="video-timeline-playhead" :style="{ left: `${previewPercent}%` }"><span /></div>
                </div>

                <div class="video-timeline-legend">
                  <span><i style="background: #22d3ee" /> intro</span>
                  <span><i style="background: #8b5cf6" /> verse</span>
                  <span><i style="background: #f59e0b" /> chorus</span>
                  <span><i style="background: #fb7185" /> bridge</span>
                  <span><i class="video-legend-cue" /> subtitle cue</span>
                  <span class="grow" />
                  <span>{{ scenes.filter((scene) => scene.video_path).length }}/{{ scenes.length }} animated</span>
                </div>

                <div class="video-timeline-audio">
                  <AudioPlayer
                    :src="audioSource"
                    :title="currentProject.title"
                    :subtitle="`Source track · ${formatDuration(currentProject.duration)}`"
                    :download-path="audioDownloadPath"
                    :bars="80"
                    compact
                  />
                </div>
              </div>
            </section>
          </div>

          <!-- Scene inspector -->
          <aside class="panel video-inspector">
            <div class="panel-head">
              <div>
                <h3>Scene inspector</h3>
                <p v-if="selectedScene">Scene {{ selectedScene.scene_id }} · {{ sceneTimeRange(selectedScene) }}</p>
                <p v-else>Select a scene to edit its prompt, motion and timing.</p>
              </div>
              <span v-if="sceneDirty" class="badge warn">Unsaved</span>
              <span v-else-if="selectedScene" class="badge success">Saved</span>
            </div>

            <div v-if="!selectedScene" class="panel-body">
              <EmptyState :icon="Layers" title="No scene selected" message="Select a scene in the rail or on the timeline to edit its story, image prompt, camera move and subtitle timing." />
            </div>

            <template v-else>
              <div class="video-inspector-scroll">
                <section class="video-inspector-section">
                  <div class="video-inspector-heading">
                    <h4>Artwork</h4>
                    <span class="badge" :class="sceneTone(selectedScene.status)">{{ selectedScene.image_source || "none" }}</span>
                  </div>
                  <div class="video-inspector-image">
                    <img v-if="selectedSceneImage" :src="selectedSceneImage" :alt="`Scene ${selectedScene.scene_id}`" />
                    <div v-else class="video-inspector-image-empty"><ImageIcon :size="24" /><span>No artwork generated</span></div>
                    <div class="video-inspector-image-foot">
                      <span>{{ (selectedScene.status || "planned").replace("_", " ") }}</span>
                      <span>{{ sceneVariants.length }} variant{{ sceneVariants.length === 1 ? "" : "s" }}</span>
                    </div>
                  </div>
                  <div class="video-image-path" :title="selectedScene.image_path || 'No image generated yet'">
                    <ImageIcon :size="10" />
                    <span class="truncate mono">{{ selectedScene.image_path || "No image path yet" }}</span>
                  </div>
                  <div v-if="sceneVariants.length > 1" class="video-variant-strip">
                    <button
                      v-for="variant in sceneVariants"
                      :key="variant"
                      class="video-variant-thumb"
                      :class="{ active: variant === selectedScene.image_path }"
                      type="button"
                      :disabled="editorLocked"
                      :title="basename(variant)"
                      @click="chooseVariant(variant)"
                    >
                      <img :src="mediaUrl(variant)" alt="Scene variant" loading="lazy" />
                    </button>
                  </div>
                  <div class="video-inspector-actions">
                    <button class="btn btn-sm" :disabled="actionsDisabled || uploadingScene" @click="triggerRegenerate(true, false)">
                      <Sparkles :size="12" /> New image
                    </button>
                    <button class="btn btn-sm" :disabled="actionsDisabled || uploadingScene" @click="triggerRegenerate(false, true)">
                      <Clapperboard :size="12" /> Re-animate
                    </button>
                    <button class="btn btn-sm btn-ghost" :disabled="editorLocked || uploadingScene" @click="requestImageUpload">
                      <Upload :size="12" /> Upload
                    </button>
                    <input ref="imageInput" type="file" accept="image/*" hidden @change="uploadSceneImage" />
                  </div>
                  <div class="video-depth-row">
                    <span class="small muted">Depth map</span>
                    <span v-if="selectedScene.depth_map_path" class="badge success">ready</span>
                    <button class="btn btn-sm btn-ghost" :disabled="editorLocked || uploadingScene" @click="requestDepthUpload">
                      <Upload :size="11" /> {{ selectedScene.depth_map_path ? "Replace" : "Upload depth" }}
                    </button>
                    <input ref="depthInput" type="file" accept="image/*" hidden @change="uploadSceneDepth" />
                  </div>
                </section>

                <section class="video-inspector-section">
                  <div class="video-inspector-heading">
                    <h4>Story & prompt</h4>
                    <span class="small muted">{{ selectedScene.subtitle_indices.length }} cue{{ selectedScene.subtitle_indices.length === 1 ? "" : "s" }}</span>
                  </div>
                  <div class="field">
                    <label>Scene description</label>
                    <textarea v-model="sceneForm.description" class="textarea" style="min-height: 68px" />
                  </div>
                  <div class="field" style="margin-top: 10px">
                    <label>Image prompt</label>
                    <textarea v-model="sceneForm.visual_prompt" class="textarea" style="min-height: 94px" />
                    <span class="hint">Project style, palette and global visual prompt are added automatically when generating.</span>
                  </div>
                  <details class="video-details">
                    <summary>Negative prompt & lyrics</summary>
                    <div class="field" style="margin-top: 10px">
                      <label>Negative prompt</label>
                      <textarea v-model="sceneForm.negative_prompt" class="textarea" style="min-height: 58px" />
                    </div>
                    <div class="field" style="margin-top: 10px">
                      <label>Lyrics on this scene</label>
                      <textarea v-model="sceneForm.lyrics" class="textarea" style="min-height: 58px" />
                    </div>
                  </details>
                </section>

                <section class="video-inspector-section">
                  <div class="video-inspector-heading">
                    <h4>Camera & transition</h4>
                    <span class="badge">{{ transitionLabel(sceneForm.transition) }}</span>
                  </div>
                  <div class="field">
                    <label>Camera move</label>
                    <select v-model="sceneForm.camera" class="select">
                      <option v-for="camera in catalog.cameras" :key="camera.value" :value="camera.value">{{ camera.label }}</option>
                    </select>
                    <span class="hint">{{ cameraHint(sceneForm.camera) }}</span>
                  </div>
                  <div class="field" style="margin-top: 10px">
                    <label>Transition out</label>
                    <select v-model="sceneForm.transition" class="select">
                      <option v-for="transition in catalog.transitions" :key="transition.value" :value="transition.value">{{ transition.label }}</option>
                    </select>
                  </div>
                  <div class="video-inline-fields">
                    <div class="field">
                      <div class="row-between"><label>Zoom</label><span class="small mono">{{ Number(sceneForm.zoom).toFixed(2) }}×</span></div>
                      <input v-model.number="sceneForm.zoom" type="range" min="1" max="1.6" step="0.01" />
                    </div>
                    <div class="field">
                      <div class="row-between"><label>Transition length</label><span class="small mono">{{ Number(sceneForm.transition_duration).toFixed(2) }}s</span></div>
                      <input v-model.number="sceneForm.transition_duration" type="range" min="0" max="2" step="0.05" :disabled="sceneForm.transition === 'cut'" />
                    </div>
                  </div>
                  <details class="video-details">
                    <summary>Handheld, pan and rotation detail</summary>
                    <div class="video-inline-fields" style="margin-top: 10px">
                      <div class="field">
                        <div class="row-between"><label>Pan X</label><span class="small mono">{{ Number(sceneForm.pan_x).toFixed(2) }}</span></div>
                        <input v-model.number="sceneForm.pan_x" type="range" min="-1" max="1" step="0.02" />
                      </div>
                      <div class="field">
                        <div class="row-between"><label>Pan Y</label><span class="small mono">{{ Number(sceneForm.pan_y).toFixed(2) }}</span></div>
                        <input v-model.number="sceneForm.pan_y" type="range" min="-1" max="1" step="0.02" />
                      </div>
                    </div>
                    <div class="field" style="margin-top: 10px">
                      <div class="row-between"><label>Rotation</label><span class="small mono">{{ Number(sceneForm.rotation).toFixed(1) }}°</span></div>
                      <input v-model.number="sceneForm.rotation" type="range" min="-3" max="3" step="0.1" />
                    </div>
                  </details>
                </section>

                <section class="video-inspector-section">
                  <div class="video-inspector-heading">
                    <h4>Visual effects</h4>
                    <span class="small muted">{{ sceneForm.effects.length }} active</span>
                  </div>
                  <div class="pill-row">
                    <button
                      v-for="effect in catalog.effects"
                      :key="effect.id"
                      class="chip clickable"
                      :class="{ active: sceneForm.effects.includes(effect.id) }"
                      type="button"
                      :title="effect.description"
                      @click="toggleEffect(effect.id)"
                    >
                      <Check v-if="sceneForm.effects.includes(effect.id)" :size="10" />
                      {{ effect.label }}
                    </button>
                  </div>
                </section>

                <section class="video-inspector-section">
                  <div class="video-inspector-heading">
                    <h4>Timing</h4>
                    <span class="badge">{{ sceneFormDuration.toFixed(1) }}s</span>
                  </div>
                  <div class="video-inline-fields">
                    <div class="field">
                      <label>Start</label>
                      <input class="input" :value="formatClock(sceneForm.start)" disabled />
                    </div>
                    <div class="field">
                      <label>End</label>
                      <input v-model.number="sceneForm.end" class="input" type="number" :min="sceneForm.start + 0.5" :max="maxSceneEnd" step="0.1" />
                    </div>
                  </div>
                  <div class="row-between small muted" style="margin-top: 7px">
                    <span>Start follows the previous scene.</span>
                    <span>{{ formatClock(sceneForm.start) }} → {{ formatClock(sceneForm.end) }}</span>
                  </div>
                </section>

                <section class="video-inspector-section">
                  <div class="video-inspector-heading">
                    <h4>Generation</h4>
                    <span class="badge">{{ providerLabel(regenProvider) }}</span>
                  </div>
                  <div class="video-inline-fields">
                    <div class="field">
                      <label>Image provider</label>
                      <select v-model="regenProvider" class="select">
                        <option v-for="provider in catalog.providers" :key="provider.value" :value="provider.value">{{ provider.label }}</option>
                      </select>
                    </div>
                    <div class="field">
                      <label>Variants</label>
                      <select v-model.number="regenVariants" class="select">
                        <option v-for="count in maxSceneVariants" :key="count" :value="count">{{ count }}</option>
                      </select>
                    </div>
                  </div>
                  <div class="field" style="margin-top: 10px">
                    <label>Seed</label>
                    <input v-model.number="sceneForm.seed" class="input" type="number" min="0" step="1" />
                  </div>
                  <div class="video-inspector-actions">
                    <button class="btn btn-sm btn-primary" :disabled="actionsDisabled" @click="triggerRegenerate(true, true)">
                      <RefreshCw :size="12" :class="{ spin: actionBusy === 'regenerate' }" /> Regenerate image & motion
                    </button>
                  </div>
                  <div class="alert" style="margin-top: 9px">
                    {{ providerLabel(regenProvider) }} uses the project style and this scene prompt. Procedural art never claims to be AI generated.
                  </div>
                </section>
              </div>

              <div class="video-inspector-footer">
                <button class="btn btn-sm btn-primary" :disabled="!sceneDirty || savingScene || editorLocked" @click="saveScene(false)">
                  <Save :size="12" :class="{ spin: savingScene }" /> {{ savingScene ? "Saving…" : "Save scene" }}
                </button>
                <button class="icon-btn" :disabled="selectedSceneIndex <= 0 || reorderingScene || editorLocked" title="Move scene content earlier" @click="moveScene(-1)">
                  <ArrowUp :size="14" />
                </button>
                <button class="icon-btn" :disabled="selectedSceneIndex < 0 || selectedSceneIndex >= scenes.length - 1 || reorderingScene || editorLocked" title="Move scene content later" @click="moveScene(1)">
                  <ArrowDown :size="14" />
                </button>
                <button class="btn btn-sm btn-ghost" :disabled="!sceneDirty" @click="resetSceneForm">Reset</button>
              </div>
            </template>
          </aside>
        </div>

        <!-- Export panel -->
        <section class="panel video-export-panel">
          <div class="panel-head">
            <div>
              <h3>Delivery & export</h3>
              <p>Resolution, encoding, subtitle burn-in, reactivity and the rendered deliverables.</p>
            </div>
            <div class="row" style="gap: 7px">
              <button class="btn btn-sm" :disabled="!exportDirty || savingConfig || editorLocked" @click="saveProjectConfig(false)">
                <Save :size="12" :class="{ spin: savingConfig }" /> {{ savingConfig ? "Saving…" : "Save settings" }}
              </button>
              <button class="btn btn-sm btn-primary" :disabled="actionsDisabled" @click="triggerRender">
                <Film :size="12" :class="{ spin: actionBusy === 'render' }" /> Render final video
              </button>
            </div>
          </div>

          <div class="panel-body video-export-grid">
            <div class="stack" style="gap: 14px">
              <div class="video-export-section">
                <div class="video-export-section-head">
                  <h4><Film :size="13" /> Video output</h4>
                  <span class="chip mono">{{ exportDimensions.width }} × {{ exportDimensions.height }}</span>
                </div>
                <div class="video-export-fields">
                  <div class="field">
                    <label>Resolution</label>
                    <select v-model="exportForm.output.resolution" class="select" :disabled="editorLocked">
                      <option v-for="resolution in catalog.resolutions" :key="resolution.value" :value="resolution.value">{{ resolution.label }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Aspect ratio</label>
                    <select v-model="exportForm.output.aspect_ratio" class="select" :disabled="editorLocked">
                      <option v-for="aspect in catalog.aspects" :key="aspect.value" :value="aspect.value">{{ aspect.label }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Frame rate</label>
                    <select v-model.number="exportForm.output.fps" class="select" :disabled="editorLocked">
                      <option v-for="fps in catalog.fps" :key="fps" :value="fps">{{ fps }} fps</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Codec</label>
                    <select v-model="exportForm.output.codec" class="select" :disabled="editorLocked">
                      <option v-for="codec in catalog.codecs" :key="codec.value" :value="codec.value">{{ codec.label }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Quality</label>
                    <select v-model="exportForm.output.quality" class="select" :disabled="editorLocked">
                      <option v-for="quality in catalog.qualities" :key="quality.value" :value="quality.value">{{ quality.label }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Audio bitrate</label>
                    <select v-model="exportForm.output.audio_bitrate" class="select" :disabled="editorLocked">
                      <option v-for="bitrate in catalog.audioBitrates" :key="bitrate" :value="bitrate">{{ bitrate }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Output filename</label>
                    <input v-model="exportForm.output.output_filename" class="input" :disabled="editorLocked" placeholder="final_video.mp4" />
                  </div>
                  <div class="field">
                    <label>Output directory <span class="muted">(optional)</span></label>
                    <input v-model="exportForm.output.output_dir" class="input" :disabled="editorLocked" placeholder="Default project output folder" />
                  </div>
                </div>
                <div class="video-export-switches">
                  <label class="video-check"><input v-model="exportForm.output.burn_subtitles" type="checkbox" :disabled="editorLocked" /> Burn styled subtitles into the video</label>
                  <label class="video-check"><input v-model="exportForm.output.export_srt" type="checkbox" :disabled="editorLocked" /> Export the original-timestamp SRT</label>
                </div>
                <details class="video-details">
                  <summary>Advanced encoding</summary>
                  <div class="video-export-fields" style="margin-top: 10px">
                    <div class="field">
                      <label>Encoder preset</label>
                      <select v-model="exportForm.output.preset" class="select" :disabled="editorLocked">
                        <option v-for="preset in catalog.presets" :key="preset" :value="preset">{{ preset }}</option>
                      </select>
                    </div>
                    <div class="field">
                      <label>CRF override</label>
                      <input
                        class="input"
                        type="number"
                        min="0"
                        max="51"
                        placeholder="Auto from quality"
                        :value="exportForm.output.crf ?? ''"
                        :disabled="editorLocked"
                        @input="setExportCrf"
                      />
                    </div>
                  </div>
                </details>
                <div class="alert" style="margin-top: 10px">
                  <AlertTriangle :size="12" style="vertical-align: -2px; color: var(--warning)" />
                  Changing resolution or frame rate requires a re-render. Scene clips are preserved until you animate again.
                </div>
              </div>

              <div class="video-export-section">
                <div class="video-export-section-head">
                  <h4><Captions :size="13" /> Subtitles</h4>
                  <span class="chip">{{ exportForm.subtitles.position }} · {{ exportForm.subtitles.karaoke ? "karaoke" : "line" }}</span>
                </div>
                <div class="video-export-fields">
                  <div class="field">
                    <label>Font</label>
                    <select v-model="exportForm.subtitles.font_family" class="select" :disabled="editorLocked">
                      <option v-for="font in catalog.subtitleFonts" :key="font" :value="font">{{ font }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Position</label>
                    <select v-model="exportForm.subtitles.position" class="select" :disabled="editorLocked">
                      <option v-for="position in catalog.subtitlePositions" :key="position" :value="position">{{ titleCase(position) }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Font size</label>
                    <input v-model.number="exportForm.subtitles.font_size" class="input" type="number" min="12" max="180" :disabled="editorLocked" />
                  </div>
                  <div class="field">
                    <label>Alignment</label>
                    <select v-model="exportForm.subtitles.alignment" class="select" :disabled="editorLocked">
                      <option v-for="alignment in catalog.subtitleAlignments" :key="alignment" :value="alignment">{{ titleCase(alignment) }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Text color</label>
                    <div class="video-color-field">
                      <input v-model="exportForm.subtitles.primary_color" type="color" :disabled="editorLocked" />
                      <span class="mono">{{ exportForm.subtitles.primary_color }}</span>
                    </div>
                  </div>
                  <div class="field">
                    <label>Karaoke highlight</label>
                    <div class="video-color-field">
                      <input v-model="exportForm.subtitles.highlight_color" type="color" :disabled="editorLocked" />
                      <span class="mono">{{ exportForm.subtitles.highlight_color }}</span>
                    </div>
                  </div>
                </div>
                <div class="video-export-switches">
                  <label class="video-check"><input v-model="exportForm.subtitles.karaoke" type="checkbox" :disabled="editorLocked" /> Karaoke-style line emphasis</label>
                  <label class="video-check"><input v-model="exportForm.subtitles.background" type="checkbox" :disabled="editorLocked" /> Subtle background box</label>
                </div>
                <details class="video-details">
                  <summary>Outline, shadow, margin and box</summary>
                  <div class="video-export-fields" style="margin-top: 10px">
                    <div class="field">
                      <label>Outline color</label>
                      <div class="video-color-field"><input v-model="exportForm.subtitles.outline_color" type="color" :disabled="editorLocked" /><span class="mono">{{ exportForm.subtitles.outline_color }}</span></div>
                    </div>
                    <div class="field">
                      <label>Outline width</label>
                      <input v-model.number="exportForm.subtitles.outline_width" class="input" type="number" min="0" max="12" step="0.5" :disabled="editorLocked" />
                    </div>
                    <div class="field">
                      <label>Shadow</label>
                      <input v-model.number="exportForm.subtitles.shadow" class="input" type="number" min="0" max="12" step="0.5" :disabled="editorLocked" />
                    </div>
                    <div class="field">
                      <label>Vertical margin</label>
                      <input v-model.number="exportForm.subtitles.margin_v" class="input" type="number" min="0" max="1000" :disabled="editorLocked" />
                    </div>
                    <div class="field">
                      <label>Max line width</label>
                      <input v-model.number="exportForm.subtitles.max_line_width" class="input" type="number" min="10" max="140" :disabled="editorLocked" />
                    </div>
                    <div class="field" v-if="exportForm.subtitles.background">
                      <label>Box color</label>
                      <div class="video-color-field"><input v-model="exportForm.subtitles.background_color" type="color" :disabled="editorLocked" /><span class="mono">{{ exportForm.subtitles.background_color }}</span></div>
                    </div>
                    <div class="field" v-if="exportForm.subtitles.background">
                      <label>Box opacity · {{ Math.round(exportForm.subtitles.background_opacity * 100) }}%</label>
                      <input v-model.number="exportForm.subtitles.background_opacity" type="range" min="0" max="1" step="0.05" :disabled="editorLocked" />
                    </div>
                  </div>
                </details>
              </div>

              <div class="video-export-section">
                <div class="video-export-section-head">
                  <h4><Zap :size="13" /> Music reactivity</h4>
                  <span class="chip" :class="{ active: exportForm.audio_reactive.enabled }">{{ exportForm.audio_reactive.enabled ? `${Math.round(exportForm.audio_reactive.intensity * 100)}%` : "off" }}</span>
                </div>
                <div class="video-reactive-grid">
                  <div class="video-switch-row"><div><strong>Audio-reactive visuals</strong><span>Beat-synced cuts, light pulses and motion accents.</span></div><div class="switch" :class="{ on: exportForm.audio_reactive.enabled }" role="switch" :aria-checked="exportForm.audio_reactive.enabled" @click="exportForm.audio_reactive.enabled = !exportForm.audio_reactive.enabled" /></div>
                  <div class="video-switch-row"><div><strong>Beat cuts</strong><span>Cut scenes on strong beats and downbeats.</span></div><div class="switch" :class="{ on: exportForm.audio_reactive.beat_cuts }" role="switch" :aria-checked="exportForm.audio_reactive.beat_cuts" @click="exportForm.audio_reactive.beat_cuts = !exportForm.audio_reactive.beat_cuts" /></div>
                  <div class="video-switch-row"><div><strong>Beat pulse</strong><span>Brightness and zoom pulses on the beat.</span></div><div class="switch" :class="{ on: exportForm.audio_reactive.beat_pulse }" role="switch" :aria-checked="exportForm.audio_reactive.beat_pulse" @click="exportForm.audio_reactive.beat_pulse = !exportForm.audio_reactive.beat_pulse" /></div>
                  <div class="video-switch-row"><div><strong>Bass pulse</strong><span>Low-end light blooms and camera energy.</span></div><div class="switch" :class="{ on: exportForm.audio_reactive.bass_pulse }" role="switch" :aria-checked="exportForm.audio_reactive.bass_pulse" @click="exportForm.audio_reactive.bass_pulse = !exportForm.audio_reactive.bass_pulse" /></div>
                  <div class="video-switch-row"><div><strong>Particles</strong><span>Dust and fireflies on high-energy scenes.</span></div><div class="switch" :class="{ on: exportForm.audio_reactive.particles }" role="switch" :aria-checked="exportForm.audio_reactive.particles" @click="exportForm.audio_reactive.particles = !exportForm.audio_reactive.particles" /></div>
                  <div class="video-switch-row"><div><strong>Intensity</strong><span>{{ Math.round(exportForm.audio_reactive.intensity * 100) }}% reaction strength</span></div><input v-model.number="exportForm.audio_reactive.intensity" type="range" min="0" max="1" step="0.05" style="max-width: 150px" :disabled="!exportForm.audio_reactive.enabled" /></div>
                </div>
              </div>
            </div>

            <div class="stack" style="gap: 14px">
              <div class="video-export-section">
                <div class="video-export-section-head">
                  <h4><Download :size="13" /> Deliverables</h4>
                  <span class="badge" :class="deliverableVideo ? 'success' : 'queued'">{{ deliverableVideo ? "Ready" : "Pending" }}</span>
                </div>
                <div class="video-deliverables">
                  <div class="video-deliverable" :class="{ ready: deliverableVideo }">
                    <span class="video-deliverable-icon"><FileVideo :size="16" /></span>
                    <div class="grow" style="min-width: 0"><strong>Final video</strong><span>{{ basename(deliverableVideo) || "Render the final master" }}</span></div>
                    <a v-if="deliverableVideo && !DEMO" class="icon-btn" :href="downloadUrl(deliverableVideo)" :title="'Download ' + basename(deliverableVideo)"><Download :size="14" /></a>
                    <button v-else-if="deliverableVideo" class="icon-btn" title="Download final video" @click="demoDownload('The final video')"><Download :size="14" /></button>
                    <span v-else class="badge queued">Pending</span>
                  </div>
                  <div class="video-deliverable" :class="{ ready: deliverableSrt }">
                    <span class="video-deliverable-icon"><FileText :size="16" /></span>
                    <div class="grow" style="min-width: 0"><strong>Subtitles</strong><span>{{ basename(deliverableSrt) || "Original SRT timing" }}</span></div>
                    <a v-if="deliverableSrt && !DEMO" class="icon-btn" :href="downloadUrl(deliverableSrt)" title="Download subtitles"><Download :size="14" /></a>
                    <button v-else-if="deliverableSrt" class="icon-btn" title="Download subtitles" @click="demoDownload('The SRT')"><Download :size="14" /></button>
                    <span v-else class="badge queued">Pending</span>
                  </div>
                  <div class="video-deliverable" :class="{ ready: deliverableThumbnail }">
                    <span class="video-deliverable-icon"><FileImage :size="16" /></span>
                    <div class="grow" style="min-width: 0"><strong>Thumbnail</strong><span>{{ basename(deliverableThumbnail) || "Poster still" }}</span></div>
                    <a v-if="deliverableThumbnail && !DEMO" class="icon-btn" :href="fileUrl(deliverableThumbnail)" target="_blank" rel="noopener" title="Open thumbnail"><Eye :size="14" /></a>
                    <button v-else-if="deliverableThumbnail" class="icon-btn" title="Open thumbnail" @click="demoDownload('The thumbnail')"><Eye :size="14" /></button>
                    <span v-else class="badge queued">Pending</span>
                  </div>
                  <div class="video-deliverable" :class="{ ready: deliverableZip }">
                    <span class="video-deliverable-icon"><Archive :size="16" /></span>
                    <div class="grow" style="min-width: 0"><strong>Project archive</strong><span>{{ basename(deliverableZip) || "Video, SRT and assets" }}</span></div>
                    <a v-if="deliverableZip && !DEMO" class="icon-btn" :href="downloadUrl(deliverableZip)" title="Download project archive"><Download :size="14" /></a>
                    <button v-else-if="deliverableZip" class="icon-btn" title="Download project archive" @click="demoDownload('The project archive')"><Download :size="14" /></button>
                    <button v-else class="btn btn-sm btn-ghost" :disabled="archiveBusy || !videoAssets.length" @click="createArchive"><Archive :size="11" /> {{ archiveBusy ? "Zipping…" : "Create ZIP" }}</button>
                  </div>
                </div>
              </div>

              <div class="video-export-section video-assets-section">
                <div class="video-export-section-head">
                  <h4><FolderOpen :size="13" /> Project assets</h4>
                  <button class="btn btn-sm btn-ghost" :disabled="!currentProject" @click="loadAssets()"><RefreshCw :size="11" /> Refresh</button>
                </div>
                <div class="video-asset-list">
                  <div v-for="asset in videoAssets" :key="asset.path" class="video-asset-row">
                    <span class="video-asset-icon"><component :is="assetIcon(asset)" :size="13" /></span>
                    <div class="grow" style="min-width: 0">
                      <span class="strong truncate">{{ assetName(asset) }}</span>
                      <span class="small muted">{{ assetKindLabel(asset) }} · {{ asset.size ? formatBytes(asset.size) : "—" }}</span>
                    </div>
                    <a v-if="!DEMO" class="icon-btn" :href="downloadUrl(asset.path)" :title="'Download ' + assetName(asset)"><Download :size="13" /></a>
                    <button v-else class="icon-btn" title="Download asset" @click="demoDownload(assetName(asset))"><Download :size="13" /></button>
                  </div>
                  <div v-if="!videoAssets.length" class="small muted" style="padding: 10px 2px">Assets appear once the project has written media to shared storage.</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- Activity log and job history -->
        <div class="video-activity-grid">
          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Generation log</h3>
                <p>Warnings and live pipeline messages, never hidden.</p>
              </div>
              <span class="chip mono">{{ currentJob ? currentJob.id.slice(-8) : "idle" }}</span>
            </div>
            <div class="panel-body stack" style="gap: 9px">
              <div v-for="warning in currentJobWarnings.slice(-4)" :key="warning" class="alert warn">
                <AlertTriangle :size="12" style="vertical-align: -2px" /> {{ warning }}
              </div>
              <div class="video-log">
                <div v-for="(line, index) in currentJobLogs" :key="`${line.message}-${index}`" class="video-log-row" :class="line.level">
                  <span class="video-log-time">{{ logTime(line.timestamp) }}</span>
                  <span class="video-log-dot" />
                  <span>{{ line.message }}</span>
                </div>
                <div v-if="!currentJobLogs.length" class="video-log-empty">
                  Pipeline messages appear here. Run analysis, planning, images, animation or the full pipeline to see live progress.
                </div>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Video job history</h3>
                <p>All jobs submitted to the shared video queue.</p>
              </div>
              <button class="btn btn-sm btn-ghost" @click="tab = 'render'">Queue <ChevronRight :size="11" /></button>
            </div>
            <div class="panel-body stack" style="gap: 10px">
              <JobCard
                v-for="job in videoJobs.slice(0, 3)"
                :key="job.id"
                :job="job"
                compact
                @cancel="cancelJob"
                @retry="retryJob"
                @remove="removeJob"
              />
              <EmptyState v-if="!videoJobs.length" :icon="Activity" title="No video jobs yet" message="Your analysis, planning, image, animation and render jobs will be listed here with live progress." />
            </div>
          </section>
        </div>
      </template>
    </section>

    <!-- ================================================================= -->
    <!-- Render queue                                                       -->
    <!-- ================================================================= -->
    <section v-else class="stack">
      <div class="stat-grid">
        <div class="stat">
          <div class="stat-label">Queued</div>
          <div class="stat-value">{{ queueMetrics.queued }}</div>
          <div class="stat-sub">Waiting for a video worker</div>
        </div>
        <div class="stat">
          <div class="stat-label">Running</div>
          <div class="stat-value">{{ queueMetrics.running }}</div>
          <div class="stat-sub">{{ queueMetrics.concurrency }}× concurrency · {{ queueMetrics.running }} active</div>
        </div>
        <div class="stat">
          <div class="stat-label">Completed</div>
          <div class="stat-value">{{ queueMetrics.completed }}</div>
          <div class="stat-sub">All-time queue completions in shared storage</div>
        </div>
        <div class="stat">
          <div class="stat-label">Failed / canceled</div>
          <div class="stat-value">{{ queueMetrics.failed }}</div>
          <div class="stat-sub">Retry keeps the original parameters</div>
        </div>
      </div>

      <div class="video-render-layout">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>Render queue</h3>
              <p>Every job submitted by this studio to the component <span class="mono">video</span> queue.</p>
            </div>
            <div class="row" style="gap: 7px">
              <span class="chip" :class="{ success: videoWorkerOnline }"><span class="dot" :class="videoWorkerOnline ? 'online' : 'offline'" /> {{ videoWorkerOnline ? "Worker online" : "Worker offline" }}</span>
              <button class="btn btn-sm" @click="jobs.refresh()"><RefreshCw :size="12" /> Refresh</button>
            </div>
          </div>
          <div class="panel-body stack">
            <div class="video-queue-summary">
              <div class="video-queue-worker">
                <span class="file-icon"><Clapperboard :size="15" /></span>
                <div><span>Component queue</span><strong>video</strong></div>
                <span class="badge running">{{ queueMetrics.concurrency }}× concurrency</span>
              </div>
              <div class="video-queue-metrics">
                <div><span>Queued</span><strong>{{ queueMetrics.queued }}</strong></div>
                <div><span>Running</span><strong>{{ queueMetrics.running }}</strong></div>
                <div><span>Completed</span><strong>{{ queueMetrics.completed }}</strong></div>
                <div><span>Failed</span><strong>{{ queueMetrics.failed }}</strong></div>
              </div>
            </div>
            <ProgressBar :value="queueUtilization" :label="`${queueMetrics.running} running · ${queueMetrics.queued} waiting`" show-label />
            <div class="stack" style="gap: 10px">
              <JobCard
                v-for="job in videoJobs"
                :key="job.id"
                :job="job"
                @cancel="cancelJob"
                @retry="retryJob"
                @remove="removeJob"
              />
              <EmptyState
                v-if="!videoJobs.length"
                :icon="Film"
                title="The video queue is idle"
                message="Run analysis, plan scenes, generate images, animate or render a final video. Each job appears here with live progress, warnings and artifacts."
              >
                <button class="btn btn-primary" @click="tab = 'editor'"><Clapperboard :size="14" /> Open the editor</button>
              </EmptyState>
            </div>
          </div>
        </section>

        <div class="stack">
          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Queue telemetry</h3>
                <p>Shared worker health across every component.</p>
              </div>
              <Activity :size="16" class="muted" />
            </div>
            <div class="panel-body stack" style="gap: 11px">
              <div class="video-queue-telemetry">
                <div><span>Concurrency</span><strong>{{ queueMetrics.concurrency }}</strong><ProgressBar :value="Math.min(100, (queueMetrics.concurrency / Math.max(1, queueMetrics.concurrency)) * 100)" thin /></div>
                <div><span>Running</span><strong>{{ queueMetrics.running }}</strong><ProgressBar :value="queueMetrics.concurrency ? (queueMetrics.running / queueMetrics.concurrency) * 100 : 0" thin /></div>
                <div><span>Waiting</span><strong>{{ queueMetrics.queued }}</strong><ProgressBar :value="queueMetrics.queued ? Math.min(100, (queueMetrics.queued / Math.max(1, queueMetrics.concurrency)) * 100) : 0" thin /></div>
                <div><span>Failures</span><strong>{{ queueMetrics.failed }}</strong><ProgressBar :value="queueMetrics.failed ? 100 : 0" thin /></div>
              </div>
              <div class="alert">
                <Zap :size="12" style="vertical-align: -2px; color: var(--warning)" />
                The video queue is independent of music, voice, subtitles and image jobs. A long render never blocks another studio.
              </div>
              <div class="row" style="gap: 6px">
                <span class="chip"><Captions :size="11" /> Subtitles</span>
                <span class="chip"><Film :size="11" /> Render</span>
                <span class="chip"><ImageIcon :size="11" /> Images</span>
                <span class="chip"><Music2 :size="11" /> Audio</span>
              </div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div>
                <h3>Latest master</h3>
                <p>{{ latestRenderJob ? `Job ${latestRenderJob.id.slice(-8)} completed` : currentProject?.final_video ? "Final master available on disk" : "No completed render yet" }}</p>
              </div>
              <Film :size="16" class="muted" />
            </div>
            <div class="panel-body stack" style="gap: 12px">
              <div class="video-latest-poster">
                <img v-if="currentThumbnail || projectPoster" :src="currentThumbnail || projectPoster" alt="Latest render poster" />
                <div v-else class="video-poster-fallback"><Film :size="24" /></div>
                <div class="video-latest-shade" />
                <span class="badge" :class="deliverableVideo ? 'success' : 'queued'">{{ deliverableVideo ? "Ready" : "Pending" }}</span>
                <div class="video-latest-caption">
                  <strong>{{ currentProject?.title || "No project selected" }}</strong>
                  <span>{{ currentProject ? `${formatDuration(currentProject.duration)} · ${currentProject.width} × ${currentProject.height}` : "Open a project to inspect its deliverables" }}</span>
                </div>
              </div>
              <div class="row" style="gap: 7px">
                <a v-if="deliverableVideo && !DEMO" class="btn btn-sm" :href="downloadUrl(deliverableVideo)"><Download :size="12" /> Final video</a>
                <button v-else-if="deliverableVideo" class="btn btn-sm" @click="demoDownload('The final video')"><Download :size="12" /> Final video</button>
                <a v-if="deliverableSrt && !DEMO" class="btn btn-sm btn-ghost" :href="downloadUrl(deliverableSrt)"><FileText :size="12" /> SRT</a>
                <button v-else-if="deliverableSrt" class="btn btn-sm btn-ghost" @click="demoDownload('The SRT')"><FileText :size="12" /> SRT</button>
                <button class="btn btn-sm btn-ghost" @click="tab = 'editor'">Editor <ChevronRight :size="12" /></button>
              </div>
              <div v-if="!currentProject" class="small muted">Open a project to see its final render and delivery links.</div>
            </div>
          </section>
        </div>
      </div>
    </section>

    <!-- ================================================================= -->
    <!-- New project modal                                                  -->
    <!-- ================================================================= -->
    <BaseModal
      v-model="newProjectOpen"
      title="New music video"
      subtitle="A song, its timed SRT lyrics, and a complete visual direction. Every field can be refined later in the editor."
      width="wide"
    >
      <div class="video-new-project">
        <section class="video-modal-section">
          <div class="video-modal-section-head">
            <span class="video-modal-number">01</span>
            <div>
              <h3>Song & lyrics</h3>
              <p>Both files are copied into the project and preserved for every render.</p>
            </div>
          </div>
          <div class="video-form-grid">
            <div class="field">
              <label>Project name</label>
              <input v-model="newDraft.name" class="input" placeholder="atravessar-a-noite" />
              <span class="hint">Used for the project folder and URL slug.</span>
            </div>
            <div class="field">
              <label>Song title <span class="muted">(optional)</span></label>
              <input v-model="newDraft.title" class="input" placeholder="Atravessar a Noite" />
            </div>
            <div class="field span-2">
              <label>Artist <span class="muted">(optional)</span></label>
              <input v-model="newDraft.artist" class="input" placeholder="Helena Rocha" />
            </div>
          </div>

          <div class="video-source-grid">
            <div class="video-source-card" :class="{ filled: newDraft.audio_path }">
              <span class="video-source-icon"><Music2 :size="19" /></span>
              <div class="video-source-copy">
                <strong>Audio track</strong>
                <span class="mono truncate">{{ newDraft.audio_path || "No audio selected" }}</span>
                <small>MP3, WAV, FLAC, M4A, AAC, OGG, Opus or AIFF</small>
              </div>
              <div class="video-source-actions">
                <button class="btn btn-sm" @click="chooseDraftAudio">{{ newDraft.audio_path ? "Replace" : "Choose file" }}</button>
                <button v-if="newDraft.audio_path" class="icon-btn" title="Clear audio" @click="newDraft.audio_path = ''; newDraft.audio_name = ''"><XIcon :size="13" /></button>
              </div>
            </div>

            <div class="video-source-card" :class="{ filled: newDraft.srt_path }">
              <span class="video-source-icon"><Captions :size="19" /></span>
              <div class="video-source-copy">
                <strong>Timed lyrics · SRT</strong>
                <span class="mono truncate">{{ newDraft.srt_path || "No subtitle file selected" }}</span>
                <small>.srt only · original timestamps are preserved exactly</small>
              </div>
              <div class="video-source-actions">
                <button class="btn btn-sm" @click="chooseDraftSrt">{{ newDraft.srt_path ? "Replace" : "Choose file" }}</button>
                <button v-if="newDraft.srt_path" class="icon-btn" title="Clear subtitles" @click="newDraft.srt_path = ''; newDraft.srt_name = ''"><XIcon :size="13" /></button>
              </div>
            </div>
          </div>

          <div class="alert" style="margin-top: 12px">
            <Upload :size="12" style="vertical-align: -2px; color: var(--accent-2)" />
            Choose from shared storage or upload directly in the file picker. The video worker validates the audio duration and SRT cues before creating the project.
          </div>
        </section>

        <section class="video-modal-section">
          <div class="video-modal-section-head">
            <span class="video-modal-number">02</span>
            <div>
              <h3>Visual direction</h3>
              <p>Art direction, image provider and animation engine for the complete film.</p>
            </div>
          </div>

          <div class="field">
            <label>Style preset</label>
            <div class="video-style-grid">
              <button
                v-for="style in catalog.styles"
                :key="style.id"
                class="video-style-card"
                :class="{ active: newDraft.config.scenes.style_id === style.id }"
                type="button"
                @click="newDraft.config.scenes.style_id = style.id"
              >
                <span class="video-style-swatches">
                  <i v-for="color in style.palette.slice(0, 5)" :key="color" :style="{ background: color }" />
                </span>
                <span class="video-style-name">{{ style.name }} <Check v-if="newDraft.config.scenes.style_id === style.id" :size="11" /></span>
                <span class="video-style-description">{{ style.description }}</span>
              </button>
            </div>
          </div>

          <div class="field" style="margin-top: 14px">
            <label>Global visual style prompt <span class="muted">(optional)</span></label>
            <textarea
              v-model="newDraft.config.scenes.visual_style_prompt"
              class="textarea"
              style="min-height: 76px"
              placeholder="Portuguese city at night, wet asphalt, sodium and teal light, 35mm anamorphic"
            />
            <span class="hint">Applied to every scene and preserved when images are regenerated.</span>
          </div>

          <div class="video-form-grid" style="margin-top: 14px">
            <div class="field">
              <label>Image provider</label>
              <select v-model="newDraft.config.scenes.image_provider" class="select">
                <option v-for="provider in catalog.providers" :key="provider.value" :value="provider.value">{{ provider.label }}</option>
              </select>
              <span class="hint">{{ catalog.providers.find((provider) => provider.value === newDraft.config.scenes.image_provider)?.description }}</span>
            </div>
            <div class="field">
              <label>Animation backend</label>
              <select v-model="newDraft.config.scenes.animation_backend" class="select">
                <option v-for="backend in catalog.backends" :key="backend.value" :value="backend.value">{{ backend.label }}</option>
              </select>
              <span class="hint">{{ catalog.backends.find((backend) => backend.value === newDraft.config.scenes.animation_backend)?.description }}</span>
            </div>
            <div class="field">
              <label>Generated image size</label>
              <select :value="imageSizePreset" class="select" @change="onImageSizePresetChange">
                <option v-for="preset in IMAGE_SIZE_PRESETS" :key="preset.id" :value="preset.id">{{ preset.label }}</option>
              </select>
              <span class="hint">Blank / match uses the final video frame size.</span>
            </div>
            <div class="field">
              <label>Image variants</label>
              <select v-model.number="newDraft.config.scenes.variants" class="select">
                <option v-for="count in 4" :key="count" :value="count">{{ count }} per scene</option>
              </select>
              <span class="hint">More variants cost more time; you can choose the best still per scene.</span>
            </div>
            <template v-if="imageSizePreset === 'custom'">
              <div class="field">
                <label>Custom image width</label>
                <input class="input" type="number" min="256" max="4096" step="2" :value="newDraft.config.scenes.image_width ?? ''" placeholder="Auto" @input="setDraftImageWidth" />
              </div>
              <div class="field">
                <label>Custom image height</label>
                <input class="input" type="number" min="256" max="4096" step="2" :value="newDraft.config.scenes.image_height ?? ''" placeholder="Auto" @input="setDraftImageHeight" />
              </div>
            </template>
            <div class="field span-2">
              <label>Scene pacing · {{ Number(newDraft.config.scenes.target_duration).toFixed(1) }}s target</label>
              <input v-model.number="newDraft.config.scenes.target_duration" type="range" min="4" max="14" step="0.5" />
              <span class="hint">Scenes snap to lyric and musical boundaries. About {{ estimatedScenes }} scenes for a three-minute song.</span>
            </div>
          </div>

          <details class="video-details">
            <summary>Advanced scene generation</summary>
            <div class="video-form-grid" style="margin-top: 10px">
              <div class="field">
                <label>Minimum scene duration</label>
                <input v-model.number="newDraft.config.scenes.min_duration" class="input" type="number" min="1" max="60" step="0.5" />
              </div>
              <div class="field">
                <label>Maximum scene duration</label>
                <input v-model.number="newDraft.config.scenes.max_duration" class="input" type="number" min="3" max="120" step="0.5" />
              </div>
              <div class="field">
                <label>Max lyric lines per scene</label>
                <input v-model.number="newDraft.config.scenes.max_lyric_lines_per_scene" class="input" type="number" min="1" max="20" />
              </div>
              <div class="field">
                <label>Seed</label>
                <input v-model.number="newDraft.config.scenes.seed" class="input" type="number" min="0" max="2147483647" />
              </div>
              <div class="field span-2">
                <div class="video-switch-row">
                  <div><strong>Generate depth maps</strong><span>Enables depth-map parallax with the OpenCV animation backend.</span></div>
                  <div class="switch" :class="{ on: newDraft.config.scenes.generate_depth_maps }" role="switch" :aria-checked="newDraft.config.scenes.generate_depth_maps" @click="newDraft.config.scenes.generate_depth_maps = !newDraft.config.scenes.generate_depth_maps" />
                </div>
              </div>
            </div>
          </details>
        </section>

        <section class="video-modal-section">
          <div class="video-modal-section-head">
            <span class="video-modal-number">03</span>
            <div>
              <h3>Format & pacing</h3>
              <p>Output dimensions, codec and the pacing rule that divides the song into scenes.</p>
            </div>
          </div>
          <div class="video-form-grid">
            <div class="field">
              <label>Resolution</label>
              <select v-model="newDraft.config.output.resolution" class="select">
                <option v-for="resolution in catalog.resolutions" :key="resolution.value" :value="resolution.value">{{ resolution.label }}</option>
              </select>
              <span class="hint">{{ draftOutputDimensions.width }} × {{ draftOutputDimensions.height }} pixels</span>
            </div>
            <div class="field">
              <label>Aspect ratio</label>
              <select v-model="newDraft.config.output.aspect_ratio" class="select">
                <option v-for="aspect in catalog.aspects" :key="aspect.value" :value="aspect.value">{{ aspect.label }}</option>
              </select>
            </div>
            <div class="field">
              <label>Frame rate</label>
              <select v-model.number="newDraft.config.output.fps" class="select">
                <option v-for="fps in catalog.fps" :key="fps" :value="fps">{{ fps }} fps</option>
              </select>
            </div>
            <div class="field">
              <label>Codec</label>
              <select v-model="newDraft.config.output.codec" class="select">
                <option v-for="codec in catalog.codecs" :key="codec.value" :value="codec.value">{{ codec.label }}</option>
              </select>
            </div>
            <div class="field">
              <label>Quality</label>
              <select v-model="newDraft.config.output.quality" class="select">
                <option v-for="quality in catalog.qualities" :key="quality.value" :value="quality.value">{{ quality.label }}</option>
              </select>
            </div>
            <div class="field">
              <label>Audio bitrate</label>
              <select v-model="newDraft.config.output.audio_bitrate" class="select">
                <option v-for="bitrate in catalog.audioBitrates" :key="bitrate" :value="bitrate">{{ bitrate }}</option>
              </select>
            </div>
            <div class="field">
              <label>Output filename</label>
              <input v-model="newDraft.config.output.output_filename" class="input" placeholder="final_video.mp4" />
            </div>
            <div class="field">
              <label>Output directory <span class="muted">(optional)</span></label>
              <input v-model="newDraft.config.output.output_dir" class="input" placeholder="Default project output folder" />
            </div>
          </div>
          <div class="video-export-switches" style="margin-top: 10px">
            <label class="video-check"><input v-model="newDraft.config.output.burn_subtitles" type="checkbox" /> Burn styled subtitles into the final video</label>
            <label class="video-check"><input v-model="newDraft.config.output.export_srt" type="checkbox" /> Export the original-timestamp SRT</label>
          </div>
          <details class="video-details">
            <summary>Advanced encoding</summary>
            <div class="video-form-grid" style="margin-top: 10px">
              <div class="field">
                <label>Encoder preset</label>
                <select v-model="newDraft.config.output.preset" class="select">
                  <option v-for="preset in catalog.presets" :key="preset" :value="preset">{{ preset }}</option>
                </select>
              </div>
              <div class="field">
                <label>CRF override</label>
                <input class="input" type="number" min="0" max="51" placeholder="Auto from quality" :value="newDraft.config.output.crf ?? ''" @input="setDraftCrf" />
              </div>
            </div>
          </details>
        </section>

        <section class="video-modal-section">
          <div class="video-modal-section-head">
            <span class="video-modal-number">04</span>
            <div>
              <h3>Subtitles & music reactivity</h3>
              <p>Style the burn-in, preserve original timing and decide how the picture reacts to the beat.</p>
            </div>
          </div>

          <div class="field">
            <label>Subtitle look</label>
            <div class="pill-row">
              <button
                v-for="preset in SUBTITLE_PRESETS"
                :key="preset.id"
                class="chip clickable"
                :class="{ active: subtitlePreset === preset.id }"
                type="button"
                :title="preset.description"
                @click="applySubtitlePreset(preset.id)"
              >
                <Check v-if="subtitlePreset === preset.id" :size="10" />
                {{ preset.name }}
              </button>
            </div>
          </div>

          <div class="video-form-grid" style="margin-top: 14px">
            <div class="field">
              <label>Font</label>
              <select v-model="newDraft.config.subtitles.font_family" class="select">
                <option v-for="font in catalog.subtitleFonts" :key="font" :value="font">{{ font }}</option>
              </select>
            </div>
            <div class="field">
              <label>Position</label>
              <select v-model="newDraft.config.subtitles.position" class="select">
                <option v-for="position in catalog.subtitlePositions" :key="position" :value="position">{{ titleCase(position) }}</option>
              </select>
            </div>
            <div class="field">
              <label>Font size</label>
              <input v-model.number="newDraft.config.subtitles.font_size" class="input" type="number" min="12" max="180" />
            </div>
            <div class="field">
              <label>Alignment</label>
              <select v-model="newDraft.config.subtitles.alignment" class="select">
                <option v-for="alignment in catalog.subtitleAlignments" :key="alignment" :value="alignment">{{ titleCase(alignment) }}</option>
              </select>
            </div>
            <div class="field">
              <label>Text color</label>
              <div class="video-color-field"><input v-model="newDraft.config.subtitles.primary_color" type="color" /><span class="mono">{{ newDraft.config.subtitles.primary_color }}</span></div>
            </div>
            <div class="field">
              <label>Karaoke highlight</label>
              <div class="video-color-field"><input v-model="newDraft.config.subtitles.highlight_color" type="color" /><span class="mono">{{ newDraft.config.subtitles.highlight_color }}</span></div>
            </div>
          </div>

          <div class="video-export-switches" style="margin-top: 10px">
            <label class="video-check"><input v-model="newDraft.config.subtitles.karaoke" type="checkbox" /> Karaoke-style line emphasis</label>
            <label class="video-check"><input v-model="newDraft.config.subtitles.background" type="checkbox" /> Subtle background box</label>
          </div>

          <details class="video-details">
            <summary>Outline, shadow, margin and box</summary>
            <div class="video-form-grid" style="margin-top: 10px">
              <div class="field">
                <label>Outline color</label>
                <div class="video-color-field"><input v-model="newDraft.config.subtitles.outline_color" type="color" /><span class="mono">{{ newDraft.config.subtitles.outline_color }}</span></div>
              </div>
              <div class="field">
                <label>Outline width</label>
                <input v-model.number="newDraft.config.subtitles.outline_width" class="input" type="number" min="0" max="12" step="0.5" />
              </div>
              <div class="field">
                <label>Shadow</label>
                <input v-model.number="newDraft.config.subtitles.shadow" class="input" type="number" min="0" max="12" step="0.5" />
              </div>
              <div class="field">
                <label>Vertical margin</label>
                <input v-model.number="newDraft.config.subtitles.margin_v" class="input" type="number" min="0" max="1000" />
              </div>
              <div class="field">
                <label>Max line width</label>
                <input v-model.number="newDraft.config.subtitles.max_line_width" class="input" type="number" min="10" max="140" />
              </div>
              <div class="field">
                <label>Box color</label>
                <div class="video-color-field"><input v-model="newDraft.config.subtitles.background_color" type="color" /><span class="mono">{{ newDraft.config.subtitles.background_color }}</span></div>
              </div>
              <div class="field span-2">
                <label>Box opacity · {{ Math.round(newDraft.config.subtitles.background_opacity * 100) }}%</label>
                <input v-model.number="newDraft.config.subtitles.background_opacity" type="range" min="0" max="1" step="0.05" :disabled="!newDraft.config.subtitles.background" />
              </div>
            </div>
          </details>

          <div class="video-reactive-grid" style="margin-top: 15px">
            <div class="video-switch-row"><div><strong>Audio-reactive visuals</strong><span>Beat-synced cuts, light pulses and motion accents.</span></div><div class="switch" :class="{ on: newDraft.config.audio_reactive.enabled }" role="switch" :aria-checked="newDraft.config.audio_reactive.enabled" @click="newDraft.config.audio_reactive.enabled = !newDraft.config.audio_reactive.enabled" /></div>
            <div class="video-switch-row"><div><strong>Beat cuts</strong><span>Cut scenes on strong beats and downbeats.</span></div><div class="switch" :class="{ on: newDraft.config.audio_reactive.beat_cuts }" role="switch" :aria-checked="newDraft.config.audio_reactive.beat_cuts" @click="newDraft.config.audio_reactive.beat_cuts = !newDraft.config.audio_reactive.beat_cuts" /></div>
            <div class="video-switch-row"><div><strong>Beat pulse</strong><span>Brightness and zoom pulses on the beat.</span></div><div class="switch" :class="{ on: newDraft.config.audio_reactive.beat_pulse }" role="switch" :aria-checked="newDraft.config.audio_reactive.beat_pulse" @click="newDraft.config.audio_reactive.beat_pulse = !newDraft.config.audio_reactive.beat_pulse" /></div>
            <div class="video-switch-row"><div><strong>Bass pulse</strong><span>Low-end light blooms and camera energy.</span></div><div class="switch" :class="{ on: newDraft.config.audio_reactive.bass_pulse }" role="switch" :aria-checked="newDraft.config.audio_reactive.bass_pulse" @click="newDraft.config.audio_reactive.bass_pulse = !newDraft.config.audio_reactive.bass_pulse" /></div>
            <div class="video-switch-row"><div><strong>Particles</strong><span>Dust and fireflies on high-energy scenes.</span></div><div class="switch" :class="{ on: newDraft.config.audio_reactive.particles }" role="switch" :aria-checked="newDraft.config.audio_reactive.particles" @click="newDraft.config.audio_reactive.particles = !newDraft.config.audio_reactive.particles" /></div>
            <div class="video-switch-row"><div><strong>Intensity</strong><span>{{ Math.round(newDraft.config.audio_reactive.intensity * 100) }}% reaction strength</span></div><input v-model.number="newDraft.config.audio_reactive.intensity" type="range" min="0" max="1" step="0.05" style="max-width: 150px" :disabled="!newDraft.config.audio_reactive.enabled" /></div>
          </div>
        </section>

        <section class="video-modal-section">
          <div class="video-modal-section-head">
            <span class="video-modal-number">05</span>
            <div>
              <h3>AI providers</h3>
              <p>Optional local models for richer story planning, ComfyUI artwork and AI image-to-video.</p>
            </div>
          </div>
          <div class="video-form-grid">
            <div class="field">
              <label>Story planner mode</label>
              <select v-model="newDraft.config.ai.llm_mode" class="select">
                <option v-for="mode in catalog.plannerModes" :key="mode.value" :value="mode.value">{{ mode.label }}</option>
              </select>
            </div>
            <div class="field">
              <label>Planner marker</label>
              <input v-model="newDraft.config.ai.marker" class="input" placeholder="optional" />
            </div>
            <div class="field span-2">
              <div class="video-switch-row">
                <div><strong>Allow deterministic fallback</strong><span>If Ollama or ComfyUI is unavailable, continue with the local planner or procedural art instead of failing.</span></div>
                <div class="switch" :class="{ on: newDraft.config.ai.allow_fallback }" role="switch" :aria-checked="newDraft.config.ai.allow_fallback" @click="newDraft.config.ai.allow_fallback = !newDraft.config.ai.allow_fallback" />
              </div>
            </div>
          </div>

          <div class="video-provider-block">
            <div class="video-provider-title"><ImageIcon :size="14" /><div><strong>ComfyUI · image generation</strong><span>Workflow placeholders: PROMPT, NEGATIVE_PROMPT, WIDTH, HEIGHT, SEED, STEPS, CFG, CHECKPOINT.</span></div></div>
            <div class="video-form-grid">
              <div class="field span-2">
                <label>ComfyUI URL</label>
                <input v-model="newDraft.comfyui_url" class="input mono" placeholder="http://127.0.0.1:8188" />
              </div>
              <div class="field span-2">
                <label>Image workflow path</label>
                <input v-model="newDraft.image_workflow_path" class="input mono" placeholder="workflows/video-image-api.json" />
              </div>
              <div class="field">
                <label>Image steps</label>
                <input v-model.number="newDraft.image_steps" class="input" type="number" min="1" max="200" />
              </div>
              <div class="field">
                <label>Image CFG</label>
                <input v-model.number="newDraft.image_cfg" class="input" type="number" min="0" max="30" step="0.1" />
              </div>
              <div class="field span-2">
                <label>Image checkpoint</label>
                <input v-model="newDraft.image_checkpoint" class="input mono" placeholder="dreamshaper_8.safetensors" />
              </div>
              <div class="field span-2">
                <label>Video workflow path <span class="muted">(AI image-to-video)</span></label>
                <input v-model="newDraft.video_workflow_path" class="input mono" placeholder="workflows/video-i2v-api.json" />
              </div>
              <div class="field">
                <label>Video steps</label>
                <input v-model.number="newDraft.video_steps" class="input" type="number" min="1" max="200" />
              </div>
              <div class="field">
                <label>Video CFG</label>
                <input v-model.number="newDraft.video_cfg" class="input" type="number" min="0" max="30" step="0.1" />
              </div>
              <div class="field span-2">
                <label>Video checkpoint</label>
                <input v-model="newDraft.video_checkpoint" class="input mono" placeholder="svd_xt.safetensors" />
              </div>
            </div>
          </div>

          <div class="video-provider-block">
            <div class="video-provider-title"><Sparkles :size="14" /><div><strong>Ollama · story planning</strong><span>Optional local LLM for richer scene descriptions. Deterministic planning remains fully offline.</span></div></div>
            <div class="video-form-grid">
              <div class="field">
                <label>Ollama URL</label>
                <input v-model="newDraft.ollama_url" class="input mono" placeholder="http://127.0.0.1:11434" />
              </div>
              <div class="field">
                <label>Ollama model</label>
                <input v-model="newDraft.ollama_model" class="input mono" placeholder="llama3.1:8b" />
              </div>
            </div>
          </div>
        </section>
      </div>

      <template #footer>
        <span class="video-modal-footer-note">
          <Check :size="12" style="vertical-align: -2px; color: var(--success)" />
          Original SRT timing is preserved. Nothing leaves your machine.
        </span>
        <button class="btn" :disabled="creating" @click="newProjectOpen = false">Cancel</button>
        <button class="btn" :disabled="!canCreate || creating" @click="createProject(false)">Create project</button>
        <button class="btn btn-primary" :disabled="!canCreate || creating" @click="createProject(true)">
          <RefreshCw v-if="creating" :size="14" class="spin" />
          <Sparkles v-else :size="14" />
          {{ creating ? "Creating…" : "Create & run pipeline" }}
        </button>
      </template>
    </BaseModal>

    <FilePicker v-if="!DEMO" v-model="audioPickerOpen" title="Choose the audio track" kind="audio" accept=".mp3,.wav,.flac,.m4a,.aac,.ogg,.opus,.aiff,.aif" @selected="onAudioSelected" />
    <FilePicker v-if="!DEMO" v-model="srtPickerOpen" title="Choose the timed lyrics" kind="subtitle" accept=".srt" @selected="onSrtSelected" />
  </div>
</template>

<style scoped>
.video-page {
  --video-surface: rgba(8, 10, 15, 0.35);
  --video-border: rgba(48, 58, 80, 0.55);
}

.spin {
  animation: video-spin 1s linear infinite;
}
@keyframes video-spin {
  to { transform: rotate(360deg); }
}

/* ------------------------------------------------------------------ */
/* Toolbar                                                             */
/* ------------------------------------------------------------------ */
.video-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}
.video-toolbar-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.video-toolbar-meta .chip {
  height: 27px;
}

/* ------------------------------------------------------------------ */
/* Projects                                                            */
/* ------------------------------------------------------------------ */
.video-projects-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 330px;
  gap: 18px;
  align-items: start;
}
.video-projects-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  gap: 16px;
}
.video-project-card {
  overflow: hidden;
  cursor: pointer;
  transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}
.video-project-card:hover {
  transform: translateY(-3px);
  border-color: var(--line-strong);
  box-shadow: 0 18px 55px rgba(0, 0, 0, 0.32);
}
.video-project-poster {
  position: relative;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  background: #070a11;
  border-bottom: 1px solid var(--line);
}
.video-project-poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 700ms ease, filter 300ms ease;
  filter: saturate(0.92) contrast(1.04);
}
.video-project-card:hover .video-project-poster img {
  transform: scale(1.035);
  filter: saturate(1.05) contrast(1.06);
}
.video-poster-fallback {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: rgba(234, 238, 247, 0.28);
  background:
    radial-gradient(400px 260px at 30% 10%, rgba(139, 92, 246, 0.2), transparent 65%),
    radial-gradient(380px 260px at 80% 90%, rgba(34, 211, 238, 0.12), transparent 60%),
    #0b0e16;
}
.video-project-poster .video-poster-fallback {
  position: absolute;
}
.video-project-poster .video-poster-fallback svg {
  width: 38px;
  height: 38px;
}
.video-poster-shade {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(180deg, rgba(4, 6, 10, 0.6) 0%, transparent 26%, transparent 42%, rgba(4, 6, 10, 0.88) 100%),
    linear-gradient(90deg, rgba(4, 6, 10, 0.28), transparent 55%);
  pointer-events: none;
}
.video-poster-top {
  position: absolute;
  top: 12px;
  left: 12px;
  right: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  z-index: 2;
}
.video-poster-top .badge {
  background: rgba(9, 12, 18, 0.62);
  backdrop-filter: blur(9px);
}
.video-poster-play {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%) scale(0.85);
  width: 49px;
  height: 49px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.3);
  background: rgba(8, 10, 15, 0.48);
  backdrop-filter: blur(8px);
  opacity: 0;
  transition: 200ms ease;
  z-index: 2;
  padding-left: 2px;
}
.video-project-card:hover .video-poster-play {
  opacity: 1;
  transform: translate(-50%, -50%) scale(1);
}
.video-poster-caption {
  position: absolute;
  left: 17px;
  right: 17px;
  bottom: 13px;
  z-index: 2;
  color: #fff;
  text-shadow: 0 2px 16px rgba(0, 0, 0, 0.65);
}
.video-poster-kicker {
  display: block;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: rgba(255, 255, 255, 0.66);
  margin-bottom: 4px;
}
.video-poster-caption h2 {
  font-size: 22px;
  line-height: 1.08;
  letter-spacing: -0.025em;
}
.video-poster-caption p {
  margin-top: 4px;
  font-size: 10.5px;
  color: rgba(255, 255, 255, 0.68);
}
.video-project-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 13px 15px 14px;
}
.video-project-open {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 10.5px;
  font-weight: 600;
  color: var(--accent-2);
  white-space: nowrap;
}
.video-new-project-card {
  min-height: 285px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 9px;
  padding: 26px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
  background:
    radial-gradient(320px 200px at 30% 20%, rgba(139, 92, 246, 0.09), transparent 68%),
    rgba(255, 255, 255, 0.012);
  color: var(--text);
  text-align: left;
  transition: 180ms ease;
}
.video-new-project-card:hover {
  border-color: rgba(139, 92, 246, 0.52);
  background:
    radial-gradient(340px 220px at 30% 20%, rgba(139, 92, 246, 0.16), transparent 68%),
    rgba(139, 92, 246, 0.03);
  transform: translateY(-2px);
}
.video-new-project-icon {
  width: 44px;
  height: 44px;
  border-radius: 13px;
  display: grid;
  place-items: center;
  color: #e9e1ff;
  background: linear-gradient(140deg, rgba(139, 92, 246, 0.36), rgba(34, 211, 238, 0.14));
  border: 1px solid rgba(139, 92, 246, 0.38);
  margin-bottom: 3px;
}
.video-new-project-card strong {
  font-family: var(--display);
  font-size: 19px;
  letter-spacing: -0.02em;
}
.video-new-project-card p {
  max-width: 340px;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--muted);
}
.video-new-project-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 4px;
}
.skeleton-card {
  cursor: default;
}
.video-feature-band {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}
.video-feature {
  padding: 15px;
  border: 1px solid var(--line);
  border-radius: 13px;
  background:
    linear-gradient(160deg, rgba(21, 26, 37, 0.72), rgba(10, 13, 19, 0.54));
  position: relative;
  overflow: hidden;
}
.video-feature::after {
  content: "";
  position: absolute;
  right: -42px;
  top: -55px;
  width: 120px;
  height: 120px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.1), transparent 70%);
  pointer-events: none;
}
.video-feature-icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  border: 1px solid rgba(139, 92, 246, 0.28);
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.18), rgba(34, 211, 238, 0.05));
  color: #d8ccff;
  margin-bottom: 11px;
}
.video-feature h3 {
  font-size: 13.5px;
  line-height: 1.25;
  margin-bottom: 6px;
}
.video-feature p {
  font-size: 10.5px;
  line-height: 1.55;
  color: var(--muted);
  min-height: 49px;
  margin-bottom: 10px;
}

/* Pipeline + capability side panels */
.video-pipeline {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding-top: 11px;
  padding-bottom: 11px;
}
.video-pipeline-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 0;
  position: relative;
}
.video-pipeline-row:not(:last-child)::after {
  content: "";
  position: absolute;
  left: 11px;
  top: 32px;
  bottom: -4px;
  width: 1px;
  background: var(--line);
}
.video-pipeline-marker {
  width: 23px;
  height: 23px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  border: 1px solid var(--line-strong);
  background: var(--panel-2);
  color: var(--muted-2);
  font-family: var(--mono);
  font-size: 9px;
  flex: none;
  position: relative;
  z-index: 1;
}
.video-pipeline-row.done .video-pipeline-marker {
  background: rgba(52, 211, 153, 0.12);
  border-color: rgba(52, 211, 153, 0.36);
  color: #6ee7b7;
}
.video-pipeline-row.active .video-pipeline-marker {
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.4), rgba(34, 211, 238, 0.16));
  border-color: rgba(139, 92, 246, 0.6);
  color: #fff;
  box-shadow: 0 0 18px rgba(139, 92, 246, 0.25);
}
.video-pipeline-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-top: 1px;
  min-width: 0;
}
.video-pipeline-copy strong {
  font-size: 11.5px;
  font-weight: 600;
}
.video-pipeline-copy span {
  font-size: 10px;
  color: var(--muted-2);
  line-height: 1.4;
}
.video-capability {
  display: flex;
  align-items: center;
  gap: 9px;
}
.video-capability .file-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
}
.video-capability > div:not(.video-palette) {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.video-capability span {
  font-size: 9.5px;
  color: var(--muted-2);
  line-height: 1.3;
}
.video-capability strong {
  font-size: 11px;
  font-weight: 600;
  line-height: 1.4;
}
.video-palette {
  display: flex;
  gap: 3px;
  margin-left: auto;
  flex: none;
}
.video-palette i {
  width: 12px;
  height: 18px;
  border-radius: 3px;
  border: 1px solid rgba(255, 255, 255, 0.14);
}

/* ------------------------------------------------------------------ */
/* Editor header                                                       */
/* ------------------------------------------------------------------ */
.video-editor-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  padding: 18px;
  flex-wrap: wrap;
  background:
    radial-gradient(500px 200px at 5% 0%, rgba(139, 92, 246, 0.12), transparent 65%),
    linear-gradient(180deg, rgba(21, 26, 37, 0.94), rgba(15, 19, 27, 0.94));
}
.video-editor-identity {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  min-width: 0;
  flex: 1;
}
.video-editor-cover {
  width: 112px;
  flex: none;
  aspect-ratio: 16 / 10;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--line-strong);
  position: relative;
  background: #090c13;
  cursor: pointer;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.28);
}
.video-editor-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.video-editor-cover-fallback {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--muted);
}
.video-editor-cover-count {
  position: absolute;
  right: 6px;
  bottom: 6px;
  min-width: 20px;
  padding: 2px 5px;
  border-radius: 6px;
  background: rgba(5, 7, 11, 0.75);
  border: 1px solid rgba(255, 255, 255, 0.16);
  color: #fff;
  font-family: var(--mono);
  font-size: 9px;
  text-align: center;
  backdrop-filter: blur(6px);
}
.video-editor-copy {
  min-width: 0;
}
.video-editor-chips {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  margin-bottom: 7px;
}
.video-editor-copy h2 {
  font-size: 26px;
  line-height: 1.08;
  letter-spacing: -0.03em;
}
.video-editor-copy p {
  margin-top: 5px;
  color: var(--muted);
  font-size: 11.5px;
}
.video-dot {
  padding: 0 3px;
  color: var(--muted-2);
}
.video-editor-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-content: flex-start;
  max-width: 620px;
}
.video-editor-actions .btn {
  min-height: 32px;
  padding: 6px 10px;
}

/* Live job */
.video-live-job {
  overflow: hidden;
}
.video-live-job-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 0.8fr);
  gap: 14px;
  align-items: stretch;
  padding-top: 13px;
  padding-bottom: 13px;
}
.video-job-context {
  display: flex;
  flex-direction: column;
  gap: 9px;
  min-width: 0;
  padding: 2px 2px;
}
.video-job-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.video-job-facts > div {
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.34);
  min-width: 0;
}
.video-job-facts span {
  display: block;
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted-2);
  margin-bottom: 3px;
}
.video-job-facts strong {
  display: block;
  font-size: 11px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.video-job-warnings {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

/* ------------------------------------------------------------------ */
/* Editor grid                                                         */
/* ------------------------------------------------------------------ */
.video-editor-grid {
  display: grid;
  grid-template-columns: 264px minmax(0, 1fr) 410px;
  gap: 14px;
  align-items: start;
}

/* Scene rail */
.video-scene-rail {
  overflow: hidden;
}
.video-scene-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 10px;
  max-height: 760px;
  overflow-y: auto;
}
.video-scene-item {
  display: grid;
  grid-template-columns: 82px minmax(0, 1fr);
  gap: 9px;
  padding: 7px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: rgba(8, 10, 15, 0.24);
  color: var(--text);
  text-align: left;
  width: 100%;
  transition: 150ms ease;
}
.video-scene-item:hover {
  border-color: var(--line-strong);
  background: rgba(255, 255, 255, 0.025);
}
.video-scene-item.active {
  border-color: rgba(139, 92, 246, 0.44);
  background:
    linear-gradient(90deg, rgba(139, 92, 246, 0.14), rgba(34, 211, 238, 0.04)),
    rgba(17, 21, 30, 0.78);
  box-shadow: inset 3px 0 0 var(--accent), 0 5px 18px rgba(0, 0, 0, 0.18);
}
.video-scene-thumb {
  position: relative;
  display: block;
  width: 82px;
  height: 54px;
  border-radius: 7px;
  overflow: hidden;
  background: #070a11;
  border: 1px solid var(--line);
}
.video-scene-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.video-scene-thumb-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--muted-2);
}
.video-scene-number {
  position: absolute;
  top: 4px;
  left: 4px;
  min-width: 17px;
  height: 17px;
  display: grid;
  place-items: center;
  padding: 0 4px;
  border-radius: 5px;
  background: rgba(5, 7, 12, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.14);
  font-family: var(--mono);
  font-size: 8px;
  font-weight: 700;
  color: #fff;
  backdrop-filter: blur(5px);
}
.video-scene-film {
  position: absolute;
  right: 4px;
  bottom: 4px;
  width: 16px;
  height: 14px;
  display: grid;
  place-items: center;
  border-radius: 4px;
  background: rgba(5, 7, 12, 0.72);
  color: #a7f3d0;
  border: 1px solid rgba(52, 211, 153, 0.3);
}
.video-scene-info {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  padding-top: 1px;
}
.video-scene-info strong {
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.video-scene-info .badge {
  font-size: 7.5px;
  padding: 1px 5px;
  letter-spacing: 0.03em;
  height: 16px;
}
.video-scene-time {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.video-scene-meta {
  font-size: 9px;
  color: var(--muted-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.video-rail-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 26px 16px;
  text-align: center;
  color: var(--muted);
}
.video-rail-empty strong {
  font-size: 12px;
  color: var(--text);
}
.video-rail-empty p {
  font-size: 10.5px;
  line-height: 1.45;
  max-width: 190px;
}
.video-rail-empty svg {
  opacity: 0.4;
}
.video-rail-footer {
  justify-content: space-between;
}

/* ------------------------------------------------------------------ */
/* Preview                                                             */
/* ------------------------------------------------------------------ */
.video-preview-panel {
  overflow: hidden;
}
.video-preview-stage {
  position: relative;
  overflow: hidden;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: #05070b;
  margin: 12px 12px 0;
}
.video-preview-poster {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: transform 9s linear;
}
.video-preview-stage.is-playing .video-preview-poster {
  transform: scale(1.035);
}
.video-preview-stage .video-poster-fallback {
  position: absolute;
}
.video-final-player {
  display: block;
  width: 100%;
  height: 100%;
  min-height: 220px;
  object-fit: contain;
  background: #000;
}
.video-preview-vignette {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(180deg, rgba(3, 5, 9, 0.62) 0%, transparent 27%, transparent 54%, rgba(3, 5, 9, 0.86) 100%),
    radial-gradient(ellipse at center, transparent 48%, rgba(3, 5, 9, 0.32) 100%);
  pointer-events: none;
}
.video-preview-top {
  position: absolute;
  top: 13px;
  left: 13px;
  right: 13px;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 9px;
  z-index: 3;
}
.video-preview-top .badge {
  background: rgba(6, 8, 13, 0.56);
  border-color: rgba(255, 255, 255, 0.14);
  color: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(8px);
}
.video-preview-resolution {
  font-family: var(--mono);
  font-size: 9px;
  color: rgba(255, 255, 255, 0.62);
  padding: 5px 7px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(6, 8, 13, 0.4);
  backdrop-filter: blur(7px);
  white-space: nowrap;
}
.video-preview-play {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 62px;
  height: 62px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.28);
  background: rgba(7, 9, 14, 0.46);
  backdrop-filter: blur(9px);
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.35);
  transition: 180ms ease;
  z-index: 3;
  padding-left: 2px;
}
.video-preview-play:hover {
  background: linear-gradient(135deg, #8b5cf6, #22d3ee 160%);
  border-color: transparent;
  transform: translate(-50%, -50%) scale(1.06);
}
.video-preview-now {
  position: absolute;
  left: 13px;
  bottom: 13px;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 7px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(6, 8, 13, 0.53);
  backdrop-filter: blur(8px);
  color: rgba(255, 255, 255, 0.72);
  font-size: 9px;
}
.video-preview-now-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent-2);
  box-shadow: 0 0 8px rgba(34, 211, 238, 0.75);
}
.video-preview-now .mono {
  color: rgba(255, 255, 255, 0.5);
  margin-left: 3px;
}
.video-preview-subtitle-zone {
  position: absolute;
  left: 20px;
  right: 20px;
  z-index: 3;
  display: flex;
  justify-content: center;
  pointer-events: none;
}
.video-preview-subtitle-zone.subtitle-bottom {
  bottom: 46px;
}
.video-preview-subtitle-zone.subtitle-center {
  top: 50%;
  transform: translateY(-50%);
}
.video-preview-subtitle-zone.subtitle-top {
  top: 47px;
}
.video-preview-subtitle {
  position: relative;
  max-width: 84%;
  text-align: center;
  font-weight: 700;
  line-height: 1.35;
  letter-spacing: 0.01em;
}
.video-preview-karaoke {
  display: block;
  height: 2px;
  margin: 5px auto 0;
  border-radius: 2px;
  background: #ffd166;
  box-shadow: 0 0 9px rgba(255, 209, 102, 0.6);
}
.video-preview-progress {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 2px;
  background: rgba(255, 255, 255, 0.1);
  z-index: 4;
}
.video-preview-progress > span {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  box-shadow: 0 0 8px rgba(34, 211, 238, 0.45);
}
.video-preview-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-top: 1px solid var(--line);
  flex-wrap: wrap;
}
.video-preview-control-btn {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--text);
  display: grid;
  place-items: center;
  flex: none;
}
.video-preview-control-btn:hover {
  border-color: var(--line-strong);
  background: var(--panel-3);
}
.video-preview-scrub {
  flex: 1;
  min-width: 80px;
}
.video-preview-control-detail {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 9.5px;
  color: var(--muted-2);
  white-space: nowrap;
}

/* ------------------------------------------------------------------ */
/* Timeline                                                            */
/* ------------------------------------------------------------------ */
.video-timeline-panel {
  overflow: hidden;
}
.video-timeline-composite {
  position: relative;
  padding-top: 18px;
  cursor: crosshair;
  user-select: none;
}
.video-timeline-ruler {
  position: relative;
  height: 16px;
}
.video-timeline-ruler span {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  font-family: var(--mono);
  font-size: 8px;
  color: var(--muted-2);
  white-space: nowrap;
}
.video-timeline-ruler span:first-child {
  transform: none;
}
.video-timeline-ruler span:last-child {
  transform: translateX(-100%);
}
.video-timeline-scenes {
  position: relative;
  height: 50px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: #090d14;
  overflow: hidden;
}
.video-timeline-scene {
  position: absolute;
  top: 0;
  bottom: 0;
  border: none;
  border-right: 1px solid rgba(255, 255, 255, 0.16);
  padding: 6px 5px;
  color: #fff;
  text-align: left;
  overflow: hidden;
  cursor: pointer;
  opacity: 0.7;
  transition: opacity 140ms ease, filter 140ms ease;
  min-width: 4px;
}
.video-timeline-scene:hover {
  opacity: 1;
  filter: brightness(1.12);
}
.video-timeline-scene.active {
  opacity: 1;
  z-index: 2;
  box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.78);
}
.video-timeline-scene-index {
  display: block;
  font-family: var(--mono);
  font-size: 9px;
  font-weight: 700;
  line-height: 1;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.4);
}
.video-timeline-scene-kind {
  display: block;
  margin-top: 2px;
  font-size: 7.5px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  opacity: 0.85;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.video-timeline-scene-film {
  position: absolute;
  right: 4px;
  bottom: 4px;
  opacity: 0.82;
}
.video-timeline-empty {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font-size: 10px;
  color: var(--muted-2);
}
.video-timeline-cues {
  position: relative;
  height: 16px;
  margin-top: 5px;
  border-radius: 5px;
  border: 1px solid var(--line);
  background: rgba(8, 10, 15, 0.55);
  overflow: hidden;
}
.video-timeline-cue {
  position: absolute;
  top: 3px;
  bottom: 3px;
  border-radius: 2px;
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.67), rgba(139, 92, 246, 0.48));
  min-width: 2px;
}
.video-timeline-playhead {
  position: absolute;
  top: 17px;
  bottom: 0;
  width: 1.5px;
  background: #fff;
  box-shadow: 0 0 8px rgba(255, 255, 255, 0.45);
  z-index: 5;
  pointer-events: none;
}
.video-timeline-playhead span {
  position: absolute;
  top: -1px;
  left: -4px;
  width: 0;
  height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 5px solid #fff;
}
.video-timeline-legend {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 9px;
  margin-top: 9px;
  font-size: 9px;
  color: var(--muted-2);
}
.video-timeline-legend span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.video-timeline-legend i {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  display: inline-block;
}
.video-legend-cue {
  background: linear-gradient(90deg, #22d3ee, #8b5cf6);
}
.video-timeline-audio {
  margin-top: 12px;
}
.video-timeline-audio :deep(.audio-player) {
  background: rgba(8, 10, 15, 0.32);
}

/* ------------------------------------------------------------------ */
/* Inspector                                                           */
/* ------------------------------------------------------------------ */
.video-inspector {
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.video-inspector-scroll {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 12px;
  max-height: 780px;
  overflow-y: auto;
}
.video-inspector-section {
  padding: 11px;
  border: 1px solid var(--video-border);
  border-radius: 11px;
  background: var(--video-surface);
}
.video-inspector-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 9px;
}
.video-inspector-heading h4 {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.09em;
  text-transform: uppercase;
  color: var(--muted);
}
.video-inspector-heading .badge {
  font-size: 8px;
  padding: 2px 5px;
}
.video-inspector-image {
  position: relative;
  aspect-ratio: 16 / 9;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--line);
  background: #070a11;
}
.video-inspector-image img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.video-inspector-image-empty {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  color: var(--muted-2);
  font-size: 9.5px;
}
.video-inspector-image-foot {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 5px 7px;
  display: flex;
  justify-content: space-between;
  gap: 6px;
  background: linear-gradient(180deg, transparent, rgba(4, 6, 10, 0.85));
  color: rgba(255, 255, 255, 0.7);
  font-size: 8.5px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.video-image-path {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 5px;
  font-size: 8.5px;
  color: var(--muted-2);
  min-width: 0;
}
.video-image-path .truncate {
  min-width: 0;
}
.video-variant-strip {
  display: flex;
  gap: 5px;
  margin-top: 7px;
  overflow-x: auto;
  padding-bottom: 2px;
}
.video-variant-thumb {
  width: 54px;
  height: 36px;
  flex: none;
  border-radius: 5px;
  overflow: hidden;
  border: 1px solid var(--line);
  padding: 0;
  background: #06080d;
  opacity: 0.7;
  transition: 150ms ease;
}
.video-variant-thumb:hover {
  opacity: 1;
}
.video-variant-thumb.active {
  border-color: var(--accent);
  opacity: 1;
  box-shadow: 0 0 0 1px rgba(139, 92, 246, 0.35);
}
.video-variant-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.video-inspector-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 8px;
}
.video-inspector-actions .btn {
  min-height: 28px;
  padding: 4px 8px;
  font-size: 10.5px;
}
.video-depth-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 7px;
}
.video-depth-row .btn {
  margin-left: auto;
}
.video-inline-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 9px;
}
.video-inspector-section .field .hint {
  font-size: 9.5px;
}
.video-inspector-section .textarea {
  font-size: 11px;
}
.video-details {
  margin-top: 9px;
  border-top: 1px solid rgba(35, 42, 58, 0.6);
  padding-top: 7px;
}
.video-details summary {
  cursor: pointer;
  font-size: 10px;
  font-weight: 600;
  color: var(--muted);
  list-style-position: inside;
}
.video-details summary:hover {
  color: var(--text);
}
.video-inspector-footer {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 9px 12px;
  border-top: 1px solid var(--line);
  background: rgba(9, 12, 18, 0.72);
}
.video-inspector-footer .btn-primary {
  flex: 1;
}

/* ------------------------------------------------------------------ */
/* Export panel                                                        */
/* ------------------------------------------------------------------ */
.video-export-panel {
  overflow: hidden;
}
.video-export-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 0.82fr);
  gap: 18px;
  align-items: start;
}
.video-export-section {
  padding: 13px;
  border: 1px solid var(--video-border);
  border-radius: 11px;
  background: var(--video-surface);
}
.video-export-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 9px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.video-export-section-head h4 {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #c8d0e1;
}
.video-export-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
}
.video-export-fields .field .label,
.video-export-fields .field label {
  font-size: 10px;
}
.video-export-switches {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  margin-top: 9px;
}
.video-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10.5px;
  color: var(--muted);
  cursor: pointer;
}
.video-color-field {
  display: flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 3px 8px 3px 4px;
  background: rgba(8, 10, 15, 0.55);
  min-height: 36px;
}
.video-color-field input[type="color"] {
  width: 27px;
  height: 27px;
  border: 0;
  padding: 0;
  background: none;
  cursor: pointer;
}
.video-color-field .mono {
  font-size: 9.5px;
  color: var(--muted);
}
.video-reactive-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}
.video-switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 9px;
  border: 1px solid rgba(35, 42, 58, 0.68);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.26);
  min-height: 50px;
}
.video-switch-row > div:first-child {
  min-width: 0;
}
.video-switch-row strong {
  display: block;
  font-size: 10.5px;
  font-weight: 600;
}
.video-switch-row span {
  display: block;
  margin-top: 2px;
  font-size: 9.5px;
  line-height: 1.35;
  color: var(--muted-2);
}
.video-switch-row .switch {
  width: 34px;
  height: 20px;
  flex: none;
}
.video-switch-row .switch::after {
  width: 14px;
  height: 14px;
}
.video-switch-row .switch.on::after {
  transform: translateX(14px);
}

/* Deliverables */
.video-deliverables {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.video-deliverable {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 46px;
  padding: 6px 8px;
  border: 1px solid rgba(35, 42, 58, 0.7);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.3);
}
.video-deliverable.ready {
  border-color: rgba(52, 211, 153, 0.23);
  background: rgba(52, 211, 153, 0.025);
}
.video-deliverable-icon {
  width: 30px;
  height: 30px;
  flex: none;
  border-radius: 8px;
  display: grid;
  place-items: center;
  background: var(--panel-3);
  color: var(--accent-2);
}
.video-deliverable .grow strong {
  display: block;
  font-size: 10.5px;
  font-weight: 600;
}
.video-deliverable .grow span {
  display: block;
  margin-top: 1px;
  font-size: 9.5px;
  color: var(--muted-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.video-assets-section .video-asset-list {
  max-height: 270px;
  overflow-y: auto;
}
.video-asset-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 2px;
  border-bottom: 1px solid rgba(35, 42, 58, 0.5);
  min-width: 0;
}
.video-asset-row:last-child {
  border-bottom: none;
}
.video-asset-icon {
  width: 27px;
  height: 27px;
  flex: none;
  border-radius: 7px;
  display: grid;
  place-items: center;
  background: rgba(26, 32, 48, 0.9);
  color: var(--muted);
}
.video-asset-row .strong {
  display: block;
  font-size: 10px;
  font-weight: 600;
}
.video-asset-row .small {
  display: block;
  font-size: 8.5px;
  margin-top: 1px;
}
.video-asset-row .icon-btn {
  width: 25px;
  height: 25px;
  flex: none;
}

/* ------------------------------------------------------------------ */
/* Activity and logs                                                   */
/* ------------------------------------------------------------------ */
.video-activity-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 0.85fr);
  gap: 14px;
  align-items: start;
}
.video-log {
  border: 1px solid var(--line);
  border-radius: 9px;
  background: #07090d;
  padding: 8px 10px;
  max-height: 240px;
  overflow-y: auto;
}
.video-log-row {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  font-family: var(--mono);
  font-size: 9px;
  line-height: 1.55;
  color: #9aa5b9;
  padding: 3px 0;
}
.video-log-time {
  width: 55px;
  flex: none;
  color: #5b6578;
  font-size: 8.5px;
}
.video-log-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  flex: none;
  margin-top: 5px;
  background: var(--accent-2);
}
.video-log-row.warning {
  color: #fde68a;
}
.video-log-row.warning .video-log-dot {
  background: var(--warning);
}
.video-log-row.error {
  color: #fecdd3;
}
.video-log-row.error .video-log-dot {
  background: var(--danger);
}
.video-log-row.success {
  color: #a7f3d0;
}
.video-log-row.success .video-log-dot {
  background: var(--success);
}
.video-log-empty {
  font-family: var(--font);
  font-size: 10px;
  line-height: 1.55;
  color: var(--muted-2);
  padding: 5px 2px;
}

/* ------------------------------------------------------------------ */
/* Render queue                                                        */
/* ------------------------------------------------------------------ */
.video-render-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 0.78fr);
  gap: 16px;
  align-items: start;
}
.video-queue-summary {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background:
    radial-gradient(300px 160px at 10% 0%, rgba(139, 92, 246, 0.1), transparent 70%),
    rgba(8, 10, 15, 0.34);
}
.video-queue-worker {
  display: flex;
  align-items: center;
  gap: 9px;
}
.video-queue-worker .file-icon {
  width: 34px;
  height: 34px;
}
.video-queue-worker > div {
  display: flex;
  flex-direction: column;
}
.video-queue-worker span {
  font-size: 9px;
  color: var(--muted-2);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
.video-queue-worker strong {
  font-family: var(--display);
  font-size: 15px;
}
.video-queue-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(48px, 1fr));
  gap: 12px;
  margin-left: auto;
}
.video-queue-metrics > div {
  text-align: right;
}
.video-queue-metrics span {
  display: block;
  font-size: 8px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted-2);
}
.video-queue-metrics strong {
  display: block;
  font-family: var(--display);
  font-size: 18px;
  line-height: 1.2;
  margin-top: 2px;
}
.video-queue-telemetry {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.video-queue-telemetry > div {
  padding: 9px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.28);
}
.video-queue-telemetry span {
  display: block;
  font-size: 9px;
  color: var(--muted-2);
}
.video-queue-telemetry strong {
  display: block;
  font-size: 17px;
  font-family: var(--display);
  line-height: 1.2;
  margin: 2px 0 6px;
}
.video-latest-poster {
  position: relative;
  aspect-ratio: 16 / 9;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--line);
  background: #070a11;
}
.video-latest-poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.video-latest-poster > .badge {
  position: absolute;
  top: 9px;
  left: 9px;
  z-index: 2;
  background: rgba(6, 8, 13, 0.65);
  backdrop-filter: blur(7px);
}
.video-latest-shade {
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, transparent 40%, rgba(4, 6, 10, 0.86));
}
.video-latest-caption {
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: 10px;
  z-index: 2;
}
.video-latest-caption strong {
  display: block;
  font-family: var(--display);
  font-size: 16px;
  color: #fff;
  text-shadow: 0 2px 12px rgba(0, 0, 0, 0.6);
}
.video-latest-caption span {
  display: block;
  margin-top: 2px;
  font-size: 9.5px;
  color: rgba(255, 255, 255, 0.65);
}

/* ------------------------------------------------------------------ */
/* New project modal                                                   */
/* ------------------------------------------------------------------ */
.video-new-project {
  display: flex;
  flex-direction: column;
}
.video-modal-section {
  padding: 18px 0;
  border-top: 1px solid var(--line);
}
.video-modal-section:first-child {
  border-top: none;
  padding-top: 2px;
}
.video-modal-section-head {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  margin-bottom: 14px;
}
.video-modal-number {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  flex: none;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.35), rgba(34, 211, 238, 0.12));
  border: 1px solid rgba(139, 92, 246, 0.38);
  color: #e9e1ff;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 700;
}
.video-modal-section-head h3 {
  font-size: 15px;
  line-height: 1.2;
}
.video-modal-section-head p {
  margin-top: 3px;
  font-size: 11px;
  line-height: 1.45;
  color: var(--muted);
}
.video-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.video-form-grid .span-2 {
  grid-column: span 2;
}
.video-source-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}
.video-source-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: rgba(8, 10, 15, 0.32);
  min-width: 0;
  transition: 150ms ease;
}
.video-source-card.filled {
  border-color: rgba(139, 92, 246, 0.34);
  background:
    linear-gradient(135deg, rgba(139, 92, 246, 0.09), rgba(34, 211, 238, 0.025)),
    rgba(8, 10, 15, 0.32);
}
.video-source-icon {
  width: 38px;
  height: 38px;
  flex: none;
  border-radius: 10px;
  display: grid;
  place-items: center;
  color: var(--accent-2);
  background: var(--panel-3);
  border: 1px solid var(--line);
}
.video-source-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 2px;
}
.video-source-copy strong {
  font-size: 11.5px;
  font-weight: 600;
}
.video-source-copy .mono {
  display: block;
  width: 100%;
  font-size: 9.5px;
  color: var(--muted);
  max-width: 100%;
}
.video-source-copy small {
  font-size: 9px;
  color: var(--muted-2);
}
.video-source-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  flex: none;
}
.video-source-actions .btn {
  min-height: 28px;
  padding: 4px 8px;
  font-size: 10.5px;
}
.video-source-actions .icon-btn {
  width: 24px;
  height: 24px;
}
.video-style-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 6px;
}
.video-style-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  text-align: left;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(8, 10, 15, 0.3);
  color: var(--text);
  transition: 150ms ease;
}
.video-style-card:hover {
  border-color: var(--line-strong);
  background: rgba(255, 255, 255, 0.025);
}
.video-style-card.active {
  border-color: rgba(139, 92, 246, 0.5);
  background:
    linear-gradient(135deg, rgba(139, 92, 246, 0.12), rgba(34, 211, 238, 0.035)),
    rgba(8, 10, 15, 0.3);
  box-shadow: 0 0 0 1px rgba(139, 92, 246, 0.16);
}
.video-style-swatches {
  display: flex;
  gap: 3px;
}
.video-style-swatches i {
  flex: 1;
  height: 16px;
  border-radius: 3px;
  border: 1px solid rgba(255, 255, 255, 0.12);
}
.video-style-name {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 11.5px;
  font-weight: 600;
}
.video-style-description {
  font-size: 10px;
  line-height: 1.4;
  color: var(--muted);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 42px;
}
.video-provider-block {
  margin-top: 14px;
  padding: 12px;
  border: 1px solid var(--video-border);
  border-radius: 11px;
  background: rgba(8, 10, 15, 0.28);
}
.video-provider-title {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 10px;
  color: var(--accent-2);
}
.video-provider-title > div {
  min-width: 0;
}
.video-provider-title strong {
  display: block;
  color: var(--text);
  font-size: 11.5px;
}
.video-provider-title span {
  display: block;
  margin-top: 2px;
  font-size: 9.5px;
  line-height: 1.45;
  color: var(--muted-2);
}
.video-modal-footer-note {
  margin-right: auto;
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 10px;
  color: var(--muted);
}

/* ------------------------------------------------------------------ */
/* Responsive                                                          */
/* ------------------------------------------------------------------ */
@media (max-width: 1580px) {
  .video-editor-grid {
    grid-template-columns: 240px minmax(0, 1fr) 380px;
  }
  .video-editor-actions {
    max-width: 520px;
  }
}

@media (max-width: 1380px) {
  .video-editor-grid {
    grid-template-columns: 240px minmax(0, 1fr);
  }
  .video-inspector {
    grid-column: 1 / -1;
  }
  .video-inspector-scroll {
    max-height: none;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
  }
  .video-inspector-footer {
    justify-content: flex-end;
  }
  .video-inspector-footer .btn-primary {
    flex: none;
  }
  .video-projects-layout {
    grid-template-columns: minmax(0, 1fr) 300px;
  }
}

@media (max-width: 1160px) {
  .video-projects-layout,
  .video-export-grid,
  .video-activity-grid,
  .video-render-layout {
    grid-template-columns: 1fr;
  }
  .video-feature-band {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .video-projects-layout > aside {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start;
  }
  .video-live-job-grid {
    grid-template-columns: 1fr;
  }
  .video-editor-head {
    flex-direction: column;
  }
  .video-editor-actions {
    justify-content: flex-start;
    max-width: none;
  }
  .video-export-grid {
    gap: 14px;
  }
}

@media (max-width: 900px) {
  .video-editor-grid {
    grid-template-columns: 1fr;
  }
  .video-scene-list {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    max-height: none;
  }
  .video-inspector-scroll {
    grid-template-columns: 1fr;
  }
  .video-projects-layout > aside {
    grid-template-columns: 1fr;
  }
  .video-form-grid,
  .video-source-grid {
    grid-template-columns: 1fr;
  }
  .video-form-grid .span-2 {
    grid-column: span 1;
  }
  .video-style-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .video-editor-copy h2 {
    font-size: 22px;
  }
  .video-editor-cover {
    width: 88px;
  }
  .video-preview-subtitle-zone.subtitle-bottom {
    bottom: 52px;
  }
  .video-preview-subtitle {
    max-width: 92%;
  }
}

@media (max-width: 640px) {
  .video-toolbar-meta {
    display: none;
  }
  .video-projects-grid {
    grid-template-columns: 1fr;
  }
  .video-feature-band {
    grid-template-columns: 1fr;
  }
  .video-new-project-card {
    min-height: 220px;
  }
  .video-editor-actions .btn {
    font-size: 10.5px;
  }
  .video-editor-identity {
    gap: 10px;
  }
  .video-preview-control-detail {
    display: none;
  }
  .video-export-fields,
  .video-reactive-grid,
  .video-queue-telemetry {
    grid-template-columns: 1fr;
  }
  .video-queue-metrics {
    width: 100%;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    margin-left: 0;
  }
  .video-queue-metrics > div {
    text-align: left;
  }
  .video-modal-footer-note {
    display: none;
  }
  .video-style-grid {
    grid-template-columns: 1fr;
  }
  .video-live-job-grid {
    padding-left: 12px;
    padding-right: 12px;
  }
}
</style>
