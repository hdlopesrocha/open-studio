<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import {
  AlertTriangle,
  Archive,
  AudioLines,
  Captions,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleDashed,
  Copy,
  Download,
  FileArchive,
  FileJson,
  FileSearch,
  FileText,
  FolderOpen,
  Gauge,
  Languages,
  ListChecks,
  Loader2,
  Play,
  RefreshCw,
  Save,
  ScanText,
  Sparkles,
  Subtitles,
  Volume2,
  Wand2,
} from "lucide-vue-next";
import { api, downloadUrl, formatBytes, formatDuration, relativeTime } from "@/lib/api";
import { DEMO } from "@/lib/types";
import type { Job } from "@/lib/types";
import {
  demoDocResult,
  demoDocsCapabilities,
  demoImagePaths,
  demoSummary,
  demoTranslateLanguages,
} from "@/lib/demo";
import { useJobsStore } from "@/stores/jobs";
import { useToastStore } from "@/stores/toasts";
import { useSystemStore } from "@/stores/system";
import PageHeader from "@/components/PageHeader.vue";
import TabsBar from "@/components/TabsBar.vue";
import JobCard from "@/components/JobCard.vue";
import FilePicker from "@/components/FilePicker.vue";
import AudioPlayer from "@/components/AudioPlayer.vue";
import EmptyState from "@/components/EmptyState.vue";
import CodeBlock from "@/components/CodeBlock.vue";
import SummaryPanel from "@/components/documents/SummaryPanel.vue";
import TranslateView from "@/views/TranslateView.vue";
import ServiceNotice from "@/components/ServiceNotice.vue";

type TextKind = "extracted" | "translation" | "summary";

const jobs = useJobsStore();
const toasts = useToastStore();
const system = useSystemStore();
const route = useRoute();
const router = useRouter();

const TAB_IDS = ["workflow", "pdf", "summary", "translate", "results"] as const;

function tabFromQuery(value: unknown): string | null {
  const candidate = Array.isArray(value) ? value[0] : value;
  return typeof candidate === "string" && (TAB_IDS as readonly string[]).includes(candidate) ? candidate : null;
}

const tab = ref(tabFromQuery(route.query.tab) || "workflow");
const summaryMounted = ref(tab.value === "summary");
const translateMounted = ref(tab.value === "translate");
watch(tab, (value) => {
  if (value === "summary") summaryMounted.value = true;
  if (value === "translate") translateMounted.value = true;
  if ((tabFromQuery(route.query.tab) || "workflow") === value) return;
  const query = { ...route.query };
  if (value === "workflow") delete query.tab;
  else query.tab = value;
  router.replace({ query });
});
watch(
  () => route.query.tab,
  (value) => {
    const next = tabFromQuery(value);
    if (next && next !== tab.value) tab.value = next;
  },
);
const resultKind = ref<TextKind>("summary");
const capsLoading = ref(!DEMO);
const capsError = ref("");
const capabilities = ref<any>(normalizeCaps(DEMO ? demoDocsCapabilities : {}));

const sourcePickerOpen = ref(false);
const toolsPickerOpen = ref(false);

const sourceType = ref<"pdf" | "text">("pdf");
const pdfPath = ref(DEMO ? `documents/${demoDocResult.source}` : "");
const sourcePdfInfo = ref<any>(DEMO ? { page_count: demoDocResult.pages, title: demoDocResult.title, author: "Open Studio GmbH", likely_scanned: false, size_bytes: 4_820_000 } : null);
const sourceText = ref("");
const inputLanguage = ref("auto");
const startPage = ref<number | string>(1);
const endPage = ref<number | string>(DEMO ? demoDocResult.pages : "");
const selectedPagesText = ref("");
const ocrEnabled = ref(false);
const ocrLanguage = ref("eng");

const translationEnabled = ref(true);
const translationSource = ref("auto");
const translationTarget = ref(DEMO ? "pt-PT" : "en");
const translationModel = ref("auto");
const translationAdvanced = ref(false);
const translationParams = reactive<Record<string, any>>({
  num_beams: 2,
  max_length: 512,
  temperature: 0,
  length_penalty: 1,
  repetition_penalty: 1,
  no_repeat_ngram_size: 3,
  batch_size: 8,
  preserve_markup: true,
});
const glossaryText = ref(DEMO ? "Open Studio = Open Studio\nlocal-first = local-first" : "");

const summaryEnabled = ref(true);
const summaryLength = ref("medium");
const summaryLanguage = ref("en");
const summarySourceLanguage = ref("auto");
const summaryModel = ref("auto");
const summaryAdvanced = ref(false);
const summaryParams = reactive<Record<string, any>>({
  max_tokens: null,
  min_tokens: null,
  num_beams: 3,
  temperature: 0,
  chunk_tokens: null,
  hierarchical: true,
  from_translation: true,
});

const ttsEnabled = ref(true);
const ttsEngine = ref("omnivoice");
const ttsMode = ref("voice");
const voiceId = ref(DEMO ? "v1" : "");
const piperVoice = ref(DEMO ? "pt-PT-tugao" : "");
const ttsLanguage = ref(DEMO ? "pt-PT" : "");
const ttsSpeed = ref(1);
const ttsFormat = ref("mp3");
const ttsNormalizeAudio = ref(true);
const ttsNormalizeText = ref(true);
const ttsTextSource = ref<"content" | "summary">("content");

const subtitlesEnabled = ref(true);
const subtitleFormat = ref("srt");
const zipEnabled = ref(true);
const pipelineTitle = ref(DEMO ? demoDocResult.title : "");

const activeJobId = ref(DEMO ? "job_33af9e88" : "");
const submitting = ref(false);
let pollTimer: number | undefined;
let capabilitiesReady = false;

const pdfToolPath = ref(DEMO ? `documents/${demoDocResult.source}` : "");
const pdfToolInfo = ref<any>(DEMO ? { page_count: demoDocResult.pages, title: demoDocResult.title, author: "Open Studio GmbH", likely_scanned: false, size_bytes: 4_820_000, producer: "Open Studio PDF" } : null);
const pdfToolStart = ref<number | string>(1);
const pdfToolEnd = ref<number | string>(DEMO ? 8 : "");
const pdfToolSelectedPages = ref("");
const pdfToolOcr = ref(false);
const pdfToolOcrLanguage = ref("eng");
const pdfToolBusy = ref(false);
const pdfToolExtracting = ref(false);
const pdfToolText = ref(DEMO ? `${demoDocResult.extracted}\n\n--- Page 3 ---\n\nRevenue rose 24%, driven by studio subscriptions and enterprise deployments.` : "");
const pdfToolWarnings = ref<string[]>([]);

const DEMO_DOC_CUES = [
  { index: 1, start: 0.42, end: 4.8, text: "O ano passado foi definido por uma mudança para fluxos de trabalho locais integrados." },
  { index: 2, start: 4.8, end: 9.1, text: "Os clientes pediram um único lugar para música, vídeo, voz e documentos." },
  { index: 3, start: 9.1, end: 13.6, text: "As receitas cresceram 24% em relação ao ano anterior." },
  { index: 4, start: 13.6, end: 18.2, text: "A equipa lançou quatro integrações de modelos." },
  { index: 5, start: 19.0, end: 22.4, text: "A latência de inferência caiu 38% com modelos quantizados." },
  { index: 6, start: 22.4, end: 26.8, text: "Os custos de armazenamento foram reduzidos com ativos endereçados por conteúdo." },
  { index: 7, start: 26.8, end: 30.1, text: "As prioridades para o próximo ano são vídeo, voz multilingue e documentos." },
  { index: 8, start: 30.1, end: 34.6, text: "O sistema de tarefas partilhado permite que todos os serviços corram em paralelo." },
];

const result = ref<any>(DEMO ? buildDemoResult() : null);
const resultTexts = reactive<Record<TextKind, string>>({ extracted: "", translation: "", summary: "" });
const originalTexts = reactive<Record<TextKind, string>>({ extracted: "", translation: "", summary: "" });
const savingKind = ref<TextKind | "">("");

const docsOnline = computed(() => (system.status ? system.service("docs")?.online === true : true));
const pdfOnline = computed(() => (system.status ? system.service("pdf")?.online === true : true));
const summaryOnline = computed(() => (system.status ? system.service("summary")?.online === true : true));
const translationOnline = computed(() => (system.status ? system.service("translation")?.online === true : true));

const tabs = computed(() => [
  ...(docsOnline.value ? [{ id: "workflow", label: "Workflow" }] : []),
  ...(pdfOnline.value ? [{ id: "pdf", label: "PDF tools" }] : []),
  ...(summaryOnline.value ? [{ id: "summary", label: "Summary" }] : []),
  ...(translationOnline.value ? [{ id: "translate", label: "Translate" }] : []),
  ...(docsOnline.value ? [{ id: "results", label: "Results", count: result.value ? 3 : undefined }] : []),
]);
watch(tabs, (items) => {
  if (!items.some((item) => item.id === tab.value)) tab.value = items[0]?.id || "workflow";
}, { immediate: true });

const resultTextTabs = computed(() => [
  { id: "extracted", label: "Extracted", count: wordCount(resultTexts.extracted) },
  { id: "translation", label: "Translation", count: wordCount(resultTexts.translation) },
  { id: "summary", label: "Summary", count: wordCount(resultTexts.summary) },
]);

const caps = computed(() => capabilities.value);
const translationSourceOptions = computed(() => caps.value?.translation.source || languageOptions(demoTranslateLanguages.source));
const translationTargetOptions = computed(() => caps.value?.translation.target || languageOptions(demoTranslateLanguages.target));
const translationModelOptions = computed(() => caps.value?.translation.models || [{ id: "auto", name: "Auto", available: true }]);
const summaryLengthOptions = computed(() => caps.value?.summary.lengths || defaultLengths());
const summaryLanguageOptions = computed(() => caps.value?.summary.languages || languageOptions(["en", "pt-PT", "pt-BR"]));
const summarySourceOptions = computed(() => [
  { code: "auto", label: languageLabel("auto") },
  ...(caps.value?.summary.languages || languageOptions(["en", "pt-PT", "pt-BR"])).filter((item: any) => item.code !== "auto"),
]);
const summaryModelOptions = computed(() => caps.value?.summary.models || [{ id: "auto", name: "Auto", available: true }]);
const ttsEngineOptions = computed(() => caps.value?.tts.engines || []);
const voiceOptions = computed(() => caps.value?.tts.voices || []);
const piperVoiceOptions = computed(() => caps.value?.tts.piperVoices || []);
const ttsFormatOptions = computed(() => caps.value?.tts.formats || ["mp3", "wav", "flac"]);
const ocrLanguageOptions = computed(() => caps.value?.ocrLanguages || []);
const subtitleFormatOptions = computed(() => caps.value?.subtitles.formats || ["srt", "vtt"]);
const voiceLanguageOptions = computed(() => {
  const languages = caps.value?.tts.languages || [];
  if (!languages.length) return languageOptions(["en", "pt-PT", "pt-BR", "es", "fr", "de"]);
  if (languages.length > 30) return languageOptions(["en", "pt-PT", "pt-BR", "es", "fr", "de", "it", "ja"]);
  return languages;
});

const translationAvailable = computed(() => Boolean(caps.value?.translation.available));
const summaryAvailable = computed(() => Boolean(caps.value?.summary.available));
const ttsAvailable = computed(() => Boolean(caps.value?.tts.available));
const translationUnavailable = computed(() => !translationAvailable.value);
const summaryUnavailable = computed(() => !summaryAvailable.value);
const ttsUnavailable = computed(() => !ttsAvailable.value);

const activeJob = computed<Job | null>(() => (activeJobId.value ? jobs.byId(activeJobId.value) || null : null));
const activeJobRunning = computed(() => Boolean(activeJob.value && ["queued", "running", "canceling"].includes(activeJob.value.status)));
const sourceLabel = computed(() => {
  if (sourceType.value === "text") return "Pasted text";
  return pdfPath.value.split("/").pop() || "No PDF selected";
});
const sourcePagesLabel = computed(() => {
  if (sourceType.value !== "pdf") return `${sourceText.value.length.toLocaleString()} characters`;
  if (sourcePdfInfo.value?.page_count) return `${sourcePdfInfo.value.page_count} pages`;
  return "Pages are detected on inspect";
});
const sourceRangeLabel = computed(() => {
  const pages = parsePageSelection(selectedPagesText.value);
  if (pages) return `${pages.length} selected page${pages.length === 1 ? "" : "s"}`;
  const start = numberOrNull(startPage.value);
  const end = numberOrNull(endPage.value);
  if (start && end) return `Pages ${start}–${end}`;
  if (start) return `From page ${start}`;
  if (end) return `Through page ${end}`;
  return "All pages";
});
const maxTextCharacters = computed(() => caps.value?.limits.maxTextCharacters || 500_000);

const runIssue = computed(() => {
  if (!docsOnline.value) return "The documents service is offline.";
  if (sourceType.value === "pdf" && !pdfPath.value) return "Choose a PDF or switch the source to text.";
  if (sourceType.value === "text" && !sourceText.value.trim()) return "Paste some text before running the workflow.";
  if (sourceType.value === "text" && sourceText.value.length > maxTextCharacters.value) return `The pasted text exceeds the ${maxTextCharacters.value.toLocaleString()}-character limit.`;
  if (sourceType.value === "pdf") {
    const rangeStart = numberOrNull(startPage.value);
    const rangeEnd = numberOrNull(endPage.value);
    if (rangeStart && rangeEnd && rangeEnd < rangeStart) return "The end page must be greater than or equal to the start page.";
  }
  const maxTokens = numberOrNull(summaryParams.max_tokens);
  const minTokens = numberOrNull(summaryParams.min_tokens);
  if (maxTokens !== null && minTokens !== null && minTokens >= maxTokens) return "Summary minimum tokens must be smaller than the maximum.";
  if (sourceType.value === "pdf" && !pdfOnline.value) return "The PDF service is offline, so PDF extraction cannot run.";
  if (translationEnabled.value && !translationAvailable.value) return "Translation is enabled but the shared translation service is unavailable.";
  if (summaryEnabled.value && !summaryAvailable.value) return "Summarization is enabled but the summary service is unavailable.";
  if (ttsEnabled.value && !ttsAvailable.value) return "Narration is enabled but the voice service is unavailable.";
  if (ttsEnabled.value && ttsTextSource.value === "summary" && !summaryEnabled.value) return "Narrate the content or enable summarization first.";
  return "";
});
const canRun = computed(() => !runIssue.value);
const enabledStageCount = computed(() => pipelineStages.value.filter((stage) => stage.state !== "skipped").length);

const stageDefs = [
  { id: "extract", label: "Extract source", detail: "PDF text, OCR or pasted content", from: 0, through: 20 },
  { id: "translate", label: "Translate", detail: "Shared OPUS-MT / NLLB service", from: 20, through: 46 },
  { id: "summarize", label: "Summarize", detail: "Hierarchical T5 summary", from: 46, through: 62 },
  { id: "tts", label: "Narrate", detail: "OmniVoice or Piper speech", from: 62, through: 87 },
  { id: "subtitles", label: "Align subtitles", detail: "Speech timeline to SRT / VTT", from: 87, through: 93 },
  { id: "archive", label: "Bundle", detail: "Manifest, downloads and ZIP", from: 93, through: 100 },
];
const pipelineStages = computed(() => {
  const enabled: Record<string, boolean> = {
    extract: true,
    translate: translationEnabled.value,
    summarize: summaryEnabled.value,
    tts: ttsEnabled.value,
    subtitles: subtitlesEnabled.value && ttsEnabled.value,
    archive: zipEnabled.value,
  };
  const job = activeJob.value;
  const progress = job ? Number(job.progress || 0) : result.value ? 100 : 0;
  return stageDefs.map((stage) => {
    if (!enabled[stage.id]) return { ...stage, state: "skipped" };
    if (progress >= 100) return { ...stage, state: "done" };
    if (job?.status === "failed" && job.stage === stage.id) return { ...stage, state: "failed" };
    if (progress >= stage.through) return { ...stage, state: "done" };
    if (progress >= stage.from && (job?.stage === stage.id || job?.stage === "complete" || progress > 0)) return { ...stage, state: "active" };
    return { ...stage, state: "pending" };
  });
});

const resultTextDirty = computed(() => resultTexts[resultKind.value] !== originalTexts[resultKind.value]);
const resultSummaryDirty = computed(() => resultTexts.summary !== originalTexts.summary);
const activeTextLabel = computed(() => ({ extracted: "Extracted text", translation: "Translation", summary: "Summary" })[resultKind.value]);
const resultCues = computed<any[]>(() => result.value?.cues || result.value?.manifest?.timeline || []);
const resultStatCards = computed(() => {
  const bundle = result.value;
  if (!bundle) return [];
  const stats = bundle.stats || {};
  return [
    { label: "Source pages", value: formatNumber(stats.pages ?? bundle.pages ?? bundle.source?.page_count), sub: "selected pages" },
    { label: "Extracted words", value: formatNumber(stats.extracted_words ?? stats.extractedWords), sub: "PDF / OCR text" },
    { label: "Summary", value: formatNumber(stats.summary_words ?? stats.summaryWords), sub: "words" },
    { label: "Narration", value: formatDuration(stats.speech_seconds ?? stats.speechSeconds), sub: "audio duration" },
  ];
});
const manifestStatRows = computed(() => {
  const stats = result.value?.stats || {};
  const labels: Record<string, string> = {
    pages: "Source pages",
    extracted_words: "Extracted words",
    extracted_characters: "Extracted characters",
    translated_words: "Translated words",
    translated_characters: "Translated characters",
    summary_input_words: "Summary input words",
    summary_words: "Summary words",
    summary_chunks: "Summary chunks",
    speech_seconds: "Narration duration",
    subtitle_cues: "Subtitle cues",
    zip_bytes: "ZIP bundle",
    translation_model: "Translation model",
    summary_model: "Summary model",
  };
  return Object.entries(stats)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => ({
      key,
      label: labels[key] || key.replace(/_/g, " "),
      value: formatStatValue(key, value),
    }));
});
const manifestJson = computed(() => JSON.stringify(result.value?.manifest || {}, null, 2));
const resultPreviews = computed(() => {
  const bundle = result.value;
  if (!bundle) return [] as Array<{ page: number; url: string }>;
  if (DEMO) return demoImagePaths.slice(0, 6).map((url, index) => ({ page: index + 1, url }));
  if (bundle.source?.type !== "pdf") return [];
  const sourcePath = bundle.source?.path || pdfPath.value;
  if (!sourcePath) return [];
  const selected: number[] = Array.isArray(bundle.source?.selected_pages) && bundle.source.selected_pages.length
    ? bundle.source.selected_pages
    : Array.from({ length: Math.min(6, Number(bundle.pages || bundle.source?.page_count || 6)) }, (_, index) => index + 1);
  return selected.slice(0, 6).map((page) => ({ page, url: pdfPreviewUrl(sourcePath, page, 420) }));
});
const pdfToolPreviewItems = computed(() => {
  if (DEMO) return demoImagePaths.slice(0, 6).map((url, index) => ({ page: index + 1, url }));
  if (!pdfToolPath.value || !pdfToolInfo.value?.page_count) return [];
  const pages = parsePageSelection(pdfToolSelectedPages.value);
  const list = pages || Array.from({ length: Math.min(6, Number(pdfToolInfo.value.page_count)) }, (_, index) => index + 1);
  return list.slice(0, 8).map((page) => ({ page, url: pdfPreviewUrl(pdfToolPath.value, page, 360) }));
});
const resultAudioSrc = computed(() => result.value?.audio?.audio_path || result.value?.audio?.path || "");
const resultAudioTitle = computed(() => {
  const audio = result.value?.audio || {};
  return audio.voice || audio.voice_id || (audio.engine === "piper" ? "Piper narration" : "Document narration");
});
const resultAudioSubtitle = computed(() => {
  const audio = result.value?.audio || {};
  return [audio.engine, audio.language, audio.format?.toUpperCase()].filter(Boolean).join(" · ");
});
const resultBundleFiles = computed<any[]>(() => {
  const files = result.value?.files;
  if (!Array.isArray(files)) return [];
  const seen = new Set<string>();
  return files.filter((file: any) => {
    if (!file?.path || seen.has(file.path)) return false;
    seen.add(file.path);
    return true;
  });
});
const toolPreviewTitle = computed(() => pdfToolPath.value.split("/").pop() || "Select a PDF");
const toolRangeLabel = computed(() => {
  const pages = parsePageSelection(pdfToolSelectedPages.value);
  if (pages) return `${pages.length} selected page${pages.length === 1 ? "" : "s"}`;
  const start = numberOrNull(pdfToolStart.value);
  const end = numberOrNull(pdfToolEnd.value);
  if (start && end) return `Pages ${start}–${end}`;
  if (start) return `From page ${start}`;
  if (end) return `Through page ${end}`;
  return "All pages";
});
const pdfToolMeta = computed(() => {
  const info = pdfToolInfo.value;
  if (!info) return [];
  return [
    { label: "Pages", value: formatNumber(info.page_count) },
    { label: "Title", value: info.title || "Untitled" },
    { label: "Author", value: info.author || "Unknown" },
    { label: "OCR", value: info.likely_scanned ? "Recommended" : "Not required" },
    { label: "Size", value: info.size_bytes ? formatBytes(info.size_bytes) : "—" },
  ];
});

onMounted(async () => {
  seedResultTexts();
  applyCapabilityDefaults();
  system.load();
  if (DEMO) {
    jobs.refresh();
    return;
  }
  await loadCapabilities();
});

onBeforeUnmount(stopPolling);

watch(
  () => activeJob.value?.status,
  (status) => {
    if (!status) return;
    if (status === "completed" && activeJobId.value) {
      stopPolling();
      loadResults(activeJobId.value);
      toasts.success("Document workflow complete");
      if (!DEMO) tab.value = "results";
    } else if (status === "failed") {
      stopPolling();
      toasts.error(activeJob.value?.error || "The document workflow failed");
    } else if (status === "canceled") {
      stopPolling();
      toasts.info("Document workflow canceled");
    }
  },
);

function seedResultTexts() {
  if (!result.value) return;
  resultTexts.extracted = result.value.extracted || "";
  resultTexts.translation = result.value.translation || "";
  resultTexts.summary = result.value.summary || "";
  originalTexts.extracted = resultTexts.extracted;
  originalTexts.translation = resultTexts.translation;
  originalTexts.summary = resultTexts.summary;
}

function buildDemoResult() {
  const extracted = `${demoDocResult.extracted}

--- Page 3 ---

Revenue rose 24% year over year, driven by studio subscriptions, enterprise deployments and the launch of shared job queues. Inference latency fell by 38% after the switch to quantized local models.

--- Page 4 ---

Storage costs were reduced through content-addressed assets and automatic deduplication. The team shipped four model integrations: ACE-Step 1.5, OmniVoice, NLLB-200 and QVAC video.

--- Page 5 ---

Priorities for next year are video generation, multilingual voice, and a unified document pipeline that can translate, summarize, narrate and caption a PDF without leaving the studio.`;
  const translation = `${demoDocResult.translation}

--- Page 3 ---

As receitas cresceram 24% em relação ao ano anterior, impulsionadas pelas subscrições de estúdio, pelas implementações empresariais e pelo lançamento das filas de trabalho partilhadas.

--- Page 4 ---

Os custos de armazenamento foram reduzidos através de ativos endereçados por conteúdo e da desduplicação automática. A equipa lançou quatro integrações de modelos: ACE-Step 1.5, OmniVoice, NLLB-200 e vídeo QVAC.`;
  const stats = {
    pages: demoDocResult.pages,
    extracted_words: 8420,
    extracted_characters: 54912,
    translated_words: 8216,
    translated_characters: 53104,
    summary_input_words: demoSummary.input_words,
    summary_words: wordCount(demoDocResult.summary),
    summary_chunks: demoSummary.chunk_count,
    speech_seconds: 624.8,
    subtitle_cues: DEMO_DOC_CUES.length,
    zip_bytes: 16233002,
    translation_model: "opus-mt-en-pt",
    summary_model: "t5-small-pt",
  };
  const audio = {
    engine: "omnivoice",
    voice: "Helena — close",
    voice_id: "v1",
    language: "pt-PT",
    format: "mp3",
    duration_seconds: 624.8,
    normalized: true,
    text_source: "content",
    timeline_method: "voice",
    audio_path: demoDocResult.audio_path,
  };
  const files = [
    { name: "extracted.txt", path: "documents/33af9e88/extracted.txt", kind: "document", mime: "text/plain", size: 54102 },
    { name: "translation.txt", path: "documents/33af9e88/translation.txt", kind: "document", mime: "text/plain", size: 52880 },
    { name: "summary.txt", path: "documents/33af9e88/summary.txt", kind: "document", mime: "text/plain", size: 4201 },
    { name: "audio.mp3", path: demoDocResult.audio_path, kind: "audio", mime: "audio/mpeg", size: 16200432 },
    { name: "subtitles.srt", path: demoDocResult.srt_path, kind: "subtitle", mime: "application/x-subrip", size: 3120 },
    { name: "captions.vtt", path: demoDocResult.vtt_path, kind: "subtitle", mime: "text/vtt", size: 3040 },
    { name: "manifest.json", path: "documents/33af9e88/manifest.json", kind: "document", mime: "application/json", size: 12600 },
    { name: "output.zip", path: demoDocResult.zip_path, kind: "archive", mime: "application/zip", size: 16233002 },
  ];
  const manifest = {
    job_id: demoDocResult.job_id,
    title: demoDocResult.title,
    status: "completed",
    generator: "Open Studio documents",
    created_at: new Date(Date.now() - 105 * 60000).toISOString(),
    completed_at: new Date(Date.now() - 92 * 60000).toISOString(),
    source: {
      type: "pdf",
      path: `documents/${demoDocResult.source}`,
      filename: demoDocResult.source,
      title: "Annual Report 2026",
      page_count: demoDocResult.pages,
      selected_pages: Array.from({ length: 12 }, (_, index) => index + 1),
      ocr_enabled: false,
    },
    languages: { source: "en", translation_source: "en", translation_target: "pt-PT", summary: "en", speech: "pt-PT" },
    stats,
    warnings: ["Subtitle timings are aligned to the OmniVoice timeline."],
    artifacts: Object.fromEntries(files.map((file) => [file.name.replace(/\..*$/, ""), file])),
    audio,
    timeline: DEMO_DOC_CUES,
  };
  return {
    jobId: demoDocResult.job_id,
    title: demoDocResult.title,
    completedAt: new Date(Date.now() - 92 * 60000).toISOString(),
    source: manifest.source,
    pages: demoDocResult.pages,
    extracted,
    translation,
    summary: demoDocResult.summary,
    stats,
    languages: manifest.languages,
    warnings: manifest.warnings,
    audio,
    srt: demoDocResult.srt_path,
    vtt: demoDocResult.vtt_path,
    zip: demoDocResult.zip_path,
    manifestPath: "documents/33af9e88/manifest.json",
    files,
    manifest,
    cues: DEMO_DOC_CUES,
  };
}

async function loadCapabilities() {
  if (DEMO) {
    capabilities.value = normalizeCaps(demoDocsCapabilities);
    applyCapabilityDefaults();
    toasts.info("Demo mode · capabilities are preloaded");
    return;
  }
  capsLoading.value = true;
  capsError.value = "";
  try {
    const raw = await api.get<any>("/docs/capabilities");
    capabilities.value = normalizeCaps(raw);
    capabilitiesReady = true;
    applyCapabilityDefaults();
  } catch (error: any) {
    capsError.value = error?.message || "Could not load document capabilities.";
    toasts.error(capsError.value);
  } finally {
    capsLoading.value = false;
  }
}

function normalizeCaps(raw: any) {
  const translation = raw?.translation || {};
  const summary = raw?.summary || {};
  const tts = raw?.tts || {};
  const inputs = raw?.inputs || {};
  const pdf = raw?.pdf || {};
  const languages = raw?.translation_languages || {};
  const integration = raw?.languages || {};
  const rawTtsEngines = tts.engines || raw?.tts_engines || [];
  const rawVoices = tts.voices || raw?.voices || [];
  const rawPiper = tts.piper_voices || tts.catalog?.piper_voices || raw?.piper_voices || [];
  const rawFormats = tts.formats || raw?.formats?.audio || raw?.formats || ["mp3", "wav", "flac"];
  const formatList = Array.isArray(rawFormats) ? rawFormats : Object.keys(rawFormats || {});
  const rawLengths = summary.lengths || raw?.summary_lengths || defaultLengths();
  const lengthList = Array.isArray(rawLengths) ? rawLengths : [];
  const ocrRaw = pdf.ocr?.items || inputs.pdf?.ocr_languages || pdf.status?.ocr_languages?.installed || raw?.ocr_languages || [];
  const ocrList = Array.isArray(ocrRaw) ? ocrRaw : [];
  const fallbackTranslationModels = [
    { id: "opus-mt-pt-en", name: "OPUS-MT · Portuguese → English", available: DEMO },
    { id: "opus-mt-en-pt", name: "OPUS-MT · English → Portuguese", available: DEMO },
    { id: "nllb-200-distilled-600M", name: "NLLB-200 distilled 600M · multilingual", available: DEMO },
  ];
  const fallbackSummaryModels = [
    { id: "t5-small-en", name: "T5 small · English summaries", available: DEMO },
    { id: "t5-small-pt", name: "T5 small · Portuguese summaries", available: DEMO },
  ];
  const translationModels = normalizeModels(translation.models || []);
  const summaryModels = normalizeModels(summary.models || []);
  return {
    raw,
    inputTypes: raw?.input_types || inputs.types || ["pdf", "text"],
    pdfAvailable: pdf.available !== false,
    ocrAvailable: Boolean(pdf.ocr?.available ?? pdf.status?.ocr_available ?? true),
    ocrLanguages: normalizeOcr(ocrList),
    translation: {
      available: translation.available !== false && Boolean(translation.source_languages || translation.languages || languages.source || DEMO),
      source: languageOptions(translation.source_languages || languages.source || demoTranslateLanguages.source),
      target: languageOptions(translation.target_languages || languages.target || demoTranslateLanguages.target),
      models: withAuto(translationModels.length ? translationModels : fallbackTranslationModels),
    },
    summary: {
      available: summary.available !== false && Boolean(summary.lengths || raw?.summary_lengths || DEMO),
      lengths: normalizeLengths(lengthList.length ? lengthList : defaultLengths()),
      languages: languageOptions(summary.languages || raw?.summary_languages || integration.target || ["en", "pt-PT", "pt-BR"]),
      models: withAuto(summaryModels.length ? summaryModels : fallbackSummaryModels),
    },
    tts: {
      available: tts.available !== false && rawTtsEngines.length > 0,
      engines: normalizeEngines(rawTtsEngines),
      voices: normalizeVoices(rawVoices),
      piperVoices: normalizePiperVoices(rawPiper),
      languages: normalizeVoiceLanguages(tts.languages || []),
      formats: Array.from(new Set(formatList.map((item: any) => String(typeof item === "string" ? item : item?.id || item?.name || item).toLowerCase()))).filter(Boolean),
    },
    subtitles: {
      formats: Array.isArray(raw?.subtitles?.formats) && raw.subtitles.formats.length ? raw.subtitles.formats : ["srt", "vtt"],
    },
    limits: {
      maxTextCharacters: raw?.limits?.max_text_characters || raw?.limits?.max_text_chars || raw?.limits?.max_text_characters || 500_000,
      maxPages: raw?.limits?.max_pages || 2000,
    },
  };
}

function languageOptions(list: any): Array<{ code: string; label: string }> {
  const items = Array.isArray(list) ? list : [];
  const mapped = items
    .map((item: any) => {
      if (typeof item === "string") return { code: item, label: languageLabel(item) };
      const code = String(item?.code ?? item?.id ?? item?.language ?? item?.value ?? "");
      return { code, label: String(item?.label ?? item?.name ?? item?.title ?? languageLabel(code)) };
    })
    .filter((item: { code: string }) => item.code);
  return mapped.length ? mapped : ["en", "pt-PT", "pt-BR"].map((code) => ({ code, label: languageLabel(code) }));
}

function languageLabel(code: string) {
  const map: Record<string, string> = {
    auto: "Detect automatically",
    en: "English",
    pt: "Portuguese",
    "pt-PT": "Portuguese (Portugal)",
    "pt-BR": "Portuguese (Brazil)",
    es: "Spanish",
    fr: "French",
    de: "German",
    it: "Italian",
    ja: "Japanese",
    zh: "Chinese",
    "zh-Hant": "Chinese (Traditional)",
    nl: "Dutch",
    pl: "Polish",
    ru: "Russian",
  };
  return map[code] || code.toUpperCase();
}

function normalizeOcr(list: any[]) {
  const mapped = list
    .map((item: any) => {
      if (typeof item === "string") return { code: item, label: ocrLabel(item) };
      return { code: String(item?.code ?? item?.id ?? item ?? ""), label: String(item?.label ?? item?.name ?? ocrLabel(String(item?.code ?? item?.id ?? ""))) };
    })
    .filter((item) => item.code);
  return mapped.length ? mapped : ["eng", "por", "spa", "fra", "deu", "ita"].map((code) => ({ code, label: ocrLabel(code) }));
}

function ocrLabel(code: string) {
  const map: Record<string, string> = {
    eng: "English",
    por: "Portuguese",
    spa: "Spanish",
    fra: "French",
    deu: "German",
    ita: "Italian",
    nld: "Dutch",
    rus: "Russian",
    jpn: "Japanese",
    chi_sim: "Chinese (Simplified)",
    chi_tra: "Chinese (Traditional)",
  };
  return map[code] || code;
}

function normalizeModels(list: any[]) {
  return list
    .map((item: any) => {
      if (typeof item === "string") return { id: item, name: item, available: true };
      const id = String(item?.id ?? item?.model ?? item?.name ?? "");
      return {
        id,
        name: String(item?.name ?? item?.label ?? id),
        available: item?.available !== false && item?.installed !== false,
      };
    })
    .filter((item: { id: string }) => item.id);
}

function withAuto(models: any[]) {
  const cleaned = models.filter((model) => model.id !== "auto");
  return [{ id: "auto", name: "Auto · best available", available: true }, ...cleaned];
}

function normalizeLengths(list: any[]) {
  const fallback: Record<string, { label: string; max: number }> = {
    short: { label: "Short", max: 120 },
    medium: { label: "Medium", max: 240 },
    long: { label: "Long", max: 420 },
  };
  const mapped = list.map((item: any) => {
    if (typeof item === "string") return { id: item, label: fallback[item]?.label || cap(item), max_tokens: fallback[item]?.max || null };
    const id = String(item?.id ?? item?.value ?? item?.length ?? "medium");
    return { id, label: String(item?.label ?? item?.name ?? cap(id)), max_tokens: item?.max_tokens ?? fallback[id]?.max ?? null };
  });
  return mapped.length ? mapped : defaultLengths();
}

function defaultLengths() {
  return [
    { id: "short", label: "Short", max_tokens: 120 },
    { id: "medium", label: "Medium", max_tokens: 240 },
    { id: "long", label: "Long", max_tokens: 420 },
  ];
}

function normalizeEngines(list: any[]) {
  return list
    .map((item: any) => {
      if (typeof item === "string") return { id: item, name: cap(item), available: true, detail: "" };
      const id = String(item?.id ?? item?.key ?? item?.name ?? "");
      return {
        id,
        name: String(item?.name ?? item?.label ?? id),
        available: item?.available !== false && !["error", "unavailable", "offline"].includes(String(item?.status || "").toLowerCase()),
        detail: [item?.device, item?.detail].filter(Boolean).join(" · "),
      };
    })
    .filter((item) => item.id);
}

function normalizeVoices(list: any[]) {
  return list
    .map((item: any) => {
      const id = String(item?.id ?? item?.voice_id ?? item?.name ?? "");
      return {
        id,
        name: String(item?.name ?? item?.label ?? id),
        language: String(item?.language ?? ""),
        detail: [item?.language, item?.duration_seconds ? `${Number(item.duration_seconds).toFixed(1)}s reference` : ""].filter(Boolean).join(" · "),
      };
    })
    .filter((item) => item.id);
}

function normalizePiperVoices(list: any[]) {
  return list
    .map((item: any) => {
      const id = String(item?.id ?? item?.voice_id ?? item?.name ?? "");
      return {
        id,
        name: String(item?.name ?? item?.label ?? id),
        language: String(item?.language ?? ""),
        available: item?.available !== false,
        detail: [item?.language, item?.gender].filter(Boolean).join(" · "),
      };
    })
    .filter((item) => item.id);
}

function normalizeVoiceLanguages(list: any[]) {
  const items = Array.isArray(list) ? list : [];
  return items
    .map((item: any) => {
      if (typeof item === "string") return { code: item, label: languageLabel(item) };
      const code = String(item?.id ?? item?.code ?? item?.language ?? "");
      return { code, label: String(item?.name ?? item?.label ?? languageLabel(code)) };
    })
    .filter((item) => item.code);
}

function applyCapabilityDefaults() {
  const value = capabilities.value;
  if (!value) return;
  if (!value.translation.source.some((item: any) => item.code === translationSource.value)) translationSource.value = value.translation.source[0]?.code || "auto";
  if (!value.translation.target.some((item: any) => item.code === translationTarget.value)) translationTarget.value = value.translation.target[0]?.code || "en";
  if (!value.summary.languages.some((item: any) => item.code === summaryLanguage.value)) summaryLanguage.value = value.summary.languages[0]?.code || "en";
  if (!value.summary.lengths.some((item: any) => item.id === summaryLength.value)) summaryLength.value = "medium";
  if (!value.ocrLanguages.some((item: any) => item.code === ocrLanguage.value)) ocrLanguage.value = value.ocrLanguages[0]?.code || "eng";
  if (!value.tts.engines.some((item: any) => item.id === ttsEngine.value)) ttsEngine.value = value.tts.engines[0]?.id || "piper";
  if (!value.tts.formats.includes(ttsFormat.value)) ttsFormat.value = value.tts.formats[0] || "mp3";
  if (!value.tts.voices.some((item: any) => item.id === voiceId.value)) voiceId.value = value.tts.voices[0]?.id || "";
  if (!value.tts.piperVoices.some((item: any) => item.id === piperVoice.value)) piperVoice.value = value.tts.piperVoices.find((item: any) => item.available)?.id || value.tts.piperVoices[0]?.id || "";
  if (ttsMode.value === "voice" && !value.tts.voices.length) ttsMode.value = "auto";
  if (!value.subtitles.formats.includes(subtitleFormat.value)) subtitleFormat.value = value.subtitles.formats[0] || "srt";
  if (ttsLanguage.value && !voiceLanguageOptions.value.some((item: any) => item.code === ttsLanguage.value)) ttsLanguage.value = "";
  if (capabilitiesReady) {
    if (!value.translation.available) translationEnabled.value = false;
    if (!value.summary.available) {
      summaryEnabled.value = false;
      if (ttsTextSource.value === "summary") ttsTextSource.value = "content";
    }
    if (!value.tts.available) {
      ttsEnabled.value = false;
      subtitlesEnabled.value = false;
    }
  }
}

function onSourcePdf(path: string, file: any) {
  if (!path.toLowerCase().endsWith(".pdf")) {
    toasts.error("Choose a PDF file for the documents workflow");
    return;
  }
  pdfPath.value = path;
  sourceType.value = "pdf";
  sourcePdfInfo.value = null;
  if (DEMO) {
    sourcePdfInfo.value = { page_count: demoDocResult.pages, title: file?.name || demoDocResult.title, author: "Open Studio GmbH", likely_scanned: false, size_bytes: file?.size || 4_820_000 };
    endPage.value = Math.min(12, demoDocResult.pages);
    return;
  }
  inspectSourcePdf(true);
}

async function inspectSourcePdf(silent = false) {
  if (!pdfPath.value) return;
  if (DEMO) {
    if (!silent) toasts.info("Demo PDF inspected · 42 pages");
    return;
  }
  try {
    sourcePdfInfo.value = await api.post<any>("/pdf/inspect", { path: pdfPath.value });
    if (sourcePdfInfo.value?.page_count) {
      endPage.value = Math.min(Number(sourcePdfInfo.value.page_count), Number(endPage.value) || 10);
    }
    if (!silent) toasts.success(`PDF inspected · ${sourcePdfInfo.value.page_count} pages`);
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function onToolPdf(path: string, file: any) {
  if (!path.toLowerCase().endsWith(".pdf")) {
    toasts.error("Choose a PDF file for the PDF tools");
    return;
  }
  pdfToolPath.value = path;
  pdfToolInfo.value = null;
  pdfToolText.value = "";
  pdfToolWarnings.value = [];
  if (DEMO) {
    pdfToolInfo.value = { page_count: demoDocResult.pages, title: file?.name || demoDocResult.title, author: "Open Studio GmbH", likely_scanned: false, size_bytes: file?.size || 4_820_000 };
    return;
  }
  inspectPdfTool(true);
}

async function inspectPdfTool(silent = false) {
  if (!pdfToolPath.value) {
    toasts.error("Choose a PDF first");
    return;
  }
  pdfToolBusy.value = true;
  try {
    if (DEMO) {
      pdfToolInfo.value = { page_count: demoDocResult.pages, title: "Annual Report 2026", author: "Open Studio GmbH", likely_scanned: false, size_bytes: 4_820_000, producer: "Open Studio PDF" };
      toasts.info("Demo PDF inspected · 42 pages");
    } else {
      pdfToolInfo.value = await api.post<any>("/pdf/inspect", { path: pdfToolPath.value });
      toasts.success(`Inspected ${pdfToolInfo.value.page_count} pages`);
    }
    if (pdfToolInfo.value?.page_count) pdfToolEnd.value = Math.min(Number(pdfToolInfo.value.page_count), Number(pdfToolEnd.value) || 8);
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    pdfToolBusy.value = false;
    if (!silent && !pdfToolInfo.value) toasts.error("Could not inspect the PDF");
  }
}

async function extractPdfTool() {
  if (!pdfToolPath.value) {
    toasts.error("Choose a PDF first");
    return;
  }
  pdfToolExtracting.value = true;
  pdfToolWarnings.value = [];
  try {
    if (DEMO) {
      await delay(450);
      pdfToolText.value = `${demoDocResult.extracted}\n\n--- Page 3 ---\n\nRevenue rose 24%, driven by studio subscriptions and enterprise deployments. Inference latency fell by 38%.\n\n--- Page 4 ---\n\nPriorities for next year are video generation, multilingual voice and a unified document pipeline.`;
      pdfToolWarnings.value = ["OCR was not required for the selected pages."];
      toasts.success("Demo extraction ready");
    } else {
      const payload: Record<string, any> = { path: pdfToolPath.value, ocr_enabled: pdfToolOcr.value };
      if (pdfToolOcr.value) payload.ocr_language = pdfToolOcrLanguage.value;
      const pages = parsePageSelection(pdfToolSelectedPages.value);
      if (pages) payload.selected_pages = pages;
      else {
        const start = numberOrNull(pdfToolStart.value);
        const end = numberOrNull(pdfToolEnd.value);
        if (start) payload.start_page = start;
        if (end) payload.end_page = end;
      }
      const data = await api.post<any>("/pdf/extract", payload);
      pdfToolText.value = data.plain_text || "";
      pdfToolWarnings.value = data.warnings || [];
      if (data.page_count && !pdfToolInfo.value) pdfToolInfo.value = { page_count: data.page_count };
      toasts.success(`Extracted ${formatNumber(data.stats?.characters)} characters`);
    }
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    pdfToolExtracting.value = false;
  }
}

function sendPdfToWorkflow() {
  if (!pdfToolPath.value) return;
  pdfPath.value = pdfToolPath.value;
  sourceType.value = "pdf";
  sourcePdfInfo.value = pdfToolInfo.value;
  startPage.value = pdfToolStart.value;
  endPage.value = pdfToolEnd.value;
  selectedPagesText.value = pdfToolSelectedPages.value;
  ocrEnabled.value = pdfToolOcr.value;
  ocrLanguage.value = pdfToolOcrLanguage.value;
  tab.value = "workflow";
  toasts.success("PDF sent to the workflow");
}

function toggleTranslation() {
  if (!translationUnavailable.value) translationEnabled.value = !translationEnabled.value;
}

function toggleSummary() {
  if (!summaryUnavailable.value) summaryEnabled.value = !summaryEnabled.value;
}

function toggleTts() {
  if (!ttsUnavailable.value) ttsEnabled.value = !ttsEnabled.value;
}

function buildPipelineParams() {
  const input: Record<string, any> = { type: sourceType.value, language: inputLanguage.value };
  if (sourceType.value === "pdf") {
    input.pdf_path = pdfPath.value;
    input.ocr_enabled = ocrEnabled.value;
    if (ocrEnabled.value) input.ocr_language = ocrLanguage.value;
    const pages = parsePageSelection(selectedPagesText.value);
    if (pages) input.selected_pages = pages;
    else {
      const start = numberOrNull(startPage.value);
      const end = numberOrNull(endPage.value);
      if (start) input.start_page = start;
      if (end) input.end_page = end;
    }
  } else {
    input.text = sourceText.value;
  }
  const tts: Record<string, any> = {
    enabled: ttsEnabled.value,
    engine: ttsEngine.value,
    language: ttsLanguage.value || undefined,
    speed: Number(ttsSpeed.value),
    format: ttsFormat.value,
    normalize_audio: ttsNormalizeAudio.value,
    normalize_text: ttsNormalizeText.value,
    text_source: ttsTextSource.value,
  };
  if (ttsEngine.value === "piper") tts.piper_voice = piperVoice.value || undefined;
  else {
    tts.mode = ttsMode.value;
    tts.voice_id = voiceId.value || undefined;
  }
  return {
    title: (pipelineTitle.value.trim() || `Document workflow · ${sourceLabel.value}`).slice(0, 200),
    input,
    translation: {
      enabled: translationEnabled.value,
      source_language: translationSource.value,
      target_language: translationTarget.value,
      model: translationModel.value,
      num_beams: Number(translationParams.num_beams),
      max_length: Number(translationParams.max_length),
      temperature: Number(translationParams.temperature),
      length_penalty: Number(translationParams.length_penalty),
      repetition_penalty: Number(translationParams.repetition_penalty),
      no_repeat_ngram_size: Number(translationParams.no_repeat_ngram_size),
      batch_size: Number(translationParams.batch_size),
      preserve_markup: translationParams.preserve_markup,
      ...(Object.keys(parseGlossary(glossaryText.value)).length ? { glossary: parseGlossary(glossaryText.value) } : {}),
    },
    summary: {
      enabled: summaryEnabled.value,
      length: summaryLength.value,
      language: summaryLanguage.value,
      source_language: summarySourceLanguage.value,
      model: summaryModel.value,
      max_tokens: numberOrNull(summaryParams.max_tokens),
      min_tokens: numberOrNull(summaryParams.min_tokens),
      num_beams: Number(summaryParams.num_beams),
      temperature: Number(summaryParams.temperature),
      chunk_tokens: numberOrNull(summaryParams.chunk_tokens),
      hierarchical: summaryParams.hierarchical,
      from_translation: summaryParams.from_translation,
    },
    tts,
    subtitles: { enabled: subtitlesEnabled.value && ttsEnabled.value, format: subtitleFormat.value },
    zip: { enabled: zipEnabled.value },
  };
}

async function runPipeline() {
  if (runIssue.value) {
    toasts.error(runIssue.value);
    return;
  }
  if (DEMO) {
    result.value = buildDemoResult();
    seedResultTexts();
    resultKind.value = "summary";
    activeJobId.value = "job_33af9e88";
    tab.value = "workflow";
    toasts.success("Demo pipeline is preloaded with a completed run");
    return;
  }
  submitting.value = true;
  try {
    const job = await api.post<Job>("/docs/run", buildPipelineParams());
    jobs.upsert(job);
    jobs.connect();
    activeJobId.value = job.id;
    tab.value = "workflow";
    toasts.success("Document workflow queued");
    startPolling(job.id);
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    submitting.value = false;
  }
}

async function cancelActiveJob() {
  if (!activeJob.value) return;
  try {
    await jobs.cancel(activeJob.value.id);
    toasts.info("Cancellation requested");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function retryActiveJob() {
  if (!activeJob.value) return;
  try {
    const job = await jobs.retry(activeJob.value.id);
    activeJobId.value = job.id;
    startPolling(job.id);
    toasts.success("Job restarted");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function removeActiveJob() {
  if (!activeJob.value) return;
  const id = activeJob.value.id;
  if (DEMO) {
    jobs.items = jobs.items.filter((job) => job.id !== id);
    activeJobId.value = "";
    toasts.success("Job record removed");
    return;
  }
  try {
    await jobs.remove(id);
    if (activeJobId.value === id) activeJobId.value = "";
    toasts.success("Job record removed");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function startPolling(id: string) {
  stopPolling();
  pollTimer = window.setInterval(async () => {
    try {
      const job = await api.get<Job>(`/jobs/${id}`);
      jobs.upsert(job);
      if (!["queued", "running", "canceling"].includes(job.status)) stopPolling();
    } catch {
      // The SSE stream remains the primary source of updates.
    }
  }, 3500);
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = undefined;
  }
}

async function loadResults(jobId: string) {
  const job = jobs.byId(jobId);
  const data: any = job?.result?.data || {};
  let manifest: any = null;
  try {
    manifest = await api.get<any>(`/docs/jobs/${jobId}/manifest`);
  } catch {
    manifest = null;
  }
  const kinds: TextKind[] = ["extracted", "translation", "summary"];
  const loaded: Record<TextKind, string> = { extracted: "", translation: "", summary: "" };
  await Promise.all(
    kinds.map(async (kind) => {
      try {
        const info = await api.get<any>(`/docs/jobs/${jobId}/text/${kind}`);
        loaded[kind] = info.text || "";
      } catch {
        loaded[kind] = "";
      }
    }),
  );
  const artifacts = manifest?.artifacts || {};
  const source = data.source || manifest?.source || {};
  const files = dedupeFiles([...(job?.result?.files || []), ...(job?.artifacts || [])]);
  result.value = {
    jobId,
    title: manifest?.title || job?.title || "Document workflow",
    completedAt: job?.finished_at || manifest?.completed_at || new Date().toISOString(),
    source,
    pages: source.page_count || manifest?.stats?.pages || 0,
    extracted: loaded.extracted,
    translation: loaded.translation,
    summary: loaded.summary,
    stats: data.stats || manifest?.stats || {},
    languages: data.languages || manifest?.languages || {},
    warnings: data.warnings || manifest?.warnings || job?.warnings || [],
    audio: data.audio || manifest?.audio || {},
    srt: data.subtitles?.srt || artifacts.subtitles?.path || "",
    vtt: data.subtitles?.vtt || artifacts.captions?.path || "",
    zip: data.zip_path || artifacts.zip?.path || "",
    manifestPath: data.manifest_path || artifacts.manifest?.path || "",
    files,
    manifest: manifest || {
      job_id: jobId,
      title: job?.title,
      status: "completed",
      source,
      languages: data.languages,
      stats: data.stats,
      warnings: data.warnings,
      artifacts,
    },
    cues: manifest?.timeline || [],
  };
  seedResultTexts();
  resultKind.value = resultTexts.summary.trim() ? "summary" : resultTexts.translation.trim() ? "translation" : "extracted";
}

async function saveText(kind: TextKind) {
  if (!result.value) return;
  const text = resultTexts[kind];
  if (!text.trim()) {
    toasts.error("The text cannot be empty");
    return;
  }
  savingKind.value = kind;
  try {
    if (DEMO) {
      await delay(250);
    } else {
      await api.patch(`/docs/jobs/${result.value.jobId}/text/${kind}`, { text });
      if (result.value.manifest) {
        result.value.manifest.stats = result.value.manifest.stats || {};
        result.value.manifest.stats[`${kind}_words`] = wordCount(text);
        result.value.manifest.stats[`${kind}_characters`] = text.length;
      }
    }
    originalTexts[kind] = text;
    toasts.success(`${kind === "summary" ? "Summary" : kind === "translation" ? "Translation" : "Extracted text"} saved`);
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    savingKind.value = "";
  }
}

function resetText(kind: TextKind) {
  resultTexts[kind] = originalTexts[kind];
}

async function copyText(text: string) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    toasts.success("Copied to clipboard");
  } catch {
    toasts.error("Could not access the clipboard");
  }
}

function downloadText(kind: TextKind) {
  downloadRaw(resultTexts[kind], `${kind}.txt`);
}

function downloadRaw(text: string, filename: string) {
  if (!text) return;
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function stageIcon(state: string) {
  if (state === "done") return CheckCircle2;
  if (state === "active") return Loader2;
  if (state === "failed") return AlertTriangle;
  return CircleDashed;
}

function pdfPreviewUrl(path: string, page: number, width = 360) {
  return `/api/pdf/preview?path=${encodeURIComponent(path)}&page=${page}&width=${width}`;
}

function parsePageSelection(value: string): number[] | undefined {
  const raw = value.trim();
  if (!raw) return undefined;
  const result: number[] = [];
  for (const part of raw.split(/[,\s;]+/).filter(Boolean)) {
    const range = part.match(/^(\d+)\s*[-–]\s*(\d+)$/);
    if (range) {
      const start = Number(range[1]);
      const end = Number(range[2]);
      if (!start || !end || end < start) continue;
      for (let page = start; page <= end && page - start < 2000; page++) result.push(page);
    } else {
      const page = Number(part);
      if (Number.isFinite(page) && page > 0) result.push(page);
    }
  }
  const unique = Array.from(new Set(result)).sort((a, b) => a - b);
  return unique.length ? unique.slice(0, 2000) : undefined;
}

function parseGlossary(value: string): Record<string, string> {
  const terms: Record<string, string> = {};
  for (const line of value.split("\n")) {
    const match = line.match(/^\s*(.+?)\s*(?:=>|=|\t)\s*(.+?)\s*$/);
    if (match && match[1] && match[2]) terms[match[1].trim()] = match[2].trim();
  }
  return terms;
}

function numberOrNull(value: any): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function wordCount(text: string) {
  return text.trim() ? text.trim().split(/\s+/).filter(Boolean).length : 0;
}

function formatNumber(value: any) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return number.toLocaleString();
}

function formatStatValue(key: string, value: any) {
  if (key.endsWith("_seconds")) return formatDuration(Number(value));
  if (key.endsWith("_bytes")) return formatBytes(Number(value));
  if (typeof value === "number") return formatNumber(value);
  return String(value);
}

function formatTimestamp(seconds: number) {
  if (!Number.isFinite(seconds)) return "—";
  const total = Math.max(0, seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = Math.floor(total % 60);
  const millis = Math.round((total - Math.floor(total)) * 1000);
  return `${hours > 0 ? `${String(hours).padStart(2, "0")}:` : ""}${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
}

function cap(value: string) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1).replace(/[-_]/g, " ") : value;
}

function dedupeFiles(files: any[]) {
  const seen = new Set<string>();
  return files.filter((file) => {
    if (!file?.path || seen.has(file.path)) return false;
    seen.add(file.path);
    return true;
  });
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="PDF · text · translation · speech"
      title="Documents"
      subtitle="PDF or text in, finished package out: translate, summarize, narrate, align SRT/VTT and bundle a ZIP. Every artifact lands in the shared file tree and every stage is tracked by the job hub."
    >
      <template #actions>
        <span class="chip" :class="{ success: docsOnline, danger: !docsOnline }"><span class="dot" :class="docsOnline ? 'online' : 'offline'" /> docs</span>
        <span v-if="DEMO" class="chip active"><Sparkles :size="11" /> Demo run</span>
        <button class="btn btn-sm" :disabled="capsLoading" @click="loadCapabilities"><RefreshCw :size="13" :class="{ spin: capsLoading }" /> Capabilities</button>
      </template>
    </PageHeader>

    <div class="row-between" style="margin-bottom: 16px">
      <TabsBar v-model="tab" :tabs="tabs" />
      <div v-if="tab !== 'summary'" class="row small muted" style="gap: 8px">
        <span>{{ sourceLabel }}</span>
        <span>·</span>
        <span>{{ sourceRangeLabel }}</span>
      </div>
    </div>

    <!-- Workflow -------------------------------------------------------- -->
    <ServiceNotice
      :services="[
        { name: 'docs', label: 'Documents' },
        { name: 'pdf', label: 'PDF tools' },
        { name: 'summary', label: 'Summary' },
        { name: 'translation', label: 'Translation' },
      ]"
      title="Some document features are unavailable"
    />

    <div v-if="docsOnline && tab === 'workflow'" class="split">
      <div class="stack">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>Source</h3>
              <p>Choose a PDF from shared storage or paste text directly.</p>
            </div>
            <div class="tabs">
              <button class="tab" :class="{ active: sourceType === 'pdf' }" @click="sourceType = 'pdf'"><FileText :size="12" /> PDF</button>
              <button class="tab" :class="{ active: sourceType === 'text' }" @click="sourceType = 'text'"><FileText :size="12" /> Text</button>
            </div>
          </div>
          <div class="panel-body stack">
            <template v-if="sourceType === 'pdf'">
              <div class="file-row" style="padding: 0">
                <span class="file-icon"><FileText :size="16" /></span>
                <span class="grow" style="min-width: 0">
                  <span class="small strong truncate" style="display: block">{{ sourceLabel }}</span>
                  <span class="small muted truncate" style="display: block">{{ pdfPath || "No PDF selected" }}</span>
                </span>
                <button class="btn btn-sm" @click="sourcePickerOpen = true"><FolderOpen :size="13" /> Browse</button>
                <button class="btn btn-sm btn-ghost" :disabled="!pdfPath" @click="inspectSourcePdf(false)"><FileSearch :size="13" /> Inspect</button>
              </div>
              <div class="row" style="gap: 7px">
                <span class="chip">{{ sourcePagesLabel }}</span>
                <span v-if="sourcePdfInfo?.likely_scanned" class="chip warn"><ScanText :size="11" /> Scanned document</span>
                <span v-if="sourcePdfInfo?.title" class="chip"><FileJson :size="11" /> {{ sourcePdfInfo.title }}</span>
              </div>
              <div class="grid grid-3">
                <div class="field">
                  <label>Start page</label>
                  <input v-model.number="startPage" class="input" type="number" min="1" placeholder="1" />
                </div>
                <div class="field">
                  <label>End page</label>
                  <input v-model.number="endPage" class="input" type="number" min="1" :placeholder="sourcePdfInfo?.page_count ? String(sourcePdfInfo.page_count) : 'Last page'" />
                </div>
                <div class="field">
                  <label>Explicit pages</label>
                  <input v-model="selectedPagesText" class="input" placeholder="1, 3, 7-9" />
                </div>
              </div>
              <div class="small muted">Leave explicit pages empty to use the range. OCR is applied only to pages without a text layer.</div>
              <div class="grid grid-2">
                <div class="field">
                  <label>OCR scanned pages</label>
                  <button class="switch" :class="{ on: ocrEnabled }" :disabled="!caps?.pdfAvailable" @click="ocrEnabled = !ocrEnabled" />
                  <span class="hint">{{ caps?.ocrAvailable ? "Tesseract is available on this host." : "OCR is not available on this host." }}</span>
                </div>
                <div class="field">
                  <label>OCR language</label>
                  <select v-model="ocrLanguage" class="select" :disabled="!ocrEnabled">
                    <option v-for="language in ocrLanguageOptions" :key="language.code" :value="language.code">{{ language.label }} · {{ language.code }}</option>
                  </select>
                </div>
              </div>
              <div class="alert" v-if="!caps?.pdfAvailable">The PDF service is unavailable. Switch to text input or start the PDF worker.</div>
            </template>
            <template v-else>
              <div class="field">
                <label>Pasted text <span class="muted">{{ sourceText.length.toLocaleString() }} / {{ maxTextCharacters.toLocaleString() }}</span></label>
                <textarea v-model="sourceText" class="textarea" style="min-height: 210px" placeholder="Paste the document text here. Page markers like --- Page 2 --- are preserved through translation." />
              </div>
            </template>
            <div class="field" style="max-width: 280px">
              <label>Source language</label>
              <select v-model="inputLanguage" class="select">
                <option v-for="language in translationSourceOptions" :key="language.code" :value="language.code">{{ language.label }}</option>
              </select>
            </div>
            <div class="alert" v-if="!docsOnline"><AlertTriangle :size="13" style="vertical-align: -2px" /> The documents service is offline. The form stays visible but the pipeline cannot be queued.</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>Translation</h3>
              <p>Uses the shared translation service with page markers and glossaries preserved.</p>
            </div>
            <div class="row" style="gap: 8px">
              <span class="chip" :class="{ warn: translationUnavailable }"><Languages :size="11" /> {{ translationAvailable ? "shared service" : "unavailable" }}</span>
              <button class="switch" :class="{ on: translationEnabled }" :disabled="translationUnavailable" @click="toggleTranslation" />
            </div>
          </div>
          <div v-show="translationEnabled" class="panel-body stack">
            <div class="grid grid-3">
              <div class="field">
                <label>Source</label>
                <select v-model="translationSource" class="select">
                  <option v-for="language in translationSourceOptions" :key="language.code" :value="language.code">{{ language.label }}</option>
                </select>
              </div>
              <div class="field">
                <label>Target</label>
                <select v-model="translationTarget" class="select">
                  <option v-for="language in translationTargetOptions" :key="language.code" :value="language.code">{{ language.label }}</option>
                </select>
              </div>
              <div class="field">
                <label>Model</label>
                <select v-model="translationModel" class="select">
                  <option v-for="model in translationModelOptions" :key="model.id" :value="model.id" :disabled="model.available === false && model.id !== 'auto'">{{ model.name }}{{ model.available === false && model.id !== 'auto' ? " · not installed" : "" }}</option>
                </select>
              </div>
            </div>
            <button class="btn btn-sm btn-ghost" style="align-self: flex-start" @click="translationAdvanced = !translationAdvanced">
              <Gauge :size="12" /> {{ translationAdvanced ? "Hide" : "Show" }} generation controls
              <ChevronUp v-if="translationAdvanced" :size="12" /><ChevronDown v-else :size="12" />
            </button>
            <div v-if="translationAdvanced" class="stack">
              <div class="grid grid-4">
                <div class="field"><label>Num beams</label><input v-model.number="translationParams.num_beams" class="input" type="number" min="1" max="16" /></div>
                <div class="field"><label>Max length</label><input v-model.number="translationParams.max_length" class="input" type="number" min="8" max="4096" /></div>
                <div class="field"><label>Temperature</label><input v-model.number="translationParams.temperature" class="input" type="number" min="0" max="2" step="0.1" /></div>
                <div class="field"><label>Batch size</label><input v-model.number="translationParams.batch_size" class="input" type="number" min="1" max="64" /></div>
                <div class="field"><label>Length penalty</label><input v-model.number="translationParams.length_penalty" class="input" type="number" min="-5" max="5" step="0.1" /></div>
                <div class="field"><label>Repetition penalty</label><input v-model.number="translationParams.repetition_penalty" class="input" type="number" min="0.1" max="5" step="0.05" /></div>
                <div class="field"><label>No repeat n-gram</label><input v-model.number="translationParams.no_repeat_ngram_size" class="input" type="number" min="0" max="10" /></div>
                <div class="field">
                  <label>Preserve markup</label>
                  <button class="switch" :class="{ on: translationParams.preserve_markup }" @click="translationParams.preserve_markup = !translationParams.preserve_markup" />
                </div>
              </div>
              <div class="field">
                <label>Glossary <span class="muted">one term per line · source = target</span></label>
                <textarea v-model="glossaryText" class="textarea" style="min-height: 72px" placeholder="Open Studio = Open Studio&#10;local-first = local-first" />
              </div>
            </div>
            <div class="alert" v-if="translationUnavailable">Translation is enabled but no shared translation service was detected. Disable it or start the translation worker.</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>Summary</h3>
              <p>Hierarchical T5 summary with a target length and language.</p>
            </div>
            <div class="row" style="gap: 8px">
              <span class="chip" :class="{ warn: summaryUnavailable }"><ListChecks :size="11" /> {{ summaryAvailable ? "T5" : "unavailable" }}</span>
              <button class="switch" :class="{ on: summaryEnabled }" :disabled="summaryUnavailable" @click="toggleSummary" />
            </div>
          </div>
          <div v-show="summaryEnabled" class="panel-body stack">
            <div class="grid grid-4">
              <div class="field">
                <label>Length</label>
                <select v-model="summaryLength" class="select">
                  <option v-for="length in summaryLengthOptions" :key="length.id" :value="length.id">{{ length.label }}{{ length.max_tokens ? ` · ~${length.max_tokens} tok` : "" }}</option>
                </select>
              </div>
              <div class="field">
                <label>Summary language</label>
                <select v-model="summaryLanguage" class="select">
                  <option v-for="language in summaryLanguageOptions" :key="language.code" :value="language.code">{{ language.label }}</option>
                </select>
              </div>
              <div class="field">
                <label>Source language</label>
                <select v-model="summarySourceLanguage" class="select">
                  <option v-for="language in summarySourceOptions" :key="language.code" :value="language.code">{{ language.label }}</option>
                </select>
              </div>
              <div class="field">
                <label>Model</label>
                <select v-model="summaryModel" class="select">
                  <option v-for="model in summaryModelOptions" :key="model.id" :value="model.id" :disabled="model.available === false && model.id !== 'auto'">{{ model.name }}{{ model.available === false && model.id !== 'auto' ? " · not installed" : "" }}</option>
                </select>
              </div>
            </div>
            <button class="btn btn-sm btn-ghost" style="align-self: flex-start" @click="summaryAdvanced = !summaryAdvanced">
              <Gauge :size="12" /> {{ summaryAdvanced ? "Hide" : "Show" }} decoding controls
              <ChevronUp v-if="summaryAdvanced" :size="12" /><ChevronDown v-else :size="12" />
            </button>
            <div v-if="summaryAdvanced" class="stack">
              <div class="grid grid-4">
                <div class="field"><label>Max tokens</label><input v-model.number="summaryParams.max_tokens" class="input" type="number" min="16" max="4096" placeholder="Auto" /></div>
                <div class="field"><label>Min tokens</label><input v-model.number="summaryParams.min_tokens" class="input" type="number" min="0" max="4096" placeholder="0" /></div>
                <div class="field"><label>Num beams</label><input v-model.number="summaryParams.num_beams" class="input" type="number" min="1" max="16" /></div>
                <div class="field"><label>Temperature</label><input v-model.number="summaryParams.temperature" class="input" type="number" min="0" max="2" step="0.1" /></div>
                <div class="field"><label>Chunk tokens</label><input v-model.number="summaryParams.chunk_tokens" class="input" type="number" min="64" max="2048" placeholder="Auto" /></div>
                <div class="field">
                  <label>Hierarchical</label>
                  <button class="switch" :class="{ on: summaryParams.hierarchical }" @click="summaryParams.hierarchical = !summaryParams.hierarchical" />
                </div>
                <div class="field">
                  <label>Summarize translation</label>
                  <button class="switch" :class="{ on: summaryParams.from_translation }" @click="summaryParams.from_translation = !summaryParams.from_translation" />
                </div>
              </div>
            </div>
            <div class="alert" v-if="summaryUnavailable">The summary service is not installed. Disable summary or start the summary worker.</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>Voice, subtitles &amp; bundle</h3>
              <p>Narrate the summary or translated content, then align captions.</p>
            </div>
            <div class="row" style="gap: 8px">
              <span class="chip" :class="{ warn: ttsUnavailable }"><Volume2 :size="11" /> {{ ttsAvailable ? "voice" : "unavailable" }}</span>
              <button class="switch" :class="{ on: ttsEnabled }" :disabled="ttsUnavailable" @click="toggleTts" />
            </div>
          </div>
          <div v-show="ttsEnabled" class="panel-body stack">
            <div class="grid grid-3">
              <div class="field">
                <label>Engine</label>
                <select v-model="ttsEngine" class="select">
                  <option v-for="engine in ttsEngineOptions" :key="engine.id" :value="engine.id" :disabled="!engine.available">{{ engine.name }}{{ engine.detail ? ` · ${engine.detail}` : "" }}</option>
                </select>
              </div>
              <div v-if="ttsEngine === 'omnivoice'" class="field">
                <label>Mode</label>
                <select v-model="ttsMode" class="select">
                  <option value="voice">Cloned voice</option>
                  <option value="auto">Automatic voice</option>
                </select>
              </div>
              <div v-if="ttsEngine === 'omnivoice'" class="field">
                <label>Voice profile</label>
                <select v-model="voiceId" class="select">
                  <option value="">Automatic selection</option>
                  <option v-for="voice in voiceOptions" :key="voice.id" :value="voice.id">{{ voice.name }}{{ voice.detail ? ` · ${voice.detail}` : "" }}</option>
                </select>
              </div>
              <div v-else class="field">
                <label>Piper voice</label>
                <select v-model="piperVoice" class="select">
                  <option v-for="voice in piperVoiceOptions" :key="voice.id" :value="voice.id" :disabled="!voice.available">{{ voice.name }}{{ voice.detail ? ` · ${voice.detail}` : "" }}</option>
                </select>
              </div>
              <div class="field">
                <label>Language</label>
                <select v-model="ttsLanguage" class="select">
                  <option value="">Match content language</option>
                  <option v-for="language in voiceLanguageOptions" :key="language.code" :value="language.code">{{ language.label }}</option>
                </select>
              </div>
              <div class="field">
                <label>Speed</label>
                <input v-model.number="ttsSpeed" class="input" type="number" min="0.5" max="2" step="0.05" />
              </div>
              <div class="field">
                <label>Format</label>
                <select v-model="ttsFormat" class="select">
                  <option v-for="format in ttsFormatOptions" :key="format" :value="format">{{ format.toUpperCase() }}</option>
                </select>
              </div>
              <div class="field">
                <label>Narrate</label>
                <select v-model="ttsTextSource" class="select">
                  <option value="content">Translated content</option>
                  <option value="summary" :disabled="!summaryEnabled">Summary</option>
                </select>
              </div>
            </div>
            <div class="grid grid-3">
              <div class="field">
                <label>Normalize text</label>
                <button class="switch" :class="{ on: ttsNormalizeText }" @click="ttsNormalizeText = !ttsNormalizeText" />
              </div>
              <div class="field">
                <label>Normalize loudness</label>
                <button class="switch" :class="{ on: ttsNormalizeAudio }" @click="ttsNormalizeAudio = !ttsNormalizeAudio" />
              </div>
              <div class="field">
                <label>Subtitles</label>
                <div class="row">
                  <button class="switch" :class="{ on: subtitlesEnabled }" :disabled="!ttsEnabled" @click="subtitlesEnabled = !subtitlesEnabled" />
                  <select v-model="subtitleFormat" class="select" style="width: 96px" :disabled="!subtitlesEnabled">
                    <option v-for="format in subtitleFormatOptions" :key="format" :value="format">{{ format.toUpperCase() }}</option>
                  </select>
                </div>
                <span class="hint">Cues follow the narration timeline.</span>
              </div>
              <div class="field">
                <label>ZIP bundle</label>
                <button class="switch" :class="{ on: zipEnabled }" @click="zipEnabled = !zipEnabled" />
                <span class="hint">Manifest, text, audio, subtitles and previews.</span>
              </div>
            </div>
            <div class="alert" v-if="ttsUnavailable">Voice synthesis is disabled by the service catalogue. The rest of the pipeline can still run.</div>
          </div>
        </section>
      </div>

      <div class="stack workflow-rail">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>Run pipeline</h3>
              <p>{{ enabledStageCount }} stages · one job hub entry</p>
            </div>
            <span class="chip" :class="{ success: result }"><Archive :size="11" /> {{ result ? "bundle ready" : "not run" }}</span>
          </div>
          <div class="panel-body stack">
            <div class="field">
              <label>Bundle title</label>
              <input v-model="pipelineTitle" class="input" :placeholder="`Document workflow · ${sourceLabel}`" />
            </div>
            <div class="stage-list">
              <div v-for="stage in pipelineStages" :key="stage.id" class="stage-row" :class="stage.state">
                <span class="stage-icon"><component :is="stageIcon(stage.state)" :size="15" :class="{ spin: stage.state === 'active' }" /></span>
                <span class="grow" style="min-width: 0">
                  <span class="small strong" style="display: block">{{ stage.label }}</span>
                  <span class="small muted" style="display: block">{{ stage.detail }}</span>
                </span>
                <span class="badge" :class="{ success: stage.state === 'done', running: stage.state === 'active', failed: stage.state === 'failed' }">{{ stage.state }}</span>
              </div>
            </div>
            <div v-if="runIssue" class="alert warn"><AlertTriangle :size="13" style="vertical-align: -2px" /> {{ runIssue }}</div>
            <div v-if="capsError" class="alert error">{{ capsError }}</div>
            <button class="btn btn-primary btn-lg btn-block" :disabled="!canRun || submitting || activeJobRunning" @click="runPipeline">
              <Loader2 v-if="submitting || activeJobRunning" :size="15" class="spin" />
              <Play v-else :size="15" />
              {{ activeJobRunning ? "Pipeline running…" : submitting ? "Queueing…" : "Run document pipeline" }}
            </button>
            <div class="row-between small muted">
              <span>{{ sourceRangeLabel }}</span>
              <span>{{ translationEnabled ? `${translationSource} → ${translationTarget}` : "no translation" }}</span>
            </div>
            <JobCard v-if="activeJob" :job="activeJob" compact @cancel="cancelActiveJob" @retry="retryActiveJob" @remove="removeActiveJob" />
            <div v-else class="alert">The job hub will report each stage here with live progress and a cancel action.</div>
          </div>
        </section>

        <section v-if="result" class="panel">
          <div class="panel-head">
            <div>
              <h3>Completed bundle</h3>
              <p>{{ result.title }} · {{ relativeTime(result.completedAt) }}</p>
            </div>
            <span class="badge success">ready</span>
          </div>
          <div class="panel-body stack">
            <div class="mini-stats">
              <div v-for="card in resultStatCards.slice(0, 3)" :key="card.label" class="mini-stat">
                <span>{{ card.label }}</span>
                <strong>{{ card.value }}</strong>
                <small>{{ card.sub }}</small>
              </div>
            </div>
            <div class="field">
              <label>Summary <span class="muted">{{ wordCount(resultTexts.summary) }} words</span></label>
              <textarea v-model="resultTexts.summary" class="textarea" style="min-height: 116px" />
            </div>
            <div class="row-between">
              <button class="btn btn-sm btn-ghost" :disabled="!resultTexts.summary" @click="copyText(resultTexts.summary)"><Copy :size="12" /> Copy</button>
              <button class="btn btn-sm btn-primary" :disabled="!resultSummaryDirty || savingKind === 'summary'" @click="saveText('summary')">
                <Loader2 v-if="savingKind === 'summary'" :size="12" class="spin" /><Save v-else :size="12" /> Save summary
              </button>
            </div>
            <AudioPlayer :src="resultAudioSrc" :title="resultAudioTitle" :subtitle="resultAudioSubtitle" :download-path="resultAudioSrc || null" compact />
            <div class="row" style="gap: 6px">
              <a v-if="result.srt" class="btn btn-sm" :href="downloadUrl(result.srt)"><Subtitles :size="12" /> SRT</a>
              <a v-if="result.vtt" class="btn btn-sm" :href="downloadUrl(result.vtt)"><Captions :size="12" /> VTT</a>
              <a v-if="result.zip" class="btn btn-sm" :href="downloadUrl(result.zip)"><FileArchive :size="12" /> ZIP</a>
              <a v-if="result.manifestPath" class="btn btn-sm btn-ghost" :href="downloadUrl(result.manifestPath)"><FileJson :size="12" /> Manifest</a>
            </div>
            <div v-if="resultCues.length" class="stack" style="gap: 6px">
              <div class="row-between"><span class="small strong">Synchronized cues</span><span class="chip">{{ resultCues.length }}</span></div>
              <div v-for="cue in resultCues.slice(0, 4)" :key="cue.index" class="cue-mini">
                <span class="mono small muted">{{ formatTimestamp(cue.start) }}</span>
                <span class="small truncate">{{ cue.text }}</span>
              </div>
            </div>
            <button class="btn btn-sm btn-block" @click="tab = 'results'"><Sparkles :size="12" /> Open full results</button>
          </div>
        </section>
      </div>
    </div>

    <!-- PDF tools ------------------------------------------------------- -->
    <div v-else-if="pdfOnline && tab === 'pdf'" class="stack">
      <div class="split">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>PDF inspection</h3>
              <p>Inspect page counts, preview pages and extract text with optional OCR.</p>
            </div>
            <span class="chip" :class="{ warn: !pdfOnline }"><FileSearch :size="11" /> {{ pdfOnline ? "pdf service" : "offline" }}</span>
          </div>
          <div class="panel-body stack">
            <div class="file-row" style="padding: 0">
              <span class="file-icon"><FileText :size="16" /></span>
              <span class="grow" style="min-width: 0">
                <span class="small strong truncate" style="display: block">{{ toolPreviewTitle }}</span>
                <span class="small muted truncate" style="display: block">{{ pdfToolPath || "No PDF selected" }}</span>
              </span>
              <button class="btn btn-sm" @click="toolsPickerOpen = true"><FolderOpen :size="13" /> Browse</button>
              <button class="btn btn-sm btn-ghost" :disabled="!pdfToolPath || pdfToolBusy" @click="inspectPdfTool(false)">
                <Loader2 v-if="pdfToolBusy" :size="13" class="spin" /><FileSearch v-else :size="13" /> Inspect
              </button>
            </div>
            <div class="grid grid-3">
              <div class="field"><label>Start page</label><input v-model.number="pdfToolStart" class="input" type="number" min="1" placeholder="1" /></div>
              <div class="field"><label>End page</label><input v-model.number="pdfToolEnd" class="input" type="number" min="1" :placeholder="pdfToolInfo?.page_count ? String(pdfToolInfo.page_count) : 'Last page'" /></div>
              <div class="field"><label>Explicit pages</label><input v-model="pdfToolSelectedPages" class="input" placeholder="1, 3, 7-9" /></div>
            </div>
            <div class="grid grid-2">
              <div class="field">
                <label>OCR</label>
                <div class="row">
                  <button class="switch" :class="{ on: pdfToolOcr }" @click="pdfToolOcr = !pdfToolOcr" />
                  <select v-model="pdfToolOcrLanguage" class="select" :disabled="!pdfToolOcr">
                    <option v-for="language in ocrLanguageOptions" :key="language.code" :value="language.code">{{ language.label }}</option>
                  </select>
                </div>
              </div>
              <div class="field">
                <label>Selected range</label>
                <span class="chip" style="align-self: flex-start">{{ toolRangeLabel }}</span>
              </div>
            </div>
            <div class="row">
              <button class="btn btn-primary" :disabled="!pdfToolPath || pdfToolExtracting || !pdfOnline" @click="extractPdfTool">
                <Loader2 v-if="pdfToolExtracting" :size="14" class="spin" /><ScanText v-else :size="14" /> Extract text
              </button>
              <button class="btn" :disabled="!pdfToolPath" @click="sendPdfToWorkflow"><Wand2 :size="14" /> Send to workflow</button>
            </div>
            <div v-if="pdfToolMeta.length" class="meta-grid">
              <div v-for="item in pdfToolMeta" :key="item.label" class="meta-cell">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
            </div>
            <div v-for="warning in pdfToolWarnings" :key="warning" class="alert warn">{{ warning }}</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>Extract result</h3>
              <p>Plain text with page markers, ready for translation or summarization.</p>
            </div>
            <div class="row" style="gap: 6px">
              <button class="btn btn-sm btn-ghost" :disabled="!pdfToolText" @click="copyText(pdfToolText)"><Copy :size="12" /> Copy</button>
              <button class="btn btn-sm btn-ghost" :disabled="!pdfToolText" @click="downloadRaw(pdfToolText, 'extracted.txt')"><Download :size="12" /></button>
            </div>
          </div>
          <div class="panel-body">
            <textarea v-model="pdfToolText" class="textarea mono" style="min-height: 410px" readonly placeholder="Extracted text appears here." />
            <div class="row-between small muted" style="margin-top: 8px">
              <span>{{ wordCount(pdfToolText) }} words</span>
              <span>{{ pdfToolText.length.toLocaleString() }} characters</span>
            </div>
          </div>
        </section>
      </div>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Page previews</h3>
            <p>Rendered by the PDF service at a thumbnail width. Click a page to open it at full size.</p>
          </div>
          <span class="chip">{{ pdfToolPreviewItems.length }} pages</span>
        </div>
        <div class="panel-body">
          <div v-if="pdfToolPreviewItems.length" class="preview-grid">
            <a v-for="page in pdfToolPreviewItems" :key="page.page" class="preview-card" :href="page.url" target="_blank" rel="noopener">
              <img :src="page.url" :alt="`Page ${page.page}`" loading="lazy" />
              <span>Page {{ page.page }}</span>
            </a>
          </div>
          <EmptyState v-else :icon="FileSearch" title="No preview yet" message="Choose a PDF and inspect it to render its first pages here." />
        </div>
      </section>
    </div>

    <!-- Results --------------------------------------------------------- -->
    <div v-else-if="docsOnline && tab === 'results'" class="stack">
      <template v-if="result">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>{{ result.title }}</h3>
              <p>{{ result.source?.filename || sourceLabel }} · {{ formatNumber(result.pages) }} pages · completed {{ relativeTime(result.completedAt) }}</p>
            </div>
            <div class="row">
              <span class="badge success">completed</span>
              <a v-if="result.zip" class="btn btn-sm" :href="downloadUrl(result.zip)"><FileArchive :size="13" /> Download bundle</a>
            </div>
          </div>
          <div class="panel-body stack">
            <div class="stat-grid">
              <div v-for="card in resultStatCards" :key="card.label" class="stat">
                <div class="stat-label">{{ card.label }}</div>
                <div class="stat-value">{{ card.value }}</div>
                <div class="stat-sub">{{ card.sub }}</div>
              </div>
            </div>
            <div class="row" style="gap: 7px">
              <a v-if="result.srt" class="btn btn-sm" :href="downloadUrl(result.srt)"><Subtitles :size="12" /> subtitles.srt</a>
              <a v-if="result.vtt" class="btn btn-sm" :href="downloadUrl(result.vtt)"><Captions :size="12" /> captions.vtt</a>
              <a v-if="result.manifestPath" class="btn btn-sm" :href="downloadUrl(result.manifestPath)"><FileJson :size="12" /> manifest.json</a>
              <a v-if="resultAudioSrc" class="btn btn-sm" :href="downloadUrl(resultAudioSrc)"><AudioLines :size="12" /> audio</a>
              <span class="chip" style="margin-left: auto">{{ resultBundleFiles.length }} bundle files</span>
            </div>
            <div v-for="warning in result.warnings" :key="warning" class="alert warn">{{ warning }}</div>
          </div>
        </section>

        <div class="split">
          <section class="panel">
            <div class="panel-head">
              <TabsBar v-model="resultKind" :tabs="resultTextTabs" />
              <div class="row" style="gap: 6px">
                <button class="btn btn-sm btn-ghost" :disabled="!resultTexts[resultKind]" @click="copyText(resultTexts[resultKind])"><Copy :size="12" /> Copy</button>
                <button class="btn btn-sm btn-ghost" :disabled="!resultTexts[resultKind]" @click="downloadText(resultKind)"><Download :size="12" /></button>
                <button class="btn btn-sm btn-primary" :disabled="!resultTextDirty || savingKind === resultKind" @click="saveText(resultKind)">
                  <Loader2 v-if="savingKind === resultKind" :size="12" class="spin" /><Save v-else :size="12" /> Save
                </button>
              </div>
            </div>
            <div class="panel-body stack">
              <div v-if="resultTexts[resultKind]" class="field">
                <label>{{ activeTextLabel }} <span class="muted">{{ wordCount(resultTexts[resultKind]) }} words · {{ resultTexts[resultKind].length.toLocaleString() }} characters</span></label>
                <textarea v-model="resultTexts[resultKind]" class="textarea" style="min-height: 430px" spellcheck="false" />
              </div>
              <EmptyState v-else :icon="FileText" :title="`No ${activeTextLabel.toLowerCase()}`" message="This stage was disabled or did not produce text for the selected pages." />
              <div class="row-between">
                <span class="small muted">Edits are written back to the job's text artifact and manifest.</span>
                <button class="btn btn-sm btn-ghost" :disabled="!resultTextDirty" @click="resetText(resultKind)">Reset</button>
              </div>
            </div>
          </section>

          <div class="stack">
            <section class="panel">
              <div class="panel-head">
                <div>
                  <h3>Narration</h3>
                  <p>{{ resultAudioSubtitle || "No audio was produced." }}</p>
                </div>
                <span class="chip"><Volume2 :size="11" /> {{ result.audio?.duration_seconds ? formatDuration(result.audio.duration_seconds) : "—" }}</span>
              </div>
              <div class="panel-body">
                <AudioPlayer :src="resultAudioSrc" :title="resultAudioTitle" :subtitle="resultAudioSubtitle" :download-path="resultAudioSrc || null" />
              </div>
            </section>

            <section class="panel">
              <div class="panel-head">
                <div>
                  <h3>Manifest stats</h3>
                  <p>Everything the pipeline recorded for this bundle.</p>
                </div>
                <span class="chip"><ListChecks :size="11" /> {{ manifestStatRows.length }}</span>
              </div>
              <div class="panel-body stack" style="gap: 7px">
                <div v-for="row in manifestStatRows" :key="row.key" class="row-between small">
                  <span class="muted" style="text-transform: capitalize">{{ row.label }}</span>
                  <span class="mono strong" style="text-align: right">{{ row.value }}</span>
                </div>
                <div v-if="!manifestStatRows.length" class="small muted">No stats were recorded.</div>
                <details class="manifest-details">
                  <summary class="small muted">Raw manifest JSON</summary>
                  <CodeBlock :code="manifestJson" label="manifest.json" />
                </details>
              </div>
            </section>

            <section class="panel">
              <div class="panel-head">
                <h3>Bundle files</h3>
                <span class="chip">{{ resultBundleFiles.length }}</span>
              </div>
              <div class="panel-body list" style="padding-top: 6px">
                <div v-for="file in resultBundleFiles" :key="file.path" class="list-item" style="padding: 7px 0">
                  <span class="file-icon" style="width: 30px; height: 30px"><FileText :size="13" /></span>
                  <span class="grow" style="min-width: 0">
                    <span class="small strong truncate" style="display: block">{{ file.name || file.path.split("/").pop() }}</span>
                    <span class="small muted mono truncate" style="display: block">{{ file.path }}</span>
                  </span>
                  <span class="small muted nowrap">{{ file.size ? formatBytes(file.size) : "—" }}</span>
                  <a class="icon-btn" :href="downloadUrl(file.path)" title="Download"><Download :size="14" /></a>
                </div>
                <div v-if="!resultBundleFiles.length" class="small muted">The bundle file list is not available yet.</div>
              </div>
            </section>
          </div>
        </div>

        <section v-if="resultPreviews.length" class="panel">
          <div class="panel-head">
            <div>
              <h3>Page previews</h3>
              <p>Rendered from the source PDF selected for this job.</p>
            </div>
            <span class="chip">{{ resultPreviews.length }} pages</span>
          </div>
          <div class="panel-body">
            <div class="preview-grid">
              <a v-for="page in resultPreviews" :key="page.page" class="preview-card" :href="page.url" target="_blank" rel="noopener">
                <img :src="page.url" :alt="`Page ${page.page}`" loading="lazy" />
                <span>Page {{ page.page }}</span>
              </a>
            </div>
          </div>
        </section>

        <section v-if="resultCues.length" class="panel">
          <div class="panel-head">
            <div>
              <h3>Synchronized cues</h3>
              <p>SRT/VTT timings aligned to the narration timeline.</p>
            </div>
            <div class="row">
              <span class="chip">{{ resultCues.length }} cues</span>
              <a v-if="result.srt" class="btn btn-sm btn-ghost" :href="downloadUrl(result.srt)"><Download :size="12" /> SRT</a>
            </div>
          </div>
          <div class="panel-body">
            <table class="table cue-table">
              <thead><tr><th>#</th><th>Start</th><th>End</th><th>Cue text</th></tr></thead>
              <tbody>
                <tr v-for="cue in resultCues" :key="cue.index">
                  <td class="mono muted">{{ cue.index }}</td>
                  <td class="mono">{{ formatTimestamp(cue.start) }}</td>
                  <td class="mono">{{ formatTimestamp(cue.end) }}</td>
                  <td class="cue-text">{{ cue.text }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
      <EmptyState v-else :icon="FileText" title="No document bundle yet" message="Configure the workflow and run a PDF or text document through translation, summarization, narration and subtitles. The complete result will appear here.">
        <button class="btn btn-primary" @click="tab = 'workflow'"><Play :size="13" /> Open workflow</button>
      </EmptyState>
    </div>

    <!-- Translation ----------------------------------------------------- -->
    <template v-if="translateMounted && translationOnline">
      <TranslateView v-show="tab === 'translate'" embedded />
    </template>

    <!-- Summary --------------------------------------------------------- -->
    <template v-if="summaryMounted && summaryOnline">
      <SummaryPanel v-show="tab === 'summary'" embedded @open-workflow="tab = 'workflow'" />
    </template>

    <FilePicker v-model="sourcePickerOpen" title="Choose a PDF" kind="document" accept=".pdf" @selected="onSourcePdf" />
    <FilePicker v-model="toolsPickerOpen" title="Choose a PDF" kind="document" accept=".pdf" @selected="onToolPdf" />
  </div>
</template>

<style scoped>
.stage-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.workflow-rail {
  position: sticky;
  top: 86px;
}
@media (max-width: 1200px) {
  .workflow-rail { position: static; }
}
.stage-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 9px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.32);
}
.stage-row.done { border-color: rgba(52, 211, 153, 0.24); }
.stage-row.active { border-color: rgba(139, 92, 246, 0.42); background: rgba(139, 92, 246, 0.08); }
.stage-row.failed { border-color: rgba(251, 113, 133, 0.35); }
.stage-row.skipped { opacity: 0.5; }
.stage-icon { display: grid; place-items: center; color: var(--muted); flex: none; }
.stage-row.done .stage-icon { color: var(--success); }
.stage-row.active .stage-icon { color: #c4b5fd; }
.stage-row.failed .stage-icon { color: var(--danger); }
.stage-row .badge { font-size: 8.5px; }

.mini-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 7px;
}
.mini-stat {
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.35);
  padding: 8px;
  min-width: 0;
}
.mini-stat span, .mini-stat small { display: block; font-size: 9px; color: var(--muted-2); text-transform: uppercase; letter-spacing: 0.06em; }
.mini-stat strong { display: block; font-family: var(--display); font-size: 16px; margin: 3px 0; }

.cue-mini {
  display: grid;
  grid-template-columns: 66px minmax(0, 1fr);
  gap: 8px;
  align-items: center;
  padding: 5px 7px;
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.025);
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 7px;
}
.meta-cell {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 7px 9px;
  background: rgba(8, 10, 15, 0.35);
}
.meta-cell span { display: block; font-size: 9px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted-2); }
.meta-cell strong { display: block; font-size: 11.5px; margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.preview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}
.preview-card {
  display: block;
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  background: var(--bg-soft);
  transition: 160ms ease;
}
.preview-card:hover { border-color: var(--line-strong); transform: translateY(-2px); }
.preview-card img {
  display: block;
  width: 100%;
  aspect-ratio: 3 / 4;
  object-fit: cover;
  object-position: top center;
  background: #0b0d13;
}
.preview-card span {
  display: block;
  padding: 6px 8px;
  font-size: 10px;
  color: var(--muted);
  border-top: 1px solid var(--line);
}

.manifest-details summary { cursor: pointer; user-select: none; margin-bottom: 6px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.switch:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
