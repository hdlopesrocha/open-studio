<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { Copy, KeyRound, Loader2, RefreshCw, Server, ShieldCheck, Trash2, WalletCards, X } from "lucide-vue-next";
import { api, formatBytes, relativeTime } from "@/lib/api";
import { useSystemStore } from "@/stores/system";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";
import { DEMO, demoSystemInfo } from "@/lib/demo";
import PageHeader from "@/components/PageHeader.vue";
import ServiceGrid from "@/components/ServiceGrid.vue";
import BaseModal from "@/components/BaseModal.vue";
import CodeBlock from "@/components/CodeBlock.vue";
import TabsBar from "@/components/TabsBar.vue";
import ServicesPanel from "@/components/ServicesPanel.vue";
import ModelsPanel from "@/components/ModelsPanel.vue";

const system = useSystemStore();
const auth = useAuthStore();
const toasts = useToastStore();
const route = useRoute();

const sessions = ref<any[]>([]);
const keys = ref<any[]>([]);
const loading = ref(false);
const keyName = ref("");
const newKey = ref("");
const keyModal = ref(false);
const currentPassword = ref("");
const newPassword = ref("");
const confirmPassword = ref("");
const changing = ref(false);
const info = ref<any>(null);

const tabs = [
  { id: "services", label: "Services" },
  { id: "security", label: "Security" },
  { id: "keys", label: "API keys" },
  { id: "system", label: "System" },
  { id: "models", label: "Models & commands" },
];
const requestedTab = typeof route.query.tab === "string" ? route.query.tab : "";
const tab = ref(tabs.some((entry) => entry.id === requestedTab) ? requestedTab : "services");
watch(
  () => route.query.tab,
  (next) => {
    if (typeof next === "string" && tabs.some((entry) => entry.id === next)) tab.value = next;
  },
);

onMounted(async () => {
  system.load(true);
  if (DEMO) {
    info.value = demoSystemInfo;
    sessions.value = [
      { id: "demo-current", created_at: new Date(Date.now() - 3600_000).toISOString(), last_seen: new Date().toISOString(), expires_at: new Date(Date.now() + 30 * 86400_000).toISOString(), user_agent: "Chrome · Linux", ip: "127.0.0.1", current: true },
      { id: "demo-2", created_at: new Date(Date.now() - 5 * 86400_000).toISOString(), last_seen: new Date(Date.now() - 4 * 3600_000).toISOString(), expires_at: new Date(Date.now() + 25 * 86400_000).toISOString(), user_agent: "Safari · iPhone", ip: "192.168.1.42", current: false },
    ];
    keys.value = [
      { id: "k1", name: "Automation / n8n", prefix: "osk_live_7f2", created_at: new Date(Date.now() - 9 * 86400_000).toISOString(), last_used_at: new Date(Date.now() - 1200_000).toISOString() },
      { id: "k2", name: "CLI uploads", prefix: "osk_live_1a9", created_at: new Date(Date.now() - 30 * 86400_000).toISOString(), last_used_at: null },
    ];
    return;
  }
  await refresh();
});

async function refresh() {
  loading.value = true;
  try {
    const [sessionData, keyData, systemInfo] = await Promise.all([
      api.get<{ items: any[] }>("/auth/sessions"),
      api.get<{ items: any[] }>("/auth/api-keys"),
      api.get<any>("/system/info").catch(() => null),
    ]);
    sessions.value = sessionData.items;
    keys.value = keyData.items;
    info.value = systemInfo;
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    loading.value = false;
  }
}

async function changePassword() {
  if (newPassword.value !== confirmPassword.value) {
    toasts.error("New passwords do not match");
    return;
  }
  changing.value = true;
  try {
    await auth.changePassword(currentPassword.value, newPassword.value);
    toasts.success("Password changed. Other sessions were signed out.");
    currentPassword.value = newPassword.value = confirmPassword.value = "";
    await refresh();
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    changing.value = false;
  }
}

async function createKey() {
  try {
    const data = await api.post<any>("/auth/api-keys", { name: keyName.value || "API key" });
    newKey.value = data.token;
    keyModal.value = true;
    keyName.value = "";
    await refresh();
    toasts.success("API key created");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function revokeKey(id: string) {
  try {
    await api.delete(`/auth/api-keys/${id}`);
    toasts.success("API key revoked");
    await refresh();
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function revokeSession(id: string) {
  try {
    await api.delete(`/auth/sessions/${id}`);
    toasts.success("Session revoked");
    await refresh();
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function copy(value: string) {
  try {
    await navigator.clipboard.writeText(value);
    toasts.success("Copied");
  } catch {}
}

const status = computed(() => system.status);
const gpu = computed(() => status.value?.system?.gpu?.[0]);

const examples = {
  jobs: `curl -H 'Authorization: Bearer osk_…' \\
  http://localhost:8090/api/jobs?limit=10`,
  image: `curl -X POST -H 'Authorization: Bearer osk_…' \\
  -H 'Content-Type: application/json' \\
  http://localhost:8090/api/jobs \\
  -d '{"component":"imagegen","action":"generate",
       "title":"Cover","params":{"prompt":"porcelain city"}}'`,
  upload: `curl -H 'Authorization: Bearer osk_…' \\
  -F file=@master.wav -F path=uploads \\
  http://localhost:8090/api/files/upload`,
};
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="Control room"
      title="Settings"
      subtitle="Security, sessions, API keys, service health, storage and the exact commands needed to download models or rebuild the stack."
    >
      <template #actions>
        <button class="btn btn-sm" @click="refresh"><RefreshCw :size="13" /> Refresh</button>
      </template>
    </PageHeader>

    <div class="tabs" style="margin-bottom: 16px"><TabsBar v-model="tab" :tabs="tabs" /></div>

    <ServicesPanel v-if="tab === 'services'" />
    <div v-else-if="tab === 'security'" class="split">
      <section class="panel">
        <div class="panel-head">
          <div><h3>Change password</h3><p>Scrypt-hashed, stored locally in the auth database.</p></div>
          <ShieldCheck :size="17" style="color: var(--success)" />
        </div>
        <form class="panel-body stack" @submit.prevent="changePassword">
          <div class="field"><label>Current password</label><input v-model="currentPassword" class="input" type="password" autocomplete="current-password" /></div>
          <div class="grid grid-2">
            <div class="field"><label>New password</label><input v-model="newPassword" class="input" type="password" autocomplete="new-password" /></div>
            <div class="field"><label>Confirm new password</label><input v-model="confirmPassword" class="input" type="password" autocomplete="new-password" /></div>
          </div>
          <div class="alert">Changing the password signs out every other session and rotates the current one. API keys stay valid until revoked.</div>
          <button class="btn btn-primary" :disabled="changing || !currentPassword || newPassword.length < 8" type="submit">
            <Loader2 v-if="changing" :size="14" class="spin" /><KeyRound v-else :size="14" /> Update password
          </button>
        </form>
      </section>

      <section class="panel">
        <div class="panel-head"><div><h3>Active sessions</h3><p>HttpOnly cookies expire after 30 days.</p></div><span class="chip">{{ sessions.length }}</span></div>
        <div class="panel-body list">
          <div v-for="session in sessions" :key="session.id" class="list-item">
            <span class="file-icon"><ShieldCheck :size="15" /></span>
            <span class="grow" style="min-width: 0">
              <span class="small strong" style="display: block">{{ session.user_agent || "Local client" }} <span v-if="session.current" class="badge success" style="margin-left: 5px">This device</span></span>
              <span class="small muted">{{ session.ip }} · last seen {{ relativeTime(session.last_seen) }} · expires {{ relativeTime(session.expires_at) }}</span>
            </span>
            <button class="icon-btn" :disabled="session.current" title="Revoke" @click="revokeSession(session.id)"><X :size="14" /></button>
          </div>
          <div v-if="!sessions.length" class="small muted">No sessions found.</div>
        </div>
      </section>
    </div>

    <div v-else-if="tab === 'keys'" class="split">
      <section class="panel">
        <div class="panel-head"><div><h3>API keys</h3><p>Bearer tokens for the CLI, n8n, scripts and external clients.</p></div><KeyRound :size="17" /></div>
        <div class="panel-body stack">
          <div class="input-group"><input v-model="keyName" class="input" placeholder="Key name (for example: n8n automation)" @keydown.enter="createKey" /><button class="btn btn-primary" @click="createKey">Create key</button></div>
          <div class="list">
            <div v-for="key in keys" :key="key.id" class="list-item">
              <span class="file-icon"><WalletCards :size="15" /></span>
              <span class="grow" style="min-width: 0">
                <span class="small strong" style="display: block">{{ key.name }}</span>
                <span class="small muted mono">{{ key.prefix }}… · created {{ relativeTime(key.created_at) }} · {{ key.last_used_at ? `last used ${relativeTime(key.last_used_at)}` : "never used" }}</span>
              </span>
              <button class="btn btn-sm btn-danger" @click="revokeKey(key.id)"><Trash2 :size="12" /> Revoke</button>
            </div>
            <div v-if="!keys.length" class="small muted">No API keys yet.</div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><div><h3>API examples</h3><p>Every service is available through the authenticated gateway.</p></div></div>
        <div class="panel-body stack">
          <CodeBlock label="List jobs" :code="examples.jobs" />
          <CodeBlock label="Generate an image" :code="examples.image" />
          <CodeBlock label="Upload a file" :code="examples.upload" />
        </div>
      </section>
    </div>

    <div v-else-if="tab === 'system'" class="stack">
      <section class="panel">
        <div class="panel-head"><div><h3>Service health</h3><p>All services are private; only the gateway is published.</p></div><span class="chip">{{ status?.online }}/{{ status?.total }}</span></div>
        <div class="panel-body"><ServiceGrid /></div>
      </section>
      <div class="grid grid-2">
        <section class="panel">
          <div class="panel-head"><div><h3>Storage</h3><p>{{ status?.storage?.root }}</p></div></div>
          <div class="panel-body stack">
            <div class="row-between"><span class="muted small">Used</span><span class="strong">{{ formatBytes(status?.storage?.used || 0) }}</span></div>
            <div class="row-between"><span class="muted small">Free</span><span class="strong">{{ status?.storage?.free_label }}</span></div>
            <div class="progress"><span :style="{ width: `${((status?.storage?.used || 0) / (status?.storage?.total || 1)) * 100}%` }" /></div>
            <div class="alert">All images, audio, video, documents and subtitles live under <span class="mono">/data/files</span>. Back up that folder and <span class="mono">/data/state</span>.</div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><div><h3>Compute</h3><p>CPU, memory and accelerator detection.</p></div><Server :size="17" /></div>
          <div class="panel-body stack">
            <div class="row-between"><span class="muted small">CPU</span><span>{{ status?.system?.cpu_count }} threads · {{ status?.system?.cpu_percent }}%</span></div>
            <div class="row-between"><span class="muted small">Memory</span><span>{{ formatBytes(status?.system?.memory_used || 0) }} / {{ formatBytes(status?.system?.memory_total || 0) }}</span></div>
            <div class="row-between"><span class="muted small">GPU</span><span>{{ gpu ? `${gpu.name} · ${gpu.memory_total_mb} MB` : "Not detected — CPU mode" }}</span></div>
            <div class="row-between"><span class="muted small">Files root</span><span class="mono">{{ info?.files_root || "/data/files" }}</span></div>
            <div class="row-between"><span class="muted small">Version</span><span class="mono">{{ info?.version || "1.0.0" }}</span></div>
          </div>
        </section>
      </div>
    </div>

    <div v-else class="stack">
      <ModelsPanel />
      <section class="panel">
        <div class="panel-head"><div><h3>Model downloads (CLI)</h3><p>Equivalent command-line shortcuts for the model packs above.</p></div></div>
        <div class="panel-body grid grid-2">
          <CodeBlock label="All models" code="make models" />
          <CodeBlock label="ACE-Step (music)" code="make models-music" />
          <CodeBlock label="Whisper (subtitles)" code="make models-whisper" />
          <CodeBlock label="Translation + summary" code="make models-text" />
          <CodeBlock label="Piper voices" code="make models-piper" />
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><div><h3>Operations</h3><p>One command launches the complete stack.</p></div></div>
        <div class="panel-body grid grid-2">
          <CodeBlock label="Start everything" code="make up" />
          <CodeBlock label="Start with NVIDIA GPU" code="make up-gpu" />
          <CodeBlock label="Start with Vulkan (AMD/Intel)" code="make up-vulkan" />
          <CodeBlock label="Status and logs" code="make ps\nmake logs" />
          <CodeBlock label="Run the test suite" code="make test" />
          <CodeBlock label="Stop" code="make down" />
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><div><h3>Reconfigure</h3><p>Change providers and storage in <span class="mono">.env</span>, then restart.</p></div></div>
        <div class="panel-body">
          <table class="table">
            <thead><tr><th>Variable</th><th>Purpose</th><th>Default</th></tr></thead>
            <tbody>
              <tr><td class="mono">PORT</td><td>Published frontend port</td><td class="mono">8090</td></tr>
              <tr><td class="mono">INTERNAL_TOKEN</td><td>Shared secret between services</td><td class="mono">generated</td></tr>
              <tr><td class="mono">LLM_BASE_URL</td><td>Ollama / OpenAI-compatible endpoint</td><td class="mono">http://ollama:11434/v1</td></tr>
              <tr><td class="mono">COMFYUI_URL</td><td>External ComfyUI for images</td><td class="mono">http://host.docker.internal:8188</td></tr>
              <tr><td class="mono">MUSIC_CONCURRENCY</td><td>Parallel music workers</td><td class="mono">1</td></tr>
              <tr><td class="mono">VIDEO_CONCURRENCY</td><td>Parallel video pipelines</td><td class="mono">2</td></tr>
              <tr><td class="mono">QVAC_DEVICE</td><td>gpu or cpu for QVAC</td><td class="mono">gpu</td></tr>
              <tr><td class="mono">DATABASE / volumes</td><td>Persistent state</td><td class="mono">./data</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <BaseModal v-model="keyModal" title="Save this API key" subtitle="It will not be shown again." width="narrow">
      <div class="alert success">Copy the key now. Only a hash is stored on the server.</div>
      <div class="input-group" style="margin-top: 10px"><input class="input mono" :value="newKey" readonly /><button class="btn" @click="copy(newKey)"><Copy :size="13" /> Copy</button></div>
      <template #footer><button class="btn btn-primary" @click="keyModal = false">Done</button></template>
    </BaseModal>
  </div>
</template>

<style scoped>
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
