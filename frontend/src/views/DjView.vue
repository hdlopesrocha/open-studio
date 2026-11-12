<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  AudioLines,
  Check,
  Disc3,
  Download,
  Gauge,
  Layers,
  ListMusic,
  Loader2,
  Music2,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Upload,
  Wand2,
  X,
  Zap,
} from "lucide-vue-next";
import { api, downloadUrl, fileUrl, formatDuration, relativeTime } from "@/lib/api";
import { DEMO } from "@/lib/types";
import type { Job } from "@/lib/types";
import { useJobsStore } from "@/stores/jobs";
import { useSystemStore } from "@/stores/system";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import TabsBar from "@/components/TabsBar.vue";
import ProgressBar from "@/components/ProgressBar.vue";
import BaseModal from "@/components/BaseModal.vue";
import AudioPlayer from "@/components/AudioPlayer.vue";
import SectionPlayer from "@/components/music/SectionPlayer.vue";
import EmptyState from "@/components/EmptyState.vue";

const props = withDefaults(defineProps<{ embedded?: boolean; activeTab?: string }>(), {
  embedded: false,
  activeTab: "",
});
const emit = defineEmits<{ "update:activeTab": [value: string] }>();

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

interface DjSection {
  id: string;
  index: number;
  role: string;
  label: string;
  start: number;
  end: number;
  bars: number;
  energy: number;
  mood: string;
  filter_hz: number;
  layers: string[];
  prompt: string;
  scene_id?: string;
  boundary_strength?: number;
  summary?: string;
  start_bar?: number;
  end_bar?: number;
}

interface DjStructure {
  source: string;
  style: string;
  bpm: number;
  key: string;
  duration: number;
  total_bars: number;
  prompt: string;
  energy: number;
  mood: string;
  tags: string[];
  sections: DjSection[];
  model?: any;
}

interface DjTrack {
  id: string;
  title: string;
  artist: string;
  path: string;
  url?: string;
  duration: number;
  bpm: number;
  bpm_confidence: number;
  key: string;
  camelot: string;
  style: string;
  style_confidence: number;
  mood: string;
  energy: number;
  danceability: number;
  valence: number;
  tags: string[];
  waveform: number[];
  status: string;
  error: string;
  notes: string;
  analyzed: boolean;
  analysis_version?: number;
  scene_count?: number;
  sections: DjSection[];
  summary: string;
  created_at?: string;
  updated_at?: string;
}

interface DjStyle {
  style: string;
  label: string;
  trained: boolean;
  track_count: number;
  available_tracks: number;
  bpm: number;
  energy: number;
  key: string;
  mood: string;
  preset: { bpm: number; energy: number; key: string; valence: number };
  model: any;
  updated_at?: string;
}

interface DjGeneration {
  id: string;
  style: string;
  title: string;
  prompt: string;
  path: string;
  url?: string;
  stems?: Record<string, { path: string; url?: string; duration?: number }>;
  structure?: DjSection[];
  params?: any;
  duration: number;
  bpm: number;
  key: string;
  seed: number;
  status: string;
  error: string;
  job_id?: string;
  created_at?: string;
}

interface DjEffect {
  id: string;
  label: string;
  description: string;
  defaults: Record<string, any>;
}

interface DjEmotion {
  id: string;
  label: string;
  effects: Array<Record<string, any>>;
  note: string;
}

interface DjSceneTrack {
  entry_id?: string;
  track_id: string;
  source_track_id?: string;
  section_id?: string;
  section_label?: string;
  section_role?: string;
  title: string;
  artist: string;
  path: string;
  style: string;
  mood: string;
  bpm: number;
  master_bpm: number;
  key: string;
  camelot: string;
  duration: number;
  in: number;
  out: number;
  start: number;
  energy: number;
  gain_db: number;
  effects: Array<Record<string, any>>;
  transition: { type?: string; beats?: number; curve?: string; bars?: number };
  timeline_duration: number;
}

interface DjScene {
  source: string;
  title?: string;
  prompt: string;
  mood: string;
  master_bpm: number;
  beat_seconds: number;
  duration: number;
  tracks: DjSceneTrack[];
  notes: string[];
  created_at?: string;
}

interface DjMix {
  id: string;
  title: string;
  prompt: string;
  path: string;
  url?: string;
  duration: number;
  status: string;
  error: string;
  job_id?: string;
  track_count: number;
  master_bpm?: number;
  notes?: string[];
  scene?: DjScene | null;
  created_at?: string;
  updated_at?: string;
}

const jobs = useJobsStore();
const system = useSystemStore();
const toasts = useToastStore();

const tab = ref(props.activeTab || "library");
watch(
  () => props.activeTab,
  (next) => {
    if (next && next !== tab.value) tab.value = next;
  },
);
watch(tab, (next) => {
  if (props.embedded) emit("update:activeTab", next);
});
const loading = ref(false);
const error = ref("");
const tracks = ref<DjTrack[]>([]);
const styles = ref<DjStyle[]>([]);
const generations = ref<DjGeneration[]>([]);
const mixes = ref<DjMix[]>([]);
const overview = ref<any>({
  tracks: 0,
  analyzed: 0,
  styles_trained: 0,
  generations: 0,
  mixes: 0,
  max_upload_mb: 512,
});
const effects = ref<DjEffect[]>([]);
const emotions = ref<DjEmotion[]>([]);
const transitions = ref<string[]>(["crossfade", "filter_sweep", "bass_swap", "echo_out", "cut"]);
const trackQuery = ref("");
const trackStyleFilter = ref("");
const activeJobId = ref("");
const pollTimer = ref<number | undefined>(undefined);

const uploading = ref(false);
const uploadProgress = ref(0);
const dragActive = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);

const editOpen = ref(false);
const editTarget = ref<DjTrack | null>(null);
const editForm = reactive({ title: "", artist: "", style: "", mood: "", notes: "", tags: "" });

const create = reactive({
  style: "House",
  prompt: "",
  duration: 180,
  energy: 0.68,
  bpm: 0,
  key: "",
  title: "",
  seed: null as number | null,
  use_llm: false,
});
const structure = ref<DjStructure | null>(null);
const selectedSection = ref(0);
const structureLoading = ref(false);
const generating = ref(false);

const mixTitle = ref("");
const mixPrompt = ref("");
const activeMix = ref<DjMix | null>(null);
const scene = ref<DjScene | null>(null);
const selectedMixTrackIds = ref<string[]>([]);
const sceneLoading = ref(false);
const sceneTransitionBeats = ref(16);
const sceneMasterBpm = ref(0);
const sceneKeepOrder = ref(true);
const sceneUseSections = ref(true);
const sceneSegments = ref(6);
const sceneDurationMinutes = ref(6);
const sceneSaving = ref(false);
const mixRendering = ref(false);

const activeJob = computed<Job | null>(() => (activeJobId.value ? (jobs.byId(activeJobId.value) as Job) || null : null));
const djService = computed(() => system.service("dj"));
const djJobs = computed(() => jobs.items.filter((job) => job.component === "dj").slice(0, 4));
const activeDjJobs = computed(() =>
  jobs.items.filter((job) => job.component === "dj" && ["queued", "running", "canceling"].includes(job.status)),
);
const filteredTracks = computed(() => {
  const needle = trackQuery.value.trim().toLowerCase();
  return tracks.value.filter((track) => {
    if (trackStyleFilter.value && track.style !== trackStyleFilter.value) return false;
    if (!needle) return true;
    return `${track.title} ${track.artist} ${track.style} ${track.mood} ${track.tags.join(" ")}`.toLowerCase().includes(needle);
  });
});
const analyzedTracks = computed(() => tracks.value.filter((track) => track.analyzed));
const mixableGenerations = computed(() => generations.value.filter((generation) => generation.status === "completed" && generation.path));
const selectedStyle = computed(() => styles.value.find((item) => item.style === create.style) || null);
const trainedCount = computed(() => styles.value.filter((item) => item.trained).length);
const selectedSceneTrack = computed(() => scene.value?.tracks?.[selectedSection.value] || null);
const tabs = computed(() => [
  { id: "library", label: "Library", count: tracks.value.length },
  { id: "create", label: "Create", count: generations.value.length },
  { id: "mix", label: "Mix Lab", count: mixes.value.length },
]);
const demoTrackBars = (seed: number) =>
  Array.from({ length: 64 }, (_, index) => 0.18 + Math.abs(Math.sin(seed + index * 0.37) * Math.cos(index * 0.13 + seed)) * 0.8);

function normalizeScene(value: any): DjScene | null {
  if (!value || typeof value !== "object" || !Array.isArray(value.tracks) || value.tracks.length === 0) {
    return null;
  }
  return {
    ...value,
    source: value.source || "manual",
    prompt: value.prompt || "",
    mood: value.mood || "balanced",
    master_bpm: Number(value.master_bpm) || 120,
    beat_seconds: Number(value.beat_seconds) || 0.5,
    duration: Number(value.duration) || 0,
    tracks: value.tracks.map((track: any, index: number) => ({
      ...track,
      index,
      title: track.title || track.name || `Track ${index + 1}`,
      effects: Array.isArray(track.effects) ? track.effects : [],
      transition: track.transition && typeof track.transition === "object" ? track.transition : { type: "crossfade", beats: 16 },
      timeline_duration: Number(track.timeline_duration || (Number(track.out) - Number(track.in)) || 0),
    })),
    notes: Array.isArray(value.notes) ? value.notes : [],
  };
}

function sceneTrackIds(tracks: DjSceneTrack[] | undefined): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const track of tracks || []) {
    const id = track.source_track_id || track.track_id;
    if (id && !seen.has(id)) {
      seen.add(id);
      result.push(id);
    }
  }
  return result;
}

function barsForSection(section: DjSection) {
  const bpm = structure.value?.bpm || create.bpm || 120;
  return Math.max(1, Number(((section.end - section.start) / (60 / bpm * 4)).toFixed(2)));
}

function sectionWidth(section: DjSection) {
  const total = structure.value?.duration || 1;
  return `${Math.max(2, ((section.end - section.start) / total) * 100)}%`;
}

function sectionColor(role: string) {
  return {
    intro: "#64748b",
    build: "#f59e0b",
    drop: "#a78bfa",
    chorus: "#22d3ee",
    breakdown: "#38bdf8",
    outro: "#475569",
    verse: "#34d399",
    bridge: "#818cf8",
    theme: "#f472b6",
    rise: "#fbbf24",
    groove: "#2dd4bf",
  }[role] || "#8b5cf6";
}

const trackPlayers = new Map<string, any>();

function setTrackPlayer(trackId: string, player: any) {
  if (player) trackPlayers.set(trackId, player);
  else trackPlayers.delete(trackId);
}

function seekToSection(track: DjTrack, section: DjSection) {
  for (const [trackId, other] of trackPlayers) {
    if (trackId !== track.id) other?.pause?.();
  }
  const player = trackPlayers.get(track.id);
  if (player?.seekTo) player.seekTo(section.start, true);
}

function trackSectionWidth(track: DjTrack, section: DjSection) {
  const total = Math.max(1, track.duration || 1);
  return `${Math.max(1.5, ((section.end - section.start) / total) * 100)}%`;
}

function sceneTrackWidth(track: DjSceneTrack) {
  const total = scene.value?.duration || 1;
  return `${Math.max(3, ((track.timeline_duration || track.out - track.in || 1) / total) * 100)}%`;
}
function sceneTrackLeft(track: DjSceneTrack) {
  const total = scene.value?.duration || 1;
  return `${Math.max(0, (track.start / total) * 100)}%`;
}
function sceneTrackColor(index: number) {
  return ["#8b5cf6", "#22d3ee", "#f59e0b", "#34d399", "#fb7185", "#818cf8", "#f472b6"][index % 7];
}

async function loadAll(silent = false) {
  if (DEMO) {
    applyDemo();
    return;
  }
  if (!silent) loading.value = true;
  error.value = "";
  try {
    const [ov, tr, st, gen, mx, fx] = await Promise.all([
      api.get<any>("/dj/overview"),
      api.get<{ items: DjTrack[] }>("/dj/tracks?limit=500"),
      api.get<{ items: DjStyle[] }>("/dj/styles"),
      api.get<{ items: DjGeneration[] }>("/dj/generations?limit=80"),
      api.get<{ items: DjMix[] }>("/dj/mixes?limit=80"),
      api.get<{ effects: DjEffect[]; emotions: DjEmotion[]; transitions: string[] }>("/dj/effects/presets"),
    ]);
    overview.value = ov;
    tracks.value = tr.items || [];
    styles.value = st.items || [];
    generations.value = gen.items || [];
    mixes.value = mx.items || [];
    effects.value = fx.effects || [];
    emotions.value = fx.emotions || [];
    transitions.value = fx.transitions || transitions.value;
    if (activeMix.value) {
      const current = mixes.value.find((item) => item.id === activeMix.value?.id);
      if (current) {
        activeMix.value = { ...current, scene: activeMix.value.scene || current.scene };
        if (!scene.value) await selectMix(current.id);
      }
    }
  } catch (err: any) {
    error.value = err?.message || "Could not reach the DJ Studio service.";
  } finally {
    loading.value = false;
  }
}

function applyDemo() {
  const demoTracks: DjTrack[] = [
    {
      id: "demo-track-1", title: "Nocturno", artist: "Open Studio", path: "dj/tracks/demo/nocturno.wav",
      duration: 214, bpm: 124, bpm_confidence: 0.92, key: "A minor", camelot: "8A", style: "House", style_confidence: 0.81,
      mood: "Warm / Uplifting", energy: 0.72, danceability: 0.86, valence: 0.63, tags: ["House", "8A", "124 BPM"],
      waveform: demoTrackBars(1), status: "analyzed", error: "", notes: "", analyzed: true,
      sections: [], summary: "House · 124 BPM · A minor (8A) · Warm / Uplifting", created_at: new Date(Date.now() - 900000).toISOString(),
    },
    {
      id: "demo-track-2", title: "Afterhours", artist: "Open Studio", path: "dj/tracks/demo/afterhours.wav",
      duration: 188, bpm: 132, bpm_confidence: 0.95, key: "F minor", camelot: "4A", style: "Techno", style_confidence: 0.88,
      mood: "Driving / Dark", energy: 0.84, danceability: 0.74, valence: 0.34, tags: ["Techno", "4A", "132 BPM"],
      waveform: demoTrackBars(2), status: "analyzed", error: "", notes: "", analyzed: true,
      sections: [], summary: "Techno · 132 BPM · F minor (4A) · Driving / Dark", created_at: new Date(Date.now() - 3600000).toISOString(),
    },
    {
      id: "demo-track-3", title: "Golden Hour", artist: "Open Studio", path: "dj/tracks/demo/golden-hour.wav",
      duration: 176, bpm: 118, bpm_confidence: 0.89, key: "C major", camelot: "8B", style: "Disco & Funk", style_confidence: 0.77,
      mood: "Euphoric", energy: 0.68, danceability: 0.9, valence: 0.84, tags: ["Disco & Funk", "8B", "118 BPM"],
      waveform: demoTrackBars(3), status: "analyzed", error: "", notes: "", analyzed: true,
      sections: [], summary: "Disco & Funk · 118 BPM · C major (8B) · Euphoric", created_at: new Date(Date.now() - 7200000).toISOString(),
    },
  ];
  tracks.value = demoTracks;
  styles.value = [
    { style: "House", label: "House", trained: true, track_count: 4, available_tracks: 4, bpm: 124, energy: 0.71, key: "A minor", mood: "Warm / Uplifting", preset: { bpm: 124, energy: 0.68, key: "A minor", valence: 0.6 }, model: { tracks: 4, bpm: 124, key: "A minor" } },
    { style: "Techno", label: "Techno", trained: true, track_count: 2, available_tracks: 2, bpm: 132, energy: 0.82, key: "F minor", mood: "Driving / Dark", preset: { bpm: 134, energy: 0.82, key: "F minor", valence: 0.38 }, model: { tracks: 2, bpm: 132, key: "F minor" } },
    { style: "Disco & Funk", label: "Disco & Funk", trained: false, track_count: 0, available_tracks: 1, bpm: 116, energy: 0.72, key: "G minor", mood: "Euphoric", preset: { bpm: 116, energy: 0.72, key: "G minor", valence: 0.72 }, model: {} },
    { style: "Drum & Bass", label: "Drum & Bass", trained: false, track_count: 0, available_tracks: 0, bpm: 174, energy: 0.84, key: "E minor", mood: "Driving / Dark", preset: { bpm: 174, energy: 0.84, key: "E minor", valence: 0.42 }, model: {} },
  ];
  effects.value = [
    { id: "filter_sweep", label: "Filter sweep", description: "Low/high-pass automation", defaults: { mode: "lowpass", from_hz: 18000, to_hz: 350, amount: 0.8 } },
    { id: "reverb", label: "Reverb", description: "Room tail", defaults: { amount: 0.24 } },
    { id: "delay", label: "Tempo delay", description: "Beat-synced echoes", defaults: { beats: 0.75, feedback: 0.38, amount: 0.28 } },
    { id: "drive", label: "Drive", description: "Saturation", defaults: { amount: 0.3 } },
    { id: "bitcrush", label: "Bitcrush", description: "Glitch/hard emotion", defaults: { amount: 0.35 } },
  ];
  emotions.value = [
    { id: "euphoric", label: "Euphoric", effects: [{ type: "highpass", cutoff: 380, amount: 0.6 }, { type: "reverb", amount: 0.2 }], note: "Open the top end." },
    { id: "dark", label: "Dark / warehouse", effects: [{ type: "lowpass", cutoff: 2400, amount: 0.9 }, { type: "drive", amount: 0.25 }], note: "Filter down and saturate." },
    { id: "dreamy", label: "Dreamy", effects: [{ type: "chorus", amount: 0.42 }, { type: "reverb", amount: 0.34 }], note: "Wide and floating." },
  ];
  const demoScene: DjScene = {
    source: "dj-ai", title: "Sunset to warehouse", prompt: "euphoric sunset into a dark warehouse",
    mood: "euphoric", master_bpm: 124, beat_seconds: 0.4839, duration: 341, notes: ["1. Nocturno · 124 BPM · A minor · crossfade (16 beats)", "2. Afterhours · 132 BPM · F minor · filter_sweep (24 beats)", "Master tempo 124 BPM · 2 tracks · 341s"],
    tracks: [
      { track_id: "demo-track-1", title: "Nocturno", artist: "Open Studio", path: demoTracks[0].path, style: "House", mood: demoIsMood(0), bpm: 124, master_bpm: 124, key: "A minor", camelot: "8A", duration: 214, in: 16, out: 198, start: 0, energy: 0.72, gain_db: 0, effects: [], transition: { type: "crossfade", beats: 16, curve: "equal_power", bars: 4 }, timeline_duration: 182 },
      { track_id: "demo-track-2", title: "Afterhours", artist: "Open Studio", path: demoTracks[1].path, style: "Techno", mood: "Driving / Dark", bpm: 132, master_bpm: 124, key: "F minor", camelot: "4A", duration: 188, in: 14, out: 174, start: 174.26, energy: 0.84, gain_db: -0.8, effects: [{ type: "reverb", amount: 0.2, start: 140, end: 160 }], transition: { type: "crossfade", beats: 16, curve: "equal_power", bars: 4 }, timeline_duration: 160 },
    ],
  };
  scene.value = demoScene;
  mixes.value = [{ id: "demo-mix", title: "Sunset to warehouse", prompt: "euphoric sunset into a dark warehouse", path: "", duration: 341, status: "draft", error: "", track_count: 2, master_bpm: 124, notes: demoScene.notes, scene: demoScene, updated_at: new Date().toISOString() }];
  activeMix.value = mixes.value[0];
  selectedMixTrackIds.value = ["demo-track-1", "demo-track-2"];
  generations.value = [
    { id: "demo-gen-1", style: "House", title: "Nocturno (AI structure)", prompt: "warm sunset house", path: "dj/generated/demo/track.wav", duration: 180, bpm: 124, key: "A minor", seed: 438921, status: "completed", error: "", created_at: new Date(Date.now() - 600000).toISOString() },
    { id: "demo-gen-2", style: "Techno", title: "Warehouse tool", prompt: "dark warehouse peak time", path: "dj/generated/demo-2/track.wav", duration: 240, bpm: 132, key: "F minor", seed: 921031, status: "completed", error: "", created_at: new Date(Date.now() - 4200000).toISOString() },
  ];
  overview.value = { tracks: tracks.value.length, analyzed: tracks.value.length, styles_trained: 2, generations: 2, mixes: 1, max_upload_mb: 512 };
  structure.value = {
    source: "local-planner", style: "House", bpm: 124, key: "A minor", duration: 180, total_bars: 93, prompt: "warm sunset house", energy: 0.72, mood: "Warm / Uplifting", tags: ["groove"],
    sections: [
      demoSection(0, "intro", "Intro", 0, 8, 36, "Dreamy", ["chords", "arp"]),
      demoSection(1, "build", "Build", 8, 8, 64, "Tense / Rising", ["drums", "bass", "chords", "arp", "riser"]),
      demoSection(2, "drop", "Drop", 16, 24, 98, "Euphoric", ["drums", "bass", "chords", "arp", "impact"]),
      demoSection(3, "breakdown", "Breakdown", 40, 12, 42, "Dreamy", ["chords", "arp", "fx"]),
      demoSection(4, "drop", "Drop 2", 52, 24, 100, "Euphoric", ["drums", "bass", "chords", "arp", "impact"]),
      demoSection(5, "outro", "Outro", 76, 16, 32, "Introspective", ["chords", "arp"]),
    ],
  };
  selectedSection.value = 2;
}

function demoSection(index: number, role: string, label: string, startBar: number, bars: number, energy: number, mood: string, layers: string[]): DjSection {
  const bar = 60 / 124 * 4;
  return { id: `demo-sec-${index}`, index, role, label, start: startBar * bar, end: (startBar + bars) * bar, bars, energy, mood, filter_hz: 900 + energy * 150, layers, prompt: `${label} · ${mood}` };
}

function demoIsMood(index: number) {
  return ["Warm / Uplifting", "Driving / Dark"][index] || "Balanced";
}

function selectStyle(style: DjStyle) {
  create.style = style.style;
  if (!create.bpm) create.bpm = style.bpm || style.preset.bpm;
  if (!create.key) create.key = style.key || style.preset.key;
  create.energy = style.energy || style.preset.energy;
}

async function planStructure() {
  if (DEMO) {
    structure.value = {
      source: "local-planner", style: create.style, bpm: create.bpm || 124, key: create.key || "A minor", duration: create.duration,
      total_bars: Math.round(create.duration / (60 / (create.bpm || 124) * 4)), prompt: create.prompt, energy: create.energy,
      mood: "Balanced", tags: [], sections: [
        demoSection(0, "intro", "Intro", 0, 8, 34, "Dreamy", ["chords", "arp"]),
        demoSection(1, "build", "Build", 8, 8, 62, "Tense / Rising", ["drums", "bass", "chords", "arp", "riser"]),
        demoSection(2, "drop", "Drop", 16, 24, 96, "Euphoric", ["drums", "bass", "chords", "arp", "impact"]),
        demoSection(3, "breakdown", "Breakdown", 40, 12, 40, "Dreamy", ["chords", "arp", "fx"]),
        demoSection(4, "drop", "Drop 2", 52, 24, 100, "Euphoric", ["drums", "bass", "chords", "arp", "impact"]),
        demoSection(5, "outro", "Outro", 76, 16, 30, "Introspective", ["chords", "arp"]),
      ],
    };
    selectedSection.value = 2;
    recalcStructure();
    toasts.info("Demo arrangement planned");
    return;
  }
  structureLoading.value = true;
  try {
    const plan = await api.post<DjStructure>("/dj/structure", {
      style: create.style,
      duration: create.duration,
      prompt: create.prompt,
      energy: create.energy,
      bpm: create.bpm || 0,
      key: create.key,
      seed: create.seed,
      use_llm: create.use_llm,
    });
    structure.value = plan;
    selectedSection.value = 0;
    toasts.success(`Arrangement planned · ${plan.sections.length} sections`);
  } catch (err: any) {
    toasts.error(err?.message || "Could not plan the arrangement");
  } finally {
    structureLoading.value = false;
  }
}

function recalcStructure() {
  if (!structure.value) return;
  const bpm = structure.value.bpm || create.bpm || 120;
  const bar = (60 / bpm) * 4;
  let cursor = 0;
  structure.value.sections.forEach((section, index) => {
    section.index = index;
    section.bars = Math.max(1, Math.round(Number(section.bars) || 1));
    section.start = Number(cursor.toFixed(3));
    section.end = Number((cursor + section.bars * bar).toFixed(3));
    cursor = section.end;
  });
  structure.value.duration = Number(cursor.toFixed(3));
  structure.value.total_bars = structure.value.sections.reduce((sum, section) => sum + section.bars, 0);
  selectedSection.value = Math.min(selectedSection.value, Math.max(0, structure.value.sections.length - 1));
}

function addSection() {
  if (!structure.value) {
    void planStructure();
    return;
  }
  const bpm = structure.value.bpm || 120;
  const bars = 8;
  const start = structure.value.sections.length ? structure.value.sections[structure.value.sections.length - 1].end : 0;
  structure.value.sections.push({
    id: `sec-${Date.now()}`, index: structure.value.sections.length, role: "drop", label: "New section",
    start, end: start + bars * (60 / bpm) * 4, bars, energy: 80, mood: "Euphoric",
    filter_hz: 12000, layers: ["drums", "bass", "chords", "arp"], prompt: "new section",
  });
  selectedSection.value = structure.value.sections.length - 1;
  recalcStructure();
}

function removeSection(index: number) {
  if (!structure.value) return;
  structure.value.sections.splice(index, 1);
  recalcStructure();
}

function moveSection(index: number, direction: number) {
  if (!structure.value) return;
  const target = index + direction;
  if (target < 0 || target >= structure.value.sections.length) return;
  const [section] = structure.value.sections.splice(index, 1);
  structure.value.sections.splice(target, 0, section);
  recalcStructure();
  selectedSection.value = target;
}

function toggleLayer(section: DjSection, layer: string) {
  const index = section.layers.indexOf(layer);
  if (index >= 0) section.layers.splice(index, 1);
  else section.layers.push(layer);
}

async function generateTrack() {
  if (!structure.value) {
    await planStructure();
    if (!structure.value) return;
  }
  generating.value = true;
  try {
    if (DEMO) {
      generations.value.unshift({
        id: `demo-gen-${Date.now()}`, style: create.style, title: create.title || `${create.style} sketch`,
        prompt: create.prompt, path: "dj/generated/demo/track.wav", duration: structure.value.duration, bpm: structure.value.bpm,
        key: structure.value.key, seed: Date.now() % 1000000, status: "completed", error: "", created_at: new Date().toISOString(),
      });
      toasts.success("Demo track generated");
      return;
    }
    const response = await api.post<{ generation: DjGeneration; job: Job }>("/dj/generations", {
      style: create.style,
      title: create.title || `${create.style} sketch`,
      prompt: create.prompt,
      duration: structure.value.duration,
      energy: create.energy,
      bpm: structure.value.bpm || create.bpm,
      key: structure.value.key || create.key,
      seed: create.seed,
      use_llm: create.use_llm,
      structure: structure.value.sections,
    });
    rememberJob(response.job);
    toasts.info("Generation queued — follow the job above");
  } catch (err: any) {
    toasts.error(err?.message || "Could not generate the track");
  } finally {
    generating.value = false;
  }
}

function handleFiles(event: Event) {
  const input = event.target as HTMLInputElement;
  if (input.files) void uploadFiles(Array.from(input.files));
  input.value = "";
}

function onDrop(event: DragEvent) {
  dragActive.value = false;
  if (event.dataTransfer?.files) void uploadFiles(Array.from(event.dataTransfer.files));
}

async function uploadFiles(files: File[]) {
  const audioFiles = files.filter((file) => file.type.startsWith("audio/") || /\.(wav|mp3|flac|m4a|aac|ogg|opus|aiff|aif|wma|webm)$/i.test(file.name));
  if (!audioFiles.length) {
    toasts.error("Choose audio files (WAV, MP3, FLAC, M4A, OGG or OPUS).");
    return;
  }
  uploading.value = true;
  uploadProgress.value = 0;
  try {
    for (const [index, file] of audioFiles.entries()) {
      const response = await uploadOne(file, (percent) => {
        uploadProgress.value = Math.round(((index + percent / 100) / audioFiles.length) * 100);
      });
      if (response?.track) tracks.value.unshift(response.track);
      rememberJob(response?.job);
      if (response?.warning) toasts.info(response.warning);
    }
    toasts.success(`${audioFiles.length} track${audioFiles.length > 1 ? "s" : ""} uploaded — analysis is running`);
    await loadAll(true);
  } catch (err: any) {
    toasts.error(err?.message || "Upload failed");
  } finally {
    uploading.value = false;
    uploadProgress.value = 0;
  }
}

function uploadOne(file: File, onProgress: (percent: number) => void): Promise<any> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    form.append("title", file.name.replace(/\.[^.]+$/, ""));
    form.append("analyze", "true");
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/dj/tracks`);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          resolve({});
        }
      } else {
        let message = `Upload failed (${xhr.status})`;
        try {
          const parsed = JSON.parse(xhr.responseText);
          message = parsed.detail || message;
        } catch {}
        reject(new Error(message));
      }
    };
    xhr.onerror = () => reject(new Error("Network error while uploading"));
    xhr.send(form);
  });
}

async function analyzeAll() {
  try {
    if (DEMO) {
      tracks.value.forEach((track) => {
        track.analyzed = true;
        track.status = "analyzed";
      });
      toasts.info("Demo analysis refreshed");
      return;
    }
    const response = await api.post<{ jobs: Job[]; count: number; errors: any[] }>("/dj/tracks/analyze-all");
    if (response.jobs?.length) rememberJob(response.jobs[0]);
    toasts.info(`${response.count} track(s) queued for scene analysis`);
  } catch (err: any) {
    toasts.error(err?.message || "Could not queue analysis");
  }
}

async function analyzeTrack(track: DjTrack) {
  try {
    if (DEMO) {
      track.analyzed = true;
      track.status = "analyzed";
      toasts.info("Demo analysis complete");
      return;
    }
    const response = await api.post<{ job: Job; track: DjTrack }>(`/dj/tracks/${track.id}/analyze`);
    const index = tracks.value.findIndex((item) => item.id === track.id);
    if (index >= 0) tracks.value[index] = response.track;
    rememberJob(response.job);
    toasts.info("Analysis queued");
  } catch (err: any) {
    toasts.error(err?.message || "Could not queue analysis");
  }
}

function openEdit(track: DjTrack) {
  editTarget.value = track;
  editForm.title = track.title;
  editForm.artist = track.artist;
  editForm.style = track.style;
  editForm.mood = track.mood;
  editForm.notes = track.notes || "";
  editForm.tags = (track.tags || []).join(", ");
  editOpen.value = true;
}

async function saveEdit() {
  if (!editTarget.value) return;
  try {
    const tags = editForm.tags.split(",").map((tag) => tag.trim()).filter(Boolean);
    const updated = await api.patch<DjTrack>(`/dj/tracks/${editTarget.value.id}`, {
      title: editForm.title,
      artist: editForm.artist,
      style: editForm.style,
      mood: editForm.mood,
      notes: editForm.notes,
      tags,
    });
    const index = tracks.value.findIndex((item) => item.id === updated.id);
    if (index >= 0) tracks.value[index] = updated;
    editOpen.value = false;
    toasts.success("Track updated");
  } catch (err: any) {
    toasts.error(err?.message || "Could not update the track");
  }
}

async function deleteTrack(track: DjTrack) {
  if (!window.confirm(`Delete “${track.title}”? The uploaded audio will be removed.`)) return;
  try {
    if (!DEMO) await api.delete(`/dj/tracks/${track.id}`);
    tracks.value = tracks.value.filter((item) => item.id !== track.id);
    selectedMixTrackIds.value = selectedMixTrackIds.value.filter((id) => id !== track.id);
    toasts.success("Track deleted");
    await loadAll(true);
  } catch (err: any) {
    toasts.error(err?.message || "Could not delete the track");
  }
}

async function trainStyle(style: DjStyle) {
  try {
    if (DEMO) {
      style.trained = true;
      style.track_count = Math.max(1, style.available_tracks);
      toasts.success(`${style.style} model trained`);
      return;
    }
    const response = await api.post<{ job: Job }>(`/dj/styles/${encodeURIComponent(style.style)}/train`);
    rememberJob(response.job);
    toasts.info(`${style.style}: training queued`);
  } catch (err: any) {
    toasts.error(err?.message || "Could not train the style model");
  }
}

async function resetStyle(style: DjStyle) {
  if (!window.confirm(`Reset the ${style.style} model to its built-in preset?`)) return;
  try {
    if (!DEMO) await api.delete(`/dj/styles/${encodeURIComponent(style.style)}`);
    style.trained = false;
    style.track_count = 0;
    style.updated_at = undefined;
    toasts.success(`${style.style} model reset`);
  } catch (err: any) {
    toasts.error(err?.message || "Could not reset the style model");
  }
}

async function trainAll() {
  try {
    if (DEMO) {
      styles.value.forEach((style) => {
        style.trained = true;
        style.track_count = Math.max(1, style.available_tracks);
      });
      toasts.success("Demo style models trained");
      return;
    }
    const response = await api.post<{ jobs: any[] }>("/dj/styles/train-all");
    const first = response.jobs?.find((job) => job.id);
    rememberJob(first);
    toasts.info(`${response.jobs?.length || 0} style model(s) queued`);
  } catch (err: any) {
    toasts.error(err?.message || "Could not train style models");
  }
}

async function createMix() {
  try {
    if (DEMO) {
      const demo = mixes.value[0];
      if (demo) await selectMix(demo.id);
      return;
    }
    const mix = await api.post<DjMix>("/dj/mixes", {
      title: mixTitle.value || "Untitled mix",
      prompt: mixPrompt.value,
    });
    mixes.value.unshift(mix);
    mixTitle.value = "";
    await selectMix(mix.id);
    toasts.success("Mix created");
  } catch (err: any) {
    toasts.error(err?.message || "Could not create the mix");
  }
}

async function selectMix(mixId: string) {
  try {
    if (DEMO) {
      const found = mixes.value.find((item) => item.id === mixId);
      if (found) {
        activeMix.value = found;
        scene.value = normalizeScene(found.scene);
        selectedMixTrackIds.value = sceneTrackIds(scene.value?.tracks);
      }
      return;
    }
    const mix = await api.get<DjMix>(`/dj/mixes/${mixId}`);
    activeMix.value = mix;
    scene.value = normalizeScene(mix.scene);
    selectedMixTrackIds.value = sceneTrackIds(scene.value?.tracks);
  } catch (err: any) {
    toasts.error(err?.message || "Could not load the mix");
  }
}

async function deleteMix(mix: DjMix) {
  if (!window.confirm(`Delete “${mix.title}”?`)) return;
  try {
    if (!DEMO) await api.delete(`/dj/mixes/${mix.id}`);
    mixes.value = mixes.value.filter((item) => item.id !== mix.id);
    if (activeMix.value?.id === mix.id) {
      activeMix.value = null;
      scene.value = null;
    }
    toasts.success("Mix deleted");
  } catch (err: any) {
    toasts.error(err?.message || "Could not delete the mix");
  }
}

function toggleMixTrack(track: { id: string }) {
  const index = selectedMixTrackIds.value.indexOf(track.id);
  if (index >= 0) selectedMixTrackIds.value.splice(index, 1);
  else selectedMixTrackIds.value.push(track.id);
}

function mixItemTitle(id: string) {
  const track = tracks.value.find((item) => item.id === id);
  if (track) return track.title;
  const generation = generations.value.find((item) => item.id === id);
  return generation ? `AI · ${generation.title}` : id;
}

function moveSelectedTrack(index: number, direction: number) {
  const target = index + direction;
  if (target < 0 || target >= selectedMixTrackIds.value.length) return;
  const [id] = selectedMixTrackIds.value.splice(index, 1);
  selectedMixTrackIds.value.splice(target, 0, id);
}

async function generateScene() {
  if (!activeMix.value) return;
  sceneLoading.value = true;
  try {
    if (DEMO) {
      scene.value = normalizeScene(activeMix.value.scene) || scene.value;
      toasts.success("Demo scene planned");
      return;
    }
    const response = await api.post<{ mix: DjMix; scene: DjScene }>(`/dj/mixes/${activeMix.value.id}/scene`, {
      prompt: activeMix.value.prompt || mixPrompt.value,
      master_bpm: sceneMasterBpm.value || 0,
      transition_beats: sceneTransitionBeats.value,
      keep_order: sceneKeepOrder.value,
      use_sections: sceneUseSections.value,
      segments: Math.max(1, Math.min(64, Number(sceneSegments.value) || 1)),
      target_duration: Math.max(10, Number(sceneDurationMinutes.value || 6) * 60),
      track_ids: selectedMixTrackIds.value,
    });
    activeMix.value = response.mix;
    const normalized = normalizeScene(response.scene);
    scene.value = normalized;
    selectedMixTrackIds.value = sceneTrackIds(normalized?.tracks);
    const index = mixes.value.findIndex((item) => item.id === response.mix.id);
    if (index >= 0) mixes.value[index] = response.mix;
    toasts.success("AI mix scene ready");
  } catch (err: any) {
    toasts.error(err?.message || "Could not create the mix scene");
  } finally {
    sceneLoading.value = false;
  }
}

async function saveScene(): Promise<boolean> {
  if (!activeMix.value || !scene.value) return false;
  sceneSaving.value = true;
  try {
    if (DEMO) {
      activeMix.value.scene = scene.value;
      return true;
    }
    const updated = await api.patch<DjMix>(`/dj/mixes/${activeMix.value.id}`, {
      title: activeMix.value.title,
      prompt: activeMix.value.prompt,
      scene: scene.value,
    });
    activeMix.value = updated;
    const index = mixes.value.findIndex((item) => item.id === updated.id);
    if (index >= 0) mixes.value[index] = updated;
    toasts.success("Scene saved");
    return true;
  } catch (err: any) {
    toasts.error(err?.message || "Could not save the scene");
    return false;
  } finally {
    sceneSaving.value = false;
  }
}

async function renderMix() {
  if (!activeMix.value) return;
  mixRendering.value = true;
  try {
    const saved = await saveScene();
    if (!saved) return;
    if (DEMO) {
      activeMix.value.status = "completed";
      activeMix.value.path = "dj/mixes/demo/mix.wav";
      toasts.success("Demo mix rendered");
      return;
    }
    const response = await api.post<{ job: Job; mix: DjMix }>(`/dj/mixes/${activeMix.value.id}/render`);
    rememberJob(response.job);
    toasts.info("Mix render queued");
  } catch (err: any) {
    toasts.error(err?.message || "Could not render the mix");
  } finally {
    mixRendering.value = false;
  }
}

function sceneDuration(track: DjSceneTrack) {
  return Math.max(0.1, Number(track.timeline_duration || track.out - track.in || 1));
}

function recalcSceneTimeline() {
  if (!scene.value) return;
  const beat = scene.value.beat_seconds || 60 / Math.max(1, scene.value.master_bpm || 120);
  let cursor = 0;
  scene.value.tracks.forEach((track, index) => {
    track.timeline_duration = Math.max(0.1, Number(track.out) - Number(track.in) || 1);
    if (index === 0) {
      track.start = 0;
    } else {
      const previous = scene.value!.tracks[index - 1];
      const overlap = Math.min(
        (Number(previous.transition?.beats) || 16) * beat,
        sceneDuration(previous) * 0.72,
        sceneDuration(track) * 0.72,
      );
      track.start = Math.max(0, cursor - overlap);
    }
    cursor = track.start + sceneDuration(track);
  });
  scene.value.duration = Number((cursor + 1.5).toFixed(3));
}

function addEffectFromEvent(index: number, event: Event) {
  const select = event.target as HTMLSelectElement;
  addEffect(index, select.value);
  select.value = "";
}

function addEffect(index: number, presetId: string) {
  if (!scene.value || !presetId) return;
  const preset = effects.value.find((item) => item.id === presetId);
  if (!preset) return;
  const track = scene.value.tracks[index];
  const duration = sceneDuration(track);
  const effect: Record<string, any> = { type: preset.id, ...preset.defaults };
  effect.start = 0;
  effect.end = Math.min(duration, Math.max(4, duration * 0.25));
  track.effects = track.effects || [];
  track.effects.push(effect);
}

function applyEmotion(index: number, emotion: DjEmotion) {
  if (!scene.value) return;
  const track = scene.value.tracks[index];
  const duration = sceneDuration(track);
  track.effects = track.effects || [];
  for (const effect of emotion.effects) {
    track.effects.push({
      ...effect,
      start: Math.max(0, duration * 0.55),
      end: duration,
    });
  }
  toasts.info(`${emotion.label} applied to ${track.title}`);
}

function removeEffect(trackIndex: number, effectIndex: number) {
  scene.value?.tracks[trackIndex]?.effects.splice(effectIndex, 1);
}

async function deleteGeneration(generation: DjGeneration) {
  if (!window.confirm(`Delete “${generation.title}”?`)) return;
  try {
    if (!DEMO) await api.delete(`/dj/generations/${generation.id}`);
    generations.value = generations.value.filter((item) => item.id !== generation.id);
    toasts.success("Generation deleted");
  } catch (err: any) {
    toasts.error(err?.message || "Could not delete the generation");
  }
}

function rememberJob(job?: Job | null) {
  if (!job?.id) return;
  activeJobId.value = job.id;
  jobs.upsert(job);
}

async function refreshAfterJob() {
  await loadAll(true);
  if (activeMix.value && tab.value === "mix") await selectMix(activeMix.value.id);
}

watch(
  () => activeJob.value?.status,
  (status) => {
    if (!status) return;
    if (["completed", "failed", "canceled"].includes(status)) {
      window.setTimeout(refreshAfterJob, 600);
    }
  },
);

watch(
  () => activeDjJobs.value.length,
  (count, previous) => {
    if (count > 0 && pollTimer.value === undefined) {
      pollTimer.value = window.setInterval(() => void loadAll(true), 3500);
    }
    if (count === 0 && previous > 0) {
      if (pollTimer.value !== undefined) window.clearInterval(pollTimer.value);
      pollTimer.value = undefined;
      window.setTimeout(refreshAfterJob, 500);
    }
  },
);

onMounted(() => {
  void loadAll();
});
onBeforeUnmount(() => {
  if (pollTimer.value !== undefined) window.clearInterval(pollTimer.value);
});
</script>

<template>
  <div class="page dj-page" :class="{ 'dj-embedded': embedded }">
    <PageHeader
      v-if="!embedded"
      eyebrow="DJ Studio"
      title="DJ Studio"
      subtitle="Upload and analyse records, train a generative model for every style, edit AI arrangements, then build a beat-matched mix scene with transitions and emotion-changing effects."
    >
      <template #actions>
        <span class="chip" :class="{ success: djService?.online || DEMO }">
          <span class="dot" :class="djService?.online || DEMO ? 'online' : 'offline'" />
          {{ DEMO ? "demo" : djService?.online ? "online" : "offline" }}
        </span>
        <button class="btn btn-sm" :disabled="loading" @click="loadAll()">
          <RefreshCw :size="13" :class="{ spin: loading }" /> Refresh
        </button>
      </template>
    </PageHeader>

    <div v-if="error" class="alert error" style="margin-bottom: 16px">{{ error }}</div>
    <div v-if="!DEMO && system.status && !djService?.online" class="alert warn" style="margin-bottom: 16px">
      DJ Studio is not running. Enable <strong>DJ Studio</strong> in <RouterLink to="/settings">Settings → Services</RouterLink>.
    </div>

    <TabsBar v-if="!embedded" v-model="tab" :tabs="tabs" />

    <div v-if="activeJob" class="panel dj-job">
      <div class="panel-body stack" style="gap: 8px">
        <div class="row-between">
          <span class="small strong">{{ activeJob.title }}</span>
          <span class="badge" :class="activeJob.status === 'failed' ? 'failed' : activeJob.status">{{ activeJob.status }}</span>
        </div>
        <div class="small muted">{{ activeJob.stage }} — {{ activeJob.message }}</div>
        <ProgressBar :value="activeJob.progress" show-label />
      </div>
    </div>

    <div class="stat-grid" style="margin: 16px 0">
      <div class="stat"><div class="stat-label">Tracks</div><div class="stat-value">{{ overview.tracks }}</div><div class="stat-sub">{{ overview.analyzed }} analysed</div></div>
      <div class="stat"><div class="stat-label">Style models</div><div class="stat-value">{{ trainedCount }}</div><div class="stat-sub">trained from your library</div></div>
      <div class="stat"><div class="stat-label">Arrangements</div><div class="stat-value">{{ generations.length }}</div><div class="stat-sub">AI generated tracks</div></div>
      <div class="stat"><div class="stat-label">Mix scenes</div><div class="stat-value">{{ mixes.length }}</div><div class="stat-sub">rendered or in progress</div></div>
    </div>

    <div v-if="tab === 'library'" class="stack">
      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Import and analyse</h3>
            <p>Drop records here. Analysis extracts BPM, key, style, mood, energy, structure and a waveform.</p>
          </div>
          <span class="chip">up to {{ overview.max_upload_mb }} MB each</span>
        </div>
        <div class="panel-body">
          <div class="dj-upload" :class="{ active: dragActive }" @dragover.prevent="dragActive = true" @dragleave.prevent="dragActive = false" @drop.prevent="onDrop" @click="fileInput?.click()">
            <input ref="fileInput" type="file" accept="audio/*,.wav,.mp3,.flac,.m4a,.aac,.ogg,.opus,.aiff,.aif" multiple hidden @change="handleFiles" />
            <div class="dj-upload-icon"><Upload :size="22" /></div>
            <div>
              <div class="strong">{{ uploading ? `Uploading ${uploadProgress}%` : "Drop audio files or click to browse" }}</div>
              <div class="small muted" style="margin-top: 4px">WAV, MP3, FLAC, M4A, OGG, OPUS · analysis starts automatically</div>
            </div>
            <Loader2 v-if="uploading" :size="18" class="spin" />
            <Upload v-else :size="18" class="muted" />
          </div>
          <ProgressBar v-if="uploading" :value="uploadProgress" thin style="margin-top: 10px" />
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div><h3>Library</h3><p>{{ filteredTracks.length }} of {{ tracks.length }} tracks shown.</p></div>
          <div class="row" style="gap: 7px">
            <input v-model="trackQuery" class="input input-sm" placeholder="Search title, artist, tag…" style="width: 220px" />
            <select v-model="trackStyleFilter" class="select input-sm" style="width: 150px">
              <option value="">All styles</option>
              <option v-for="style in styles" :key="style.style" :value="style.style">{{ style.style }}</option>
            </select>
            <button class="btn btn-sm" :disabled="!tracks.length" @click="analyzeAll"><AudioLines :size="12" /> Analyse all</button>
          </div>
        </div>
        <div class="panel-body">
          <div v-if="loading" class="stack"><div v-for="i in 3" :key="i" class="skeleton" style="height: 128px" /></div>
          <EmptyState v-else-if="!filteredTracks.length" :icon="Disc3" title="No tracks yet" message="Upload your first record above. Analysis runs as a normal job, so you can keep working while it finishes." />
          <div v-else class="dj-track-grid">
            <article v-for="track in filteredTracks" :key="track.id" class="dj-track">
              <div class="row-between" style="align-items: flex-start">
                <div style="min-width: 0">
                  <div class="strong truncate">{{ track.title }}</div>
                  <div class="small muted truncate">{{ track.artist || "Unknown artist" }} · {{ formatDuration(track.duration) }} · {{ relativeTime(track.created_at) }}</div>
                </div>
                <span class="badge" :class="track.analyzed ? 'success' : track.status === 'failed' ? 'failed' : 'queued'">{{ track.analyzed ? "analysed" : track.status }}</span>
              </div>
              <div class="row" style="gap: 5px">
                <span v-if="track.bpm" class="chip">{{ track.bpm.toFixed(0) }} BPM</span>
                <span v-if="track.key" class="chip">{{ track.key }}</span>
                <span v-if="track.camelot" class="chip success">{{ track.camelot }}</span>
                <span v-if="track.style" class="chip active">{{ track.style }}</span>
                <span v-if="track.mood" class="chip">{{ track.mood }}</span>
                <span v-if="(track.analysis_version || 0) >= 2 && track.sections?.length" class="chip active">{{ track.sections.length }} scenes</span>
                <span v-else-if="track.analyzed && (track.analysis_version || 0) < 3" class="chip warn">re-analyse for scenes</span>
              </div>
              <div class="row-between energy-row">
                <span class="small muted">Energy</span>
                <div class="energy-bar"><span :style="{ width: `${Math.round(track.energy * 100)}%` }" /></div>
                <span class="small mono">{{ Math.round(track.energy * 100) }}%</span>
              </div>
              <div class="row split-actions">
                <SectionPlayer v-if="track.path" :ref="(element) => setTrackPlayer(track.id, element)" compact :src="track.path" :bars="64" :waveform="track.waveform" :sections="track.sections" :duration="track.duration" style="flex: 1" />
              </div>
              <div v-if="track.error" class="alert error small" style="padding: 6px 8px">{{ track.error }}</div>
              <div class="row" style="justify-content: flex-end; gap: 5px">
                <a class="icon-btn" :href="downloadUrl(track.path)" title="Download"><Download :size="14" /></a>
                <button class="icon-btn" title="Analyse" :disabled="track.status === 'queued' || track.status === 'analyzing'" @click="analyzeTrack(track)"><AudioLines :size="14" /></button>
                <button class="icon-btn" title="Edit" @click="openEdit(track)"><Pencil :size="14" /></button>
                <button class="icon-btn" title="Delete" @click="deleteTrack(track)"><Trash2 :size="14" /></button>
              </div>
            </article>
          </div>
        </div>
      </section>
    </div>

    <div v-if="tab === 'create'" class="dj-create-layout">
      <div class="stack">
        <section class="panel">
          <div class="panel-head">
            <div><h3>Style models</h3><p>Train from analysed records. The model learns tempo, key, spectral balance, swing and the energy arc.</p></div>
            <button class="btn btn-sm" @click="trainAll"><Sparkles :size="12" /> Train all</button>
          </div>
          <div class="panel-body">
            <div class="style-grid">
              <div v-for="style in styles" :key="style.style" class="style-card" :class="{ active: create.style === style.style }" @click="create.style = style.style">
                <div class="row-between">
                  <span class="strong">{{ style.style }}</span>
                  <span class="badge" :class="style.trained ? 'success' : 'queued'">{{ style.trained ? "trained" : "preset" }}</span>
                </div>
                <div class="small muted" style="margin-top: 4px">{{ style.bpm.toFixed(0) }} BPM · {{ style.key || "—" }} · {{ style.available_tracks }} track(s)</div>
                <div class="row" style="gap: 4px; margin-top: 8px">
                  <button class="btn btn-sm" :disabled="!style.available_tracks" @click.stop="trainStyle(style)"><Sparkles :size="11" /> Train</button>
                  <button v-if="style.trained" class="btn btn-sm btn-ghost" @click.stop="resetStyle(style)">Reset</button>
                  <button class="btn btn-sm btn-ghost" @click.stop="selectStyle(style)"><Wand2 :size="11" /> Use</button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div><h3>Prompt</h3><p>Describe the emotion, place and energy. The planner turns it into an editable section map.</p></div></div>
          <div class="panel-body stack">
            <div class="grid grid-2" style="gap: 10px">
              <label class="field"><span class="label">Style</span><select v-model="create.style" class="select"><option v-for="style in styles" :key="style.style" :value="style.style">{{ style.style }}</option></select></label>
              <label class="field"><span class="label">Duration (seconds)</span><input v-model.number="create.duration" type="number" min="20" max="900" class="input" /></label>
            </div>
            <label class="field"><span class="label">Creative brief</span><textarea v-model="create.prompt" class="textarea" rows="3" placeholder="e.g. warm sunset house, rolling bass, female vocal air, euphoric final drop, dark warehouse second half" /></label>
            <div class="grid grid-3" style="gap: 10px">
              <label class="field"><span class="label">BPM (0 = model)</span><input v-model.number="create.bpm" type="number" min="0" max="220" class="input" /></label>
              <label class="field"><span class="label">Key (empty = model)</span><input v-model="create.key" class="input" placeholder="A minor" /></label>
              <label class="field"><span class="label">Seed</span><input v-model.number="create.seed" type="number" class="input" placeholder="random" /></label>
            </div>
            <div class="field">
              <span class="label">Energy · {{ Math.round(create.energy * 100) }}%</span>
              <input v-model.number="create.energy" type="range" min="0.1" max="1" step="0.01" />
            </div>
            <label class="row small muted" style="gap: 7px"><input v-model="create.use_llm" type="checkbox" /> Use the local LLM for the section plan when available</label>
            <div class="row">
              <button class="btn btn-primary" :disabled="structureLoading" @click="planStructure">
                <Loader2 v-if="structureLoading" :size="14" class="spin" /><Wand2 v-else :size="14" />
                {{ structure ? "Re-plan structure" : "Plan structure with AI" }}
              </button>
              <span v-if="structure" class="chip">{{ structure.sections.length }} sections · {{ structure.total_bars }} bars</span>
            </div>
          </div>
        </section>

        <section v-if="structure" class="panel">
          <div class="panel-head">
            <div><h3>Arrangement editor</h3><p>Drag the energy, rename roles, add or remove sections. Every edit is used by the synth.</p></div>
            <button class="btn btn-sm" @click="addSection"><Plus :size="12" /> Section</button>
          </div>
          <div class="panel-body stack">
            <div class="structure-bar">
              <button v-for="(section, index) in structure.sections" :key="section.id" class="structure-block" :class="{ selected: index === selectedSection }" :style="{ width: sectionWidth(section), background: sectionColor(section.role) }" :title="`${section.label} · ${section.bars} bars`" @click="selectedSection = index">
                <span>{{ section.label }}</span>
              </button>
            </div>
            <div class="section-editor" v-if="structure.sections[selectedSection]">
              <div class="row-between">
                <div class="row" style="gap: 6px">
                  <span class="section-dot" :style="{ background: sectionColor(structure.sections[selectedSection].role) }" />
                  <span class="small strong">{{ structure.sections[selectedSection].label }}</span>
                  <span class="chip">{{ structure.sections[selectedSection].bars }} bars</span>
                  <span class="chip">{{ Math.round(structure.sections[selectedSection].energy) }}%</span>
                </div>
                <div class="row" style="gap: 4px">
                  <button class="icon-btn" title="Move earlier" @click="moveSection(selectedSection, -1)"><ArrowUp :size="13" /></button>
                  <button class="icon-btn" title="Move later" @click="moveSection(selectedSection, 1)"><ArrowDown :size="13" /></button>
                  <button class="icon-btn" title="Remove" @click="removeSection(selectedSection)"><Trash2 :size="13" /></button>
                </div>
              </div>
              <div class="grid grid-4" style="gap: 10px; margin-top: 12px">
                <label class="field"><span class="label">Label</span><input v-model="structure.sections[selectedSection].label" class="input input-sm" /></label>
                <label class="field"><span class="label">Role</span>
                  <select v-model="structure.sections[selectedSection].role" class="select input-sm">
                    <option v-for="role in ['intro','build','drop','chorus','breakdown','verse','bridge','rise','theme','outro','groove']" :key="role" :value="role">{{ role }}</option>
                  </select>
                </label>
                <label class="field"><span class="label">Bars</span><input v-model.number="structure.sections[selectedSection].bars" type="number" min="1" max="128" class="input input-sm" @change="recalcStructure" /></label>
                <label class="field"><span class="label">Mood</span><input v-model="structure.sections[selectedSection].mood" class="input input-sm" /></label>
              </div>
              <div class="field" style="margin-top: 10px">
                <span class="label">Energy · {{ Math.round(structure.sections[selectedSection].energy) }}%</span>
                <input v-model.number="structure.sections[selectedSection].energy" type="range" min="5" max="100" step="1" />
              </div>
              <div class="row" style="gap: 5px; margin-top: 10px">
                <button v-for="layer in ['drums','bass','chords','arp','fx','riser','impact']" :key="layer" class="chip clickable" :class="{ active: structure.sections[selectedSection].layers.includes(layer) }" @click="toggleLayer(structure.sections[selectedSection], layer)">{{ layer }}</button>
              </div>
              <label class="field" style="margin-top: 10px"><span class="label">Section instruction</span><textarea v-model="structure.sections[selectedSection].prompt" class="textarea" rows="2" /></label>
            </div>
            <div class="small muted">Tip: use <strong>Build</strong> with a riser before a <strong>Drop</strong>, and a <strong>Breakdown</strong> without kick to make the next drop feel larger.</div>
          </div>
        </section>
      </div>

      <aside class="stack">
        <section class="panel">
          <div class="panel-head"><div><h3>Generate</h3><p>Render the edited structure with the selected style model.</p></div></div>
          <div class="panel-body stack">
            <label class="field"><span class="label">Track title</span><input v-model="create.title" class="input" placeholder="e.g. Nocturno" /></label>
            <div class="mini-summary">
              <span>{{ create.style }}</span><span>{{ structure?.bpm || create.bpm || selectedStyle?.bpm || 120 }} BPM</span><span>{{ structure?.key || create.key || selectedStyle?.key || "model key" }}</span>
            </div>
            <button class="btn btn-primary btn-block" :disabled="generating || structureLoading || !structure" @click="generateTrack">
              <Loader2 v-if="generating" :size="14" class="spin" /><Zap v-else :size="14" /> Generate track
            </button>
            <div class="small muted">Generation is a normal job. You can keep editing the structure or switch tabs while it renders.</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div><h3>Recent generations</h3><p>Play, download or remove generated arrangements.</p></div></div>
          <div class="panel-body stack" style="gap: 10px">
            <EmptyState v-if="!generations.length" :icon="AudioLines" title="No generations yet" message="Plan a structure and press Generate track." compact />
            <div v-for="generation in generations.slice(0, 5)" :key="generation.id" class="generation-card">
              <div class="row-between">
                <div style="min-width: 0">
                  <div class="strong truncate">{{ generation.title }}</div>
                  <div class="small muted">{{ generation.style }} · {{ generation.bpm?.toFixed(0) }} BPM · {{ generation.key }} · seed {{ generation.seed }}</div>
                </div>
                <span class="badge" :class="generation.status === 'completed' ? 'success' : generation.status === 'failed' ? 'failed' : 'running'">{{ generation.status }}</span>
              </div>
              <AudioPlayer v-if="generation.path" compact :src="generation.path" :title="generation.title" :subtitle="`${formatDuration(generation.duration)} · ${generation.prompt}`" :download-path="generation.path" :bars="56" style="margin-top: 8px" />
              <div class="row" style="justify-content: flex-end">
                <a v-if="generation.path" class="icon-btn" :href="downloadUrl(generation.path)" title="Download"><Download :size="13" /></a>
                <button class="icon-btn" title="Delete" @click="deleteGeneration(generation)"><Trash2 :size="13" /></button>
              </div>
              <div v-if="generation.error" class="alert error small">{{ generation.error }}</div>
            </div>
          </div>
        </section>
      </aside>
    </div>

    <div v-if="tab === 'mix'" class="dj-mix-layout">
      <aside class="stack">
        <section class="panel">
          <div class="panel-head"><div><h3>Mix scenes</h3><p>Build a set from analysed tracks.</p></div></div>
          <div class="panel-body stack" style="gap: 10px">
            <label class="field"><span class="label">New mix</span><input v-model="mixTitle" class="input input-sm" placeholder="Night drive" /></label>
            <button class="btn btn-primary btn-sm" @click="createMix"><Plus :size="12" /> Create mix</button>
            <div class="mix-list">
              <button v-for="mix in mixes" :key="mix.id" class="mix-list-item" :class="{ active: activeMix?.id === mix.id }" @click="selectMix(mix.id)">
                <span class="grow" style="text-align: left">
                  <span class="strong small" style="display: block">{{ mix.title }}</span>
                  <span class="small muted">{{ mix.track_count }} segments · {{ mix.master_bpm || "—" }} BPM · {{ mix.status }}</span>
                </span>
                <span class="badge" :class="mix.status === 'completed' ? 'success' : mix.status === 'failed' ? 'failed' : 'queued'">{{ mix.status }}</span>
              </button>
            </div>
            <EmptyState v-if="!mixes.length" :icon="ListMusic" title="No mixes" message="Create your first scene." compact />
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div><h3>Effects library</h3><p>Use these to change emotion between sections.</p></div></div>
          <div class="panel-body stack" style="gap: 7px">
            <div v-for="effect in effects" :key="effect.id" class="effect-preset">
              <div><span class="strong small">{{ effect.label }}</span><span class="small muted" style="display: block">{{ effect.description }}</span></div>
            </div>
          </div>
        </section>
      </aside>

      <div class="stack">
        <section v-if="!activeMix" class="panel">
          <div class="panel-body">
            <EmptyState :icon="Disc3" title="Create a mix scene" message="Create a mix on the left, pick analysed tracks, then let the AI planner match tempo, choose in/out points and build transitions and effects." />
          </div>
        </section>

        <template v-else>
          <section class="panel">
            <div class="panel-head">
              <div><h3>{{ activeMix.title }}</h3><p>{{ activeMix.status }} · {{ scene?.tracks?.length || activeMix.track_count }} segments · master {{ scene?.master_bpm || activeMix.master_bpm || "—" }} BPM</p></div>
              <div class="row" style="gap: 6px">
                <button class="btn btn-sm" :disabled="sceneSaving" @click="saveScene"><Save :size="12" /> Save</button>
                <button class="btn btn-sm btn-primary" :disabled="mixRendering || !scene" @click="renderMix"><Loader2 v-if="mixRendering" :size="12" class="spin" /><Zap v-else :size="12" /> Render mix</button>
                <button class="icon-btn" title="Delete mix" @click="deleteMix(activeMix)"><Trash2 :size="13" /></button>
              </div>
            </div>
            <div class="panel-body stack">
              <div class="grid grid-2" style="gap: 10px">
                <label class="field"><span class="label">Title</span><input v-model="activeMix.title" class="input input-sm" /></label>
                <label class="field"><span class="label">Brief</span><input v-model="activeMix.prompt" class="input input-sm" placeholder="e.g. euphoric peak time, dark second half" /></label>
              </div>
              <AudioPlayer v-if="activeMix.path" :src="activeMix.path" :title="activeMix.title" :subtitle="`${formatDuration(activeMix.duration)} · rendered mix`" :download-path="activeMix.path" :bars="110" />
            </div>
          </section>

          <section v-if="!scene" class="panel">
            <div class="panel-body">
              <div class="alert">This draft has no scene yet. Select tracks below, then press <strong>AI mix scene</strong> to build the timeline, transitions and effect rack.</div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head"><div><h3>1. Select tracks</h3><p>Choose analysed records. The order here is the order sent to the scene planner.</p></div><span class="chip">{{ selectedMixTrackIds.length }} selected</span></div>
            <div class="panel-body stack">
              <EmptyState v-if="!analyzedTracks.length && !mixableGenerations.length" :icon="Disc3" title="No mixable tracks yet" message="Upload and analyse a track in the Library tab, or generate an arrangement in Create. Both become available here." compact />
              <div v-if="analyzedTracks.length" class="small muted">Analysed library</div>
              <div class="track-picker">
                <button v-for="track in analyzedTracks" :key="track.id" class="pick-chip" :class="{ active: selectedMixTrackIds.includes(track.id) }" @click="toggleMixTrack(track)">
                  <Check v-if="selectedMixTrackIds.includes(track.id)" :size="11" />
                  <Disc3 v-else :size="11" />
                  {{ track.title }}
                  <span class="small muted">{{ track.bpm.toFixed(0) }}</span>
                </button>
              </div>
              <div v-if="mixableGenerations.length" class="small muted">Generated in the Create tab</div>
              <div v-if="mixableGenerations.length" class="track-picker">
                <button v-for="generation in mixableGenerations" :key="generation.id" class="pick-chip" :class="{ active: selectedMixTrackIds.includes(generation.id) }" @click="toggleMixTrack(generation)">
                  <Check v-if="selectedMixTrackIds.includes(generation.id)" :size="11" />
                  <Sparkles v-else :size="11" />
                  AI · {{ generation.title }}
                  <span class="small muted">{{ generation.bpm.toFixed(0) }}</span>
                </button>
              </div>
              <div class="selected-order" v-if="selectedMixTrackIds.length">
                <div v-for="(id, index) in selectedMixTrackIds" :key="id" class="selected-order-item">
                  <span class="chip">{{ index + 1 }}</span>
                  <span class="grow small">{{ mixItemTitle(id) }}</span>
                  <button class="icon-btn" title="Up" @click="moveSelectedTrack(index, -1)"><ArrowUp :size="12" /></button>
                  <button class="icon-btn" title="Down" @click="moveSelectedTrack(index, 1)"><ArrowDown :size="12" /></button>
                </div>
              </div>
              <div class="row" style="gap: 10px; align-items: flex-end">
                <label class="field" style="width: 150px"><span class="label">Master BPM (0 auto)</span><input v-model.number="sceneMasterBpm" type="number" min="0" max="200" class="input input-sm" /></label>
                <label class="field" style="width: 150px"><span class="label">Transition beats</span><input v-model.number="sceneTransitionBeats" type="number" min="4" max="64" class="input input-sm" /></label>
                <label class="field" style="width: 145px"><span class="label">AI segments</span><input v-model.number="sceneSegments" type="number" min="1" max="64" class="input input-sm" /></label>
                <label class="field" style="width: 160px"><span class="label">Target duration (min)</span><input v-model.number="sceneDurationMinutes" type="number" min="0.25" max="180" step="0.25" class="input input-sm" /></label>
                <label class="row small muted" style="gap: 6px"><input v-model="sceneKeepOrder" type="checkbox" /> Keep order</label>
                <label class="row small muted" style="gap: 6px"><input v-model="sceneUseSections" type="checkbox" /> Mix multiple sections</label>
                <button class="btn btn-primary" :disabled="sceneLoading || !selectedMixTrackIds.length" @click="generateScene">
                  <Loader2 v-if="sceneLoading" :size="13" class="spin" /><Wand2 v-else :size="13" /> AI mix scene
                </button>
              </div>
            </div>
          </section>

          <section v-if="scene" class="panel">
            <div class="panel-head"><div><h3>2. Timeline</h3><p>{{ (scene.notes || []).join(" · ") }}</p></div><span class="chip">{{ formatDuration(scene.duration) }}</span></div>
            <div class="panel-body stack">
              <div class="mix-timeline">
                <div v-for="(track, index) in scene.tracks" :key="`${track.track_id}-${index}`" class="mix-block" :style="{ left: sceneTrackLeft(track), width: sceneTrackWidth(track), background: sceneTrackColor(index) }" :title="`${track.title} · ${track.start.toFixed(1)}s`">
                  <span class="mix-block-title">{{ track.section_label ? `${track.title} · ${track.section_label}` : track.title }}</span>
                  <span class="mix-block-meta">{{ track.bpm.toFixed(0) }} BPM · {{ track.key }}</span>
                </div>
                <div v-for="(track, index) in scene.tracks.slice(0, -1)" :key="`fade-${index}`" class="mix-fade" :style="{ left: `calc(${sceneTrackLeft(scene.tracks[index + 1])} + 2px)`, width: `${Math.max(2, ((track.transition?.beats || 16) * (scene.beat_seconds || 0.5) / Math.max(1, scene.duration)) * 100)}%` }" :title="track.transition?.type || 'transition'" />
              </div>
              <div class="row" style="gap: 8px; flex-wrap: wrap">
                <span v-for="(track, index) in scene.tracks" :key="`legend-${index}`" class="chip"><span class="section-dot" :style="{ background: sceneTrackColor(index) }" />{{ track.title }}<template v-if="track.section_label"> · {{ track.section_label }}</template></span>
              </div>
            </div>
          </section>

          <section v-if="scene" class="panel">
            <div class="panel-head"><div><h3>3. Scene editor</h3><p>Adjust trims, transitions and effects. The renderer beat-matches every segment to the master tempo.</p></div><span class="chip">{{ scene.tracks.length }} segments</span></div>
            <div class="panel-body stack">
              <article v-for="(track, index) in scene.tracks" :key="`editor-${track.track_id}-${index}`" class="scene-track-card">
                <div class="row-between">
                  <div class="row" style="gap: 8px; min-width: 0">
                    <span class="section-dot" :style="{ background: sceneTrackColor(index) }" />
                    <span class="strong">{{ track.title }}</span>
                    <span v-if="track.section_label" class="chip active">{{ track.section_label }}</span>
                    <span class="chip">{{ track.bpm.toFixed(0) }} → {{ scene.master_bpm.toFixed(0) }} BPM</span>
                    <span class="chip">{{ track.key }}</span>
                  </div>
                  <span class="small muted">starts {{ track.start.toFixed(1) }}s · {{ sceneDuration(track).toFixed(1) }}s</span>
                </div>
                <div class="grid grid-4" style="gap: 9px; margin-top: 10px">
                  <label class="field"><span class="label">In (s)</span><input v-model.number="track.in" type="number" min="0" step="0.1" class="input input-sm" @change="recalcSceneTimeline" /></label>
                  <label class="field"><span class="label">Out (s)</span><input v-model.number="track.out" type="number" min="1" step="0.1" class="input input-sm" @change="recalcSceneTimeline" /></label>
                  <label class="field"><span class="label">Transition</span><select v-model="track.transition.type" class="select input-sm"><option v-for="type in transitions" :key="type" :value="type">{{ type }}</option></select></label>
                  <label class="field"><span class="label">Transition beats</span><input v-model.number="track.transition.beats" type="number" min="1" max="64" class="input input-sm" @change="recalcSceneTimeline" /></label>
                </div>
                <div class="row" style="gap: 6px; margin-top: 10px; align-items: flex-end">
                  <label class="field" style="width: 190px"><span class="label">Add effect</span>
                    <select class="select input-sm" @change="addEffectFromEvent(index, $event)">
                      <option value="">Choose effect…</option>
                      <option v-for="effect in effects" :key="effect.id" :value="effect.id">{{ effect.label }}</option>
                    </select>
                  </label>
                  <div class="row" style="gap: 5px">
                    <button v-for="emotion in emotions" :key="emotion.id" class="chip clickable" :title="emotion.note" @click="applyEmotion(index, emotion)">{{ emotion.label }}</button>
                  </div>
                </div>
                <div v-if="track.effects.length" class="effect-rack">
                  <div v-for="(effect, effectIndex) in track.effects" :key="effectIndex" class="effect-row">
                    <span class="chip active">{{ effect.type }}</span>
                    <label class="effect-num"><span>start</span><input v-model.number="effect.start" type="number" min="0" step="0.5" class="input input-sm" /></label>
                    <label class="effect-num"><span>end</span><input v-model.number="effect.end" type="number" min="0" step="0.5" class="input input-sm" /></label>
                    <label v-if="effect.amount !== undefined" class="effect-num grow"><span>amount {{ Math.round(effect.amount * 100) }}%</span><input v-model.number="effect.amount" type="range" min="0" max="1" step="0.01" /></label>
                    <label v-if="effect.cutoff !== undefined" class="effect-num"><span>cutoff</span><input v-model.number="effect.cutoff" type="number" min="40" max="20000" step="50" class="input input-sm" /></label>
                    <label v-if="effect.from_hz !== undefined" class="effect-num"><span>from Hz</span><input v-model.number="effect.from_hz" type="number" min="25" max="22000" step="100" class="input input-sm" /></label>
                    <label v-if="effect.to_hz !== undefined" class="effect-num"><span>to Hz</span><input v-model.number="effect.to_hz" type="number" min="25" max="22000" step="100" class="input input-sm" /></label>
                    <label v-if="effect.mode" class="effect-num"><span>mode</span><select v-model="effect.mode" class="select input-sm" style="width: 96px"><option value="lowpass">lowpass</option><option value="highpass">highpass</option></select></label>
                    <button class="icon-btn" title="Remove effect" @click="removeEffect(index, effectIndex)"><X :size="12" /></button>
                  </div>
                </div>
              </article>
              <div class="small muted">{{ (scene.notes || []).join(" ") }}</div>
            </div>
          </section>
        </template>
      </div>
    </div>

    <section v-if="djJobs.length" class="panel" style="margin-top: 18px">
      <div class="panel-head"><div><h3>DJ operations</h3><p>Analysis, training, generation and mix renders use the global job queue.</p></div><RouterLink class="btn btn-sm" to="/jobs">Open job center</RouterLink></div>
      <div class="panel-body stack" style="gap: 8px">
        <div v-for="job in djJobs" :key="job.id" class="row-between">
          <span class="small strong">{{ job.title }}</span>
          <span class="badge" :class="job.status === 'failed' ? 'failed' : job.status === 'completed' ? 'success' : 'running'">{{ job.status }}</span>
          <span class="small muted grow truncate">{{ job.stage }} — {{ job.message }}</span>
          <span class="small mono">{{ Math.round(job.progress) }}%</span>
        </div>
      </div>
    </section>

    <BaseModal v-model="editOpen" title="Edit track" subtitle="Correct the style, add a note or rename the record." width="narrow">
      <div class="stack" style="gap: 10px">
        <label class="field"><span class="label">Title</span><input v-model="editForm.title" class="input" /></label>
        <label class="field"><span class="label">Artist</span><input v-model="editForm.artist" class="input" /></label>
        <div class="grid grid-2" style="gap: 10px">
          <label class="field"><span class="label">Style</span><select v-model="editForm.style" class="select"><option v-for="style in styles" :key="style.style" :value="style.style">{{ style.style }}</option></select></label>
          <label class="field"><span class="label">Mood</span><input v-model="editForm.mood" class="input" /></label>
        </div>
        <label class="field"><span class="label">Tags (comma separated)</span><input v-model="editForm.tags" class="input" /></label>
        <label class="field"><span class="label">Notes</span><textarea v-model="editForm.notes" class="textarea" rows="3" /></label>
      </div>
      <template #footer>
        <button class="btn" @click="editOpen = false">Cancel</button>
        <button class="btn btn-primary" @click="saveEdit"><Save :size="13" /> Save track</button>
      </template>
    </BaseModal>
  </div>
</template>

<style scoped>
.dj-page { --dj-purple: #a78bfa; --dj-cyan: #22d3ee; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.dj-job { margin-top: 14px; border-color: rgba(139, 92, 246, 0.28); }
.dj-upload { display: flex; align-items: center; gap: 14px; padding: 22px; border: 1px dashed var(--line-strong); border-radius: 14px; background: rgba(139, 92, 246, 0.03); cursor: pointer; transition: border-color 160ms, background 160ms; }
.dj-upload:hover, .dj-upload.active { border-color: rgba(139, 92, 246, 0.65); background: rgba(139, 92, 246, 0.08); }
.dj-upload-icon { width: 42px; height: 42px; display: grid; place-items: center; border-radius: 12px; background: linear-gradient(135deg, rgba(139, 92, 246, 0.26), rgba(34, 211, 238, 0.16)); border: 1px solid rgba(139, 92, 246, 0.35); color: #ddd6fe; }
.dj-track-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.dj-track { display: flex; flex-direction: column; gap: 9px; padding: 14px; border: 1px solid var(--line); border-radius: 13px; background: rgba(17, 21, 30, 0.7); }
.dj-track:hover { border-color: var(--line-strong); }
.scene-strip { display: flex; height: 24px; gap: 2px; border-radius: 7px; overflow: hidden; background: rgba(8, 10, 15, 0.65); padding: 2px; }
.scene-block { display: flex; align-items: center; justify-content: center; min-width: 0; padding: 0 3px; border: 0; border-radius: 4px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; color: #070a10; font-size: 8px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.02em; opacity: 0.9; cursor: pointer; }
.scene-block:hover { opacity: 1; }
.energy-row { gap: 8px; }
.energy-bar { flex: 1; height: 5px; border-radius: 999px; overflow: hidden; background: var(--line); }
.energy-bar span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--success), var(--accent-3), var(--danger)); }
.split-actions { align-items: stretch; }
.dj-create-layout { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(300px, 0.75fr); gap: 16px; align-items: start; }
.style-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.style-card { padding: 11px; border: 1px solid var(--line); border-radius: 11px; background: rgba(17, 21, 30, 0.65); cursor: pointer; }
.style-card:hover { border-color: var(--line-strong); }
.style-card.active { border-color: rgba(139, 92, 246, 0.55); background: rgba(139, 92, 246, 0.08); box-shadow: inset 0 0 0 1px rgba(139, 92, 246, 0.12); }
.structure-bar { display: flex; gap: 3px; min-height: 38px; border-radius: 10px; overflow: hidden; background: rgba(8, 10, 15, 0.55); padding: 3px; }
.structure-block { border: 0; min-width: 20px; height: 32px; padding: 0 5px; display: flex; align-items: center; justify-content: center; overflow: hidden; border-radius: 6px; color: #070a10; font-size: 9px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.03em; opacity: 0.72; transition: opacity 120ms, transform 120ms; }
.structure-block:hover { opacity: 0.92; }
.structure-block.selected { opacity: 1; box-shadow: 0 0 0 2px #eaeef7 inset; transform: translateY(-1px); }
.structure-block span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.section-editor { border: 1px solid var(--line); border-radius: 12px; padding: 13px; background: rgba(8, 10, 15, 0.32); }
.section-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: none; }
.mini-summary { display: flex; gap: 5px; flex-wrap: wrap; }
.mini-summary span { font-size: 10px; padding: 3px 6px; border-radius: 6px; border: 1px solid var(--line); color: var(--muted); }
.generation-card { padding: 10px; border: 1px solid var(--line); border-radius: 10px; background: rgba(17, 21, 30, 0.6); }
.dj-mix-layout { display: grid; grid-template-columns: 290px minmax(0, 1fr); gap: 16px; align-items: start; }
.mix-list { display: flex; flex-direction: column; gap: 5px; }
.mix-list-item { display: flex; align-items: center; gap: 8px; border: 1px solid var(--line); border-radius: 9px; background: transparent; padding: 8px; color: var(--text); }
.mix-list-item:hover, .mix-list-item.active { border-color: rgba(139, 92, 246, 0.4); background: rgba(139, 92, 246, 0.07); }
.effect-preset { padding: 8px; border: 1px solid var(--line); border-radius: 8px; background: rgba(8, 10, 15, 0.3); }
.track-picker { display: flex; flex-wrap: wrap; gap: 6px; }
.pick-chip { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--line); border-radius: 999px; padding: 5px 9px; color: var(--muted); background: transparent; font-size: 11px; }
.pick-chip:hover { color: var(--text); border-color: var(--line-strong); }
.pick-chip.active { color: #ddd6fe; border-color: rgba(139, 92, 246, 0.5); background: rgba(139, 92, 246, 0.12); }
.selected-order { display: flex; flex-direction: column; gap: 4px; padding: 8px; border-radius: 9px; background: rgba(8, 10, 15, 0.3); border: 1px solid var(--line); }
.selected-order-item { display: flex; align-items: center; gap: 6px; }
.mix-timeline { position: relative; height: 92px; border-radius: 11px; background: rgba(8, 10, 15, 0.6); border: 1px solid var(--line); overflow: hidden; }
.mix-block { position: absolute; top: 8px; height: 76px; border-radius: 8px; padding: 8px; color: #070a10; overflow: hidden; opacity: 0.92; box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.18) inset; }
.mix-block-title { display: block; font-weight: 800; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mix-block-meta { display: block; font-size: 9.5px; opacity: 0.72; margin-top: 4px; }
.mix-fade { position: absolute; top: 0; bottom: 0; background: repeating-linear-gradient(135deg, rgba(8, 10, 15, 0.5), rgba(8, 10, 15, 0.5) 3px, rgba(234, 238, 247, 0.25) 3px, rgba(234, 238, 247, 0.25) 4px); pointer-events: none; border-left: 1px solid rgba(234, 238, 247, 0.35); border-right: 1px solid rgba(234, 238, 247, 0.35); }
.scene-track-card { padding: 12px; border: 1px solid var(--line); border-radius: 11px; background: rgba(17, 21, 30, 0.6); }
.effect-rack { margin-top: 9px; display: flex; flex-direction: column; gap: 5px; }
.effect-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 6px; border-radius: 7px; background: rgba(8, 10, 15, 0.35); border: 1px solid var(--line); }
.effect-num { display: flex; align-items: center; gap: 4px; font-size: 9.5px; color: var(--muted); }
.effect-num .input { width: 62px; }
.effect-num input[type="range"] { width: 110px; }
@media (max-width: 1200px) {
  .dj-create-layout, .dj-mix-layout { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .dj-track-grid, .style-grid { grid-template-columns: 1fr; }
}
</style>

<style scoped>
.dj-embedded { padding: 0; }
</style>
