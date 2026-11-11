<script setup lang="ts">
import { computed } from "vue";
import { Ban, Download, RotateCcw, Trash2, ExternalLink, AlertTriangle } from "lucide-vue-next";
import { downloadUrl, fileUrl, formatBytes, relativeTime } from "@/lib/api";
import type { Job } from "@/lib/types";
import JobStatus from "./JobStatus.vue";
import ProgressBar from "./ProgressBar.vue";

const props = withDefaults(defineProps<{ job: Job; compact?: boolean }>(), { compact: false });
const emit = defineEmits<{ cancel: [id: string]; retry: [id: string]; remove: [id: string] }>();
const active = computed(() => ["queued", "running", "canceling"].includes(props.job.status));
const elapsed = computed(() => {
  const start = props.job.started_at ? new Date(props.job.started_at).getTime() : new Date(props.job.created_at).getTime();
  const end = props.job.finished_at ? new Date(props.job.finished_at).getTime() : Date.now();
  const seconds = Math.max(0, Math.round((end - start) / 1000));
  return seconds > 3600 ? `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m` : seconds > 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`;
});
const artifacts = computed(() => props.job.artifacts || []);
const resultFiles = computed(() => {
  const files = props.job.result?.files;
  if (!Array.isArray(files)) return [];
  const seen = new Set(artifacts.value.map((item) => item.path));
  return files.filter((item: any) => item?.path && !seen.has(item.path));
});
const outputLog = computed(() => {
  const value = props.job.result?.data?.output;
  if (Array.isArray(value)) return value.slice(-12).join("\n");
  if (typeof value === "string") return value.split("\n").slice(-12).join("\n");
  return "";
});
</script>

<template>
  <div class="job-card" :class="job.status">
    <div class="row-between">
      <div class="row" style="gap: 7px; min-width: 0">
        <span class="badge">{{ job.component }}</span>
        <span class="small strong truncate">{{ job.title }}</span>
      </div>
      <JobStatus :status="job.status" />
    </div>
    <div class="small muted truncate">{{ job.stage || job.action }} — {{ job.message || "Waiting" }}</div>
    <ProgressBar :value="job.progress" :warn="job.status === 'failed'" thin />
    <div class="row-between small muted">
      <span class="mono">{{ Math.round(job.progress) }}% · {{ elapsed }}</span>
      <span>{{ relativeTime(job.created_at) }}</span>
    </div>
    <div v-if="job.warnings?.length" class="alert warn" style="display: flex; gap: 7px; align-items: flex-start">
      <AlertTriangle :size="13" style="flex: none; margin-top: 1px" />
      <span>{{ job.warnings.slice(-2).join(" · ") }}</span>
    </div>
    <div v-if="job.error" class="alert error">{{ job.error }}</div>
    <pre v-if="outputLog" class="code" style="max-height: 150px">{{ outputLog }}</pre>
    <div v-if="artifacts.length || resultFiles.length" class="row" style="gap: 6px">
      <a
        v-for="file in [...artifacts, ...resultFiles].slice(0, 6)"
        :key="file.path"
        class="btn btn-sm"
        :href="downloadUrl(file.path)"
        target="_blank"
        rel="noopener"
      >
        <Download :size="12" />
        {{ file.name || file.path.split("/").pop() }}
        <span v-if="file.size" class="muted">{{ formatBytes(file.size) }}</span>
      </a>
    </div>
    <div class="row" style="gap: 6px">
      <button v-if="active" class="btn btn-sm btn-danger" @click="emit('cancel', job.id)"><Ban :size="12" /> Cancel</button>
      <button v-if="job.status === 'failed' || job.status === 'canceled'" class="btn btn-sm" @click="emit('retry', job.id)"><RotateCcw :size="12" /> Retry</button>
      <button v-if="!active" class="btn btn-sm btn-ghost" @click="emit('remove', job.id)"><Trash2 :size="12" /> Delete</button>
      <a v-if="job.result?.video_path" class="btn btn-sm btn-ghost" :href="fileUrl(job.result.video_path)" target="_blank" rel="noopener"><ExternalLink :size="12" /> Open</a>
    </div>
  </div>
</template>
