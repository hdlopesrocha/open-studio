<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Activity, Ban, Layers, RefreshCw, RotateCcw, Trash2 } from "lucide-vue-next";
import { useJobsStore } from "@/stores/jobs";
import { useToastStore } from "@/stores/toasts";
import { formatBytes, relativeTime } from "@/lib/api";
import PageHeader from "@/components/PageHeader.vue";
import JobCard from "@/components/JobCard.vue";
import TabsBar from "@/components/TabsBar.vue";
import EmptyState from "@/components/EmptyState.vue";
import ProgressBar from "@/components/ProgressBar.vue";

const jobs = useJobsStore();
const toasts = useToastStore();
const filter = ref<"active" | "all" | "completed" | "failed">("active");
const busy = ref(false);

const tabs = computed(() => [
  { id: "active", label: "Active", count: jobs.activeCount },
  { id: "all", label: "All", count: jobs.total },
  { id: "completed", label: "Completed" },
  { id: "failed", label: "Failed / canceled" },
]);

const shown = computed(() => {
  const list = filter.value === "active" ? jobs.items.filter((job) => ["queued", "running", "canceling"].includes(job.status)) : filter.value === "all" ? jobs.items : filter.value === "completed" ? jobs.items.filter((job) => job.status === "completed") : jobs.items.filter((job) => ["failed", "canceled"].includes(job.status));
  return [...list].sort((a, b) => b.created_at.localeCompare(a.created_at));
});

const stats = computed(() => ({
  queued: jobs.items.filter((job) => job.status === "queued").length,
  running: jobs.items.filter((job) => job.status === "running").length,
  completed: jobs.items.filter((job) => job.status === "completed").length,
  failed: jobs.items.filter((job) => job.status === "failed").length,
}));

onMounted(() => {
  if (!jobs.items.length) jobs.refresh();
  jobs.loadQueues();
});

async function refresh() {
  busy.value = true;
  await jobs.refresh();
  busy.value = false;
}

async function cancel(id: string) {
  try {
    await jobs.cancel(id);
    toasts.info("Cancellation requested");
  } catch (error: any) {
    toasts.error(error.message);
  }
}
async function retry(id: string) {
  try {
    await jobs.retry(id);
    toasts.success("Job restarted");
  } catch (error: any) {
    toasts.error(error.message);
  }
}
async function remove(id: string) {
  try {
    await jobs.remove(id);
    toasts.success("Job record removed");
  } catch (error: any) {
    toasts.error(error.message);
  }
}
async function cancelQueued() {
  const queued = jobs.items.filter((job) => job.status === "queued");
  for (const job of queued) await cancel(job.id);
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="Global job system"
      title="Job center"
      subtitle="One persistent queue per component. Music, video, voice, subtitles, images, documents, FFmpeg, yt-dlp and QVAC can run at the same time without blocking each other."
    >
      <template #actions>
        <button class="btn btn-sm" :disabled="busy" @click="refresh"><RefreshCw :size="13" :class="{ spin: busy }" /> Refresh</button>
        <button class="btn btn-sm btn-danger" :disabled="!stats.queued" @click="cancelQueued"><Ban :size="13" /> Cancel queued ({{ stats.queued }})</button>
      </template>
    </PageHeader>

    <div class="stat-grid" style="margin-bottom: 18px">
      <div class="stat"><div class="stat-label">Queued</div><div class="stat-value">{{ stats.queued }}</div><div class="stat-sub">Waiting for a free worker</div></div>
      <div class="stat"><div class="stat-label">Running</div><div class="stat-value">{{ stats.running }}</div><div class="stat-sub">Across {{ jobs.queues.length || 13 }} component queues</div></div>
      <div class="stat"><div class="stat-label">Completed</div><div class="stat-value">{{ stats.completed }}</div><div class="stat-sub">Artifacts in shared storage</div></div>
      <div class="stat"><div class="stat-label">Failed</div><div class="stat-value">{{ stats.failed }}</div><div class="stat-sub">Retry keeps the same parameters</div></div>
    </div>

    <div class="grid" style="grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr); margin-bottom: 18px">
      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Queues</h3>
            <p>Concurrency is configured per component, so heavy jobs can run in parallel.</p>
          </div>
          <span class="chip"><Layers :size="11" /> {{ jobs.queues.length }} workers groups</span>
        </div>
        <div class="panel-body">
          <div class="grid grid-2" style="gap: 10px">
            <div v-for="queue in jobs.queues" :key="queue.component" class="job-card" style="gap: 6px">
              <div class="row-between">
                <span class="small strong" style="text-transform: capitalize">{{ queue.component }}</span>
                <span class="chip">{{ queue.concurrency }}×</span>
              </div>
              <div class="row-between small muted">
                <span>{{ queue.running }} running</span>
                <span>{{ queue.queued }} waiting</span>
              </div>
              <ProgressBar :value="queue.running ? 55 : 0" thin />
            </div>
            <div v-if="!jobs.queues.length" class="small muted">Queue information is loading.</div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Artifacts</h3>
            <p>Every completed job writes into the shared file tree.</p>
          </div>
        </div>
        <div class="panel-body stack">
          <div v-for="job in jobs.items.filter((j) => j.artifacts?.length).slice(0, 4)" :key="job.id" class="list-item" style="padding: 8px 0">
            <span class="file-icon"><Activity :size="14" /></span>
            <span class="grow" style="min-width: 0">
              <span class="small strong truncate" style="display: block">{{ job.title }}</span>
              <span class="small muted">{{ job.artifacts.length }} files · {{ relativeTime(job.finished_at) }}</span>
            </span>
            <span class="small muted mono">{{ formatBytes(job.artifacts.reduce((sum, f) => sum + (f.size || 0), 0)) }}</span>
          </div>
          <div v-if="!jobs.items.some((j) => j.artifacts?.length)" class="small muted">No artifacts yet.</div>
          <RouterLink to="/files" class="btn btn-sm">Open file explorer</RouterLink>
        </div>
      </section>
    </div>

    <section class="panel">
      <div class="panel-head">
        <TabsBar v-model="filter" :tabs="tabs" />
        <span class="small muted">{{ shown.length }} shown</span>
      </div>
      <div class="panel-body stack">
        <JobCard v-for="job in shown" :key="job.id" :job="job" @cancel="cancel" @retry="retry" @remove="remove" />
        <EmptyState v-if="!shown.length" :icon="Activity" title="Nothing in this queue" message="Start a music generation, a video render, a voice take, an SRT alignment or any media operation and it will show up here with live progress and artifacts.">
          <RouterLink to="/" class="btn btn-sm">Browse studios</RouterLink>
        </EmptyState>
      </div>
    </section>
  </div>
</template>

<style scoped>
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
