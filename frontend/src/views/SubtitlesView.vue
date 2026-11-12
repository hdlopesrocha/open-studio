<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import {
  AlignLeft,
  AudioLines,
  Captions,
  Check,
  ChevronRight,
  Clock3,
  Download,
  FileAudio,
  FileText,
  Gauge,
  Languages,
  Loader2,
  Merge,
  Plus,
  RefreshCw,
  Scissors,
  Search,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Wand2,
  X,
  Zap,
} from "lucide-vue-next";
import type { Job } from "@/lib/types";
import { DEMO } from "@/lib/types";
import { demoCues, demoLyrics, demoSubtitlesCatalog } from "@/lib/demo";
import { api, downloadUrl, formatBytes, formatDuration, relativeTime } from "@/lib/api";
import { useJobsStore } from "@/stores/jobs";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import FilePicker from "@/components/FilePicker.vue";
import AudioPlayer from "@/components/AudioPlayer.vue";
import JobCard from "@/components/JobCard.vue";
import CodeBlock from "@/components/CodeBlock.vue";
import EmptyState from "@/components/EmptyState.vue";
import TabsBar from "@/components/TabsBar.vue";

const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false });

const jobs = useJobsStore();
const toasts = useToastStore();

const LANGUAGE_NAMES: Record<string, string> = {
  auto: "Auto-detect",
  pt: "Portuguese",
  en: "English",
  es: "Spanish",
  fr: "French",
  de: "German",
  it: "Italian",
  ja: "Japanese",
  zh: "Chinese",
  ko: "Korean",
  ru: "Russian",
  ar: "Arabic",
  hi: "Hindi",
  nl: "Dutch",
  pl: "Polish",
  tr: "Turkish",
  sv: "Swedish",
  uk: "Ukrainian",
};

const MODEL_FALLBACK = [
  { id: "tiny", name: "Tiny", detail: "Fastest · rough draft", disk_mb: 75 },
  { id: "base", name: "Base", detail: "Fast · good for clean speech", disk_mb: 145 },
  { id: "small", name: "Small", detail: "CPU friendly · balanced", disk_mb: 480 },
  { id: "medium", name: "Medium", detail: "Higher accuracy · slower", disk_mb: 1530 },
  { id: "large-v3", name: "Large v3", detail: "Best multilingual quality", disk_mb: 3090 },
  { id: "distil-large-v3", name: "Distil large v3", detail: "Fast English-heavy distillation", disk_mb: 1510 },
];

const DEMO_LYRICS = demoLyrics.sections.map((section) => section.content).join("\n\n");
const DEMO_AUDIO = {
  path: "music/nocturno/master/nocturno-master.wav",
  name: "nocturno-master.wav",
  size_label: "50.0 MB",
  kind: "audio",
};
const DEMO_SUBTITLE = {
  path: "subtitles/67c9de20/nocturno.srt",
  name: "nocturno.srt",
  size_label: "3.1 KB",
  kind: "subtitle",
};

const demoStats = {
  lines: 14,
  anchored_lines: 14,
  matched_ratio: 0.96,
  token_match: 0.96,
  line_match: 0.93,
  gap_count: 3,
  warnings: [],
};

const demoSubtitleResult: any = {
  title: "Nocturno — lyric alignment",
  cues: demoCues.map((cue) => ({ ...cue })),
  language: "pt",
  duration: 214.6,
  files: {
    srt: "subtitles/67c9de20/nocturno.srt",
    vtt: "subtitles/67c9de20/nocturno.vtt",
    ass: "subtitles/67c9de20/nocturno.ass",
    cues: "subtitles/67c9de20/nocturno.cues.json",
    metadata: "subtitles/67c9de20/nocturno.metadata.json",
  },
  model: { model: "large-v3", device: "cuda", compute_type: "float16", warnings: [] },
  stats: demoStats,
  warnings: [
    "Cue 05 starts after a 0.8s instrumental gap.",
    "Line 09 (outro) was matched with 82% token confidence.",
  ],
  cue_count: demoCues.length,
  audio_path: DEMO_AUDIO.path,
  created_at: new Date(Date.now() - 68 * 60_000).toISOString(),
};

const fallbackCatalog = {
  ...demoSubtitlesCatalog,
  models: demoSubtitlesCatalog.models,
  languages: demoSubtitlesCatalog.languages,
};

const catalog = ref<any>(fallbackCatalog);
const tab = ref("align");
const audioFile = ref<any>(DEMO ? { ...DEMO_AUDIO } : null);
const audioPickerOpen = ref(false);
const lyrics = ref(DEMO ? DEMO_LYRICS : "");
const showAdvanced = ref(true);

const whisper = reactive({
  model: "large-v3",
  language: "pt",
  task: "transcribe" as "transcribe" | "translate",
  beam_size: 5,
  vad_filter: true,
  word_timestamps: true,
  temperature: 0,
  initial_prompt: "Nocturno — Helena Rocha",
  condition_on_previous_text: false,
  no_speech_threshold: 0.6,
  max_line_chars: 42,
  max_lines: 2,
  segment_gap: 0.06,
  output_format: "srt",
  translate_to: "",
  use_lyrics_bias: true,
  instrumental_gap: 8,
});

const fromText = ref(DEMO ? DEMO_LYRICS : "");
const fromDuration = ref(214.6);
const fromStart = ref(0);
const fromWpm = ref(160);
const fromFormat = ref("srt");
const fromTranslate = ref("");

const convertPickerOpen = ref(false);
const convertFile = ref<any>(DEMO ? { ...DEMO_SUBTITLE } : null);
const convertSource = ref("auto");
const convertTarget = ref("vtt");
const convertContent = ref(DEMO ? buildSrt(demoCues) : "");
const convertResult = ref<any>(null);
const convertBusy = ref(false);

const result = ref<any>(DEMO ? { ...demoSubtitleResult } : null);
const cues = ref<any[]>(DEMO ? demoCues.map((cue) => ({ ...cue })) : []);
const jobId = ref("");
const submittedJob = ref<Job | null>(null);
const processedJobId = ref("");
const jobAction = ref("align");
const busy = ref(false);
let pollTimer: number | undefined;
let demoProgressTimer: number | undefined;

const tabs = [
  { id: "align", label: "Align lyrics" },
  { id: "transcribe", label: "Transcribe" },
  { id: "from-text", label: "From text" },
  { id: "convert", label: "Convert" },
];

const modelItems = computed(() => {
  const raw = catalog.value.models || [];
  if (!raw.length) return MODEL_FALLBACK;
  return raw.map((item: any) => {
    if (typeof item === "string") {
      return MODEL_FALLBACK.find((model) => model.id === item) || { id: item, name: item, detail: "Whisper model", disk_mb: null };
    }
    return {
      ...item,
      id: String(item.id || item.model || ""),
      name: String(item.name || item.id || item.model || ""),
      detail: item.description || item.detail || (item.multilingual === false ? "English only" : "Multilingual"),
      downloaded: item.downloaded,
      recommended: item.recommended,
    };
  });
});

const languageOptions = computed<Array<{ code: string; name: string }>>(() => {
  const raw = catalog.value.languages || [];
  const items: Array<{ code: string; name: string }> = raw.map((item: any) => {
    if (typeof item === "string") return { code: item, name: LANGUAGE_NAMES[item] || item };
    return {
      code: String(item.code || item.id || ""),
      name: String(item.name || LANGUAGE_NAMES[item.code] || item.code || ""),
    };
  });
  if (!items.some((item) => item.code === "auto")) items.unshift({ code: "auto", name: "Auto-detect" });
  return items.filter((item) => item.code);
});

const targetLanguages = computed(() => languageOptions.value.filter((item) => item.code !== "auto"));

const lyricsLineCount = computed(() => lyrics.value.split(/\r?\n/).filter((line) => line.trim()).length);
const fromTextLineCount = computed(() => fromText.value.split(/\r?\n/).filter((line) => line.trim()).length);
const activeJob = computed<Job | null>(() => (jobId.value ? jobs.byId(jobId.value) || submittedJob.value : submittedJob.value));
const activeRunning = computed(() => (activeJob.value ? ["queued", "running", "canceling"].includes(activeJob.value.status) : false));
const cueCount = computed(() => cues.value.length);
const resultWarnings = computed(() => {
  const values = [...(result.value?.warnings || []), ...(result.value?.stats?.warnings || [])];
  return Array.from(new Set(values.filter(Boolean)));
});
const confidence = computed(() => {
  const values = cues.value.map((cue) => Number(cue.confidence)).filter((value) => Number.isFinite(value) && value > 0);
  if (values.length) return values.reduce((sum, value) => sum + value, 0) / values.length;
  return Number(result.value?.stats?.matched_ratio || result.value?.stats?.token_match || result.value?.confidence || 0.96);
});
const confidenceLabel = computed(() => `${Math.round(confidence.value * 100)}%`);
const resultLanguage = computed(() => result.value?.language || (whisper.language === "auto" ? null : whisper.language));
const estimatedCues = computed(() => estimateCues(fromText.value, Number(fromDuration.value) || 0, Number(fromStart.value) || 0, Number(whisper.segment_gap) || 0.08));
const timingPreview = computed(() => estimatedCues.value.slice(0, 4));
const resultTitle = computed(() => result.value?.title || (tab.value === "align" ? "Lyric alignment" : tab.value === "transcribe" ? "Transcription" : "Timed subtitles"));

function formatTimecode(seconds: number) {
  const value = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = Math.floor(value % 60);
  const ms = Math.round((value - Math.floor(value)) * 1000);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
}

function parseTimecode(value: string) {
  const text = String(value || "").trim();
  const match = text.match(/(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?/);
  if (match) {
    const hours = Number(match[1] || 0);
    const minutes = Number(match[2] || 0);
    const seconds = Number(match[3] || 0);
    const fraction = Number((match[4] || "0").padEnd(3, "0"));
    return hours * 3600 + minutes * 60 + seconds + fraction / 1000;
  }
  const numeric = Number(text);
  return Number.isFinite(numeric) ? numeric : null;
}

function srtTime(seconds: number) {
  return formatTimecode(seconds).replace(".", ",");
}

function buildSrt(items: Array<any>) {
  return items
    .map((cue, index) => `${index + 1}\n${srtTime(cue.start)} --> ${srtTime(cue.end)}\n${String(cue.text || "").trim()}\n`)
    .join("\n");
}

function buildVtt(items: Array<any>) {
  return `WEBVTT\n\n${items
    .map((cue, index) => `${index + 1}\n${formatTimecode(cue.start)} --> ${formatTimecode(cue.end)}\n${String(cue.text || "").trim()}\n`)
    .join("\n")}`;
}

function buildAss(items: Array<any>) {
  const assTime = (seconds: number) => {
    const value = Math.max(0, Number(seconds) || 0);
    const centis = Math.round(value * 100);
    const hours = Math.floor(centis / 360000);
    const minutes = Math.floor((centis % 360000) / 6000);
    const secs = Math.floor((centis % 6000) / 100);
    const cs = centis % 100;
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${String(cs).padStart(2, "0")}`;
  };
  const style = `[Script Info]
Title: Open Studio Subtitles
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,54,&H00FFFFFF,&H0000D1FF,&H00000000,&H60000000,0,0,0,0,100,100,0,0,1,2,1,2,40,40,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
`;
  const lines = items.map((cue) => {
    const start = assTime(cue.start);
    const end = assTime(cue.end);
    const text = String(cue.text || "").replace(/\n/g, "\\N");
    return `Dialogue: 0,${start},${end},Default,,0,0,0,,${text}`;
  });
  return `${style}${lines.join("\n")}\n`;
}

function buildCaption(format: string, items: Array<any>) {
  if (format === "vtt") return buildVtt(items);
  if (format === "ass") return buildAss(items);
  return buildSrt(items);
}

function languageName(code?: string | null) {
  if (!code) return "Auto-detect";
  const match = languageOptions.value.find((item) => item.code === code);
  return match?.name || LANGUAGE_NAMES[code] || code;
}

function chooseAudio(path: string, file: any) {
  audioFile.value = {
    path,
    name: file?.name || path.split("/").pop() || "audio",
    size_label: file?.size_label || (file?.size ? formatBytes(file.size) : ""),
    kind: "audio",
  };
  toasts.success("Audio selected");
}

function chooseConvertFile(path: string, file: any) {
  convertFile.value = {
    path,
    name: file?.name || path.split("/").pop() || "subtitles.srt",
    size_label: file?.size_label || (file?.size ? formatBytes(file.size) : ""),
    kind: "subtitle",
  };
  const suffix = String(file?.name || path).split(".").pop()?.toLowerCase();
  if (suffix === "srt" || suffix === "vtt" || suffix === "ass") convertSource.value = suffix;
  if (DEMO) {
    convertContent.value = buildSrt(demoCues);
    return;
  }
  api
    .get<{ content: string }>(`/files/read?path=${encodeURIComponent(path)}`)
    .then((data) => {
      convertContent.value = data.content || "";
    })
    .catch((error: any) => toasts.error(error.message));
}

function updateCueTime(cue: any, key: "start" | "end", event: Event) {
  const parsed = parseTimecode((event.target as HTMLInputElement).value);
  if (parsed === null) return;
  cue[key] = Math.max(0, parsed);
  if (key === "start" && cue.end < cue.start + 0.2) cue.end = cue.start + 0.2;
}

function updateCueText(cue: any, event: Event) {
  cue.text = (event.target as HTMLTextAreaElement).value;
}

function addCue() {
  const previous = cues.value[cues.value.length - 1];
  const start = previous ? Math.max(previous.end + 0.2, previous.start + 1) : 0;
  cues.value.push({ index: cues.value.length + 1, start, end: start + 2.2, text: "New cue" });
}

function removeCue(index: number) {
  cues.value.splice(index, 1);
}

function splitCue(index: number) {
  const cue = cues.value[index];
  if (!cue) return;
  const words = String(cue.text || "").trim().split(/\s+/).filter(Boolean);
  let first = "";
  let second = "";
  if (words.length > 1) {
    const middle = Math.ceil(words.length / 2);
    first = words.slice(0, middle).join(" ");
    second = words.slice(middle).join(" ");
  } else {
    const text = String(cue.text || "").trim();
    const middle = Math.max(1, Math.ceil(text.length / 2));
    first = text.slice(0, middle).trim();
    second = text.slice(middle).trim();
  }
  const middleTime = cue.start + Math.max(0.2, (cue.end - cue.start) / 2);
  cues.value.splice(index, 1, { ...cue, end: middleTime, text: first }, { ...cue, start: middleTime, end: cue.end, text: second });
}

function mergeCue(index: number) {
  const cue = cues.value[index];
  const next = cues.value[index + 1];
  if (!cue || !next) return;
  cues.value.splice(index, 2, { ...cue, end: next.end, text: `${String(cue.text).trim()} ${String(next.text).trim()}`.trim() });
}

function estimateCues(text: string, duration: number, start: number, gap: number) {
  const lines = String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.length || duration <= 0) return [];
  const weights = lines.map((line) => Math.max(1, line.split(/\s+/).length));
  const totalWeight = weights.reduce((sum, value) => sum + value, 0);
  const usable = Math.max(0.2, duration - gap * Math.max(0, lines.length - 1));
  let cursor = start;
  return lines.map((textLine, index) => {
    const share = index === lines.length - 1 ? start + duration - cursor : (usable * weights[index]) / totalWeight;
    const cueStart = Math.min(start + duration, cursor);
    const cueEnd =
      index === lines.length - 1
        ? start + duration
        : Math.max(cueStart + 0.05, Math.min(start + duration, cueStart + share));
    cursor = cueEnd + gap;
    return { index: index + 1, start: Math.round(cueStart * 1000) / 1000, end: Math.round(Math.max(cueStart + 0.05, cueEnd) * 1000) / 1000, text: textLine };
  });
}

function buildFromTextResult() {
  const duration = Number(fromDuration.value) || 0;
  const start = Number(fromStart.value) || 0;
  const generated = estimateCues(fromText.value, duration, start, Number(whisper.segment_gap) || 0.08);
  return {
    title: "Subtitles from text",
    cues: generated,
    language: null,
    duration,
    files: {
      srt: "subtitles/from-text/timings.srt",
      vtt: "subtitles/from-text/timings.vtt",
      ass: "subtitles/from-text/timings.ass",
      cues: "subtitles/from-text/timings.cues.json",
      metadata: "subtitles/from-text/timings.metadata.json",
    },
    model: {},
    stats: { mode: "from_text", words_per_minute: fromWpm.value, lines: generated.length },
    warnings: [],
    cue_count: generated.length,
    audio_path: null,
    created_at: new Date().toISOString(),
  };
}

function buildDemoResult(action: string) {
  if (action === "from-text") return buildFromTextResult();
  const prefix = action === "transcribe" ? "demo-transcribe" : "67c9de20";
  return {
    ...demoSubtitleResult,
    title: action === "transcribe" ? "Nocturne — transcription" : "Nocturno — lyric alignment",
    language: action === "transcribe" ? (whisper.language === "auto" ? "pt" : whisper.language) : "pt",
    files: {
      srt: `subtitles/${prefix}/nocturno.srt`,
      vtt: `subtitles/${prefix}/nocturno.vtt`,
      ass: `subtitles/${prefix}/nocturno.ass`,
      cues: `subtitles/${prefix}/nocturno.cues.json`,
      metadata: `subtitles/${prefix}/nocturno.metadata.json`,
    },
    audio_path: audioFile.value?.path || DEMO_AUDIO.path,
    created_at: new Date().toISOString(),
    cues: cues.value.length ? cues.value.map((cue) => ({ ...cue })) : demoCues.map((cue) => ({ ...cue })),
    cue_count: cues.value.length || demoCues.length,
  };
}

function trackJob(raw: any, action: string) {
  const id = raw?.id || raw?.job_id;
  if (!id) throw new Error("The subtitles service did not return a job id");
  const normalized = { ...raw, id } as Job;
  submittedJob.value = normalized;
  jobId.value = id;
  jobAction.value = action;
  processedJobId.value = "";
  jobs.upsert(normalized);
  if (!DEMO) startPollingJob(id);
}

function startPollingJob(id: string) {
  window.clearTimeout(pollTimer);
  const tick = async () => {
    try {
      const fresh = await api.get<Job>(`/jobs/${id}`);
      jobs.upsert(fresh);
      if (!["queued", "running", "canceling"].includes(fresh.status)) return;
    } catch {
      // SSE is the primary update channel; polling is a fallback.
    }
    pollTimer = window.setTimeout(tick, 2600);
  };
  pollTimer = window.setTimeout(tick, 2200);
}

function simulateJob(action: string, title: string, data: any) {
  window.clearInterval(demoProgressTimer);
  const id = `job_demo_srt_${Math.random().toString(36).slice(2, 10)}`;
  const now = new Date().toISOString();
  const base: Job = {
    id,
    component: "srt",
    action,
    title,
    status: "running",
    stage: action === "align" ? "Aligning lyrics" : action === "transcribe" ? "Transcribing" : "Estimating timings",
    message: "Whisper is working through the audio…",
    progress: 7,
    params: {},
    result: null,
    error: null,
    warnings: [],
    artifacts: [],
    cancel_requested: false,
    attempts: 1,
    created_at: now,
    started_at: now,
    finished_at: null,
    updated_at: now,
  };
  submittedJob.value = base;
  jobId.value = id;
  jobAction.value = action;
  processedJobId.value = "";
  jobs.upsert(base);
  let progress = 7;
  demoProgressTimer = window.setInterval(() => {
    progress = Math.min(95, progress + 8 + Math.random() * 10);
    const running: Job = {
      ...base,
      progress,
      stage: action === "from-text" ? "Distributing cues" : "Transcribing",
      message: action === "from-text" ? "Spreading lines across the requested duration…" : "Decoding speech and matching lyric tokens…",
      updated_at: new Date().toISOString(),
    };
    submittedJob.value = running;
    jobs.upsert(running);
    if (progress >= 95) {
      window.clearInterval(demoProgressTimer);
      const completed: Job = {
        ...running,
        status: "completed",
        stage: "Complete",
        message: "Demo subtitles ready.",
        progress: 100,
        result: {
          message: "Demo subtitles ready.",
          files: Object.entries(data.files || {}).map(([format, path]: any) => ({
            path,
            name: String(path).split("/").pop(),
            kind: "subtitle",
            format,
            size: format === "srt" ? 3120 : 3400,
          })),
          data,
        },
        finished_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      submittedJob.value = completed;
      jobs.upsert(completed);
    }
  }, 440);
}

async function runSubtitles() {
  if (tab.value === "align" || tab.value === "transcribe") {
    if (!audioFile.value?.path) {
      toasts.error("Choose an audio file first");
      return;
    }
  }
  if (tab.value === "align" && !lyrics.value.trim()) {
    toasts.error("Paste the lyrics to align");
    return;
  }
  if (tab.value === "from-text" && !fromText.value.trim()) {
    toasts.error("Paste some text to time");
    return;
  }
  if (tab.value === "from-text" && (!fromDuration.value || Number(fromDuration.value) <= 0)) {
    toasts.error("Enter a positive duration");
    return;
  }
  busy.value = true;
  try {
    if (tab.value === "from-text") {
      if (DEMO) {
        const data = buildFromTextResult();
        simulateJob("from_text", "Subtitles from text", data);
        toasts.info("Estimating demo cue timings…");
        return;
      }
      const payload = {
        text: fromText.value,
        duration: Number(fromDuration.value),
        start: Number(fromStart.value) || 0,
        words_per_minute: Number(fromWpm.value) || 160,
        output_format: fromFormat.value,
        translate_to: fromTranslate.value || undefined,
        max_line_chars: whisper.max_line_chars,
        max_lines: whisper.max_lines,
        segment_gap: whisper.segment_gap,
        title: "Subtitles from text",
      };
      const raw = await api.post<any>("/srt/from-text", payload);
      trackJob(raw, "from_text");
      toasts.info("Timing estimate queued");
      return;
    }

    const action = tab.value === "align" ? "align" : "transcribe";
    const options = {
      model: whisper.model,
      language: whisper.language === "auto" ? null : whisper.language,
      task: whisper.task,
      beam_size: Number(whisper.beam_size),
      vad_filter: whisper.vad_filter,
      word_timestamps: whisper.word_timestamps,
      temperature: Number(whisper.temperature),
      initial_prompt: whisper.initial_prompt || null,
      condition_on_previous_text: whisper.condition_on_previous_text,
      no_speech_threshold: Number(whisper.no_speech_threshold),
      output_format: whisper.output_format,
      translate_to: whisper.translate_to || null,
      max_line_chars: Number(whisper.max_line_chars),
      max_lines: Number(whisper.max_lines),
      segment_gap: Number(whisper.segment_gap),
      audio_path: audioFile.value.path,
      title: action === "align" ? "Nocturno — lyric alignment" : `Transcribe ${audioFile.value.name}`,
    };
    if (action === "align") {
      Object.assign(options, {
        lyrics: lyrics.value,
        use_lyrics_bias: whisper.use_lyrics_bias,
        instrumental_gap: Number(whisper.instrumental_gap),
      });
    }
    if (DEMO) {
      const data = buildDemoResult(action);
      simulateJob(action, action === "align" ? "Nocturno — lyric alignment" : `Transcribe ${audioFile.value.name}`, data);
      toasts.info(action === "align" ? "Aligning demo lyrics…" : "Transcribing demo audio…");
      return;
    }
    options.task = action === "align" ? "transcribe" : whisper.task;
    const raw = await api.post<any>(action === "align" ? "/srt/align" : "/srt/transcribe", options);
    trackJob(raw, action);
    toasts.info(action === "align" ? "Lyric alignment queued" : "Transcription queued");
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    busy.value = false;
  }
}

function handleCompleted(job: Job) {
  const data: any = job.result?.data || {};
  if (Array.isArray(data.cues)) {
    cues.value = data.cues.map((cue: any) => ({ ...cue }));
  }
  if (data && data.cues) {
    result.value = { ...data };
    toasts.success(jobAction.value === "transcribe" ? "Transcription complete" : jobAction.value === "from_text" ? "Timings ready" : "Lyrics aligned");
  } else {
    toasts.success("Subtitles ready");
  }
}

watch(
  activeJob,
  (job) => {
    if (!job || job.id === processedJobId.value) return;
    if (["queued", "running", "canceling"].includes(job.status)) return;
    processedJobId.value = job.id;
    if (job.status === "completed") handleCompleted(job);
    else if (job.status === "failed") toasts.error(job.error || "Subtitle job failed");
    else if (job.status === "canceled") toasts.info("Subtitle job canceled");
  },
  { deep: true },
);

async function cancelActive() {
  if (!activeJob.value) return;
  if (DEMO) {
    window.clearInterval(demoProgressTimer);
    const canceled: Job = {
      ...activeJob.value,
      status: "canceled",
      stage: "Cancelled",
      message: "Cancelled by the user.",
      cancel_requested: true,
      finished_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    submittedJob.value = canceled;
    jobs.upsert(canceled);
    toasts.info("Cancellation requested");
    return;
  }
  try {
    await jobs.cancel(activeJob.value.id);
    toasts.info("Cancellation requested");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function downloadFor(format: string) {
  const files = result.value?.files;
  if (!files) return "";
  if (Array.isArray(files)) {
    const found = files.find((item: any) => item.format === format || String(item.path || "").toLowerCase().endsWith(`.${format}`));
    return found?.path || "";
  }
  return files[format] || "";
}

function setCueResultFormat(format: string) {
  whisper.output_format = format;
}

async function convertSubtitles() {
  if (!convertContent.value.trim() && !convertFile.value?.path) {
    toasts.error("Choose a subtitle file or paste subtitle text");
    return;
  }
  convertBusy.value = true;
  try {
    if (DEMO) {
      const items = cues.value.length ? cues.value : demoCues;
      const content = buildCaption(convertTarget.value, items);
      convertResult.value = {
        format: convertTarget.value,
        source_format: convertSource.value === "auto" ? "srt" : convertSource.value,
        content,
        cues: items.map((cue: any) => ({ ...cue })),
        count: items.length,
        title: "Open Studio conversion",
        saved: true,
        path: `subtitles/converted/nocturno.${convertTarget.value}`,
        filename: `nocturno.${convertTarget.value}`,
        created_at: new Date().toISOString(),
      };
      toasts.success(`Converted to ${convertTarget.value.toUpperCase()} (demo)`);
      return;
    }
    const payload: any = {
      source_format: convertSource.value,
      output_format: convertTarget.value,
      save: true,
      title: "Open Studio conversion",
    };
    if (convertContent.value.trim()) payload.content = convertContent.value;
    else payload.path = convertFile.value.path;
    const data = await api.post<any>("/srt/convert", payload);
    convertResult.value = data;
    toasts.success(`Converted to ${String(data.format || convertTarget.value).toUpperCase()}`);
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    convertBusy.value = false;
  }
}

async function loadCatalog() {
  if (DEMO) return;
  try {
    const data = await api.get<any>("/srt/catalog");
    catalog.value = { ...fallbackCatalog, ...data };
    if (data.defaults) {
      whisper.model = data.defaults.model || whisper.model;
      whisper.beam_size = data.defaults.beam_size ?? whisper.beam_size;
      whisper.vad_filter = data.defaults.vad_filter ?? whisper.vad_filter;
      whisper.word_timestamps = data.defaults.word_timestamps ?? whisper.word_timestamps;
    }
  } catch (error: any) {
    toasts.error(error.message);
  }
}

onMounted(() => {
  if (!DEMO) loadCatalog();
});

onBeforeUnmount(() => {
  window.clearTimeout(pollTimer);
  window.clearInterval(demoProgressTimer);
});
</script>

<template>
  <div class="page srt-page" :class="{ 'srt-embedded': embedded }">
    <PageHeader
      v-if="!embedded"
      eyebrow="AI subtitles · Whisper + DP alignment"
      title="AI subtitles"
      subtitle="Turn an MP3 and its lyrics into frame-accurate SRT with Whisper and dynamic-programming alignment. Transcribe speech, time plain text, or convert between SRT, VTT and ASS."
    >
      <template #actions>
        <span class="chip success"><span class="dot online" /> faster-whisper</span>
        <span class="chip"><Gauge :size="11" /> {{ whisper.model }}</span>
        <a v-if="downloadFor('srt')" class="btn btn-sm" :href="downloadUrl(downloadFor('srt'))"><Download :size="13" /> Download SRT</a>
      </template>
    </PageHeader>

    <div class="stat-grid" style="margin-bottom: 16px">
      <div class="stat">
        <div class="stat-label">Cues in editor</div>
        <div class="stat-value">{{ cueCount }}</div>
        <div class="stat-sub">{{ resultTitle }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Alignment confidence</div>
        <div class="stat-value">{{ confidenceLabel }}</div>
        <div class="stat-sub">Token match · DP anchor pass</div>
      </div>
      <div class="stat">
        <div class="stat-label">Language</div>
        <div class="stat-value" style="font-size: 20px">{{ languageName(resultLanguage) }}</div>
        <div class="stat-sub">{{ result?.model?.model || whisper.model }} · {{ result?.model?.device || "auto device" }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Duration</div>
        <div class="stat-value">{{ formatDuration(result?.duration || (audioFile ? 214.6 : 0)) }}</div>
        <div class="stat-sub">SRT · VTT · ASS written together</div>
      </div>
    </div>

    <div class="row-between" style="margin-bottom: 16px; align-items: flex-start">
      <TabsBar v-model="tab" :tabs="tabs" />
      <div class="row" style="gap: 5px">
        <span class="chip"><Clock3 :size="11" /> {{ lyricsLineCount }} lyric lines</span>
        <span class="chip"><Languages :size="11" /> {{ languageOptions.length }} languages</span>
      </div>
    </div>

    <section v-if="tab !== 'convert' && activeJob" class="panel" style="margin-bottom: 16px">
      <div class="panel-head">
        <div><h3>Active subtitle job</h3><p>{{ activeJob.action }} · progress streams from the job hub.</p></div>
        <span class="badge running">{{ Math.round(activeJob.progress) }}%</span>
      </div>
      <div class="panel-body"><JobCard :job="activeJob" @cancel="cancelActive" /></div>
    </section>

    <section v-if="tab === 'align' || tab === 'transcribe'" class="split split-wide">
      <div class="stack">
        <div class="panel">
          <div class="panel-head">
            <div>
              <h3>{{ tab === "align" ? "Audio source" : "Audio to transcribe" }}</h3>
              <p>{{ tab === "align" ? "A song, voice memo or narration track. Whisper listens once, then DP aligns the lyric lines." : "Whisper detects speech, language and sentence boundaries in one pass." }}</p>
            </div>
            <button class="btn btn-sm" @click="audioPickerOpen = true"><FileAudio :size="13" /> Choose audio</button>
          </div>
          <div class="panel-body">
            <div v-if="audioFile" class="selected-file">
              <span class="file-icon"><AudioLines :size="18" /></span>
              <div class="grow" style="min-width: 0">
                <div class="small strong truncate">{{ audioFile.name }}</div>
                <div class="small muted truncate mono">{{ audioFile.path }}</div>
              </div>
              <span class="chip">{{ audioFile.size_label || "audio" }}</span>
              <button class="icon-btn" title="Remove" @click="audioFile = null"><X :size="14" /></button>
            </div>
            <button v-else class="pick-zone" @click="audioPickerOpen = true">
              <FileAudio :size="24" />
              <span class="strong">Select an audio file</span>
              <span class="small muted">MP3, WAV, FLAC, M4A — or upload into shared storage.</span>
            </button>
            <div class="row-between small muted" style="margin-top: 9px">
              <span>Files come from the shared tree, so music, video and voice takes are all available.</span>
              <span v-if="audioFile">Duration ≈ {{ formatDuration(214.6) }}</span>
            </div>
          </div>
        </div>

        <div v-if="tab === 'align'" class="panel">
          <div class="panel-head">
            <div>
              <h3>Lyrics</h3>
              <p>One lyric line per subtitle cue. Blank lines are preserved as stanza breaks.</p>
            </div>
            <span class="chip">{{ lyricsLineCount }} lines</span>
          </div>
          <div class="panel-body stack" style="gap: 11px">
            <textarea v-model="lyrics" class="textarea lyrics-area" rows="13" placeholder="Paste the lyrics exactly as they are sung…" />
            <div class="row-between">
              <div class="row" style="gap: 6px">
                <span class="chip">PT</span>
                <span class="chip">EN</span>
                <span class="chip">ES</span>
                <span class="small muted">Any language Whisper understands</span>
              </div>
              <span class="small muted">{{ lyrics.length }} characters</span>
            </div>
            <div class="grid grid-2" style="gap: 12px">
              <div class="switch-row" style="padding: 0">
                <div><div class="switch-label">Use lyrics as recognition bias</div><div class="switch-hint">Adds the first lines as Whisper's initial prompt.</div></div>
                <button class="switch" :class="{ on: whisper.use_lyrics_bias }" @click="whisper.use_lyrics_bias = !whisper.use_lyrics_bias" />
              </div>
              <div class="field">
                <label>Instrumental gap <span class="small muted">seconds</span></label>
                <input v-model.number="whisper.instrumental_gap" class="input" type="number" min="2" max="120" step="0.5" />
              </div>
            </div>
          </div>
        </div>

        <div v-else class="panel">
          <div class="panel-head">
            <div><h3>What Whisper does</h3><p>Audio is decoded with ffmpeg, VAD trims silence, and sentence cues are split to your line length.</p></div>
            <span class="badge success"><Check :size="10" /> Local</span>
          </div>
          <div class="panel-body grid grid-3" style="gap: 10px">
            <div class="mini-tile"><span>01</span><strong>VAD</strong><p>Speech regions detected before decoding.</p></div>
            <div class="mini-tile"><span>02</span><strong>Decode</strong><p>Whisper transcribes with beam search and temperature fallback.</p></div>
            <div class="mini-tile"><span>03</span><strong>Wrap</strong><p>Long sentences become readable multi-line cues.</p></div>
          </div>
        </div>
      </div>

      <aside class="panel settings-sticky">
        <div class="panel-head">
          <div><h3>Whisper settings</h3><p>Shared by align and transcribe.</p></div>
          <span class="badge success">{{ whisper.model }}</span>
        </div>
        <div class="panel-body stack" style="gap: 12px">
          <div class="grid grid-2" style="gap: 10px">
            <div class="field">
              <label>Model</label>
              <select v-model="whisper.model" class="select">
                <option v-for="model in modelItems" :key="model.id" :value="model.id">
                  {{ model.name }}{{ model.recommended ? " · recommended" : "" }}{{ model.downloaded === false ? " · download" : "" }}
                </option>
              </select>
              <span class="hint">{{ modelItems.find((model: any) => model.id === whisper.model)?.detail || "Whisper model" }}</span>
            </div>
            <div class="field">
              <label>Language</label>
              <select v-model="whisper.language" class="select">
                <option v-for="language in languageOptions" :key="language.code" :value="language.code">{{ language.name }}</option>
              </select>
            </div>
          </div>

          <div class="grid grid-2" style="gap: 10px">
            <div class="field">
              <label>Beam size</label>
              <select v-model.number="whisper.beam_size" class="select">
                <option v-for="size in [1, 3, 5, 8, 10]" :key="size" :value="size">{{ size }}{{ size === 5 ? " · balanced" : size === 1 ? " · greedy" : "" }}</option>
              </select>
            </div>
            <div class="field">
              <label>Output format</label>
              <div class="pill-row">
                <button
                  v-for="format in ['srt', 'vtt', 'ass']"
                  :key="format"
                  class="chip clickable"
                  :class="{ active: whisper.output_format === format }"
                  @click="setCueResultFormat(format)"
                >
                  {{ format.toUpperCase() }}
                </button>
              </div>
              <span class="hint">All three files are written; this is the primary format.</span>
            </div>
          </div>

          <div class="switch-row" style="padding: 4px 0">
            <div><div class="switch-label">VAD filter</div><div class="switch-hint">Skip silence and breathing before decoding.</div></div>
            <button class="switch" :class="{ on: whisper.vad_filter }" @click="whisper.vad_filter = !whisper.vad_filter" />
          </div>
          <div class="switch-row" style="padding: 4px 0">
            <div><div class="switch-label">Word timestamps</div><div class="switch-hint">Required for lyric alignment; useful for karaoke.</div></div>
            <button class="switch" :class="{ on: whisper.word_timestamps || tab === 'align' }" @click="whisper.word_timestamps = !whisper.word_timestamps" />
          </div>
          <div class="switch-row" style="padding: 4px 0">
            <div><div class="switch-label">Condition on previous text</div><div class="switch-hint">Can improve flow, but risks repeating a bad line.</div></div>
            <button class="switch" :class="{ on: whisper.condition_on_previous_text }" @click="whisper.condition_on_previous_text = !whisper.condition_on_previous_text" />
          </div>

          <div class="field">
            <label>Translate to <span class="small muted">optional</span></label>
            <select v-model="whisper.translate_to" class="select">
              <option value="">Keep the spoken language</option>
              <option v-for="language in targetLanguages" :key="language.code" :value="language.code">{{ language.name }}</option>
            </select>
            <span class="hint">Finished cues are translated after timing; original files are kept.</span>
          </div>

          <div class="panel" style="background: rgba(8, 10, 15, 0.28)">
            <div class="panel-head" style="padding: 10px 12px; cursor: pointer" @click="showAdvanced = !showAdvanced">
              <div><h3 style="font-size: 12.5px">Advanced decoding</h3><p>Temperature, prompt, thresholds and cue wrapping.</p></div>
              <ChevronRight :size="14" :style="{ transform: showAdvanced ? 'rotate(90deg)' : 'none', transition: '150ms' }" class="muted" />
            </div>
            <div v-if="showAdvanced" class="panel-body grid grid-2" style="padding: 12px; gap: 10px">
              <div v-if="tab === 'transcribe'" class="field">
                <label>Task</label>
                <select v-model="whisper.task" class="select">
                  <option value="transcribe">Transcribe</option>
                  <option value="translate">Translate to English</option>
                </select>
              </div>
              <div class="field">
                <label>Temperature</label>
                <input v-model.number="whisper.temperature" class="input" type="number" min="0" max="2" step="0.1" />
              </div>
              <div class="field">
                <label>No-speech threshold</label>
                <input v-model.number="whisper.no_speech_threshold" class="input" type="number" min="0" max="1" step="0.05" />
              </div>
              <div class="field">
                <label>Max line chars</label>
                <input v-model.number="whisper.max_line_chars" class="input" type="number" min="0" max="200" />
              </div>
              <div class="field">
                <label>Max lines</label>
                <select v-model.number="whisper.max_lines" class="select">
                  <option v-for="lineCount in [1, 2, 3, 4]" :key="lineCount" :value="lineCount">{{ lineCount }}</option>
                </select>
              </div>
              <div class="field">
                <label>Segment gap <span class="small muted">seconds</span></label>
                <input v-model.number="whisper.segment_gap" class="input" type="number" min="0" max="2" step="0.01" />
              </div>
              <div class="field" style="grid-column: 1 / -1">
                <label>Initial prompt <span class="small muted">optional</span></label>
                <textarea v-model="whisper.initial_prompt" class="textarea" rows="2" maxlength="4000" placeholder="Names, places or the first lyric lines…" />
              </div>
            </div>
          </div>

          <button class="btn btn-primary btn-block" :disabled="busy || activeRunning" @click="runSubtitles">
            <Loader2 v-if="busy" :size="14" class="spin" />
            <Sparkles v-else :size="14" />
            {{ tab === "align" ? "Align lyrics to audio" : "Transcribe audio" }}
          </button>
          <span class="small muted" style="text-align: center">
            {{ tab === "align" ? "Whisper + DP token alignment" : "faster-whisper · " + whisper.model }} · runs locally
          </span>
        </div>
      </aside>
    </section>

    <section v-else-if="tab === 'from-text'" class="split split-wide">
      <div class="stack">
        <div class="panel">
          <div class="panel-head">
            <div><h3>Text to time</h3><p>One line becomes one cue. Timings are distributed by word weight across the duration.</p></div>
            <span class="chip">{{ fromTextLineCount }} lines</span>
          </div>
          <div class="panel-body stack" style="gap: 12px">
            <textarea v-model="fromText" class="textarea" rows="13" placeholder="Paste the text, one subtitle line per line…" />
            <div class="grid grid-3" style="gap: 11px">
              <div class="field">
                <label>Total duration <span class="small muted">seconds</span></label>
                <input v-model.number="fromDuration" class="input" type="number" min="0.1" step="0.1" />
                <span class="hint">{{ formatDuration(fromDuration) }}</span>
              </div>
              <div class="field">
                <label>Start at <span class="small muted">seconds</span></label>
                <input v-model.number="fromStart" class="input" type="number" min="0" step="0.1" />
              </div>
              <div class="field">
                <label>Reading speed <span class="small muted">wpm</span></label>
                <input v-model.number="fromWpm" class="input" type="number" min="40" max="400" step="5" />
              </div>
            </div>
            <div class="row-between">
              <span class="small muted">{{ fromText.length }} characters · {{ estimatedCues.length }} estimated cues · {{ Math.round(Number(fromWpm) || 0) }} wpm</span>
              <span class="chip"><Clock3 :size="11" /> line-by-line estimate</span>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head"><div><h3>Timing preview</h3><p>The first cues before you run the job.</p></div><span class="chip">{{ formatDuration(fromDuration) }}</span></div>
          <div class="panel-body">
            <div v-if="timingPreview.length" class="stack" style="gap: 8px">
              <div v-for="cue in timingPreview" :key="cue.index" class="preview-cue">
                <span class="mono small muted">{{ formatTimecode(cue.start) }} → {{ formatTimecode(cue.end) }}</span>
                <span class="small">{{ cue.text }}</span>
              </div>
            </div>
            <EmptyState v-else :icon="AlignLeft" title="Nothing to preview" message="Paste a few lines and set the duration; the estimated cue table appears here." />
          </div>
        </div>
      </div>

      <aside class="panel settings-sticky">
        <div class="panel-head"><div><h3>Timing settings</h3><p>From-text does not need a model.</p></div><span class="badge">No Whisper</span></div>
        <div class="panel-body stack" style="gap: 12px">
          <div class="field">
            <label>Primary format</label>
            <div class="pill-row">
              <button v-for="format in ['srt', 'vtt', 'ass']" :key="format" class="chip clickable" :class="{ active: fromFormat === format }" @click="fromFormat = format">{{ format.toUpperCase() }}</button>
            </div>
          </div>
          <div class="field">
            <label>Max line chars</label>
            <input v-model.number="whisper.max_line_chars" class="input" type="number" min="0" max="200" />
          </div>
          <div class="field">
            <label>Max lines per cue</label>
            <select v-model.number="whisper.max_lines" class="select">
              <option v-for="lineCount in [1, 2, 3, 4]" :key="lineCount" :value="lineCount">{{ lineCount }}</option>
            </select>
          </div>
          <div class="field">
            <label>Segment gap <span class="small muted">seconds</span></label>
            <input v-model.number="whisper.segment_gap" class="input" type="number" min="0" max="2" step="0.01" />
          </div>
          <div class="field">
            <label>Translate to <span class="small muted">optional</span></label>
            <select v-model="fromTranslate" class="select">
              <option value="">No translation</option>
              <option v-for="language in targetLanguages" :key="language.code" :value="language.code">{{ language.name }}</option>
            </select>
          </div>
          <div class="alert">No audio is required. Timings assume a steady reading pace; use an audio file later if you need exact sync.</div>
          <button class="btn btn-primary btn-block" :disabled="busy || activeRunning" @click="runSubtitles">
            <Loader2 v-if="busy" :size="14" class="spin" />
            <AlignLeft v-else :size="14" />
            Estimate timings
          </button>
        </div>
      </aside>
    </section>

    <section v-else-if="tab === 'convert'" class="split split-wide">
      <div class="stack">
        <div class="panel">
          <div class="panel-head">
            <div><h3>Subtitle input</h3><p>Pick an existing subtitle from shared files or paste its text directly.</p></div>
            <button class="btn btn-sm" @click="convertPickerOpen = true"><FileText :size="13" /> Choose subtitle</button>
          </div>
          <div class="panel-body stack" style="gap: 11px">
            <div v-if="convertFile" class="selected-file">
              <span class="file-icon"><Captions :size="17" /></span>
              <div class="grow" style="min-width: 0">
                <div class="small strong truncate">{{ convertFile.name }}</div>
                <div class="small muted truncate mono">{{ convertFile.path }}</div>
              </div>
              <span class="chip">{{ convertFile.size_label || "subtitle" }}</span>
              <button class="icon-btn" title="Clear" @click="convertFile = null"><X :size="14" /></button>
            </div>
            <textarea v-model="convertContent" class="textarea mono" rows="14" placeholder="1&#10;00:00:00,420 --> 00:00:04,800&#10;A cidade fecha os olhos devagar…" />
            <div class="row-between">
              <div class="field" style="max-width: 210px">
                <label>Source format</label>
                <select v-model="convertSource" class="select">
                  <option value="auto">Auto-detect</option>
                  <option value="srt">SRT</option>
                  <option value="vtt">VTT</option>
                  <option value="ass">ASS</option>
                </select>
              </div>
              <span class="small muted">{{ convertContent.length }} chars · sync conversion, no model</span>
            </div>
          </div>
        </div>
      </div>

      <aside class="panel settings-sticky">
        <div class="panel-head"><div><h3>Convert</h3><p>SRT ↔ VTT ↔ ASS with timing preserved.</p></div><RefreshCw :size="15" class="muted" /></div>
        <div class="panel-body stack" style="gap: 12px">
          <div class="field">
            <label>From</label>
            <select v-model="convertSource" class="select">
              <option value="auto">Auto-detect</option>
              <option value="srt">SRT · SubRip</option>
              <option value="vtt">VTT · WebVTT</option>
              <option value="ass">ASS · Advanced SubStation</option>
            </select>
          </div>
          <div class="field">
            <label>To</label>
            <div class="pill-row">
              <button v-for="format in ['srt', 'vtt', 'ass']" :key="format" class="chip clickable" :class="{ active: convertTarget === format }" @click="convertTarget = format">{{ format.toUpperCase() }}</button>
            </div>
          </div>
          <div class="alert success"><Zap :size="12" style="vertical-align: -2px" /> Conversion is synchronous and saves a copy under <span class="mono">subtitles/converted/</span>.</div>
          <button class="btn btn-primary btn-block" :disabled="convertBusy" @click="convertSubtitles">
            <Loader2 v-if="convertBusy" :size="14" class="spin" />
            <RefreshCw v-else :size="14" />
            Convert to {{ convertTarget.toUpperCase() }}
          </button>
          <div v-if="convertResult" style="margin-top: 3px">
            <div class="row-between small" style="margin-bottom: 7px">
              <span class="chip success">{{ convertResult.count || 0 }} cues · {{ String(convertResult.format || convertTarget).toUpperCase() }}</span>
              <a v-if="convertResult.path" class="btn btn-sm" :href="downloadUrl(convertResult.path)"><Download :size="12" /> Download</a>
            </div>
            <CodeBlock :code="convertResult.content" :label="convertResult.filename || 'Converted subtitles'" />
          </div>
          <EmptyState v-else :icon="RefreshCw" title="Nothing converted yet" message="Choose a source format and a target; the result appears here with a saved file." />
        </div>
      </aside>
    </section>

    <section v-if="tab !== 'convert' && result && cues.length" class="panel" style="margin-top: 16px">
      <div class="panel-head" style="flex-wrap: wrap; gap: 9px">
        <div>
          <h3>Cue editor</h3>
          <p>{{ resultTitle }} · {{ relativeTime(result.created_at) }} · {{ result?.model?.model || whisper.model }}</p>
        </div>
        <div class="row" style="gap: 5px">
          <span class="chip active">{{ cueCount }} cues</span>
          <span class="chip">{{ languageName(resultLanguage) }}</span>
          <span class="chip success">{{ confidenceLabel }} confidence</span>
          <span class="chip" :class="resultWarnings.length ? 'warn' : 'success'">{{ resultWarnings.length }} warning{{ resultWarnings.length === 1 ? "" : "s" }}</span>
          <button class="btn btn-sm" @click="addCue"><Plus :size="12" /> Add cue</button>
        </div>
      </div>
      <div class="panel-body stack" style="gap: 12px">
        <div class="result-audio">
          <AudioPlayer
            :src="result.audio_path || audioFile?.path || ''"
            :title="result.title || 'Subtitle source audio'"
            :subtitle="`${formatDuration(result.duration)} · ${languageName(resultLanguage)}`"
            :download-path="result.audio_path || audioFile?.path || null"
          />
          <div class="download-stack">
            <template v-for="format in ['srt', 'vtt', 'ass']" :key="format">
              <a v-if="downloadFor(format)" class="btn btn-sm" :href="downloadUrl(downloadFor(format))">
                <Download :size="12" /> {{ format.toUpperCase() }}
              </a>
              <span v-else class="btn btn-sm" style="opacity: 0.4">{{ format.toUpperCase() }}</span>
            </template>
            <span class="small muted" style="margin-top: 2px">Edited cues are kept in this session.</span>
          </div>
        </div>

        <div v-if="resultWarnings.length" class="alert warn">
          <strong>Warnings</strong>
          <div v-for="warning in resultWarnings" :key="warning" style="margin-top: 3px">· {{ warning }}</div>
        </div>

        <div class="table-wrap">
          <table class="table cue-table">
            <thead>
              <tr>
                <th style="width: 38px">#</th>
                <th style="width: 126px">Start</th>
                <th style="width: 126px">End</th>
                <th>Text</th>
                <th style="width: 112px">Edit</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(cue, index) in cues" :key="index">
                <td class="mono small muted">{{ index + 1 }}</td>
                <td><input class="input input-sm mono time-input" :value="formatTimecode(cue.start)" @change="updateCueTime(cue, 'start', $event)" /></td>
                <td><input class="input input-sm mono time-input" :value="formatTimecode(cue.end)" @change="updateCueTime(cue, 'end', $event)" /></td>
                <td class="cue-text">
                  <textarea class="textarea cue-input" rows="1" :value="cue.text" @input="updateCueText(cue, $event)" />
                </td>
                <td>
                  <div class="row" style="gap: 2px; flex-wrap: nowrap">
                    <button class="icon-btn" title="Split cue" @click="splitCue(index)"><Scissors :size="13" /></button>
                    <button class="icon-btn" title="Merge with next" :disabled="index === cues.length - 1" @click="mergeCue(index)"><Merge :size="13" /></button>
                    <button class="icon-btn" title="Delete cue" @click="removeCue(index)"><Trash2 :size="13" /></button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="row-between small muted">
          <span>{{ cueCount }} editable cues · split, merge, add or remove before exporting.</span>
          <span class="mono">{{ formatTimecode(cues[cues.length - 1]?.end || 0) }} end</span>
        </div>
      </div>
    </section>

    <FilePicker v-model="audioPickerOpen" title="Choose audio" kind="audio" accept="audio/*" @selected="chooseAudio" />
    <FilePicker v-model="convertPickerOpen" title="Choose subtitles" kind="subtitle" accept=".srt,.vtt,.ass,text/*" @selected="chooseConvertFile" />
  </div>
</template>

<style scoped>
.selected-file {
  display: flex;
  align-items: center;
  gap: 11px;
  border: 1px solid rgba(139, 92, 246, 0.3);
  background: rgba(139, 92, 246, 0.07);
  border-radius: 11px;
  padding: 10px 11px;
}
.selected-file .file-icon {
  width: 38px;
  height: 38px;
}
.pick-zone {
  width: 100%;
  min-height: 116px;
  border: 1px dashed var(--line-strong);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.012);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--muted);
  padding: 18px;
}
.pick-zone:hover {
  border-color: rgba(139, 92, 246, 0.5);
  color: var(--text);
  background: rgba(139, 92, 246, 0.04);
}
.lyrics-area {
  min-height: 250px;
  font-size: 13px;
  line-height: 1.75;
}
.settings-sticky {
  position: sticky;
  top: 84px;
}
.mini-tile {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(8, 10, 15, 0.3);
  padding: 11px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.mini-tile span {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--accent-2);
}
.mini-tile strong {
  font-size: 12px;
}
.mini-tile p {
  font-size: 10.5px;
  line-height: 1.5;
  color: var(--muted);
}
.preview-cue {
  display: flex;
  gap: 14px;
  align-items: baseline;
  border-bottom: 1px solid rgba(35, 42, 58, 0.55);
  padding: 6px 2px;
}
.preview-cue:last-child {
  border-bottom: none;
}
.preview-cue .mono {
  min-width: 208px;
}
.result-audio {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 126px;
  gap: 12px;
  align-items: stretch;
}
.download-stack {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
}
.download-stack .btn {
  width: 100%;
}
.table-wrap {
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: 11px;
}
.cue-table {
  min-width: 760px;
}
.cue-table td {
  vertical-align: middle;
  padding: 7px 8px;
}
.cue-table th {
  background: rgba(8, 10, 15, 0.42);
}
.time-input {
  width: 118px;
  font-size: 10.5px;
  padding: 5px 6px;
}
.cue-input {
  min-height: 32px;
  height: 32px;
  padding: 6px 8px;
  font-size: 11.5px;
  line-height: 1.4;
  resize: vertical;
}
.cue-text {
  min-width: 280px;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 1200px) {
  .settings-sticky {
    position: static;
  }
}
@media (max-width: 780px) {
  .result-audio {
    grid-template-columns: 1fr;
  }
  .download-stack {
    flex-direction: row;
    flex-wrap: wrap;
  }
  .download-stack .btn {
    width: auto;
  }
  .preview-cue {
    flex-direction: column;
    gap: 3px;
  }
}
</style>

<style scoped>
.srt-embedded { padding: 0; }
</style>
