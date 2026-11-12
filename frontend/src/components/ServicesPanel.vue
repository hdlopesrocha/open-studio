<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  AlertTriangle,
  CheckCircle2,
  Container,
  Hammer,
  Loader2,
  Power,
  RefreshCw,
  RotateCcw,
  ScrollText,
  ShieldCheck,
  Square,
  Trash2,
} from "lucide-vue-next";
import { api } from "@/lib/api";
import { DEMO, demoServices } from "@/lib/demo";
import { useJobsStore } from "@/stores/jobs";
import { useToastStore } from "@/stores/toasts";
import BaseModal from "@/components/BaseModal.vue";
import JobCard from "@/components/JobCard.vue";
import ProgressBar from "@/components/ProgressBar.vue";

interface Service {
  name: string;
  label: string;
  description: string;
  group: string;
  core: boolean;
  enabled: boolean;
  running: boolean;
  state: string;
  health: string;
  image: string;
  image_built: boolean;
  requires: string[];
  container: string;
  status: string;
}

const jobs = useJobsStore();
const toasts = useToastStore();
const items = ref<Service[]>([]);
const loading = ref(false);
const error = ref("");
const busyService = ref("");
const activeJobId = ref("");
const logsOpen = ref(false);
const logsService = ref("");
const logsText = ref("");
const logsLoading = ref(false);
const deleteOpen = ref(false);
const deleting = ref(false);
const deleteResult = ref("");

const activeJob = computed(() => (activeJobId.value ? jobs.byId(activeJobId.value) : null));
const groups = computed(() => {
  const order = ["Core", "Create", "Engines", "Video helpers", "Text", "Tools", "Core AI", "Services"];
  const grouped = new Map<string, Service[]>();
  for (const service of items.value) {
    if (!grouped.has(service.group)) grouped.set(service.group, []);
    grouped.get(service.group)!.push(service);
  }
  return order.filter((group) => grouped.has(group)).map((group) => ({ group, items: grouped.get(group)! }));
});
const runningCount = computed(() => items.value.filter((service) => service.running).length);
const enabledCount = computed(() => items.value.filter((service) => service.enabled).length);
const adminJobs = computed(() => jobs.items.filter((job) => job.component === "admin").slice(0, 5));
const jobOutput = computed(() => {
  const output = activeJob.value?.result?.data?.output;
  return Array.isArray(output) ? output.join("\n") : "";
});

async function load() {
  loading.value = true;
  error.value = "";
  if (DEMO) {
    items.value = demoServices.items as Service[];
    loading.value = false;
    return;
  }
  try {
    const data = await api.get<{ items: Service[] }>("/admin/services");
    items.value = data.items;
  } catch (err: any) {
    error.value = err?.message || "Could not read service state";
  } finally {
    loading.value = false;
  }
}

onMounted(async () => {
  await load();
  if (!DEMO && !items.value.length && !error.value) {
    window.setTimeout(load, 1200);
  }
});

watch(
  () => (activeJob.value ? `${activeJob.value.status}:${activeJob.value.progress}` : ""),
  (next, previous) => {
    if (!next) {
      // The active job disappeared (hub restart or history refresh).
      busyService.value = "";
      return;
    }
    if (next === previous) return;
    if (next.startsWith("completed") || next.startsWith("failed") || next.startsWith("canceled")) {
      window.setTimeout(() => {
        load();
        busyService.value = "";
      }, 700);
    }
  },
);

async function control(service: Service, action: "enable" | "disable" | "build" | "restart") {
  if (service.core && action !== "restart") {
    toasts.info("Core services are always on.");
    return;
  }
  if (DEMO) {
    if (action === "enable") {
      service.enabled = true;
      service.running = true;
      service.state = "running";
      service.health = "healthy";
      toasts.success(`${service.label} enabled (demo)`);
    } else if (action === "disable") {
      service.enabled = false;
      service.running = false;
      service.state = "absent";
      service.health = "disabled";
      toasts.success(`${service.label} disabled (demo)`);
    } else {
      toasts.success(`${service.label}: ${action} simulated`);
    }
    return;
  }
  busyService.value = service.name;
  try {
    const job = await jobs.submit(
      "admin",
      action,
      `${action === "enable" ? "Enable" : action === "disable" ? "Disable" : action === "build" ? "Build" : "Restart"} ${service.label}`,
      { service: service.name },
    );
    activeJobId.value = job.id;
    toasts.info(`${service.label}: ${action} queued`);
  } catch (err: any) {
    busyService.value = "";
    toasts.error(err?.message || `${action} failed`);
  }
}

async function showLogs(service: Service) {
  logsService.value = service.name;
  logsText.value = "";
  logsOpen.value = true;
  logsLoading.value = true;
  try {
    if (DEMO) {
      logsText.value = `[demo] ${service.name} is running\nhealth: ${service.health}\nimage: ${service.image}\n\nNo live logs in demo mode.`;
    } else {
      const data = await api.get<{ lines: string[] }>(`/admin/services/${service.name}/logs?lines=300`);
      logsText.value = (data.lines || []).join("\n") || "No log lines.";
    }
  } catch (err: any) {
    logsText.value = err?.message || "Could not read logs";
  } finally {
    logsLoading.value = false;
  }
}

async function deleteAllFiles() {
  deleting.value = true;
  deleteResult.value = "";
  try {
    if (DEMO) {
      deleteResult.value = "Demo: all files would be deleted.";
    } else {
      const data = await api.post<any>("/admin/files/delete-all", { confirm: "DELETE" });
      deleteResult.value = `Deleted ${data.removed} item(s), freed ${(data.bytes_freed / 1024 ** 2).toFixed(1)} MB.`;
    }
    toasts.success("Shared files cleared");
  } catch (err: any) {
    toasts.error(err?.message || "Could not delete files");
  } finally {
    deleting.value = false;
  }
}

function dotClass(service: Service) {
  if (service.running && ["healthy", "running"].includes(service.health)) return "online";
  if (service.running && service.health === "starting") return "busy";
  if (service.running) return "busy";
  return "offline";
}
</script>

<template>
  <div class="stack">
    <section class="panel">
      <div class="panel-head">
        <div>
          <h3>Service control</h3>
          <p>Core is always on. Enable only what you need; the image is built and the container starts on demand.</p>
        </div>
        <div class="row" style="gap: 7px">
          <span class="chip success">{{ runningCount }} running</span>
          <span class="chip">{{ enabledCount }} enabled</span>
          <button class="btn btn-sm" :disabled="loading" @click="load"><RefreshCw :size="13" :class="{ spin: loading }" /> Refresh</button>
        </div>
      </div>
      <div v-if="error" class="panel-body"><div class="alert error">{{ error }}</div></div>
      <div v-else-if="loading" class="panel-body stack"><div v-for="i in 6" :key="i" class="skeleton" style="height: 58px" /></div>
      <div v-else class="panel-body stack">
        <div v-if="activeJob" class="job-card running">
          <div class="row-between">
            <span class="small strong">{{ activeJob.title }}</span>
            <span class="badge running">{{ activeJob.status }}</span>
          </div>
          <div class="small muted">{{ activeJob.stage }} — {{ activeJob.message }}</div>
          <ProgressBar :value="activeJob.progress" show-label />
          <div class="row" style="gap: 6px">
            <button class="btn btn-sm btn-danger" @click="jobs.cancel(activeJob.id)"><Square :size="12" /> Cancel</button>
          </div>
          <pre v-if="jobOutput" class="code" style="max-height: 210px">{{ jobOutput }}</pre>
        </div>

        <div v-for="group in groups" :key="group.group" class="stack" style="gap: 8px">
          <div class="row-between" style="margin-top: 4px">
            <div class="eyebrow" style="margin: 0">{{ group.group }}</div>
            <span class="small muted">{{ group.items.filter((s) => s.running).length }}/{{ group.items.length }} running</span>
          </div>
          <div class="grid grid-2" style="gap: 9px">
            <div v-for="service in group.items" :key="service.name" class="service-row" :class="{ enabled: service.running }">
              <div class="row" style="gap: 9px; min-width: 0; align-items: flex-start">
                <span class="dot" :class="dotClass(service)" style="margin-top: 5px" />
                <div style="min-width: 0">
                  <div class="row" style="gap: 7px">
                    <span class="strong small">{{ service.label }}</span>
                    <span v-if="service.core" class="badge success">core</span>
                    <span v-else-if="service.running" class="badge success">on</span>
                    <span v-else class="badge queued">off</span>
                    <span v-if="service.health === 'unhealthy'" class="badge failed">unhealthy</span>
                  </div>
                  <div class="small muted" style="margin-top: 3px">{{ service.description }}</div>
                  <div class="row" style="gap: 5px; margin-top: 6px">
                    <span class="chip">{{ service.name }}</span>
                    <span class="chip" :class="{ success: service.image_built }">{{ service.image_built ? "image built" : "not built" }}</span>
                    <span v-if="service.requires.length" class="chip warn">requires {{ service.requires.join(", ") }}</span>
                  </div>
                </div>
              </div>
              <div class="row" style="gap: 4px; justify-content: flex-end; flex-wrap: wrap">
                <button class="icon-btn" title="Logs" @click="showLogs(service)"><ScrollText :size="14" /></button>
                <button class="icon-btn" title="Restart" :disabled="!service.running || busyService === service.name" @click="control(service, 'restart')"><RotateCcw :size="14" /></button>
                <button v-if="!service.running && !service.core" class="btn btn-sm" :disabled="busyService === service.name" @click="control(service, 'build')"><Hammer :size="12" /> Build</button>
                <button v-if="!service.running && !service.core" class="btn btn-sm btn-primary" :disabled="busyService === service.name" @click="control(service, 'enable')"><Power :size="12" /> Enable</button>
                <button v-if="service.running && !service.core" class="btn btn-sm btn-danger" :disabled="busyService === service.name" @click="control(service, 'disable')"><Square :size="12" /> Disable</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div><h3>Docker operations</h3><p>Every enable, disable, build or restart is a normal global job. Its compose output is kept here.</p></div>
        <button class="btn btn-sm btn-ghost" @click="jobs.refresh"><RefreshCw :size="12" /> Refresh jobs</button>
      </div>
      <div class="panel-body stack">
        <JobCard v-for="job in adminJobs" :key="job.id" :job="job" @cancel="jobs.cancel" @retry="jobs.retry" @remove="jobs.remove" />
        <div v-if="!adminJobs.length" class="small muted">No Docker operations yet. Toggle a service above.</div>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div><h3>Shared file cleanup</h3><p>Delete every file under the shared home. Voices, generated media and uploads are removed; models and state are kept.</p></div>
        <Trash2 :size="17" style="color: var(--danger)" />
      </div>
      <div class="panel-body row-between">
        <div class="small muted">This is irreversible. Use <span class="kbd">make backup</span> first if you need a copy.</div>
        <button class="btn btn-danger" @click="deleteOpen = true"><Trash2 :size="13" /> Delete all files</button>
      </div>
    </section>

    <BaseModal v-model="logsOpen" :title="`Logs · ${logsService}`" subtitle="Last 300 lines." width="wide">
      <div v-if="logsLoading" class="skeleton" style="height: 220px" />
      <pre v-else class="code" style="max-height: 520px">{{ logsText }}</pre>
      <template #footer><button class="btn" @click="logsOpen = false">Close</button></template>
    </BaseModal>

    <BaseModal v-model="deleteOpen" title="Delete all shared files?" subtitle="Voices, uploads, projects and generated media will be removed." width="narrow">
      <div class="alert error">This cannot be undone. Models under <span class="mono">data/models</span> and service state are not touched.</div>
      <div v-if="deleteResult" class="alert success" style="margin-top: 10px">{{ deleteResult }}</div>
      <template #footer>
        <button class="btn" @click="deleteOpen = false">Cancel</button>
        <button class="btn btn-danger" :disabled="deleting" @click="deleteAllFiles">
          <Loader2 v-if="deleting" :size="13" class="spin" /><Trash2 v-else :size="13" /> Delete everything
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<style scoped>
.service-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 11px;
  background: rgba(17, 21, 30, 0.65);
}
.service-row.enabled { border-color: rgba(52, 211, 153, 0.2); }
.service-row:hover { border-color: var(--line-strong); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1100px) {
  .service-row { flex-direction: column; }
}
</style>
