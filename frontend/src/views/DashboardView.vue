<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import {
  Activity,
  ArrowRight,
  Captions,
  Clapperboard,
  Cpu,
  Disc3,
  DownloadCloud,
  FileText,
  FolderOpen,
  HardDrive,
  Image,
  Mic2,
  Music2,
  Sparkles,
  Terminal,
  Zap,
} from "lucide-vue-next";
import { useSystemStore } from "@/stores/system";
import { useJobsStore } from "@/stores/jobs";
import { DEMO, demoStatus } from "@/lib/demo";
import { api, formatBytes, relativeTime } from "@/lib/api";
import PageHeader from "@/components/PageHeader.vue";
import ServiceGrid from "@/components/ServiceGrid.vue";
import EmptyState from "@/components/EmptyState.vue";
import JobCard from "@/components/JobCard.vue";

const system = useSystemStore();
const jobs = useJobsStore();
const kinds = ref<Record<string, { files: number; size: number; size_label: string }>>({});

onMounted(async () => {
  system.load(true);
  if (DEMO) {
    kinds.value = {
      music: { files: 48, size: 1.84 * 1024 ** 3, size_label: "1.8 GB" },
      dj: { files: 22, size: 936 * 1024 ** 2, size_label: "936 MB" },
      video: { files: 64, size: 12.4 * 1024 ** 3, size_label: "12.4 GB" },
      voice: { files: 31, size: 684 * 1024 ** 2, size_label: "684 MB" },
      images: { files: 122, size: 412 * 1024 ** 2, size_label: "412 MB" },
      documents: { files: 19, size: 224 * 1024 ** 2, size_label: "224 MB" },
      subtitles: { files: 12, size: 4 * 1024 ** 2, size_label: "4 MB" },
    };
    return;
  }
  try {
    const data = await api.get<{ kinds: Record<string, any> }>("/files/kinds");
    kinds.value = data.kinds;
  } catch {}
});

const status = computed(() => system.status || (DEMO ? demoStatus : null));
const recentJobs = computed(() => jobs.recent.slice(0, 3));
const quick = [
  { to: "/music", label: "Compose a song", detail: "ACE-Step 1.5 · lyrics · repaint", icon: Music2, tone: "violet" },
  { to: "/dj", label: "Build a DJ set", detail: "Analyse · style models · mix scenes", icon: Disc3, tone: "cyan" },
  { to: "/video", label: "Make a music video", detail: "Scenes · animation · subtitles", icon: Clapperboard, tone: "cyan" },
  { to: "/voice", label: "Clone a voice", detail: "OmniVoice · Piper · 646 languages", icon: Mic2, tone: "amber" },
  { to: "/subtitles", label: "Align lyrics to SRT", detail: "Whisper · DP alignment · VTT", icon: Captions, tone: "green" },
  { to: "/images", label: "Generate artwork", detail: "Diffusers · ComfyUI · QVAC", icon: Image, tone: "pink" },
  { to: "/ffmpeg", label: "Process media", detail: "Trim · crop · concat · transcode", icon: Terminal, tone: "slate" },
  { to: "/ytdlp", label: "Download a source", detail: "yt-dlp · playlists · subtitles", icon: DownloadCloud, tone: "blue" },
  { to: "/documents", label: "Translate a document", detail: "PDF · OCR · summary · narration", icon: FileText, tone: "orange" },
];
const kindEntries = computed(() => Object.entries(kinds.value).sort((a, b) => b[1].size - a[1].size));
const totalFiles = computed(() => kindEntries.value.reduce((sum, [, value]) => sum + value.files, 0));

function shortSize(bytes: number) {
  return formatBytes(bytes);
}
</script>

<template>
  <div class="page">
    <section class="hero" style="margin-bottom: 20px">
      <div class="hero-grid">
        <div>
          <div class="eyebrow"><Sparkles :size="13" /> Local-first · password protected</div>
          <h1>One private studio for sound, picture and words.</h1>
          <p>
            Music, video, voice, subtitles, images, documents and media tools share one storage tree and one global job
            system. Every model runs on your machine, every API is behind your password, and every service can see the
            files produced by the others.
          </p>
          <div class="hero-actions">
            <RouterLink to="/music" class="btn btn-primary btn-lg"><Music2 :size="16" /> Start creating</RouterLink>
            <RouterLink to="/jobs" class="btn btn-lg"><Activity :size="16" /> Open job center</RouterLink>
            <RouterLink to="/files" class="btn btn-lg btn-ghost"><FolderOpen :size="16" /> Browse shared files</RouterLink>
          </div>
        </div>
        <div class="hero-visual">
          <div class="hero-tile"><span>Services online</span><strong>{{ status?.online ?? "—" }}/{{ status?.total ?? "—" }}</strong></div>
          <div class="hero-tile"><span>Active jobs</span><strong>{{ jobs.activeCount }}</strong></div>
          <div class="hero-tile"><span>Workers</span><strong>{{ status?.queues?.components?.length ?? 13 }}</strong></div>
          <div class="hero-tile"><span>Files</span><strong>{{ totalFiles || 296 }}</strong></div>
          <div class="hero-tile"><span>Free disk</span><strong style="font-size: 15px">{{ status?.storage?.free_label || "—" }}</strong></div>
          <div class="hero-tile"><span>GPU</span><strong style="font-size: 15px">{{ status?.system?.gpu?.length ? status.system.gpu[0].name : "CPU mode" }}</strong></div>
        </div>
      </div>
    </section>

    <div class="stat-grid" style="margin-bottom: 18px">
      <div class="stat">
        <div class="stat-label">Job engine</div>
        <div class="stat-value">{{ jobs.activeCount }} active</div>
        <div class="stat-sub">{{ jobs.total }} jobs tracked · per-component queues</div>
      </div>
      <div class="stat">
        <div class="stat-label">Shared storage</div>
        <div class="stat-value">{{ status?.storage?.free_label || "—" }}</div>
        <div class="stat-sub">{{ totalFiles || 296 }} files · {{ status?.storage?.root || "/data/files" }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Compute</div>
        <div class="stat-value">{{ status?.system?.cpu_percent ?? 0 }}%</div>
        <div class="stat-sub">{{ status?.system?.cpu_count ?? 16 }} threads · {{ status?.system?.memory_percent ?? 0 }}% memory</div>
      </div>
      <div class="stat">
        <div class="stat-label">Protection</div>
        <div class="stat-value" style="font-size: 19px">Password + keys</div>
        <div class="stat-sub">Scrypt · HttpOnly sessions · API keys</div>
      </div>
    </div>

    <div class="grid" style="grid-template-columns: minmax(0, 1.55fr) minmax(0, 1fr); margin-bottom: 18px">
      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Quick start</h3>
            <p>Every sub-page uses the same layout, controls and job feedback.</p>
          </div>
          <RouterLink to="/settings" class="btn btn-sm btn-ghost">Configure</RouterLink>
        </div>
        <div class="panel-body">
          <div class="grid grid-4" style="gap: 9px">
            <RouterLink v-for="item in quick" :key="item.to" :to="item.to" class="tool-btn" style="display: flex; gap: 10px; align-items: flex-start; min-height: 82px">
              <span class="file-icon" style="width: 30px; height: 30px; flex: none"><component :is="item.icon" :size="15" /></span>
              <span>
                <span class="strong" style="display: block; font-size: 11.5px">{{ item.label }}</span>
                <span class="small muted" style="display: block; font-size: 10px; line-height: 1.4; margin-top: 3px">{{ item.detail }}</span>
              </span>
            </RouterLink>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Storage</h3>
            <p>All services write into the same folder.</p>
          </div>
          <span class="chip">{{ totalFiles || 296 }} files</span>
        </div>
        <div class="panel-body stack" style="gap: 11px">
          <div v-for="[kind, value] in kindEntries" :key="kind" class="stack" style="gap: 5px">
            <div class="row-between small">
              <span class="strong" style="text-transform: capitalize">{{ kind }}</span>
              <span class="muted">{{ value.size_label }} · {{ value.files }}</span>
            </div>
            <div class="progress thin"><span :style="{ width: `${Math.min(100, (value.size / (status?.storage?.used || 1)) * 100 * 8)}%` }" /></div>
          </div>
          <div v-if="!kindEntries.length" class="small muted">No files indexed yet.</div>
          <RouterLink to="/files" class="btn btn-sm btn-block" style="margin-top: 4px"><HardDrive :size="13" /> Open file explorer</RouterLink>
        </div>
      </section>
    </div>

    <div class="grid" style="grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr)">
      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Recent activity</h3>
            <p>Cross-component jobs run in parallel.</p>
          </div>
          <RouterLink to="/jobs" class="btn btn-sm">All jobs <ArrowRight :size="12" /></RouterLink>
        </div>
        <div class="panel-body stack">
          <JobCard v-for="job in recentJobs" :key="job.id" :job="job" compact @cancel="jobs.cancel($event)" @retry="jobs.retry($event)" @remove="jobs.remove($event)" />
          <EmptyState v-if="!recentJobs.length" :icon="Activity" title="No jobs yet" message="Start a generation from any studio page. Every job appears here with live progress." />
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Service health</h3>
            <p>{{ status?.online ?? 0 }} of {{ status?.total ?? 0 }} services responding.</p>
          </div>
          <RouterLink to="/settings" class="icon-btn"><Cpu :size="15" /></RouterLink>
        </div>
        <div class="panel-body">
          <ServiceGrid />
          <div class="alert" style="margin-top: 14px">
            <Zap :size="13" style="vertical-align: -2px; color: var(--warning)" />
            Models download on first use. Run <span class="kbd">make models</span> to pre-fetch every model, or let each page warm up its engine.
          </div>
        </div>
      </section>
    </div>

    <div class="row" style="margin-top: 18px; gap: 8px">
      <RouterLink to="/voice" class="chip"><Mic2 :size="11" /> Voice</RouterLink>
      <RouterLink to="/translate" class="chip">Translate</RouterLink>
      <RouterLink to="/summary" class="chip">Summary</RouterLink>
      <RouterLink to="/qvac" class="chip"><Sparkles :size="11" /> QVAC video</RouterLink>
      <span class="chip" style="margin-left: auto">v{{ status?.app?.version || "1.0.0" }} · up {{ Math.floor((status?.app?.uptime_seconds || 0) / 3600) }}h</span>
    </div>
  </div>
</template>
