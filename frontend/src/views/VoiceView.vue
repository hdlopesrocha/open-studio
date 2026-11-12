<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import {
  AudioLines,
  Check,
  ChevronRight,
  Clock3,
  Download,
  FileAudio,
  FileArchive,
  Gauge,
  History,
  Layers,
  Loader2,
  Mic2,
  Mic,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
  Upload,
  Users,
  Wand2,
  X,
  Zap,
} from "lucide-vue-next";
import type { Job } from "@/lib/types";
import { DEMO } from "@/lib/types";
import { demoPiperVoices, demoVoiceCatalog, demoVoiceOutputs, demoVoices } from "@/lib/demo";
import { api, downloadUrl, fileUrl, formatDuration, relativeTime } from "@/lib/api";
import { useJobsStore } from "@/stores/jobs";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import BaseModal from "@/components/BaseModal.vue";
import FilePicker from "@/components/FilePicker.vue";
import AudioPlayer from "@/components/AudioPlayer.vue";
import JobCard from "@/components/JobCard.vue";
import EmptyState from "@/components/EmptyState.vue";
import TabsBar from "@/components/TabsBar.vue";

const jobs = useJobsStore();
const toasts = useToastStore();

const DEMO_SCRIPT =
  "[breath] A cidade fecha os olhos devagar.\nEu conto os passos até te encontrar.\nHá luz nas janelas que ninguém apagou,\n[soft laugh] e um fio de voz que nunca se calou.\n\nNocturno, nocturno... [pause] dança comigo no escuro.";

const SAMPLE_SCRIPTS = [
  { label: "Nocturno · PT", text: DEMO_SCRIPT },
  { label: "Documentary · EN", text: "The last train leaves the coast just before sunrise. [breath] Outside, the fields turn the colour of pewter, and the river keeps its own slow time." },
  { label: "Studio tagline · PT", text: "Open Studio. [pause] A sua música, as suas imagens, a sua voz — tudo em casa, num único estúdio privado." },
  { label: "Trailer · EN", text: "In a city that never sleeps, one voice remembers everything. [whispers] This winter, listen closely." },
];

const NONVERBAL_TAGS = ["[breath]", "[laughs]", "[sighs]", "[whispers]", "[pause]", "[excited]", "[sad]", "[soft laugh]"];

const designPresets = [
  {
    label: "Warm documentary narrator",
    attrs: { gender: "female", age: "adult", pitch: "warm", style: "narrator", accent: "british", dialect: "any" },
  },
  {
    label: "Cinematic trailer voice",
    attrs: { gender: "male", age: "middle-aged", pitch: "low", style: "cinematic", accent: "american", dialect: "any" },
  },
  {
    label: "Soft ASMR whisper",
    attrs: { gender: "any", age: "young adult", pitch: "bright", style: "whisper", accent: "irish", dialect: "any" },
  },
  {
    label: "Bright commercial read",
    attrs: { gender: "female", age: "young adult", pitch: "bright", style: "energetic", accent: "australian", dialect: "any" },
  },
  {
    label: "Mandarin storyteller",
    attrs: { gender: "female", age: "adult", pitch: "neutral", style: "narrator", accent: "any", dialect: "mandarin" },
  },
];

const sampleVoiceOutput = {
  id: "o1",
  engine: "omnivoice",
  mode: "voice",
  voice_id: "v1",
  voice_name: "Helena — close",
  voice: "Helena — close",
  text: "A cidade fecha os olhos devagar. Eu conto os passos até te encontrar.",
  text_preview: "A cidade fecha os olhos devagar. Eu conto os passos até te encontrar.",
  language: "pt-PT",
  format: "mp3",
  duration_seconds: 8.9,
  generation_seconds: 2.7,
  rtf: 0.303,
  seed: 438921,
  timeline_count: 4,
  size_bytes: 218_402,
  path: "voice/outputs/2c7e1a55/chapter-03.mp3",
  created_at: new Date(Date.now() - 20 * 60_000).toISOString(),
};

const demoResult = {
  ...sampleVoiceOutput,
  message: "Generated with OmniVoice · cloned voice",
};

const fallbackCatalog: any = {
  ...demoVoiceCatalog,
  popular_languages: ["pt-PT", "pt-BR", "en", "es", "fr", "de", "it", "ja"],
  variants: [
    { id: "pt-PT", name: "Portuguese (Portugal)", variant_of: "pt" },
    { id: "pt-BR", name: "Portuguese (Brazil)", variant_of: "pt" },
  ],
  defaults: {
    engine: "omnivoice",
    mode: "voice",
    speed: 1,
    num_step: 32,
    guidance_scale: 2,
    t_shift: 0.5,
    denoise: true,
    preprocess_prompt: true,
    postprocess_output: true,
    format: "wav",
    normalize_text: false,
    pitch: 0,
    normalize_audio: false,
  },
  options: { languages: demoVoiceCatalog.languages.length, preview_text: "Há dias em que a cidade parece feita de vidro." },
  advanced_defaults: { duration: null },
};

const catalog = ref<any>(fallbackCatalog);
const voices = ref<any[]>([]);
const piperVoices = ref<any[]>([]);
const outputs = ref<any[]>([]);
const tab = ref("studio");
const advancedOpen = ref(true);
const instructOpen = ref(false);
const busy = ref(false);
const loading = ref(false);

const form = reactive({
  engine: "omnivoice",
  mode: "voice",
  voice_id: "v1",
  piper_voice: "pt-PT-tugao",
  language: "pt-PT",
  language_variant: "",
  speed: 1,
  num_step: 32,
  guidance_scale: 2,
  t_shift: 0.5,
  denoise: true,
  preprocess_prompt: true,
  postprocess_output: true,
  seed: 438921 as number | null,
  format: "wav",
  normalize_text: false,
  pitch: 0,
  normalize_audio: false,
  duration: null as number | null,
  text: DEMO ? DEMO_SCRIPT : "",
  instruct: "",
});

const textareaEl = ref<HTMLTextAreaElement | null>(null);
const languageSearch = ref("");
const languageOpen = ref(false);
let languageBlurTimer: number | undefined;

const result = ref<any>(DEMO ? demoResult : null);
const activeJobId = ref("");
const activeKind = ref<"tts" | "batch" | "train" | "preview" | "transcribe" | "piper_install">("tts");
const submittedJob = ref<Job | null>(null);
const processedJobId = ref("");
let pollTimer: number | undefined;
let demoProgressTimer: number | undefined;
let demoStepTimer: number | undefined;
let previewVoiceId = ref("");
let previewId = ref("");
let trainTargetVoiceId = ref("");

const pickerOpen = ref(false);
const importInput = ref<HTMLInputElement | null>(null);
const trainOpen = ref(false);
const trainMode = ref<"create" | "retrain">("create");
const trainBusy = ref(false);
const trainForm = reactive({
  name: "",
  language: "pt-PT",
  transcript: "",
  preprocess_prompt: true,
  consent: false,
  description: "",
});
const trainAudioPath = ref("");
const trainAudioName = ref("");
const recordedBlob = ref<Blob | null>(null);
const recordedUrl = ref("");

const recording = ref(false);
const level = ref(0);
let mediaRecorder: MediaRecorder | null = null;
let mediaStream: MediaStream | null = null;
let analyser: AnalyserNode | null = null;
let audioContext: AudioContext | null = null;
let meterFrame = 0;
let recordingChunks: BlobPart[] = [];

const renameOpen = ref(false);
const renameTarget = ref<any>(null);
const renameValue = ref("");
const deleteOpen = ref(false);
const deleteTarget = ref<any>(null);
const outputDeleteOpen = ref(false);
const outputDeleteTarget = ref<any>(null);
const historySearch = ref("");
const historyFormat = ref("all");
const expandedOutputId = ref(DEMO ? "o1" : "");

const batchText = ref(
  DEMO
    ? "A cidade fecha os olhos devagar. Eu conto os passos até te encontrar.\n\nNocturno, nocturno. Dança comigo no escuro.\n\nHá luz nas janelas que ninguém apagou."
    : "",
);
const batchSplit = ref<"blank-line" | "line">("blank-line");
const batchMode = ref<"auto" | "voice" | "design">("voice");
const demoBatchLines = DEMO ? batchText.value.split(/\r?\n\s*\r?\n/).map((item) => item.trim()).filter(Boolean) : [];
const batchResults = ref<any[]>(
  DEMO
    ? demoVoiceOutputs.map((output, index) => {
        const text = demoBatchLines[index] || output.text;
        return { ...normalizeOutput(output), text, text_preview: text };
      })
    : [],
);
const zipLoading = ref(false);

const designAttrs = reactive({
  gender: "female",
  age: "adult",
  pitch: "warm",
  style: "narrator",
  accent: "british",
  dialect: "any",
});
const designText = ref(buildDesignInstruct(designAttrs));
const designScript = ref(DEMO ? "Há dias em que a cidade parece feita de vidro. [breath] E tudo o que tocamos fica." : "");

const piperInstalling = ref("");

const AVATAR_GRADIENTS = [
  "linear-gradient(135deg, #8b5cf6, #22d3ee)",
  "linear-gradient(135deg, #f59e0b, #fb7185)",
  "linear-gradient(135deg, #22d3ee, #34d399)",
  "linear-gradient(135deg, #6366f1, #a78bfa)",
  "linear-gradient(135deg, #fb7185, #f59e0b)",
];

const tabs = computed(() => [
  { id: "studio", label: "Studio" },
  { id: "voices", label: "Voices", count: voices.value.length },
  { id: "design", label: "Design" },
  { id: "batch", label: "Batch" },
  { id: "history", label: "History", count: outputs.value.length },
  { id: "builtin", label: "Built-in", count: piperVoices.value.length },
]);

const languages = computed<Array<{ id: string; name: string }>>(() => {
  const raw = catalog.value.languages || [];
  const items = raw.map((item: any) => {
    if (typeof item === "string") return { id: item, name: item };
    return { id: String(item.id || item.code || ""), name: String(item.name || item.label || item.id || "") };
  });
  if (!items.some((item: any) => item.id === "pt")) {
    items.splice(5, 0, { id: "pt", name: "Portuguese (generic)" });
  }
  return items.filter((item: any) => item.id);
});

const filteredLanguages = computed(() => {
  const needle = languageSearch.value.trim().toLowerCase();
  if (!needle) return languages.value;
  return languages.value.filter((item) => `${item.name} ${item.id}`.toLowerCase().includes(needle));
});

const languageCount = computed(() => catalog.value.options?.languages || languages.value.length);
const isPortuguese = computed(() => String(form.language || "").toLowerCase().startsWith("pt"));
const scriptSentences = computed(() => form.text.split(/[.!?…]+/).map((item) => item.trim()).filter(Boolean).length);
const selectedVoice = computed(() => voices.value.find((voice) => voice.id === form.voice_id) || voices.value[0] || null);
const piperAvailable = computed(() => piperVoices.value.filter((voice) => voice.available).length);
const piperLanguageFilter = ref("all");
const piperGenderFilter = ref("all");
const piperLanguageOptions = computed(() => {
  const seen = new Map<string, string>();
  for (const voice of piperVoices.value) {
    if (!seen.has(voice.language)) seen.set(voice.language, voice.language_name || languageLabel(voice.language));
  }
  return [...seen.entries()].map(([id, label]) => ({ id, label }));
});
const filteredPiperVoices = computed(() =>
  piperVoices.value.filter((voice) => {
    if (piperLanguageFilter.value !== "all" && voice.language !== piperLanguageFilter.value) return false;
    if (piperGenderFilter.value !== "all" && voice.gender !== piperGenderFilter.value) return false;
    return true;
  }),
);
const piperEngine = computed(() => (catalog.value.engines || []).find((engine: any) => engine.id === "piper") || null);
const omniEngine = computed(() => (catalog.value.engines || []).find((engine: any) => engine.id === "omnivoice") || null);
const batchItems = computed(() => {
  const raw = batchText.value || "";
  if (batchSplit.value === "line") {
    return raw.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  }
  return raw.split(/\r?\n\s*\r?\n/).map((item) => item.trim()).filter(Boolean);
});
const batchCharCount = computed(() => batchText.value.length);
const historyFiltered = computed(() => {
  const needle = historySearch.value.trim().toLowerCase();
  return outputs.value.filter((output) => {
    if (historyFormat.value !== "all" && output.format !== historyFormat.value) return false;
    if (!needle) return true;
    return `${output.text || ""} ${output.voice_name || ""} ${output.language || ""}`.toLowerCase().includes(needle);
  });
});
const activeJob = computed<Job | null>(() => {
  if (!activeJobId.value) return submittedJob.value;
  return jobs.byId(activeJobId.value) || submittedJob.value;
});
const activeRunning = computed(() =>
  activeJob.value ? ["queued", "running", "canceling"].includes(activeJob.value.status) : false,
);

function normalizeVoice(voice: any) {
  return {
    ...voice,
    id: String(voice.id || ""),
    name: voice.name || "Untitled voice",
    language: voice.language || "",
    duration_seconds: Number(voice.duration_seconds || 0),
    transcript: voice.transcript || "",
    has_preview: Boolean(voice.has_preview || voice.preview_url || voice.preview),
    preview_url: voice.preview_url || voice.preview || "",
    created_at: voice.created_at || new Date().toISOString(),
  };
}

function ensureVoiceSelection() {
  if (!voices.value.some((voice) => voice.id === form.voice_id)) {
    form.voice_id = voices.value[0]?.id || "";
  }
  if (!voices.value.length && form.mode === "voice") form.mode = "auto";
}

function normalizeOutput(output: any) {
  const path = output.path || output.audio_path || "";
  const duration = Number(output.duration_seconds || 0);
  const generation = Number(output.generation_seconds || 0);
  return {
    ...output,
    id: String(output.id || path || Math.random()),
    path,
    url: output.url || (path ? fileUrl(path) : ""),
    text: output.text || output.text_preview || "",
    text_preview: output.text_preview || output.text || "",
    duration_seconds: duration,
    generation_seconds: generation,
    rtf: output.rtf ?? (duration && generation ? generation / duration : null),
    format: output.format || (path.split(".").pop() || "wav"),
    voice_name: output.voice_name || output.voice || "auto",
    created_at: output.created_at || new Date().toISOString(),
  };
}

function languageLabel(id?: string | null) {
  if (!id) return "Auto";
  const match = languages.value.find((item) => item.id === id);
  return match?.name || id;
}

function initials(name: string) {
  return (name || "?")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

function avatarStyle(name: string, index = 0) {
  let hash = 0;
  for (let position = 0; position < (name || "").length; position++) hash = (hash * 31 + name.charCodeAt(position)) | 0;
  const gradient = AVATAR_GRADIENTS[Math.abs(hash + index) % AVATAR_GRADIENTS.length];
  return { background: gradient };
}

function formatRtf(value: any) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number.toFixed(2) : "—";
}

function formatSize(bytes?: number) {
  if (!bytes) return "—";
  return bytes > 1024 ** 2 ? `${(bytes / 1024 ** 2).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
}

function previewSrc(voice: any) {
  if (voice.preview_url) return voice.preview_url;
  if (DEMO) return voice.preview || "/demo/voice-preview.wav";
  return `/api/voice/voices/${voice.id}/preview`;
}

function openLanguage() {
  window.clearTimeout(languageBlurTimer);
  languageSearch.value = "";
  languageOpen.value = true;
}

function closeLanguage() {
  languageBlurTimer = window.setTimeout(() => (languageOpen.value = false), 120);
}

function chooseLanguage(language: { id: string; name: string }) {
  form.language = language.id;
  form.language_variant = language.id === "pt-PT" || language.id === "pt-BR" ? language.id : "";
  languageOpen.value = false;
}

function insertTag(tag: string) {
  const textarea = textareaEl.value;
  if (!textarea) {
    form.text = `${form.text}${form.text.endsWith(" ") ? "" : " "}${tag}`;
    return;
  }
  const start = textarea.selectionStart ?? form.text.length;
  const end = textarea.selectionEnd ?? start;
  const before = form.text.slice(0, start);
  const after = form.text.slice(end);
  const spacer = before && !before.endsWith(" ") ? " " : "";
  form.text = `${before}${spacer}${tag}${after.startsWith(" ") || !after ? "" : " "}${after}`;
  nextTick(() => {
    textarea.focus();
    const caret = start + spacer.length + tag.length;
    textarea.setSelectionRange(caret, caret);
  });
}

function randomSeed() {
  form.seed = Math.floor(Math.random() * 4_294_967_295);
}

function buildBaseParams() {
  const isPiper = form.engine === "piper";
  const mode = isPiper ? "auto" : form.mode;
  return {
    engine: form.engine,
    mode,
    voice_id: !isPiper && mode === "voice" ? form.voice_id || null : null,
    piper_voice: isPiper ? form.piper_voice || null : null,
    instruct: !isPiper && mode === "design" ? (form.instruct || null) : null,
    language: form.language || null,
    language_variant: form.language_variant || null,
    speed: Number(form.speed),
    num_step: Number(form.num_step),
    guidance_scale: Number(form.guidance_scale),
    t_shift: Number(form.t_shift),
    denoise: form.denoise,
    preprocess_prompt: form.preprocess_prompt,
    postprocess_output: form.postprocess_output,
    seed: form.seed === null || form.seed === undefined || Number.isNaN(Number(form.seed)) ? null : Number(form.seed),
    format: form.format,
    normalize_text: form.normalize_text,
    pitch: isPiper ? Number(form.pitch) : 0,
    normalize_audio: form.normalize_audio,
    duration: form.duration || null,
  };
}

function buildDesignInstruct(attrs: any) {
  const pieces: string[] = [];
  if (attrs.gender !== "any") pieces.push(`${attrs.gender}`);
  if (attrs.age !== "any") pieces.push(`${attrs.age}`);
  if (attrs.pitch !== "any") pieces.push(`${attrs.pitch} pitch`);
  if (attrs.style !== "any") pieces.push(`${attrs.style} delivery`);
  if (attrs.accent !== "any") pieces.push(`${attrs.accent} English accent`);
  if (attrs.dialect !== "any") pieces.push(`${attrs.dialect} Mandarin`);
  const profile = pieces.length ? pieces.join(", ") : "natural, versatile";
  const nuance =
    attrs.style === "whisper"
      ? "Speak very softly, close to the microphone, with audible breath and long pauses."
      : attrs.style === "cinematic"
        ? "Speak slowly with weight and drama, letting each sentence land before the next."
        : attrs.style === "energetic"
          ? "Speak with bright energy, crisp consonants and an upbeat, confident rhythm."
          : "Speak clearly and naturally, with warm pauses and an intimate, close-mic presence.";
  return `A ${profile} voice. ${nuance}`;
}

function syncDesignInstruct() {
  designText.value = buildDesignInstruct(designAttrs);
}

function applyDesignPreset(preset: any) {
  Object.assign(designAttrs, preset.attrs);
  syncDesignInstruct();
}

watch(
  () => [form.engine, form.mode],
  () => {
    if (form.engine === "piper") {
      form.mode = "auto";
      form.format = "mp3";
    } else if (form.mode === "design") {
      instructOpen.value = true;
    }
  },
);

watch(
  () => languageOpen.value,
  (open) => {
    if (!open) languageSearch.value = "";
  },
);

watch(
  activeJob,
  (job) => {
    if (!job || job.id === processedJobId.value) return;
    if (["queued", "running", "canceling"].includes(job.status)) return;
    processedJobId.value = job.id;
    if (job.status === "completed") {
      handleJobCompleted(job);
    } else if (job.status === "failed") {
      if (activeKind.value === "piper_install") piperInstalling.value = "";
      toasts.error(job.error || "Voice job failed");
    } else if (job.status === "canceled") {
      if (activeKind.value === "piper_install") piperInstalling.value = "";
      toasts.info("Voice job canceled");
    }
  },
  { deep: true },
);

async function handleJobCompleted(job: Job) {
  if (activeKind.value === "tts") {
    const data: any = job.result?.data || {};
    const output = data.output || data;
    if (output?.path) {
      const normalized = normalizeOutput(output);
      result.value = normalized;
      if (!outputs.value.some((item) => item.id === normalized.id)) outputs.value.unshift(normalized);
      toasts.success("Speech generated");
    }
    if (!DEMO) loadOutputs();
  } else if (activeKind.value === "batch") {
    const data: any = job.result?.data || {};
    const items = data.items || [];
    batchResults.value = items.map(normalizeOutput);
    if (!DEMO) loadOutputs();
    toasts.success(`Batch complete · ${items.length} take(s)`);
  } else if (activeKind.value === "train") {
    const voice = job.result?.data?.voice;
    if (voice) {
      const normalized = normalizeVoice(voice);
      const index = voices.value.findIndex((item) => item.id === normalized.id);
      if (index >= 0) voices.value[index] = normalized;
      else voices.value.unshift(normalized);
      form.voice_id = normalized.id;
    } else if (!DEMO) {
      await loadVoices();
    }
    trainOpen.value = false;
    toasts.success(trainMode.value === "retrain" ? "Voice retrained" : "Voice profile ready");
  } else if (activeKind.value === "preview") {
    previewId.value = previewVoiceId.value;
    if (!DEMO) await loadVoices();
    toasts.success("Voice preview ready");
  } else if (activeKind.value === "transcribe") {
    const text = job.result?.data?.text;
    if (text) {
      trainForm.transcript = text;
      toasts.success("Transcript added");
    }
  } else if (activeKind.value === "piper_install") {
    const data: any = job.result?.data || {};
    const items = data.items || [];
    piperInstalling.value = "";
    if (!DEMO) await loadCatalog();
    const names = items.map((item: any) => item.name || item.id).filter(Boolean).join(", ");
    toasts.success(names ? `${names} voice${items.length > 1 ? "s" : ""} installed` : "Voice download complete");
  }
}

function trackJob(raw: any, kind: typeof activeKind.value, meta?: { previewVoiceId?: string }) {
  const id = raw?.id || raw?.job_id;
  if (!id) throw new Error("The service did not return a job id");
  const normalized = { ...raw, id } as Job;
  submittedJob.value = normalized;
  activeJobId.value = id;
  activeKind.value = kind;
  processedJobId.value = "";
  if (kind === "preview") previewVoiceId.value = meta?.previewVoiceId || "";
  jobs.upsert(normalized);
  if (!DEMO) startPollingJob(id);
  return normalized;
}

function startPollingJob(id: string) {
  window.clearTimeout(pollTimer);
  const tick = async () => {
    try {
      const fresh = await api.get<Job>(`/jobs/${id}`);
      jobs.upsert(fresh);
      if (!["queued", "running", "canceling"].includes(fresh.status)) return;
    } catch {
      // SSE usually keeps the job fresh; polling is only a fallback.
    }
    pollTimer = window.setTimeout(tick, 2600);
  };
  pollTimer = window.setTimeout(tick, 2200);
}

function simulateJob(kind: typeof activeKind.value, title: string, jobResult: any, action = "tts") {
  window.clearInterval(demoProgressTimer);
  const id = `job_demo_${Math.random().toString(36).slice(2, 10)}`;
  const now = new Date().toISOString();
  const base: Job = {
    id,
    component: "voice",
    action,
    title,
    status: "running",
    stage: kind === "train" ? "Preparing reference" : kind === "batch" ? "Splitting script" : "Synthesising",
    message: "Rendering locally in the voice worker…",
    progress: 6,
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
  activeJobId.value = id;
  activeKind.value = kind;
  processedJobId.value = "";
  jobs.upsert(base);
  let progress = 6;
  demoProgressTimer = window.setInterval(() => {
    progress = Math.min(96, progress + 7 + Math.random() * 9);
    const running: Job = {
      ...base,
      progress,
      stage: kind === "train" ? "Building prompt" : kind === "batch" ? "Synthesising items" : "Diffusing speech",
      message: kind === "train" ? "Extracting speaker embedding and building the prompt…" : "Rendering waveform and timelines…",
      updated_at: new Date().toISOString(),
    };
    submittedJob.value = running;
    jobs.upsert(running);
    if (progress >= 96) {
      window.clearInterval(demoProgressTimer);
      const finished: Job = {
        ...running,
        status: "completed",
        stage: "Complete",
        message: "Demo job complete.",
        progress: 100,
        result: jobResult,
        finished_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      submittedJob.value = finished;
      jobs.upsert(finished);
    }
  }, 420);
}

async function generateTts() {
  if (!form.text.trim()) {
    toasts.error("Write something to speak first");
    return;
  }
  if (form.text.length > (catalog.value.limits?.max_input_chars || 8000)) {
    toasts.error("The script is longer than the engine limit");
    return;
  }
  if (form.engine === "omnivoice" && form.mode === "voice" && !form.voice_id) {
    toasts.error("Choose a trained voice profile");
    return;
  }
  busy.value = true;
  try {
    const text = form.text.trim();
    if (DEMO) {
      const take = {
        ...demoResult,
        id: `demo-${Date.now()}`,
        text,
        text_preview: text.slice(0, 180),
        voice_name: form.engine === "piper" ? form.piper_voice : selectedVoice.value?.name || "Auto voice",
        voice: form.engine === "piper" ? form.piper_voice : selectedVoice.value?.name || "Auto voice",
        engine: form.engine,
        mode: form.mode,
        language: form.language,
        format: form.format,
        seed: form.seed,
        duration_seconds: Math.max(4.2, text.split(/\s+/).length * 0.42),
        generation_seconds: Math.max(1.8, text.split(/\s+/).length * 0.11),
        rtf: 0.27,
        created_at: new Date().toISOString(),
        path: `voice/outputs/demo-${Date.now()}/take.${form.format}`,
      };
      simulateJob("tts", `Voice · ${text.slice(0, 64)}`, {
        message: "Speech generation complete.",
        files: [{ path: take.path, kind: "audio", mime: `audio/${form.format}`, name: `take.${form.format}`, size: 219_406 }],
        data: { output: take, output_id: take.id, path: take.path, duration_seconds: take.duration_seconds, format: take.format },
      });
      toasts.info("Rendering a demo voice take…");
      return;
    }
    const payload = { ...buildBaseParams(), text };
    const raw = await api.post<any>("/voice/tts", payload);
    trackJob(raw, "tts");
    toasts.info("Voice generation queued");
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    busy.value = false;
  }
}

async function previewVoice(voice: any) {
  previewId.value = previewId.value === voice.id ? "" : voice.id;
  if (DEMO || voice.has_preview) return;
  try {
    const raw = await api.post<any>(`/voice/voices/${voice.id}/preview`, { text: "" });
    trackJob(raw, "preview", { previewVoiceId: voice.id });
    toasts.info("Rendering a preview take");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

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

function openTrain(voice?: any) {
  trainMode.value = voice ? "retrain" : "create";
  trainTargetVoiceId.value = voice?.id || "";
  trainForm.name = voice?.name || "";
  trainForm.language = voice?.language || form.language || "pt-PT";
  trainForm.transcript = voice?.transcript || "";
  trainForm.description = voice?.description || "";
  trainForm.preprocess_prompt = true;
  trainForm.consent = false;
  trainAudioPath.value = "";
  trainAudioName.value = "";
  clearRecorded();
  trainOpen.value = true;
}

function onTrainAudioSelected(path: string, file: any) {
  trainAudioPath.value = path;
  trainAudioName.value = file?.name || path.split("/").pop() || "reference.wav";
  recordedBlob.value = null;
  if (recordedUrl.value) URL.revokeObjectURL(recordedUrl.value);
  recordedUrl.value = "";
}

function clearAudioSource() {
  trainAudioPath.value = "";
  trainAudioName.value = "";
  clearRecorded();
}

function clearRecorded() {
  recordedBlob.value = null;
  if (recordedUrl.value) URL.revokeObjectURL(recordedUrl.value);
  recordedUrl.value = "";
  level.value = 0;
}

async function toggleRecording() {
  if (recording.value) {
    stopRecording();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    toasts.error("This browser does not expose microphone recording");
    return;
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordingChunks = [];
    mediaRecorder = new MediaRecorder(mediaStream);
    mediaRecorder.ondataavailable = (event) => {
      if (event.data.size) recordingChunks.push(event.data);
    };
    mediaRecorder.onstop = () => {
      const blob = new Blob(recordingChunks, { type: mediaRecorder?.mimeType || "audio/webm" });
      recordedBlob.value = blob;
      recordedUrl.value = URL.createObjectURL(blob);
      trainAudioPath.value = "";
      trainAudioName.value = "browser-recording.webm";
      stopMeter();
    };
    mediaRecorder.start();
    recording.value = true;
    audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(mediaStream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    meterLoop();
  } catch (error: any) {
    toasts.error(`Microphone unavailable: ${error.message || error}`);
    stopRecording();
  }
}

function meterLoop() {
  if (!analyser) return;
  const data = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(data);
  let peak = 0;
  for (const value of data) peak = Math.max(peak, Math.abs(value - 128));
  level.value = Math.min(100, Math.round((peak / 128) * 150));
  meterFrame = requestAnimationFrame(meterLoop);
}

function stopMeter() {
  cancelAnimationFrame(meterFrame);
  analyser = null;
  audioContext?.close().catch(() => {});
  audioContext = null;
  level.value = 0;
}

function stopRecording() {
  recording.value = false;
  if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
  mediaRecorder = null;
  mediaStream?.getTracks().forEach((track) => track.stop());
  mediaStream = null;
  stopMeter();
}

async function resolveTrainFile(): Promise<File | null> {
  if (recordedBlob.value) {
    return new File([recordedBlob.value], trainAudioName.value || "recording.webm", {
      type: recordedBlob.value.type || "audio/webm",
    });
  }
  if (!trainAudioPath.value) return null;
  const response = await fetch(fileUrl(trainAudioPath.value), { credentials: "include" });
  if (!response.ok) throw new Error("Could not read the selected reference audio");
  const blob = await response.blob();
  const name = trainAudioName.value || trainAudioPath.value.split("/").pop() || "reference.wav";
  return new File([blob], name, { type: blob.type || "audio/wav" });
}

async function transcribeReference() {
  if (DEMO) {
    trainForm.transcript =
      "Há dias em que a cidade parece feita de vidro. O rio lembra-se de tudo o que lhe contamos, e a noite guarda o resto.";
    toasts.success("Demo transcript inserted");
    return;
  }
  try {
    const file = await resolveTrainFile();
    if (!file) {
      toasts.error("Choose or record reference audio first");
      return;
    }
    const formData = new FormData();
    formData.append("audio", file);
    const raw = await api.post<any>("/voice/transcribe", formData);
    trackJob(raw, "transcribe");
    toasts.info("Transcription queued");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function submitTrain() {
  if (!trainForm.name.trim()) {
    toasts.error("Give this voice a name");
    return;
  }
  if (!trainForm.consent) {
    toasts.error("Confirm that you own this voice or have permission to clone it");
    return;
  }
  if (trainMode.value === "create" && !trainAudioPath.value && !recordedBlob.value) {
    toasts.error("Choose a reference clip or record one in the browser");
    return;
  }
  trainBusy.value = true;
  try {
    if (DEMO) {
      const voice = {
        id: trainTargetVoiceId.value || `v${Date.now()}`,
        name: trainForm.name.trim(),
        language: trainForm.language,
        transcript: trainForm.transcript,
        duration_seconds: 8.4,
        has_preview: false,
        preview_url: "",
        created_at: new Date().toISOString(),
        description: trainForm.description,
      };
      simulateJob(
        "train",
        `${trainMode.value === "retrain" ? "Retrain" : "Train"} voice · ${voice.name}`,
        {
          message: "Voice profile ready.",
          files: [],
          data: { voice, voice_id: voice.id },
        },
        "train",
      );
      trainOpen.value = false;
      toasts.info("Training the demo voice profile…");
      return;
    }
    const file = await resolveTrainFile();
    const formData = new FormData();
    formData.append("name", trainForm.name.trim());
    formData.append("consent", "true");
    formData.append("preprocess_prompt", String(trainForm.preprocess_prompt));
    if (trainForm.language) formData.append("language", trainForm.language);
    if (trainForm.transcript.trim()) formData.append("transcript", trainForm.transcript.trim());
    if (trainForm.description.trim()) formData.append("description", trainForm.description.trim());
    if (file) formData.append("audio", file);
    const endpoint =
      trainMode.value === "retrain" && trainTargetVoiceId.value
        ? `/voice/voices/${trainTargetVoiceId.value}/retrain`
        : "/voice/train";
    const raw = await api.post<any>(endpoint, formData);
    trackJob(raw, "train");
    trainOpen.value = false;
    toasts.info(trainMode.value === "retrain" ? "Retraining queued" : "Voice training queued");
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    trainBusy.value = false;
  }
}

async function importVoiceZip(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (DEMO) {
    toasts.success(`Imported ${file.name} (demo)`);
    return;
  }
  if (
    !window.confirm(
      "Only import voice profiles you own or have explicit permission to use. Continue with this archive?",
    )
  ) {
    return;
  }
  try {
    const formData = new FormData();
    formData.append("archive", file);
    formData.append("consent", "true");
    const voice = await api.post<any>("/voice/voices/import", formData);
    const normalized = normalizeVoice(voice);
    voices.value.unshift(normalized);
    toasts.success(`Imported ${normalized.name}`);
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function openRename(voice: any) {
  renameTarget.value = voice;
  renameValue.value = voice.name;
  renameOpen.value = true;
}

async function saveRename() {
  if (!renameTarget.value || !renameValue.value.trim()) return;
  try {
    if (!DEMO) {
      await api.patch(`/voice/voices/${renameTarget.value.id}`, { name: renameValue.value.trim() });
    }
    renameTarget.value.name = renameValue.value.trim();
    renameOpen.value = false;
    toasts.success("Voice renamed");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function exportVoice(voice: any) {
  if (DEMO) {
    toasts.success(`Exported ${voice.name}.zip (demo)`);
    return;
  }
  window.open(`/api/voice/voices/${voice.id}/export`, "_blank", "noopener");
}

function askDeleteVoice(voice: any) {
  deleteTarget.value = voice;
  deleteOpen.value = true;
}

async function confirmDeleteVoice() {
  if (!deleteTarget.value) return;
  try {
    if (!DEMO) await api.delete(`/voice/voices/${deleteTarget.value.id}`);
    voices.value = voices.value.filter((voice) => voice.id !== deleteTarget.value.id);
    ensureVoiceSelection();
    deleteOpen.value = false;
    toasts.success("Voice deleted");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function askDeleteOutput(output: any) {
  outputDeleteTarget.value = output;
  outputDeleteOpen.value = true;
}

async function confirmDeleteOutput() {
  if (!outputDeleteTarget.value) return;
  try {
    if (!DEMO) await api.delete(`/voice/outputs/${outputDeleteTarget.value.id}`);
    outputs.value = outputs.value.filter((item) => item.id !== outputDeleteTarget.value.id);
    if (result.value?.id === outputDeleteTarget.value.id) result.value = outputs.value[0] || null;
    outputDeleteOpen.value = false;
    toasts.success("Output deleted");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function installPiper(voice: any) {
  piperInstalling.value = voice.id;
  try {
    if (DEMO) {
      voice.available = true;
      voice.size_bytes = 63_402_112;
      piperInstalling.value = "";
      toasts.success(`${voice.name} installed`);
      return;
    }
    const raw = await api.post<any>("/voice/piper/install", { voice_id: voice.id });
    trackJob(raw, "piper_install");
    toasts.info(`${voice.name} download queued — follow it in Jobs`);
  } catch (error: any) {
    piperInstalling.value = "";
    toasts.error(error.message);
  }
}

function usePiper(voice: any) {
  form.engine = "piper";
  form.piper_voice = voice.id;
  form.language = voice.language;
  form.mode = "auto";
  form.format = "mp3";
  tab.value = "studio";
  toasts.info(`${voice.name} selected in the studio`);
}

function setResultFromOutput(output: any) {
  result.value = normalizeOutput(output);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setDesignResult(resultValue: any) {
  result.value = normalizeOutput(resultValue);
}

async function generateDesign() {
  const script = designScript.value.trim();
  if (!script) {
    toasts.error("Add a line for the designed voice to read");
    return;
  }
  if (!designText.value.trim()) {
    toasts.error("Describe the voice first");
    return;
  }
  form.instruct = designText.value;
  busy.value = true;
  try {
    if (DEMO) {
      const take = {
        ...demoResult,
        id: `demo-design-${Date.now()}`,
        text: script,
        text_preview: script.slice(0, 180),
        voice_name: "Designed voice",
        voice: "Designed voice",
        mode: "design",
        instruct: designText.value,
        language: form.language,
        format: form.format,
        seed: form.seed,
        duration_seconds: Math.max(4.4, script.split(/\s+/).length * 0.44),
        generation_seconds: 2.4,
        rtf: 0.31,
        created_at: new Date().toISOString(),
        path: `voice/outputs/demo-design-${Date.now()}/take.${form.format}`,
      };
      simulateJob("tts", `Designed voice · ${script.slice(0, 52)}`, {
        message: "Speech generation complete.",
        files: [{ path: take.path, kind: "audio", mime: `audio/${form.format}`, name: `take.${form.format}`, size: 232_401 }],
        data: { output: take, path: take.path, duration_seconds: take.duration_seconds, format: take.format },
      });
      toasts.info("Rendering the designed voice…");
      return;
    }
    const payload = {
      ...buildBaseParams(),
      mode: "design",
      engine: "omnivoice",
      instruct: designText.value,
      text: script,
    };
    const raw = await api.post<any>("/voice/tts", payload);
    trackJob(raw, "tts");
    toasts.info("Designed voice queued");
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    busy.value = false;
  }
}

async function runBatch() {
  if (!batchItems.value.length) {
    toasts.error("Add at least one batch item");
    return;
  }
  if (batchItems.value.length > (catalog.value.limits?.batch_items || catalog.value.limits?.max_batch_items || 50)) {
    toasts.error("Too many batch items");
    return;
  }
  form.mode = batchMode.value;
  busy.value = true;
  try {
    if (DEMO) {
      const items = demoVoiceOutputs.slice(0, Math.min(3, batchItems.value.length)).map((item, index) => ({
        ...item,
        id: `demo-batch-${Date.now()}-${index}`,
        text: batchItems.value[index] || item.text,
        text_preview: (batchItems.value[index] || item.text).slice(0, 180),
        created_at: new Date().toISOString(),
        path: `voice/outputs/demo-batch-${index + 1}/take.${form.format}`,
        format: form.format,
      }));
      simulateJob(
        "batch",
        `Voice batch · ${batchItems.value.length} item(s)`,
        {
          message: `Batch complete: ${items.length} item(s).`,
          files: items.map((item) => ({ path: item.path, kind: "audio", mime: `audio/${item.format}`, name: item.path.split("/").pop(), size: 204_800 })),
          data: { items, count: items.length },
        },
        "batch",
      );
      toasts.info("Rendering the demo batch…");
      return;
    }
    const base: any = { ...buildBaseParams(), mode: batchMode.value };
    delete base.instruct;
    if (base.mode === "design") base.instruct = form.instruct || null;
    const payload = {
      ...base,
      items: batchItems.value,
      split_mode: batchSplit.value,
    };
    const raw = await api.post<any>("/voice/batch", payload);
    trackJob(raw, "batch");
    toasts.info("Voice batch queued");
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    busy.value = false;
  }
}

let crcTable: Uint32Array | null = null;
function crc32(bytes: Uint8Array) {
  if (!crcTable) {
    crcTable = new Uint32Array(256);
    for (let index = 0; index < 256; index++) {
      let value = index;
      for (let bit = 0; bit < 8; bit++) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
      crcTable[index] = value >>> 0;
    }
  }
  let crc = 0xffffffff;
  for (let index = 0; index < bytes.length; index++) crc = crcTable[(crc ^ bytes[index]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

async function downloadZip(filename: string, files: Array<{ name: string; path: string }>) {
  const encoder = new TextEncoder();
  const locals: any[] = [];
  const entries: Array<{ name: Uint8Array; crc: number; size: number; offset: number }> = [];
  let offset = 0;
  for (const file of files) {
    let data: Uint8Array;
    try {
      const response = await fetch(fileUrl(file.path), { credentials: "include" });
      if (!response.ok) throw new Error("missing");
      data = new Uint8Array(await response.arrayBuffer());
    } catch {
      data = encoder.encode(`Open Studio demo batch\n${file.path}\n`);
    }
    const name = encoder.encode(file.name);
    const crc = crc32(data);
    const now = new Date();
    const time = (now.getHours() << 11) | (now.getMinutes() << 5) | Math.floor(now.getSeconds() / 2);
    const date = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
    const header = new Uint8Array(30 + name.length);
    const view = new DataView(header.buffer);
    view.setUint32(0, 0x04034b50, true);
    view.setUint16(4, 20, true);
    view.setUint16(6, 0x0800, true);
    view.setUint16(8, 0, true);
    view.setUint16(10, time, true);
    view.setUint16(12, date, true);
    view.setUint32(14, crc, true);
    view.setUint32(18, data.length, true);
    view.setUint32(22, data.length, true);
    view.setUint16(26, name.length, true);
    view.setUint16(28, 0, true);
    header.set(name, 30);
    locals.push(header, data);
    entries.push({ name, crc, size: data.length, offset });
    offset += header.length + data.length;
  }
  const central: any[] = [];
  let centralSize = 0;
  for (const entry of entries) {
    const header = new Uint8Array(46 + entry.name.length);
    const view = new DataView(header.buffer);
    const now = new Date();
    const time = (now.getHours() << 11) | (now.getMinutes() << 5) | Math.floor(now.getSeconds() / 2);
    const date = ((now.getFullYear() - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
    view.setUint32(0, 0x02014b50, true);
    view.setUint16(4, 20, true);
    view.setUint16(6, 20, true);
    view.setUint16(8, 0x0800, true);
    view.setUint16(10, 0, true);
    view.setUint16(12, time, true);
    view.setUint16(14, date, true);
    view.setUint32(16, entry.crc, true);
    view.setUint32(20, entry.size, true);
    view.setUint32(24, entry.size, true);
    view.setUint16(28, entry.name.length, true);
    view.setUint16(30, 0, true);
    view.setUint16(32, 0, true);
    view.setUint16(34, 0, true);
    view.setUint16(36, 0, true);
    view.setUint32(38, 0, true);
    view.setUint32(42, entry.offset, true);
    header.set(entry.name, 46);
    central.push(header);
    centralSize += header.length;
  }
  const end = new Uint8Array(22);
  const endView = new DataView(end.buffer);
  endView.setUint32(0, 0x06054b50, true);
  endView.setUint16(4, 0, true);
  endView.setUint16(6, 0, true);
  endView.setUint16(8, entries.length, true);
  endView.setUint16(10, entries.length, true);
  endView.setUint32(12, centralSize, true);
  endView.setUint32(16, offset, true);
  endView.setUint16(20, 0, true);
  const blob = new Blob([...locals, ...central, end] as any, { type: "application/zip" });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(href), 3000);
}

async function downloadBatchZip() {
  if (!batchResults.value.length) {
    toasts.error("Nothing to archive yet");
    return;
  }
  zipLoading.value = true;
  try {
    await downloadZip(
      "openstudio-voice-batch.zip",
      batchResults.value.map((item, index) => ({
        name: `${String(index + 1).padStart(2, "0")}-${(item.voice_name || "take").replace(/[^a-z0-9]+/gi, "-")}.${item.format || "wav"}`,
        path: item.path,
      })),
    );
    toasts.success("Batch archive downloaded");
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    zipLoading.value = false;
  }
}

async function loadCatalog() {
  if (DEMO) return;
  try {
    const data = await api.get<any>("/voice/catalog");
    catalog.value = { ...fallbackCatalog, ...data };
    if (data.voices) voices.value = data.voices.map(normalizeVoice);
    if (data.piper_voices) piperVoices.value = data.piper_voices;
    if (data.defaults?.voice_id) form.voice_id = data.defaults.voice_id;
    ensureVoiceSelection();
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function loadVoices() {
  if (DEMO) return;
  try {
    const data = await api.get<{ items: any[] }>("/voice/voices");
    voices.value = (data.items || []).map(normalizeVoice);
    ensureVoiceSelection();
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function loadOutputs() {
  if (DEMO) return;
  loading.value = true;
  try {
    const data = await api.get<{ items: any[] }>("/voice/outputs?limit=100");
    outputs.value = (data.items || []).map(normalizeOutput);
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    loading.value = false;
  }
}

async function refreshAll() {
  busy.value = true;
  await Promise.all([loadCatalog(), loadVoices(), loadOutputs()]);
  busy.value = false;
}

onMounted(() => {
  if (!DEMO) {
    loadCatalog();
    loadVoices();
    loadOutputs();
    return;
  }
  voices.value = demoVoices.map(normalizeVoice);
  piperVoices.value = demoPiperVoices.map((voice: any) => ({
    ...voice,
    language_name: languageLabel(voice.language),
    quality: "medium",
    sample_rate: 22050,
    license: "CC0 / CC BY-NC-ND",
    description: `${voice.gender} ${voice.language} neural voice, 22.05 kHz.`,
    size_bytes: voice.available ? 63_402_112 : null,
  }));
  outputs.value = demoVoiceOutputs.map(normalizeOutput);
  result.value = normalizeOutput(demoResult);
});

onBeforeUnmount(() => {
  window.clearTimeout(pollTimer);
  window.clearTimeout(languageBlurTimer);
  window.clearInterval(demoProgressTimer);
  window.clearTimeout(demoStepTimer);
  stopRecording();
  clearAudioSource();
});
import ServiceNotice from "@/components/ServiceNotice.vue";
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="Voice · OmniVoice + Piper"
      title="Voice studio"
      subtitle="Clone a voice from a short reference, design one from a sentence, or use fast built-in Piper voices. Every TTS model runs locally in Docker and writes straight into shared storage."
    >
      <template #actions>
        <span class="chip success"><span class="dot online" /> All TTS in Docker</span>
        <span class="chip"><Layers :size="11" /> {{ catalog.limits?.max_input_chars || 8000 }} chars</span>
        <button class="btn btn-sm" @click="openTrain()"><Plus :size="13" /> Train a voice</button>
      </template>
    </PageHeader>

    <ServiceNotice
      :services="[{ name: 'voice', label: 'Voice' }]"
      title="This workspace needs Voice"
    />

    <div class="stat-grid" style="margin-bottom: 16px">
      <div class="stat">
        <div class="stat-label">Engines</div>
        <div class="stat-value">2</div>
        <div class="stat-sub">OmniVoice cloning · Piper ONNX</div>
      </div>
      <div class="stat">
        <div class="stat-label">Trained voices</div>
        <div class="stat-value">{{ voices.length }}</div>
        <div class="stat-sub">{{ piperAvailable }} Piper voices installed</div>
      </div>
      <div class="stat">
        <div class="stat-label">Languages</div>
        <div class="stat-value">{{ languageCount }}</div>
        <div class="stat-sub">Including European and Brazilian Portuguese</div>
      </div>
      <div class="stat">
        <div class="stat-label">Rendered takes</div>
        <div class="stat-value">{{ outputs.length }}</div>
        <div class="stat-sub">Shared history · WAV, MP3 and FLAC</div>
      </div>
    </div>

    <div class="row-between" style="margin-bottom: 16px; align-items: flex-start">
      <TabsBar v-model="tab" :tabs="tabs" />
      <span class="chip"><span class="dot" :class="omniEngine?.status === 'ready' || omniEngine?.status === 'ok' ? 'online' : 'busy'" /> {{ omniEngine?.device || "CUDA · voice worker" }}</span>
    </div>

    <section v-if="tab === 'studio'" class="stack">
      <div class="split split-wide">
        <div class="stack">
          <div class="panel">
            <div class="panel-head">
              <div>
                <h3>Script</h3>
                <p>Type or paste the performance. Non-verbal tags are spoken as directions where the engine supports them.</p>
              </div>
              <span class="chip">{{ form.text.length }} / {{ catalog.limits?.max_input_chars || 8000 }}</span>
            </div>
            <div class="panel-body stack" style="gap: 12px">
              <div class="row" style="gap: 6px">
                <span class="small muted">Try a sample</span>
                <button v-for="sample in SAMPLE_SCRIPTS" :key="sample.label" class="chip clickable" @click="form.text = sample.text">
                  {{ sample.label }}
                </button>
              </div>
              <textarea
                ref="textareaEl"
                v-model="form.text"
                class="textarea script-area"
                rows="7"
                :maxlength="catalog.limits?.max_input_chars || 8000"
                placeholder="Write the line, scene or chapter you want to hear…"
              />
              <div class="row-between">
                <div class="row" style="gap: 5px">
                  <span class="small muted" style="margin-right: 3px">Non-verbal tags</span>
                  <button v-for="tag in NONVERBAL_TAGS" :key="tag" class="chip clickable" @click="insertTag(tag)">{{ tag }}</button>
                </div>
                <span class="small muted">{{ scriptSentences }} sentences</span>
              </div>
            </div>
          </div>

          <div class="panel">
            <div class="panel-head">
              <div>
                <h3>Engine &amp; voice</h3>
                <p>OmniVoice handles cloning, design and auto voices. Piper is instant and runs entirely on CPU.</p>
              </div>
              <span class="badge success">{{ form.engine === "piper" ? "Piper" : "OmniVoice" }}</span>
            </div>
            <div class="panel-body">
              <div class="grid grid-2" style="gap: 13px">
                <div class="field">
                  <label>Engine</label>
                  <select v-model="form.engine" class="select">
                    <option value="omnivoice">OmniVoice · cloning + design</option>
                    <option value="piper">Piper · fast built-in voices</option>
                  </select>
                  <span class="hint">OmniVoice is lazy-loaded; Piper works even when the heavy engine is unavailable.</span>
                </div>
                <div class="field">
                  <label>Mode</label>
                  <select v-model="form.mode" class="select" :disabled="form.engine === 'piper'">
                    <option value="auto">Auto · neutral voice</option>
                    <option value="voice">Cloned voice · reference profile</option>
                    <option value="design">Design · describe the voice</option>
                  </select>
                  <span class="hint">{{ form.engine === "piper" ? "Piper always uses the selected built-in voice." : "Auto is the quickest way to hear the script." }}</span>
                </div>

                <div v-if="form.engine === 'omnivoice'" class="field">
                  <label>Voice profile <span class="small muted">{{ selectedVoice?.duration_seconds ? formatDuration(selectedVoice.duration_seconds) : "" }}</span></label>
                  <select v-model="form.voice_id" class="select" :disabled="form.mode !== 'voice'">
                    <option value="">Choose a trained profile…</option>
                    <option v-for="voice in voices" :key="voice.id" :value="voice.id">
                      {{ voice.name }} · {{ languageLabel(voice.language) }}
                    </option>
                  </select>
                  <span class="hint">Use a 3–10 second reference for the cleanest clone. Preview and retrain profiles in Voices.</span>
                </div>

                <div v-if="form.engine === 'piper'" class="field">
                  <label>Piper voice</label>
                  <select v-model="form.piper_voice" class="select">
                    <option v-for="voice in piperVoices" :key="voice.id" :value="voice.id" :disabled="!voice.available">
                      {{ voice.name }} · {{ languageLabel(voice.language) }} {{ voice.available ? "" : "· not installed" }}
                    </option>
                  </select>
                  <span class="hint">Install more voices from the Built-in tab. Piper supports WAV and MP3.</span>
                </div>

                <div v-if="form.engine === 'omnivoice' && form.mode === 'design'" class="field" style="grid-column: 1 / -1">
                  <label>Voice instruction</label>
                  <textarea v-model="form.instruct" class="textarea" rows="3" maxlength="600" placeholder="A warm adult female narrator with a British accent, speaking slowly and intimately…" />
                  <span class="hint">Or use the Design tab to compose this from attributes and presets.</span>
                </div>

                <div class="field combo">
                  <label>Language</label>
                  <div class="combo-input">
                    <Search :size="13" class="muted" />
                    <input
                      class="input"
                      :value="languageOpen ? languageSearch : languageLabel(form.language)"
                      placeholder="Search 646 languages…"
                      @focus="openLanguage"
                      @input="languageSearch = ($event.target as HTMLInputElement).value; languageOpen = true"
                      @blur="closeLanguage"
                    />
                  </div>
                  <div v-if="languageOpen" class="combo-dropdown" @mousedown.prevent>
                    <button
                      v-for="language in filteredLanguages"
                      :key="language.id"
                      class="combo-option"
                      :class="{ active: language.id === form.language }"
                      @mousedown.prevent="chooseLanguage(language)"
                    >
                      <span>{{ language.name }}</span>
                      <span class="mono muted small">{{ language.id }}</span>
                    </button>
                    <div v-if="!filteredLanguages.length" class="small muted" style="padding: 8px">No language matches.</div>
                  </div>
                  <span class="hint">pt-PT and pt-BR are separate regional variants.</span>
                </div>

                <div class="field">
                  <label>Regional variant <span class="small muted">optional</span></label>
                  <select v-model="form.language_variant" class="select" :disabled="!isPortuguese">
                    <option value="">None · follow the language</option>
                    <option value="pt-PT">Portuguese (Portugal)</option>
                    <option value="pt-BR">Portuguese (Brazil)</option>
                  </select>
                  <span class="hint">The reference clip carries the accent; the variant tags the output.</span>
                </div>

                <div class="field">
                  <label>Speed <span class="mono small">{{ Number(form.speed).toFixed(2) }}×</span></label>
                  <input v-model.number="form.speed" type="range" min="0.5" max="2" step="0.05" />
                  <span class="hint">0.5× – 2.0×; Piper stays within its fast native range.</span>
                </div>

                <div class="field">
                  <label>Quality steps</label>
                  <select v-model.number="form.num_step" class="select" :disabled="form.engine === 'piper'">
                    <option :value="16">16 · fast draft</option>
                    <option :value="32">32 · balanced</option>
                    <option :value="48">48 · highest detail</option>
                  </select>
                  <span class="hint">OmniVoice diffusion steps. More steps cost more time.</span>
                </div>

                <div class="field">
                  <label>Output format</label>
                  <select v-model="form.format" class="select">
                    <option value="wav">WAV · lossless</option>
                    <option value="mp3">MP3 · compact</option>
                    <option value="flac">FLAC · lossless compressed</option>
                  </select>
                  <span class="hint">Files are written under <span class="mono">voice/outputs/</span>.</span>
                </div>
              </div>
            </div>
            <div class="panel-footer" style="justify-content: space-between">
              <span class="small muted">
                {{ form.engine === "piper" ? "Piper · CPU" : form.mode === "auto" ? "Auto voice" : form.mode === "design" ? "Designed voice" : selectedVoice?.name || "No profile selected" }}
                · {{ languageLabel(form.language) }} · {{ form.format.toUpperCase() }}
              </span>
              <button class="btn btn-primary" :disabled="busy || activeRunning" @click="generateTts">
                <Loader2 v-if="busy" :size="14" class="spin" />
                <Sparkles v-else :size="14" />
                Generate speech
              </button>
            </div>
          </div>

          <div class="panel">
            <div class="panel-head" style="cursor: pointer" @click="advancedOpen = !advancedOpen">
              <div>
                <h3>Advanced controls</h3>
                <p>Diffusion quality, prompt processing, seed, loudness and Piper pitch.</p>
              </div>
              <span class="chip">
                <SlidersHorizontal :size="11" />
                {{ advancedOpen ? "Hide" : "Show" }}
                <ChevronRight :size="11" :style="{ transform: advancedOpen ? 'rotate(90deg)' : 'none', transition: '150ms' }" />
              </span>
            </div>
            <div v-if="advancedOpen" class="panel-body">
              <div class="grid grid-3" style="gap: 13px">
                <div class="field">
                  <label>Num step</label>
                  <input v-model.number="form.num_step" class="input" type="number" min="1" max="128" />
                </div>
                <div class="field">
                  <label>Guidance scale</label>
                  <input v-model.number="form.guidance_scale" class="input" type="number" min="0" max="20" step="0.1" />
                </div>
                <div class="field">
                  <label>Time shift</label>
                  <input v-model.number="form.t_shift" class="input" type="number" min="0" max="10" step="0.01" />
                </div>
                <div class="field">
                  <label>Seed <button class="chip clickable" style="padding: 1px 6px" @click="randomSeed">randomize</button></label>
                  <input v-model.number="form.seed" class="input mono" type="number" min="0" max="4294967295" placeholder="Random" />
                </div>
                <div class="field">
                  <label>Fixed duration <span class="small muted">optional</span></label>
                  <input v-model.number="form.duration" class="input" type="number" min="0.5" max="600" step="0.1" placeholder="Auto" />
                  <span class="hint">Force a duration in seconds instead of letting the model decide.</span>
                </div>
                <div class="field">
                  <label>Pitch <span class="small muted">Piper only</span></label>
                  <input v-model.number="form.pitch" class="input" type="number" min="-24" max="24" step="0.5" :disabled="form.engine !== 'piper'" />
                  <span class="hint">Bundled Piper voices do not declare pitch support; the service will reject it.</span>
                </div>
              </div>
              <div class="grid grid-2" style="gap: 0 24px; margin-top: 5px">
                <div>
                  <div class="switch-row">
                    <div><div class="switch-label">Denoise</div><div class="switch-hint">Clean the reference prompt before cloning.</div></div>
                    <button class="switch" :class="{ on: form.denoise }" @click="form.denoise = !form.denoise" />
                  </div>
                  <div class="switch-row">
                    <div><div class="switch-label">Preprocess reference prompt</div><div class="switch-hint">Trim silence and normalise the reference.</div></div>
                    <button class="switch" :class="{ on: form.preprocess_prompt }" @click="form.preprocess_prompt = !form.preprocess_prompt" />
                  </div>
                  <div class="switch-row">
                    <div><div class="switch-label">Postprocess output</div><div class="switch-hint">Remove clicks and smooth sentence joins.</div></div>
                    <button class="switch" :class="{ on: form.postprocess_output }" @click="form.postprocess_output = !form.postprocess_output" />
                  </div>
                </div>
                <div>
                  <div class="switch-row">
                    <div><div class="switch-label">Normalize text</div><div class="switch-hint">Expand numbers and abbreviations before speaking.</div></div>
                    <button class="switch" :class="{ on: form.normalize_text }" @click="form.normalize_text = !form.normalize_text" />
                  </div>
                  <div class="switch-row">
                    <div><div class="switch-label">Normalize loudness</div><div class="switch-hint">Apply dynaudnorm to the finished file.</div></div>
                    <button class="switch" :class="{ on: form.normalize_audio }" @click="form.normalize_audio = !form.normalize_audio" />
                  </div>
                  <div class="alert" style="margin-top: 8px">
                    <Zap :size="12" style="vertical-align: -2px; color: var(--warning)" />
                    All TTS happens inside the voice container. Nothing leaves your machine.
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <aside class="stack">
          <div class="panel">
            <div class="panel-head">
              <div>
                <h3>Latest result</h3>
                <p>{{ result ? `${result.voice_name || "Voice"} · ${relativeTime(result.created_at)}` : "Your next take lands here." }}</p>
              </div>
              <span v-if="result" class="badge success"><Check :size="10" /> Ready</span>
            </div>
            <div v-if="result" class="panel-body stack" style="gap: 12px">
              <AudioPlayer
                :src="result.path"
                :title="result.voice_name || 'Generated voice'"
                :subtitle="`${String(result.format || 'wav').toUpperCase()} · ${languageLabel(result.language)} · ${relativeTime(result.created_at)}`"
                :download-path="result.path"
              />
              <div class="result-meta">
                <div><span>Duration</span><strong>{{ formatDuration(result.duration_seconds) }}</strong></div>
                <div><span>RTF</span><strong>{{ formatRtf(result.rtf) }}</strong></div>
                <div><span>Format</span><strong>{{ String(result.format || "wav").toUpperCase() }}</strong></div>
                <div><span>Engine</span><strong style="text-transform: capitalize">{{ result.engine || "OmniVoice" }}</strong></div>
                <div><span>Seed</span><strong class="mono">{{ result.seed ?? "auto" }}</strong></div>
                <div><span>Timeline</span><strong>{{ result.timeline_count || 0 }} lines</strong></div>
              </div>
              <div v-if="result.text" class="script-preview">{{ result.text }}</div>
              <div class="row">
                <a class="btn btn-sm" :href="downloadUrl(result.path)"><Download :size="12" /> Download</a>
                <button class="btn btn-sm btn-ghost" style="margin-left: auto" @click="tab = 'history'"><History :size="12" /> History</button>
              </div>
            </div>
            <div v-else class="panel-body">
              <EmptyState :icon="AudioLines" title="No take yet" message="Write a script, pick a voice and generate. The finished audio, duration and real-time factor appear here." />
            </div>
          </div>

          <div v-if="activeJob" class="panel">
            <div class="panel-head">
              <div>
                <h3>Active job</h3>
                <p>{{ activeKind === "tts" ? "Speech synthesis" : activeKind === "piper_install" ? "Voice download" : activeKind }}</p>
              </div>
              <span class="badge running">{{ Math.round(activeJob.progress) }}%</span>
            </div>
            <div class="panel-body">
              <JobCard :job="activeJob" compact @cancel="cancelActive" />
            </div>
          </div>

          <div class="panel">
            <div class="panel-head">
              <div><h3>Recent outputs</h3><p>{{ outputs.length }} takes in the shared history.</p></div>
              <button class="btn btn-sm btn-ghost" @click="tab = 'history'">All <ChevronRight :size="12" /></button>
            </div>
            <div class="panel-body tight">
              <div v-for="output in outputs.slice(0, 4)" :key="output.id" class="list-item" style="padding: 8px 6px">
                <button class="icon-btn" title="Load in result" @click="setResultFromOutput(output)"><Play :size="14" /></button>
                <div class="grow" style="min-width: 0">
                  <div class="small strong truncate">{{ output.text_preview || output.text || "Generated audio" }}</div>
                  <div class="small muted truncate">{{ output.voice_name }} · {{ output.format?.toUpperCase() }} · {{ formatDuration(output.duration_seconds) }}</div>
                </div>
                <span class="small muted nowrap">{{ relativeTime(output.created_at) }}</span>
              </div>
              <div v-if="!outputs.length" class="small muted" style="padding: 10px">Nothing rendered yet.</div>
            </div>
          </div>

          <div class="panel">
            <div class="panel-head">
              <div><h3>Engine health</h3><p>Both engines are local Docker workers.</p></div>
              <Gauge :size="16" class="muted" />
            </div>
            <div class="panel-body stack" style="gap: 9px">
              <div class="row-between small">
                <span class="row" style="gap: 6px"><span class="dot online" /> OmniVoice</span>
                <span class="muted">{{ omniEngine?.device || "loading" }}</span>
              </div>
              <div class="row-between small">
                <span class="row" style="gap: 6px"><span class="dot online" /> Piper</span>
                <span class="muted">{{ piperAvailable }}/{{ piperVoices.length }} voices</span>
              </div>
              <div class="progress thin"><span style="width: 100%" /></div>
              <span class="small muted">646 languages exposed by OmniVoice; this catalog indexes the most-used set.</span>
            </div>
          </div>
        </aside>
      </div>
    </section>

    <section v-else-if="tab === 'voices'" class="stack">
      <div class="row-between">
        <div>
          <h2 style="font-size: 20px">Voice library</h2>
          <p class="small muted" style="margin-top: 4px">Reusable reference profiles with consent, transcripts and preview takes.</p>
        </div>
        <div class="row">
          <button class="btn btn-sm" @click="importInput?.click()"><Upload :size="13" /> Import ZIP</button>
          <button class="btn btn-sm btn-primary" @click="openTrain()"><Plus :size="13" /> Train a voice</button>
          <input ref="importInput" type="file" accept=".zip,application/zip" hidden @change="importVoiceZip" />
        </div>
      </div>

      <div class="grid grid-3">
        <article v-for="(voice, index) in voices" :key="voice.id" class="panel voice-card">
          <div class="panel-body stack" style="gap: 11px">
            <div class="row" style="align-items: flex-start">
              <span class="voice-avatar" :style="avatarStyle(voice.name, index)">{{ initials(voice.name) }}</span>
              <div class="grow" style="min-width: 0">
                <div class="strong truncate">{{ voice.name }}</div>
                <div class="row" style="gap: 5px; margin-top: 6px">
                  <span class="chip">{{ languageLabel(voice.language) }}</span>
                  <span class="chip"><Clock3 :size="10" /> {{ formatDuration(voice.duration_seconds) }}</span>
                  <span class="badge success">Ready</span>
                </div>
              </div>
            </div>
            <p class="small muted transcript">{{ voice.transcript || "No transcript saved. Transcribe a reference to improve alignment." }}</p>
            <div v-if="previewId === voice.id" class="card-preview">
              <AudioPlayer :src="previewSrc(voice)" compact :title="`${voice.name} preview`" />
            </div>
          </div>
          <div class="panel-footer" style="justify-content: flex-start; flex-wrap: wrap; gap: 5px">
            <button class="btn btn-sm" @click="previewVoice(voice)"><Play :size="12" /> Preview</button>
            <button class="btn btn-sm" @click="openTrain(voice)"><RefreshCw :size="12" /> Retrain</button>
            <button class="btn btn-sm" @click="openRename(voice)"><Pencil :size="12" /> Rename</button>
            <button class="btn btn-sm btn-ghost" @click="exportVoice(voice)"><Download :size="12" /> Export</button>
            <button class="btn btn-sm btn-danger" style="margin-left: auto" title="Delete voice" aria-label="Delete voice" @click="askDeleteVoice(voice)"><Trash2 :size="12" /></button>
          </div>
        </article>

        <button class="panel voice-add" @click="openTrain()">
          <span class="file-icon" style="width: 46px; height: 46px"><Plus :size="20" /></span>
          <span class="strong">Train another voice</span>
          <span class="small muted">Upload 3–10 seconds of clean speech, record in the browser, and keep a consent record with the profile.</span>
          <span class="chip active">Reference audio + transcript</span>
        </button>
      </div>

      <div class="panel">
        <div class="panel-head">
          <div><h3>Voice safety</h3><p>Consent is stored with every profile and required for training, retraining and imports.</p></div>
          <span class="badge warn">Consent required</span>
        </div>
        <div class="panel-body grid grid-3" style="gap: 12px">
          <div class="alert"><strong>Use your own voice.</strong> Or obtain explicit permission from the speaker. Do not clone public figures or third parties without consent.</div>
          <div class="alert"><strong>Keep references clean.</strong> One speaker, no music, no reverb, 3–10 seconds is ideal. The service trims and normalises the clip.</div>
          <div class="alert"><strong>Profiles travel as ZIPs.</strong> Export includes <span class="mono">meta.json</span>, reference audio, the prompt tensor and a preview when available.</div>
        </div>
      </div>
    </section>

    <section v-else-if="tab === 'design'" class="stack">
      <div class="split split-wide">
        <div class="stack">
          <div class="panel">
            <div class="panel-head">
              <div>
                <h3>Describe the voice</h3>
                <p>Build an instruction from attributes, then edit the final sentence freely.</p>
              </div>
              <span class="badge success">Design mode</span>
            </div>
            <div class="panel-body stack" style="gap: 13px">
              <div class="grid grid-3" style="gap: 11px">
                <div class="field">
                  <label>Gender</label>
                  <select v-model="designAttrs.gender" class="select" @change="syncDesignInstruct">
                    <option value="any">Any</option><option value="female">Female</option><option value="male">Male</option><option value="non-binary">Non-binary</option>
                  </select>
                </div>
                <div class="field">
                  <label>Age</label>
                  <select v-model="designAttrs.age" class="select" @change="syncDesignInstruct">
                    <option value="any">Any</option><option value="young adult">Young adult</option><option value="adult">Adult</option><option value="middle-aged">Middle-aged</option><option value="older">Older</option>
                  </select>
                </div>
                <div class="field">
                  <label>Pitch</label>
                  <select v-model="designAttrs.pitch" class="select" @change="syncDesignInstruct">
                    <option value="any">Any</option><option value="low">Low</option><option value="warm">Warm</option><option value="neutral">Neutral</option><option value="bright">Bright</option><option value="high">High</option>
                  </select>
                </div>
                <div class="field">
                  <label>Style</label>
                  <select v-model="designAttrs.style" class="select" @change="syncDesignInstruct">
                    <option value="any">Any</option><option value="conversational">Conversational</option><option value="narrator">Narrator</option><option value="cinematic">Cinematic</option><option value="whisper">Whisper</option><option value="energetic">Energetic</option>
                  </select>
                </div>
                <div class="field">
                  <label>English accent</label>
                  <select v-model="designAttrs.accent" class="select" @change="syncDesignInstruct">
                    <option value="any">Any</option><option value="american">American</option><option value="british">British</option><option value="australian">Australian</option><option value="irish">Irish</option><option value="scottish">Scottish</option>
                  </select>
                </div>
                <div class="field">
                  <label>Chinese dialect</label>
                  <select v-model="designAttrs.dialect" class="select" @change="syncDesignInstruct">
                    <option value="any">Any</option><option value="mandarin">Mandarin</option><option value="cantonese">Cantonese</option><option value="taiwanese">Taiwanese</option><option value="sichuanese">Sichuanese</option>
                  </select>
                </div>
              </div>
              <div class="row" style="gap: 5px">
                <span class="small muted" style="margin-right: 2px">Presets</span>
                <button v-for="preset in designPresets" :key="preset.label" class="chip clickable" @click="applyDesignPreset(preset)">{{ preset.label }}</button>
              </div>
              <div class="field">
                <label>Final instruction</label>
                <textarea v-model="designText" class="textarea" rows="5" maxlength="600" />
                <span class="hint">{{ designText.length }} / 600 characters · changes here override the generated sentence.</span>
              </div>
            </div>
          </div>

          <div class="panel">
            <div class="panel-head">
              <div><h3>Design result</h3><p>The latest designed take and its full instruction.</p></div>
              <span v-if="result?.mode === 'design'" class="badge success">Designed</span>
            </div>
            <div class="panel-body">
              <template v-if="result">
                <AudioPlayer :src="result.path" :title="result.voice_name || 'Designed voice'" :subtitle="`${formatDuration(result.duration_seconds)} · ${languageLabel(result.language)}`" :download-path="result.path" />
                <div class="row-between small muted" style="margin-top: 8px">
                  <span class="mono">RTF {{ formatRtf(result.rtf) }}</span>
                  <span>{{ String(result.format || "wav").toUpperCase() }} · seed {{ result.seed ?? "auto" }}</span>
                </div>
              </template>
              <EmptyState v-else :icon="Wand2" title="Design a voice" message="Pick a few attributes or write your own instruction. The result appears here with the exact prompt used." />
            </div>
          </div>
        </div>

        <aside class="panel">
          <div class="panel-head">
            <div><h3>Read this</h3><p>Use a line with breath and punctuation to hear the design.</p></div>
            <button class="chip clickable" @click="instructOpen = !instructOpen">{{ instructOpen ? "Hide" : "Show" }} prompt</button>
          </div>
          <div class="panel-body stack" style="gap: 13px">
            <div class="field">
              <label>Script</label>
              <textarea v-model="designScript" class="textarea" rows="7" />
            </div>
            <div class="row" style="gap: 6px">
              <span class="chip">{{ languageLabel(form.language) }}</span>
              <span class="chip">{{ form.format.toUpperCase() }}</span>
              <span class="chip">{{ form.num_step }} steps</span>
            </div>
            <div v-if="instructOpen" class="code" style="max-height: 220px">{{ designText }}</div>
            <div class="switches">
              <div class="switch-row" style="padding: 4px 0">
                <div><div class="switch-label">Normalize text</div><div class="switch-hint">Expand numbers before speaking.</div></div>
                <button class="switch" :class="{ on: form.normalize_text }" @click="form.normalize_text = !form.normalize_text" />
              </div>
              <div class="switch-row" style="padding: 4px 0">
                <div><div class="switch-label">Normalize loudness</div><div class="switch-hint">Dynaudnorm on the finished file.</div></div>
                <button class="switch" :class="{ on: form.normalize_audio }" @click="form.normalize_audio = !form.normalize_audio" />
              </div>
            </div>
            <button class="btn btn-primary btn-block" :disabled="busy || activeRunning" @click="generateDesign">
              <Loader2 v-if="busy" :size="14" class="spin" />
              <Wand2 v-else :size="14" />
              Generate designed voice
            </button>
            <div class="alert">
              Design mode is OmniVoice-only. The instruction is capped at 600 characters and is stored with the output metadata.
            </div>
          </div>
        </aside>
      </div>
    </section>

    <section v-else-if="tab === 'batch'" class="stack">
      <div class="split split-wide">
        <div class="panel">
          <div class="panel-head">
            <div><h3>Batch script</h3><p>Split by blank line for paragraphs, or by line for sentence-per-item delivery.</p></div>
            <span class="chip">{{ batchItems.length }} item(s)</span>
          </div>
          <div class="panel-body stack" style="gap: 12px">
            <div class="row-between">
              <div class="tabs" style="padding: 2px">
                <button class="tab" :class="{ active: batchSplit === 'blank-line' }" @click="batchSplit = 'blank-line'">Blank line</button>
                <button class="tab" :class="{ active: batchSplit === 'line' }" @click="batchSplit = 'line'">Line</button>
              </div>
              <span class="small muted">{{ batchCharCount }} chars · {{ batchItems.length }} / {{ catalog.limits?.batch_items || 50 }}</span>
            </div>
            <textarea v-model="batchText" class="textarea" rows="12" placeholder="One paragraph per item…" />
            <div class="row-between">
              <span class="small muted">Each item renders as its own audio file with a matching timeline.</span>
              <button class="btn btn-primary" :disabled="busy || activeRunning || !batchItems.length" @click="runBatch">
                <Layers :size="14" /> Generate batch
              </button>
            </div>
          </div>
        </div>

        <aside class="stack">
          <div class="panel">
            <div class="panel-head"><div><h3>Batch voice</h3><p>Same engine, language and quality as the Studio.</p></div></div>
            <div class="panel-body stack" style="gap: 11px">
              <div class="field">
                <label>Mode</label>
                <div class="tabs" style="padding: 2px">
                  <button class="tab" :class="{ active: batchMode === 'auto' }" @click="batchMode = 'auto'">Auto</button>
                  <button class="tab" :class="{ active: batchMode === 'voice' }" @click="batchMode = 'voice'">Cloned</button>
                  <button class="tab" :class="{ active: batchMode === 'design' }" @click="batchMode = 'design'">Design</button>
                </div>
              </div>
              <div v-if="batchMode === 'voice'" class="field">
                <label>Voice profile</label>
                <select v-model="form.voice_id" class="select">
                  <option value="">Choose a profile…</option>
                  <option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.name }}</option>
                </select>
              </div>
              <div v-else-if="batchMode === 'design'" class="field">
                <label>Instruction</label>
                <textarea v-model="form.instruct" class="textarea" rows="4" maxlength="600" placeholder="Describe the voice for every item…" />
              </div>
              <div v-else class="alert">Auto uses a neutral OmniVoice speaker. It is the most reliable choice for long batches.</div>
              <div class="result-meta">
                <div><span>Engine</span><strong style="text-transform: capitalize">{{ form.engine }}</strong></div>
                <div><span>Language</span><strong>{{ languageLabel(form.language) }}</strong></div>
                <div><span>Format</span><strong>{{ form.format.toUpperCase() }}</strong></div>
                <div><span>Speed</span><strong>{{ Number(form.speed).toFixed(2) }}×</strong></div>
                <div><span>Quality</span><strong>{{ form.num_step }} steps</strong></div>
                <div><span>Seed</span><strong class="mono">{{ form.seed ?? "auto" }}</strong></div>
              </div>
              <button class="btn btn-ghost btn-sm" @click="tab = 'studio'">Edit shared settings in Studio <ChevronRight :size="12" /></button>
            </div>
          </div>
          <div v-if="activeJob" class="panel">
            <div class="panel-head"><div><h3>Batch job</h3><p>Renders items sequentially inside one job.</p></div><span class="badge running">{{ Math.round(activeJob.progress) }}%</span></div>
            <div class="panel-body"><JobCard :job="activeJob" compact @cancel="cancelActive" /></div>
          </div>
        </aside>
      </div>

      <div v-if="batchResults.length" class="panel">
        <div class="panel-head">
          <div><h3>Batch results</h3><p>{{ batchResults.length }} take(s) · each one is in the voice history.</p></div>
          <button class="btn btn-sm" :disabled="zipLoading" @click="downloadBatchZip">
            <Loader2 v-if="zipLoading" :size="12" class="spin" />
            <FileArchive v-else :size="13" />
            Download ZIP
          </button>
        </div>
        <div class="panel-body">
          <div class="grid grid-2" style="gap: 12px">
            <div v-for="(item, index) in batchResults" :key="item.id || index" class="job-card" style="gap: 8px">
              <div class="row-between">
                <span class="chip active">#{{ index + 1 }}</span>
                <span class="small muted">{{ formatDuration(item.duration_seconds) }} · {{ String(item.format).toUpperCase() }}</span>
              </div>
              <div class="small strong truncate">{{ item.text_preview || item.text }}</div>
              <AudioPlayer :src="item.path" compact :download-path="item.path" :title="`Take ${index + 1}`" />
              <div class="row-between small muted">
                <span>{{ item.voice_name }} · {{ languageLabel(item.language) }}</span>
                <a :href="downloadUrl(item.path)" class="icon-btn" title="Download"><Download :size="13" /></a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section v-else-if="tab === 'history'" class="stack">
      <div class="panel">
        <div class="panel-head" style="flex-wrap: wrap; gap: 10px">
          <div><h3>Voice history</h3><p>{{ outputs.length }} rendered files in shared storage.</p></div>
          <div class="row">
            <div class="input-group" style="width: 230px">
              <Search :size="13" class="muted" />
              <input v-model="historySearch" class="input input-sm" placeholder="Search text, voice, language…" />
            </div>
            <select v-model="historyFormat" class="select input-sm" style="width: 110px">
              <option value="all">All formats</option>
              <option value="wav">WAV</option>
              <option value="mp3">MP3</option>
              <option value="flac">FLAC</option>
            </select>
            <button class="btn btn-sm btn-ghost" :disabled="busy" @click="refreshAll"><RefreshCw :size="13" /> Refresh</button>
          </div>
        </div>
        <div class="panel-body" style="padding: 8px">
          <div v-for="output in historyFiltered" :key="output.id" class="history-row">
            <div class="list-item" style="padding: 9px 7px">
              <button class="icon-btn" :title="expandedOutputId === output.id ? 'Hide audio' : 'Play audio'" @click="expandedOutputId = expandedOutputId === output.id ? '' : output.id">
                <Play :size="14" />
              </button>
              <div class="grow" style="min-width: 0">
                <div class="small strong truncate">{{ output.text_preview || output.text }}</div>
                <div class="small muted truncate">
                  {{ output.voice_name }} · {{ languageLabel(output.language) }} · {{ formatDuration(output.duration_seconds) }} · RTF {{ formatRtf(output.rtf) }} · {{ relativeTime(output.created_at) }}
                </div>
              </div>
              <span class="chip">{{ output.format?.toUpperCase() }}</span>
              <span class="small muted nowrap">{{ formatSize(output.size_bytes) }}</span>
              <a class="icon-btn" :href="downloadUrl(output.path)" title="Download"><Download :size="14" /></a>
              <button class="icon-btn" title="Delete" @click="askDeleteOutput(output)"><Trash2 :size="14" /></button>
            </div>
            <div v-if="expandedOutputId === output.id" style="padding: 0 7px 10px 45px">
              <AudioPlayer :src="output.path" compact :title="output.voice_name" :subtitle="`${String(output.format).toUpperCase()} · ${formatDuration(output.duration_seconds)}`" :download-path="output.path" />
            </div>
          </div>
          <EmptyState v-if="!historyFiltered.length" :icon="History" title="No matching takes" message="Generate speech in the Studio, run a batch, or clear the filters to see the shared voice history.">
            <button class="btn btn-sm" @click="tab = 'studio'">Open studio</button>
          </EmptyState>
        </div>
      </div>
    </section>

    <section v-else-if="tab === 'builtin'" class="stack">
      <div v-if="activeKind === 'piper_install' && activeJob" class="panel">
        <div class="panel-head">
          <div><h3>Voice download</h3><p>This download is running as a global job.</p></div>
          <span class="badge running">{{ Math.round(activeJob.progress) }}%</span>
        </div>
        <div class="panel-body"><JobCard :job="activeJob" compact @cancel="cancelActive" /></div>
      </div>
      <div class="panel">
        <div class="panel-head">
          <div>
            <h3>Piper built-in voices</h3>
            <p>Small ONNX voices that run fast on CPU. Install once, then select them in the Studio.</p>
          </div>
          <div class="row">
            <span class="chip success">{{ piperAvailable }}/{{ piperVoices.length }} installed</span>
            <span class="chip"><Gauge :size="11" /> {{ piperEngine?.device || "CPU" }}</span>
          </div>
        </div>
        <div class="panel-body">
          <div class="row" style="gap: 8px; margin-bottom: 12px">
            <select v-model="piperLanguageFilter" class="select input-sm" style="width: 210px">
              <option value="all">All languages</option>
              <option v-for="language in piperLanguageOptions" :key="language.id" :value="language.id">{{ language.label }}</option>
            </select>
            <select v-model="piperGenderFilter" class="select input-sm" style="width: 150px">
              <option value="all">All genders</option>
              <option value="female">Female</option>
              <option value="male">Male</option>
            </select>
            <span class="chip">{{ filteredPiperVoices.length }} shown</span>
          </div>
          <div class="grid grid-3">
            <article v-for="(voice, index) in filteredPiperVoices" :key="voice.id" class="panel piper-card">
              <div class="panel-body stack" style="gap: 10px">
                <div class="row" style="align-items: flex-start">
                  <span class="voice-avatar" :style="avatarStyle(voice.name, index + 2)">{{ initials(voice.name) }}</span>
                  <div class="grow" style="min-width: 0">
                    <div class="strong">{{ voice.name }}</div>
                    <div class="small muted">{{ voice.language_name || languageLabel(voice.language) }}</div>
                    <div class="row" style="gap: 4px; margin-top: 5px">
                      <span class="chip">{{ voice.gender || "voice" }}</span>
                      <span class="chip">{{ voice.quality || "medium" }}</span>
                      <span class="badge" :class="voice.available ? 'success' : 'warn'">{{ voice.available ? "Installed" : "Not installed" }}</span>
                    </div>
                  </div>
                </div>
                <p class="small muted" style="line-height: 1.55; min-height: 34px">{{ voice.description || `${voice.language} neural voice.` }}</p>
                <div class="row-between small muted">
                  <span>{{ voice.sample_rate ? `${voice.sample_rate} Hz` : "22.05 kHz" }}</span>
                  <span>{{ voice.license || "Piper voice license" }}</span>
                </div>
              </div>
              <div class="panel-footer" style="justify-content: space-between">
                <span class="small muted">{{ voice.size_bytes ? formatSize(voice.size_bytes) : "Download on demand" }}</span>
                <div class="row" style="gap: 6px">
                  <button v-if="voice.available" class="btn btn-sm" @click="usePiper(voice)"><Mic :size="12" /> Use voice</button>
                  <button v-else class="btn btn-sm btn-primary" :disabled="piperInstalling === voice.id" @click="installPiper(voice)">
                    <Loader2 v-if="piperInstalling === voice.id" :size="12" class="spin" />
                    <Download v-else :size="12" />
                    Install
                  </button>
                </div>
              </div>
            </article>
          </div>
        </div>
      </div>

      <div class="grid grid-2">
        <div class="panel">
          <div class="panel-head"><div><h3>Piper engine</h3><p>CPU worker installed in the voice container.</p></div><span class="badge success">{{ piperEngine?.status || "ready" }}</span></div>
          <div class="panel-body stack" style="gap: 9px">
            <div class="row-between small"><span class="muted">Location</span><span class="mono">/data/models/piper</span></div>
            <div class="row-between small"><span class="muted">Formats</span><span>WAV · MP3</span></div>
            <div class="row-between small"><span class="muted">Speed</span><span>0.5× – 2.0×</span></div>
            <div class="row-between small"><span class="muted">Pitch</span><span>Not exposed by bundled voices</span></div>
            <div class="alert">Piper can keep producing speech even when OmniVoice is unavailable. Its sentence timeline is written into every output.</div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><div><h3>Install another language</h3><p>The catalog is fixed; downloads go to shared model storage.</p></div><FileAudio :size="16" class="muted" /></div>
          <div class="panel-body">
            <div class="row" style="gap: 5px; flex-wrap: wrap">
              <span v-for="voice in piperVoices" :key="voice.id" class="chip" :class="voice.available ? 'success' : ''">{{ voice.language }}</span>
            </div>
            <div class="alert" style="margin-top: 12px">
              Install queues a normal voice job on <span class="mono">/api/voice/piper/install</span>. Progress, errors and retries appear in Jobs and in the download panel above.
            </div>
            <button class="btn btn-sm btn-block" style="margin-top: 10px" @click="tab = 'studio'"><Mic2 :size="13" /> Back to the studio</button>
          </div>
        </div>
      </div>
    </section>

    <BaseModal v-model="trainOpen" :title="trainMode === 'retrain' ? 'Retrain voice' : 'Train a new voice'" subtitle="Reference audio + transcript become a reusable OmniVoice prompt. Consent is stored with the profile." width="wide">
      <div class="grid grid-2" style="gap: 20px">
        <div class="stack" style="gap: 12px">
          <div class="field">
            <label>Voice name</label>
            <input v-model="trainForm.name" class="input" maxlength="60" placeholder="Helena — close" />
          </div>
          <div class="field">
            <label>Language</label>
            <select v-model="trainForm.language" class="select">
              <option v-for="language in languages" :key="language.id" :value="language.id">{{ language.name }}</option>
            </select>
          </div>

          <div class="panel" style="background: rgba(8,10,15,.28)">
            <div class="panel-head">
              <div><h3 style="font-size: 13px">Reference audio</h3><p>Clean, single speaker, 3–10 seconds is ideal.</p></div>
              <span class="chip">{{ trainAudioName ? "Selected" : "Required" }}</span>
            </div>
            <div class="panel-body stack" style="gap: 10px">
              <div class="row">
                <button class="btn btn-sm" @click="pickerOpen = true"><FileAudio :size="13" /> {{ trainAudioName || "Choose audio file" }}</button>
                <button v-if="trainAudioName || recordedUrl" class="icon-btn" title="Clear audio" @click="clearAudioSource"><X :size="14" /></button>
              </div>
              <div class="alert">OmniVoice accepts 1–30 seconds; 3–10 seconds gives the cleanest clone. The service normalises the clip.</div>
              <div class="record-box">
                <div class="row-between">
                  <span class="small strong"><Mic :size="13" style="vertical-align: -2px" /> Record in the browser</span>
                  <span class="small muted">{{ recording ? "Recording…" : recordedUrl ? "Recording ready" : "MediaRecorder" }}</span>
                </div>
                <div class="meter"><span :style="{ width: `${level}%` }" /></div>
                <div class="row" style="gap: 7px">
                  <button class="btn btn-sm" :class="{ 'btn-danger': recording }" @click="toggleRecording">
                    <Square v-if="recording" :size="12" />
                    <Mic v-else :size="13" />
                    {{ recording ? "Stop recording" : "Start recording" }}
                  </button>
                  <span class="small muted">{{ recordedUrl ? "Use this take as the reference." : "Microphone stays in this browser." }}</span>
                </div>
                <audio v-if="recordedUrl" :src="recordedUrl" controls style="width: 100%; height: 34px" />
              </div>
            </div>
          </div>
        </div>

        <div class="stack" style="gap: 12px">
          <div class="field">
            <label>
              Transcript
              <button class="chip clickable" :disabled="recordedBlob === null && !trainAudioPath" @click="transcribeReference">
                <Sparkles :size="10" /> Transcribe
              </button>
            </label>
            <textarea v-model="trainForm.transcript" class="textarea" rows="5" placeholder="Leave blank to let Whisper transcribe the reference automatically." />
            <span class="hint">A matching transcript improves cloning. Transcribe runs a Whisper job against the selected clip.</span>
          </div>
          <div class="field">
            <label>Description <span class="small muted">optional</span></label>
            <input v-model="trainForm.description" class="input" maxlength="1000" placeholder="Close-mic narration, soft delivery" />
          </div>
          <div class="switch-row">
            <div><div class="switch-label">Preprocess reference prompt</div><div class="switch-hint">Trim silence and normalise before building the prompt.</div></div>
            <button class="switch" :class="{ on: trainForm.preprocess_prompt }" @click="trainForm.preprocess_prompt = !trainForm.preprocess_prompt" />
          </div>
          <label class="consent">
            <input v-model="trainForm.consent" type="checkbox" />
            <span>I own this voice or have explicit permission from the speaker to clone it. I will not use it to impersonate anyone without consent.</span>
          </label>
          <div class="alert warn">Consent is required by the service for training, retraining and ZIP imports.</div>
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="trainOpen = false">Cancel</button>
        <button class="btn btn-primary" :disabled="trainBusy || !trainForm.consent" @click="submitTrain">
          <Loader2 v-if="trainBusy" :size="13" class="spin" />
          <Sparkles v-else :size="13" />
          {{ trainMode === "retrain" ? "Retrain voice" : "Start training" }}
        </button>
      </template>
    </BaseModal>

    <BaseModal v-model="renameOpen" title="Rename voice" subtitle="The profile and preview stay unchanged." width="narrow">
      <div class="field">
        <label>Voice name</label>
        <input v-model="renameValue" class="input" maxlength="60" @keydown.enter="saveRename" />
      </div>
      <template #footer>
        <button class="btn" @click="renameOpen = false">Cancel</button>
        <button class="btn btn-primary" :disabled="!renameValue.trim()" @click="saveRename">Save name</button>
      </template>
    </BaseModal>

    <BaseModal v-model="deleteOpen" title="Delete voice profile" subtitle="The reference, prompt and preview are removed from shared storage." width="narrow">
      <div class="alert error">{{ deleteTarget?.name }} will be permanently deleted. Existing generated audio is not affected.</div>
      <template #footer>
        <button class="btn" @click="deleteOpen = false">Cancel</button>
        <button class="btn btn-danger" @click="confirmDeleteVoice"><Trash2 :size="13" /> Delete voice</button>
      </template>
    </BaseModal>

    <BaseModal v-model="outputDeleteOpen" title="Delete output" subtitle="This removes the audio file and its metadata." width="narrow">
      <div class="alert error">{{ outputDeleteTarget?.text_preview || outputDeleteTarget?.text || "This take" }} will be permanently deleted.</div>
      <template #footer>
        <button class="btn" @click="outputDeleteOpen = false">Cancel</button>
        <button class="btn btn-danger" @click="confirmDeleteOutput"><Trash2 :size="13" /> Delete output</button>
      </template>
    </BaseModal>

    <FilePicker v-model="pickerOpen" title="Reference audio" kind="audio" accept="audio/*" @selected="onTrainAudioSelected" />
  </div>
</template>

<style scoped>
.script-area {
  min-height: 150px;
  font-size: 13.5px;
  line-height: 1.7;
}

.design-script {
  min-height: 140px;
}

.voice-card {
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: 160ms ease;
}
.voice-card:hover {
  border-color: var(--line-strong);
  transform: translateY(-2px);
}
.voice-card .panel-body {
  flex: 1;
}
.voice-avatar {
  width: 52px;
  height: 52px;
  border-radius: 15px;
  display: grid;
  place-items: center;
  color: white;
  font-family: var(--display);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.03em;
  box-shadow: 0 8px 26px rgba(0, 0, 0, 0.28);
  flex: none;
  border: 1px solid rgba(255, 255, 255, 0.12);
}
.transcript {
  min-height: 42px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-preview {
  padding-top: 2px;
}
.voice-add {
  min-height: 250px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  text-align: center;
  padding: 28px 22px;
  border-style: dashed;
  border-color: var(--line-strong);
  color: var(--text);
  background: rgba(255, 255, 255, 0.012);
}
.voice-add:hover {
  border-color: rgba(139, 92, 246, 0.5);
  background: rgba(139, 92, 246, 0.04);
}
.voice-add > .small {
  max-width: 290px;
  line-height: 1.6;
}
.combo {
  position: relative;
}
.combo-input {
  display: flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.55);
  padding: 0 9px;
  min-height: 36px;
}
.combo-input .input {
  border: none;
  background: transparent;
  box-shadow: none;
  padding-left: 0;
  min-height: 34px;
}
.combo-input .input:focus {
  box-shadow: none;
}
.combo-dropdown {
  position: absolute;
  z-index: 20;
  top: calc(100% + 5px);
  left: 0;
  right: 0;
  max-height: 225px;
  overflow-y: auto;
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  background: var(--panel-3);
  box-shadow: var(--shadow);
  padding: 4px;
}
.combo-option {
  width: 100%;
  border: none;
  background: none;
  color: var(--text);
  border-radius: 7px;
  padding: 7px 8px;
  font-size: 11.5px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  text-align: left;
}
.combo-option:hover,
.combo-option.active {
  background: rgba(139, 92, 246, 0.16);
  color: #ddd6fe;
}
.result-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}
.result-meta > div {
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.35);
  padding: 8px 9px;
  min-width: 0;
}
.result-meta span {
  display: block;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted-2);
  font-weight: 700;
}
.result-meta strong {
  display: block;
  font-size: 12px;
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.record-box {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(8, 10, 15, 0.35);
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.consent {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  font-size: 11.5px;
  line-height: 1.55;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.015);
  padding: 10px 11px;
  cursor: pointer;
}
.consent input {
  margin-top: 2px;
  flex: none;
}
.history-row {
  border-bottom: 1px solid rgba(35, 42, 58, 0.55);
}
.history-row:last-child {
  border-bottom: none;
}
.piper-card {
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.piper-card .panel-body {
  flex: 1;
}
.piper-card .panel-footer {
  flex-wrap: wrap;
  gap: 7px;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 780px) {
  .result-meta {
    grid-template-columns: 1fr;
  }
}
</style>
