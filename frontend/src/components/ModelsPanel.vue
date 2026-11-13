<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { CheckCircle2, Download, HardDrive, Loader2, RefreshCw } from "lucide-vue-next";
import { api } from "@/lib/api";
import { DEMO } from "@/lib/types";
import type { Job } from "@/lib/types";
import { useJobsStore } from "@/stores/jobs";
import { useToastStore } from "@/stores/toasts";
import ProgressBar from "@/components/ProgressBar.vue";

interface ModelItem {
  id: string;
  label: string;
  group: string;
  description: string;
  size: string;
  kind: string;
  service: string;
  installed: boolean;
  detail?: string;
}

const jobs = useJobsStore();
const toasts = useToastStore();
const loading = ref(false);
const error = ref("");
const items = ref<ModelItem[]>([]);
const groups = ref<Array<{ group: string; items: ModelItem[] }>>([]);
const activeJobId = ref("");
const installingId = ref("");

const activeJob = computed(() => (activeJobId.value ? (jobs.byId(activeJobId.value) as Job) || null : null));
const installedCount = computed(() => items.value.filter((item) => item.installed).length);
const totalCount = computed(() => items.value.length);

function demoItems(): ModelItem[] {
  return [
    { id: "llm-llama3.2-3b", label: "Llama 3.2 3B", group: "Language", description: "Lyricist and planner model.", size: "~2.0 GB", kind: "ollama", service: "ollama", installed: true, detail: "installed" },
    { id: "music-ace-step", label: "ACE-Step 1.5 GGUF set", group: "Music", description: "Music engine diffusion + LM weights.", size: "~7.7 GB", kind: "music", service: "music-engine", installed: true, detail: "4/4 GGUF files present" },
    { id: "whisper-large-v3", label: "Whisper large-v3", group: "Subtitles", description: "Highest-quality transcription model.", size: "~3.0 GB", kind: "whisper", service: "srt", installed: false, detail: "not downloaded" },
    { id: "piper-voices", label: "Piper built-in voices", group: "Voice", description: "15 male and female voices.", size: "~1.0 GB", kind: "piper", service: "voice", installed: true, detail: "15/15 voices installed" },
    { id: "image-sdxl", label: "SDXL Base 1.0", group: "Images", description: "1024px diffusion model.", size: "~7 GB", kind: "diffusers", service: "imagegen", installed: false, detail: "not downloaded" },
    { id: "qvac-wan2-1-t2v", label: "QVAC · Wan 2.1 T2V", group: "QVAC", description: "Wan text-to-video diffusion, UMT5 encoder and VAE.", size: "~14.5 GB", kind: "qvac", service: "qvac", installed: true, detail: "3/3 assets installed" },
    { id: "qvac-flux2-klein", label: "QVAC · FLUX.2-klein", group: "QVAC", description: "FLUX.2 image diffusion, Qwen3 encoder and VAE.", size: "~5.2 GB", kind: "qvac", service: "qvac", installed: false, detail: "0/3 assets installed" },
  ];
}

function groupItems(list: ModelItem[]) {
  const order = ["Language", "Music", "Voice", "Subtitles", "Text", "Images", "QVAC"];
  const map = new Map<string, ModelItem[]>();
  for (const item of list) {
    if (!map.has(item.group)) map.set(item.group, []);
    map.get(item.group)!.push(item);
  }
  return order.filter((group) => map.has(group)).map((group) => ({ group, items: map.get(group)! }));
}

async function load() {
  if (DEMO) {
    items.value = demoItems();
    groups.value = groupItems(items.value);
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const data = await api.get<{ items: ModelItem[]; groups: Array<{ group: string; items: ModelItem[] }> }>("/admin/models");
    items.value = data.items || [];
    groups.value = data.groups || groupItems(items.value);
  } catch (err: any) {
    error.value = err?.message || "Could not load model catalog";
  } finally {
    loading.value = false;
  }
}

async function install(item: ModelItem, force = false) {
  if (item.installed && !force) return;
  installingId.value = item.id;
  try {
    if (DEMO) {
      item.installed = true;
      item.detail = "installed (demo)";
      installingId.value = "";
      toasts.success(`${item.label} installed (demo)`);
      return;
    }
    const response = await api.post<{ item: ModelItem; job: Job | null; message: string }>(
      `/admin/models/${item.id}/install${force ? "?force=true" : ""}`,
    );
    if (response.job?.id) {
      jobs.upsert(response.job);
      jobs.connect();
      activeJobId.value = response.job.id;
    }
    toasts.info(response.message || `${item.label} download queued`);
    if (!response.job) {
      installingId.value = "";
      await load();
    }
  } catch (err: any) {
    installingId.value = "";
    toasts.error(err?.message || "Could not start model download");
  }
}

watch(
  () => activeJob.value?.status,
  (status) => {
    if (!status) return;
    if (["completed", "failed", "canceled"].includes(status)) {
      installingId.value = "";
      window.setTimeout(() => void load(), 500);
    }
  },
);

onMounted(() => {
  void load();
});
</script>

<template>
  <section class="panel">
    <div class="panel-head">
      <div>
        <h3>Models</h3>
        <p>Download model packs once. QVAC packs installed here become the selectable models in QVAC generation. Everything is stored under <span class="mono">data/</span> and survives restarts.</p>
      </div>
      <div class="row" style="gap: 7px">
        <span class="chip success">{{ installedCount }}/{{ totalCount }} installed</span>
        <button class="btn btn-sm" :disabled="loading" @click="load"><RefreshCw :size="12" :class="{ spin: loading }" /> Refresh</button>
      </div>
    </div>

    <div v-if="activeJob" class="panel-body" style="padding-bottom: 0">
      <div class="model-job">
        <div class="row-between">
          <span class="small strong">{{ activeJob.title }}</span>
          <span class="badge" :class="activeJob.status === 'failed' ? 'failed' : activeJob.status">{{ activeJob.status }}</span>
        </div>
        <div class="small muted" style="margin-top: 3px">{{ activeJob.stage }} — {{ activeJob.message }}</div>
        <ProgressBar :value="activeJob.progress" show-label style="margin-top: 7px" />
      </div>
    </div>

    <div v-if="error" class="panel-body"><div class="alert error">{{ error }}</div></div>
    <div v-else-if="loading && !items.length" class="panel-body stack">
      <div v-for="index in 4" :key="index" class="skeleton" style="height: 72px" />
    </div>
    <div v-else class="panel-body stack model-groups">
      <div v-for="group in groups" :key="group.group" class="stack" style="gap: 8px">
        <div class="row-between" style="margin-top: 4px">
          <div class="eyebrow" style="margin: 0">{{ group.group }}</div>
          <span class="small muted">{{ group.items.filter((item) => item.installed).length }}/{{ group.items.length }}</span>
        </div>
        <div class="model-grid">
          <article v-for="item in group.items" :key="item.id" class="model-card">
            <div class="row-between" style="align-items: flex-start">
              <div style="min-width: 0">
                <div class="strong">{{ item.label }}</div>
                <div class="small muted" style="margin-top: 3px">{{ item.description }}</div>
              </div>
              <span class="badge" :class="item.installed ? 'success' : 'queued'">{{ item.installed ? "installed" : "available" }}</span>
            </div>
            <div class="row" style="gap: 5px; margin-top: 9px">
              <span class="chip"><HardDrive :size="10" /> {{ item.size }}</span>
              <span class="chip">{{ item.detail || item.service }}</span>
            </div>
            <div class="row" style="justify-content: flex-end; gap: 6px; margin-top: 6px">
              <span v-if="item.installed" class="small success"><CheckCircle2 :size="12" /> Ready</span>
              <button v-if="item.installed" class="btn btn-sm" :disabled="installingId === item.id" title="Verify installed files and download anything missing" @click="install(item, true)">
                <Loader2 v-if="installingId === item.id" :size="12" class="spin" />
                <RefreshCw v-else :size="12" />
                Re-check
              </button>
              <button v-else class="btn btn-sm btn-primary" :disabled="installingId === item.id" @click="install(item)">
                <Loader2 v-if="installingId === item.id" :size="12" class="spin" />
                <Download v-else :size="12" />
                Install
              </button>
            </div>
          </article>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.model-groups { gap: 15px; }
.model-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.model-card { padding: 12px; border: 1px solid var(--line); border-radius: 11px; background: rgba(17, 21, 30, 0.65); }
.model-card:hover { border-color: var(--line-strong); }
.model-job { padding: 11px; border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 10px; background: rgba(139, 92, 246, 0.05); }
.small.success { color: var(--success); display: inline-flex; align-items: center; gap: 4px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .model-grid { grid-template-columns: 1fr; } }
</style>
