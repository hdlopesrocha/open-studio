<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from "vue";
import { RouterLink, RouterView, useRouter } from "vue-router";
import {
  Activity,
  Clapperboard,
  DownloadCloud,
  FileText,
  Film,
  FolderOpen,
  Image,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  Mic2,
  Music2,
  Settings2,
  Terminal,
  Wifi,
  WifiOff,
} from "lucide-vue-next";
import { useSystemStore } from "@/stores/system";
import { useJobsStore } from "@/stores/jobs";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";
import ToastHost from "@/components/ToastHost.vue";

const system = useSystemStore();
const jobs = useJobsStore();
const auth = useAuthStore();
const toasts = useToastStore();
const router = useRouter();

const nav = [
  { to: "/", label: "Home", icon: LayoutDashboard },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/music", label: "Audio", icon: Music2 },
  { to: "/video", label: "Video", icon: Clapperboard },
  { to: "/voice", label: "Voice", icon: Mic2 },
  { to: "/images", label: "Images", icon: Image },
  { to: "/documents", label: "Docs", icon: FileText },
  { to: "/ffmpeg", label: "FFmpeg", icon: Terminal },
  { to: "/ytdlp", label: "yt-dlp", icon: DownloadCloud },
  { to: "/files", label: "Files", icon: FolderOpen },
  { to: "/jobs", label: "Jobs", icon: Activity },
  { to: "/settings", label: "Settings", icon: Settings2 },
];

let stopPolling: (() => void) | null = null;

onMounted(() => {
  stopPolling = system.startPolling();
  jobs.refresh();
  jobs.connect();
  window.addEventListener("openstudio:unauthorized", onUnauthorized);
});
onBeforeUnmount(() => {
  stopPolling?.();
  jobs.disconnect();
  window.removeEventListener("openstudio:unauthorized", onUnauthorized);
});

function onUnauthorized() {
  router.push({ path: "/login", query: { next: router.currentRoute.value.fullPath } });
}

const onlineLabel = computed(() => {
  if (!system.status) return "Connecting…";
  return `${system.status.online}/${system.status.total} services`;
});

async function logout() {
  try {
    await auth.logout();
    jobs.disconnect();
    router.push("/login");
  } catch (error: any) {
    toasts.error(error.message);
  }
}
</script>

<template>
  <div class="app-shell">
    <div class="app-main">
      <header class="topbar">
        <RouterLink to="/" class="brand">
          <span class="brand-mark">
            <svg width="19" height="19" viewBox="0 0 64 64" aria-hidden="true">
              <circle cx="32" cy="32" r="17" fill="none" stroke="url(#brandGrad)" stroke-width="4" />
              <circle cx="32" cy="32" r="6" fill="url(#brandGrad)" />
              <defs>
                <linearGradient id="brandGrad" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stop-color="#a78bfa" />
                  <stop offset="0.6" stop-color="#22d3ee" />
                  <stop offset="1" stop-color="#f59e0b" />
                </linearGradient>
              </defs>
            </svg>
          </span>
          <span>
            Open Studio
            <small>Private creative suite</small>
          </span>
        </RouterLink>
        <div class="topbar-spacer" />
        <RouterLink to="/jobs" class="top-status" style="color: inherit">
          <span class="dot" :class="jobs.activeCount ? 'busy' : system.online ? 'online' : 'offline'" />
          <span>{{ jobs.activeCount ? `${jobs.activeCount} job${jobs.activeCount > 1 ? "s" : ""} running` : "All queues idle" }}</span>
        </RouterLink>
        <div class="top-status">
          <Wifi v-if="system.status?.online" :size="13" style="color: var(--success)" />
          <WifiOff v-else :size="13" style="color: var(--danger)" />
          <span>{{ onlineLabel }}</span>
        </div>
        <RouterLink to="/files" class="btn btn-sm btn-ghost"><FolderOpen :size="14" /> Shared files</RouterLink>
      </header>

      <main class="grow">
        <RouterView v-slot="{ Component }">
          <component :is="Component" />
        </RouterView>
      </main>
    </div>

    <aside class="rail">
      <RouterLink to="/" class="rail-brand" aria-label="Open Studio home">
        <svg width="24" height="24" viewBox="0 0 64 64" aria-hidden="true">
          <circle cx="32" cy="32" r="17" fill="none" stroke="url(#railGrad)" stroke-width="4" />
          <circle cx="32" cy="32" r="6" fill="url(#railGrad)" />
          <defs>
            <linearGradient id="railGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stop-color="#a78bfa" />
              <stop offset="0.6" stop-color="#22d3ee" />
              <stop offset="1" stop-color="#f59e0b" />
            </linearGradient>
          </defs>
        </svg>
      </RouterLink>
      <nav class="rail-nav">
        <RouterLink v-for="item in nav" :key="item.to" :to="item.to" class="rail-link">
          <component :is="item.icon" :size="18" :stroke-width="1.8" />
          <span>{{ item.label }}</span>
          <span v-if="item.to === '/jobs' && jobs.activeCount" class="rail-badge">{{ jobs.activeCount }}</span>
        </RouterLink>
      </nav>
      <div class="rail-spacer" />
      <div class="rail-sep" />
      <div class="rail-avatar" :title="auth.identity?.identity?.type || 'Local user'">{{ (auth.identity?.identity?.type || "L").slice(0, 1).toUpperCase() }}</div>
      <button class="rail-link" style="border: none; background: none; margin-top: 4px" title="Sign out" @click="logout">
        <LogOut :size="17" :stroke-width="1.8" />
        <span>Exit</span>
      </button>
    </aside>

    <ToastHost />
  </div>
</template>
