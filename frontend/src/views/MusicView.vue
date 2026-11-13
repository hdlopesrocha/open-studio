<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import {
  Activity,
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  AudioLines,
  BookOpen,
  Check,
  ChevronRight,
  Clock3,
  Copy,
  Cpu,
  Database,
  Dice5,
  Disc3,
  Download,
  ExternalLink,
  FastForward,
  FileAudio,
  FolderOpen,
  FolderPlus,
  Gauge,
  GitCompare,
  HardDrive,
  Heart,
  Layers,
  ListMusic,
  Loader2,
  Lock,
  MemoryStick,
  Music2,
  Package,
  Paintbrush,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  Server,
  Sparkles,
  Star,
  Terminal,
  Trash2,
  Unlock,
  Wand2,
  X,
} from "lucide-vue-next";
import { api, downloadUrl, fileUrl, formatDuration, relativeTime } from "@/lib/api";
import { DEMO } from "@/lib/types";
import type { Job } from "@/lib/types";
import { demoJobs, demoLyrics, demoMusicCatalog, demoProjects, demoSongs, demoTakes } from "@/lib/demo";
import { useJobsStore } from "@/stores/jobs";
import { useSystemStore } from "@/stores/system";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import BaseModal from "@/components/BaseModal.vue";
import FilePicker from "@/components/FilePicker.vue";
import AudioPlayer from "@/components/AudioPlayer.vue";
import SubtitlesView from "@/views/SubtitlesView.vue";
import ServiceNotice from "@/components/ServiceNotice.vue";
import SectionPlayer from "@/components/music/SectionPlayer.vue";
import DjView from "@/views/DjView.vue";
import JobCard from "@/components/JobCard.vue";
import TabsBar from "@/components/TabsBar.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import EmptyState from "@/components/EmptyState.vue";
import CodeBlock from "@/components/CodeBlock.vue";

interface MusicProject {
  id: string;
  title: string;
  artist: string;
  description: string;
  color: string;
  song_count: number;
  take_count: number;
  updated_at: string;
  last_activity?: string | null;
  cover?: string;
}

interface MusicSong {
  id: string;
  project_id: string;
  title: string;
  artist: string;
  language: string;
  language_label: string;
  genre: string;
  subgenre: string;
  style: string;
  mood: string;
  energy: number;
  bpm: number;
  duration: number;
  vocal_type: string;
  vocal_intensity: number;
  singing_style: string;
  vocal_emotion: string;
  vocal_range: string;
  vocal_prompt: string;
  pronunciation: string;
  instructions: string;
  provider: string;
  model_id: string;
  selected_take_id?: string | null;
  take_count?: number;
  project_title?: string;
  project_color?: string;
  created_at?: string;
  updated_at?: string;
  project?: any;
  lyrics?: { sections: LyricsSection[] };
  selected_take?: MusicTake | null;
}

interface MusicTake {
  id: string;
  song_id?: string;
  job_id?: string | null;
  position: number;
  path: string;
  url?: string | null;
  name?: string;
  duration: number;
  seed: string | number | null;
  metadata: Record<string, any>;
  is_favorite: boolean;
  notes?: string;
  created_at?: string;
  bpm?: number;
  selected?: boolean;
}

interface LyricsSection {
  id: string;
  type: string;
  label: string;
  content: string;
  instructions: string;
}

interface SongBrief {
  title: string;
  artist: string;
  language: string;
  genre: string;
  subgenre: string;
  style: string;
  mood: string;
  energy: number;
  bpm: number;
  duration: number;
  vocal_type: string;
  vocal_intensity: number;
  singing_style: string;
  vocal_emotion: string;
  vocal_range: string;
  vocal_prompt: string;
  pronunciation: string;
  instructions: string;
}

interface DraftPlan {
  type: string;
  label: string;
  line_count: number;
}

interface TakeGroup {
  key: string;
  label: string;
  mode: string;
  model: string;
  createdAt: string;
  takes: MusicTake[];
}

interface ExportTarget {
  kind: "song" | "project";
  id: string;
  title: string;
}

type ConfirmAction = () => Promise<void>;

const DEMO_ART = [
  "/demo/art-01.png",
  "/demo/art-02.png",
  "/demo/art-03.png",
  "/demo/art-04.png",
  "/demo/art-05.png",
  "/demo/art-06.png",
  "/demo/art-07.png",
  "/demo/art-08.png",
];

const SECTION_TYPES = ["intro", "verse", "pre-chorus", "chorus", "bridge", "outro", "instrumental"];
const SECTION_LABELS: Record<string, string> = {
  intro: "Intro",
  verse: "Verse",
  "pre-chorus": "Pre-Chorus",
  chorus: "Chorus",
  bridge: "Bridge",
  outro: "Outro",
  instrumental: "Instrumental",
};
const SECTION_COLORS: Record<string, string> = {
  intro: "#22d3ee",
  verse: "#8b5cf6",
  "pre-chorus": "#f59e0b",
  chorus: "#34d399",
  bridge: "#fb7185",
  outro: "#60a5fa",
  instrumental: "#a3a3a3",
};
const MODE_CAPABILITY: Record<string, string> = {
  full: "text_to_music",
  repaint: "repaint",
  cover: "cover",
  extend: "extend",
};
const MODE_ICONS: Record<string, any> = {
  full: Music2,
  repaint: Paintbrush,
  cover: Disc3,
  extend: FastForward,
};
const COLOR_HEX: Record<string, string> = {
  lime: "#d9ff6b",
  coral: "#ff7c5c",
  mint: "#83f0c4",
  blue: "#82b9ff",
  amber: "#ffc46b",
  rose: "#f48bb2",
  violet: "#8b5cf6",
  cyan: "#22d3ee",
  green: "#34d399",
};
const LANG_LABELS: Record<string, string> = {
  "pt-PT": "Portuguese (Portugal)",
  "pt-BR": "Portuguese (Brazil)",
  en: "English",
  es: "Spanish",
  fr: "French",
  de: "German",
  it: "Italian",
  ja: "Japanese",
  zh: "Chinese",
  ko: "Korean",
};
const CAPABILITY_LABELS: Record<string, string> = {
  text_to_music: "Text to music",
  lyrics: "Structured lyrics",
  instrumental: "Instrumental",
  vocals: "Vocals",
  cover: "Cover",
  repaint: "Repaint",
  extend: "Extend / complete",
  source_audio: "Source audio",
  reference_audio: "Reference audio",
  variations: "Variations",
  multiple_variations: "Multiple variations",
  seed: "Seed",
  seed_control: "Seed lock",
  steps: "Steps",
  inference_steps: "Inference steps",
  guidance: "Guidance",
  guidance_control: "Guidance control",
  prompt_expansion: "Prompt expansion",
  thinking: "Thinking",
  bpm: "BPM",
  bpm_control: "BPM control",
  duration: "Duration",
  duration_control: "Duration control",
  vocal_language: "Vocal language",
  stem_extraction: "Stem extraction",
};
const BASE_MODES = [
  {
    id: "full",
    label: "Full song",
    task_type: "text2music",
    requires_source: false,
    requires_range: false,
    description: "Create a complete song from the brief and lyrics.",
  },
  {
    id: "repaint",
    label: "Repaint section",
    task_type: "repaint",
    requires_source: true,
    requires_range: true,
    description: "Regenerate a time range while preserving the rest.",
  },
  {
    id: "cover",
    label: "Cover / re-imagine",
    task_type: "cover",
    requires_source: true,
    requires_range: false,
    description: "Re-interpret source audio in a new style.",
  },
  {
    id: "extend",
    label: "Extend / complete",
    task_type: "complete",
    requires_source: true,
    requires_range: false,
    description: "Continue or complete source audio. Needs a base or SFT model.",
  },
];
const FALLBACK_AUDIO_FORMATS = [
  { id: "wav", label: "WAV 16-bit" },
  { id: "wav24", label: "WAV 24-bit" },
  { id: "mp3", label: "MP3" },
  { id: "flac", label: "FLAC" },
];
const FALLBACK_EXPORT_FORMATS = [
  { id: "wav", label: "WAV" },
  { id: "mp3", label: "MP3" },
  { id: "flac", label: "FLAC" },
  { id: "zip", label: "Session ZIP" },
];
const FALLBACK_INFER_METHODS = [
  { id: "ode", label: "ODE (deterministic)" },
  { id: "sde", label: "SDE (ancestral)" },
];
const FALLBACK_VOCAL_TYPES = [
  { value: "female", label: "Female" },
  { value: "male", label: "Male" },
  { value: "duet", label: "Duet" },
  { value: "group", label: "Group" },
  { value: "choir", label: "Choir" },
  { value: "instrumental", label: "Instrumental" },
];
const FALLBACK_OPTIONS: Record<string, any> = {
  modes: BASE_MODES,
  audio_formats: FALLBACK_AUDIO_FORMATS,
  export_formats: FALLBACK_EXPORT_FORMATS,
  infer_methods: FALLBACK_INFER_METHODS,
  vocal_types: FALLBACK_VOCAL_TYPES,
  genres: ["Art pop", "Dream pop", "Electronic", "Trip hop", "Folk", "Jazz", "Ambient", "Rock", "Fado"],
  moods: ["Introspective", "Melancholic", "Dreamy", "Romantic", "Hopeful", "Uplifting", "Playful", "Dark", "Defiant", "Haunting", "Nostalgic", "Epic", "Serene", "Restless"],
  singing_styles: ["Melodic", "Intimate", "Breathy", "Belting", "Falsetto", "Spoken word", "Rap", "Chant", "Crooner", "Ornamented"],
  vocal_emotions: ["Intimate", "Tender", "Yearning", "Joyful", "Defiant", "Haunting", "Playful", "Mournful", "Serene", "Ecstatic", "Restrained"],
  vocal_ranges: ["Soprano", "Mezzo-soprano", "Alto", "Tenor", "Baritone", "Bass", "Unspecified"],
  energy_labels: [
    { value: 0, label: "Still" },
    { value: 25, label: "Low" },
    { value: 50, label: "Mid" },
    { value: 75, label: "High" },
    { value: 100, label: "Peak" },
  ],
  project_colors: [
    { id: "violet", label: "Violet", hex: "#8b5cf6" },
    { id: "cyan", label: "Cyan", hex: "#22d3ee" },
    { id: "mint", label: "Mint", hex: "#83f0c4" },
    { id: "amber", label: "Amber", hex: "#ffc46b" },
    { id: "coral", label: "Coral", hex: "#ff7c5c" },
    { id: "rose", label: "Rose", hex: "#f48bb2" },
  ],
  structures: [
    { id: "pop-standard", label: "Pop standard", sections: ["Intro", "Verse 1", "Pre-Chorus", "Chorus", "Verse 2", "Chorus", "Bridge", "Chorus", "Outro"] },
    { id: "radio-edit", label: "Radio edit", sections: ["Verse 1", "Pre-Chorus", "Chorus", "Verse 2", "Chorus", "Outro"] },
    { id: "ballad", label: "Ballad", sections: ["Intro", "Verse 1", "Chorus", "Verse 2", "Chorus", "Bridge", "Chorus", "Outro"] },
  ],
  style_suggestions: ["intimate", "cinematic", "analog warmth", "live room", "nylon guitar", "muted trumpet", "brushed drums", "wide stereo", "lo-fi texture", "orchestral swell", "close vocal", "modal harmony", "tape saturation", "sparse arrangement"],
};

const DEMO_LIMITATIONS = [
  "The GGUF engine consumes the same ACE-Step 1.5 checkpoints as the official Python API but exposes a different HTTP API.",
  "Full text-to-music runs the 5Hz language model for audio codes. Cover and repaint bypass the LM.",
  "Thinking/COT toggles from the official API are not exposed by the GGUF engine; full songs always use the LM planner.",
  "Repaint is the supported way to regenerate a vocal section; vocal-only regeneration is not exposed.",
];
const DEMO_MODEL_FILES = [
  { name: "acestep-v15-turbo-dit-Q4_K_M.gguf", size: 1_913_000_000, size_label: "1.8 GB", path: "/data/models/acestep/acestep-v15-turbo-dit-Q4_K_M.gguf" },
  { name: "acestep-v15-sft-dit-Q4_K_M.gguf", size: 1_898_000_000, size_label: "1.8 GB", path: "/data/models/acestep/acestep-v15-sft-dit-Q4_K_M.gguf" },
  { name: "acestep-5hz-lm-2b-Q8_0.gguf", size: 2_412_000_000, size_label: "2.2 GB", path: "/data/models/acestep/acestep-5hz-lm-2b-Q8_0.gguf" },
  { name: "Qwen3-Embedding-0.6B-Q8_0.gguf", size: 611_000_000, size_label: "583 MB", path: "/data/models/acestep/Qwen3-Embedding-0.6B-Q8_0.gguf" },
  { name: "acestep-v15-vae-fp16.gguf", size: 168_000_000, size_label: "160 MB", path: "/data/models/acestep/acestep-v15-vae-fp16.gguf" },
];
const DEMO_SYSTEM = {
  engine: {
    id: "ace_step",
    name: "ACE-Step 1.5",
    kind: "music",
    available: true,
    status: "online",
    status_detail: "ACE-Step GGUF engine ready.",
    version: "1.5.0",
    backend: "CPU · OpenBLAS / GGUF",
    engine: "acestep.cpp / GGUF",
    default_model: "acestep-v15-turbo",
    models: ["acestep-v15-turbo", "acestep-v15-sft"],
    docs_url: "https://github.com/ServeurpersoCom/acestep.cpp",
    limitations: DEMO_LIMITATIONS,
    setup_hint: "Start the music-engine container and wait for the first-run GGUF download to finish.",
  },
  health: { reachable: true, status: "ok", detail: "GET /health returned 200 in 11 ms", latency_ms: 11 },
  available: true,
  status: "online",
  status_detail: "ACE-Step GGUF engine ready.",
  version: "1.5.0",
  engine_url: "http://music-engine:8000",
  model_dir: "/data/models/acestep",
  installed_files: { path: "/data/models/acestep", count: DEMO_MODEL_FILES.length, files: DEMO_MODEL_FILES },
  buckets: {
    dit: ["acestep-v15-turbo-dit-Q4_K_M.gguf", "acestep-v15-sft-dit-Q4_K_M.gguf"],
    lm: ["acestep-5hz-lm-2b-Q8_0.gguf"],
    embedding: ["Qwen3-Embedding-0.6B-Q8_0.gguf"],
    vae: ["acestep-v15-vae-fp16.gguf"],
  },
  models: demoMusicCatalog.models,
  installed_models: demoMusicCatalog.models.filter((model: any) => model.installed),
  resources: {
    cpu_count: 16,
    load_avg: [0.82, 0.64, 0.51],
    process_memory_mb: 486,
    memory: { total_mb: 32768, available_mb: 18350, used_mb: 14418, percent: 44 },
    disk: {
      files: { path: "/data/files", total_gb: 512, used_gb: 184, free_gb: 328 },
      state: { path: "/data/state", total_gb: 512, used_gb: 184, free_gb: 328 },
      models: { path: "/data/models", total_gb: 512, used_gb: 184, free_gb: 328 },
    },
  },
  checked_at: new Date().toISOString(),
  timestamp: new Date().toISOString(),
};

const jobs = useJobsStore();
const system = useSystemStore();
const toasts = useToastStore();
const serviceOnline = (name: string) => DEMO || !system.status || system.service(name)?.online === true;

const route = useRoute();
const API_BASE = import.meta.env.VITE_API_BASE || "/api";
const requestedTab = typeof route.query.tab === "string" ? route.query.tab : "";
const tab = ref(requestedTab || (DEMO ? "studio" : "projects"));
watch(
  () => route.query.tab,
  (next) => {
    if (typeof next === "string" && next && next !== tab.value) tab.value = next;
  },
);
const projects = ref<MusicProject[]>([]);
const songs = ref<MusicSong[]>([]);
const takes = ref<MusicTake[]>([]);
const lyricsSections = ref<LyricsSection[]>([]);
const activeSong = ref<MusicSong | null>(null);
const selectedProjectId = ref<string | null>(null);
const selectedSongId = ref<string | null>(null);
const catalog = ref<any>(null);
const musicSystem = ref<any>(null);
const loading = ref(!DEMO);
const loadingSong = ref(false);
const serviceError = ref("");
const refreshing = ref(false);

const brief = ref<SongBrief>(emptyBrief());
const briefSnapshot = ref("");
const lyricsSnapshot = ref("");
const savingSong = ref(false);
const savingLyrics = ref(false);
const lastSavedAt = ref<string | null>(null);

const songQuery = ref("");
const libraryProject = ref("");

const genProvider = ref("ace_step");
const genModelId = ref("acestep-v15-turbo");
const genMode = ref("full");
const genVariations = ref(2);
const seedEnabled = ref(false);
const seed = ref(438921);
const stepsAuto = ref(true);
const genSteps = ref(8);
const guidanceAuto = ref(true);
const genGuidance = ref(1);
const thinking = ref(false);
const useFormat = ref(false);
const enhancePrompt = ref(false);
const genInstruction = ref("");
const sourcePath = ref("");
const referencePath = ref("");
const styles = ref<any[]>([]);
const selectedStyleId = ref("");
const styleOpen = ref(false);
const stylePicker = ref(false);
const styleSaving = ref(false);
const styleForm = ref({ name: "", description: "", prompt: "", tags: "", reference_path: "", reference_name: "" });
const sourceTakeId = ref("");
const startSeconds = ref(0);
const endSeconds = ref(60);
const coverStrength = ref(0.75);
const bpmOverride = ref(false);
const genBpm = ref(96);
const durationOverride = ref(false);
const genDuration = ref(150);
const audioFormat = ref("wav");
const inferMethod = ref("ode");
const lmBatchSize = ref(1);
const synthBatchSize = ref(2);
const generating = ref(false);
const currentJobId = ref("");
const generationJobId = ref("");
const sourcePicker = ref(false);
const referencePicker = ref(false);

const exportModal = ref(false);
const exportFormat = ref("wav");
const exportIncludeAll = ref(true);
const exportTarget = ref<ExportTarget | null>(null);
const exporting = ref(false);

const projectModal = ref(false);
const projectForm = ref({ id: "", title: "", artist: "", description: "", color: "#8b5cf6" });
const savingProject = ref(false);

const songModal = ref(false);
const songForm = ref({
  project_id: "",
  title: "",
  artist: "",
  language: "pt-PT",
  genre: "Art pop",
  mood: "Introspective",
  bpm: 96,
  duration: 180,
});
const savingNewSong = ref(false);

const draftModal = ref(false);
const draftTheme = ref("");
const draftDirection = ref("");
const draftStructure = ref<DraftPlan[]>([]);
const draftJobId = ref("");
const localDraftSections = ref<LyricsSection[] | null>(null);
const drafting = ref(false);

const confirmOpen = ref(false);
const confirmTitle = ref("");
const confirmMessage = ref("");
const confirmLabel = ref("Delete");
const confirmAction = ref<ConfirmAction | null>(null);
const confirming = ref(false);

const compareModal = ref(false);
const compareA = ref("");
const compareB = ref("");

const demoTakeCache = ref<MusicTake[]>([]);
const demoLyricsCache = ref<Record<string, LyricsSection[]>>({});
let loadToken = 0;

const TAKE_EXPORT_FORMATS = ["wav", "mp3", "flac"];

/* ------------------------------------------------------------------ helpers */
function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function uid(prefix = "m"): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

function isoMinutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60000).toISOString();
}

function isoNow(): string {
  return new Date().toISOString();
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error || "Something went wrong.");
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function fileBase(path: string): string {
  return path.split("/").filter(Boolean).pop() || path;
}

function pretty(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function sectionColor(type: string): string {
  return SECTION_COLORS[type] || "#8b5cf6";
}

function sectionTint(type: string): string {
  const hex = sectionColor(type).replace("#", "");
  return `#${hex}2e`;
}

function colorHex(value?: string | null): string {
  if (!value) return "#8b5cf6";
  if (value.startsWith("#")) return value;
  return COLOR_HEX[value] || "#8b5cf6";
}

function lineCount(content: string): number {
  return content.split("\n").filter((line) => line.trim().length > 0).length;
}

function wordCount(content: string): number {
  return content.trim() ? content.trim().split(/\s+/).length : 0;
}

function emptyBrief(): SongBrief {
  return {
    title: "",
    artist: "",
    language: "pt-PT",
    genre: "Art pop",
    subgenre: "",
    style: "",
    mood: "Introspective",
    energy: 48,
    bpm: 96,
    duration: 180,
    vocal_type: "female",
    vocal_intensity: 55,
    singing_style: "Melodic",
    vocal_emotion: "Intimate",
    vocal_range: "Alto",
    vocal_prompt: "",
    pronunciation: "",
    instructions: "",
  };
}

function briefFromSong(song: MusicSong): SongBrief {
  return {
    title: song.title || "",
    artist: song.artist || "",
    language: song.language || "pt-PT",
    genre: song.genre || "Art pop",
    subgenre: song.subgenre || "",
    style: song.style || "",
    mood: song.mood || "Introspective",
    energy: Number(song.energy ?? 48),
    bpm: Number(song.bpm ?? 96),
    duration: Number(song.duration ?? 180),
    vocal_type: song.vocal_type || "female",
    vocal_intensity: Number(song.vocal_intensity ?? 55),
    singing_style: song.singing_style || "Melodic",
    vocal_emotion: song.vocal_emotion || "Intimate",
    vocal_range: song.vocal_range || "Alto",
    vocal_prompt: song.vocal_prompt || "",
    pronunciation: song.pronunciation || "",
    instructions: song.instructions || "",
  };
}

function briefPayload(): Record<string, any> {
  const value = brief.value;
  return {
    title: value.title.trim() || "Untitled song",
    artist: value.artist.trim(),
    language: value.language,
    language_label: languageLabelFor(value.language),
    genre: value.genre.trim() || "Pop",
    subgenre: value.subgenre.trim(),
    style: value.style.trim(),
    mood: value.mood.trim() || "Introspective",
    energy: clamp(Math.round(Number(value.energy) || 0), 0, 100),
    bpm: clamp(Math.round(Number(value.bpm) || 96), 30, 300),
    duration: clamp(Number(value.duration) || 150, 5, 600),
    vocal_type: value.vocal_type || "female",
    vocal_intensity: clamp(Math.round(Number(value.vocal_intensity) || 0), 0, 100),
    singing_style: value.singing_style.trim(),
    vocal_emotion: value.vocal_emotion.trim(),
    vocal_range: value.vocal_range.trim(),
    vocal_prompt: value.vocal_prompt.trim(),
    pronunciation: value.pronunciation.trim(),
    instructions: value.instructions.trim(),
  };
}

function lyricsSignature(sections: LyricsSection[]): string {
  return JSON.stringify(
    sections.map((section) => ({
      id: section.id,
      type: section.type,
      label: section.label,
      content: section.content,
      instructions: section.instructions,
    })),
  );
}

function jobSections(job: Job | null | undefined): LyricsSection[] {
  const result = job?.result;
  const raw = result?.data?.sections ?? result?.sections;
  return Array.isArray(raw) ? normalizeSections(raw) : [];
}

function normalizeSections(raw: any): LyricsSection[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((section, index) => ({
    id: String(section?.id || uid(`lyric${index}`)),
    type: String(section?.type || "verse"),
    label: String(section?.label || SECTION_LABELS[String(section?.type || "verse")] || "Section"),
    content: String(section?.content || ""),
    instructions: String(section?.instructions || ""),
  }));
}

function makeDemoSong(spec: any, index: number): MusicSong {
  const project = demoProjects.find((item) => item.id === spec.project_id);
  const language = spec.language || "en";
  return {
    id: spec.id,
    project_id: spec.project_id,
    project_title: project?.title,
    project_color: project?.color,
    title: spec.title,
    artist: spec.artist || project?.artist || "Open Studio",
    language,
    language_label: LANG_LABELS[language] || language,
    genre: spec.genre || "Ambient",
    subgenre: spec.subgenre || "",
    style: spec.style || "",
    mood: spec.mood || "Serene",
    energy: Number(spec.energy ?? 44),
    bpm: Number(spec.bpm ?? 90),
    duration: Number(spec.duration ?? 180),
    vocal_type: spec.vocal_type || "female",
    vocal_intensity: Number(spec.vocal_intensity ?? 50),
    singing_style: spec.singing_style || "Melodic",
    vocal_emotion: spec.vocal_emotion || "Intimate",
    vocal_range: spec.vocal_range || "Alto",
    vocal_prompt: spec.vocal_prompt || "",
    pronunciation: spec.pronunciation || "",
    instructions: spec.instructions || "",
    provider: "ace_step",
    model_id: spec.model_id || "acestep-v15-turbo",
    selected_take_id: spec.selected_take_id || null,
    take_count: Number(spec.take_count ?? 0),
    created_at: spec.created_at || isoMinutesAgo(900 + index * 30),
    updated_at: spec.updated_at || isoMinutesAgo(120 + index * 25),
  };
}

function defaultLyricsFor(song: MusicSong): LyricsSection[] {
  return [
    { id: uid("lyric"), type: "intro", label: "Intro", content: "", instructions: "Set the room tone. Let the first line arrive late." },
    { id: uid("lyric"), type: "verse", label: "Verse 1", content: "", instructions: `Close-mic, ${(song.mood || "intimate").toLowerCase()} delivery.` },
    { id: uid("lyric"), type: "chorus", label: "Chorus", content: "", instructions: "Open the harmony. Wider and higher than the verse." },
    { id: uid("lyric"), type: "outro", label: "Outro", content: "", instructions: "Leave space. Fade on breath, not on an edit." },
  ];
}

function makeDemoTakes(): MusicTake[] {
  const base: MusicTake[] = demoTakes.map((take, index) => ({
    id: take.id,
    song_id: "s1",
    job_id: index < 2 ? "job_78a2b901" : "job_5c21repaint",
    position: index,
    path: take.path,
    duration: Number(take.duration),
    seed: take.seed,
    metadata: take.metadata,
    is_favorite: Boolean(take.favorite),
    notes: "",
    created_at: take.created_at,
    bpm: Number(take.bpm),
  }));
  base.push(
    {
      id: "t4",
      song_id: "s1",
      job_id: "job_b71c40e2",
      position: 3,
      path: "music/nocturno/takes/nocturno-bridge-repaint.wav",
      duration: 62.4,
      seed: "438923",
      metadata: { mode: "repaint", model: "acestep-v15-sft", range: "0:42 → 1:44" },
      is_favorite: false,
      notes: "Bridge rebuild with the SFT checkpoint.",
      created_at: isoMinutesAgo(140),
      bpm: 78,
    },
    {
      id: "t5",
      song_id: "s1",
      job_id: "job_98ac21de",
      position: 4,
      path: "music/nocturno/takes/nocturno-extended-outro.wav",
      duration: 238.7,
      seed: "438924",
      metadata: { mode: "extend", model: "acestep-v15-sft" },
      is_favorite: false,
      notes: "Extended outro, keeps the final breath.",
      created_at: isoMinutesAgo(230),
      bpm: 78,
    },
  );
  return base;
}

function demoDraftSections(): LyricsSection[] {
  return [
    { id: uid("draft"), type: "verse", label: "Verse 1", content: "Midnight folds the avenue in blue\nEvery window keeps a version of you\nI count the streetlights like a metronome\nFinding my way by the sound of home", instructions: "Close, almost whispered" },
    { id: uid("draft"), type: "pre-chorus", label: "Pre-Chorus", content: "Hold the door, the city's breathing in\nOne more step before the light begins", instructions: "Tighter, building" },
    { id: uid("draft"), type: "chorus", label: "Chorus", content: "Nocturno, carry me slow\nThrough the quiet where the city goes\nNocturno, don't let me wake\nI'll keep the darkness for daylight's sake", instructions: "Open harmony, wide reverb" },
    { id: uid("draft"), type: "verse", label: "Verse 2", content: "Paper moon above the kiosk glow\nAll the roads I know are letting go\nIf morning finds us out of time\nLeave a little of the night behind", instructions: "Lower register, restrained" },
    { id: uid("draft"), type: "chorus", label: "Chorus", content: "Nocturno, carry me slow\nThrough the quiet where the city goes\nNocturno, don't let me wake\nI'll keep the darkness for daylight's sake", instructions: "Full harmony, lift the last line" },
    { id: uid("draft"), type: "outro", label: "Outro", content: "Nocturno...\nDon't wake me yet", instructions: "Fade on breath" },
  ];
}

function normalizeOptions(raw: any): Record<string, any> {
  const value = raw || {};
  const demoOptions = (demoMusicCatalog as any).options || {};
  const pick = (key: string): any => {
    if (Array.isArray(value[key]) && value[key].length) return value[key];
    if (Array.isArray(demoOptions[key]) && demoOptions[key].length) return demoOptions[key];
    return FALLBACK_OPTIONS[key];
  };
  return {
    ...FALLBACK_OPTIONS,
    ...value,
    modes: pick("modes"),
    audio_formats: pick("audio_formats"),
    export_formats: pick("export_formats"),
    infer_methods: pick("infer_methods"),
    vocal_types: pick("vocal_types"),
    section_types: pick("section_types"),
    moods: pick("moods"),
    singing_styles: pick("singing_styles"),
    vocal_emotions: pick("vocal_emotions"),
    vocal_ranges: pick("vocal_ranges"),
    energy_labels: pick("energy_labels"),
    project_colors: pick("project_colors"),
    structures: pick("structures"),
    style_suggestions: pick("style_suggestions"),
    genres: value.genres ?? demoOptions.genres ?? FALLBACK_OPTIONS.genres,
  };
}

function flattenGenres(value: any): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item));
  if (value && typeof value === "object") {
    const output: string[] = [];
    Object.values(value).forEach((group) => {
      if (Array.isArray(group)) output.push(...group.map((item) => String(item)));
      else if (typeof group === "string") output.push(group);
    });
    return output;
  }
  return [];
}

function choiceOptions(value: any, fallback: Array<{ value: string; label: string }>): Array<{ value: string; label: string }> {
  if (Array.isArray(value) && value.length) {
    return value
      .map((item) => {
        if (typeof item === "string") return { value: item, label: pretty(item) };
        const key = String(item?.value ?? item?.id ?? "");
        return { value: key, label: String(item?.label ?? item?.name ?? key) };
      })
      .filter((item) => item.value);
  }
  return fallback;
}

function stringOptions(value: any, fallback: string[]): string[] {
  if (Array.isArray(value) && value.length) {
    return value.map((item) => (typeof item === "string" ? item : String(item?.label ?? item?.value ?? item))).filter(Boolean);
  }
  return fallback;
}

/* ------------------------------------------------------------------ demo init */
function initializeDemo(): void {
  projects.value = clone(demoProjects).map((project, index) => ({
    ...project,
    cover: DEMO_ART[index % DEMO_ART.length],
    last_activity: project.updated_at,
  }));

  const primary = demoSongs.map((song, index) =>
    makeDemoSong(
      {
        ...song,
        subgenre: index === 0 ? "Chamber pop" : index === 1 ? "Dream pop" : index === 2 ? "Synth-pop" : "Piano ballad",
        style: index === 0 ? "intimate, analog warmth, nylon guitar, brushed drums, close vocal" : index === 1 ? "Dreamy pads, wide stereo, tape saturation" : index === 2 ? "Analog synth, gated drums, neon haze" : "Sparse piano, room noise, vocal at the edge of breath",
        energy: [42, 56, 63, 33][index] ?? 45,
        vocal_prompt: "Close, intimate lead with airy doubles in the chorus. Keep the consonants soft.",
        pronunciation: "European Portuguese. Final vowels are quiet, never Brazilianised.",
        instructions: "Keep the arrangement nocturnal and uncluttered. Let the vocal carry the story; no big drum entrance before the second chorus.",
        selected_take_id: song.id === "s1" ? "t1" : null,
      },
      index,
    ),
  );

  const extras: Array<Record<string, any>> = [
    { id: "s5", project_id: "atravessar-noite", title: "Atravessar a Noite", genre: "Fado", subgenre: "Alternative fado", mood: "Mournful", bpm: 72, duration: 236, language: "pt-PT", take_count: 3, energy: 36, style: "nylon guitar, cello, live room, almost no percussion", vocal_prompt: "Restrained fado delivery. Let the last syllable fall.", instructions: "Recorded live in one room. Keep the guitar and voice in the same space." },
    { id: "s6", project_id: "atravessar-noite", title: "Rio de Vidro", genre: "Art pop", subgenre: "Chamber pop", mood: "Yearning", bpm: 88, duration: 205, language: "pt-PT", take_count: 2, energy: 52, style: "muted trumpet, brushed drums, wide stereo", vocal_prompt: "Warm mezzo lead, light harmony on the hook.", instructions: "The river is a mirror. Keep the second verse lower and closer." },
    { id: "s7", project_id: "atravessar-noite", title: "A Última Luz", genre: "Fado", subgenre: "Fado canção", mood: "Serene", bpm: 64, duration: 198, language: "pt-PT", take_count: 2, energy: 29, style: "solo guitar, room reverb, silence", vocal_prompt: "Barely above a whisper in the verses.", instructions: "Leave long silences. The final chord should ring until it disappears." },
    { id: "s8", project_id: "field-notes", title: "Tape Loop I", genre: "Ambient", subgenre: "Soundscape", mood: "Serene", bpm: 74, duration: 192, language: "en", take_count: 4, energy: 24, vocal_type: "instrumental", style: "tape loops, field recording, soft hiss", instructions: "No vocals. Build from a single four-bar loop, then let it drift." },
    { id: "s9", project_id: "field-notes", title: "Coastal Static", genre: "Ambient", subgenre: "Drone", mood: "Dreamy", bpm: 60, duration: 241, language: "en", take_count: 3, energy: 21, vocal_type: "instrumental", style: "ocean recordings, granular pads, long reverb", instructions: "Instrumental. The sea is the lead instrument." },
    { id: "s10", project_id: "field-notes", title: "Radio Tower", genre: "Electronic", subgenre: "Downtempo", mood: "Haunting", bpm: 92, duration: 188, language: "en", take_count: 3, energy: 48, vocal_type: "instrumental", style: "shortwave radio, sub bass, sparse percussion", instructions: "Instrumental. Keep the transmission fragile and slightly out of tune." },
    { id: "s11", project_id: "field-notes", title: "Rain on Glass", genre: "Ambient", subgenre: "Neoclassical", mood: "Introspective", bpm: 66, duration: 175, language: "en", take_count: 3, energy: 27, vocal_type: "instrumental", style: "felt piano, rain, close room", instructions: "Instrumental. Pedal noise and breath are part of the arrangement." },
    { id: "s12", project_id: "field-notes", title: "Night Train", genre: "Trip hop", subgenre: "Downtempo", mood: "Restless", bpm: 84, duration: 212, language: "en", take_count: 3, energy: 57, vocal_type: "instrumental", style: "vinyl drums, double bass, rail rhythm", instructions: "Instrumental. The rhythm should feel like a train that never quite stops." },
    { id: "s13", project_id: "field-notes", title: "Open Field", genre: "Folk", subgenre: "Indie folk", mood: "Hopeful", bpm: 78, duration: 167, language: "en", take_count: 2, energy: 41, vocal_type: "instrumental", style: "acoustic guitar, harmonium, wide air", instructions: "Instrumental. Let the harmonium hold the last note." },
  ];
  songs.value = [...primary, ...extras.map((spec, index) => makeDemoSong(spec, primary.length + index))];

  demoTakeCache.value = makeDemoTakes();
  demoLyricsCache.value = { s1: normalizeSections(clone(demoLyrics.sections)) };

  const nocturno = projects.value.find((project) => project.id === "nocturno") || projects.value[0];
  const song = songs.value.find((item) => item.id === "s1") || songs.value[0];
  if (nocturno) selectedProjectId.value = nocturno.id;
  if (song) activateSong(song, demoTakeCache.value, demoLyricsCache.value[song.id] || defaultLyricsFor(song));
  catalog.value = demoMusicCatalog;
  musicSystem.value = DEMO_SYSTEM;
  styles.value = [
    { id: "style-warm-analog", name: "Warm analog chamber pop", description: "Close-mic vocals, nylon guitar, brushed drums and tape saturation.", prompt: "intimate analog warmth, close vocal, nylon guitar, brushed drums, tape saturation, wide but natural stereo", tags: ["analog", "chamber pop", "intimate"], reference_path: "music/style-references/nocturno.wav", created_at: isoNow() },
    { id: "style-nocturnal", name: "Nocturnal city", description: "Sparse electronic pulse, wet asphalt textures and airy pads.", prompt: "nocturnal electronic pulse, wet asphalt ambience, airy pads, sub bass, restrained percussion, cinematic space", tags: ["electronic", "night", "cinematic"], reference_path: "music/style-references/glass-avenue.wav", created_at: isoNow() },
  ];
  currentJobId.value = demoJobs.find((job) => job.component === "music")?.id || demoJobs[0]?.id || "";
  genProvider.value = "ace_step";
  genModelId.value = (demoMusicCatalog as any).defaults?.model_id || "acestep-v15-turbo";
  if (!requestedTab) tab.value = "studio";
  syncGenerationDefaults();
}

/* ------------------------------------------------------------------ lifecycle */
onMounted(async () => {
  if (DEMO) return;
  await loadAll();
});

watch(tab, async (next) => {
  if (next === "studio" && !activeSong.value && songs.value.length) {
    await openSong(songs.value[0]);
  }
});

watch(
  () => brief.value.bpm,
  (value) => {
    if (!bpmOverride.value) genBpm.value = Number(value) || 96;
  },
);
watch(
  () => brief.value.duration,
  (value) => {
    if (!durationOverride.value) genDuration.value = Number(value) || 150;
  },
);
watch(sourceTakeId, (id) => {
  const take = takes.value.find((item) => item.id === id);
  if (!take) return;
  sourcePath.value = take.path;
  if (!endSeconds.value || endSeconds.value <= startSeconds.value) {
    endSeconds.value = Math.round(take.duration || brief.value.duration || 180);
  }
});
watch(
  () => jobs.byId(generationJobId.value)?.status,
  (status, previous) => {
    if (!DEMO && status === "completed" && previous && previous !== "completed" && activeSong.value) {
      void refreshTakes(activeSong.value.id);
      toasts.success("Generation finished — the new takes are ready.");
    }
  },
);

/* ------------------------------------------------------------------ data loading */
async function loadAll(): Promise<void> {
  loading.value = true;
  serviceError.value = "";
  const results = await Promise.allSettled([
    api.get<any>("/music/catalog"),
    api.get<{ items: any[] }>("/music/projects"),
    api.get<{ items: any[] }>("/music/songs?limit=500"),
    api.get<any>("/music/system"),
    api.get<{ items: any[] }>("/music/styles"),
  ]);
  const failures: string[] = [];

  if (results[0].status === "fulfilled") {
    catalog.value = results[0].value;
  } else {
    failures.push(errorMessage(results[0].reason));
  }
  if (results[1].status === "fulfilled") {
    projects.value = (results[1].value.items || []).map((project: any) => ({
      ...project,
      song_count: Number(project.song_count || 0),
      take_count: Number(project.take_count || 0),
      last_activity: project.last_activity || project.updated_at,
    })) as MusicProject[];
  } else {
    failures.push(errorMessage(results[1].reason));
  }
  if (results[2].status === "fulfilled") {
    songs.value = (results[2].value.items || []) as MusicSong[];
  } else {
    failures.push(errorMessage(results[2].reason));
  }
  if (results[3].status === "fulfilled") {
    musicSystem.value = results[3].value;
  }
  if (results[4].status === "fulfilled") {
    styles.value = results[4].value.items || [];
  }

  if (failures.length) {
    serviceError.value = failures[0];
    toasts.error(`Music service: ${failures[0]}`);
  }
  if (!selectedProjectId.value && projects.value.length) selectedProjectId.value = projects.value[0].id;
  loading.value = false;
  syncGenerationDefaults();
}

async function refreshAll(): Promise<void> {
  if (DEMO) {
    toasts.info("Demo workspace is already up to date.");
    return;
  }
  refreshing.value = true;
  await loadAll();
  if (activeSong.value) await reloadActiveSong(activeSong.value.id, true);
  refreshing.value = false;
  if (!serviceError.value) toasts.success("Music studio refreshed.");
}

async function reloadActiveSong(id: string, keepTab = true): Promise<void> {
  const summary = songs.value.find((song) => song.id === id);
  if (!summary) return;
  const token = ++loadToken;
  loadingSong.value = true;
  try {
    const [detail, takeData] = await Promise.all([
      api.get<MusicSong>(`/music/songs/${id}`),
      api.get<{ items: MusicTake[] }>(`/music/songs/${id}/takes`),
    ]);
    if (token !== loadToken) return;
    activateSong(detail, takeData.items || [], detail.lyrics?.sections || [], keepTab);
    replaceSong(detail);
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    if (token === loadToken) loadingSong.value = false;
  }
}

async function refreshTakes(id: string): Promise<void> {
  if (DEMO) return;
  try {
    const [detail, takeData] = await Promise.all([
      api.get<MusicSong>(`/music/songs/${id}`),
      api.get<{ items: MusicTake[] }>(`/music/songs/${id}/takes`),
    ]);
    if (activeSong.value?.id !== id) return;
    takes.value = takeData.items || [];
    activeSong.value.selected_take_id = detail.selected_take_id || takes.value[0]?.id || null;
    activeSong.value.take_count = takes.value.length;
    if (!sourceTakeId.value && takes.value.length) {
      sourceTakeId.value = takes.value[0].id;
      sourcePath.value = takes.value[0].path;
    }
    replaceSong({ ...activeSong.value, ...detail, lyrics: activeSong.value.lyrics });
  } catch (error: any) {
    toasts.error(error.message);
  }
}

/* ------------------------------------------------------------------ selection */
async function openSong(song: MusicSong, keepTab = false): Promise<void> {
  selectedProjectId.value = song.project_id;
  selectedSongId.value = song.id;
  if (!keepTab) tab.value = "studio";
  if (DEMO) {
    const cachedLyrics = demoLyricsCache.value[song.id] || defaultLyricsFor(song);
    const cachedTakes = song.id === "s1" ? demoTakeCache.value : [];
    const detail = songs.value.find((item) => item.id === song.id) || song;
    activateSong(clone(detail), cachedTakes, clone(cachedLyrics));
    return;
  }
  await reloadActiveSong(song.id, keepTab);
}

function activateSong(song: MusicSong, songTakes: MusicTake[], sections: any[], keepTab = true): void {
  void keepTab;
  activeSong.value = song;
  selectedSongId.value = song.id;
  selectedProjectId.value = song.project_id;
  brief.value = briefFromSong(song);
  briefSnapshot.value = JSON.stringify(brief.value);
  lyricsSections.value = normalizeSections(sections.length ? sections : defaultLyricsFor(song));
  lyricsSnapshot.value = lyricsSignature(lyricsSections.value);
  takes.value = songTakes;
  lastSavedAt.value = song.updated_at || isoNow();

  if (!song.selected_take_id && takes.value.length) song.selected_take_id = takes.value[0].id;
  const master = song.selected_take_id ? takes.value.find((take) => take.id === song.selected_take_id) : null;
  const source = master || takes.value.find((take) => take.is_favorite) || takes.value[0];
  sourceTakeId.value = source?.id || "";
  sourcePath.value = source?.path || "";
  startSeconds.value = 0;
  endSeconds.value = Math.round(source?.duration || song.duration || 180);

  genProvider.value = song.provider || catalog.value?.defaults?.provider || "ace_step";
  genModelId.value = song.model_id || catalog.value?.defaults?.model_id || "acestep-v15-turbo";
  genBpm.value = Number(song.bpm || 96);
  genDuration.value = Number(song.duration || 150);
  bpmOverride.value = false;
  durationOverride.value = false;
  syncGenerationDefaults();
  if (!sourceTakeId.value) sourceTakeId.value = "";
}

function syncGenerationDefaults(): void {
  const defaults = catalog.value?.defaults || {};
  const model = selectedModel.value;
  genVariations.value = clamp(Number(defaults.variations ?? 2), 1, 4);
  genSteps.value = Number(defaults.inference_steps ?? defaults.steps ?? model?.default_steps ?? 8);
  stepsAuto.value = true;
  genGuidance.value = Number(defaults.guidance_scale ?? defaults.guidance ?? model?.default_guidance ?? 1);
  guidanceAuto.value = true;
  audioFormat.value = defaults.audio_format || "wav";
  inferMethod.value = defaults.infer_method || "ode";
  lmBatchSize.value = clamp(Number(defaults.lm_batch_size ?? 1), 1, 4);
  synthBatchSize.value = clamp(Number(defaults.synth_batch_size ?? Math.min(2, genVariations.value)), 1, 9);
}

function replaceSong(song: MusicSong): void {
  const index = songs.value.findIndex((item) => item.id === song.id);
  if (index >= 0) songs.value[index] = { ...songs.value[index], ...song };
  else songs.value.unshift(song);
}

function openProject(project: MusicProject): void {
  selectedProjectId.value = project.id;
  libraryProject.value = project.id;
  tab.value = "library";
}

/* ------------------------------------------------------------------ projects */
function openProjectModal(project?: MusicProject): void {
  if (project) {
    projectForm.value = {
      id: project.id,
      title: project.title,
      artist: project.artist || "",
      description: project.description || "",
      color: project.color || defaultProjectColor(),
    };
  } else {
    projectForm.value = {
      id: "",
      title: "",
      artist: selectedProject.value?.artist || activeProjectName.value || "",
      description: "",
      color: defaultProjectColor(),
    };
  }
  projectModal.value = true;
}

async function saveProject(): Promise<void> {
  const title = projectForm.value.title.trim();
  if (!title) {
    toasts.error("Give the project a title first.");
    return;
  }
  savingProject.value = true;
  try {
    if (DEMO) {
      if (projectForm.value.id) {
        const project = projects.value.find((item) => item.id === projectForm.value.id);
        if (project) {
          Object.assign(project, {
            title,
            artist: projectForm.value.artist.trim(),
            description: projectForm.value.description.trim(),
            color: projectForm.value.color,
            updated_at: isoNow(),
            last_activity: isoNow(),
          });
        }
        toasts.success("Project updated.");
      } else {
        const project: MusicProject = {
          id: uid("project"),
          title,
          artist: projectForm.value.artist.trim(),
          description: projectForm.value.description.trim(),
          color: projectForm.value.color,
          song_count: 0,
          take_count: 0,
          updated_at: isoNow(),
          last_activity: isoNow(),
          cover: DEMO_ART[projects.value.length % DEMO_ART.length],
        };
        projects.value.push(project);
        selectedProjectId.value = project.id;
        toasts.success("Project created.");
      }
    } else {
      const payload = {
        title,
        artist: projectForm.value.artist.trim(),
        description: projectForm.value.description.trim(),
        color: projectForm.value.color,
      };
      if (projectForm.value.id) {
        const data = await api.patch<MusicProject>(`/music/projects/${projectForm.value.id}`, payload);
        const index = projects.value.findIndex((item) => item.id === data.id);
        if (index >= 0) projects.value[index] = { ...projects.value[index], ...data };
        toasts.success("Project updated.");
      } else {
        const data = await api.post<MusicProject>("/music/projects", payload);
        projects.value.unshift(data);
        selectedProjectId.value = data.id;
        toasts.success("Project created.");
      }
    }
    projectModal.value = false;
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    savingProject.value = false;
  }
}

function askDeleteProject(project: MusicProject): void {
  askConfirm(
    "Delete project",
    `“${project.title}”, its songs, takes and audio files will be permanently deleted. This cannot be undone.`,
    "Delete project",
    async () => {
      if (DEMO) {
        projects.value = projects.value.filter((item) => item.id !== project.id);
        songs.value = songs.value.filter((item) => item.project_id !== project.id);
      } else {
        await api.delete(`/music/projects/${project.id}`);
        projects.value = projects.value.filter((item) => item.id !== project.id);
        songs.value = songs.value.filter((item) => item.project_id !== project.id);
      }
      if (selectedProjectId.value === project.id) selectedProjectId.value = projects.value[0]?.id || null;
      if (libraryProject.value === project.id) libraryProject.value = "";
      if (activeSong.value?.project_id === project.id) {
        activeSong.value = null;
        selectedSongId.value = null;
        takes.value = [];
      }
      toasts.success("Project deleted.");
    },
  );
}

/* ------------------------------------------------------------------ songs */
function openNewSong(): void {
  if (!projects.value.length) {
    toasts.error("Create a project first.");
    openProjectModal();
    return;
  }
  const project = selectedProject.value || projects.value.find((item) => item.id === libraryProject.value) || projects.value[0];
  songForm.value = {
    project_id: project.id,
    title: "",
    artist: project.artist || "",
    language: "pt-PT",
    genre: "Art pop",
    mood: "Introspective",
    bpm: 96,
    duration: 180,
  };
  songModal.value = true;
}

async function createSong(): Promise<void> {
  if (!songForm.value.project_id) {
    toasts.error("Choose a project for the new song.");
    return;
  }
  if (!songForm.value.title.trim()) {
    toasts.error("Give the song a title first.");
    return;
  }
  savingNewSong.value = true;
  const project = projects.value.find((item) => item.id === songForm.value.project_id);
  try {
    if (DEMO) {
      const song = makeDemoSong(
        {
          id: uid("song"),
          project_id: songForm.value.project_id,
          title: songForm.value.title.trim(),
          artist: songForm.value.artist.trim(),
          language: songForm.value.language,
          genre: songForm.value.genre,
          mood: songForm.value.mood,
          bpm: clamp(Math.round(Number(songForm.value.bpm) || 96), 30, 300),
          duration: clamp(Number(songForm.value.duration) || 180, 5, 600),
          take_count: 0,
          created_at: isoNow(),
          updated_at: isoNow(),
        },
        songs.value.length,
      );
      songs.value.unshift(song);
      bumpProjectSongCount(song.project_id, 1);
      songModal.value = false;
      await openSong(song);
      toasts.success("Song created.");
    } else {
      const payload = {
        project_id: songForm.value.project_id,
        title: songForm.value.title.trim(),
        artist: songForm.value.artist.trim(),
        language: songForm.value.language,
        language_label: languageLabelFor(songForm.value.language),
        genre: songForm.value.genre.trim() || "Pop",
        mood: songForm.value.mood || "Introspective",
        bpm: clamp(Math.round(Number(songForm.value.bpm) || 96), 30, 300),
        duration: clamp(Number(songForm.value.duration) || 180, 5, 600),
      };
      const data = await api.post<MusicSong>(`/music/projects/${songForm.value.project_id}/songs`, payload);
      data.project_title = project?.title;
      data.project_color = project?.color;
      songs.value.unshift(data);
      bumpProjectSongCount(data.project_id, 1);
      songModal.value = false;
      await openSong(data);
      toasts.success("Song created.");
    }
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    savingNewSong.value = false;
  }
}

async function duplicateSong(): Promise<void> {
  if (!activeSong.value) return;
  const source = activeSong.value;
  if (DEMO) {
    const copy = clone(source);
    copy.id = uid("song");
    copy.title = `${source.title} (copy)`;
    copy.selected_take_id = null;
    copy.take_count = 0;
    copy.updated_at = isoNow();
    copy.created_at = isoNow();
    songs.value.unshift(copy);
    bumpProjectSongCount(copy.project_id, 1);
    demoLyricsCache.value[copy.id] = clone(lyricsSections.value);
    await openSong(copy);
    toasts.success("Song duplicated with its lyrics.");
    return;
  }
  try {
    await ensureSaved();
    const data = await api.post<MusicSong>(`/music/songs/${source.id}/duplicate`);
    data.project_title = source.project_title || activeProjectName.value;
    data.project_color = source.project_color;
    songs.value.unshift(data);
    bumpProjectSongCount(data.project_id, 1);
    await openSong(data);
    toasts.success("Song duplicated with its lyrics.");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function askDeleteSong(): void {
  if (!activeSong.value) return;
  const song = activeSong.value;
  askConfirm(
    "Delete song",
    `“${song.title}” and all of its generated takes and audio files will be permanently deleted.`,
    "Delete song",
    async () => {
      if (!DEMO) await api.delete(`/music/songs/${song.id}`);
      songs.value = songs.value.filter((item) => item.id !== song.id);
      bumpProjectSongCount(song.project_id, -1);
      demoLyricsCache.value[song.id] = [];
      activeSong.value = null;
      selectedSongId.value = null;
      takes.value = [];
      tab.value = "library";
      toasts.success("Song deleted.");
    },
  );
}

function bumpProjectSongCount(projectId: string, delta: number): void {
  const project = projects.value.find((item) => item.id === projectId);
  if (project) project.song_count = Math.max(0, project.song_count + delta);
}

async function saveSong(silent = false): Promise<void> {
  const song = activeSong.value;
  if (!song) return;
  const payload = briefPayload();
  savingSong.value = true;
  try {
    if (DEMO) {
      brief.value = { ...brief.value, ...payload };
      const updated: MusicSong = { ...song, ...payload, updated_at: isoNow() };
      activeSong.value = updated;
      replaceSong(updated);
      briefSnapshot.value = JSON.stringify(brief.value);
      lastSavedAt.value = isoNow();
      if (!silent) toasts.success("Song brief saved.");
    } else {
      const data = await api.patch<MusicSong>(`/music/songs/${song.id}`, payload);
      brief.value = { ...brief.value, ...payload };
      briefSnapshot.value = JSON.stringify(brief.value);
      activeSong.value = { ...activeSong.value, ...data, lyrics: activeSong.value?.lyrics };
      replaceSong(activeSong.value);
      lastSavedAt.value = isoNow();
      if (!silent) toasts.success("Song brief saved.");
    }
  } catch (error: any) {
    toasts.error(error.message);
    throw error;
  } finally {
    savingSong.value = false;
  }
}

/* ------------------------------------------------------------------ lyrics */
function addLyricSection(): void {
  const type = "verse";
  const verseCount = lyricsSections.value.filter((section) => section.type === "verse").length + 1;
  lyricsSections.value.push({
    id: uid("lyric"),
    type,
    label: `Verse ${verseCount}`,
    content: "",
    instructions: "",
  });
}

function removeLyricSection(index: number): void {
  lyricsSections.value.splice(index, 1);
}

function moveLyricSection(index: number, direction: number): void {
  const target = index + direction;
  if (target < 0 || target >= lyricsSections.value.length) return;
  const [section] = lyricsSections.value.splice(index, 1);
  lyricsSections.value.splice(target, 0, section);
}

function onSectionTypeChange(section: LyricsSection): void {
  const defaultLabel = SECTION_LABELS[section.type] || "Section";
  const previousDefaults = Object.values(SECTION_LABELS);
  if (!section.label.trim() || previousDefaults.includes(section.label.trim())) {
    section.label = defaultLabel;
  }
}

async function saveLyrics(silent = false): Promise<void> {
  const song = activeSong.value;
  if (!song) return;
  savingLyrics.value = true;
  try {
    if (DEMO) {
      lyricsSnapshot.value = lyricsSignature(lyricsSections.value);
      demoLyricsCache.value[song.id] = clone(lyricsSections.value);
      lastSavedAt.value = isoNow();
      if (!silent) toasts.success("Lyrics saved.");
    } else {
      const sections = lyricsSections.value.map(({ id, type, label, content, instructions }) => ({
        id,
        type,
        label,
        content,
        instructions,
      }));
      const data = await api.put<{ sections: LyricsSection[] }>(`/music/songs/${song.id}/lyrics`, { sections });
      lyricsSections.value = normalizeSections(data.sections || []);
      lyricsSnapshot.value = lyricsSignature(lyricsSections.value);
      lastSavedAt.value = isoNow();
      if (!silent) toasts.success("Lyrics saved.");
    }
  } catch (error: any) {
    toasts.error(error.message);
    throw error;
  } finally {
    savingLyrics.value = false;
  }
}

function openDraftModal(): void {
  if (!activeSong.value) return;
  if (!draftStructure.value.length) {
    draftStructure.value = [
      { type: "intro", label: "Intro", line_count: 2 },
      { type: "verse", label: "Verse 1", line_count: 4 },
      { type: "pre-chorus", label: "Pre-Chorus", line_count: 2 },
      { type: "chorus", label: "Chorus", line_count: 4 },
      { type: "verse", label: "Verse 2", line_count: 4 },
      { type: "chorus", label: "Chorus", line_count: 4 },
      { type: "outro", label: "Outro", line_count: 2 },
    ];
  }
  draftTheme.value = brief.value.instructions || `${brief.value.mood} ${brief.value.genre.toLowerCase()} song about crossing a city after midnight.`;
  draftDirection.value = brief.value.vocal_prompt || `${brief.value.vocal_type} lead, ${brief.value.singing_style.toLowerCase()} phrasing, ${brief.value.vocal_emotion.toLowerCase()} delivery.`;
  draftModal.value = true;
}

function addDraftPlan(): void {
  draftStructure.value.push({ type: "verse", label: "Verse", line_count: 4 });
}

function removeDraftPlan(index: number): void {
  draftStructure.value.splice(index, 1);
}

function syncDraftPlanLabel(plan: DraftPlan): void {
  const defaultLabel = SECTION_LABELS[plan.type] || "Section";
  if (!plan.label.trim() || Object.values(SECTION_LABELS).includes(plan.label.trim())) plan.label = defaultLabel;
}

async function requestDraft(): Promise<void> {
  const song = activeSong.value;
  if (!song) return;
  if (!draftTheme.value.trim() && !draftDirection.value.trim()) {
    toasts.error("Add a theme or some creative direction for the lyricist.");
    return;
  }
  const structure = draftStructure.value.filter((item) => item.line_count > 0).map(({ type, label, line_count }) => ({ type, label, line_count: clamp(Math.round(line_count), 1, 16) }));
  if (!structure.length) {
    toasts.error("Add at least one section to the lyric structure.");
    return;
  }
  if (DEMO) {
    localDraftSections.value = demoDraftSections();
    draftJobId.value = "";
    draftModal.value = false;
    toasts.success("Demo lyric draft is ready to apply.");
    return;
  }
  drafting.value = true;
  try {
    const job = await api.post<Job>("/music/lyrics/draft", {
      song_id: song.id,

      title: song.title,
      theme: draftTheme.value.trim(),
      direction: draftDirection.value.trim(),
      genre: brief.value.genre,
      subgenre: brief.value.subgenre,
      style: brief.value.style,
      mood: brief.value.mood,
      energy: clamp(Math.round(brief.value.energy), 0, 100),
      language: brief.value.language,
      language_label: languageLabelFor(brief.value.language),
      vocal_type: brief.value.vocal_type,
      structure,
      save: false,
    });
    jobs.upsert(job);
    jobs.connect();
    draftJobId.value = job.id;
    localDraftSections.value = null;
    draftModal.value = false;
    toasts.success("The lyricist is working — progress appears in the Lyrics panel.");
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    drafting.value = false;
  }
}

function applyDraft(): void {
  const sections = draftReadySections.value;
  if (!sections.length) return;
  lyricsSections.value = sections.map((section) => ({
    id: uid("lyric"),
    type: section.type,
    label: section.label,
    content: section.content,
    instructions: section.instructions,
  }));
  localDraftSections.value = null;
  draftJobId.value = "";
  toasts.success("Draft applied. Review the sections and save the lyrics.");
}

function dismissDraft(): void {
  localDraftSections.value = null;
  draftJobId.value = "";
}

async function refreshDraftJob(): Promise<void> {
  if (!draftJobId.value) return;
  if (DEMO) {
    toasts.info("Demo draft is already available.");
    return;
  }
  try {
    const job = await api.get<Job>(`/jobs/${draftJobId.value}`);
    jobs.upsert(job);
    if (job.status === "completed" && jobSections(job).length) toasts.success("Draft ready to apply.");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

/* ------------------------------------------------------------------ takes */
function takeName(take: MusicTake): string {
  return take.name || fileBase(take.path);
}

function takeTitle(take: MusicTake): string {
  return `Take ${String(Number(take.position || 0) + 1).padStart(2, "0")}`;
}

function modelName(id?: string | null): string {
  const model = models.value.find((item: any) => item.id === id);
  return model?.name || id || "ACE-Step 1.5 Turbo";
}

async function toggleTakeFavorite(take: MusicTake): Promise<void> {
  const next = !take.is_favorite;
  if (DEMO) {
    take.is_favorite = next;
    toasts.success(next ? `${takeTitle(take)} added to favorites.` : `${takeTitle(take)} removed from favorites.`);
    return;
  }
  try {
    const data = await api.patch<MusicTake>(`/music/takes/${take.id}`, { is_favorite: next });
    const index = takes.value.findIndex((item) => item.id === take.id);
    if (index >= 0) takes.value[index] = { ...takes.value[index], ...data };
    toasts.success(next ? "Take favorited." : "Favorite removed.");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function makeMaster(take: MusicTake): Promise<void> {
  if (!activeSong.value) return;
  const previousMaster = activeSong.value.selected_take_id;
  if (DEMO) {
    activeSong.value.selected_take_id = take.id;
    const index = songs.value.findIndex((item) => item.id === activeSong.value?.id);
    if (index >= 0) songs.value[index].selected_take_id = take.id;
    if (!sourceTakeId.value || sourceTakeId.value === previousMaster) {
      sourceTakeId.value = take.id;
      sourcePath.value = take.path;
    }
    compareModal.value = false;
    toasts.success(`${takeTitle(take)} is now the master take.`);
    return;
  }
  try {
    const data = await api.post<MusicSong>(`/music/songs/${activeSong.value.id}/select-take`, { take_id: take.id });
    activeSong.value.selected_take_id = data.selected_take_id || take.id;
    const index = songs.value.findIndex((item) => item.id === data.id);
    if (index >= 0) songs.value[index].selected_take_id = activeSong.value.selected_take_id;
    if (!sourceTakeId.value || sourceTakeId.value === previousMaster) {
      sourceTakeId.value = take.id;
      sourcePath.value = take.path;
    }
    compareModal.value = false;
    toasts.success(`${takeTitle(take)} is now the master take.`);
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function askDeleteTake(take: MusicTake): void {
  askConfirm(
    "Delete take",
    `${takeTitle(take)} and its audio file will be permanently deleted.`,
    "Delete take",
    async () => {
      if (!DEMO) await api.delete(`/music/takes/${take.id}`);
      takes.value = takes.value.filter((item) => item.id !== take.id);
      if (DEMO && activeSong.value?.id === "s1") demoTakeCache.value = takes.value;
      if (activeSong.value) {
        if (activeSong.value.selected_take_id === take.id) activeSong.value.selected_take_id = takes.value[0]?.id || null;
        activeSong.value.take_count = takes.value.length;
      }
      if (sourceTakeId.value === take.id) {
        sourceTakeId.value = takes.value[0]?.id || "";
        sourcePath.value = takes.value[0]?.path || "";
      }
      toasts.success("Take deleted.");
    },
  );
}

function openCompare(first?: MusicTake): void {
  const primary = first?.id || masterTake.value?.id || takes.value[0]?.id || "";
  compareA.value = primary;
  compareB.value = takes.value.find((take) => take.id !== primary)?.id || "";
  compareModal.value = true;
}

/* ------------------------------------------------------------------ export */
function openSongExport(): void {
  if (!activeSong.value) return;
  exportTarget.value = { kind: "song", id: activeSong.value.id, title: activeSong.value.title };
  exportFormat.value = "wav";
  exportIncludeAll.value = true;
  exportModal.value = true;
}

function openProjectExport(project: MusicProject): void {
  exportTarget.value = { kind: "project", id: project.id, title: project.title };
  exportFormat.value = "zip";
  exportModal.value = true;
}

async function submitExport(): Promise<void> {
  const target = exportTarget.value;
  if (!target) return;
  const format = target.kind === "project" ? "zip" : exportFormat.value;
  if (DEMO) {
    toasts.success(`Demo: ${target.kind === "project" ? "session ZIP" : format.toUpperCase()} export queued for “${target.title}”.`);
    exportModal.value = false;
    return;
  }
  exporting.value = true;
  try {
    if (target.kind === "song" || activeSong.value?.project_id === target.id) await ensureSaved();
    const payload =
      target.kind === "project"
        ? { project_id: target.id, format: "zip", kind: "project" }
        : format === "zip"
          ? { song_id: target.id, format: "zip", include_all_takes: exportIncludeAll.value }
          : { song_id: target.id, format, include_all_takes: exportIncludeAll.value };
    const job = await api.post<Job>("/music/export", payload);
    jobs.upsert(job);
    jobs.connect();
    currentJobId.value = job.id;
    exportModal.value = false;
    toasts.success("Export queued. The finished file will appear in shared storage.");
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    exporting.value = false;
  }
}

async function exportTake(take: MusicTake, format: string): Promise<void> {
  if (!activeSong.value) return;
  if (DEMO) {
    toasts.success(`Demo: ${format.toUpperCase()} export queued for ${takeTitle(take)}.`);
    return;
  }
  try {
    const job = await api.post<Job>("/music/export", {
      song_id: activeSong.value.id,
      take_id: take.id,
      format,
      include_all_takes: false,
    });
    jobs.upsert(job);
    jobs.connect();
    currentJobId.value = job.id;
    toasts.success(`${format.toUpperCase()} export queued for ${takeTitle(take)}.`);
  } catch (error: any) {
    toasts.error(error.message);
  }
}

/* ------------------------------------------------------------------ generation */
function modeSupported(id: string): boolean {
  const model = selectedModel.value;
  if (!model) return true;
  const capabilities = model.capabilities;
  const key = MODE_CAPABILITY[id];
  if (Array.isArray(capabilities)) return id === "full" ? true : capabilities.includes(key) || capabilities.includes(id);
  if (capabilities && typeof capabilities === "object") return Boolean(capabilities[key]);
  return true;
}

function selectMode(id: string): void {
  if (!modeSupported(id)) return;
  genMode.value = id;
  const source = takes.value.find((take) => take.id === sourceTakeId.value) || masterTake.value;
  if (id === "repaint" && (!endSeconds.value || endSeconds.value <= startSeconds.value)) {
    endSeconds.value = Math.round(source?.duration || brief.value.duration || 180);
  }
}

function rollSeed(): void {
  seed.value = Math.floor(100000 + Math.random() * 899999999);
  seedEnabled.value = true;
}

function openStyleModal(): void {
  styleForm.value = { name: "", description: "", prompt: "", tags: "", reference_path: "", reference_name: "" };
  styleOpen.value = true;
}

function onStyleAudio(path: string, file: any): void {
  styleForm.value.reference_path = path;
  styleForm.value.reference_name = file?.name || path.split("/").pop() || "reference audio";
}

async function saveStyle(): Promise<void> {
  if (!styleForm.value.name.trim()) {
    toasts.error("Give the style a name.");
    return;
  }
  if (!styleForm.value.reference_path) {
    toasts.error("Choose a reference audio file.");
    return;
  }
  styleSaving.value = true;
  try {
    if (DEMO) {
      const created = {
        id: `style-${Date.now()}`,
        name: styleForm.value.name.trim(),
        description: styleForm.value.description,
        prompt: styleForm.value.prompt,
        tags: styleForm.value.tags.split(",").map((tag) => tag.trim()).filter(Boolean),
        reference_path: styleForm.value.reference_path,
        created_at: isoNow(),
      };
      styles.value.unshift(created);
      selectedStyleId.value = created.id;
    } else {
      const created = await api.post<any>("/music/styles", {
        name: styleForm.value.name.trim(),
        description: styleForm.value.description.trim(),
        prompt: styleForm.value.prompt.trim(),
        tags: styleForm.value.tags,
        reference_path: styleForm.value.reference_path,
      });
      styles.value.unshift(created);
      selectedStyleId.value = created.id;
    }
    styleOpen.value = false;
    toasts.success("Style profile added. Select it before generating.");
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    styleSaving.value = false;
  }
}

async function deleteStyle(style: any): Promise<void> {
  try {
    if (!DEMO) await api.delete(`/music/styles/${style.id}`);
    styles.value = styles.value.filter((item) => item.id !== style.id);
    if (selectedStyleId.value === style.id) selectedStyleId.value = "";
    toasts.success(`Removed ${style.name}`);
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function openSourcePicker(): void {
  if (DEMO) {
    const take = takes.value.find((item) => item.id === sourceTakeId.value) || takes.value[0];
    if (take) {
      sourcePath.value = take.path;
      sourceTakeId.value = take.id;
      toasts.info(`Demo source set to ${takeName(take)}.`);
    } else {
      toasts.info("Generate a take first to use it as source audio.");
    }
    return;
  }
  sourcePicker.value = true;
}

function openReferencePicker(): void {
  if (DEMO) {
    referencePath.value = takes.value[0]?.path || "music/nocturno/takes/nocturno-v2.wav";
    toasts.info("Demo reference audio selected.");
    return;
  }
  referencePicker.value = true;
}

function onSourceSelected(path: string): void {
  sourcePath.value = path;
  sourceTakeId.value = "";
  toasts.success(`Source audio: ${fileBase(path)}`);
}

function onReferenceSelected(path: string): void {
  referencePath.value = path;
  toasts.success(`Reference audio: ${fileBase(path)}`);
}

async function ensureSaved(): Promise<void> {
  if (DEMO || !activeSong.value) return;
  if (briefDirty.value) await saveSong(true);
  if (lyricsDirty.value) await saveLyrics(true);
}

async function generateTakes(): Promise<void> {
  const song = activeSong.value;
  if (!song) {
    toasts.error("Choose a song first.");
    return;
  }
  if (generationBlockedReason.value) {
    toasts.error(generationBlockedReason.value);
    return;
  }
  if (DEMO) {
    toasts.success(`Demo: ${genVariations.value} ${genMode.value} take(s) queued for “${song.title}”.`);
    return;
  }
  generating.value = true;
  try {
    await ensureSaved();
    const payload = {
      provider: genProvider.value,
      model_id: genModelId.value,
      mode: genMode.value,
      variations: clamp(Math.round(genVariations.value), 1, 4),
      seed: seedEnabled.value ? clamp(Math.round(Number(seed.value) || 0), 0, 2 ** 63 - 1) : null,
      inference_steps: stepsAuto.value ? null : clamp(Math.round(Number(genSteps.value) || 1), 1, 200),
      guidance_scale: guidanceAuto.value ? null : clamp(Number(genGuidance.value) || 0, 0, 30),
      thinking: thinking.value,
      use_format: useFormat.value,
      enhance_prompt: enhancePrompt.value,
      instruction: genInstruction.value.trim(),
      vocal_language: brief.value.language,
      duration: durationOverride.value ? clamp(Number(genDuration.value) || 150, 5, 600) : null,
      bpm: bpmOverride.value ? clamp(Math.round(Number(genBpm.value) || 96), 30, 300) : null,
      source_path: genMode.value === "full" ? null : sourcePath.value || null,
      reference_path: referencePath.value || null,
      style_id: selectedStyleId.value || null,
      start_seconds: genMode.value === "repaint" ? clamp(Number(startSeconds.value) || 0, 0, 600) : null,
      end_seconds: genMode.value === "repaint" ? clamp(Number(endSeconds.value) || 1, 0.1, 600) : null,
      cover_strength: clamp(Number(coverStrength.value) || 0, 0, 1),
      infer_method: inferMethod.value,
      audio_format: audioFormat.value,
      lm_batch_size: clamp(Math.round(Number(lmBatchSize.value) || 1), 1, 4),
      synth_batch_size: clamp(Math.round(Number(synthBatchSize.value) || 1), 1, 9),
    };
    const job = await api.post<Job>(`/music/songs/${song.id}/generate`, payload);
    jobs.upsert(job);
    jobs.connect();
    currentJobId.value = job.id;
    generationJobId.value = job.id;
    toasts.success(`Generation queued — ${genVariations.value} take(s) on ${modelName(genModelId.value)}.`);
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    generating.value = false;
  }
}

async function cancelJob(id: string): Promise<void> {
  if (DEMO) {
    toasts.info("Demo jobs keep their illustrative state.");
    return;
  }
  try {
    await jobs.cancel(id);
    toasts.info("Cancellation requested.");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function retryJob(id: string): Promise<void> {
  if (DEMO) {
    toasts.info("Demo jobs cannot be retried.");
    return;
  }
  try {
    await jobs.retry(id);
    toasts.success("Job restarted.");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function removeJob(id: string): Promise<void> {
  if (DEMO) {
    toasts.info("Demo job records are read-only.");
    return;
  }
  try {
    await jobs.remove(id);
    if (currentJobId.value === id) currentJobId.value = "";
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function demoLinkToast(): void {
  toasts.info("Demo audio is illustrative — use Export to queue a real render.");
}

/* ------------------------------------------------------------------ confirm */
function askConfirm(title: string, message: string, label: string, action: ConfirmAction): void {
  confirmTitle.value = title;
  confirmMessage.value = message;
  confirmLabel.value = label;
  confirmAction.value = action;
  confirmOpen.value = true;
}

async function executeConfirm(): Promise<void> {
  if (!confirmAction.value) return;
  confirming.value = true;
  try {
    await confirmAction.value();
    confirmOpen.value = false;
    confirmAction.value = null;
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    confirming.value = false;
  }
}

/* ------------------------------------------------------------------ derived catalog */
const models = computed<any[]>(() => (Array.isArray(catalog.value?.models) ? catalog.value.models : []));
const engines = computed<any[]>(() => (Array.isArray(catalog.value?.engines) ? catalog.value.engines : []));
const options = computed<Record<string, any>>(() => normalizeOptions(catalog.value?.options));

const languageOptions = computed<Array<{ code: string; label: string }>>(() => {
  const raw = catalog.value?.languages;
  if (Array.isArray(raw) && raw.length) {
    return raw
      .map((item: any) => ({ code: String(item.code || item.id || ""), label: String(item.label || item.name || item.code || "") }))
      .filter((item: { code: string }) => item.code);
  }
  return Object.entries(LANG_LABELS).map(([code, label]) => ({ code, label }));
});

const genreSuggestions = computed<string[]>(() => flattenGenres(options.value.genres));
const moodOptions = computed<string[]>(() => stringOptions(options.value.moods, FALLBACK_OPTIONS.moods));
const singingStyleOptions = computed<string[]>(() => stringOptions(options.value.singing_styles, FALLBACK_OPTIONS.singing_styles));
const vocalEmotionOptions = computed<string[]>(() => stringOptions(options.value.vocal_emotions, FALLBACK_OPTIONS.vocal_emotions));
const vocalRangeOptions = computed<string[]>(() => stringOptions(options.value.vocal_ranges, FALLBACK_OPTIONS.vocal_ranges));
const styleSuggestions = computed<string[]>(() => stringOptions(options.value.style_suggestions, FALLBACK_OPTIONS.style_suggestions));
const vocalTypeOptions = computed<Array<{ value: string; label: string }>>(() => choiceOptions(options.value.vocal_types, FALLBACK_VOCAL_TYPES));
const audioFormatOptions = computed<Array<{ value: string; label: string }>>(() => choiceOptions(options.value.audio_formats, FALLBACK_AUDIO_FORMATS.map((item) => ({ value: item.id, label: item.label }))));
const inferMethodOptions = computed<Array<{ value: string; label: string }>>(() => choiceOptions(options.value.infer_methods, FALLBACK_INFER_METHODS.map((item) => ({ value: item.id, label: item.label }))));
const exportFormatOptions = computed<Array<{ value: string; label: string }>>(() => choiceOptions(options.value.export_formats, FALLBACK_EXPORT_FORMATS.map((item) => ({ value: item.id, label: item.label }))));
const projectColorOptions = computed<Array<{ id: string; label: string; hex: string }>>(() => {
  const raw = options.value.project_colors;
  if (Array.isArray(raw) && raw.length) {
    return raw.map((item: any, index: number) => {
      const id = String(item.id || item.value || `color-${index}`);
      return { id, label: String(item.label || pretty(id)), hex: String(item.hex || colorHex(id)) };
    });
  }
  return FALLBACK_OPTIONS.project_colors;
});
const energyLabels = computed<Array<{ value: number; label: string }>>(() => {
  const raw = options.value.energy_labels;
  if (Array.isArray(raw) && raw.length) {
    return raw
      .map((item: any) => (typeof item === "number" ? { value: item, label: String(item) } : { value: Number(item.value ?? 0), label: String(item.label ?? item.value ?? "") }))
      .filter((item: { label: string }) => item.label);
  }
  return FALLBACK_OPTIONS.energy_labels;
});
const modeOptions = computed<any[]>(() =>
  BASE_MODES.map((base) => {
    const remote = Array.isArray(options.value.modes) ? options.value.modes.find((mode: any) => mode.id === base.id) : null;
    return { ...base, ...(remote || {}) };
  }),
);

const selectedModel = computed<any>(() => models.value.find((model) => model.id === genModelId.value) || models.value[0] || null);
watch(
  () => selectedModel.value,
  (model) => {
    if (!model) return;
    if (!modeSupported(genMode.value)) genMode.value = "full";
    if (stepsAuto.value) genSteps.value = Number(model?.controls?.inference_steps?.default ?? model?.controls?.steps?.default ?? model?.default_steps ?? 8);
    if (guidanceAuto.value) genGuidance.value = Number(model?.controls?.guidance_scale?.default ?? model?.controls?.guidance?.default ?? model?.default_guidance ?? 1);
  },
);
const selectedEngine = computed<any>(() => engines.value.find((engine) => engine.id === genProvider.value) || engines.value[0] || null);
const selectedStyle = computed<any>(() => styles.value.find((style) => style.id === selectedStyleId.value) || null);
const selectedModeMeta = computed<any>(() => modeOptions.value.find((mode) => mode.id === genMode.value) || modeOptions.value[0]);
const selectedModeSupported = computed<boolean>(() => modeSupported(genMode.value));
const batchProduct = computed<number>(() => Number(lmBatchSize.value) * Number(synthBatchSize.value));

const maxVariations = computed<number>(() => clamp(Number(selectedModel.value?.controls?.variations?.max ?? selectedModel.value?.capabilities?.max_variations ?? 4), 1, 4));
watch(maxVariations, (max) => {
  if (genVariations.value > max) genVariations.value = max;
});

const engineKnown = computed<boolean>(() => DEMO || Boolean(catalog.value || musicSystem.value || serviceError.value));
const engineOnline = computed<boolean>(() => {
  if (DEMO) return true;
  if (musicSystem.value && typeof musicSystem.value.available === "boolean") return Boolean(musicSystem.value.available);
  if (selectedEngine.value && typeof selectedEngine.value.available === "boolean") return Boolean(selectedEngine.value.available);
  return false;
});
const engineOffline = computed<boolean>(() => engineKnown.value && !engineOnline.value);
const engineLabel = computed<string>(() => (!engineKnown.value ? "connecting…" : engineOnline.value ? "ready" : "offline"));
const engineStatusText = computed<string>(() => (engineOnline.value ? "Engine responding" : "Engine unreachable"));
const engineDetail = computed<string>(() => musicSystem.value?.status_detail || selectedEngine.value?.status_detail || selectedEngine.value?.detail || (engineOnline.value ? "ACE-Step GGUF engine ready." : "The ACE-Step engine is not reachable."));
const engineVersion = computed<string>(() => String(musicSystem.value?.version || selectedEngine.value?.version || "1.5.0"));
const engineUrl = computed<string>(() => String(musicSystem.value?.engine_url || selectedEngine.value?.engine_url || "http://music-engine:8000"));
const engineBackend = computed<string>(() => String(selectedEngine.value?.backend || "acestep.cpp / GGUF · CPU / CUDA / Vulkan"));
const engineModelDir = computed<string>(() => String(musicSystem.value?.model_dir || selectedEngine.value?.model_dir || "/data/models/acestep"));
const docsUrl = computed<string>(() => String(selectedEngine.value?.docs_url || "https://github.com/ServeurpersoCom/acestep.cpp"));
const engineLimitations = computed<string[]>(() => {
  const list = selectedEngine.value?.limitations;
  return Array.isArray(list) && list.length ? list.map(String) : DEMO_LIMITATIONS;
});
const modelFiles = computed<any[]>(() => {
  const files = musicSystem.value?.installed_files?.files;
  if (Array.isArray(files)) return files;
  return DEMO && !musicSystem.value ? DEMO_MODEL_FILES : [];
});
const resources = computed<any>(() => musicSystem.value?.resources || {});
const diskEntries = computed<Array<{ key: string; path?: string; total_gb?: number; used_gb?: number; free_gb?: number }>>(() =>
  Object.entries(resources.value?.disk || {}).map(([key, value]) => ({ key, ...(value as any) })),
);
const queueInfo = computed<any>(() => jobs.queues.find((queue) => queue.component === "music") || null);
const installedModelCount = computed<number>(() => models.value.filter((model) => model.installed).length);

const generationBlockedReason = computed<string>(() => {
  if (!activeSong.value) return "Choose a song first.";
  if (engineOffline.value) return "The ACE-Step engine is offline. Start the music-engine container.";
  if (!selectedModeSupported.value) return `${selectedModeMeta.value?.label || "This mode"} is not supported by the selected model.`;
  if (selectedModeMeta.value?.requires_source && !sourcePath.value) return `${selectedModeMeta.value?.label || "This mode"} requires source audio.`;
  if (genMode.value === "repaint" && (!endSeconds.value || Number(endSeconds.value) <= Number(startSeconds.value))) return "Set a valid repaint range (end must be after start).";
  if (batchProduct.value > 9) return "LM batch × synth batch must be at most 9.";
  return "";
});

const currentJob = computed<Job | null>(() => {
  const found = currentJobId.value ? jobs.byId(currentJobId.value) : null;
  if (found) return found;
  if (DEMO) return jobs.items.find((job) => job.component === "music") || demoJobs.find((job) => job.component === "music") || demoJobs[0] || null;
  return jobs.items.find((job) => job.component === "music" && ["queued", "running", "canceling"].includes(job.status)) || null;
});
const draftJob = computed<Job | null>(() => (draftJobId.value ? jobs.byId(draftJobId.value) || null : null));
const draftJobActive = computed<boolean>(() => Boolean(draftJob.value && ["queued", "running", "canceling"].includes(draftJob.value.status)));
const draftReadySections = computed<LyricsSection[]>(() => {
  const sections = jobSections(draftJob.value);
  if (sections.length) return sections;
  return localDraftSections.value || [];
});
const draftPlanLines = computed<number>(() => draftStructure.value.reduce((sum, plan) => sum + Number(plan.line_count || 0), 0));

/* ------------------------------------------------------------------ derived project/song */
const tabs = computed(() => [
  ...(serviceOnline("music") ? [
    { id: "projects", label: "Projects", count: projects.value.length },
    { id: "studio", label: "Studio" },
    { id: "library", label: "Library", count: songs.value.length },
  ] : []),
  ...(serviceOnline("dj") ? [
    { id: "dj-library", label: "DJ Library" },
    { id: "dj-create", label: "DJ Create" },
    { id: "dj-mix", label: "DJ Mix" },
  ] : []),
  ...(serviceOnline("srt") ? [{ id: "srt", label: "SRT" }] : []),
  ...(serviceOnline("music-engine") ? [{ id: "engine", label: "Engine" }] : []),
]);
watch(tabs, (items) => {
  if (!items.some((item) => item.id === tab.value)) tab.value = items[0]?.id || "projects";
}, { immediate: true });

const selectedProject = computed<MusicProject | null>(() => projects.value.find((project) => project.id === selectedProjectId.value) || null);
const activeProject = computed<MusicProject | null>(() => projects.value.find((project) => project.id === activeSong.value?.project_id) || null);
const activeProjectName = computed<string>(() => activeProject.value?.title || activeSong.value?.project_title || "Unfiled");
const activeProjectColor = computed<string>(() => colorHex(activeProject.value?.color || activeSong.value?.project_color || "#8b5cf6"));
const activeCover = computed<string | null>(() => (activeSong.value ? songCover(activeSong.value) : null));

const filteredSongs = computed<MusicSong[]>(() => {
  const needle = songQuery.value.trim().toLowerCase();
  return songs.value.filter((song) => {
    if (libraryProject.value && song.project_id !== libraryProject.value) return false;
    if (!needle) return true;
    return [song.title, song.artist, song.genre, song.subgenre, song.mood].some((value) => String(value || "").toLowerCase().includes(needle));
  });
});

const projectTakeTotal = computed<number>(() => projects.value.reduce((sum, project) => sum + Number(project.take_count || 0), 0));

const briefDirty = computed<boolean>(() => Boolean(activeSong.value) && JSON.stringify(brief.value) !== briefSnapshot.value);
const lyricsDirty = computed<boolean>(() => Boolean(activeSong.value) && lyricsSignature(lyricsSections.value) !== lyricsSnapshot.value);
const saveLabel = computed<string>(() => {
  if (savingSong.value || savingLyrics.value) return "Saving…";
  if (briefDirty.value || lyricsDirty.value) return "Unsaved changes";
  if (lastSavedAt.value) return `Saved ${relativeTime(lastSavedAt.value)}`;
  return "All changes saved";
});
const saveDot = computed<string>(() => (briefDirty.value || lyricsDirty.value ? "busy" : "online"));
const totalWords = computed<number>(() => lyricsSections.value.reduce((sum, section) => sum + wordCount(section.content), 0));
const totalLines = computed<number>(() => lyricsSections.value.reduce((sum, section) => sum + lineCount(section.content), 0));

const masterTake = computed<MusicTake | null>(() => {
  const selected = activeSong.value?.selected_take_id;
  return (
    takes.value.find((take) => take.id === selected) ||
    takes.value.find((take) => take.is_favorite) ||
    takes.value[0] ||
    null
  );
});

const takeGroups = computed<TakeGroup[]>(() => {
  const groups: TakeGroup[] = [];
  const byKey = new Map<string, TakeGroup>();
  const ordered = [...takes.value].sort((a, b) => Number(a.position || 0) - Number(b.position || 0));
  ordered.forEach((take) => {
    const key = String(take.job_id || take.metadata?.generation_id || take.metadata?.batch_id || "manual-takes");
    let group = byKey.get(key);
    if (!group) {
      group = {
        key,
        label: `Generation ${groups.length + 1}`,
        mode: String(take.metadata?.mode || "full"),
        model: String(take.metadata?.model || activeSong.value?.model_id || "ACE-Step 1.5 Turbo"),
        createdAt: take.created_at || "",
        takes: [],
      };
      byKey.set(key, group);
      groups.push(group);
    }
    group.takes.push(take);
  });
  return groups;
});

const sectionMap = computed<Array<{ id: string; label: string; type: string; width: number; color: string; tint: string }>>(() => {
  const sections = lyricsSections.value;
  if (!sections.length) return [];
  const weights = sections.map((section) => Math.max(1, lineCount(section.content) || 2));
  const total = weights.reduce((sum, weight) => sum + weight, 0) || 1;
  return sections.map((section, index) => ({
    id: section.id,
    label: section.label,
    type: section.type,
    width: Math.max(5, (weights[index] / total) * 100),
    color: sectionColor(section.type),
    tint: sectionTint(section.type),
  }));
});

const musicPlayer = ref<any>(null);
const musicCurrent = ref(0);

const lyricSpans = computed(() => {
  const sections = lyricsSections.value;
  if (!sections.length) return [];
  const duration = Number(masterTake.value?.duration || activeSong.value?.duration || 0) || 60;
  const weights = sections.map((section) => Math.max(1, lineCount(section.content) || 2));
  const total = weights.reduce((sum, weight) => sum + weight, 0) || 1;
  let cursor = 0;
  return sections.map((section, index) => {
    const start = (cursor / total) * duration;
    cursor += weights[index];
    const end = (cursor / total) * duration;
    return {
      id: section.id,
      label: section.label,
      type: section.type,
      start,
      end,
      weight: weights[index],
      color: sectionColor(section.type),
    };
  });
});

const activeLyricSectionId = computed(() => {
  const time = musicCurrent.value;
  return lyricSpans.value.find((span) => time >= span.start && time < span.end)?.id || "";
});

function onMusicTime(payload: { current: number; duration?: number }) {
  musicCurrent.value = Number(payload.current) || 0;
}

function seekLyricSection(section: LyricsSection) {
  const span = lyricSpans.value.find((item) => item.id === section.id);
  if (span) musicPlayer.value?.seekTo?.(span.start, true);
}

function allLyricsText(): string {
  return lyricsSections.value
    .map((section) => `[${section.label}]\n${String(section.content || "").trim()}`.trim())
    .filter(Boolean)
    .join("\n\n");
}

async function copyAllLyrics() {
  const text = allLyricsText();
  if (!text) {
    toasts.error("There are no lyrics to copy.");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    toasts.success("Full lyrics copied with section markers.");
  } catch {
    toasts.error("Could not copy the lyrics.");
  }
}

function downloadLyricsSrt() {
  if (!activeSong.value) return;
  const take = masterTake.value;
  const query = take ? `?take_id=${encodeURIComponent(take.id)}` : "";
  const url = `${API_BASE}/music/songs/${encodeURIComponent(activeSong.value.id)}/lyrics.srt${query}`;
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.target = "_blank";
  anchor.rel = "noopener";
  anchor.click();
}

const compareTakeA = computed<MusicTake | null>(() => takes.value.find((take) => take.id === compareA.value) || null);
const compareTakeB = computed<MusicTake | null>(() => takes.value.find((take) => take.id === compareB.value) || null);
const activeExportFormats = computed<Array<{ value: string; label: string }>>(() =>
  exportTarget.value?.kind === "project" ? [{ value: "zip", label: "Session ZIP" }] : exportFormatOptions.value,
);

const engineCommands = computed<string>(() =>
  [
    "# Music service health and engine state",
    "curl -s http://localhost:8099/api/music/system | jq",
    "",
    "# Follow the ACE-Step engine while it loads checkpoints",
    "docker compose logs -f music-engine",
    "",
    "# Inspect the installed GGUF files",
    `ls -lh ${engineModelDir.value}`,
    "",
    "# Restart the engine after changing the model volume",
    "docker compose restart music-engine",
  ].join("\n"),
);

/* ------------------------------------------------------------------ template helpers */
function projectCover(project: MusicProject): string | null {
  if (project.cover) return project.cover;
  if (!DEMO) return null;
  const index = projects.value.findIndex((item) => item.id === project.id);
  return DEMO_ART[Math.max(0, index) % DEMO_ART.length];
}

function songCover(song: MusicSong): string | null {
  const project = projects.value.find((item) => item.id === song.project_id);
  const cover = project ? projectCover(project) : null;
  if (cover) return cover;
  if (!DEMO) return null;
  const index = songs.value.findIndex((item) => item.id === song.id);
  return DEMO_ART[Math.max(0, index) % DEMO_ART.length];
}

function projectInitials(project: MusicProject): string {
  return project.title
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() || "")
    .join("");
}

function defaultProjectColor(): string {
  return projectColorOptions.value[0]?.hex || "#8b5cf6";
}

function languageLabelFor(code: string): string {
  return languageOptions.value.find((language) => language.code === code)?.label || LANG_LABELS[code] || code;
}

function energyLabel(value: number): string {
  const sorted = [...energyLabels.value].sort((a, b) => a.value - b.value);
  let label = sorted[0]?.label || "Mid";
  sorted.forEach((item) => {
    if (Number(value) >= item.value) label = item.label;
  });
  return label;
}

function modeLabel(id: string): string {
  return modeOptions.value.find((mode) => mode.id === id)?.label || pretty(id);
}

function takeNumber(take: MusicTake): string {
  return String(Number(take.position || 0) + 1).padStart(2, "0");
}

function modelCapabilityKeys(model: any): string[] {
  const value = model?.capabilities;
  if (Array.isArray(value)) return value.map(String);
  if (value && typeof value === "object") {
    return Object.entries(value)
      .filter(([key, enabled]) => enabled === true && Boolean(CAPABILITY_LABELS[key]))
      .map(([key]) => key);
  }
  return [];
}

function capabilityLabel(key: string): string {
  return CAPABILITY_LABELS[key] || pretty(key);
}

function formatIcon(format: string): any {
  return format === "zip" ? Package : AudioLines;
}

function formatHint(format: string, targetKind?: string): string {
  if (format === "wav") return "Uncompressed master";
  if (format === "mp3") return "Small, portable copy";
  if (format === "flac") return "Lossless archive";
  return targetKind === "project" ? "Every song, lyric sheet and take" : "Song, lyrics and every take";
}

function diskPercent(disk: { total_gb?: number; used_gb?: number }): number {
  if (!disk?.total_gb) return 0;
  return Math.min(100, Math.round((Number(disk.used_gb || 0) / Number(disk.total_gb)) * 100));
}

function gbLabel(value?: number): string {
  return `${Number(value || 0).toFixed(1)} GB`;
}

function mbLabel(value?: number): string {
  return `${(Number(value || 0) / 1024).toFixed(1)} GB`;
}

if (DEMO) initializeDemo();
</script>

<template>
  <div class="page music-page">
    <PageHeader
      eyebrow="Audio studio"
      title="Audio"
      subtitle="ACE-Step 1.5 songwriting, DJ analysis and mixing, and lyric-aligned SRT tools in one audio workspace. Every render runs as a per-component job."
    >
      <template #actions>
        <button class="btn btn-sm" @click="openProjectModal()"><FolderPlus :size="13" /> New project</button>
        <button class="btn btn-sm" @click="openNewSong"><Music2 :size="13" /> New song</button>
        <button class="btn btn-sm btn-ghost" :disabled="refreshing" @click="refreshAll">
          <RefreshCw :size="13" :class="{ spin: refreshing }" /> Refresh
        </button>
      </template>
    </PageHeader>

    <ServiceNotice
      :services="[
        { name: 'music', label: 'Music / ACE-Step' },
        { name: 'music-engine', label: 'ACE-Step Engine' },
        { name: 'dj', label: 'DJ Studio' },
        { name: 'srt', label: 'AI Subtitles' },
        { name: 'llm', label: 'Local LLM' },
      ]"
      title="Some Audio features are unavailable"
    />

    <div class="music-toolbar">
      <TabsBar v-model="tab" :tabs="tabs" />
      <div class="music-toolbar-meta">
        <span v-if="DEMO" class="chip"><Sparkles :size="11" /> Demo workspace</span>
        <span class="chip" :class="engineOnline ? 'success' : engineKnown ? 'danger' : ''">
          <span class="dot" :class="!engineKnown ? 'busy' : engineOnline ? 'online' : 'offline'" />
          ACE-Step 1.5 · {{ engineLabel }}
        </span>
        <span class="chip"><Layers :size="11" /> {{ models.length }} model{{ models.length === 1 ? "" : "s" }} · {{ songs.length }} song{{ songs.length === 1 ? "" : "s" }}</span>
      </div>
    </div>

    <div v-if="serviceError" class="alert error music-banner">
      <AlertTriangle :size="17" style="flex: none" />
      <div class="grow">
        <strong>Music service unavailable.</strong>
        <span class="small"> {{ serviceError }}</span>
      </div>
      <button class="btn btn-sm" @click="refreshAll"><RefreshCw :size="12" /> Retry</button>
    </div>

    <div v-if="loading" class="stack">
      <div class="grid grid-4">
        <div v-for="i in 4" :key="i" class="skeleton" style="height: 94px" />
      </div>
      <div class="grid grid-3">
        <div v-for="i in 3" :key="i" class="skeleton" style="height: 290px" />
      </div>
    </div>

    <!-- ---------------------------------------------------------------- projects -->
    <template v-else-if="serviceOnline('music') && tab === 'projects'">
      <div class="stat-grid music-stats">
        <div class="stat">
          <div class="stat-label">Projects</div>
          <div class="stat-value">{{ projects.length }}</div>
          <div class="stat-sub">Every project owns a folder in shared storage</div>
        </div>
        <div class="stat">
          <div class="stat-label">Songs</div>
          <div class="stat-value">{{ songs.length }}</div>
          <div class="stat-sub">Briefs, lyrics and takes in one session</div>
        </div>
        <div class="stat">
          <div class="stat-label">Takes</div>
          <div class="stat-value">{{ projectTakeTotal }}</div>
          <div class="stat-sub">Master, variations and edits</div>
        </div>
        <div class="stat">
          <div class="stat-label">Engine</div>
          <div class="stat-value" style="font-size: 20px">{{ engineOnline ? "Ready" : "Offline" }}</div>
          <div class="stat-sub">{{ installedModelCount }} installed checkpoints · GGUF</div>
        </div>
      </div>

      <div class="row-between" style="margin: 22px 0 12px">
        <div>
          <h2 style="font-size: 19px">Projects</h2>
          <p class="small muted" style="margin-top: 3px">
            {{ DEMO ? "Cover art is illustrative in demo mode." : "Cover art follows the project accent." }}
            Select a project to open its song library.
          </p>
        </div>
        <button class="btn btn-sm" @click="openProjectModal()"><Plus :size="13" /> Create project</button>
      </div>

      <div class="project-grid">
        <article
          v-for="project in projects"
          :key="project.id"
          class="project-card"
          :class="{ selected: selectedProjectId === project.id }"
          :style="{ borderColor: colorHex(project.color) + '38' }"
          @click="openProject(project)"
        >
          <div class="project-cover">
            <img v-if="projectCover(project)" :src="projectCover(project) as string" :alt="project.title" />
            <div
              v-else
              class="project-cover-fallback"
              :style="{ background: `linear-gradient(135deg, ${colorHex(project.color)}55, #0b0d13 68%), radial-gradient(circle at 75% 20%, ${colorHex(project.color)}44, transparent 50%)` }"
            >
              {{ projectInitials(project) }}
            </div>
            <div class="project-cover-shade" />
            <div class="project-cover-top">
              <span class="chip"><Music2 :size="10" /> {{ project.song_count }} song{{ project.song_count === 1 ? "" : "s" }}</span>
              <div class="project-actions" @click.stop>
                <button title="Edit project" aria-label="Edit project" @click="openProjectModal(project)"><Pencil :size="13" /></button>
                <button title="Export session ZIP" aria-label="Export project" @click="openProjectExport(project)"><Download :size="13" /></button>
                <button title="Delete project" aria-label="Delete project" @click="askDeleteProject(project)"><Trash2 :size="13" /></button>
              </div>
            </div>
            <div class="project-cover-bottom">
              <span class="chip"><Disc3 :size="10" /> {{ project.take_count }} take{{ project.take_count === 1 ? "" : "s" }}</span>
              <span class="chip"><Clock3 :size="10" /> {{ relativeTime(project.last_activity || project.updated_at) }}</span>
            </div>
          </div>
          <div class="project-info">
            <div class="row-between">
              <h3>{{ project.title }}</h3>
              <ChevronRight :size="16" class="muted" />
            </div>
            <div class="small muted">{{ project.artist || "No artist yet" }}</div>
            <p class="small muted project-desc">{{ project.description || "No description yet." }}</p>
            <div class="project-progress">
              <span :style="{ background: colorHex(project.color) }" />
            </div>
          </div>
        </article>

        <button class="new-project-card" @click="openProjectModal()">
          <span class="new-project-icon"><FolderPlus :size="26" /></span>
          <strong>New project</strong>
          <span class="small muted">Group songs, lyrics and takes into an album-sized session.</span>
        </button>
      </div>
    </template>

    <!-- ---------------------------------------------------------------- studio -->
    <template v-else-if="serviceOnline('music') && tab === 'studio'">
      <div v-if="loadingSong && !activeSong" class="panel">
        <div class="panel-body stack">
          <div class="skeleton" style="height: 110px" />
          <div class="skeleton" style="height: 220px" />
        </div>
      </div>

      <EmptyState
        v-else-if="!activeSong"
        :icon="Music2"
        title="Open a song in the studio"
        message="Choose a song from the library or create a new one. The studio holds the brief, structured lyrics, master take and every generation control in one place."
      >
        <div class="row" style="justify-content: center">
          <button class="btn btn-sm" @click="tab = 'library'"><ListMusic :size="13" /> Open library</button>
          <button class="btn btn-sm btn-primary" @click="openNewSong"><Plus :size="13" /> New song</button>
        </div>
      </EmptyState>

      <div v-else class="stack">
        <section class="panel studio-hero" :style="{ borderColor: activeProjectColor + '40' }">
          <div class="studio-hero-glow" :style="{ backgroundImage: activeCover ? `url(${activeCover})` : 'none' }" />
          <div class="studio-hero-inner">
            <div class="studio-cover">
              <img v-if="activeCover" :src="activeCover" :alt="activeSong.title" />
              <span v-else>{{ projectInitials(activeProject || ({ title: activeSong.title } as MusicProject)) }}</span>
            </div>
            <div class="grow" style="min-width: 0">
              <div class="eyebrow" style="margin-bottom: 5px"><Disc3 :size="12" /> {{ activeProjectName }} · ACE-Step session</div>
              <h2 class="studio-title">{{ activeSong.title }}</h2>
              <div class="row studio-chips">
                <span v-if="activeSong.artist" class="chip">{{ activeSong.artist }}</span>
                <span class="chip"><Music2 :size="10" /> {{ activeSong.genre || "No genre" }}<template v-if="activeSong.subgenre"> · {{ activeSong.subgenre }}</template></span>
                <span class="chip">{{ activeSong.mood || "Unspecified mood" }}</span>
                <span class="chip">{{ activeSong.bpm }} BPM</span>
                <span class="chip">{{ formatDuration(activeSong.duration) }}</span>
                <span class="chip">{{ languageLabelFor(activeSong.language) }}</span>
                <span class="chip">Energy {{ activeSong.energy }}/100</span>
                <span class="chip" :class="{ success: activeSong.vocal_type === 'instrumental' }">{{ pretty(activeSong.vocal_type) }}</span>
              </div>
              <div class="row" style="margin-top: 11px; gap: 10px">
                <span class="save-state">
                  <span class="dot" :class="saveDot" />
                  {{ saveLabel }}
                </span>
                <span class="small muted">{{ takes.length }} take{{ takes.length === 1 ? "" : "s" }} · {{ lyricsSections.length }} lyric section{{ lyricsSections.length === 1 ? "" : "s" }} · {{ totalWords }} words</span>
              </div>
            </div>
            <div class="studio-actions">
              <button class="btn btn-sm" @click="duplicateSong"><Copy :size="13" /> Duplicate</button>
              <button class="btn btn-sm" @click="openSongExport"><Download :size="13" /> Export</button>
              <button class="btn btn-sm btn-danger" @click="askDeleteSong"><Trash2 :size="13" /> Delete</button>
            </div>
          </div>
        </section>

        <div class="studio-grid">
          <div class="stack">
            <!-- master take -->
            <section class="panel">
              <div class="panel-head">
                <div>
                  <div class="row" style="gap: 8px">
                    <h3>Master take</h3>
                    <span v-if="masterTake" class="badge success"><Star :size="9" /> Master</span>
                    <span v-if="masterTake?.is_favorite" class="badge warn"><Heart :size="9" /> Favorite</span>
                  </div>
                  <p v-if="masterTake">{{ takeName(masterTake) }} · {{ relativeTime(masterTake.created_at) }}</p>
                  <p v-else>No take yet — generate the first render from the panel on the right.</p>
                </div>
                <div v-if="masterTake" class="row">
                  <button class="btn btn-sm" @click="toggleTakeFavorite(masterTake)">
                    <Heart :size="12" :fill="masterTake.is_favorite ? 'currentColor' : 'none'" /> {{ masterTake.is_favorite ? "Favorited" : "Favorite" }}
                  </button>
                  <button class="btn btn-sm" @click="openCompare(masterTake)"><GitCompare :size="12" /> Compare</button>
                </div>
              </div>
              <div v-if="masterTake" class="panel-body stack">
                <SectionPlayer
                  ref="musicPlayer"
                  :src="masterTake.path"
                  :title="takeTitle(masterTake)"
                  :subtitle="`${modelName(masterTake.metadata?.model || activeSong.model_id)} · ${formatDuration(masterTake.duration)}`"
                  :download-path="DEMO ? null : masterTake.path"
                  :bars="144"
                  :sections="lyricSpans"
                  :duration="masterTake.duration"
                  @timeupdate="onMusicTime"
                />
                <div class="master-meta-grid">
                  <div class="meta-tile">
                    <div class="label">Seed</div>
                    <div class="value mono">{{ masterTake.seed ?? "—" }}</div>
                  </div>
                  <div class="meta-tile">
                    <div class="label">BPM</div>
                    <div class="value">{{ masterTake.bpm || activeSong.bpm }}</div>
                  </div>
                  <div class="meta-tile">
                    <div class="label">Model</div>
                    <div class="value truncate" :title="modelName(masterTake.metadata?.model || activeSong.model_id)">{{ modelName(masterTake.metadata?.model || activeSong.model_id) }}</div>
                  </div>
                  <div class="meta-tile">
                    <div class="label">Created</div>
                    <div class="value">{{ relativeTime(masterTake.created_at) }}</div>
                  </div>
                </div>
                <div class="row">
                  <span class="chip mono" style="max-width: 100%"><AudioLines :size="10" /> <span class="truncate">{{ masterTake.path }}</span></span>
                  <span class="chip">{{ modeLabel(String(masterTake.metadata?.mode || "full")) }}</span>
                  <span class="chip">{{ formatDuration(masterTake.duration) }}</span>
                  <span v-if="masterTake.notes" class="chip" :title="masterTake.notes"><Check :size="10" /> Notes</span>
                </div>
              </div>
              <div v-else class="panel-body">
                <div class="empty" style="padding: 24px">
                  <Disc3 :size="26" style="opacity: 0.45; margin-bottom: 6px" />
                  <h3>No takes yet</h3>
                  <p>Use the generation panel on the right. The first completed take becomes the master automatically.</p>
                </div>
              </div>
            </section>

            <!-- song brief -->
            <section class="panel">
              <div class="panel-head">
                <div>
                  <h3>Song brief</h3>
                  <p>The planner, vocal direction and arrangement controls sent with every generation.</p>
                </div>
                <span class="chip" :class="{ warn: briefDirty }">{{ briefDirty ? "Unsaved" : "Synced" }}</span>
              </div>
              <div class="panel-body">
                <div class="form-grid">
                  <div class="field">
                    <label>Title</label>
                    <input v-model="brief.title" class="input" placeholder="Song title" />
                  </div>
                  <div class="field">
                    <label>Artist</label>
                    <input v-model="brief.artist" class="input" placeholder="Artist or project name" />
                  </div>
                  <div class="field">
                    <label>Language <span class="hint">{{ languageOptions.length }} options</span></label>
                    <select v-model="brief.language" class="select">
                      <option v-for="language in languageOptions" :key="language.code" :value="language.code">{{ language.label }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Genre</label>
                    <input v-model="brief.genre" class="input" list="music-genre-options" placeholder="Art pop" />
                    <datalist id="music-genre-options">
                      <option v-for="genre in genreSuggestions" :key="genre" :value="genre" />
                    </datalist>
                  </div>
                  <div class="field">
                    <label>Subgenre</label>
                    <input v-model="brief.subgenre" class="input" placeholder="Chamber pop, fado canção…" />
                  </div>
                  <div class="field">
                    <label>Style / production <span class="hint">comma-separated</span></label>
                    <input v-model="brief.style" class="input" list="music-style-options" placeholder="intimate, analog warmth, nylon guitar" />
                    <datalist id="music-style-options">
                      <option v-for="style in styleSuggestions" :key="style" :value="style" />
                    </datalist>
                  </div>
                  <div class="field">
                    <label>Mood</label>
                    <select v-model="brief.mood" class="select">
                      <option v-for="mood in moodOptions" :key="mood" :value="mood">{{ mood }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Energy <span class="hint">{{ energyLabel(brief.energy) }} · {{ brief.energy }}/100</span></label>
                    <input v-model.number="brief.energy" type="range" min="0" max="100" step="1" />
                  </div>
                  <div class="field">
                    <label>BPM <span class="hint">30–300</span></label>
                    <input v-model.number="brief.bpm" class="input" type="number" min="30" max="300" />
                  </div>
                  <div class="field">
                    <label>Target duration <span class="hint">10–600 seconds</span></label>
                    <input v-model.number="brief.duration" class="input" type="number" min="10" max="600" step="1" />
                  </div>
                  <div class="field">
                    <label>Vocal type</label>
                    <select v-model="brief.vocal_type" class="select">
                      <option v-for="voice in vocalTypeOptions" :key="voice.value" :value="voice.value">{{ voice.label }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Vocal range</label>
                    <select v-model="brief.vocal_range" class="select">
                      <option v-for="range in vocalRangeOptions" :key="range" :value="range">{{ range }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Singing style</label>
                    <select v-model="brief.singing_style" class="select">
                      <option v-for="style in singingStyleOptions" :key="style" :value="style">{{ style }}</option>
                    </select>
                  </div>
                  <div class="field">
                    <label>Vocal emotion</label>
                    <select v-model="brief.vocal_emotion" class="select">
                      <option v-for="emotion in vocalEmotionOptions" :key="emotion" :value="emotion">{{ emotion }}</option>
                    </select>
                  </div>
                  <div class="field span-2">
                    <label>Vocal intensity <span class="hint">{{ brief.vocal_intensity }}/100 · how far the lead sits in front of the arrangement</span></label>
                    <input v-model.number="brief.vocal_intensity" type="range" min="0" max="100" step="1" />
                  </div>
                  <div class="field span-2">
                    <label>Vocal prompt <span class="hint">tone, placement, harmony</span></label>
                    <textarea v-model="brief.vocal_prompt" class="textarea" style="min-height: 64px" placeholder="Close, intimate lead with airy doubles in the chorus…" />
                  </div>
                  <div class="field span-2">
                    <label>Pronunciation &amp; dialect <span class="hint">language-specific notes</span></label>
                    <textarea v-model="brief.pronunciation" class="textarea" style="min-height: 58px" placeholder="European Portuguese. Final vowels are quiet, never Brazilianised." />
                  </div>
                  <div class="field span-2">
                    <label>Arrangement instructions <span class="hint">structure, dynamics, what to avoid</span></label>
                    <textarea v-model="brief.instructions" class="textarea" placeholder="Keep the arrangement nocturnal and uncluttered. Let the vocal carry the story." />
                  </div>
                </div>
              </div>
              <div class="panel-footer">
                <span class="small muted grow">{{ briefDirty ? "Local edits are not applied until you save." : "The brief is saved on the server." }}</span>
                <button class="btn btn-primary" :disabled="savingSong || !briefDirty" @click="saveSong()">
                  <Loader2 v-if="savingSong" :size="13" class="spin" /><Save v-else :size="13" /> Save song
                </button>
              </div>
            </section>

            <!-- lyrics -->
            <section class="panel">
              <div class="panel-head">
                <div>
                  <h3>Lyrics</h3>
                  <p>{{ lyricsSections.length }} sections · {{ totalLines }} lines · {{ totalWords }} words, structured for ACE-Step.</p>
                </div>
                <div class="row" style="gap: 5px; flex-wrap: wrap">
                  <button class="btn btn-sm" @click="openDraftModal"><Wand2 :size="12" /> Draft with LLM</button>
                  <button class="btn btn-sm" :disabled="!lyricsSections.length" @click="copyAllLyrics"><Copy :size="12" /> Copy all</button>
                  <button class="btn btn-sm" :disabled="!lyricsSections.length || !activeSong" @click="downloadLyricsSrt"><Download :size="12" /> SRT</button>
                  <button class="btn btn-sm btn-primary" :disabled="savingLyrics || !lyricsDirty" @click="saveLyrics()">
                    <Loader2 v-if="savingLyrics" :size="12" class="spin" /><Save v-else :size="12" /> Save lyrics
                  </button>
                </div>
              </div>
              <div class="panel-body stack">
                <div v-if="draftJob || localDraftSections" class="draft-card">
                  <div class="row-between" style="gap: 10px; align-items: flex-start">
                    <div class="row" style="gap: 8px">
                      <span class="file-icon" style="width: 30px; height: 30px"><Sparkles :size="14" /></span>
                      <div>
                        <div class="row" style="gap: 6px">
                          <strong class="small">Lyric draft</strong>
                          <span v-if="draftJob" class="badge" :class="{ running: draftJobActive, success: draftJob.status === 'completed', failed: draftJob.status === 'failed' }">{{ draftJob.status }}</span>
                          <span v-else class="badge success">ready</span>
                        </div>
                        <p class="small muted" style="margin-top: 2px">{{ draftJob?.message || (localDraftSections ? "Demo draft generated from your theme and direction." : "Waiting for the lyricist.") }}</p>
                      </div>
                    </div>
                    <div class="row" style="gap: 4px">
                      <button v-if="draftJob && draftJobActive" class="btn btn-sm btn-danger" @click="cancelJob(draftJob.id)"><X :size="12" /> Cancel</button>
                      <button v-if="draftJob && !draftJobActive" class="icon-btn" title="Refresh draft" @click="refreshDraftJob"><RefreshCw :size="13" /></button>
                      <button class="icon-btn" title="Dismiss draft" @click="dismissDraft"><X :size="14" /></button>
                    </div>
                  </div>
                  <ProgressBar v-if="draftJob" :value="draftJob.progress" :warn="draftJob.status === 'failed'" thin />
                  <div v-if="draftJob?.error" class="alert error">{{ draftJob.error }}</div>
                  <div class="row-between">
                    <span class="small muted">
                      <template v-if="draftReadySections.length">{{ draftReadySections.length }} sections ready to apply</template>
                      <template v-else-if="draftJobActive">{{ draftJob?.stage || "Planning" }} — {{ Math.round(draftJob?.progress || 0) }}%</template>
                      <template v-else>No sections returned yet.</template>
                    </span>
                    <button v-if="draftReadySections.length" class="btn btn-sm btn-primary" @click="applyDraft"><Check :size="12" /> Apply to lyrics</button>
                  </div>
                </div>

                <div v-if="!lyricsSections.length" class="empty" style="padding: 24px">
                  <Wand2 :size="26" style="opacity: 0.45; margin-bottom: 6px" />
                  <h3>No lyric sections</h3>
                  <p>Add a section below or ask the lyricist for a structured draft.</p>
                </div>

                <div
                  v-for="(section, index) in lyricsSections"
                  :key="section.id"
                  class="lyric-section"
                  :class="{ active: activeLyricSectionId === section.id }"
                  :style="{ borderLeftColor: sectionColor(section.type) }"
                >
                  <div class="lyric-head">
                    <div class="row grow" style="gap: 6px; min-width: 0">
                      <span class="lyric-type-dot" :style="{ background: sectionColor(section.type) }" />
                      <select v-model="section.type" class="select input-sm lyric-type-select" @change="onSectionTypeChange(section)">
                        <option v-for="type in SECTION_TYPES" :key="type" :value="type">{{ SECTION_LABELS[type] }}</option>
                      </select>
                      <input v-model="section.label" class="input input-sm lyric-label-input" placeholder="Section label" />
                      <span class="chip nowrap">{{ lineCount(section.content) }} lines</span>
                    </div>
                    <div class="row" style="gap: 2px">
                      <button class="icon-btn" title="Seek to this section" @click="seekLyricSection(section)"><Play :size="13" /></button>
                      <button class="icon-btn" :disabled="index === 0" title="Move up" @click="moveLyricSection(index, -1)"><ArrowUp :size="13" /></button>
                      <button class="icon-btn" :disabled="index === lyricsSections.length - 1" title="Move down" @click="moveLyricSection(index, 1)"><ArrowDown :size="13" /></button>
                      <button class="icon-btn" title="Remove section" @click="removeLyricSection(index)"><Trash2 :size="13" /></button>
                    </div>
                  </div>
                  <textarea v-model="section.content" class="textarea lyric-text" :placeholder="section.type === 'instrumental' ? 'Instrumental — describe what carries the section in the instructions.' : 'One lyric line per row…'" />
                  <input v-model="section.instructions" class="input input-sm" placeholder="Performance direction for this section…" />
                </div>

                <div class="row">
                  <button class="btn btn-sm" @click="addLyricSection"><Plus :size="12" /> Add section</button>
                  <span class="small muted">Reorder with the arrows. Instrumental sections are kept in the structure without lyric text.</span>
                </div>
              </div>
            </section>

            <!-- takes -->
            <section class="panel">
              <div class="panel-head">
                <div>
                  <h3>Takes</h3>
                  <p>{{ takes.length }} audio file{{ takes.length === 1 ? "" : "s" }} across {{ takeGroups.length }} generation{{ takeGroups.length === 1 ? "" : "s" }}. Grouped by the job that produced them.</p>
                </div>
                <div class="row">
                  <span class="chip"><Layers :size="10" /> {{ takeGroups.length }} generation{{ takeGroups.length === 1 ? "" : "s" }}</span>
                  <button class="btn btn-sm" :disabled="!takes.length" @click="openCompare()"><GitCompare :size="12" /> Compare</button>
                </div>
              </div>
              <div class="panel-body stack">
                <div v-for="(group, groupIndex) in takeGroups" :key="group.key" class="take-group">
                  <div class="take-group-head">
                    <div class="row" style="gap: 7px">
                      <span class="gen-index">G{{ groupIndex + 1 }}</span>
                      <strong class="small">{{ group.label }}</strong>
                      <span class="chip">{{ group.takes.length }} take{{ group.takes.length === 1 ? "" : "s" }}</span>
                    </div>
                    <div class="row small muted" style="gap: 6px">
                      <span>{{ modeLabel(group.mode) }}</span>
                      <span>·</span>
                      <span>{{ modelName(group.model) }}</span>
                      <span>·</span>
                      <span>{{ relativeTime(group.createdAt) }}</span>
                    </div>
                  </div>

                  <div
                    v-for="take in group.takes"
                    :key="take.id"
                    class="take-item"
                    :class="{ master: masterTake?.id === take.id }"
                  >
                    <div class="take-top">
                      <div class="take-number">{{ takeNumber(take) }}</div>
                      <div class="grow" style="min-width: 0">
                        <div class="row" style="gap: 6px">
                          <strong class="small">{{ takeTitle(take) }}</strong>
                          <span v-if="masterTake?.id === take.id" class="badge success"><Star :size="8" /> Master</span>
                          <span v-if="take.is_favorite" class="badge warn"><Heart :size="8" /> Favorite</span>
                          <span class="chip">{{ modeLabel(String(take.metadata?.mode || "full")) }}</span>
                        </div>
                        <div class="small muted truncate" style="margin-top: 3px">
                          <span class="mono">{{ take.path }}</span>
                        </div>
                        <div class="row small muted" style="gap: 7px; margin-top: 4px">
                          <span>Seed {{ take.seed ?? "—" }}</span>
                          <span>·</span>
                          <span>{{ formatDuration(take.duration) }}</span>
                          <span>·</span>
                          <span>{{ relativeTime(take.created_at) }}</span>
                          <span v-if="take.metadata?.range">· {{ take.metadata.range }}</span>
                        </div>
                      </div>
                      <div class="row take-actions">
                        <button class="icon-btn" :title="take.is_favorite ? 'Remove favorite' : 'Favorite'" @click="toggleTakeFavorite(take)">
                          <Heart :size="14" :fill="take.is_favorite ? 'currentColor' : 'none'" />
                        </button>
                        <button class="icon-btn" title="Compare takes" @click="openCompare(take)"><GitCompare :size="14" /></button>
                        <button class="btn btn-sm" :disabled="masterTake?.id === take.id" @click="makeMaster(take)">
                          <Star :size="11" /> {{ masterTake?.id === take.id ? "Master" : "Set master" }}
                        </button>
                        <button class="icon-btn" title="Delete take" @click="askDeleteTake(take)"><Trash2 :size="14" /></button>
                      </div>
                    </div>

                    <AudioPlayer
                      :src="take.path"
                      :title="takeTitle(take)"
                      :subtitle="`${modelName(take.metadata?.model || activeSong.model_id)} · ${formatDuration(take.duration)}`"
                      :download-path="DEMO ? null : take.path"
                      compact
                      :bars="96"
                    />

                    <div class="row take-export-row">
                      <span class="small muted">Export</span>
                      <button v-for="format in TAKE_EXPORT_FORMATS" :key="format" class="btn btn-sm" @click="exportTake(take, format)">
                        <Download :size="11" /> {{ format.toUpperCase() }}
                      </button>
                      <span class="grow" />
                      <a v-if="!DEMO" class="icon-btn" :href="fileUrl(take.path)" target="_blank" rel="noopener" title="Open original audio"><ExternalLink :size="13" /></a>
                      <a v-if="!DEMO" class="icon-btn" :href="downloadUrl(take.path)" title="Download original audio"><Download :size="13" /></a>
                      <button v-else class="icon-btn" title="Open original audio (demo)" @click="demoLinkToast"><ExternalLink :size="13" /></button>
                    </div>
                  </div>
                </div>

                <EmptyState v-if="!takes.length" :icon="Disc3" title="No takes yet" message="Generate a full song, a repaint or a cover from the panel on the right. Takes are grouped by generation and can be compared, favorited and exported." />
              </div>
            </section>
          </div>

          <!-- generation panel -->
          <aside class="panel generation-panel">
            <div class="panel-head">
              <div>
                <h3>Generate</h3>
                <p>{{ selectedModel?.name || "ACE-Step 1.5" }} · {{ selectedEngine?.name || "ace_step" }}</p>
              </div>
              <span class="chip" :class="engineOnline ? 'success' : 'danger'"><span class="dot" :class="engineOnline ? 'online' : 'offline'" /> {{ engineOnline ? "ready" : "offline" }}</span>
            </div>
            <div class="panel-body gen-body">
              <div v-if="engineOffline" class="alert warn">
                <div class="row" style="gap: 7px; align-items: flex-start">
                  <AlertTriangle :size="14" style="flex: none; margin-top: 1px" />
                  <span>The ACE-Step engine is offline. Start the music-engine container and wait for the GGUF checkpoints; the studio stays usable while it boots.</span>
                </div>
              </div>

              <div v-if="currentJob" class="gen-section" style="padding-top: 0; border-top: none">
                <div class="gen-label">Current job</div>
                <JobCard :job="currentJob" compact @cancel="cancelJob" @retry="retryJob" @remove="removeJob" />
              </div>

              <div class="field">
                <label>Style profile <span class="hint">optional reference</span></label>
                <div class="input-group">
                  <select v-model="selectedStyleId" class="select">
                    <option value="">No style reference</option>
                    <option v-for="style in styles" :key="style.id" :value="style.id">{{ style.name }}</option>
                  </select>
                  <button class="btn btn-sm" title="Add a style reference" @click="openStyleModal">+ Style</button>
                </div>
                <div v-if="selectedStyle" class="style-reference-note">
                  <span class="chip active">reference audio</span>
                  <span class="small muted truncate">{{ selectedStyle.reference_path }}</span>
                  <span v-if="selectedStyle.tags?.length" class="small muted">· {{ selectedStyle.tags.join(", ") }}</span>
                </div>
                <div v-else class="hint">Upload a song that represents the sound you want, name the style, then select it here. ACE-Step uses it as reference audio and prompt guidance.</div>
              </div>

              <div class="field">
                <label>Engine <span class="hint">provider</span></label>
                <select v-model="genProvider" class="select">
                  <option v-for="engine in engines" :key="engine.id" :value="engine.id">{{ engine.name }}</option>
                  <option v-if="!engines.length" value="ace_step">ACE-Step 1.5</option>
                </select>
              </div>

              <div class="field">
                <label>Model <span class="hint">{{ installedModelCount }} installed</span></label>
                <select v-model="genModelId" class="select">
                  <option v-for="model in models" :key="model.id" :value="model.id" :disabled="model.installed === false">
                    {{ model.name }}{{ model.installed === false ? " · not installed" : "" }}
                  </option>
                  <option v-if="!models.length" value="acestep-v15-turbo">ACE-Step 1.5 Turbo</option>
                </select>
                <div class="model-note small muted">
                  {{ selectedModel?.description || "The best starting point for consumer hardware. DiT generation with 5Hz LM planning." }}
                </div>
                <div v-if="selectedModel" class="row" style="gap: 5px">
                  <span class="chip">{{ selectedModel.parameters || "2B" }}</span>
                  <span class="chip">{{ selectedModel.quality || "High" }} quality</span>
                  <span class="chip">{{ selectedModel.speed || "Fast" }}</span>
                  <span v-if="selectedModel.vram_gb" class="chip">~{{ selectedModel.vram_gb }} GB</span>
                </div>
              </div>

              <div class="gen-section">
                <div class="gen-label">Mode <span class="hint">task</span></div>
                <div class="mode-grid">
                  <button
                    v-for="mode in modeOptions"
                    :key="mode.id"
                    class="mode-option"
                    :class="{ active: genMode === mode.id, disabled: !modeSupported(mode.id) }"
                    :disabled="!modeSupported(mode.id)"
                    :title="`${mode.description} ${modeSupported(mode.id) ? '' : 'Not supported by this model.'}`"
                    @click="selectMode(mode.id)"
                  >
                    <component :is="MODE_ICONS[mode.id] || Music2" :size="14" />
                    <strong>{{ mode.label }}</strong>
                    <span>{{ mode.description }}<template v-if="!modeSupported(mode.id)"> Unavailable on this model.</template></span>
                  </button>
                </div>
                <div class="small muted">{{ selectedModeMeta?.description }} <template v-if="selectedModeMeta?.requires_source"> Source audio is required.</template></div>
              </div>

              <div class="gen-section">
                <div class="row-between">
                  <span class="gen-label">Variations</span>
                  <span class="chip">{{ genVariations }} take{{ genVariations === 1 ? "" : "s" }} per pass</span>
                </div>
                <div class="variation-row">
                  <button
                    v-for="count in 4"
                    :key="count"
                    class="variation-btn"
                    :class="{ active: genVariations === count }"
                    :disabled="count > maxVariations"
                    @click="genVariations = count"
                  >
                    {{ count }}
                  </button>
                </div>
              </div>

              <div class="gen-section">
                <div class="gen-label">Seed</div>
                <div class="input-group">
                  <button class="btn btn-sm" :class="{ 'btn-primary': seedEnabled }" @click="seedEnabled = !seedEnabled">
                    <Lock v-if="seedEnabled" :size="12" /><Unlock v-else :size="12" /> {{ seedEnabled ? "Locked" : "Random" }}
                  </button>
                  <input v-model.number="seed" class="input mono" type="number" min="0" :disabled="!seedEnabled" />
                  <button class="icon-btn" title="Roll a new seed" @click="rollSeed"><Dice5 :size="16" /></button>
                </div>
                <div class="hint">A locked seed reproduces the same starting noise for A/B comparisons.</div>
              </div>

              <div class="control-grid">
                <div class="field">
                  <label>Inference steps <button class="chip clickable" :class="{ active: stepsAuto }" @click="stepsAuto = !stepsAuto">{{ stepsAuto ? "Auto" : "Manual" }}</button></label>
                  <input v-model.number="genSteps" class="input" type="number" min="1" max="200" :disabled="stepsAuto" />
                  <div class="hint">{{ stepsAuto ? "Model default is applied." : "1–200 diffusion steps." }}</div>
                </div>
                <div class="field">
                  <label>Guidance <button class="chip clickable" :class="{ active: guidanceAuto }" @click="guidanceAuto = !guidanceAuto">{{ guidanceAuto ? "Auto" : "Manual" }}</button></label>
                  <input v-model.number="genGuidance" class="input" type="number" min="0" max="30" step="0.1" :disabled="guidanceAuto" />
                  <div class="hint">{{ guidanceAuto ? "Model default is applied." : "0–30 classifier-free guidance." }}</div>
                </div>
              </div>

              <div class="switch-list">
                <div class="switch-row">
                  <div><div class="switch-label">Thinking</div><div class="switch-hint">The GGUF engine always uses its LM for full songs; this is informational.</div></div>
                  <button class="switch" :class="{ on: thinking }" role="switch" :aria-checked="thinking" @click="thinking = !thinking" />
                </div>
                <div class="switch-row">
                  <div><div class="switch-label">Use format</div><div class="switch-hint">Ask the engine to respect the structured section formatting.</div></div>
                  <button class="switch" :class="{ on: useFormat }" role="switch" :aria-checked="useFormat" @click="useFormat = !useFormat" />
                </div>
                <div class="switch-row">
                  <div><div class="switch-label">Enhance prompt</div><div class="switch-hint">Express extra production detail through the caption.</div></div>
                  <button class="switch" :class="{ on: enhancePrompt }" role="switch" :aria-checked="enhancePrompt" @click="enhancePrompt = !enhancePrompt" />
                </div>
              </div>

              <div class="gen-section">
                <div class="gen-label">Arrangement overrides</div>
                <div class="control-grid">
                  <div class="field">
                    <label>BPM <button class="chip clickable" :class="{ active: bpmOverride }" @click="bpmOverride = !bpmOverride">Override</button></label>
                    <input v-model.number="genBpm" class="input" type="number" min="30" max="300" :disabled="!bpmOverride" />
                    <div class="hint">{{ bpmOverride ? "Overrides the song brief." : `Using brief: ${brief.bpm} BPM` }}</div>
                  </div>
                  <div class="field">
                    <label>Duration <button class="chip clickable" :class="{ active: durationOverride }" @click="durationOverride = !durationOverride">Override</button></label>
                    <input v-model.number="genDuration" class="input" type="number" min="10" max="600" :disabled="!durationOverride" />
                    <div class="hint">{{ durationOverride ? "Overrides the song brief." : `Using brief: ${formatDuration(brief.duration)}` }}</div>
                  </div>
                </div>
              </div>

              <div class="control-grid">
                <div class="field">
                  <label>Audio format</label>
                  <select v-model="audioFormat" class="select">
                    <option v-for="format in audioFormatOptions" :key="format.value" :value="format.value">{{ format.label }}</option>
                  </select>
                </div>
                <div class="field">
                  <label>Infer method</label>
                  <select v-model="inferMethod" class="select">
                    <option v-for="method in inferMethodOptions" :key="method.value" :value="method.value">{{ method.label }}</option>
                  </select>
                </div>
                <div class="field">
                  <label>LM batch</label>
                  <input v-model.number="lmBatchSize" class="input" type="number" min="1" max="4" />
                  <div class="hint">Planning passes. Max 4.</div>
                </div>
                <div class="field">
                  <label>Synth batch</label>
                  <input v-model.number="synthBatchSize" class="input" type="number" min="1" max="9" />
                  <div class="hint">Renders per pass. LM × synth ≤ 9.</div>
                </div>
              </div>

              <div class="gen-section">
                <div class="gen-label">Source &amp; reference <span class="hint">shared audio</span></div>
                <div class="field">
                  <label>Source take</label>
                  <select v-model="sourceTakeId" class="select">
                    <option value="">Choose a take…</option>
                    <option v-for="take in takes" :key="take.id" :value="take.id">{{ takeTitle(take) }} · {{ formatDuration(take.duration) }} · {{ takeName(take) }}</option>
                  </select>
                </div>
                <div class="row" style="gap: 6px">
                  <button class="btn btn-sm" @click="openSourcePicker"><FileAudio :size="12" /> Source audio</button>
                  <button class="icon-btn" :disabled="!sourcePath" title="Clear source" @click="sourcePath = ''; sourceTakeId = ''"><X :size="13" /></button>
                  <span v-if="sourcePath" class="chip mono truncate" style="max-width: 190px" :title="sourcePath">{{ fileBase(sourcePath) }}</span>
                  <span v-else class="small muted">None selected</span>
                </div>
                <div class="row" style="gap: 6px">
                  <button class="btn btn-sm" @click="openReferencePicker"><FileAudio :size="12" /> Reference audio</button>
                  <button class="icon-btn" :disabled="!referencePath" title="Clear reference" @click="referencePath = ''"><X :size="13" /></button>
                  <span v-if="referencePath" class="chip mono truncate" style="max-width: 190px" :title="referencePath">{{ fileBase(referencePath) }}</span>
                  <span v-else class="small muted">None selected</span>
                </div>
                <div class="control-grid">
                  <div class="field">
                    <label>Repaint start <span class="hint">seconds</span></label>
                    <input v-model.number="startSeconds" class="input" type="number" min="0" max="600" step="0.1" :disabled="genMode !== 'repaint'" />
                  </div>
                  <div class="field">
                    <label>Repaint end <span class="hint">seconds</span></label>
                    <input v-model.number="endSeconds" class="input" type="number" min="0.1" max="600" step="0.1" :disabled="genMode !== 'repaint'" />
                  </div>
                </div>
                <div class="field">
                  <label>Cover strength <span class="hint">0–1 · {{ Number(coverStrength).toFixed(2) }}</span></label>
                  <input v-model.number="coverStrength" type="range" min="0" max="1" step="0.05" :disabled="genMode !== 'cover'" :style="{ opacity: genMode === 'cover' ? 1 : 0.5 }" />
                  <div class="hint">Used by cover mode. Lower values keep the source closer.</div>
                </div>
                <div class="hint">Source and reference files come from the shared Files tree. The source take is selected automatically from the master.</div>
              </div>

              <div class="field">
                <label>One-off instruction</label>
                <textarea v-model="genInstruction" class="textarea" style="min-height: 72px" placeholder="Only for this render — e.g. keep the outro sparse, add muted trumpet, no cymbal lift." />
              </div>

              <div class="gen-footer">
                <button class="btn btn-primary btn-block btn-lg" :disabled="generating || Boolean(generationBlockedReason)" @click="generateTakes">
                  <Loader2 v-if="generating" :size="15" class="spin" /><Sparkles v-else :size="15" />
                  Generate {{ genVariations }} take{{ genVariations === 1 ? "" : "s" }}
                </button>
                <div v-if="generationBlockedReason" class="small muted" style="text-align: center; margin-top: 6px">{{ generationBlockedReason }}</div>
                <div v-else class="small muted" style="text-align: center; margin-top: 6px">{{ modeLabel(genMode) }} · {{ modelName(genModelId) }} · {{ formatDuration(genDuration) }}</div>
              </div>

            </div>
          </aside>
        </div>
      </div>
    </template>

    <!-- ---------------------------------------------------------------- library -->
    <template v-else-if="serviceOnline('music') && tab === 'library'">
      <section class="panel">
        <div class="panel-head" style="align-items: flex-start; flex-wrap: wrap">
          <div>
            <h3>Library</h3>
            <p>{{ filteredSongs.length }} of {{ songs.length }} song{{ songs.length === 1 ? "" : "s" }} · click a row to open it in the studio.</p>
          </div>
          <div class="row">
            <div class="input-group" style="width: 220px">
              <Search :size="14" class="muted" />
              <input v-model="songQuery" class="input input-sm" placeholder="Search title, genre, mood…" />
            </div>
            <select v-model="libraryProject" class="select input-sm" style="width: 190px">
              <option value="">All projects</option>
              <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.title }}</option>
            </select>
            <button class="btn btn-sm" @click="openNewSong"><Plus :size="12" /> New song</button>
          </div>
        </div>
        <div class="panel-body" style="padding-top: 12px">
          <div class="pill-row" style="margin-bottom: 12px">
            <button class="chip clickable" :class="{ active: !libraryProject }" @click="libraryProject = ''">All projects</button>
            <button v-for="project in projects" :key="project.id" class="chip clickable" :class="{ active: libraryProject === project.id }" @click="libraryProject = project.id">
              <span class="dot" :style="{ background: colorHex(project.color) }" /> {{ project.title }} · {{ project.song_count }}
            </button>
          </div>

          <div v-if="filteredSongs.length" class="table-wrap">
            <table class="table library-table">
              <thead>
                <tr>
                  <th>Song</th>
                  <th>Project</th>
                  <th>Genre / mood</th>
                  <th>BPM</th>
                  <th>Duration</th>
                  <th>Language</th>
                  <th>Takes</th>
                  <th>Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <tr v-for="song in filteredSongs" :key="song.id" class="library-row" @click="openSong(song)">
                  <td>
                    <div class="library-song">
                      <img v-if="songCover(song)" class="library-cover" :src="songCover(song) as string" :alt="song.title" />
                      <span v-else class="library-cover library-cover-fallback">{{ song.title.slice(0, 1).toUpperCase() }}</span>
                      <span>
                        <span class="small strong truncate" style="display: block">{{ song.title }}</span>
                        <span class="small muted truncate" style="display: block">{{ song.artist || "No artist" }}</span>
                      </span>
                    </div>
                  </td>
                  <td><span class="chip" :style="{ borderColor: colorHex(song.project_color || projects.find((project) => project.id === song.project_id)?.color) + '55' }">{{ song.project_title || projects.find((project) => project.id === song.project_id)?.title || "Unfiled" }}</span></td>
                  <td>
                    <span class="small">{{ song.genre || "—" }}</span>
                    <span class="small muted" style="display: block">{{ song.mood || "—" }}</span>
                  </td>
                  <td class="mono">{{ song.bpm }}</td>
                  <td class="mono">{{ formatDuration(song.duration) }}</td>
                  <td><span class="small">{{ languageLabelFor(song.language) }}</span></td>
                  <td><span class="chip">{{ song.take_count ?? 0 }}</span></td>
                  <td><span class="small muted nowrap">{{ relativeTime(song.updated_at) }}</span></td>
                  <td><ChevronRight :size="14" class="muted" /></td>
                </tr>
              </tbody>
            </table>
          </div>

          <EmptyState
            v-else
            :icon="ListMusic"
            title="No songs match this view"
            message="Clear the search or choose another project. New songs are created inside a project so their files and takes stay together."
          >
            <button class="btn btn-sm btn-primary" @click="openNewSong"><Plus :size="12" /> New song</button>
          </EmptyState>
        </div>
        <div class="panel-footer">
          <span class="small muted grow">{{ filteredSongs.length }} songs · {{ projectTakeTotal }} takes across {{ projects.length }} projects</span>
          <button class="btn btn-sm btn-ghost" @click="tab = 'projects'"><FolderOpen :size="12" /> Projects</button>
        </div>
      </section>
    </template>

    <!-- ---------------------------------------------------------------- DJ studio -->
    <template v-else-if="serviceOnline('dj') && tab.startsWith('dj-')">
      <DjView
        embedded
        :active-tab="tab.slice(3)"
        @update:active-tab="tab = `dj-${$event}`"
      />
    </template>

    <!-- ---------------------------------------------------------------- SRT -->
    <template v-else-if="serviceOnline('srt') && tab === 'srt'">
      <SubtitlesView embedded />
    </template>

    <!-- ---------------------------------------------------------------- engine -->
    <template v-else-if="serviceOnline('music-engine') && tab === 'engine'">
      <div class="stack">
        <section class="panel engine-hero">
          <div class="engine-hero-inner">
            <div class="engine-orb"><Server :size="28" /></div>
            <div class="grow" style="min-width: 0">
              <div class="eyebrow" style="margin-bottom: 5px"><Cpu :size="12" /> Local inference engine</div>
              <h2>{{ selectedEngine?.name || "ACE-Step 1.5" }}</h2>
              <p class="muted" style="margin-top: 5px">{{ engineDetail }}</p>
              <div class="row" style="margin-top: 11px">
                <span class="chip" :class="engineOnline ? 'success' : 'danger'"><span class="dot" :class="engineOnline ? 'online' : 'offline'" /> {{ engineOnline ? "Online" : "Offline" }}</span>
                <span class="chip">v{{ engineVersion }}</span>
                <span class="chip">{{ engineBackend }}</span>
                <span class="chip mono truncate" style="max-width: 320px" :title="engineUrl">{{ engineUrl }}</span>
              </div>
            </div>
            <div class="row" style="align-self: flex-start">
              <a class="btn btn-sm" :href="docsUrl" target="_blank" rel="noopener"><BookOpen :size="12" /> Docs <ExternalLink :size="11" /></a>
              <button class="btn btn-sm btn-ghost" :disabled="refreshing" @click="refreshAll"><RefreshCw :size="12" :class="{ spin: refreshing }" /> Refresh</button>
            </div>
          </div>
          <div class="health-strip">
            <div class="health-tile">
              <span class="label">Engine status</span>
              <strong :style="{ color: engineOnline ? 'var(--success)' : 'var(--danger)' }">{{ engineOnline ? "Ready" : "Offline" }}</strong>
              <span class="small muted">{{ musicSystem?.health?.detail || "Health probe pending" }}</span>
            </div>
            <div class="health-tile">
              <span class="label">Models installed</span>
              <strong>{{ installedModelCount }} / {{ models.length }}</strong>
              <span class="small muted">GGUF checkpoints with DiT + LM</span>
            </div>
            <div class="health-tile">
              <span class="label">Model files</span>
              <strong>{{ modelFiles.length }}</strong>
              <span class="small muted">{{ engineModelDir }}</span>
            </div>
            <div class="health-tile">
              <span class="label">Music queue</span>
              <strong>{{ queueInfo ? `${queueInfo.running} running` : "Idle" }}</strong>
              <span class="small muted">{{ queueInfo ? `${queueInfo.queued} waiting · ${queueInfo.concurrency}× concurrency` : "Per-component worker" }}</span>
            </div>
          </div>
        </section>

        <div v-if="engineOffline" class="alert warn">
          <div class="row" style="gap: 8px; align-items: flex-start">
            <AlertTriangle :size="15" style="flex: none; margin-top: 1px" />
            <div>
              <strong>The engine is offline.</strong> {{ selectedEngine?.setup_hint || "Start the music-engine container and wait for the first-run GGUF download to finish." }}
              <div v-if="selectedEngine?.restart_instructions" class="small" style="margin-top: 4px">{{ selectedEngine.restart_instructions }}</div>
            </div>
          </div>
        </div>

        <div class="grid grid-2">
          <section class="panel">
            <div class="panel-head">
              <div><h3>Resources</h3><p>Live CPU, memory and disk headroom reported by the music service.</p></div>
              <span class="chip"><Gauge :size="10" /> {{ resources.cpu_count || "—" }} threads</span>
            </div>
            <div class="panel-body stack">
              <div>
                <div class="row-between small"><span><Cpu :size="12" style="vertical-align: -2px" /> CPU load</span><span class="mono">{{ Array.isArray(resources.load_avg) ? resources.load_avg.join(" · ") : "—" }}</span></div>
                <div class="progress thin" style="margin-top: 5px"><span :style="{ width: `${Math.min(100, Number(resources.load_avg?.[0] || 0) / Math.max(1, Number(resources.cpu_count || 1)) * 100)}%` }" /></div>
              </div>
              <div>
                <div class="row-between small"><span><MemoryStick :size="12" style="vertical-align: -2px" /> Memory</span><span class="mono">{{ mbLabel(resources.memory?.used_mb) }} / {{ mbLabel(resources.memory?.total_mb) }}</span></div>
                <div class="progress thin" style="margin-top: 5px"><span :style="{ width: `${Number(resources.memory?.percent || 0)}%` }" /></div>
              </div>
              <div v-for="disk in diskEntries" :key="disk.key">
                <div class="row-between small">
                  <span><HardDrive :size="12" style="vertical-align: -2px" /> {{ disk.key }}</span>
                  <span class="mono">{{ gbLabel(disk.used_gb) }} / {{ gbLabel(disk.total_gb) }}</span>
                </div>
                <div class="progress thin" style="margin-top: 5px"><span :style="{ width: `${diskPercent(disk)}%` }" /></div>
                <div class="small muted mono" style="margin-top: 3px">{{ disk.path || "—" }}</div>
              </div>
              <div v-if="!diskEntries.length" class="small muted">Resource telemetry is not available yet.</div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div><h3>Model files</h3><p>GGUF checkpoints discovered in {{ engineModelDir }}.</p></div>
              <span class="chip">{{ modelFiles.length }} files</span>
            </div>
            <div class="panel-body">
              <div v-if="modelFiles.length" class="file-list">
                <div v-for="file in modelFiles" :key="file.path || file.name" class="file-row" style="padding: 8px 4px">
                  <span class="file-icon" style="width: 30px; height: 30px"><Database :size="14" /></span>
                  <span class="grow" style="min-width: 0">
                    <span class="small strong truncate" style="display: block">{{ file.name }}</span>
                    <span class="small muted mono truncate" style="display: block">{{ file.path }}</span>
                  </span>
                  <span class="small muted nowrap">{{ file.size_label || "—" }}</span>
                </div>
              </div>
              <EmptyState v-else :icon="HardDrive" title="No model files yet" message="The engine downloads GGUF checkpoints on first start. Follow the container logs, then refresh this page." />
            </div>
          </section>
        </div>

        <section class="panel">
          <div class="panel-head">
            <div><h3>Model catalog</h3><p>Every ACE-Step checkpoint the studio can address, with its installed state and capability coverage.</p></div>
            <span class="chip"><Check :size="10" /> {{ installedModelCount }} installed</span>
          </div>
          <div class="panel-body">
            <div class="model-grid">
              <article v-for="model in models" :key="model.id" class="model-card" :class="{ installed: model.installed }">
                <div class="row-between" style="align-items: flex-start">
                  <div>
                    <div class="row" style="gap: 6px">
                      <strong>{{ model.name }}</strong>
                      <span v-if="model.recommended" class="badge running">Recommended</span>
                    </div>
                    <div class="small muted" style="margin-top: 3px">{{ model.description || model.short_name || model.id }}</div>
                  </div>
                  <span class="badge" :class="model.installed ? 'success' : 'warn'">{{ model.installed ? "Installed" : "Missing" }}</span>
                </div>
                <div class="row" style="gap: 5px; margin-top: 8px">
                  <span class="chip">{{ model.parameters || "2B" }}</span>
                  <span class="chip">{{ model.quality || "High" }}</span>
                  <span class="chip">{{ model.speed || "Fast" }}</span>
                  <span v-if="model.vram_gb" class="chip">~{{ model.vram_gb }} GB</span>
                </div>
                <div class="capability-list">
                  <span v-for="key in modelCapabilityKeys(model)" :key="key" class="chip">{{ capabilityLabel(key) }}</span>
                </div>
                <div v-if="model.notes?.length" class="small muted" style="line-height: 1.5">
                  {{ model.notes[0] }}
                </div>
              </article>
              <div v-if="!models.length" class="empty">
                <Server :size="26" style="opacity: 0.45; margin-bottom: 6px" />
                <h3>Catalog unavailable</h3>
                <p>The music service did not return models. Check the service health above.</p>
              </div>
            </div>
          </div>
        </section>

        <div class="grid grid-2">
          <section class="panel">
            <div class="panel-head">
              <div><h3>Commands</h3><p>Useful checks while the engine downloads or warms up.</p></div>
              <span class="chip"><Terminal :size="10" /> shell</span>
            </div>
            <div class="panel-body">
              <CodeBlock :code="engineCommands" label="Music service and ACE-Step" />
            </div>
          </section>

          <section class="panel">
            <div class="panel-head">
              <div><h3>Engine notes</h3><p>Operational limits reported by the music service.</p></div>
              <a class="btn btn-sm btn-ghost" :href="docsUrl" target="_blank" rel="noopener">ACE-Step docs <ExternalLink :size="11" /></a>
            </div>
            <div class="panel-body stack" style="gap: 9px">
              <div v-for="(limit, index) in engineLimitations" :key="index" class="note-row">
                <span class="note-index">{{ String(index + 1).padStart(2, "0") }}</span>
                <span class="small muted" style="line-height: 1.55">{{ limit }}</span>
              </div>
              <div class="row" style="margin-top: 4px">
                <span class="chip"><Activity :size="10" /> {{ engineStatusText }}</span>
                <span class="chip"><Clock3 :size="10" /> checked {{ relativeTime(musicSystem?.checked_at) }}</span>
              </div>
            </div>
          </section>
        </div>

        <section class="panel" style="margin-top: 16px">
          <div class="panel-head">
            <div><h3>Style references</h3><p>Upload music that represents a style. Selected profiles become ACE-Step reference audio and prompt guidance.</p></div>
            <button class="btn btn-sm btn-primary" @click="openStyleModal"><Plus :size="12" /> Add style</button>
          </div>
          <div class="panel-body">
            <div v-if="styles.length" class="grid grid-3" style="gap: 9px">
              <div v-for="style in styles" :key="style.id" class="note-row" style="align-items: flex-start">
                <span class="note-index">{{ style.name.slice(0, 1).toUpperCase() }}</span>
                <div class="stack grow" style="gap: 5px; min-width: 0">
                  <div class="row-between">
                    <span class="small strong truncate">{{ style.name }}</span>
                    <div class="row" style="gap: 3px">
                      <button class="btn btn-sm" @click="selectedStyleId = style.id; tab = 'studio'"><Music2 :size="11" /> Use</button>
                      <button class="icon-btn" title="Delete style" @click="deleteStyle(style)"><Trash2 :size="13" /></button>
                    </div>
                  </div>
                  <div class="small muted">{{ style.description || style.prompt || "Reference audio profile" }}</div>
                  <div class="row" style="gap: 4px">
                    <span class="chip">{{ style.reference_path.split("/").pop() }}</span>
                    <span v-for="tag in style.tags || []" :key="tag" class="chip">{{ tag }}</span>
                  </div>
                </div>
              </div>
            </div>
            <EmptyState v-else :icon="Paintbrush" title="No style references yet" message="Add a song, name the style, and use it as reference audio for future generations." />
          </div>
        </section>
      </div>
    </template>

    <!-- ---------------------------------------------------------------- modals -->
    <BaseModal
      v-model="projectModal"
      :title="projectForm.id ? 'Edit project' : 'New project'"
      subtitle="Projects group songs, lyrics and takes under music/<project>/ in shared storage."
      width="narrow"
    >
      <div class="stack">
        <div class="field">
          <label>Title</label>
          <input v-model="projectForm.title" class="input" placeholder="Nocturno" @keydown.enter="saveProject" />
        </div>
        <div class="field">
          <label>Artist</label>
          <input v-model="projectForm.artist" class="input" placeholder="Helena Rocha" />
        </div>
        <div class="field">
          <label>Description</label>
          <textarea v-model="projectForm.description" class="textarea" placeholder="A nocturnal art-pop record about crossing a city after midnight." />
        </div>
        <div class="field">
          <label>Accent colour</label>
          <div class="swatch-row">
            <button
              v-for="color in projectColorOptions"
              :key="color.id"
              class="swatch"
              :class="{ active: projectForm.color === color.id || projectForm.color === color.hex }"
              :style="{ background: color.hex }"
              :title="color.label"
              @click="projectForm.color = color.hex"
            />
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="projectModal = false">Cancel</button>
        <button class="btn btn-primary" :disabled="savingProject" @click="saveProject">
          <Loader2 v-if="savingProject" :size="13" class="spin" /><Save v-else :size="13" /> {{ projectForm.id ? "Save project" : "Create project" }}
        </button>
      </template>
    </BaseModal>

    <BaseModal v-model="songModal" title="New song" subtitle="The song starts with a complete brief and a blank structured lyric sheet." width="normal">
      <div class="form-grid">
        <div class="field">
          <label>Project</label>
          <select v-model="songForm.project_id" class="select">
            <option v-for="project in projects" :key="project.id" :value="project.id">{{ project.title }}</option>
          </select>
        </div>
        <div class="field">
          <label>Title</label>
          <input v-model="songForm.title" class="input" placeholder="Untitled song" @keydown.enter="createSong" />
        </div>
        <div class="field">
          <label>Artist</label>
          <input v-model="songForm.artist" class="input" placeholder="Artist" />
        </div>
        <div class="field">
          <label>Language</label>
          <select v-model="songForm.language" class="select">
            <option v-for="language in languageOptions" :key="language.code" :value="language.code">{{ language.label }}</option>
          </select>
        </div>
        <div class="field">
          <label>Genre</label>
          <input v-model="songForm.genre" class="input" list="new-song-genre-options" />
          <datalist id="new-song-genre-options">
            <option v-for="genre in genreSuggestions" :key="genre" :value="genre" />
          </datalist>
        </div>
        <div class="field">
          <label>Mood</label>
          <select v-model="songForm.mood" class="select">
            <option v-for="mood in moodOptions" :key="mood" :value="mood">{{ mood }}</option>
          </select>
        </div>
        <div class="field">
          <label>BPM <span class="hint">30–300</span></label>
          <input v-model.number="songForm.bpm" class="input" type="number" min="30" max="300" />
        </div>
        <div class="field">
          <label>Target duration <span class="hint">seconds</span></label>
          <input v-model.number="songForm.duration" class="input" type="number" min="10" max="600" />
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="songModal = false">Cancel</button>
        <button class="btn btn-primary" :disabled="savingNewSong" @click="createSong">
          <Loader2 v-if="savingNewSong" :size="13" class="spin" /><Plus v-else :size="13" /> Create song
        </button>
      </template>
    </BaseModal>

    <BaseModal v-model="draftModal" title="Draft lyrics with the LLM" subtitle="The lyricist receives the song brief, theme and a structured plan with line counts." width="wide">
      <div class="stack">
        <div class="alert">
          <Sparkles :size="12" style="vertical-align: -2px; color: var(--accent-2)" />
          The draft is returned as structured sections. You can review it in the Lyrics panel and apply it without leaving the studio.
        </div>
        <div class="form-grid">
          <div class="field span-2">
            <label>Theme</label>
            <textarea v-model="draftTheme" class="textarea" style="min-height: 68px" placeholder="What is the song about? Images, story, point of view…" />
          </div>
          <div class="field span-2">
            <label>Creative direction</label>
            <textarea v-model="draftDirection" class="textarea" style="min-height: 62px" placeholder="Voice, register, rhyme density, language quirks, what to avoid…" />
          </div>
        </div>

        <div class="panel" style="background: rgba(8, 10, 15, 0.35)">
          <div class="panel-head" style="padding: 11px 13px">
            <div>
              <h3 style="font-size: 13px">Structure</h3>
              <p>{{ draftStructure.length }} sections · {{ draftPlanLines }} lines requested</p>
            </div>
            <button class="btn btn-sm" @click="addDraftPlan"><Plus :size="11" /> Add section</button>
          </div>
          <div class="panel-body stack" style="padding: 10px 13px; gap: 7px">
            <div v-for="(plan, index) in draftStructure" :key="index" class="draft-plan-row">
              <select v-model="plan.type" class="select input-sm" style="width: 128px" @change="syncDraftPlanLabel(plan)">
                <option v-for="type in SECTION_TYPES" :key="type" :value="type">{{ SECTION_LABELS[type] }}</option>
              </select>
              <input v-model="plan.label" class="input input-sm grow" placeholder="Label" />
              <input v-model.number="plan.line_count" class="input input-sm" type="number" min="1" max="16" style="width: 74px" />
              <span class="small muted nowrap">lines</span>
              <button class="icon-btn" title="Remove section" @click="removeDraftPlan(index)"><Trash2 :size="12" /></button>
            </div>
            <div v-if="!draftStructure.length" class="small muted">No sections requested. Add at least one.</div>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="draftModal = false">Cancel</button>
        <button class="btn btn-primary" :disabled="drafting" @click="requestDraft">
          <Loader2 v-if="drafting" :size="13" class="spin" /><Wand2 v-else :size="13" /> Draft lyrics
        </button>
      </template>
    </BaseModal>

    <BaseModal v-model="exportModal" title="Export session" :subtitle="exportTarget?.kind === 'project' ? `Package “${exportTarget?.title}” with every song, lyric sheet and take.` : `Choose the delivery format for “${exportTarget?.title}”.`" width="normal">
      <div class="stack">
        <div class="format-grid">
          <button
            v-for="format in activeExportFormats"
            :key="format.value"
            class="format-option"
            :class="{ active: exportFormat === format.value }"
            @click="exportFormat = format.value"
          >
            <span class="file-icon" style="width: 34px; height: 34px"><component :is="formatIcon(format.value)" :size="16" /></span>
            <span class="grow">
              <strong class="small" style="display: block">{{ format.label }}</strong>
              <span class="small muted">{{ formatHint(format.value, exportTarget?.kind) }}</span>
            </span>
            <Check v-if="exportFormat === format.value" :size="14" style="color: var(--accent-2)" />
          </button>
        </div>
        <div v-if="exportTarget?.kind === 'song' && exportFormat === 'zip'" class="switch-row">
          <div>
            <div class="switch-label">Include every take</div>
            <div class="switch-hint">Ships the master plus every alternative in the session ZIP.</div>
          </div>
          <button class="switch" :class="{ on: exportIncludeAll }" role="switch" :aria-checked="exportIncludeAll" @click="exportIncludeAll = !exportIncludeAll" />
        </div>
        <div class="alert">
          <template v-if="exportTarget?.kind === 'project'">
            Project exports run as a music job and package every song, lyric sheet, take and metadata file into a single ZIP under <span class="mono">music/&lt;project&gt;/exports</span>.
          </template>
          <template v-else>
            Exports run as a music job and write into <span class="mono">music/&lt;project&gt;/&lt;song&gt;/exports</span>. WAV, MP3 and FLAC are rendered with ffmpeg; Session ZIP adds the lyric sheet, song metadata and every take.
          </template>
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="exportModal = false">Cancel</button>
        <button class="btn btn-primary" :disabled="exporting" @click="submitExport">
          <Loader2 v-if="exporting" :size="13" class="spin" /><Download v-else :size="13" /> Export {{ exportFormat.toUpperCase() }}
        </button>
      </template>
    </BaseModal>

    <BaseModal v-model="compareModal" title="Compare takes" subtitle="A/B the master candidates with the same waveform view and metadata." width="wide">
      <div class="compare-grid">
        <div class="compare-column">
          <div class="field">
            <label>Take A</label>
            <select v-model="compareA" class="select">
              <option v-for="take in takes" :key="`a-${take.id}`" :value="take.id">{{ takeTitle(take) }} · {{ formatDuration(take.duration) }}</option>
            </select>
          </div>
          <template v-if="compareTakeA">
            <AudioPlayer :src="compareTakeA.path" :title="takeTitle(compareTakeA)" :subtitle="`${modelName(compareTakeA.metadata?.model || activeSong?.model_id)} · seed ${compareTakeA.seed ?? '—'}`" :download-path="DEMO ? null : compareTakeA.path" compact :bars="82" />
            <div class="compare-meta">
              <div class="row-between small"><span class="muted">Mode</span><span>{{ modeLabel(String(compareTakeA.metadata?.mode || 'full')) }}</span></div>
              <div class="row-between small"><span class="muted">Seed</span><span class="mono">{{ compareTakeA.seed ?? "—" }}</span></div>
              <div class="row-between small"><span class="muted">BPM</span><span>{{ compareTakeA.bpm || activeSong?.bpm }}</span></div>
              <div class="row-between small"><span class="muted">Created</span><span>{{ relativeTime(compareTakeA.created_at) }}</span></div>
            </div>
            <button class="btn btn-sm" :disabled="masterTake?.id === compareTakeA.id" @click="makeMaster(compareTakeA)"><Star :size="11" /> Use as master</button>
          </template>
          <EmptyState v-else :icon="Disc3" title="No take selected" message="Choose a take from the list." />
        </div>
        <div class="compare-column">
          <div class="field">
            <label>Take B</label>
            <select v-model="compareB" class="select">
              <option value="">Choose a take…</option>
              <option v-for="take in takes" :key="`b-${take.id}`" :value="take.id">{{ takeTitle(take) }} · {{ formatDuration(take.duration) }}</option>
            </select>
          </div>
          <template v-if="compareTakeB">
            <AudioPlayer :src="compareTakeB.path" :title="takeTitle(compareTakeB)" :subtitle="`${modelName(compareTakeB.metadata?.model || activeSong?.model_id)} · seed ${compareTakeB.seed ?? '—'}`" :download-path="DEMO ? null : compareTakeB.path" compact :bars="82" />
            <div class="compare-meta">
              <div class="row-between small"><span class="muted">Mode</span><span>{{ modeLabel(String(compareTakeB.metadata?.mode || 'full')) }}</span></div>
              <div class="row-between small"><span class="muted">Seed</span><span class="mono">{{ compareTakeB.seed ?? "—" }}</span></div>
              <div class="row-between small"><span class="muted">BPM</span><span>{{ compareTakeB.bpm || activeSong?.bpm }}</span></div>
              <div class="row-between small"><span class="muted">Created</span><span>{{ relativeTime(compareTakeB.created_at) }}</span></div>
            </div>
            <button class="btn btn-sm" :disabled="masterTake?.id === compareTakeB.id" @click="makeMaster(compareTakeB)"><Star :size="11" /> Use as master</button>
          </template>
          <EmptyState v-else :icon="GitCompare" title="Pick a second take" message="Comparing two generations makes it easier to hear the seed, model and prompt differences." />
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="compareModal = false">Close</button>
      </template>
    </BaseModal>

    <BaseModal v-model="confirmOpen" :title="confirmTitle" width="narrow">
      <div class="alert error">{{ confirmMessage }}</div>
      <template #footer>
        <button class="btn" @click="confirmOpen = false">Cancel</button>
        <button class="btn btn-danger" :disabled="confirming" @click="executeConfirm">
          <Loader2 v-if="confirming" :size="13" class="spin" /><Trash2 v-else :size="13" /> {{ confirmLabel }}
        </button>
      </template>
    </BaseModal>

    <BaseModal v-model="styleOpen" title="Add a style reference" subtitle="Upload a song that represents the sound. It becomes ACE-Step reference audio and prompt guidance." width="normal">
      <div class="stack" style="gap: 12px">
        <div class="grid grid-2">
          <div class="field"><label>Style name</label><input v-model="styleForm.name" class="input" placeholder="Warm analog chamber pop" /></div>
          <div class="field"><label>Tags</label><input v-model="styleForm.tags" class="input" placeholder="analog, intimate, chamber pop" /></div>
        </div>
        <div class="field"><label>Description</label><input v-model="styleForm.description" class="input" placeholder="What makes this style recognisable?" /></div>
        <div class="field"><label>Prompt guidance</label><textarea v-model="styleForm.prompt" class="textarea" placeholder="intimate analog warmth, close vocal, nylon guitar, brushed drums, tape saturation" /></div>
        <div class="field">
          <label>Reference music <span class="hint">audio file</span></label>
          <div class="row">
            <button class="btn btn-sm" @click="stylePicker = true"><FolderOpen :size="13" /> Choose / upload audio</button>
            <span v-if="styleForm.reference_path" class="small muted truncate">{{ styleForm.reference_name || styleForm.reference_path }}</span>
            <span v-else class="small muted">No file selected</span>
          </div>
        </div>
      </div>
      <template #footer>
        <button class="btn" @click="styleOpen = false">Cancel</button>
        <button class="btn btn-primary" :disabled="styleSaving" @click="saveStyle">
          <Loader2 v-if="styleSaving" :size="13" class="spin" /><Plus v-else :size="13" /> Save style
        </button>
      </template>
    </BaseModal>

    <FilePicker v-model="stylePicker" title="Choose style reference audio" kind="audio" accept="audio/*" @selected="onStyleAudio" />
    <FilePicker v-model="sourcePicker" title="Choose source audio" kind="audio" accept="audio/*" @selected="onSourceSelected" />
    <FilePicker v-model="referencePicker" title="Choose reference audio" kind="audio" accept="audio/*" @selected="onReferenceSelected" />
  </div>
</template>

<style scoped>
.music-toolbar {
  position: sticky;
  top: 62px;
  z-index: 22;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin: -10px 0 18px;
  padding: 9px 0;
  border-bottom: 1px solid rgba(35, 42, 58, 0.6);
  background: linear-gradient(180deg, rgba(8, 10, 15, 0.97), rgba(8, 10, 15, 0.84));
  backdrop-filter: blur(16px);
}
.music-toolbar-meta {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  margin-left: auto;
}
.music-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.music-stats { margin-bottom: 18px; }

.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(285px, 1fr));
  gap: 16px;
}
.project-card {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(21, 26, 37, 0.92), rgba(13, 16, 23, 0.95));
  cursor: pointer;
  transition: transform 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}
.project-card:hover {
  transform: translateY(-3px);
  border-color: var(--line-strong);
  box-shadow: 0 22px 50px rgba(0, 0, 0, 0.32);
}
.project-card.selected {
  box-shadow: 0 0 0 1px rgba(139, 92, 246, 0.55), 0 22px 50px rgba(0, 0, 0, 0.28);
}
.project-card.selected .project-info h3 { color: #ddd6fe; }
.project-cover {
  position: relative;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  background: #0b0d13;
}
.project-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  opacity: 0.92;
  transition: transform 500ms ease;
}
.project-card:hover .project-cover img { transform: scale(1.045); }
.project-cover-fallback {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  font-family: var(--display);
  font-size: 44px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.72);
  letter-spacing: -0.04em;
}
.project-cover-shade {
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(4, 6, 10, 0.1) 0%, rgba(4, 6, 10, 0.04) 42%, rgba(5, 7, 11, 0.92) 100%);
}
.project-cover-top,
.project-cover-bottom {
  position: absolute;
  left: 11px;
  right: 11px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.project-cover-top { top: 10px; align-items: flex-start; }
.project-cover-bottom { bottom: 10px; }
.project-cover .chip {
  background: rgba(8, 10, 15, 0.58);
  backdrop-filter: blur(8px);
  border-color: rgba(255, 255, 255, 0.1);
}
.project-actions {
  display: flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.62);
  backdrop-filter: blur(10px);
}
.project-actions button {
  display: grid;
  place-items: center;
  width: 27px;
  height: 27px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--muted);
}
.project-actions button:hover { background: rgba(255, 255, 255, 0.09); color: var(--text); }
.project-info {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 14px 16px 16px;
}
.project-info h3 { font-size: 17px; font-weight: 650; }
.project-desc {
  min-height: 34px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.project-progress {
  height: 3px;
  overflow: hidden;
  border-radius: 99px;
  background: #1b2130;
  margin-top: 4px;
}
.project-progress span {
  display: block;
  width: 38%;
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
}
.new-project-card {
  min-height: 310px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  border: 1px dashed var(--line-strong);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.012);
  color: var(--muted);
  text-align: center;
  transition: 160ms ease;
}
.new-project-card:hover {
  border-color: rgba(139, 92, 246, 0.55);
  background: rgba(139, 92, 246, 0.05);
  color: var(--text);
}
.new-project-icon {
  width: 54px;
  height: 54px;
  display: grid;
  place-items: center;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: var(--panel-2);
  color: var(--accent-2);
  margin-bottom: 2px;
}

.studio-hero {
  position: relative;
  overflow: hidden;
}
.studio-hero-glow {
  position: absolute;
  inset: -30%;
  background-size: cover;
  background-position: center;
  filter: blur(50px) saturate(1.2);
  opacity: 0.22;
  transform: scale(1.15);
  pointer-events: none;
}
.studio-hero::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, rgba(8, 10, 15, 0.5), rgba(8, 10, 15, 0.12) 55%, rgba(8, 10, 15, 0.55));
  pointer-events: none;
}
.studio-hero-inner {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-start;
  gap: 18px;
  padding: 20px 22px;
}
.studio-cover {
  width: 118px;
  height: 118px;
  flex: none;
  display: grid;
  place-items: center;
  overflow: hidden;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.42), rgba(34, 211, 238, 0.2));
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.38);
  font-family: var(--display);
  font-size: 38px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.82);
}
.studio-cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
.studio-title {
  font-size: clamp(24px, 3vw, 34px);
  line-height: 1.08;
  font-weight: 700;
  letter-spacing: -0.035em;
}
.studio-chips { margin-top: 9px; gap: 5px; }
.studio-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.save-state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 9px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: rgba(8, 10, 15, 0.4);
  font-size: 10.5px;
  font-weight: 600;
  color: var(--muted);
  white-space: nowrap;
}

.studio-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 400px;
  gap: 18px;
  align-items: start;
}
.generation-panel {
  position: sticky;
  top: 128px;
  max-height: calc(100vh - 146px);
  display: flex;
  flex-direction: column;
}
.generation-panel .panel-head { flex: none; }
.style-reference-note { display: flex; align-items: center; gap: 6px; padding: 7px 8px; border: 1px solid rgba(139,92,246,.25); border-radius: 8px; background: rgba(139,92,246,.07); min-width: 0; }
.gen-body {
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 15px;
  scrollbar-width: thin;
}
.gen-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 13px;
  border-top: 1px solid rgba(35, 42, 58, 0.72);
}
.gen-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--muted-2);
}
.gen-footer {
  padding-top: 15px;
  border-top: 1px solid rgba(35, 42, 58, 0.8);
}
.model-note {
  line-height: 1.45;
  margin-top: 2px;
}
.mode-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}
.mode-option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  min-height: 78px;
  padding: 9px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(8, 10, 15, 0.35);
  color: var(--muted);
  text-align: left;
  transition: 150ms ease;
}
.mode-option strong { font-size: 11px; color: var(--text); }
.mode-option span { font-size: 9.5px; line-height: 1.35; }
.mode-option:hover:not(.disabled) { border-color: var(--line-strong); color: var(--text); }
.mode-option.active {
  border-color: rgba(139, 92, 246, 0.55);
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.15), rgba(34, 211, 238, 0.05));
  box-shadow: inset 0 0 0 1px rgba(139, 92, 246, 0.15);
}
.mode-option.active svg { color: var(--accent-2); }
.mode-option.disabled { opacity: 0.38; cursor: not-allowed; }
.variation-row { display: flex; gap: 6px; }
.variation-btn {
  flex: 1;
  height: 32px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(8, 10, 15, 0.38);
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
}
.variation-btn:hover:not(:disabled) { border-color: var(--line-strong); color: var(--text); }
.variation-btn.active {
  border-color: rgba(139, 92, 246, 0.6);
  background: rgba(139, 92, 246, 0.18);
  color: #ddd6fe;
}
.variation-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.control-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.switch-list { display: flex; flex-direction: column; }
.switch-list .switch-row { border-bottom: 1px solid rgba(35, 42, 58, 0.55); }
.switch-list .switch-row:last-child { border-bottom: none; }

.master-meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
.meta-tile {
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(8, 10, 15, 0.4);
}
.meta-tile .label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted-2);
}
.meta-tile .value {
  margin-top: 4px;
  font-size: 12px;
  font-weight: 600;
}
.section-map {
  display: flex;
  height: 34px;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.section-map-segment {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  overflow: hidden;
  padding: 0 5px;
  border-right: 1px solid rgba(255, 255, 255, 0.09);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.72);
  white-space: nowrap;
}
.section-map-segment:last-child { border-right: none; }

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 13px;
}
.form-grid .span-2 { grid-column: 1 / -1; }

.lyric-section.active { border-color: var(--accent); background: rgba(139, 92, 246, 0.06); }

.lyric-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--accent);
  border-radius: 12px;
  background: rgba(8, 10, 15, 0.32);
}
.lyric-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 10px;
}
.lyric-type-dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
}
.lyric-type-select { width: 119px; }
.lyric-label-input { width: 150px; }
.lyric-text {
  min-height: 92px;
  font-size: 12.5px;
  line-height: 1.75;
}
.draft-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px;
  border: 1px solid rgba(139, 92, 246, 0.3);
  border-radius: 12px;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.09), rgba(8, 10, 15, 0.36));
}

.take-group { display: flex; flex-direction: column; gap: 8px; }
.take-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  padding: 2px 2px 4px;
}
.gen-index {
  width: 25px;
  height: 25px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(34, 211, 238, 0.28);
  border-radius: 7px;
  background: rgba(34, 211, 238, 0.08);
  color: var(--accent-2);
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.02em;
}
.take-item {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 11px;
  border: 1px solid var(--line);
  border-radius: 13px;
  background: rgba(8, 10, 15, 0.28);
}
.take-item.master {
  border-color: rgba(139, 92, 246, 0.42);
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.08), rgba(8, 10, 15, 0.36));
  box-shadow: inset 3px 0 0 rgba(139, 92, 246, 0.8);
}
.take-top {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.take-number {
  width: 34px;
  height: 34px;
  flex: none;
  display: grid;
  place-items: center;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--panel-3);
  font-family: var(--display);
  font-size: 12px;
  font-weight: 700;
}
.take-actions { gap: 4px; flex-wrap: wrap; justify-content: flex-end; }
.take-export-row { gap: 5px; flex-wrap: wrap; }

.engine-hero { overflow: hidden; }
.engine-hero-inner {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 18px;
  padding: 22px;
  background:
    radial-gradient(500px 200px at 12% 0%, rgba(139, 92, 246, 0.13), transparent 65%),
    radial-gradient(420px 220px at 90% 100%, rgba(34, 211, 238, 0.07), transparent 65%);
}
.engine-orb {
  width: 62px;
  height: 62px;
  flex: none;
  display: grid;
  place-items: center;
  border: 1px solid rgba(139, 92, 246, 0.4);
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.32), rgba(34, 211, 238, 0.16));
  color: #ddd6fe;
  box-shadow: 0 0 42px rgba(139, 92, 246, 0.18);
}
.engine-hero h2 {
  font-size: 27px;
  line-height: 1.1;
  letter-spacing: -0.03em;
}
.health-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-top: 1px solid var(--line);
}
.health-tile {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 14px 18px;
  border-right: 1px solid var(--line);
}
.health-tile:last-child { border-right: none; }
.health-tile .label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.11em;
  text-transform: uppercase;
  color: var(--muted-2);
}
.health-tile strong {
  font-family: var(--display);
  font-size: 19px;
  letter-spacing: -0.02em;
}
.model-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(265px, 1fr));
  gap: 12px;
}
.model-card {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 13px;
  background: rgba(8, 10, 15, 0.3);
}
.model-card.installed {
  border-color: rgba(52, 211, 153, 0.22);
  background: linear-gradient(135deg, rgba(52, 211, 153, 0.03), rgba(8, 10, 15, 0.32));
}
.capability-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.capability-list .chip { font-size: 9px; padding: 3px 6px; }
.note-row {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 8px 0;
  border-bottom: 1px solid rgba(35, 42, 58, 0.5);
}
.note-row:last-child { border-bottom: none; }
.note-index {
  font-family: var(--mono);
  font-size: 9px;
  color: var(--accent-2);
  padding-top: 2px;
}

.table-wrap { overflow-x: auto; }
.library-table { min-width: 940px; }
.library-row { cursor: pointer; }
.library-row:hover td { background: rgba(139, 92, 246, 0.055); }
.library-song {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 190px;
}
.library-cover {
  width: 36px;
  height: 36px;
  flex: none;
  object-fit: cover;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.library-cover-fallback {
  display: grid;
  place-items: center;
  background: linear-gradient(135deg, rgba(139, 92, 246, 0.3), rgba(34, 211, 238, 0.12));
  font-family: var(--display);
  font-size: 15px;
  font-weight: 700;
}

.swatch-row { display: flex; flex-wrap: wrap; gap: 8px; }
.swatch {
  width: 28px;
  height: 28px;
  border: 2px solid transparent;
  border-radius: 9px;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.1) inset;
}
.swatch.active {
  border-color: #fff;
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.35);
}
.format-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.format-option {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: rgba(8, 10, 15, 0.32);
  text-align: left;
}
.format-option:hover { border-color: var(--line-strong); }
.format-option.active {
  border-color: rgba(139, 92, 246, 0.5);
  background: rgba(139, 92, 246, 0.09);
}
.draft-plan-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 7px;
}
.compare-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.compare-column {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 13px;
  background: rgba(8, 10, 15, 0.28);
}
.compare-meta {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 9px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.32);
}
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1320px) {
  .studio-grid { grid-template-columns: 1fr; }
  .generation-panel {
    position: static;
    max-height: none;
  }
  .gen-body { overflow: visible; }
  .studio-actions { margin-left: auto; }
}
@media (max-width: 980px) {
  .studio-hero-inner { flex-wrap: wrap; }
  .studio-actions { width: 100%; justify-content: flex-start; margin-left: 0; }
  .master-meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .health-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .health-tile:nth-child(2) { border-right: none; }
  .health-tile:nth-child(-n + 2) { border-bottom: 1px solid var(--line); }
}
@media (max-width: 780px) {
  .music-toolbar { top: 54px; }
  .project-grid { grid-template-columns: 1fr; }
  .new-project-card { min-height: 160px; }
  .form-grid, .control-grid, .mode-grid, .compare-grid, .format-grid { grid-template-columns: 1fr; }
  .studio-cover { width: 86px; height: 86px; font-size: 28px; }
  .studio-title { font-size: 24px; }
  .master-meta-grid { grid-template-columns: 1fr 1fr; }
  .lyric-type-select, .lyric-label-input { width: auto; flex: 1; min-width: 100px; }
  .take-top { flex-wrap: wrap; }
  .take-actions { width: 100%; justify-content: flex-start; }
  .health-strip { grid-template-columns: 1fr; }
  .health-tile { border-right: none; border-bottom: 1px solid var(--line); }
}
</style>
