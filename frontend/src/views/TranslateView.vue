<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import {
  AlertTriangle,
  ArrowLeftRight,
  ArrowRight,
  BookOpen,
  Clock,
  Copy,
  Cpu,
  Download,
  FolderOpen,
  Gauge,
  Hash,
  Languages,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
  Wand2,
} from "lucide-vue-next";
import { api, formatDuration, relativeTime } from "@/lib/api";
import { DEMO } from "@/lib/types";
import type { Job } from "@/lib/types";
import { demoTranslateLanguages, demoTranslation } from "@/lib/demo";
import { useJobsStore } from "@/stores/jobs";
import { useSystemStore } from "@/stores/system";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import FilePicker from "@/components/FilePicker.vue";
import JobCard from "@/components/JobCard.vue";
import EmptyState from "@/components/EmptyState.vue";

const jobs = useJobsStore();
const system = useSystemStore();
const toasts = useToastStore();

const DEMO_SOURCE = `A cidade fecha os olhos devagar
Eu conto os passos até te encontrar
Há luz nas janelas que ninguém apagou
E um fio de voz que nunca se calou

Nocturno, nocturno
Dança comigo no escuro
Nocturno, nocturno
Até o silêncio ficar maduro`;

const DEMO_MODELS = [
  { id: "auto", name: "Auto · OPUS-MT preferred", available: true, family: "auto", detail: "Picks the best installed pair" },
  { id: "opus-mt-pt-en", name: "OPUS-MT · Portuguese → English", available: true, family: "opus-mt", detail: "Helsinki-NLP · 77M" },
  { id: "opus-mt-en-pt", name: "OPUS-MT · English → Portuguese", available: true, family: "opus-mt", detail: "Helsinki-NLP · 77M" },
  { id: "nllb-200-distilled-600M", name: "NLLB-200 distilled 600M · multilingual", available: true, family: "nllb", detail: "200 languages · optional install" },
];

const COMMON_LANGUAGE_NAMES: Record<string, string> = {
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
  zh: "Chinese (Simplified)",
  "zh-Hant": "Chinese (Traditional)",
  nl: "Dutch",
  pl: "Polish",
  ru: "Russian",
  uk: "Ukrainian",
  tr: "Turkish",
  ar: "Arabic",
  hi: "Hindi",
  ko: "Korean",
};

interface HistoryEntry {
  id: string;
  createdAt: string;
  sourceLanguage: string;
  targetLanguage: string;
  model: string;
  modelLabel: string;
  characters: number;
  duration: number;
  preview: string;
  sourceText: string;
  resultText: string;
  stats: Record<string, any>;
  warnings: string[];
}

const source = ref(DEMO ? DEMO_SOURCE : "");
const result = ref(DEMO ? demoTranslation.translated_text : "");
const sourceLanguage = ref("pt");
const targetLanguage = ref("en");
const model = ref("auto");
const detected = ref<any>(DEMO ? { language: "pt", name: "Portuguese", confidence: 0.99 } : null);
const detectedLoading = ref(false);
const loading = ref(false);
const submittingJob = ref(false);
const serviceBusy = ref(false);
const serviceError = ref("");
const statusInfo = ref<any>(DEMO ? { status: "ok", device: "cpu", cpu_threads: 12, loaded_model: "opus-mt-pt-en", runtime: { torch: true, transformers: true, sentencepiece: true, langdetect: true } } : null);
const languageNames = ref<Record<string, string>>({ ...COMMON_LANGUAGE_NAMES });
const sourceLanguageList = ref<string[]>(DEMO ? demoTranslateLanguages.source : ["auto", "pt", "pt-PT", "pt-BR", "en", "es", "fr", "de"]);
const targetLanguageList = ref<string[]>(DEMO ? demoTranslateLanguages.target : ["en", "pt-PT", "pt-BR", "es", "fr", "de"]);
const modelItems = ref<any[]>(DEMO ? DEMO_MODELS : [{ id: "auto", name: "Auto · best available", available: true, family: "auto", detail: "" }]);
const filePickerOpen = ref(false);
const activeJobId = ref("");
const savePath = ref(DEMO ? "documents/translation/nocturne-pt-en.txt" : "documents/translation/translation.txt");
const history = ref<HistoryEntry[]>([]);
let pollTimer: number | undefined;

const params = reactive<Record<string, any>>({
  num_beams: 4,
  max_length: 512,
  temperature: 0,
  length_penalty: 1,
  repetition_penalty: 1,
  no_repeat_ngram_size: 3,
  batch_size: 8,
  preserve_markup: true,
});

const glossary = ref<Array<{ source: string; target: string }>>(
  DEMO
    ? [
        { source: "Nocturno", target: "Nocturne" },
        { source: "Open Studio", target: "Open Studio" },
      ]
    : [],
);

const resultMeta = ref<any>(
  DEMO
    ? {
        model: demoTranslation.model,
        modelLabel: "OPUS-MT · Portuguese → English",
        duration: demoTranslation.duration_seconds,
        stats: {
          ...demoTranslation.stats,
          input_characters: DEMO_SOURCE.length,
          input_words: countWords(DEMO_SOURCE),
          output_characters: demoTranslation.translated_text.length,
          output_words: countWords(demoTranslation.translated_text),
          paragraphs: countParagraphs(demoTranslation.translated_text),
          chunks: 2,
          batches: 1,
          pages: 0,
          parameters: { num_beams: 4, max_length: 512, batch_size: 8, preserve_markup: true },
        },
        warnings: ["Machine translation can change names, numbers and nuances. Review important documents before publishing."],
        source_language: "pt",
        target_language: "en",
      }
    : null,
);

const translationOnline = computed(() => (system.status ? system.service("translation")?.online !== false : true));
const activeJob = computed<Job | null>(() => (activeJobId.value ? jobs.byId(activeJobId.value) || null : null));
const activeJobRunning = computed(() => Boolean(activeJob.value && ["queued", "running", "canceling"].includes(activeJob.value.status)));
const serviceLabel = computed(() => {
  if (!translationOnline.value) return "translation offline";
  if (statusInfo.value?.loaded_model) return `loaded · ${statusInfo.value.loaded_model}`;
  return statusInfo.value?.status === "ok" ? "shared service" : "shared service";
});

const sourceLanguageOptions = computed(() =>
  sourceLanguageList.value.map((code) => ({ code, label: languageLabel(code) })),
);
const targetLanguageOptions = computed(() =>
  targetLanguageList.value.map((code) => ({ code, label: languageLabel(code) })),
);
const inputCharacters = computed(() => source.value.length);
const inputWords = computed(() => countWords(source.value));
const inputParagraphs = computed(() => countParagraphs(source.value));
const outputCharacters = computed(() => result.value.length);
const outputWords = computed(() => countWords(result.value));
const outputParagraphs = computed(() => countParagraphs(result.value));
const activeModel = computed(() => modelItems.value.find((item) => item.id === model.value) || modelItems.value[0]);
const detectedLabel = computed(() => {
  if (!detected.value) return "";
  const confidence = Number(detected.value.confidence || 0);
  const percent = confidence > 0 ? ` · ${Math.round(confidence * 100)}%` : "";
  return `${detected.value.name || languageLabel(detected.value.language)}${percent}`;
});

const stats = computed(() => {
  const metaStats = resultMeta.value?.stats || {};
  return {
    input: Number(metaStats.input_characters ?? inputCharacters.value),
    output: Number(metaStats.output_characters ?? outputCharacters.value),
    paragraphs: Number(metaStats.paragraphs ?? outputParagraphs.value),
    chunks: Number(metaStats.chunks ?? 0),
    batches: Number(metaStats.batches ?? 0),
    device: String(metaStats.device || statusInfo.value?.device || "cpu"),
    duration: Number(resultMeta.value?.duration ?? 0),
    model: resultMeta.value?.model || activeModel.value?.name || "auto",
  };
});
const statCards = computed(() => [
  {
    label: "Characters",
    value: formatNumber(stats.value.input),
    sub: `${formatNumber(stats.value.output)} in the translation`,
    icon: Hash,
  },
  {
    label: "Paragraphs",
    value: formatNumber(stats.value.paragraphs),
    sub: `${stats.value.chunks || "—"} chunks · ${stats.value.batches || "—"} batches`,
    icon: BookOpen,
  },
  {
    label: "Device",
    value: stats.value.device.toUpperCase(),
    sub: statusInfo.value?.cpu_threads ? `${statusInfo.value.cpu_threads} CPU threads` : "local inference",
    icon: Cpu,
  },
  {
    label: "Duration",
    value: durationLabel(stats.value.duration),
    sub: resultMeta.value?.modelLabel || modelLabel(stats.value.model),
    icon: Clock,
  },
]);

const runIssue = computed(() => {
  if (!translationOnline.value) return "The shared translation service is offline.";
  if (!source.value.trim()) return "Type or load some text to translate.";
  if (!targetLanguage.value) return "Choose a target language.";
  if (!model.value) return "Choose a translation model.";
  const selected = modelItems.value.find((item) => item.id === model.value);
  if (selected && selected.available === false && selected.id !== "auto") return `${selected.name} is not installed. Choose Auto or install the model.`;
  return "";
});
const canTranslate = computed(() => !runIssue.value && !loading && !activeJobRunning.value);

onMounted(async () => {
  loadHistory();
  system.load();
  if (DEMO) return;
  await refreshService();
});

onBeforeUnmount(stopPolling);

watch([sourceLanguage, targetLanguage], ([sourceCode, targetCode]) => {
  if (!model.value.startsWith("opus-mt")) return;
  const pair = `${baseLanguage(sourceCode)}-${baseLanguage(targetCode)}`;
  if (sourceCode === "auto" || model.value !== `opus-mt-${pair}`) model.value = "auto";
});

watch(
  () => activeJob.value?.status,
  (status) => {
    if (!status) return;
    if (status === "completed" && activeJobId.value) {
      stopPolling();
      loadJobResult(activeJobId.value);
    } else if (status === "failed") {
      stopPolling();
      toasts.error(activeJob.value?.error || "The translation job failed");
    } else if (status === "canceled") {
      stopPolling();
      toasts.info("Translation job canceled");
    }
  },
);

function languageLabel(code: string) {
  return languageNames.value[code] || COMMON_LANGUAGE_NAMES[code] || code;
}

function baseLanguage(code: string) {
  return (code || "").toLowerCase().split("-")[0];
}

function modelLabel(id: string) {
  const found = modelItems.value.find((item) => item.id === id);
  if (found) return found.name;
  const special: Record<string, string> = {
    "Helsinki-NLP/opus-mt-roa-en": "OPUS-MT · Portuguese → English",
    "Helsinki-NLP/opus-mt-tc-big-en-pt": "OPUS-MT · English → Portuguese",
    "opus-mt-pt-en": "OPUS-MT · Portuguese → English",
    "opus-mt-en-pt": "OPUS-MT · English → Portuguese",
  };
  return special[id] || id || "auto";
}

async function refreshService() {
  if (DEMO) {
    toasts.info("Demo mode · translation runtime is preloaded");
    return;
  }
  serviceBusy.value = true;
  serviceError.value = "";
  try {
    const [languagesPayload, modelsPayload, statusPayload] = await Promise.all([
      api.get<any>("/translate/languages"),
      api.get<any>("/translate/models"),
      api.get<any>("/translate/status"),
    ]);
    applyLanguages(languagesPayload);
    applyModels(modelsPayload);
    statusInfo.value = statusPayload;
    if (statusPayload?.defaults) {
      params.num_beams = Number(statusPayload.defaults.num_beams ?? params.num_beams);
      params.max_length = Number(statusPayload.defaults.max_length ?? params.max_length);
      params.batch_size = Number(statusPayload.defaults.batch_size ?? params.batch_size);
    }
  } catch (error: any) {
    serviceError.value = error?.message || "Could not reach the translation service.";
    toasts.error(serviceError.value);
  } finally {
    serviceBusy.value = false;
  }
}

function applyLanguages(payload: any) {
  const items = payload?.items || payload?.languages || [];
  const names: Record<string, string> = { ...COMMON_LANGUAGE_NAMES };
  for (const item of items) {
    if (!item) continue;
    const code = String(item.code ?? item.id ?? item.language ?? "");
    if (!code) continue;
    names[code] = String(item.name ?? item.label ?? code);
    for (const variant of item.variants || []) {
      if (typeof variant === "string") names[variant] = names[code];
    }
  }
  languageNames.value = names;
  const sourceList = payload?.source || ["auto", ...(payload?.target || [])];
  const targetList = (payload?.target || []).filter((code: string) => code !== "auto");
  sourceLanguageList.value = sourceList;
  targetLanguageList.value = targetList.length ? targetList : ["en"];
  if (!sourceLanguageList.value.includes(sourceLanguage.value)) sourceLanguage.value = "auto";
  if (!targetLanguageList.value.includes(targetLanguage.value)) targetLanguage.value = targetLanguageList.value[0] || "en";
}

function applyModels(payload: any) {
  const items = payload?.items || [];
  const normalized = items.map((item: any) => {
    const id = String(item?.id ?? item?.model ?? item?.name ?? "");
    return {
      id,
      name: String(item?.name ?? item?.label ?? id),
      available: item?.available !== false && item?.installed !== false,
      family: String(item?.family ?? ""),
      detail: [item?.family, item?.direction, item?.available === false ? "not installed" : ""].filter(Boolean).join(" · "),
    };
  });
  const list = [{ id: "auto", name: "Auto · best available", available: true, family: "auto", detail: "Picks the best installed pair" }, ...normalized.filter((item: any) => item.id && item.id !== "auto")];
  modelItems.value = list.length > 1 ? list : DEMO_MODELS;
  if (!modelItems.value.some((item) => item.id === model.value)) model.value = "auto";
}

async function detectLanguage() {
  if (!source.value.trim()) {
    toasts.error("Add some text before detecting its language");
    return;
  }
  detectedLoading.value = true;
  try {
    if (DEMO) {
      await delay(350);
      detected.value = { language: "pt", name: "Portuguese", confidence: 0.99 };
      sourceLanguage.value = "pt";
      toasts.success("Detected Portuguese · 99% confidence");
    } else {
      const data = await api.post<any>("/translate/detect", { text: source.value.slice(0, 20_000) });
      detected.value = data;
      const candidate = data.variant || data.language;
      if (candidate && sourceLanguageList.value.includes(candidate)) sourceLanguage.value = candidate;
      else if (data.language && sourceLanguageList.value.includes(data.language)) sourceLanguage.value = data.language;
      toasts.success(`Detected ${data.name || data.language}${data.confidence ? ` · ${Math.round(Number(data.confidence) * 100)}%` : ""}`);
    }
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    detectedLoading.value = false;
  }
}

function swapLanguages() {
  const previousSource = sourceLanguage.value;
  const previousTarget = targetLanguage.value;
  const resolvedSource = previousSource === "auto" ? detected.value?.variant || detected.value?.language || "pt" : previousSource;
  sourceLanguage.value = previousTarget;
  const nextTarget = resolveTargetCode(resolvedSource);
  targetLanguage.value = nextTarget === sourceLanguage.value ? resolveTargetCode(sourceLanguage.value === "en" ? "pt" : "en") : nextTarget;
  toasts.info(`Swapped to ${languageLabel(sourceLanguage.value)} → ${languageLabel(targetLanguage.value)}`);
}

function resolveTargetCode(code: string) {
  if (targetLanguageList.value.includes(code)) return code;
  if (code.startsWith("pt")) {
    if (targetLanguageList.value.includes("pt-PT")) return "pt-PT";
    if (targetLanguageList.value.includes("pt-BR")) return "pt-BR";
  }
  if (code.startsWith("en") && targetLanguageList.value.includes("en")) return "en";
  return targetLanguageList.value[0] || "en";
}

function buildPayload() {
  const terms = glossary.value.reduce<Record<string, string>>((acc, entry) => {
    const from = entry.source.trim();
    const to = entry.target.trim();
    if (from && to) acc[from] = to;
    return acc;
  }, {});
  const payload: Record<string, any> = {
    text: source.value,
    source_language: sourceLanguage.value,
    target_language: targetLanguage.value,
    model: model.value,
    num_beams: Number(params.num_beams),
    max_length: Number(params.max_length),
    temperature: Number(params.temperature),
    length_penalty: Number(params.length_penalty),
    repetition_penalty: Number(params.repetition_penalty),
    no_repeat_ngram_size: Number(params.no_repeat_ngram_size),
    batch_size: Number(params.batch_size),
    preserve_markup: params.preserve_markup,
  };
  if (Object.keys(terms).length) payload.glossary = terms;
  return payload;
}

async function translate() {
  if (runIssue.value) {
    toasts.error(runIssue.value);
    return;
  }
  loading.value = true;
  serviceError.value = "";
  try {
    if (DEMO) {
      await delay(700);
      const targetIsPortuguese = targetLanguage.value.startsWith("pt");
      const text = targetIsPortuguese ? DEMO_SOURCE : demoTranslation.translated_text;
      const meta = {
        model: targetIsPortuguese ? "opus-mt-en-pt" : "opus-mt-pt-en",
        modelLabel: targetIsPortuguese ? "OPUS-MT · English → Portuguese" : "OPUS-MT · Portuguese → English",
        duration: 1.4,
        stats: {
          input_characters: source.value.length,
          input_words: countWords(source.value),
          output_characters: text.length,
          paragraphs: countParagraphs(text),
          chunks: 2,
          batches: 1,
          device: "cpu",
          parameters: { num_beams: params.num_beams, max_length: params.max_length, batch_size: params.batch_size, preserve_markup: params.preserve_markup },
        },
        warnings: ["Machine translation can change names, numbers and nuances. Review important documents before publishing."],
        source_language: sourceLanguage.value === "auto" ? "pt" : sourceLanguage.value,
        target_language: targetLanguage.value,
      };
      applyResult(text, meta);
      toasts.success("Demo translation ready");
    } else {
      const data = await api.post<any>("/translate/translate", buildPayload());
      applyResult(data.translated_text || "", {
        model: data.model,
        modelLabel: modelLabel(data.model),
        duration: data.duration_seconds,
        stats: data.stats,
        warnings: data.warnings || [],
        source_language: data.source_language,
        target_language: data.target_language,
      });
      if (data.detected_source_language) {
        detected.value = {
          language: data.source_language,
          name: data.source_language_name || languageLabel(data.source_language),
          confidence: data.detection?.confidence || 0.98,
        };
      }
      toasts.success(`Translated ${formatNumber(data.stats?.input_characters)} characters`);
    }
    recordHistory();
  } catch (error: any) {
    serviceError.value = error.message;
    toasts.error(error.message);
  } finally {
    loading.value = false;
  }
}

async function translateAsJob() {
  if (runIssue.value) {
    toasts.error(runIssue.value);
    return;
  }
  if (DEMO) {
    await translate();
    toasts.info("Demo mode · this run used the synchronous endpoint");
    return;
  }
  submittingJob.value = true;
  try {
    const job = await api.post<Job>("/translate/translate/job", buildPayload());
    jobs.upsert(job);
    jobs.connect();
    activeJobId.value = job.id;
    startPolling(job.id);
    toasts.success("Translation job queued");
  } catch (error: any) {
    serviceError.value = error.message;
    toasts.error(error.message);
  } finally {
    submittingJob.value = false;
  }
}

function applyResult(text: string, meta: any) {
  result.value = text;
  resultMeta.value = meta;
  savePath.value = `documents/translation/translation-${sourceLanguage.value === "auto" ? "detected" : sourceLanguage.value}-${targetLanguage.value}.txt`;
}

async function loadJobResult(jobId: string) {
  const job = jobs.byId(jobId);
  const data: any = job?.result?.data || {};
  try {
    let text = "";
    if (data.text_path) {
      const file = await api.get<any>(`/files/read?path=${encodeURIComponent(data.text_path)}`);
      text = file?.content || "";
      savePath.value = data.text_path;
    }
    if (!text) text = data.translated_text || "";
    if (!text.trim()) throw new Error("The translation job finished without readable text.");
    applyResult(text, {
      model: data.model,
      modelLabel: modelLabel(data.model),
      duration: data.duration_seconds,
      stats: data.stats,
      warnings: data.warnings || [],
      source_language: data.source_language,
      target_language: data.target_language,
    });
    if (data.text_path) savePath.value = data.text_path;
    recordHistory();
    toasts.success("Translation job complete");
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

async function onFileSelected(path: string, file: any) {
  if (DEMO) {
    source.value = DEMO_SOURCE;
    toasts.info(`Demo mode · loaded sample text instead of ${file?.name || path}`);
    return;
  }
  try {
    const data = await api.get<any>(`/files/read?path=${encodeURIComponent(path)}`);
    source.value = data.content || "";
    if (data.truncated) toasts.info("The file was truncated to the service read limit");
    toasts.success(`Loaded ${file?.name || path}`);
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function useSample() {
  source.value = DEMO_SOURCE;
  sourceLanguage.value = "pt";
  targetLanguage.value = "en";
  toasts.info("Sample Portuguese lyrics loaded");
}

function clearSource() {
  source.value = "";
  result.value = "";
  resultMeta.value = null;
}

async function copyResult() {
  if (!result.value) return;
  try {
    await navigator.clipboard.writeText(result.value);
    toasts.success("Translation copied");
  } catch {
    toasts.error("Could not access the clipboard");
  }
}

function downloadResult() {
  if (!result.value) return;
  const blob = new Blob([result.value], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `translation-${sourceLanguage.value}-${targetLanguage.value}.txt`;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function saveToFiles() {
  if (!result.value) {
    toasts.error("Translate something before saving");
    return;
  }
  if (!savePath.value.trim()) {
    toasts.error("Enter a destination path");
    return;
  }
  try {
    if (DEMO) {
      await delay(250);
      toasts.success(`Demo mode · would save to ${savePath.value}`);
    } else {
      await api.post("/files/write", { path: savePath.value.trim(), content: result.value });
      toasts.success(`Saved to ${savePath.value.trim()}`);
    }
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function addGlossaryRow() {
  glossary.value.push({ source: "", target: "" });
}

function removeGlossaryRow(index: number) {
  glossary.value.splice(index, 1);
}

function loadHistory() {
  try {
    const raw = localStorage.getItem("openstudio.translation.history.v1");
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        history.value = parsed.slice(0, 12);
        return;
      }
    }
  } catch {
    // Ignore malformed local history.
  }
  if (DEMO) {
    history.value = demoHistory();
    persistHistory();
  }
}

function persistHistory() {
  try {
    localStorage.setItem("openstudio.translation.history.v1", JSON.stringify(history.value));
  } catch {
    // Storage can be unavailable in private windows.
  }
}

function recordHistory() {
  if (!result.value.trim() || !source.value.trim()) return;
  const entry: HistoryEntry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    createdAt: new Date().toISOString(),
    sourceLanguage: sourceLanguage.value,
    targetLanguage: targetLanguage.value,
    model: resultMeta.value?.model || model.value,
    modelLabel: resultMeta.value?.modelLabel || modelLabel(resultMeta.value?.model || model.value),
    characters: resultMeta.value?.stats?.input_characters ?? source.value.length,
    duration: resultMeta.value?.duration || 0,
    preview: source.value.replace(/\s+/g, " ").trim().slice(0, 130),
    sourceText: source.value,
    resultText: result.value,
    stats: resultMeta.value?.stats || {},
    warnings: resultMeta.value?.warnings || [],
  };
  history.value = [entry, ...history.value.filter((item) => item.preview !== entry.preview || item.resultText !== entry.resultText)].slice(0, 12);
  persistHistory();
}

function restoreHistory(entry: HistoryEntry) {
  source.value = entry.sourceText;
  result.value = entry.resultText;
  sourceLanguage.value = entry.sourceLanguage;
  targetLanguage.value = entry.targetLanguage;
  model.value = entry.model && modelItems.value.some((item) => item.id === entry.model) ? entry.model : "auto";
  detected.value = null;
  resultMeta.value = {
    model: entry.model,
    modelLabel: entry.modelLabel,
    duration: entry.duration,
    stats: entry.stats,
    warnings: entry.warnings,
    source_language: entry.sourceLanguage,
    target_language: entry.targetLanguage,
  };
  savePath.value = `documents/translation/history-${entry.sourceLanguage}-${entry.targetLanguage}.txt`;
  toasts.success("Translation restored from history");
}

function demoHistory(): HistoryEntry[] {
  const base = Date.now();
  return [
    {
      id: "demo-h1",
      createdAt: new Date(base - 18 * 60000).toISOString(),
      sourceLanguage: "pt",
      targetLanguage: "en",
      model: "opus-mt-pt-en",
      modelLabel: "OPUS-MT · Portuguese → English",
      characters: 214,
      duration: 1.4,
      preview: "A cidade fecha os olhos devagar · Eu conto os passos até te encontrar…",
      sourceText: DEMO_SOURCE,
      resultText: demoTranslation.translated_text,
      stats: { input_characters: 214, output_characters: 206, paragraphs: 2, chunks: 2, device: "cpu" },
      warnings: [],
    },
    {
      id: "demo-h2",
      createdAt: new Date(base - 2.4 * 3600000).toISOString(),
      sourceLanguage: "en",
      targetLanguage: "pt-PT",
      model: "opus-mt-en-pt",
      modelLabel: "OPUS-MT · English → Portuguese",
      characters: 512,
      duration: 2.6,
      preview: "The studio now keeps every file, every job and every model behind one password…",
      sourceText: "The studio now keeps every file, every job and every model behind one password. Music, video, voice and documents share the same storage tree.",
      resultText: "O estúdio mantém agora todos os ficheiros, todas as tarefas e todos os modelos atrás de uma única palavra-passe. Música, vídeo, voz e documentos partilham a mesma árvore de armazenamento.",
      stats: { input_characters: 512, output_characters: 486, paragraphs: 2, chunks: 3, device: "cpu" },
      warnings: [],
    },
    {
      id: "demo-h3",
      createdAt: new Date(base - 26 * 3600000).toISOString(),
      sourceLanguage: "pt",
      targetLanguage: "en",
      model: "nllb-200-distilled-600M",
      modelLabel: "NLLB-200 distilled 600M · multilingual",
      characters: 180,
      duration: 1.1,
      preview: "Guardar o teu nome do lado errado · Nocturno, não acordes ainda…",
      sourceText: "Guardar o teu nome do lado errado\nNocturno...\nNão acordes ainda",
      resultText: "Keep your name on the wrong side\nNocturne...\nDon't wake up yet",
      stats: { input_characters: 180, output_characters: 172, paragraphs: 3, chunks: 1, device: "cpu" },
      warnings: [],
    },
  ];
}

function countWords(text: string) {
  return text.trim() ? text.trim().split(/\s+/).filter(Boolean).length : 0;
}

function countParagraphs(text: string) {
  if (!text.trim()) return 0;
  return text.split(/\n{2,}/).filter((part) => part.trim()).length;
}

function formatNumber(value: any) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toLocaleString() : "—";
}

function durationLabel(value: any) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "—";
  if (number < 60) return `${number.toFixed(number < 10 ? 2 : 1)}s`;
  return formatDuration(number);
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="Shared language service"
      title="Translation"
      subtitle="One local translation service for every studio page. Portuguese ↔ English uses OPUS-MT, NLLB-200 adds 200 languages, and glossaries plus markup protection keep names and page markers intact."
    >
      <template #actions>
        <span class="chip" :class="{ success: translationOnline, danger: !translationOnline }">
          <span class="dot" :class="translationOnline ? 'online' : 'offline'" /> {{ serviceLabel }}
        </span>
        <span class="chip"><Cpu :size="11" /> {{ statusInfo?.device || "cpu" }}</span>
        <button class="btn btn-sm" :disabled="serviceBusy" @click="refreshService"><RefreshCw :size="13" :class="{ spin: serviceBusy }" /> Service</button>
      </template>
    </PageHeader>

    <section class="panel" style="margin-bottom: 14px">
      <div class="panel-body">
        <div class="language-bar">
          <div class="field">
            <label>Source language</label>
            <select v-model="sourceLanguage" class="select">
              <option v-for="language in sourceLanguageOptions" :key="language.code" :value="language.code">{{ language.label }}</option>
            </select>
          </div>
          <button class="btn btn-icon" title="Swap languages" style="margin-bottom: 1px" @click="swapLanguages"><ArrowLeftRight :size="15" /></button>
          <div class="field">
            <label>Target language</label>
            <select v-model="targetLanguage" class="select">
              <option v-for="language in targetLanguageOptions" :key="language.code" :value="language.code">{{ language.label }}</option>
            </select>
          </div>
          <div class="field model-field">
            <label>Model</label>
            <select v-model="model" class="select">
              <option v-for="item in modelItems" :key="item.id" :value="item.id" :disabled="item.available === false && item.id !== 'auto'">{{ item.name }}{{ item.available === false && item.id !== 'auto' ? " · not installed" : "" }}</option>
            </select>
            <span v-if="activeModel?.detail" class="hint">{{ activeModel.detail }}</span>
          </div>
          <button class="btn detect-btn" :disabled="detectedLoading" @click="detectLanguage">
            <Loader2 v-if="detectedLoading" :size="14" class="spin" /><Languages v-else :size="14" /> Detect
          </button>
        </div>
        <div class="row" style="margin-top: 10px; gap: 7px">
          <span v-if="detectedLabel" class="chip success"><Sparkles :size="11" /> Detected {{ detectedLabel }}</span>
          <span class="chip">{{ formatNumber(inputCharacters) }} source characters</span>
          <span class="chip">{{ inputParagraphs }} paragraphs</span>
          <span v-if="resultMeta?.target_language" class="chip active">{{ languageLabel(resultMeta.source_language) }} → {{ languageLabel(resultMeta.target_language) }}</span>
          <span class="chip" style="margin-left: auto">{{ activeJobRunning ? "job running" : "sync or job mode" }}</span>
        </div>
      </div>
    </section>

    <div class="row" style="margin-bottom: 14px; gap: 8px">
      <button class="btn btn-primary btn-lg" :disabled="!canTranslate" @click="translate">
        <Loader2 v-if="loading" :size="15" class="spin" /><Wand2 v-else :size="15" /> {{ loading ? "Translating…" : "Translate" }}
      </button>
      <button class="btn btn-lg" :disabled="!canTranslate || submittingJob" @click="translateAsJob">
        <Loader2 v-if="submittingJob" :size="15" class="spin" /><Play v-else :size="15" /> Run as job
      </button>
      <span class="small muted">POST /translate · synchronous or queued through the shared job hub</span>
      <span v-if="runIssue" class="chip warn"><AlertTriangle :size="11" /> {{ runIssue }}</span>
    </div>

    <div v-if="serviceError" class="alert error" style="margin-bottom: 14px">{{ serviceError }}</div>

    <div class="grid grid-2">
      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Source text</h3>
            <p>{{ inputWords }} words · {{ inputParagraphs }} paragraphs</p>
          </div>
          <div class="row" style="gap: 6px">
            <button class="btn btn-sm" @click="filePickerOpen = true"><FolderOpen :size="13" /> Load file</button>
            <button class="btn btn-sm btn-ghost" @click="clearSource">Clear</button>
          </div>
        </div>
        <div class="panel-body stack">
          <textarea v-model="source" class="textarea editor" spellcheck="false" placeholder="Paste or type the text to translate. Page markers, HTML tags, code fences and URLs are preserved." />
          <div class="row-between small muted">
            <span>{{ formatNumber(source.length) }} characters</span>
            <button class="btn btn-sm btn-ghost" @click="useSample"><Sparkles :size="12" /> Use sample lyrics</button>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Translation</h3>
            <p>{{ resultMeta ? `${resultMeta.modelLabel || modelLabel(resultMeta.model)} · ${durationLabel(resultMeta.duration)}` : "The translated text appears here." }}</p>
          </div>
          <div class="row" style="gap: 6px">
            <button class="btn btn-sm btn-ghost" :disabled="!result" @click="copyResult"><Copy :size="13" /> Copy</button>
            <button class="btn btn-sm btn-ghost" :disabled="!result" @click="downloadResult"><Download :size="13" /> .txt</button>
          </div>
        </div>
        <div class="panel-body stack">
          <textarea v-model="result" class="textarea editor" spellcheck="false" placeholder="Translation output…" />
          <div class="row-between small muted">
            <span>{{ outputWords }} words · {{ formatNumber(outputCharacters) }} characters</span>
            <span v-if="resultMeta?.model" class="chip">{{ resultMeta.modelLabel || resultMeta.model }}</span>
          </div>
          <div class="field">
            <label>Save to shared files</label>
            <div class="input-group">
              <input v-model="savePath" class="input mono" placeholder="documents/translation/translation.txt" />
              <button class="btn" :disabled="!result" @click="saveToFiles"><Save :size="13" /> Save</button>
            </div>
            <span class="hint">POST /files/write · the result becomes available to documents, summaries and every other service.</span>
          </div>
          <div v-for="warning in (resultMeta?.warnings || []).slice(0, 1)" :key="warning" class="alert warn">{{ warning }}</div>
        </div>
      </section>
    </div>

    <div class="stat-grid" style="margin: 16px 0">
      <div v-for="card in statCards" :key="card.label" class="stat">
        <div class="stat-label">{{ card.label }}</div>
        <div class="stat-value">{{ card.value }}</div>
        <div class="stat-sub">{{ card.sub }}</div>
      </div>
    </div>

    <div class="grid text-lower-grid">
      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Generation parameters</h3>
            <p>Sent with both the synchronous and queued translation requests.</p>
          </div>
          <span class="chip"><Gauge :size="11" /> {{ params.num_beams }} beams · {{ params.batch_size }} batch</span>
        </div>
        <div class="panel-body stack">
          <div class="grid grid-4">
            <div class="field"><label>Num beams</label><input v-model.number="params.num_beams" class="input" type="number" min="1" max="16" /></div>
            <div class="field"><label>Max length</label><input v-model.number="params.max_length" class="input" type="number" min="8" max="4096" /></div>
            <div class="field"><label>Temperature</label><input v-model.number="params.temperature" class="input" type="number" min="0" max="2" step="0.1" /></div>
            <div class="field"><label>Batch size</label><input v-model.number="params.batch_size" class="input" type="number" min="1" max="64" /></div>
            <div class="field"><label>Length penalty</label><input v-model.number="params.length_penalty" class="input" type="number" min="-5" max="5" step="0.1" /></div>
            <div class="field"><label>Repetition penalty</label><input v-model.number="params.repetition_penalty" class="input" type="number" min="0.1" max="5" step="0.05" /></div>
            <div class="field"><label>No repeat n-gram</label><input v-model.number="params.no_repeat_ngram_size" class="input" type="number" min="0" max="10" /></div>
            <div class="field">
              <label>Preserve markup</label>
              <button class="switch" :class="{ on: params.preserve_markup }" @click="params.preserve_markup = !params.preserve_markup" />
              <span class="hint">Tags, URLs, code and page markers stay intact.</span>
            </div>
          </div>

          <div class="row-between" style="margin-top: 4px">
            <div>
              <h3 style="font-size: 13px">Glossary</h3>
              <p class="small muted">Terms are replaced exactly and protected from the model.</p>
            </div>
            <button class="btn btn-sm" @click="addGlossaryRow"><Plus :size="12" /> Add term</button>
          </div>
          <div v-if="glossary.length" class="glossary-list">
            <div v-for="(entry, index) in glossary" :key="index" class="glossary-row">
              <input v-model="entry.source" class="input" placeholder="Source term" />
              <ArrowRight :size="14" class="muted" />
              <input v-model="entry.target" class="input" placeholder="Target term" />
              <button class="icon-btn" title="Remove term" @click="removeGlossaryRow(index)"><Trash2 :size="14" /></button>
            </div>
          </div>
          <div v-else class="empty" style="padding: 20px">
            <p>No glossary terms. Add product names, people or recurring phrases that must not change.</p>
          </div>
        </div>
      </section>

      <div class="stack">
        <section v-if="activeJob" class="panel">
          <div class="panel-head">
            <div><h3>Translation job</h3><p>Queued through the shared job hub.</p></div>
            <RouterLink to="/jobs" class="btn btn-sm btn-ghost">Job center</RouterLink>
          </div>
          <div class="panel-body">
            <JobCard :job="activeJob" @cancel="cancelActiveJob" @retry="retryActiveJob" @remove="removeActiveJob" />
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <h3>Recent translations</h3>
              <p>Kept in this browser for quick reuse.</p>
            </div>
            <span class="chip">{{ history.length }}</span>
          </div>
          <div class="panel-body stack" style="gap: 8px">
            <button v-for="entry in history" :key="entry.id" class="history-item" @click="restoreHistory(entry)">
              <div class="row-between">
                <span class="small strong">{{ languageLabel(entry.sourceLanguage) }} → {{ languageLabel(entry.targetLanguage) }}</span>
                <span class="small muted">{{ relativeTime(entry.createdAt) }}</span>
              </div>
              <div class="small muted truncate" style="margin: 3px 0 5px">{{ entry.preview }}</div>
              <div class="row small muted" style="gap: 7px">
                <span>{{ formatNumber(entry.characters) }} chars</span>
                <span>·</span>
                <span>{{ durationLabel(entry.duration) }}</span>
                <span class="chip" style="margin-left: auto">{{ (entry.modelLabel || entry.model || "auto").split("·")[0].trim() }}</span>
              </div>
            </button>
            <EmptyState v-if="!history.length" :icon="Clock" title="No recent translations" message="Every translation you run is kept here locally so you can restore the text, languages and parameters." />
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><h3>Service runtime</h3><p>Local model, CPU threads and library availability.</p></div>
            <span class="dot" :class="translationOnline ? 'online' : 'offline'" />
          </div>
          <div class="panel-body stack" style="gap: 7px">
            <div class="row-between small"><span class="muted">Loaded model</span><span class="mono">{{ statusInfo?.loaded_model || "lazy load" }}</span></div>
            <div class="row-between small"><span class="muted">Device</span><span class="mono">{{ statusInfo?.device || "cpu" }}</span></div>
            <div class="row-between small"><span class="muted">CPU threads</span><span class="mono">{{ statusInfo?.cpu_threads || "—" }}</span></div>
            <div class="row-between small"><span class="muted">PyTorch</span><span class="chip" :class="statusInfo?.runtime?.torch ? 'success' : 'danger'">{{ statusInfo?.runtime?.torch ? "ready" : "missing" }}</span></div>
            <div class="row-between small"><span class="muted">Transformers</span><span class="chip" :class="statusInfo?.runtime?.transformers ? 'success' : 'danger'">{{ statusInfo?.runtime?.transformers ? "ready" : "missing" }}</span></div>
            <div class="row-between small"><span class="muted">Language detect</span><span class="chip" :class="statusInfo?.runtime?.langdetect ? 'success' : 'warn'">{{ statusInfo?.runtime?.langdetect ? "ready" : "heuristic" }}</span></div>
            <div class="alert" style="margin-top: 4px">
              OPUS-MT is preferred for Portuguese ↔ English. Install NLLB-200 to translate every other language pair.
            </div>
          </div>
        </section>
      </div>
    </div>

    <FilePicker v-model="filePickerOpen" title="Load text from shared files" kind="document" accept=".txt,.md,.csv,.json,.srt,.vtt" @selected="onFileSelected" />
  </div>
</template>

<style scoped>
.language-bar {
  display: flex;
  align-items: flex-end;
  gap: 9px;
  flex-wrap: wrap;
}
.language-bar .field { flex: 1; min-width: 170px; }
.language-bar .model-field { flex: 1.5; min-width: 260px; }
.detect-btn { min-height: 36px; }
.editor { min-height: 330px; font-size: 13px; }
.glossary-list { display: flex; flex-direction: column; gap: 7px; }
.glossary-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 18px minmax(0, 1fr) 30px;
  gap: 7px;
  align-items: center;
}
.history-item {
  text-align: left;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(8, 10, 15, 0.32);
  padding: 9px 10px;
  color: var(--text);
  transition: 150ms ease;
}
.history-item:hover { border-color: rgba(139, 92, 246, 0.4); background: rgba(139, 92, 246, 0.06); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.text-lower-grid {
  grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr);
  align-items: start;
}
@media (max-width: 1100px) {
  .text-lower-grid { grid-template-columns: 1fr; }
}

@media (max-width: 900px) {
  .language-bar .field, .language-bar .model-field { min-width: 100%; }
  .language-bar .detect-btn { width: 100%; }
}
</style>
