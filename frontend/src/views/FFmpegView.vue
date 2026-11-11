<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  AudioLines,
  Camera,
  Captions,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Code2,
  Crop,
  Download,
  Film,
  FileAudio,
  FileImage,
  FileVideo,
  Gauge,
  GitMerge,
  Grid2x2,
  Image as ImageIcon,
  ImagePlus,
  Layers,
  Loader2,
  Maximize2,
  Music2,
  Play,
  Plus,
  RotateCw,
  Scissors,
  SlidersHorizontal,
  Sparkles,
  Split,
  Terminal,
  Trash2,
  Volume2,
  Wand2,
  X,
} from "lucide-vue-next";
import { api, downloadUrl, formatBytes, formatDuration, relativeTime } from "@/lib/api";
import type { Job } from "@/lib/types";
import { DEMO } from "@/lib/types";
import { demoFFmpegCatalog, demoJobs, demoProbe } from "@/lib/demo";
import { useJobsStore } from "@/stores/jobs";
import { useSystemStore } from "@/stores/system";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import FilePicker from "@/components/FilePicker.vue";
import JobCard from "@/components/JobCard.vue";
import CodeBlock from "@/components/CodeBlock.vue";
import EmptyState from "@/components/EmptyState.vue";
import ProgressBar from "@/components/ProgressBar.vue";

interface OperationDef {
  id: string;
  label: string;
  category: "video" | "audio" | "image" | "advanced";
  icon: any;
  blurb: string;
}

const operations: OperationDef[] = [
  { id: "transcode", label: "Transcode", category: "video", icon: Film, blurb: "Re-encode video and audio with full codec, quality and resolution control." },
  { id: "extract_audio", label: "Extract audio", category: "audio", icon: FileAudio, blurb: "Pull the audio track out as MP3, WAV, FLAC, AAC, Opus or OGG." },
  { id: "trim", label: "Trim", category: "video", icon: Scissors, blurb: "Cut a section with stream copy or a frame-accurate re-encode." },
  { id: "crop_video", label: "Crop video", category: "video", icon: Crop, blurb: "Crop a video to an exact rectangle or a target aspect ratio." },
  { id: "crop_image", label: "Crop image", category: "image", icon: Crop, blurb: "Crop a still image and save it as PNG, JPEG or WebP." },
  { id: "scale", label: "Scale", category: "video", icon: Maximize2, blurb: "Resize with fit, fill or stretch semantics and optional padding." },
  { id: "rotate", label: "Rotate / flip", category: "video", icon: RotateCw, blurb: "Rotate by 90/180/270 or any angle, then mirror horizontally or vertically." },
  { id: "concat", label: "Concat", category: "video", icon: Layers, blurb: "Join clips in order, optionally with an xfade transition." },
  { id: "overlay", label: "Overlay", category: "video", icon: ImagePlus, blurb: "Composite an image watermark or styled text onto a video." },
  { id: "subtitles", label: "Burn subtitles", category: "video", icon: Captions, blurb: "Burn SRT, VTT or ASS subtitles with complete force_style control." },
  { id: "frames", label: "Extract frames", category: "image", icon: Grid2x2, blurb: "Extract frames at a fixed rate or at explicit timestamps." },
  { id: "gif", label: "Create GIF", category: "image", icon: ImageIcon, blurb: "Turn a clip section into an optimized palette GIF." },
  { id: "merge", label: "Merge A/V", category: "video", icon: GitMerge, blurb: "Attach an audio file to a video, replacing or mixing the original." },
  { id: "replace_audio", label: "Replace audio", category: "audio", icon: Music2, blurb: "Swap or mute the original audio with a new track." },
  { id: "speed", label: "Speed", category: "video", icon: Gauge, blurb: "Speed up or slow down video and audio while preserving pitch." },
  { id: "volume", label: "Volume", category: "audio", icon: Volume2, blurb: "Apply linear or dB gain, or one-pass EBU R128 normalization." },
  { id: "normalize", label: "Normalize", category: "audio", icon: SlidersHorizontal, blurb: "Measure and apply two-pass EBU R128 loudnorm for broadcast loudness." },
  { id: "thumbnail", label: "Thumbnail", category: "image", icon: Camera, blurb: "Grab a single frame at a timestamp and resize it." },
  { id: "split", label: "Split", category: "video", icon: Split, blurb: "Split a file into fixed-duration segments with a custom output pattern." },
  { id: "raw", label: "Raw FFmpeg", category: "advanced", icon: Terminal, blurb: "Run an explicit argv list. No shell, only the ffmpeg executable." },
];

const DEMO_INPUT = "video/atravessar-noite/output/final_video.mp4";
const DEMO_IMAGE = "images/album-art/cover-porcelain-city.png";
const DEMO_AUDIO = "music/nocturno/master/nocturno-master.wav";
const DEMO_SUB = "subtitles/67c9de20/nocturno.srt";

const jobs = useJobsStore();
const system = useSystemStore();
const toasts = useToastStore();

const op = ref("trim");
const forms = reactive<Record<string, Record<string, any>>>({
  transcode: baseForm(DEMO_INPUT, {
    video_codec: "libx264",
    audio_codec: "aac",
    crf: 23,
    preset: "medium",
    video_bitrate: "",
    audio_bitrate: "192k",
    pix_fmt: "yuv420p",
    width: 1920,
    height: 1080,
    fps: 30,
    format: "mp4",
    media: "auto",
  }),
  extract_audio: baseForm(DEMO_INPUT, {
    format: "mp3",
    bitrate: "192k",
    sample_rate: 48000,
    channels: 2,
    normalize: false,
    target_lufs: -16,
    true_peak: -1.5,
    lra: 11,
  }),
  trim: baseForm(DEMO_INPUT, {
    start: 12.5,
    end: 42.5,
    duration: null,
    copy: false,
    accurate: true,
    video_codec: "libx264",
    audio_codec: "aac",
    crf: 20,
    preset: "medium",
    format: "mp4",
  }),
  crop_video: baseForm(DEMO_INPUT, {
    width: 1280,
    height: 720,
    x: 320,
    y: 180,
    aspect: "",
    center: false,
    video_codec: "libx264",
    audio_codec: "copy",
    crf: 20,
    preset: "medium",
    format: "mp4",
  }),
  crop_image: baseForm(DEMO_IMAGE, {
    width: 1200,
    height: 1200,
    x: 0,
    y: 0,
    aspect: "1:1",
    center: true,
    format: "png",
    quality: 2,
  }),
  scale: baseForm(DEMO_INPUT, {
    width: 1920,
    height: 1080,
    mode: "fit",
    pad: true,
    pad_color: "black",
    no_upscale: false,
    flags: "lanczos",
    video_codec: "libx264",
    audio_codec: "copy",
    crf: 20,
    preset: "medium",
    format: "mp4",
  }),
  rotate: baseForm(DEMO_INPUT, {
    angle: 90,
    flip_h: false,
    flip_v: false,
    fill_color: "black",
    video_codec: "libx264",
    audio_codec: "copy",
    crf: 20,
    preset: "medium",
    format: "mp4",
  }),
  concat: baseForm("", {
    files: [DEMO_INPUT, "video/atravessar-noite/output/final_video.mp4"],
    copy: true,
    reencode: false,
    transition: "fade",
    transition_duration: 0.6,
    video_codec: "libx264",
    audio_codec: "aac",
    crf: 20,
    preset: "medium",
    format: "mp4",
  }),
  overlay: baseForm(DEMO_INPUT, {
    mode: "image",
    overlay_path: DEMO_IMAGE,
    text: "OPEN STUDIO · FIELD NOTES",
    position: "bottom-right",
    x: null,
    y: null,
    margin: 28,
    opacity: 0.86,
    scale: "18%",
    font: "DejaVu Sans",
    font_file: "",
    font_size: 36,
    font_color: "#ffffff",
    border_width: 2,
    border_color: "black",
    shadow: 0,
    box: true,
    box_color: "black@0.45",
    start: 0,
    end: 30,
    video_codec: "libx264",
    audio_codec: "copy",
    crf: 20,
    preset: "medium",
    format: "mp4",
  }),
  subtitles: baseForm(DEMO_INPUT, {
    subtitle_path: DEMO_SUB,
    font: "DejaVu Sans",
    font_size: 28,
    color: "#ffffff",
    outline_color: "#000000",
    outline: 1.4,
    shadow: 0,
    position: "bottom",
    margin_v: 36,
    margin_l: 24,
    margin_r: 24,
    bold: false,
    italic: false,
    fontsdir: "",
    burn: true,
    video_codec: "libx264",
    audio_codec: "copy",
    crf: 20,
    preset: "medium",
    format: "mp4",
  }),
  frames: baseForm(DEMO_INPUT, {
    frames_mode: "fps",
    fps: 2,
    timestamps: "0, 5, 12.5, 24, 36",
    start: 30,
    duration: 10,
    format: "jpg",
    width: 1280,
    height: -1,
    quality: 2,
    max_frames: 100,
  }),
  gif: baseForm(DEMO_INPUT, {
    start: 18,
    duration: 4,
    fps: 15,
    width: 640,
    max_colors: 256,
    dither: "bayer",
    loop: 0,
    palette: true,
  }),
  merge: baseForm(DEMO_INPUT, {
    audio_path: DEMO_AUDIO,
    replace: true,
    original_volume: 0.35,
    new_volume: 1,
    shortest: true,
    copy_video: true,
    audio_codec: "aac",
    audio_bitrate: "192k",
    format: "mp4",
  }),
  replace_audio: baseForm(DEMO_INPUT, {
    audio_path: DEMO_AUDIO,
    mute_original: true,
    original_volume: 0.35,
    new_volume: 1,
    shortest: false,
    copy_video: true,
    audio_codec: "aac",
    audio_bitrate: "192k",
    format: "mp4",
  }),
  speed: baseForm(DEMO_INPUT, {
    factor: 1.25,
    video_factor: null,
    audio_factor: null,
    pitch_correction: true,
    video_codec: "libx264",
    audio_codec: "aac",
    crf: 20,
    preset: "medium",
    audio_bitrate: "192k",
    format: "mp4",
  }),
  volume: baseForm(DEMO_INPUT, {
    gain_db: -3,
    gain: null,
    normalize: false,
    target_lufs: -16,
    true_peak: -1.5,
    lra: 11,
    audio_codec: "aac",
    audio_bitrate: "192k",
    copy_video: true,
    format: "mp4",
  }),
  normalize: baseForm(DEMO_INPUT, {
    target_lufs: -14,
    true_peak: -1,
    lra: 11,
    sample_rate: 48000,
    dual_mono: false,
    keep_video: false,
    format: "wav",
    audio_codec: "",
    audio_bitrate: "192k",
  }),
  thumbnail: baseForm(DEMO_INPUT, {
    time: 24,
    width: 640,
    height: null,
    format: "jpg",
    quality: 2,
  }),
  split: baseForm(DEMO_INPUT, {
    duration: 30,
    copy: true,
    video_codec: "libx264",
    audio_codec: "aac",
    crf: 23,
    preset: "medium",
    reset_timestamps: true,
    format: "mp4",
    segment_pattern: "segment_%03d.mp4",
  }),
  raw: baseForm(DEMO_INPUT, {
    argv: [
      "-c:v",
      "libx264",
      "-preset",
      "slow",
      "-crf",
      "19",
      "-vf",
      "scale=1920:-2",
      "-c:a",
      "aac",
      "-b:a",
      "192k",
    ].join("\n"),
    timeout: 3600,
  }),
});

function baseForm(input: string, values: Record<string, any>): Record<string, any> {
  return { input_path: input, output_path: "", extra_options: "", _auto_output: true, ...values };
}

for (const definition of operations) {
  const entry = forms[definition.id];
  entry.output_path = suggestOutput(definition.id, entry);
}

const current = computed(() => forms[op.value]);
const currentOperation = computed(() => operations.find((item) => item.id === op.value) || operations[0]);

const inputPicker = ref(false);
const probePicker = ref(false);
const concatPicker = ref(false);
const overlayPicker = ref(false);
const subtitlePicker = ref(false);
const audioPicker = ref(false);

const catalog = ref<any>(DEMO ? demoFFmpegCatalog : null);
const catalogLoading = ref(false);
const activeProcesses = ref<any[]>(
  DEMO
    ? [{ job_id: "job_ffmpeg_preview", operation: "thumbnail", input: DEMO_IMAGE, progress: 63, elapsed: "1.8s" }]
    : [],
);

const probePath = ref(DEMO_INPUT);
const probeResult = ref<any>(DEMO ? demoProbe : null);
const probeLoading = ref(false);
const showProbeJson = ref(false);

const busyJob = ref(false);
const busySync = ref(false);
const syncResult = ref<any>(null);
const activeJobId = ref("");
const demoActiveJob = ref<Job | null>(null);
const demoHistory = ref<Job[]>([]);

const inputKind = computed<"all" | "video" | "audio" | "image" | "subtitle">(() => {
  if (op.value === "crop_image") return "image";
  if (op.value === "overlay") return "video";
  return "all";
});
const initialDir = computed(() => parentDir(current.value.input_path || ""));

const videoCodecs = computed<string[]>(
  () => catalog.value?.codecs?.video || catalog.value?.video_codecs || demoFFmpegCatalog.video_codecs,
);
const audioCodecs = computed<string[]>(
  () => catalog.value?.codecs?.audio || catalog.value?.audio_codecs || demoFFmpegCatalog.audio_codecs,
);
const formats = computed<string[]>(() => catalog.value?.formats || demoFFmpegCatalog.formats);
const ffmpegVersion = computed(() => catalog.value?.ffmpeg?.version || catalog.value?.version || "7.0.2");
const serviceVersion = computed(() => (catalog.value?.service ? `service ${catalog.value.version}` : "bundled runner"));
const ffmpegService = computed(() => system.service("ffmpeg"));
const operationCount = computed(() => catalog.value?.operations?.length || operations.length);

const activeJob = computed<Job | null>(() => {
  if (DEMO) return demoActiveJob.value;
  if (activeJobId.value) return jobs.byId(activeJobId.value) || null;
  return jobs.items.find((job) => job.component === "ffmpeg" && ["queued", "running", "canceling"].includes(job.status)) || null;
});

const history = computed<Job[]>(() => {
  if (DEMO) return demoHistory.value;
  return jobs.items.filter((job) => job.component === "ffmpeg").slice(0, 8);
});

const ffmpegActiveJobs = computed(() => {
  if (DEMO) return demoActiveJob.value && ["queued", "running", "canceling"].includes(demoActiveJob.value.status) ? [demoActiveJob.value] : [];
  return jobs.items.filter((job) => job.component === "ffmpeg" && ["queued", "running", "canceling"].includes(job.status));
});

const result = computed<any>(() => {
  if (syncResult.value) return syncResult.value;
  return activeJob.value?.result || null;
});
const resultFiles = computed<any[]>(() => (Array.isArray(result.value?.files) ? result.value.files : []));
const outputSummary = computed<any>(() => result.value?.data?.output || null);
const resultMessage = computed(() => result.value?.message || activeJob.value?.message || "");
const resultWarnings = computed<string[]>(() => {
  const dataWarnings = result.value?.data?.warnings;
  return [...(activeJob.value?.warnings || []), ...(Array.isArray(dataWarnings) ? dataWarnings : [])];
});

const effectiveOutput = computed(() => {
  const entry = current.value;
  const base = String(entry.output_path || "").trim();
  if (op.value === "split") {
    const pattern = String(entry.segment_pattern || "segment_%03d.mp4").trim();
    return base ? `${base.replace(/\/+$/, "")}/${pattern.replace(/^\/+/, "")}` : pattern;
  }
  return base;
});

const rawArgv = computed(() => String(current.value.argv || "").split(/\r?\n/).filter((line) => line.length > 0));
const rawLooksValid = computed(() => rawArgv.value.length > 0 && !rawArgv.value.some((line) => line.includes("\0")));
const rawHasInput = computed(() => rawArgv.value.includes("-i"));
const rawHasShellTokens = computed(() => rawArgv.value.some((line) => /[;&|<>`]/.test(line)));
const rawPreview = computed(() => ["ffmpeg", ...rawArgv.value, ...(effectiveOutput.value ? [effectiveOutput.value] : [])].join(" "));

const probeStreams = computed<any[]>(() => (Array.isArray(probeResult.value?.streams) ? probeResult.value.streams : []));

onMounted(async () => {
  if (DEMO) {
    demoActiveJob.value = buildDemoCompletedJob();
    demoHistory.value = [demoActiveJob.value, ...demoJobs.filter((job) => job.component === "ffmpeg").map(cloneJob)];
    catalog.value = demoFFmpegCatalog;
    return;
  }
  if (!jobs.items.length) jobs.refresh();
  loadCatalog();
  loadProcesses();
});

async function loadCatalog() {
  catalogLoading.value = true;
  try {
    if (DEMO) {
      catalog.value = demoFFmpegCatalog;
      toasts.info("Demo FFmpeg catalog refreshed");
      return;
    }
    catalog.value = await api.get<any>("/ffmpeg/catalog");
  } catch (error: any) {
    toasts.error(error?.message || "Could not load the FFmpeg catalog");
  } finally {
    catalogLoading.value = false;
  }
}

async function loadProcesses() {
  try {
    const data = await api.get<any>("/ffmpeg/active");
    activeProcesses.value = Array.isArray(data.processes) ? data.processes : [];
  } catch {
    activeProcesses.value = [];
  }
}

function cloneJob(job: Job): Job {
  return JSON.parse(JSON.stringify(job));
}

function isoAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

function buildDemoCompletedJob(): Job {
  const output = {
    path: "ffmpeg/exports/final_video_trim.mp4",
    kind: "video",
    duration: 30,
    size: 48_210_304,
    format: "mov,mp4,m4a,3gp,3g2,mj2",
    width: 1920,
    height: 1080,
    fps: 30,
    video_codec: "h264",
    audio_codec: "aac",
    sample_rate: 48000,
    channels: 2,
  };
  return {
    id: "job_trim_9f2a71",
    component: "ffmpeg",
    action: "trim",
    title: "FFmpeg · Trim · final_video.mp4",
    status: "completed",
    stage: "Complete",
    message: "Trimmed 00:12.5 → 00:42.5 with a frame-accurate re-encode.",
    progress: 100,
    params: { operation: "trim", input_path: DEMO_INPUT, output_path: "ffmpeg/exports/final_video_trim.mp4" },
    result: {
      message: "Trimmed final_video.mp4",
      files: [
        {
          path: "ffmpeg/exports/final_video_trim.mp4",
          name: "final_video_trim.mp4",
          kind: "video",
          mime: "video/mp4",
          size: 48_210_304,
        },
      ],
      data: {
        operation: "trim",
        elapsed_seconds: 12.4,
        file_count: 1,
        output,
        warnings: [],
      },
    },
    error: null,
    warnings: [],
    artifacts: [
      {
        path: "ffmpeg/exports/final_video_trim.mp4",
        name: "final_video_trim.mp4",
        kind: "video",
        mime: "video/mp4",
        size: 48_210_304,
      },
    ],
    cancel_requested: false,
    attempts: 1,
    created_at: isoAgo(18),
    started_at: isoAgo(18),
    finished_at: isoAgo(17),
    updated_at: isoAgo(17),
  };
}

function suggestOutput(operation: string, entry: Record<string, any>): string {
  const input = String(entry.input_path || "").trim();
  const stem = basename(input).replace(/\.[^.]+$/, "") || (operation === "concat" ? "concert-master" : "output");
  if (operation === "frames") return `ffmpeg/exports/${stem}_frames/`;
  if (operation === "split") return `ffmpeg/exports/${stem}_segments/`;
  if (operation === "concat") return `ffmpeg/exports/${stem}_concat.mp4`;
  return `ffmpeg/exports/${stem}_${operation}.${extensionFor(operation, entry)}`;
}

function extensionFor(operation: string, entry: Record<string, any>): string {
  switch (operation) {
    case "extract_audio":
      return entry.format || "mp3";
    case "normalize":
      return entry.keep_video ? "mp4" : entry.format || "wav";
    case "thumbnail":
    case "crop_image":
      return entry.format || "jpg";
    case "frames":
      return entry.format || "jpg";
    case "gif":
      return "gif";
    case "raw":
      return "mp4";
    default:
      return entry.format || "mp4";
  }
}

function basename(path: string): string {
  return String(path || "").split("/").pop() || "";
}

function parentDir(path: string): string {
  const parts = String(path || "").split("/");
  parts.pop();
  return parts.join("/");
}

function selectOperation(id: string) {
  op.value = id;
  syncResult.value = null;
  const entry = forms[id];
  if (entry._auto_output || !entry.output_path) {
    entry.output_path = suggestOutput(id, entry);
  }
}

function syncOutput(force = false) {
  const entry = current.value;
  if (force || entry._auto_output || !entry.output_path) {
    entry.output_path = suggestOutput(op.value, entry);
    entry._auto_output = true;
  }
}

function onInputSelected(path: string) {
  current.value.input_path = path;
  if (current.value._auto_output) syncOutput(true);
}

function markOutputManual() {
  current.value._auto_output = false;
}

function addConcatFile(path: string) {
  if (!forms.concat.files.includes(path)) forms.concat.files.push(path);
}

function setOverlayPath(path: string) {
  current.value.overlay_path = path;
}

function setSubtitlePath(path: string) {
  current.value.subtitle_path = path;
}

function setAudioPath(path: string) {
  current.value.audio_path = path;
}

function moveConcat(index: number, direction: number) {
  const list = forms.concat.files as string[];
  const target = index + direction;
  if (target < 0 || target >= list.length) return;
  const [entry] = list.splice(index, 1);
  list.splice(target, 0, entry);
}

function removeConcat(index: number) {
  forms.concat.files.splice(index, 1);
}

const OP_KEYS: Record<string, string[]> = {
  transcode: ["video_codec", "audio_codec", "crf", "preset", "video_bitrate", "audio_bitrate", "pix_fmt", "width", "height", "fps", "format", "media", "profile", "level", "tune", "sample_rate", "channels", "resolution", "hwaccel", "hwaccel_device", "movflags_faststart", "shortest"],
  extract_audio: ["format", "bitrate", "sample_rate", "channels", "normalize", "target_lufs", "true_peak", "lra", "audio_codec", "audio_bitrate"],
  trim: ["start", "end", "duration", "copy", "accurate", "video_codec", "audio_codec", "crf", "preset", "format"],
  crop_video: ["width", "height", "x", "y", "aspect", "center", "video_codec", "audio_codec", "crf", "preset", "audio_bitrate", "format"],
  crop_image: ["width", "height", "x", "y", "aspect", "center", "format", "quality"],
  scale: ["width", "height", "mode", "pad", "pad_color", "no_upscale", "flags", "video_codec", "audio_codec", "crf", "preset", "audio_bitrate", "format"],
  rotate: ["angle", "flip_h", "flip_v", "fill_color", "video_codec", "audio_codec", "crf", "preset", "format"],
  concat: ["copy", "reencode", "transition", "transition_duration", "video_codec", "audio_codec", "crf", "preset", "format"],
  overlay: ["mode", "overlay_path", "text", "position", "x", "y", "margin", "opacity", "scale", "font", "font_file", "font_size", "font_color", "border_width", "border_color", "shadow", "box", "box_color", "start", "end", "video_codec", "audio_codec", "crf", "preset", "format"],
  subtitles: ["subtitle_path", "font", "font_size", "color", "outline_color", "outline", "shadow", "position", "margin_v", "margin_l", "margin_r", "bold", "italic", "underline", "strikeout", "fontsdir", "burn", "video_codec", "audio_codec", "crf", "preset", "format"],
  frames: ["mode", "fps", "timestamps", "start", "duration", "format", "width", "height", "quality", "max_frames"],
  gif: ["start", "duration", "fps", "width", "max_colors", "dither", "loop", "palette"],
  merge: ["audio_path", "replace", "original_volume", "new_volume", "shortest", "copy_video", "video_codec", "audio_codec", "audio_bitrate", "format"],
  replace_audio: ["audio_path", "mute_original", "original_volume", "new_volume", "shortest", "copy_video", "audio_codec", "audio_bitrate", "format"],
  speed: ["factor", "video_factor", "audio_factor", "pitch_correction", "video_codec", "audio_codec", "crf", "preset", "audio_bitrate", "format"],
  volume: ["gain_db", "gain", "normalize", "target_lufs", "true_peak", "lra", "audio_codec", "audio_bitrate", "copy_video", "format"],
  normalize: ["target_lufs", "true_peak", "lra", "sample_rate", "dual_mono", "keep_video", "format", "audio_codec", "audio_bitrate"],
  thumbnail: ["time", "width", "height", "format", "quality"],
  split: ["duration", "copy", "video_codec", "audio_codec", "crf", "preset", "reset_timestamps", "format"],
  raw: ["argv", "timeout"],
};

function parseTimestamps(value: string): number[] {
  return String(value || "")
    .split(/[\s,;]+/)
    .map((part) => Number(part))
    .filter((number) => Number.isFinite(number) && number >= 0);
}

function parseExtraOptions(): Record<string, any> {
  const raw = String(current.value.extra_options || "").trim();
  if (!raw) return {};
  const parsed = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Extra options must be a JSON object");
  }
  return parsed;
}

function buildOptions(): Record<string, any> {
  const entry = current.value;
  const options: Record<string, any> = {};
  const keys = OP_KEYS[op.value] || [];
  for (const key of keys) {
    const value = entry[key];
    if (value === "" || value === null || value === undefined) continue;
    options[key] = value;
  }
  if (op.value === "concat") {
    options.files = [...(entry.files || [])];
    if (!options.files.length) throw new Error("Add at least two clips to concatenate");
  }
  if (op.value === "frames") {
    options.mode = entry.frames_mode;
    if (entry.frames_mode === "timestamps") {
      options.timestamps = parseTimestamps(entry.timestamps);
      delete options.fps;
      if (!options.timestamps.length) throw new Error("Add at least one valid timestamp");
    } else {
      delete options.timestamps;
    }
  }
  if (op.value === "raw") {
    const argv = rawArgv.value;
    if (!argv.length) throw new Error("The raw argv list is empty");
    const first = basename(argv[0]).toLowerCase();
    if (first !== "ffmpeg" && first !== "ffmpeg.exe" && !argv[0].startsWith("-")) {
      throw new Error("Raw argv must start with ffmpeg flags or the ffmpeg executable");
    }
    if (argv.some((item) => item.includes("\0"))) throw new Error("Arguments cannot contain null bytes");
    options.argv = first === "ffmpeg" || first === "ffmpeg.exe" ? argv.slice(1) : argv;
    delete options.frames_mode;
  }
  return { ...options, ...parseExtraOptions() };
}

function validate(): string | null {
  const entry = current.value;
  if (op.value !== "concat" && op.value !== "raw" && !String(entry.input_path || "").trim()) {
    return "Choose an input file first.";
  }
  if (op.value === "concat" && (entry.files || []).length < 2) {
    return "Concatenate needs at least two clips.";
  }
  if (op.value === "trim") {
    if (entry.end !== null && entry.end !== "" && Number(entry.end) <= Number(entry.start)) return "Trim end must be after the start time.";
    if (entry.duration !== null && entry.duration !== "" && Number(entry.duration) <= 0) return "Trim duration must be positive.";
  }
  if (["crop_video", "crop_image"].includes(op.value)) {
    if (!entry.width && !entry.height && !entry.aspect && !entry.center) return "Set a crop rectangle, an aspect ratio or center the crop.";
  }
  if (op.value === "scale" && !entry.width && !entry.height) {
    return "Scale needs at least one of width or height.";
  }
  if (op.value === "gif" && Number(entry.duration) <= 0) return "GIF duration must be positive.";
  if (op.value === "split" && Number(entry.duration) < 1) return "Segment duration must be at least one second.";
  if (op.value === "speed" && Number(entry.factor) < 0.1) return "Speed factor must be at least 0.1.";
  if (op.value === "overlay" && entry.mode !== "text" && !String(entry.overlay_path || "").trim()) {
    return "Choose an overlay image or switch to text mode.";
  }
  if (op.value === "overlay" && entry.mode === "text" && !String(entry.text || "").trim()) {
    return "Enter the text to draw.";
  }
  if (op.value === "subtitles" && !String(entry.subtitle_path || "").trim()) {
    return "Choose a subtitle file.";
  }
  if (["merge", "replace_audio"].includes(op.value) && !String(entry.audio_path || "").trim()) {
    return "Choose the audio file.";
  }
  if (op.value === "split" && !String(entry.segment_pattern || "").match(/%0?\d*d/)) {
    return "The segment pattern must contain a counter such as %03d.";
  }
  if (op.value === "raw" && !rawLooksValid.value) {
    return "The raw argv list is not valid.";
  }
  if (op.value === "raw" && !rawHasInput.value && !String(entry.input_path || "").trim()) {
    return "Add -i to argv or choose an input file.";
  }
  if (op.value !== "concat" && op.value !== "raw") {
    const input = String(entry.input_path || "").trim();
    const output = effectiveOutput.value.replace(/\/+$/, "");
    if (input && output && input === output) return "Output path must differ from the input path.";
  }
  return null;
}

function payload(): Record<string, any> {
  const entry = current.value;
  const options = buildOptions();
  return {
    operation: op.value,
    input_path: op.value === "concat" ? "" : String(entry.input_path || ""),
    output_path: effectiveOutput.value,
    options,
    title: `FFmpeg · ${currentOperation.value.label} · ${basename(entry.input_path) || "argv"}`,
  };
}

async function runJob() {
  const problem = validate();
  if (problem) {
    toasts.error(problem);
    return;
  }
  busyJob.value = true;
  try {
    syncResult.value = null;
    const body = payload();
    if (DEMO) {
      await runDemo(body, false);
      return;
    }
    const job = await api.post<Job>("/ffmpeg/run", body);
    jobs.upsert(job);
    activeJobId.value = job.id;
    toasts.success("FFmpeg job queued");
  } catch (error: any) {
    toasts.error(error?.message || "Could not submit the FFmpeg job");
  } finally {
    busyJob.value = false;
  }
}

async function runSync() {
  const problem = validate();
  if (problem) {
    toasts.error(problem);
    return;
  }
  busySync.value = true;
  try {
    syncResult.value = null;
    const body = payload();
    if (DEMO) {
      await runDemo(body, true);
      return;
    }
    const data = await api.post<any>("/ffmpeg/run-sync", body);
    syncResult.value = data;
    await jobs.refresh();
    toasts.success("Synchronous FFmpeg run completed");
  } catch (error: any) {
    toasts.error(error?.message || "The synchronous run failed");
  } finally {
    busySync.value = false;
  }
}

async function runDemo(body: Record<string, any>, sync: boolean) {
  const demo = buildDemoCompletedJob();
  demo.title = body.title;
  demo.action = body.operation;
  demo.message = sync ? "Synchronous demo run completed." : "Demo job completed in the ffmpeg container.";
  demo.params = body;
  const output = demo.result?.data?.output;
  if (output) output.path = effectiveOutput.value || output.path;
  const file = demo.result?.files?.[0];
  if (file) {
    file.path = effectiveOutput.value || file.path;
    file.name = basename(file.path);
    demo.artifacts = [{ ...file }];
  }
  if (sync) {
    syncResult.value = demo.result;
    demoActiveJob.value = demo;
  } else {
    demoActiveJob.value = demo;
  }
  demoHistory.value = [demo, ...demoHistory.value.filter((item) => item.id !== demo.id)];
  await new Promise((resolve) => window.setTimeout(resolve, 450));
  if (sync) toasts.success("Synchronous demo run completed");
  else toasts.success("FFmpeg demo job completed");
}

async function probe() {
  const path = String(probePath.value || "").trim();
  if (!path) {
    toasts.error("Choose a file to probe.");
    return;
  }
  probeLoading.value = true;
  try {
    if (DEMO) {
      probeResult.value = demoProbe;
      toasts.success("ffprobe demo metadata loaded");
      return;
    }
    probeResult.value = await api.post<any>("/ffmpeg/probe", { path });
  } catch (error: any) {
    toasts.error(error?.message || "ffprobe failed");
  } finally {
    probeLoading.value = false;
  }
}

function probeSelected(path: string) {
  probePath.value = path;
  probeResult.value = null;
}

async function cancelJob(id: string) {
  if (DEMO) {
    if (demoActiveJob.value?.id === id) demoActiveJob.value = { ...demoActiveJob.value, status: "canceled", message: "Cancelled by the user." };
    toasts.info("Demo job cancelled");
    return;
  }
  try {
    await jobs.cancel(id);
    toasts.info("Cancellation requested");
  } catch (error: any) {
    toasts.error(error?.message || "Could not cancel the job");
  }
}

async function retryJob(id: string) {
  if (DEMO) {
    const job = demoHistory.value.find((item) => item.id === id);
    if (job) demoActiveJob.value = { ...cloneJob(job), status: "running", progress: 18, message: "Re-queued in demo mode." };
    toasts.info("Demo job restarted");
    return;
  }
  try {
    const job = await jobs.retry(id);
    activeJobId.value = job.id;
    toasts.success("Job restarted");
  } catch (error: any) {
    toasts.error(error?.message || "Could not retry the job");
  }
}

async function removeJob(id: string) {
  if (DEMO) {
    demoHistory.value = demoHistory.value.filter((item) => item.id !== id);
    if (demoActiveJob.value?.id === id) demoActiveJob.value = null;
    toasts.success("Demo job removed");
    return;
  }
  try {
    await jobs.remove(id);
    if (activeJobId.value === id) activeJobId.value = "";
    toasts.success("Job record removed");
  } catch (error: any) {
    toasts.error(error?.message || "Could not remove the job");
  }
}

function bitrateLabel(value?: number | null): string {
  if (!value) return "—";
  return value >= 1_000_000 ? `${(value / 1_000_000).toFixed(1)} Mbps` : `${Math.round(value / 1000)} kbps`;
}

function streamResolution(stream: any): string {
  if (!stream) return "—";
  if (stream.width && stream.height) return `${stream.width} × ${stream.height}`;
  if (stream.channels || stream.sample_rate) return "Audio";
  return "—";
}

function openPicker(which: "input" | "probe" | "concat" | "overlay" | "subtitle" | "audio") {
  if (which === "input") inputPicker.value = true;
  if (which === "probe") probePicker.value = true;
  if (which === "concat") concatPicker.value = true;
  if (which === "overlay") overlayPicker.value = true;
  if (which === "subtitle") subtitlePicker.value = true;
  if (which === "audio") audioPicker.value = true;
}

const categoryTone: Record<string, string> = {
  video: "chip",
  audio: "chip success",
  image: "chip warn",
  advanced: "chip danger",
};
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="Media toolkit · shared files · job queue"
      title="FFmpeg workbench"
      subtitle="Every operation runs inside the ffmpeg Docker image against the same shared file tree. Submit long work to the global job queue or run short cuts synchronously, then reuse the result anywhere in Open Studio."
    >
      <template #actions>
        <span class="chip" :class="ffmpegService?.online ? 'success' : ''">
          <span class="dot" :class="ffmpegService?.online ? 'online' : 'busy'" />
          {{ ffmpegService?.online ? "ffmpeg online" : "bundled ffmpeg" }}
        </span>
        <span class="chip"><Film :size="11" /> FFmpeg {{ ffmpegVersion }}</span>
        <button class="btn btn-sm" :disabled="catalogLoading" @click="loadCatalog">
          <Loader2 v-if="catalogLoading" :size="13" class="spin" />
          <Sparkles v-else :size="13" />
          Refresh catalog
        </button>
      </template>
    </PageHeader>

    <div class="workbench">
      <aside class="panel ops-panel">
        <div class="panel-head" style="padding: 14px 15px">
          <div>
            <h3>Operations</h3>
            <p>{{ operationCount }} registered in the catalog</p>
          </div>
          <span class="badge">{{ operations.length }}</span>
        </div>
        <div class="panel-body" style="padding: 8px">
          <div class="tool-grid ops-grid">
            <button
              v-for="definition in operations"
              :key="definition.id"
              class="tool-btn ops-btn"
              :class="{ active: definition.id === op }"
              @click="selectOperation(definition.id)"
            >
              <span class="row" style="gap: 7px; width: 100%">
                <component :is="definition.icon" :size="14" />
                <span class="grow truncate">{{ definition.label }}</span>
              </span>
              <span class="small muted ops-category">{{ definition.category }}</span>
            </button>
          </div>
        </div>
        <div class="panel-footer" style="justify-content: space-between">
          <span class="small muted">All paths relative to /data/files</span>
          <span class="chip">{{ currentOperation.category }}</span>
        </div>
      </aside>

      <main class="stack">
        <section class="panel">
          <div class="panel-head">
            <div class="row" style="gap: 10px; min-width: 0">
              <span class="file-icon" style="width: 38px; height: 38px"><component :is="currentOperation.icon" :size="18" /></span>
              <div style="min-width: 0">
                <h3>{{ currentOperation.label }}</h3>
                <p>{{ currentOperation.blurb }}</p>
              </div>
            </div>
            <span class="chip" :class="categoryTone[currentOperation.category]">{{ currentOperation.category }}</span>
          </div>

          <div class="panel-body stack">
            <div class="form-grid">
              <div class="field" v-if="op !== 'concat'">
                <label>Input file <span class="muted small">required</span></label>
                <div class="input-group">
                  <input v-model="current.input_path" class="input mono" placeholder="video/my-clip.mp4" @input="syncOutput()" />
                  <button class="btn btn-sm" @click="openPicker('input')">Browse</button>
                </div>
                <span class="hint">Video, audio and still images are all supported. Files are shared with every studio.</span>
              </div>

              <div class="field">
                <label>
                  Output path
                  <button class="btn btn-sm btn-ghost" style="min-height: 20px; padding: 0 4px" @click="syncOutput(true)"><Wand2 :size="11" /> Suggest</button>
                </label>
                <div class="input-group">
                  <input v-model="current.output_path" class="input mono" placeholder="ffmpeg/exports/output.mp4" @input="markOutputManual" />
                  <button v-if="current.output_path" class="icon-btn" title="Clear" @click="current.output_path = ''; syncOutput(true)"><X :size="14" /></button>
                </div>
                <span class="hint">Auto-suggested under <span class="mono">ffmpeg/</span>. Folders and <span class="mono">%03d</span> patterns are supported.</span>
              </div>
            </div>

            <div v-if="op === 'transcode'" class="form-grid cols-3">
              <div class="field">
                <label>Video codec</label>
                <select v-model="current.video_codec" class="select">
                  <option v-for="codec in videoCodecs" :key="codec" :value="codec">{{ codec }}</option>
                  <option value="copy">copy</option>
                </select>
              </div>
              <div class="field">
                <label>Audio codec</label>
                <select v-model="current.audio_codec" class="select">
                  <option v-for="codec in audioCodecs" :key="codec" :value="codec">{{ codec }}</option>
                  <option value="none">none</option>
                </select>
              </div>
              <div class="field"><label>CRF</label><input v-model.number="current.crf" type="number" min="0" max="63" class="input" /></div>
              <div class="field">
                <label>Preset</label>
                <select v-model="current.preset" class="select">
                  <option v-for="preset in ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow', 'placebo']" :key="preset">{{ preset }}</option>
                </select>
              </div>
              <div class="field"><label>Video bitrate</label><input v-model="current.video_bitrate" class="input" placeholder="6M (overrides CRF)" /></div>
              <div class="field"><label>Audio bitrate</label><input v-model="current.audio_bitrate" class="input" placeholder="192k" /></div>
              <div class="field">
                <label>Pixel format</label>
                <select v-model="current.pix_fmt" class="select">
                  <option v-for="pix in ['yuv420p', 'yuv422p', 'yuv444p', 'yuv420p10le', 'yuv422p10le', 'yuv444p10le', 'nv12', 'rgb24', 'gray']" :key="pix">{{ pix }}</option>
                </select>
              </div>
              <div class="field"><label>Width</label><input v-model.number="current.width" type="number" class="input" /></div>
              <div class="field"><label>Height</label><input v-model.number="current.height" type="number" class="input" /></div>
              <div class="field"><label>Frame rate</label><input v-model.number="current.fps" type="number" step="0.01" class="input" /></div>
              <div class="field">
                <label>Container</label>
                <select v-model="current.format" class="select">
                  <option v-for="format in formats" :key="format">{{ format }}</option>
                </select>
              </div>
              <div class="field">
                <label>Streams</label>
                <select v-model="current.media" class="select"><option>auto</option><option>video</option><option>audio</option></select>
              </div>
            </div>

            <div v-if="op === 'extract_audio'" class="form-grid cols-3">
              <div class="field"><label>Format</label><select v-model="current.format" class="select"><option v-for="format in ['mp3', 'wav', 'flac', 'aac', 'opus', 'ogg']" :key="format">{{ format }}</option></select></div>
              <div class="field"><label>Bitrate</label><input v-model="current.bitrate" class="input" placeholder="192k" /></div>
              <div class="field"><label>Sample rate</label><select v-model.number="current.sample_rate" class="select"><option :value="''">Source</option><option v-for="rate in [8000, 16000, 22050, 32000, 44100, 48000, 88200, 96000]" :key="rate" :value="rate">{{ rate }} Hz</option></select></div>
              <div class="field"><label>Channels</label><select v-model.number="current.channels" class="select"><option :value="''">Source</option><option v-for="count in [1, 2, 3, 4, 6, 8]" :key="count" :value="count">{{ count }}</option></select></div>
            </div>
            <div v-if="op === 'extract_audio'" class="switch-row">
              <div><div class="switch-label">Normalize loudness</div><div class="switch-hint">Add a single-pass EBU R128 loudnorm stage.</div></div>
              <button class="switch" :class="{ on: current.normalize }" @click="current.normalize = !current.normalize" />
            </div>
            <div v-if="op === 'extract_audio' && current.normalize" class="form-grid cols-3">
              <div class="field"><label>Target LUFS</label><input v-model.number="current.target_lufs" type="number" class="input" /></div>
              <div class="field"><label>True peak (dBTP)</label><input v-model.number="current.true_peak" type="number" step="0.1" class="input" /></div>
              <div class="field"><label>Loudness range</label><input v-model.number="current.lra" type="number" class="input" /></div>
            </div>

            <template v-if="op === 'trim'">
              <div class="form-grid cols-3">
                <div class="field"><label>Start (-ss)</label><input v-model.number="current.start" type="number" min="0" step="0.01" class="input" /><span class="hint">Seconds</span></div>
                <div class="field"><label>End (-to)</label><input v-model.number="current.end" type="number" min="0" step="0.01" class="input" /><span class="hint">Seconds; ignored when duration is set.</span></div>
                <div class="field"><label>Duration</label><input v-model.number="current.duration" type="number" min="0.01" step="0.01" class="input" placeholder="Optional" /></div>
              </div>
              <div class="form-grid cols-3">
                <div class="field"><label>Video codec</label><select v-model="current.video_codec" class="select"><option v-for="codec in videoCodecs" :key="codec">{{ codec }}</option></select></div>
                <div class="field"><label>Audio codec</label><select v-model="current.audio_codec" class="select"><option v-for="codec in audioCodecs" :key="codec">{{ codec }}</option></select></div>
                <div class="field"><label>CRF</label><input v-model.number="current.crf" type="number" class="input" /></div>
              </div>
              <div class="switch-row">
                <div><div class="switch-label">Stream copy</div><div class="switch-hint">Fast and lossless, but cuts land on keyframes.</div></div>
                <button class="switch" :class="{ on: current.copy }" @click="current.copy = !current.copy" />
              </div>
              <div class="switch-row" v-if="!current.copy">
                <div><div class="switch-label">Frame-accurate seek</div><div class="switch-hint">Decodes to the exact frame before cutting.</div></div>
                <button class="switch" :class="{ on: current.accurate }" @click="current.accurate = !current.accurate" />
              </div>
            </template>

            <div v-if="['crop_video', 'crop_image'].includes(op)" class="form-grid cols-3">
              <div class="field"><label>Width</label><input v-model.number="current.width" type="number" min="1" class="input" /></div>
              <div class="field"><label>Height</label><input v-model.number="current.height" type="number" min="1" class="input" /></div>
              <div class="field"><label>Aspect</label><input v-model="current.aspect" class="input" placeholder="16:9 or 1:1" /></div>
              <div class="field"><label>X offset</label><input v-model.number="current.x" type="number" min="0" class="input" /></div>
              <div class="field"><label>Y offset</label><input v-model.number="current.y" type="number" min="0" class="input" /></div>
              <div class="field"><label>Output format</label><select v-model="current.format" class="select"><template v-if="op === 'crop_image'"><option v-for="format in ['png', 'jpg', 'jpeg', 'webp']" :key="format">{{ format }}</option></template><template v-else><option v-for="format in formats" :key="format">{{ format }}</option></template></select></div>
              <div class="field" v-if="op === 'crop_video'"><label>Video codec</label><select v-model="current.video_codec" class="select"><option v-for="codec in videoCodecs" :key="codec">{{ codec }}</option></select></div>
              <div class="field" v-if="op === 'crop_video'"><label>CRF</label><input v-model.number="current.crf" type="number" class="input" /></div>
              <div class="field" v-if="op === 'crop_image'"><label>Quality (2 best)</label><input v-model.number="current.quality" type="number" min="2" max="31" class="input" /></div>
            </div>
            <div v-if="['crop_video', 'crop_image'].includes(op)" class="switch-row">
              <div><div class="switch-label">Center crop</div><div class="switch-hint">Ignore offsets and center the rectangle.</div></div>
              <button class="switch" :class="{ on: current.center }" @click="current.center = !current.center" />
            </div>

            <template v-if="op === 'scale'">
              <div class="form-grid cols-3">
                <div class="field"><label>Width</label><input v-model.number="current.width" type="number" class="input" /><span class="hint">Use -2 to keep the ratio.</span></div>
                <div class="field"><label>Height</label><input v-model.number="current.height" type="number" class="input" /></div>
                <div class="field"><label>Mode</label><select v-model="current.mode" class="select"><option value="fit">fit — letterbox</option><option value="fill">fill — crop</option><option value="stretch">stretch — distort</option></select></div>
                <div class="field"><label>Pad color</label><input v-model="current.pad_color" class="input" placeholder="black or 0x101018" /></div>
                <div class="field"><label>Scaling flags</label><select v-model="current.flags" class="select"><option>lanczos</option><option>bicubic</option><option>bilinear</option><option>neighbor</option><option>area</option></select></div>
                <div class="field"><label>CRF</label><input v-model.number="current.crf" type="number" class="input" /></div>
              </div>
              <div class="switch-row"><div><div class="switch-label">Pad to exact size</div><div class="switch-hint">Adds bars when using fit mode.</div></div><button class="switch" :class="{ on: current.pad }" @click="current.pad = !current.pad" /></div>
              <div class="switch-row"><div><div class="switch-label">Never upscale</div><div class="switch-hint">Keeps the source size when it is smaller.</div></div><button class="switch" :class="{ on: current.no_upscale }" @click="current.no_upscale = !current.no_upscale" /></div>
            </template>

            <template v-if="op === 'rotate'">
              <div class="form-grid cols-3">
                <div class="field">
                  <label>Angle</label>
                  <div class="input-group">
                    <input v-model.number="current.angle" type="number" class="input" />
                    <button v-for="angle in [90, 180, 270]" :key="angle" class="btn btn-sm" @click="current.angle = angle">{{ angle }}°</button>
                  </div>
                </div>
                <div class="field"><label>Fill color</label><input v-model="current.fill_color" class="input" placeholder="black" /></div>
                <div class="field"><label>Video codec</label><select v-model="current.video_codec" class="select"><option v-for="codec in videoCodecs" :key="codec">{{ codec }}</option></select></div>
              </div>
              <div class="row">
                <button class="btn btn-sm" :class="{ 'btn-primary': current.flip_h }" @click="current.flip_h = !current.flip_h">Flip horizontal</button>
                <button class="btn btn-sm" :class="{ 'btn-primary': current.flip_v }" @click="current.flip_v = !current.flip_v">Flip vertical</button>
              </div>
            </template>

            <template v-if="op === 'concat'">
              <div class="field">
                <label>Clips in order <span class="muted small">{{ current.files.length }} selected</span></label>
                <div class="stack" style="gap: 6px">
                  <div v-for="(path, index) in current.files" :key="`${path}-${index}`" class="clip-row">
                    <span class="badge">{{ index + 1 }}</span>
                    <span class="small mono truncate grow">{{ path }}</span>
                    <button class="icon-btn" :disabled="index === 0" title="Move up" @click="moveConcat(index, -1)"><ChevronUp :size="14" /></button>
                    <button class="icon-btn" :disabled="index === current.files.length - 1" title="Move down" @click="moveConcat(index, 1)"><ChevronDown :size="14" /></button>
                    <button class="icon-btn" title="Remove" @click="removeConcat(index)"><Trash2 :size="14" /></button>
                  </div>
                  <div v-if="!current.files.length" class="small muted">No clips yet.</div>
                </div>
                <button class="btn btn-sm" style="align-self: flex-start" @click="openPicker('concat')"><Plus :size="13" /> Add clip</button>
              </div>
              <div class="form-grid cols-3">
                <div class="field"><label>Transition</label><select v-model="current.transition" class="select"><option value="">Hard cut</option><option v-for="transition in ['fade', 'fadeblack', 'fadewhite', 'wipeleft', 'wiperight', 'slideleft', 'slideright', 'dissolve', 'circleopen', 'pixelize', 'radial']" :key="transition">{{ transition }}</option></select></div>
                <div class="field"><label>Transition duration</label><input v-model.number="current.transition_duration" type="number" step="0.05" min="0.05" max="10" class="input" /></div>
                <div class="field"><label>Container</label><select v-model="current.format" class="select"><option v-for="format in formats" :key="format">{{ format }}</option></select></div>
                <div class="field"><label>Video codec</label><select v-model="current.video_codec" class="select"><option v-for="codec in videoCodecs" :key="codec">{{ codec }}</option></select></div>
                <div class="field"><label>Audio codec</label><select v-model="current.audio_codec" class="select"><option v-for="codec in audioCodecs" :key="codec">{{ codec }}</option></select></div>
                <div class="field"><label>CRF</label><input v-model.number="current.crf" type="number" class="input" /></div>
              </div>
              <div class="switch-row"><div><div class="switch-label">Stream copy when possible</div><div class="switch-hint">Disable for xfade transitions or mixed sources.</div></div><button class="switch" :class="{ on: current.copy }" @click="current.copy = !current.copy" /></div>
              <div class="switch-row"><div><div class="switch-label">Force re-encode</div><div class="switch-hint">Overrides stream copy.</div></div><button class="switch" :class="{ on: current.reencode }" @click="current.reencode = !current.reencode" /></div>
            </template>

            <template v-if="op === 'overlay'">
              <div class="form-grid cols-3">
                <div class="field"><label>Overlay mode</label><select v-model="current.mode" class="select"><option value="image">Image</option><option value="watermark">Watermark</option><option value="text">Styled text</option></select></div>
                <div class="field"><label>Position</label><select v-model="current.position" class="select"><option v-for="position in ['top-left', 'top', 'top-right', 'bottom-left', 'center', 'bottom-right', 'bottom', 'custom']" :key="position">{{ position }}</option></select></div>
                <div class="field"><label>Margin</label><input v-model.number="current.margin" type="number" class="input" /></div>
              </div>
              <div class="field" v-if="current.mode !== 'text'">
                <label>Overlay image</label>
                <div class="input-group">
                  <input v-model="current.overlay_path" class="input mono" placeholder="images/logo.png" />
                  <button class="btn btn-sm" @click="openPicker('overlay')">Browse</button>
                </div>
              </div>
              <div class="form-grid cols-3" v-if="current.mode === 'text'">
                <div class="field"><label>Text</label><input v-model="current.text" class="input" /></div>
                <div class="field"><label>Font</label><select v-model="current.font" class="select"><option>DejaVu Sans</option><option>DejaVu Serif</option><option>Noto Sans</option><option>Liberation Sans</option></select></div>
                <div class="field"><label>Font size</label><input v-model.number="current.font_size" type="number" class="input" /></div>
                <div class="field"><label>Font color</label><input v-model="current.font_color" class="input" placeholder="#ffffff" /></div>
                <div class="field"><label>Border width</label><input v-model.number="current.border_width" type="number" class="input" /></div>
                <div class="field"><label>Border color</label><input v-model="current.border_color" class="input" /></div>
              </div>
              <div class="form-grid cols-3">
                <div class="field"><label>Opacity</label><input v-model.number="current.opacity" type="range" min="0" max="1" step="0.01" /><span class="hint mono">{{ Number(current.opacity).toFixed(2) }}</span></div>
                <div class="field"><label>Overlay scale</label><input v-model="current.scale" class="input" placeholder="18% or 320" /></div>
                <div class="field"><label>Start / end</label><div class="input-group"><input v-model.number="current.start" type="number" class="input" placeholder="0" /><input v-model.number="current.end" type="number" class="input" placeholder="30" /></div><span class="hint">Seconds; end may be empty.</span></div>
              </div>
              <div class="form-grid cols-3" v-if="current.mode === 'text'">
                <div class="field"><label>Box</label><button class="switch" :class="{ on: current.box }" style="align-self: flex-start" @click="current.box = !current.box" /></div>
                <div class="field"><label>Box color</label><input v-model="current.box_color" class="input" placeholder="black@0.45" /></div>
                <div class="field"><label>Shadow</label><input v-model.number="current.shadow" type="number" class="input" /></div>
              </div>
            </template>

            <template v-if="op === 'subtitles'">
              <div class="field">
                <label>Subtitle file</label>
                <div class="input-group">
                  <input v-model="current.subtitle_path" class="input mono" placeholder="subtitles/lyrics.srt" />
                  <button class="btn btn-sm" @click="openPicker('subtitle')">Browse</button>
                </div>
              </div>
              <div class="form-grid cols-3">
                <div class="field"><label>Font</label><select v-model="current.font" class="select"><option>DejaVu Sans</option><option>DejaVu Serif</option><option>Noto Sans</option><option>Liberation Sans</option></select></div>
                <div class="field"><label>Font size</label><input v-model.number="current.font_size" type="number" class="input" /></div>
                <div class="field"><label>Position</label><select v-model="current.position" class="select"><option value="bottom">bottom</option><option value="center">center</option><option value="top">top</option></select></div>
                <div class="field"><label>Primary color</label><input v-model="current.color" class="input" placeholder="#ffffff" /></div>
                <div class="field"><label>Outline color</label><input v-model="current.outline_color" class="input" /></div>
                <div class="field"><label>Outline</label><input v-model.number="current.outline" type="number" step="0.1" class="input" /></div>
                <div class="field"><label>Shadow</label><input v-model.number="current.shadow" type="number" step="0.1" class="input" /></div>
                <div class="field"><label>Vertical margin</label><input v-model.number="current.margin_v" type="number" class="input" /></div>
                <div class="field"><label>Left / right margin</label><div class="input-group"><input v-model.number="current.margin_l" type="number" class="input" /><input v-model.number="current.margin_r" type="number" class="input" /></div></div>
              </div>
              <div class="row">
                <button class="btn btn-sm" :class="{ 'btn-primary': current.bold }" @click="current.bold = !current.bold">Bold</button>
                <button class="btn btn-sm" :class="{ 'btn-primary': current.italic }" @click="current.italic = !current.italic">Italic</button>
                <button class="btn btn-sm" :class="{ 'btn-primary': current.underline }" @click="current.underline = !current.underline">Underline</button>
                <button class="btn btn-sm" :class="{ 'btn-primary': current.strikeout }" @click="current.strikeout = !current.strikeout">Strikeout</button>
              </div>
              <div class="alert warn">This build burns subtitles into the picture. Soft subtitle tracks are not exposed by the contract, so the burn switch stays on.</div>
            </template>

            <template v-if="op === 'frames'">
              <div class="form-grid cols-3">
                <div class="field"><label>Mode</label><select v-model="current.frames_mode" class="select"><option value="fps">Fixed frame rate</option><option value="timestamps">Explicit timestamps</option></select></div>
                <div class="field" v-if="current.frames_mode === 'fps'"><label>Frames per second</label><input v-model.number="current.fps" type="number" step="0.01" class="input" /></div>
                <div class="field" v-else><label>Timestamps (seconds)</label><input v-model="current.timestamps" class="input mono" placeholder="0, 5, 12.5" /></div>
                <div class="field"><label>Output format</label><select v-model="current.format" class="select"><option>jpg</option><option>jpeg</option><option>png</option><option>webp</option></select></div>
                <div class="field"><label>Start</label><input v-model.number="current.start" type="number" class="input" /></div>
                <div class="field"><label>Duration</label><input v-model.number="current.duration" type="number" class="input" /></div>
                <div class="field"><label>Width</label><input v-model.number="current.width" type="number" class="input" /></div>
                <div class="field"><label>Height</label><input v-model.number="current.height" type="number" class="input" /></div>
                <div class="field"><label>Max frames</label><input v-model.number="current.max_frames" type="number" class="input" /></div>
              </div>
            </template>

            <div v-if="op === 'gif'" class="form-grid cols-3">
              <div class="field"><label>Start</label><input v-model.number="current.start" type="number" class="input" /></div>
              <div class="field"><label>Duration</label><input v-model.number="current.duration" type="number" class="input" /></div>
              <div class="field"><label>FPS</label><input v-model.number="current.fps" type="number" class="input" /></div>
              <div class="field"><label>Width</label><input v-model.number="current.width" type="number" class="input" /></div>
              <div class="field"><label>Palette colors</label><input v-model.number="current.max_colors" type="number" min="2" max="256" class="input" /></div>
              <div class="field"><label>Dither</label><select v-model="current.dither" class="select"><option>bayer</option><option>sierra2_4a</option><option>none</option></select></div>
              <div class="field"><label>Loop</label><input v-model.number="current.loop" type="number" class="input" placeholder="0 = infinite" /></div>
            </div>
            <div v-if="op === 'gif'" class="switch-row"><div><div class="switch-label">Optimized palette</div><div class="switch-hint">Generate a palette before the GIF pass.</div></div><button class="switch" :class="{ on: current.palette }" @click="current.palette = !current.palette" /></div>

            <template v-if="['merge', 'replace_audio'].includes(op)">
              <div class="field">
                <label>Audio file</label>
                <div class="input-group">
                  <input v-model="current.audio_path" class="input mono" placeholder="music/track.wav" />
                  <button class="btn btn-sm" @click="openPicker('audio')">Browse</button>
                </div>
              </div>
              <div class="form-grid cols-3">
                <div class="field"><label>New audio volume</label><input v-model.number="current.new_volume" type="number" step="0.05" min="0" max="4" class="input" /></div>
                <div class="field"><label>Original audio volume</label><input v-model.number="current.original_volume" type="number" step="0.05" min="0" max="4" class="input" /></div>
                <div class="field"><label>Audio codec</label><select v-model="current.audio_codec" class="select"><option v-for="codec in audioCodecs" :key="codec">{{ codec }}</option></select></div>
                <div class="field"><label>Audio bitrate</label><input v-model="current.audio_bitrate" class="input" /></div>
                <div class="field"><label>Container</label><select v-model="current.format" class="select"><option v-for="format in ['mp4', 'mkv', 'mov', 'webm']" :key="format">{{ format }}</option></select></div>
              </div>
              <div class="switch-row" v-if="op === 'merge'"><div><div class="switch-label">Replace original audio</div><div class="switch-hint">Turn off to mix both tracks together.</div></div><button class="switch" :class="{ on: current.replace }" @click="current.replace = !current.replace" /></div>
              <div class="switch-row" v-if="op === 'replace_audio'"><div><div class="switch-label">Mute original audio</div><div class="switch-hint">Turn off to mix the original back in.</div></div><button class="switch" :class="{ on: current.mute_original }" @click="current.mute_original = !current.mute_original" /></div>
              <div class="switch-row"><div><div class="switch-label">Stop at shortest</div><div class="switch-hint">End when either input ends.</div></div><button class="switch" :class="{ on: current.shortest }" @click="current.shortest = !current.shortest" /></div>
              <div class="switch-row"><div><div class="switch-label">Copy video stream</div><div class="switch-hint">Avoid re-encoding the picture.</div></div><button class="switch" :class="{ on: current.copy_video }" @click="current.copy_video = !current.copy_video" /></div>
            </template>

            <template v-if="op === 'speed'">
              <div class="form-grid cols-3">
                <div class="field"><label>Speed factor</label><input v-model.number="current.factor" type="number" step="0.05" min="0.1" max="100" class="input" /><span class="hint">1.25 = 25% faster, 0.8 = slower.</span></div>
                <div class="field"><label>Video factor</label><input v-model.number="current.video_factor" type="number" step="0.05" class="input" placeholder="Same as factor" /></div>
                <div class="field"><label>Audio factor</label><input v-model.number="current.audio_factor" type="number" step="0.05" class="input" placeholder="Same as factor" /></div>
                <div class="field"><label>Video codec</label><select v-model="current.video_codec" class="select"><option v-for="codec in videoCodecs" :key="codec">{{ codec }}</option></select></div>
                <div class="field"><label>CRF</label><input v-model.number="current.crf" type="number" class="input" /></div>
                <div class="field"><label>Audio codec</label><select v-model="current.audio_codec" class="select"><option v-for="codec in audioCodecs" :key="codec">{{ codec }}</option></select></div>
              </div>
              <div class="switch-row"><div><div class="switch-label">Keep audio pitch</div><div class="switch-hint">Uses the atempo chain instead of shifting pitch with the video.</div></div><button class="switch" :class="{ on: current.pitch_correction }" @click="current.pitch_correction = !current.pitch_correction" /></div>
            </template>

            <template v-if="op === 'volume'">
              <div class="form-grid cols-3">
                <div class="field"><label>Gain (dB)</label><input v-model.number="current.gain_db" type="number" step="0.5" class="input" /></div>
                <div class="field"><label>Linear gain</label><input v-model.number="current.gain" type="number" step="0.05" class="input" placeholder="Optional, overrides dB" /></div>
                <div class="field"><label>Audio codec</label><select v-model="current.audio_codec" class="select"><option v-for="codec in audioCodecs" :key="codec">{{ codec }}</option></select></div>
                <div class="field"><label>Audio bitrate</label><input v-model="current.audio_bitrate" class="input" /></div>
                <div class="field"><label>Container</label><select v-model="current.format" class="select"><option v-for="format in ['mp4', 'mkv', 'mov', 'wav', 'mp3', 'flac']" :key="format">{{ format }}</option></select></div>
              </div>
              <div class="switch-row"><div><div class="switch-label">Loudnorm instead of gain</div><div class="switch-hint">Run one-pass EBU R128 normalization.</div></div><button class="switch" :class="{ on: current.normalize }" @click="current.normalize = !current.normalize" /></div>
              <div class="form-grid cols-3" v-if="current.normalize">
                <div class="field"><label>Target LUFS</label><input v-model.number="current.target_lufs" type="number" class="input" /></div>
                <div class="field"><label>True peak</label><input v-model.number="current.true_peak" type="number" step="0.1" class="input" /></div>
                <div class="field"><label>Loudness range</label><input v-model.number="current.lra" type="number" class="input" /></div>
              </div>
            </template>

            <template v-if="op === 'normalize'">
              <div class="form-grid cols-3">
                <div class="field"><label>Target LUFS</label><input v-model.number="current.target_lufs" type="number" class="input" /></div>
                <div class="field"><label>True peak (dBTP)</label><input v-model.number="current.true_peak" type="number" step="0.1" class="input" /></div>
                <div class="field"><label>Loudness range</label><input v-model.number="current.lra" type="number" class="input" /></div>
                <div class="field"><label>Sample rate</label><select v-model.number="current.sample_rate" class="select"><option v-for="rate in [44100, 48000, 88200, 96000]" :key="rate" :value="rate">{{ rate }} Hz</option></select></div>
                <div class="field"><label>Output format</label><select v-model="current.format" class="select"><option v-for="format in ['wav', 'mp3', 'flac', 'm4a', 'opus', 'ogg', 'mp4', 'mkv']" :key="format">{{ format }}</option></select></div>
                <div class="field"><label>Audio bitrate</label><input v-model="current.audio_bitrate" class="input" /></div>
              </div>
              <div class="switch-row"><div><div class="switch-label">Dual mono</div><div class="switch-hint">Treat a mono source as dual mono.</div></div><button class="switch" :class="{ on: current.dual_mono }" @click="current.dual_mono = !current.dual_mono" /></div>
              <div class="switch-row"><div><div class="switch-label">Keep video stream</div><div class="switch-hint">Normalize only the audio and remux the existing picture.</div></div><button class="switch" :class="{ on: current.keep_video }" @click="current.keep_video = !current.keep_video" /></div>
              <div class="alert">Two-pass loudnorm measures the file first, then applies the measured values in a second encode.</div>
            </template>

            <div v-if="op === 'thumbnail'" class="form-grid cols-3">
              <div class="field"><label>Timestamp</label><input v-model.number="current.time" type="number" step="0.1" class="input" /><span class="hint">Seconds</span></div>
              <div class="field"><label>Width</label><input v-model.number="current.width" type="number" class="input" /></div>
              <div class="field"><label>Height</label><input v-model.number="current.height" type="number" class="input" placeholder="Auto" /></div>
              <div class="field"><label>Format</label><select v-model="current.format" class="select"><option>jpg</option><option>jpeg</option><option>png</option><option>webp</option></select></div>
              <div class="field"><label>Quality (2 best)</label><input v-model.number="current.quality" type="number" min="2" max="31" class="input" /></div>
            </div>

            <template v-if="op === 'split'">
              <div class="form-grid cols-3">
                <div class="field"><label>Segment duration</label><input v-model.number="current.duration" type="number" min="1" class="input" /><span class="hint">Seconds per segment</span></div>
                <div class="field"><label>Output pattern</label><input v-model="current.segment_pattern" class="input mono" placeholder="segment_%03d.mp4" /><span class="hint">Join to the output folder above.</span></div>
                <div class="field"><label>Video codec</label><select v-model="current.video_codec" class="select"><option v-for="codec in videoCodecs" :key="codec">{{ codec }}</option></select></div>
                <div class="field"><label>Audio codec</label><select v-model="current.audio_codec" class="select"><option v-for="codec in audioCodecs" :key="codec">{{ codec }}</option></select></div>
                <div class="field"><label>CRF</label><input v-model.number="current.crf" type="number" class="input" /></div>
                <div class="field"><label>Container</label><select v-model="current.format" class="select"><option v-for="format in ['mp4', 'mkv', 'mov', 'ts', 'webm']" :key="format">{{ format }}</option></select></div>
              </div>
              <div class="switch-row"><div><div class="switch-label">Stream copy</div><div class="switch-hint">Fast segmentation, cuts at keyframes.</div></div><button class="switch" :class="{ on: current.copy }" @click="current.copy = !current.copy" /></div>
              <div class="switch-row"><div><div class="switch-label">Reset timestamps</div><div class="switch-hint">Every segment starts at zero.</div></div><button class="switch" :class="{ on: current.reset_timestamps }" @click="current.reset_timestamps = !current.reset_timestamps" /></div>
            </template>

            <template v-if="op === 'raw'">
              <div class="alert warn" style="display: flex; gap: 9px; align-items: flex-start">
                <Terminal :size="15" style="flex: none; margin-top: 1px" />
                <div>
                  <strong>Advanced operation.</strong> One argument per line, without a shell. Arguments are validated as strings on the server, the executable is restricted to ffmpeg, and the output path is appended when it is not already present. Never paste untrusted values.
                </div>
              </div>
              <div class="field">
                <label>argv <span class="muted small">{{ rawArgv.length }} arguments</span></label>
                <textarea v-model="current.argv" class="textarea mono" style="min-height: 170px" spellcheck="false" />
                <span class="hint">Example: <span class="mono">-c:v</span> on one line and <span class="mono">libx264</span> on the next. Spaces inside a line are preserved in that argument.</span>
              </div>
              <div class="row">
                <span :class="rawHasInput ? 'chip success' : 'chip warn'"><CheckCircle2 :size="11" /> {{ rawHasInput ? "-i present" : "input path will be prepended" }}</span>
                <span v-if="rawHasShellTokens" class="chip warn">Shell characters are literal</span>
                <span class="chip">{{ rawArgv.length }} args</span>
              </div>
              <CodeBlock :code="rawPreview" label="Effective command (no shell)" />
              <div class="field"><label>Timeout (seconds)</label><input v-model.number="current.timeout" type="number" min="1" max="86400" class="input" /></div>
            </template>

            <details class="extra-box">
              <summary><span><Code2 :size="13" /> Extra options</span><span class="small muted">Advanced JSON</span></summary>
              <div class="field" style="margin-top: 9px">
                <label>Additional options object</label>
                <textarea v-model="current.extra_options" class="textarea mono" style="min-height: 70px" spellcheck="false" placeholder='{"movflags_faststart": true}' />
                <span class="hint">Merged after the form values. Must be a JSON object; invalid JSON blocks the run.</span>
              </div>
            </details>
          </div>

          <div class="panel-footer" style="justify-content: space-between; flex-wrap: wrap">
            <div class="row" style="gap: 7px">
              <span class="chip">{{ op }}</span>
              <span class="chip">{{ effectiveOutput || "output path pending" }}</span>
            </div>
            <div class="row">
              <button class="btn" :disabled="busySync || busyJob" @click="runSync">
                <Loader2 v-if="busySync" :size="14" class="spin" />
                <Play v-else :size="14" />
                {{ busySync ? "Running…" : "Run sync" }}
              </button>
              <button class="btn btn-primary" :disabled="busyJob || busySync" @click="runJob">
                <Loader2 v-if="busyJob" :size="14" class="spin" />
                <Sparkles v-else :size="14" />
                {{ busyJob ? "Submitting…" : "Run as job" }}
              </button>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>Probe</h3>
              <p>Inspect streams, codecs, resolution and loudness metadata before processing.</p>
            </div>
            <span class="chip"><Gauge :size="11" /> ffprobe</span>
          </div>
          <div class="panel-body stack">
            <div class="form-grid">
              <div class="field">
                <label>File to probe</label>
                <div class="input-group">
                  <input v-model="probePath" class="input mono" placeholder="video/my-clip.mp4" />
                  <button class="btn btn-sm" @click="openPicker('probe')">Browse</button>
                  <button class="btn btn-sm btn-primary" :disabled="probeLoading" @click="probe">
                    <Loader2 v-if="probeLoading" :size="13" class="spin" />
                    <Gauge v-else :size="13" />
                    Probe
                  </button>
                </div>
              </div>
            </div>

            <template v-if="probeResult">
              <div class="row" style="gap: 8px">
                <span class="chip success">{{ probeResult.format_name || "media" }}</span>
                <span class="chip"><Clock :size="11" /> {{ formatDuration(probeResult.duration) }}</span>
                <span class="chip">{{ formatBytes(probeResult.size || 0) }}</span>
                <span class="chip">{{ bitrateLabel(probeResult.bit_rate) }}</span>
                <span class="chip">{{ probeStreams.length }} streams</span>
              </div>
              <div style="overflow-x: auto">
                <table class="table">
                  <thead>
                    <tr><th>#</th><th>Type</th><th>Codec</th><th>Resolution</th><th>FPS</th><th>Sample rate</th><th>Channels</th><th>Bitrate</th><th>Duration</th></tr>
                  </thead>
                  <tbody>
                    <tr v-for="stream in probeStreams" :key="stream.index">
                      <td class="mono">{{ stream.index }}</td>
                      <td><span class="badge">{{ stream.type }}</span></td>
                      <td class="mono">{{ stream.codec || "—" }}</td>
                      <td>{{ streamResolution(stream) }}</td>
                      <td>{{ stream.fps ?? "—" }}</td>
                      <td>{{ stream.sample_rate ? `${stream.sample_rate} Hz` : "—" }}</td>
                      <td>{{ stream.channels ?? "—" }}</td>
                      <td>{{ bitrateLabel(stream.bit_rate) }}</td>
                      <td>{{ formatDuration(stream.duration ?? probeResult.duration) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div class="row-between">
                <span class="small muted">Raw ffprobe payload</span>
                <button class="btn btn-sm btn-ghost" @click="showProbeJson = !showProbeJson"><Code2 :size="12" /> {{ showProbeJson ? "Hide" : "Show" }} JSON</button>
              </div>
              <CodeBlock v-if="showProbeJson" :code="JSON.stringify(probeResult, null, 2)" label="ffprobe JSON" />
            </template>
            <EmptyState v-else :icon="Gauge" title="Nothing probed yet" message="Pick a video, audio or image file and run ffprobe to see every stream before choosing an operation." />
          </div>
        </section>

        <section class="panel" v-if="activeJob || result">
          <div class="panel-head">
            <div>
              <h3>Latest run</h3>
              <p>{{ resultMessage || "Waiting for output" }}</p>
            </div>
            <span class="chip" :class="activeJob?.status === 'completed' || syncResult ? 'success' : 'warn'">
              {{ syncResult ? "synchronous" : activeJob?.status || "result" }}
            </span>
          </div>
          <div class="panel-body stack">
            <JobCard
              v-if="activeJob"
              :job="activeJob"
              @cancel="cancelJob"
              @retry="retryJob"
              @remove="removeJob"
            />
            <div v-if="outputSummary" class="result-summary">
              <div class="result-stat"><span>Output</span><strong class="mono">{{ outputSummary.path || effectiveOutput }}</strong></div>
              <div class="result-stat"><span>Picture</span><strong>{{ outputSummary.width ? `${outputSummary.width} × ${outputSummary.height}` : outputSummary.kind || "—" }}</strong></div>
              <div class="result-stat"><span>Codec</span><strong class="mono">{{ outputSummary.video_codec || outputSummary.audio_codec || "—" }}</strong></div>
              <div class="result-stat"><span>Duration</span><strong>{{ formatDuration(outputSummary.duration) }}</strong></div>
              <div class="result-stat"><span>Size</span><strong>{{ formatBytes(outputSummary.size || 0) }}</strong></div>
              <div class="result-stat"><span>Elapsed</span><strong>{{ result?.data?.elapsed_seconds ? `${result.data.elapsed_seconds}s` : "—" }}</strong></div>
            </div>
            <div v-if="resultFiles.length" class="stack" style="gap: 7px">
              <div v-for="file in resultFiles" :key="file.path" class="result-file">
                <span class="file-icon">
                  <FileAudio v-if="file.kind === 'audio'" :size="15" />
                  <FileImage v-else-if="file.kind === 'image'" :size="15" />
                  <FileVideo v-else-if="file.kind === 'video'" :size="15" />
                  <Download v-else :size="15" />
                </span>
                <span class="grow" style="min-width: 0">
                  <span class="small strong truncate" style="display: block">{{ file.name || basename(file.path) }}</span>
                  <span class="small muted mono truncate" style="display: block">{{ file.path }}</span>
                </span>
                <span class="small muted nowrap">{{ file.size ? formatBytes(file.size) : "" }}</span>
                <a class="btn btn-sm" :href="downloadUrl(file.path)" target="_blank" rel="noopener"><Download :size="12" /> Download</a>
              </div>
            </div>
            <div v-if="resultWarnings.length" class="alert warn">
              <div v-for="warning in resultWarnings" :key="warning">· {{ warning }}</div>
            </div>
            <div v-if="!activeJob && result" class="row-between small muted">
              <span>Synchronous result {{ syncResult?.job_id ? `· ${syncResult.job_id}` : "" }}</span>
              <span>{{ result?.data?.operation || op }}</span>
            </div>
          </div>
        </section>
      </main>

      <aside class="stack side-stack">
        <section class="panel" v-if="activeJob">
          <div class="panel-head">
            <div><h3>Latest job</h3><p>{{ activeJob.message || activeJob.stage || activeJob.action }}</p></div>
            <span class="badge" :class="activeJob.status">{{ activeJob.status }}</span>
          </div>
          <div class="panel-body">
            <JobCard :job="activeJob" compact @cancel="cancelJob" @retry="retryJob" @remove="removeJob" />
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><h3>Runtime</h3><p>Catalog and image capabilities</p></div>
            <span class="badge success">ready</span>
          </div>
          <div class="panel-body stack" style="gap: 11px">
            <div class="row-between small"><span class="muted">FFmpeg</span><span class="mono strong">{{ ffmpegVersion }}</span></div>
            <div class="row-between small"><span class="muted">Build</span><span>{{ serviceVersion }}</span></div>
            <div class="row-between small"><span class="muted">Operations</span><span>{{ operationCount }}</span></div>
            <div>
              <div class="label" style="margin-bottom: 6px">Video codecs</div>
              <div class="tag-list"><span v-for="codec in videoCodecs.slice(0, 8)" :key="codec" class="chip">{{ codec }}</span></div>
            </div>
            <div>
              <div class="label" style="margin-bottom: 6px">Audio codecs</div>
              <div class="tag-list"><span v-for="codec in audioCodecs.slice(0, 8)" :key="codec" class="chip">{{ codec }}</span></div>
            </div>
            <div>
              <div class="label" style="margin-bottom: 6px">Containers</div>
              <div class="tag-list"><span v-for="format in formats.slice(0, 12)" :key="format" class="chip">{{ format }}</span></div>
            </div>
            <div class="alert">
              Jobs write to <span class="mono">ffmpeg/&lt;job_id&gt;/</span> by default. Explicit output paths are resolved inside the shared files root.
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><h3>Active processes</h3><p>Live ffmpeg workers</p></div>
            <span class="chip">{{ ffmpegActiveJobs.length + activeProcesses.length }}</span>
          </div>
          <div class="panel-body stack" style="gap: 8px">
            <div v-for="job in ffmpegActiveJobs" :key="job.id" class="process-row">
              <span class="dot busy" />
              <span class="grow" style="min-width: 0">
                <span class="small strong truncate" style="display: block">{{ job.title }}</span>
                <span class="small muted truncate" style="display: block">{{ job.stage || job.message || job.action }}</span>
              </span>
              <span class="small mono">{{ Math.round(job.progress) }}%</span>
            </div>
            <div v-for="process in activeProcesses" :key="process.job_id" class="process-row">
              <span class="dot" :class="process.progress === 100 ? 'online' : 'busy'" />
              <span class="grow" style="min-width: 0">
                <span class="small strong truncate" style="display: block">{{ process.operation || "ffmpeg" }}</span>
                <span class="small muted truncate" style="display: block">{{ process.job_id }} · {{ process.elapsed || "running" }}</span>
              </span>
              <span class="small mono">{{ process.progress ?? "—" }}%</span>
            </div>
            <div v-if="!ffmpegActiveJobs.length && !activeProcesses.length" class="small muted">No active ffmpeg process. The queue is idle.</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><h3>Job history</h3><p>This component only</p></div>
            <span class="chip">{{ history.length }}</span>
          </div>
          <div class="panel-body" style="padding: 8px">
            <div v-for="job in history" :key="job.id" class="history-row" @click="activeJobId = job.id">
              <span class="dot" :class="job.status === 'completed' ? 'online' : job.status === 'failed' ? 'offline' : job.status === 'running' ? 'busy' : ''" />
              <span class="grow" style="min-width: 0">
                <span class="small strong truncate" style="display: block">{{ job.title }}</span>
                <span class="small muted truncate" style="display: block">{{ job.message || job.action }} · {{ relativeTime(job.created_at) }}</span>
              </span>
              <span class="badge" :class="job.status">{{ job.status }}</span>
            </div>
            <div v-if="!history.length" class="small muted" style="padding: 10px">No FFmpeg jobs yet.</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div><h3>Recent outputs</h3><p>Shared file tree</p></div><span class="chip"><FileVideo :size="11" /></span></div>
          <div class="panel-body stack" style="gap: 7px">
            <div v-for="file in resultFiles.slice(0, 3)" :key="`side-${file.path}`" class="row-between small">
              <span class="truncate mono">{{ file.name || basename(file.path) }}</span>
              <a class="icon-btn" :href="downloadUrl(file.path)"><Download :size="14" /></a>
            </div>
            <div v-if="!resultFiles.length" class="small muted">Completed outputs will be listed here.</div>
          </div>
        </section>
      </aside>
    </div>

    <FilePicker v-model="inputPicker" :kind="inputKind" :start-path="initialDir" title="Choose the input file" @selected="onInputSelected" />
    <FilePicker v-model="probePicker" kind="all" :start-path="initialDir" title="Choose a file to probe" @selected="probeSelected" />
    <FilePicker v-model="concatPicker" kind="video" title="Add a clip to the concat list" @selected="addConcatFile" />
    <FilePicker v-model="overlayPicker" kind="image" title="Choose an overlay image" @selected="setOverlayPath" />
    <FilePicker v-model="subtitlePicker" kind="subtitle" title="Choose a subtitle file" @selected="setSubtitlePath" />
    <FilePicker v-model="audioPicker" kind="audio" title="Choose replacement audio" @selected="setAudioPath" />
  </div>
</template>

<style scoped>
.workbench {
  display: grid;
  grid-template-columns: 252px minmax(0, 1fr) 330px;
  gap: 16px;
  align-items: start;
}
.ops-panel {
  position: sticky;
  top: 78px;
}
.ops-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 5px;
}
.ops-btn {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 7px 8px;
  font-size: 10.5px;
}
.ops-category {
  padding-left: 21px;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  opacity: 0.72;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
}
.form-grid.cols-3 {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
.extra-box {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  background: rgba(8, 10, 15, 0.3);
}
.extra-box summary {
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  list-style: none;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--muted);
}
.extra-box summary span:first-child {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.extra-box summary::-webkit-details-marker { display: none; }
.clip-row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 8px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.35);
}
.result-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}
.result-stat {
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.3);
  min-width: 0;
}
.result-stat span {
  display: block;
  font-size: 9.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted-2);
  margin-bottom: 4px;
}
.result-stat strong {
  display: block;
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.result-file {
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 9px;
  background: rgba(8, 10, 15, 0.3);
}
.process-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.25);
}
.history-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-radius: 9px;
  cursor: pointer;
}
.history-row:hover { background: rgba(255, 255, 255, 0.035); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1380px) {
  .workbench { grid-template-columns: 226px minmax(0, 1fr) 300px; }
  .form-grid.cols-3 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 1100px) {
  .workbench { grid-template-columns: 1fr; }
  .ops-panel { position: static; }
  .ops-grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); }
  .side-stack { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
}
@media (max-width: 720px) {
  .form-grid, .form-grid.cols-3 { grid-template-columns: 1fr; }
  .result-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
