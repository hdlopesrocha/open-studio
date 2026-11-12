<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Copy,
  Cpu,
  Download,
  FileText,
  FolderOpen,
  Gauge,
  Languages,
  Layers,
  Loader2,
  Play,
  RefreshCw,
  Save,
  Sparkles,
  Wand2,
} from "lucide-vue-next";
import { api, formatDuration } from "@/lib/api";
import { DEMO } from "@/lib/types";
import type { Job } from "@/lib/types";
import { demoDocsCapabilities, demoSummary } from "@/lib/demo";
import { useJobsStore } from "@/stores/jobs";
import { useSystemStore } from "@/stores/system";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import FilePicker from "@/components/FilePicker.vue";
import JobCard from "@/components/JobCard.vue";
import EmptyState from "@/components/EmptyState.vue";

const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false });
const emit = defineEmits<{ "open-workflow": [] }>();

const jobs = useJobsStore();
const system = useSystemStore();
const toasts = useToastStore();

const DEMO_SOURCE = `Open Studio's 2026 annual report describes a year of steady growth in local-first creative tooling. Revenue rose 24% year over year, driven by studio subscriptions, enterprise deployments and the launch of a shared job system that lets music, video, voice, images and documents run in parallel on one machine.

The team shipped four model integrations: ACE-Step 1.5 for music, OmniVoice for zero-shot speech, NLLB-200 for multilingual translation and QVAC for local video generation. Inference latency fell by 38% after the switch to quantized local models, while storage costs were reduced through content-addressed assets and automatic deduplication. The shared file tree now holds more than 300,000 artifacts produced by every studio page.

Customers asked for one place where their files, jobs and privacy model are the same regardless of the medium. The answer was a single password-protected studio with per-component queues, a central job hub and a file explorer that every service can read and write. Support volume dropped by 21% after the new onboarding flow shipped.

Priorities for next year are video generation, multilingual voice, and a unified document pipeline that can translate, summarize, narrate and caption a PDF without leaving the studio. The report also recommends expanding benchmark coverage for Portuguese, adding regional voice variants and keeping every model usable on CPU-only hardware.

The financial outlook remains conservative. The team plans to grow headcount by six people, invest in evaluation tooling and keep the storage footprint flat even as usage doubles. The report closes with a note on durability: local-first tools must remain usable offline, with predictable upgrades and complete ownership of every artifact.`;

const COMMON_LANGUAGE_NAMES: Record<string, string> = {
  auto: "Detect from the text",
  en: "English",
  pt: "Portuguese",
  "pt-PT": "Portuguese (Portugal)",
  "pt-BR": "Portuguese (Brazil)",
};

const sourceText = ref(DEMO ? DEMO_SOURCE : "");
const summaryText = ref(DEMO ? demoSummary.summary : "");
const length = ref("medium");
const language = ref("en");
const sourceLanguage = ref("auto");
const model = ref("auto");
const advancedOpen = ref(DEMO);
const filePickerOpen = ref(false);
const loading = ref(false);
const submittingJob = ref(false);
const serviceBusy = ref(false);
const serviceError = ref("");
const statusInfo = ref<any>(DEMO ? { status: "ok", device: "cpu", cpu_threads: 12, loaded_model: "t5-small-en", available: { en: true, pt: true }, runtime: { torch: true, transformers: true, sentencepiece: true, langdetect: true } } : null);
const activeJobId = ref("");
const savePath = ref(DEMO ? "documents/summary/annual-report-2026-en.txt" : "documents/summary/summary.txt");
const languageNames = ref<Record<string, string>>({ ...COMMON_LANGUAGE_NAMES });
const lengthOptions = ref<any[]>(
  DEMO
    ? (demoDocsCapabilities.summary_lengths as string[]).map((id) => ({ id, label: cap(id), max_tokens: id === "short" ? 120 : id === "long" ? 420 : 240 }))
    : [
        { id: "short", label: "Short", max_tokens: 120 },
        { id: "medium", label: "Medium", max_tokens: 240 },
        { id: "long", label: "Long", max_tokens: 420 },
      ],
);
const languageList = ref<string[]>(DEMO ? ["en", "pt-PT", "pt-BR"] : ["en", "pt-PT", "pt-BR"]);
const sourceLanguageList = ref<string[]>(DEMO ? ["auto", "en", "pt", "pt-PT", "pt-BR"] : ["auto", "en", "pt", "pt-PT", "pt-BR"]);
const modelItems = ref<any[]>(
  DEMO
    ? [
        { id: "auto", name: "Auto · language matched", available: true, language: "auto" },
        { id: "t5-small-en", name: "T5 small · English summaries", available: true, language: "en" },
        { id: "t5-small-pt", name: "T5 small · Portuguese summaries", available: true, language: "pt" },
      ]
    : [{ id: "auto", name: "Auto · language matched", available: true, language: "auto" }],
);
let pollTimer: number | undefined;

const advanced = reactive<Record<string, any>>({
  max_tokens: null,
  min_tokens: null,
  num_beams: 3,
  temperature: 0,
  chunk_tokens: null,
  hierarchical: true,
});

const resultMeta = ref<any>(
  DEMO
    ? {
        model: demoSummary.model,
        modelLabel: "T5 small · English summaries",
        input_words: countWords(DEMO_SOURCE),
        output_words: countWords(demoSummary.summary),
        chunk_count: demoSummary.chunk_count,
        hierarchy_levels: 3,
        duration: demoSummary.duration_seconds,
        warnings: ["Summaries are generated by a compact local model. Verify names, dates and figures before relying on them."],
        translated: false,
        source_language: "en",
        language: "en",
        parameters: { max_tokens: 240, min_tokens: 0, num_beams: 3, temperature: 0, chunk_tokens: 512, hierarchical: true },
      }
    : null,
);

const summaryOnline = computed(() => (system.status ? system.service("summary")?.online !== false : true));
const activeJob = computed<Job | null>(() => (activeJobId.value ? jobs.byId(activeJobId.value) || null : null));
const activeJobRunning = computed(() => Boolean(activeJob.value && ["queued", "running", "canceling"].includes(activeJob.value.status)));
const sourceWords = computed(() => countWords(sourceText.value));
const sourceChars = computed(() => sourceText.value.length);
const sourceParagraphs = computed(() => countParagraphs(sourceText.value));
const summaryWords = computed(() => countWords(summaryText.value));
const summaryChars = computed(() => summaryText.value.length);
const selectedLength = computed(() => lengthOptions.value.find((item) => item.id === length.value) || lengthOptions.value[0]);
const selectedModel = computed(() => modelItems.value.find((item) => item.id === model.value) || modelItems.value[0]);

const stats = computed(() => {
  const meta = resultMeta.value;
  return {
    input: Number(meta?.input_words ?? sourceWords.value),
    output: Number(meta?.output_words ?? summaryWords.value),
    chunks: Number(meta?.chunk_count ?? 0),
    levels: Number(meta?.hierarchy_levels ?? 0),
    duration: Number(meta?.duration ?? 0),
    translated: Boolean(meta?.translated),
    warnings: (meta?.warnings || []) as string[],
    model: meta?.model || selectedModel.value?.name || "auto",
  };
});
const compression = computed(() => {
  if (!stats.value.input) return 0;
  return Math.max(0, Math.round((1 - stats.value.output / stats.value.input) * 100));
});
const statCards = computed(() => [
  {
    label: "Input words",
    value: formatNumber(stats.value.input),
    sub: `${formatNumber(sourceChars.value)} characters · ${sourceParagraphs.value} paragraphs`,
  },
  {
    label: "Output words",
    value: formatNumber(stats.value.output),
    sub: `${formatNumber(summaryChars.value)} characters · ${compression.value}% reduction`,
  },
  {
    label: "Chunks",
    value: formatNumber(stats.value.chunks),
    sub: `${stats.value.levels || "—"} hierarchy levels`,
  },
  {
    label: "Duration",
    value: durationLabel(stats.value.duration),
    sub: `${resultMeta.value?.modelLabel || modelLabel(stats.value.model)} · ${statusInfo.value?.device || "cpu"}`,
  },
]);
const languageOptions = computed(() => languageList.value.map((code) => ({ code, label: languageLabel(code) })));
const sourceLanguageOptions = computed(() => sourceLanguageList.value.map((code) => ({ code, label: languageLabel(code) })));
const modelLabelText = computed(() => resultMeta.value?.modelLabel || modelLabel(resultMeta.value?.model || model.value));

const runIssue = computed(() => {
  if (!summaryOnline.value) return "The summary service is offline.";
  if (!sourceText.value.trim()) return "Paste a document or load a text file to summarize.";
  const maxTokens = numberOrNull(advanced.max_tokens);
  const minTokens = numberOrNull(advanced.min_tokens);
  if (maxTokens !== null && minTokens !== null && minTokens >= maxTokens) return "Minimum tokens must be smaller than maximum tokens.";
  if (selectedModel.value?.available === false && selectedModel.value.id !== "auto") return `${selectedModel.value.name} is not installed.`;
  if (selectedModel.value && !modelSupportsLanguage(selectedModel.value)) return "Choose a model that matches the summary language.";
  return "";
});
const canSummarize = computed(() => !runIssue.value && !loading && !activeJobRunning.value);

onMounted(async () => {
  system.load();
  if (DEMO) return;
  await refreshService();
});

onBeforeUnmount(stopPolling);

watch(language, () => {
  if (selectedModel.value && !modelSupportsLanguage(selectedModel.value)) model.value = "auto";
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
      toasts.error(activeJob.value?.error || "The summary job failed");
    } else if (status === "canceled") {
      stopPolling();
      toasts.info("Summary job canceled");
    }
  },
);

function languageLabel(code: string) {
  return languageNames.value[code] || COMMON_LANGUAGE_NAMES[code] || code;
}

function modelLabel(id: string) {
  const found = modelItems.value.find((item) => item.id === id);
  if (found) return found.name;
  if (id === "t5-small-en" || id === "t5-small") return "T5 small · English summaries";
  if (id === "t5-small-pt") return "T5 small · Portuguese summaries";
  return id || "auto";
}

function modelSupportsLanguage(item: any) {
  const base = language.value.split("-")[0];
  return !item?.language || item.language === "auto" || item.language === base;
}

async function refreshService() {
  if (DEMO) {
    toasts.info("Demo mode · summary runtime is preloaded");
    return;
  }
  serviceBusy.value = true;
  serviceError.value = "";
  try {
    const [statusPayload, lengthsPayload, languagesPayload, modelsPayload] = await Promise.all([
      api.get<any>("/summary/status"),
      api.get<any>("/summary/lengths"),
      api.get<any>("/summary/languages"),
      api.get<any>("/summary/models"),
    ]);
    statusInfo.value = statusPayload;
    applyLengths(lengthsPayload);
    applyLanguages(languagesPayload);
    applyModels(modelsPayload);
  } catch (error: any) {
    serviceError.value = error?.message || "Could not reach the summary service.";
    toasts.error(serviceError.value);
  } finally {
    serviceBusy.value = false;
  }
}

function applyLengths(payload: any) {
  const items = payload?.items || payload?.lengths || [];
  const normalized = items.map((item: any) => {
    if (typeof item === "string") return { id: item, label: cap(item), max_tokens: null };
    const id = String(item?.id ?? item?.value ?? "medium");
    return { id, label: String(item?.label ?? item?.name ?? cap(id)), max_tokens: item?.max_tokens ?? null };
  });
  if (normalized.length) lengthOptions.value = normalized;
  if (!lengthOptions.value.some((item) => item.id === length.value)) length.value = "medium";
}

function applyLanguages(payload: any) {
  const items = payload?.items || payload?.languages || [];
  const names: Record<string, string> = { ...COMMON_LANGUAGE_NAMES };
  for (const item of items) {
    if (!item) continue;
    const code = String(item.code ?? item.id ?? item.language ?? "");
    if (!code) continue;
    names[code] = String(item.name ?? item.label ?? code);
  }
  languageNames.value = names;
  const list = Array.from(new Set<string>((items as any[]).map((item: any) => String(item.code ?? item.id ?? item.language ?? "")).filter(Boolean)));
  if (list.length) languageList.value = list;
  if (Array.isArray(payload?.source) && payload.source.length) {
    sourceLanguageList.value = payload.source.map((code: any) => String(code));
  } else {
    sourceLanguageList.value = Array.from(new Set(["auto", ...languageList.value, "pt"]));
  }
  if (!languageList.value.includes(language.value)) language.value = languageList.value[0] || "en";
  if (!sourceLanguageList.value.includes(sourceLanguage.value)) sourceLanguage.value = "auto";
}

function applyModels(payload: any) {
  const items = payload?.items || [];
  const normalized = items.map((item: any) => {
    const id = String(item?.id ?? item?.model ?? item?.name ?? "");
    return {
      id,
      name: String(item?.name ?? item?.label ?? id),
      available: item?.available !== false && item?.installed !== false,
      language: String(item?.language ?? "auto"),
    };
  });
  const list = [{ id: "auto", name: "Auto · language matched", available: true, language: "auto" }, ...normalized.filter((item: any) => item.id && item.id !== "auto")];
  modelItems.value = list.length > 1 ? list : modelItems.value;
  if (!modelItems.value.some((item) => item.id === model.value)) model.value = "auto";
  if (payload?.defaults) {
    advanced.num_beams = Number(payload.defaults.num_beams ?? advanced.num_beams);
    advanced.chunk_tokens = payload.defaults.chunk_tokens ?? advanced.chunk_tokens;
    advanced.hierarchical = payload.defaults.hierarchical !== false;
  }
}

function buildPayload() {
  const payload: Record<string, any> = {
    text: sourceText.value,
    length: length.value,
    language: language.value || null,
    source_language: sourceLanguage.value,
    model: model.value,
    num_beams: Number(advanced.num_beams),
    temperature: Number(advanced.temperature),
    hierarchical: advanced.hierarchical,
  };
  const maxTokens = numberOrNull(advanced.max_tokens);
  const minTokens = numberOrNull(advanced.min_tokens);
  const chunkTokens = numberOrNull(advanced.chunk_tokens);
  if (maxTokens !== null) payload.max_tokens = maxTokens;
  if (minTokens !== null) payload.min_tokens = minTokens;
  if (chunkTokens !== null) payload.chunk_tokens = chunkTokens;
  return payload;
}

async function summarize() {
  if (runIssue.value) {
    toasts.error(runIssue.value);
    return;
  }
  loading.value = true;
  serviceError.value = "";
  try {
    if (DEMO) {
      await delay(750);
      applySummary({
        summary: demoSummary.summary,
        model: "t5-small-en",
        model_repo: "farleyknight/cnn_dailymail-summarization-t5-small-2022-09-08",
        source_language: "en",
        source_language_variant: "en",
        language: "en",
        target_language_code: "en",
        translated: false,
        length: length.value,
        input_words: countWords(DEMO_SOURCE),
        output_words: countWords(demoSummary.summary),
        chunk_count: demoSummary.chunk_count,
        hierarchy_levels: 3,
        duration_seconds: demoSummary.duration_seconds,
        warnings: ["Summaries are generated by a compact local model. Verify names, dates and figures before relying on them."],
        parameters: { max_tokens: selectedLength.value?.max_tokens ?? 240, min_tokens: 0, num_beams: advanced.num_beams, temperature: advanced.temperature, chunk_tokens: 512, hierarchical: advanced.hierarchical },
      });
      toasts.success("Demo summary ready");
    } else {
      const data = await api.post<any>("/summary/summarize", buildPayload());
      applySummary(data);
      toasts.success(`Summary ready · ${formatNumber(data.output_words)} words`);
    }
  } catch (error: any) {
    serviceError.value = error.message;
    toasts.error(error.message);
  } finally {
    loading.value = false;
  }
}

async function summarizeAsJob() {
  if (runIssue.value) {
    toasts.error(runIssue.value);
    return;
  }
  if (DEMO) {
    await summarize();
    toasts.info("Demo mode · this run used the synchronous endpoint");
    return;
  }
  submittingJob.value = true;
  try {
    const job = await api.post<Job>("/summary/summarize/job", buildPayload());
    jobs.upsert(job);
    jobs.connect();
    activeJobId.value = job.id;
    startPolling(job.id);
    toasts.success("Summary job queued");
  } catch (error: any) {
    serviceError.value = error.message;
    toasts.error(error.message);
  } finally {
    submittingJob.value = false;
  }
}

function applySummary(data: any) {
  summaryText.value = (data.summary || "").trim();
  resultMeta.value = {
    model: data.model,
    modelLabel: modelLabel(data.model),
    input_words: data.input_words,
    output_words: data.output_words,
    chunk_count: data.chunk_count,
    hierarchy_levels: data.hierarchy_levels,
    duration: data.duration_seconds,
    warnings: data.warnings || [],
    translated: Boolean(data.translated),
    source_language: data.source_language,
    language: data.language,
    parameters: data.parameters || {},
  };
  savePath.value = `documents/summary/summary-${String(data.language || language.value).replace(/[^a-z0-9-]/gi, "-").toLowerCase()}.txt`;
}

async function loadJobResult(jobId: string) {
  const job = jobs.byId(jobId);
  const data: any = job?.result?.data || {};
  try {
    let text = String(data.summary || "").trim();
    if (!text && data.text_path) {
      const file = await api.get<any>(`/files/read?path=${encodeURIComponent(data.text_path)}`);
      text = String(file?.content || "").trim();
      savePath.value = data.text_path;
    }
    if (!text) throw new Error("The summary job finished without readable text.");
    applySummary({ ...data, summary: text });
    if (data.text_path) savePath.value = data.text_path;
    toasts.success("Summary job complete");
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
    sourceText.value = DEMO_SOURCE;
    toasts.info(`Demo mode · loaded sample text instead of ${file?.name || path}`);
    return;
  }
  try {
    const data = await api.get<any>(`/files/read?path=${encodeURIComponent(path)}`);
    sourceText.value = data.content || "";
    if (data.truncated) toasts.info("The file was truncated to the service read limit");
    toasts.success(`Loaded ${file?.name || path}`);
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function useSample() {
  sourceText.value = DEMO_SOURCE;
  sourceLanguage.value = "en";
  language.value = "en";
  toasts.info("Sample annual report loaded");
}

async function copySummary() {
  if (!summaryText.value) return;
  try {
    await navigator.clipboard.writeText(summaryText.value);
    toasts.success("Summary copied");
  } catch {
    toasts.error("Could not access the clipboard");
  }
}

function downloadSummary() {
  if (!summaryText.value) return;
  const blob = new Blob([summaryText.value], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `summary-${language.value}.txt`;
  anchor.click();
  URL.revokeObjectURL(url);
}

async function saveToFiles() {
  if (!summaryText.value.trim()) {
    toasts.error("There is no summary to save");
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
      await api.post("/files/write", { path: savePath.value.trim(), content: summaryText.value });
      toasts.success(`Saved to ${savePath.value.trim()}`);
    }
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function openWorkflow() {
  emit("open-workflow");
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

function numberOrNull(value: any) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function cap(value: string) {
  return value ? value.charAt(0).toUpperCase() + value.slice(1) : value;
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
</script>

<template>
  <div :class="props.embedded ? 'summary-embed' : 'page'">
    <PageHeader
      v-if="!props.embedded"
      eyebrow="Hierarchical T5"
      title="Summaries"
      subtitle="Compact local summaries in English and Portuguese. Long documents are split into token-aware chunks, reduced level by level, then assembled into a final summary with a length budget."
    >
      <template #actions>
        <span class="chip" :class="{ success: summaryOnline, danger: !summaryOnline }">
          <span class="dot" :class="summaryOnline ? 'online' : 'offline'" /> {{ resultMeta?.modelLabel || "T5 summary service" }}
        </span>
        <span class="chip"><Cpu :size="11" /> {{ statusInfo?.device || "cpu" }}</span>
        <button class="btn btn-sm" :disabled="serviceBusy" @click="refreshService"><RefreshCw :size="13" :class="{ spin: serviceBusy }" /> Service</button>
      </template>
    </PageHeader>

    <div v-else class="summary-embed-bar">
      <div class="row small muted summary-embed-meta">
        <span class="chip" :class="{ success: summaryOnline, danger: !summaryOnline }">
          <span class="dot" :class="summaryOnline ? 'online' : 'offline'" /> {{ resultMeta?.modelLabel || "T5 summary service" }}
        </span>
        <span class="chip"><Cpu :size="11" /> {{ statusInfo?.device || "cpu" }}</span>
        <span class="summary-embed-note">Hierarchical T5 summaries · long documents are chunked and reduced level by level.</span>
      </div>
      <button class="btn btn-sm" :disabled="serviceBusy" @click="refreshService"><RefreshCw :size="13" :class="{ spin: serviceBusy }" /> Service</button>
    </div>

    <section class="panel" style="margin-bottom: 14px">
      <div class="panel-head">
        <div>
          <h3>Summary controls</h3>
          <p>Pick a length budget, language and model. Advanced controls are optional.</p>
        </div>
        <div class="row" style="gap: 7px">
          <button class="btn btn-primary" :disabled="!canSummarize" @click="summarize">
            <Loader2 v-if="loading" :size="14" class="spin" /><Wand2 v-else :size="14" /> {{ loading ? "Summarizing…" : "Summarize" }}
          </button>
          <button class="btn" :disabled="!canSummarize || submittingJob" @click="summarizeAsJob">
            <Loader2 v-if="submittingJob" :size="14" class="spin" /><Play v-else :size="14" /> Run as job
          </button>
        </div>
      </div>
      <div class="panel-body stack">
        <div class="grid grid-4">
          <div class="field">
            <label>Length</label>
            <div class="seg">
              <button v-for="option in lengthOptions" :key="option.id" class="seg-btn" :class="{ active: length === option.id }" @click="length = option.id">
                {{ option.label }}
              </button>
            </div>
            <span class="hint">{{ selectedLength?.max_tokens ? `Target ≈ ${selectedLength.max_tokens} output tokens` : "Model default budget" }}</span>
          </div>
          <div class="field">
            <label>Summary language</label>
            <select v-model="language" class="select">
              <option v-for="option in languageOptions" :key="option.code" :value="option.code">{{ option.label }}</option>
            </select>
            <span class="hint">Summaries are produced in English or Portuguese.</span>
          </div>
          <div class="field">
            <label>Source language</label>
            <select v-model="sourceLanguage" class="select">
              <option v-for="option in sourceLanguageOptions" :key="option.code" :value="option.code">{{ option.label }}</option>
            </select>
            <span class="hint">Select it explicitly if detection is ambiguous.</span>
          </div>
          <div class="field">
            <label>Model</label>
            <select v-model="model" class="select">
              <option v-for="item in modelItems" :key="item.id" :value="item.id" :disabled="(item.available === false && item.id !== 'auto') || !modelSupportsLanguage(item)">{{ item.name }}{{ item.available === false && item.id !== 'auto' ? " · not installed" : "" }}{{ !modelSupportsLanguage(item) ? " · other language" : "" }}</option>
            </select>
            <span class="hint">{{ selectedModel?.language === "auto" ? "Matched to the detected source language." : `Optimised for ${languageLabel(selectedModel?.language)}.` }}</span>
          </div>
        </div>

        <div class="row-between">
          <button class="btn btn-sm btn-ghost" @click="advancedOpen = !advancedOpen">
            <Gauge :size="12" /> {{ advancedOpen ? "Hide" : "Show" }} advanced generation controls
          </button>
          <div class="row small muted" style="gap: 7px">
            <span>{{ sourceWords }} source words</span>
            <span>·</span>
            <span>{{ statusInfo?.runtime?.transformers === false ? "Transformers missing" : "Transformers ready" }}</span>
            <span v-if="stats.translated" class="chip warn">translated summary</span>
          </div>
        </div>

        <div v-if="advancedOpen" class="grid grid-4">
          <div class="field"><label>Max tokens</label><input v-model.number="advanced.max_tokens" class="input" type="number" min="16" max="4096" placeholder="Auto" /></div>
          <div class="field"><label>Min tokens</label><input v-model.number="advanced.min_tokens" class="input" type="number" min="0" max="4096" placeholder="0" /></div>
          <div class="field"><label>Num beams</label><input v-model.number="advanced.num_beams" class="input" type="number" min="1" max="16" /></div>
          <div class="field"><label>Temperature</label><input v-model.number="advanced.temperature" class="input" type="number" min="0" max="2" step="0.1" /></div>
          <div class="field"><label>Chunk tokens</label><input v-model.number="advanced.chunk_tokens" class="input" type="number" min="64" max="2048" placeholder="Auto" /></div>
          <div class="field">
            <label>Hierarchical map-reduce</label>
            <button class="switch" :class="{ on: advanced.hierarchical }" @click="advanced.hierarchical = !advanced.hierarchical" />
            <span class="hint">{{ advanced.hierarchical ? "Every chunk contributes to the final summary." : "Only the beginning of long documents is summarized." }}</span>
          </div>
        </div>

        <div v-if="runIssue" class="chip warn" style="align-self: flex-start"><AlertTriangle :size="11" /> {{ runIssue }}</div>
      </div>
    </section>

    <div v-if="serviceError" class="alert error" style="margin-bottom: 14px">{{ serviceError }}</div>

    <div class="grid grid-2">
      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Source document</h3>
            <p>{{ sourceWords }} words · {{ sourceParagraphs }} paragraphs · {{ formatNumber(sourceChars) }} characters</p>
          </div>
          <div class="row" style="gap: 6px">
            <button class="btn btn-sm" @click="filePickerOpen = true"><FolderOpen :size="13" /> Load file</button>
            <button class="btn btn-sm btn-ghost" @click="sourceText = ''"><FileText :size="13" /> Clear</button>
          </div>
        </div>
        <div class="panel-body stack">
          <textarea v-model="sourceText" class="textarea document-editor" spellcheck="false" placeholder="Paste a report, article, transcript or book chapter here." />
          <div class="row-between small muted">
            <span>{{ sourceChars.toLocaleString() }} characters</span>
            <button class="btn btn-sm btn-ghost" @click="useSample"><Sparkles :size="12" /> Use sample report</button>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Summary</h3>
            <p>{{ resultMeta ? `${modelLabelText} · ${durationLabel(resultMeta.duration)}` : "The generated summary appears here, ready to edit." }}</p>
          </div>
          <div class="row" style="gap: 6px">
            <button class="btn btn-sm btn-ghost" :disabled="!summaryText" @click="copySummary"><Copy :size="13" /> Copy</button>
            <button class="btn btn-sm btn-ghost" :disabled="!summaryText" @click="downloadSummary"><Download :size="13" /> .txt</button>
          </div>
        </div>
        <div class="panel-body stack">
          <textarea v-model="summaryText" class="textarea summary-editor" spellcheck="false" placeholder="Summary output…" />
          <div class="row-between small muted">
            <span>{{ summaryWords }} words · {{ formatNumber(summaryChars) }} characters</span>
            <span v-if="resultMeta?.model" class="chip">{{ resultMeta.modelLabel || resultMeta.model }}</span>
          </div>
          <div class="field">
            <label>Save to shared files</label>
            <div class="input-group">
              <input v-model="savePath" class="input mono" placeholder="documents/summary/summary.txt" />
              <button class="btn" :disabled="!summaryText" @click="saveToFiles"><Save :size="13" /> Save</button>
            </div>
          </div>
          <div v-for="warning in (resultMeta?.warnings || []).slice(0, 2)" :key="warning" class="alert warn">{{ warning }}</div>
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

    <div class="grid summary-lower-grid">
      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Run details</h3>
            <p>Everything the summary service reported for this run.</p>
          </div>
          <div class="row" style="gap: 6px">
            <span class="chip">{{ languageLabel(resultMeta?.source_language || sourceLanguage) }} → {{ languageLabel(resultMeta?.language || language) }}</span>
            <span v-if="resultMeta?.chunk_count" class="chip"><Layers :size="11" /> {{ resultMeta.chunk_count }} chunks</span>
          </div>
        </div>
        <div class="panel-body stack" style="gap: 8px">
          <div class="row-between small"><span class="muted">Model</span><span class="mono">{{ resultMeta?.model || "—" }}</span></div>
          <div class="row-between small"><span class="muted">Requested length</span><span class="mono">{{ length }} · {{ selectedLength?.max_tokens || "auto" }} tokens</span></div>
          <div class="row-between small"><span class="muted">Chunks / levels</span><span class="mono">{{ stats.chunks || "—" }} / {{ stats.levels || "—" }}</span></div>
          <div class="row-between small"><span class="muted">Decoding</span><span class="mono">{{ advanced.num_beams }} beams · temp {{ advanced.temperature }}</span></div>
          <div class="row-between small"><span class="muted">Max / min tokens</span><span class="mono">{{ resultMeta?.parameters?.max_tokens ?? "auto" }} / {{ resultMeta?.parameters?.min_tokens ?? 0 }}</span></div>
          <div class="row-between small"><span class="muted">Hierarchical</span><span class="chip" :class="advanced.hierarchical ? 'success' : 'warn'">{{ advanced.hierarchical ? "on" : "off" }}</span></div>
          <div class="row-between small"><span class="muted">Device</span><span class="mono">{{ statusInfo?.device || "cpu" }}</span></div>
          <div class="row-between small"><span class="muted">Translated summary</span><span class="chip" :class="stats.translated ? 'warn' : 'success'">{{ stats.translated ? "yes" : "no" }}</span></div>
          <div v-for="warning in stats.warnings" :key="warning" class="alert warn">{{ warning }}</div>
          <div v-if="!stats.warnings.length" class="alert success"><CheckCircle2 :size="13" style="vertical-align: -2px" /> No model warnings for this run.</div>
          <div class="row" style="margin-top: 3px">
            <RouterLink to="/translate" class="btn btn-sm"><Languages :size="12" /> Translate this summary</RouterLink>
            <RouterLink v-if="!props.embedded" to="/documents" class="btn btn-sm btn-ghost"><FileText :size="12" /> Document pipeline</RouterLink>
            <button v-else class="btn btn-sm btn-ghost" @click="openWorkflow"><FileText :size="12" /> Document pipeline</button>
          </div>
        </div>
      </section>

      <div class="stack">
        <section v-if="activeJob" class="panel">
          <div class="panel-head">
            <div><h3>Summary job</h3><p>Queued through the shared job hub.</p></div>
            <RouterLink to="/jobs" class="btn btn-sm btn-ghost">Job center</RouterLink>
          </div>
          <div class="panel-body">
            <JobCard :job="activeJob" @cancel="cancelActiveJob" @retry="retryActiveJob" @remove="removeActiveJob" />
          </div>
        </section>
        <section v-else class="panel">
          <div class="panel-head">
            <div><h3>Background runs</h3><p>Long reports can run through the job hub.</p></div>
            <span class="chip"><Clock :size="11" /> optional</span>
          </div>
          <div class="panel-body">
            <EmptyState :icon="Play" title="No summary job yet" message="Use Run as job for a long document. Progress, cancellation and artifacts appear here with a link to the global job center.">
              <button class="btn btn-sm" :disabled="!canSummarize" @click="summarizeAsJob"><Play :size="12" /> Queue summary</button>
            </EmptyState>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><h3>Service runtime</h3><p>T5 checkpoints available on this host.</p></div>
            <span class="dot" :class="summaryOnline ? 'online' : 'offline'" />
          </div>
          <div class="panel-body stack" style="gap: 7px">
            <div class="row-between small"><span class="muted">Loaded model</span><span class="mono">{{ statusInfo?.loaded_model || "lazy load" }}</span></div>
            <div class="row-between small"><span class="muted">English model</span><span class="chip" :class="statusInfo?.available?.en === false ? 'danger' : 'success'">{{ statusInfo?.available?.en === false ? "missing" : "installed" }}</span></div>
            <div class="row-between small"><span class="muted">Portuguese model</span><span class="chip" :class="statusInfo?.available?.pt === false ? 'danger' : 'success'">{{ statusInfo?.available?.pt === false ? "missing" : "installed" }}</span></div>
            <div class="row-between small"><span class="muted">CPU threads</span><span class="mono">{{ statusInfo?.cpu_threads || "—" }}</span></div>
            <div class="row-between small"><span class="muted">PyTorch</span><span class="chip" :class="statusInfo?.runtime?.torch ? 'success' : 'danger'">{{ statusInfo?.runtime?.torch ? "ready" : "missing" }}</span></div>
            <div class="row-between small"><span class="muted">Transformers</span><span class="chip" :class="statusInfo?.runtime?.transformers ? 'success' : 'danger'">{{ statusInfo?.runtime?.transformers ? "ready" : "missing" }}</span></div>
            <div class="alert" style="margin-top: 4px">
              T5 small is intentionally compact. For critical documents, review numbers, names and dates against the source.
            </div>
          </div>
        </section>
      </div>
    </div>

    <FilePicker v-model="filePickerOpen" title="Load a document to summarize" kind="document" accept=".txt,.md,.csv,.json,.srt,.vtt" @selected="onFileSelected" />
  </div>
</template>

<style scoped>
.seg {
  display: inline-flex;
  gap: 3px;
  padding: 3px;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: rgba(8, 10, 15, 0.5);
}
.seg-btn {
  border: none;
  background: transparent;
  color: var(--muted);
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}
.seg-btn:hover { color: var(--text); }
.seg-btn.active { background: var(--panel-3); color: var(--text); box-shadow: 0 1px 8px rgba(0, 0, 0, 0.3); }

.document-editor { min-height: 360px; font-size: 13px; }
.summary-editor { min-height: 360px; font-size: 13px; line-height: 1.7; }

.summary-lower-grid {
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
  align-items: start;
}
@media (max-width: 1100px) {
  .summary-lower-grid { grid-template-columns: 1fr; }
}

.summary-embed-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(8, 10, 15, 0.32);
}
.summary-embed-meta { gap: 8px; flex-wrap: wrap; }
.summary-embed-note { color: var(--muted-2); }

.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
