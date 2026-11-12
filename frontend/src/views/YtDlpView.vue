<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  Calendar,
  Captions,
  Check,
  ChevronRight,
  Clock,
  Cookie,
  Download,
  DownloadCloud,
  ExternalLink,
  Eye,
  FileAudio,
  FileImage,
  FileText,
  FileVideo,
  Globe2,
  HardDrive,
  Image as ImageIcon,
  Link2,
  ListChecks,
  ListVideo,
  Loader2,
  Music2,
  Play,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  User,
  Video,
  X,
} from "lucide-vue-next";
import { api, downloadUrl, fileUrl, formatBytes, formatDuration, relativeTime } from "@/lib/api";
import type { Job } from "@/lib/types";
import { DEMO } from "@/lib/types";
import { demoJobs, demoYtInfo } from "@/lib/demo";
import { useJobsStore } from "@/stores/jobs";
import { useSystemStore } from "@/stores/system";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import TabsBar from "@/components/TabsBar.vue";
import FilePicker from "@/components/FilePicker.vue";
import JobCard from "@/components/JobCard.vue";
import AudioPlayer from "@/components/AudioPlayer.vue";
import EmptyState from "@/components/EmptyState.vue";
import CodeBlock from "@/components/CodeBlock.vue";

const jobs = useJobsStore();
const system = useSystemStore();
const toasts = useToastStore();

const tab = ref("download");
const tabs = computed(() => [
  { id: "download", label: "Downloader" },
  { id: "playlist", label: "Playlist", count: DEMO ? demoPlaylist.entries.length : undefined },
  { id: "search", label: "Search" },
]);

const catalog = ref<any>(
  DEMO
    ? {
        version: "2026.10.11",
        yt_dlp: { version: "2026.10.11", available: true },
        extractors: { count: 1842 },
        ffmpeg: "7.0.2",
        formats: [
          { name: "best", selector: "bv*+ba/b" },
          { name: "1080p", selector: "bv*[height<=1080]+ba/b[height<=1080]" },
          { name: "audio", selector: "ba/b" },
        ],
      }
    : null,
);
const catalogLoading = ref(false);
const ytdlpService = computed(() => system.service("ytdlp"));

/* ------------------------------------------------------------------ */
/* Downloader                                                          */
/* ------------------------------------------------------------------ */

const url = ref(DEMO ? demoYtInfo.webpage_url : "");
const info = ref<any>(DEMO ? demoYtInfo : null);
const analyzing = ref(false);
const analyzeError = ref("");

const formatMode = ref<"preset" | "specific" | "custom" | "audio">(DEMO ? "specific" : "preset");
const preset = ref("best");
const selectedFormatId = ref(DEMO ? "137" : "");
const customFormat = ref("bv*[height<=1440]+ba/b");
const presets = [
  { id: "best", label: "Best video + audio", selector: "bv*+ba/b" },
  { id: "bestvideo", label: "Best video only", selector: "bv*" },
  { id: "1080p", label: "Up to 1080p", selector: "bv*[height<=1080]+ba/b[height<=1080]" },
  { id: "720p", label: "Up to 720p", selector: "bv*[height<=720]+ba/b[height<=720]" },
  { id: "mp4", label: "Prefer MP4 / M4A", selector: "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]" },
  { id: "webm", label: "Prefer WebM / Opus", selector: "bv*[ext=webm]+ba[ext=webm]/b[ext=webm]" },
];

const downloadForm = reactive({
  format_sort: "res:1080,codec:h264",
  merge_output_format: "mp4",
  output_template: "%(title).200B [%(id)s].%(ext)s",
  output_path: "ytdlp/downloads",
  subtitleWrite: false,
  subtitleLangs: "en,pt",
  embedSubs: false,
  convertSubs: "",
  writeThumbnail: true,
  embedThumbnail: true,
  writeInfoJson: true,
  writeDescription: true,
  writeComments: false,
  playlist: true,
  playlistItems: "",
  reverse: false,
  maxDownloads: null as number | null,
  matchFilter: "",
  dateafter: "",
  datebefore: "",
  rateLimit: "",
  retries: 10,
  fragmentRetries: 10,
  concurrentFragments: 4,
  proxy: "",
  cookiesPath: "",
  cookiesFromBrowser: "",
  sponsorMark: false,
  sponsorRemove: false,
  archivePath: "ytdlp/archive.txt",
  keepVideo: false,
  noCheckCertificate: false,
  geoBypass: true,
  userAgent: "",
  referer: "",
  headersText: "",
  extractorArgs: "",
  extractAudio: false,
  audioFormat: "mp3",
  audioQuality: "0",
  remux: "",
  recode: "",
  preferFreeFormats: false,
  noPart: false,
  continueDl: true,
  sleepInterval: 0,
  socketTimeout: 20,
  sourceAddress: "",
  timeout: 86400,
});

const cookiePicker = ref(false);
const formatTableOpen = ref(true);

const formats = computed<any[]>(() => (Array.isArray(info.value?.formats) ? info.value.formats : []));
const selectedFormat = computed(() => formats.value.find((format) => format.format_id === selectedFormatId.value) || null);
const formatSelector = computed(() => {
  if (formatMode.value === "preset") {
    return presets.find((item) => item.id === preset.value)?.selector || "bv*+ba/b";
  }
  if (formatMode.value === "audio") return "ba/b";
  if (formatMode.value === "custom") return customFormat.value.trim() || "bv*+ba/b";
  const chosen = selectedFormat.value;
  if (!chosen) return "bv*+ba/b";
  return chosen.acodec && chosen.acodec !== "none" ? String(chosen.format_id) : `${chosen.format_id}+ba/b`;
});
const formatSummary = computed(() => {
  if (formatMode.value === "audio") return `Audio only · ${downloadForm.audioFormat.toUpperCase()}`;
  if (formatMode.value === "specific") return selectedFormat.value ? `${selectedFormat.value.format_id} · ${formatLabel(selectedFormat.value)}` : "Pick a format below";
  if (formatMode.value === "custom") return customFormat.value || "Custom selector";
  return presets.find((item) => item.id === preset.value)?.label || "Best";
});

const activeJobId = ref("");
const demoActiveJob = ref<Job | null>(null);
const demoHistory = ref<Job[]>([]);

const activeJob = computed<Job | null>(() => {
  if (DEMO) return demoActiveJob.value;
  if (activeJobId.value) return jobs.byId(activeJobId.value) || null;
  return jobs.items.find((job) => job.component === "ytdlp" && ["queued", "running", "canceling"].includes(job.status)) || null;
});
const resultData = computed<any>(() => activeJob.value?.result?.data || null);
const resultFiles = computed<any[]>(() => {
  const files = activeJob.value?.result?.files;
  return Array.isArray(files) ? files : [];
});
const resultTitle = computed(() => resultData.value?.title || info.value?.title || activeJob.value?.title || "Download result");
const resultDuration = computed(() => resultData.value?.duration || info.value?.duration || activeJob.value?.params?.duration || null);
const history = computed<Job[]>(() => (DEMO ? demoHistory.value : jobs.items.filter((job) => job.component === "ytdlp").slice(0, 8)));
const activeDownloads = computed(() => {
  if (DEMO) return demoActiveJob.value && ["queued", "running", "canceling"].includes(demoActiveJob.value.status) ? [demoActiveJob.value] : [];
  return jobs.items.filter((job) => job.component === "ytdlp" && ["queued", "running", "canceling"].includes(job.status));
});

onMounted(async () => {
  if (DEMO) {
    demoActiveJob.value = buildDemoJob();
    demoHistory.value = [demoActiveJob.value, ...demoJobs.filter((job) => job.component === "ytdlp").map(cloneJob)];
    return;
  }
  if (!jobs.items.length) jobs.refresh();
  loadCatalog();
});

async function loadCatalog() {
  catalogLoading.value = true;
  try {
    if (DEMO) {
      toasts.info("Demo yt-dlp catalog refreshed");
      return;
    }
    catalog.value = await api.get<any>("/ytdlp/catalog");
  } catch (error: any) {
    toasts.error(error?.message || "Could not load the yt-dlp catalog");
  } finally {
    catalogLoading.value = false;
  }
}

function cloneJob(job: Job): Job {
  return JSON.parse(JSON.stringify(job));
}

function isoAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

function buildDemoJob(): Job {
  const videoPath = "ytdlp/downloads/Field Recording — Lisbon at 4am [dQw4w9WgXcQ].mp4";
  const audioPath = "ytdlp/downloads/Field Recording — Lisbon at 4am [dQw4w9WgXcQ].m4a";
  const files = [
    { path: videoPath, name: "Field Recording — Lisbon at 4am [dQw4w9WgXcQ].mp4", kind: "video", mime: "video/mp4", size: 213_401_600 },
    { path: audioPath, name: "Field Recording — Lisbon at 4am [dQw4w9WgXcQ].m4a", kind: "audio", mime: "audio/mp4", size: 29_401_600 },
    { path: "ytdlp/downloads/Field Recording — Lisbon at 4am [dQw4w9WgXcQ].en.srt", name: "Field Recording — Lisbon at 4am.en.srt", kind: "subtitle", mime: "application/x-subrip", size: 8_420 },
    { path: "ytdlp/downloads/Field Recording — Lisbon at 4am [dQw4w9WgXcQ].info.json", name: "Field Recording — Lisbon at 4am.info.json", kind: "document", mime: "application/json", size: 84_210 },
  ];
  return {
    id: "job_dl_5e1c8a",
    component: "ytdlp",
    action: "download",
    title: "yt-dlp · Field Recording — Lisbon at 4am",
    status: "completed",
    stage: "Complete",
    message: "Downloaded 4 files · 242.9 MB · 01:12",
    progress: 100,
    params: {
      url: demoYtInfo.webpage_url,
      format: "137+ba/b",
      merge_output_format: "mp4",
      output_path: "ytdlp/downloads",
    },
    result: {
      message: "Downloaded Field Recording — Lisbon at 4am (binaural)",
      files,
      data: {
        operation: "download",
        title: demoYtInfo.title,
        duration: demoYtInfo.duration,
        thumbnail: demoYtInfo.thumbnail,
        webpage_url: demoYtInfo.webpage_url,
        uploader: demoYtInfo.uploader,
        extractor: "youtube",
        id: demoYtInfo.id,
        output_dir: "ytdlp/downloads",
        download_seconds: 72.4,
        info_json: files[3].path,
      },
    },
    error: null,
    warnings: [],
    artifacts: files.slice(0, 2).map((file) => ({ ...file })),
    cancel_requested: false,
    attempts: 1,
    created_at: isoAgo(26),
    started_at: isoAgo(26),
    finished_at: isoAgo(25),
    updated_at: isoAgo(25),
  };
}

function mediaUrl(path?: string | null): string {
  if (!path) return "";
  if (/^(https?:|data:|blob:|\/demo\/|\/api\/)/.test(path)) return path;
  return fileUrl(path);
}

function formatLabel(format: any): string {
  if (!format) return "—";
  if (format.resolution && format.resolution !== "audio only") return format.resolution;
  if (format.width && format.height) return `${format.width} × ${format.height}`;
  if (format.acodec && format.acodec !== "none" && (!format.vcodec || format.vcodec === "none")) return "Audio only";
  return format.format_note || format.resolution || format.ext || "—";
}

function formatFps(format: any): string {
  return format?.fps ? `${Math.round(format.fps)} fps` : "—";
}

function formatCodec(format: any): string {
  const video = format?.vcodec && format.vcodec !== "none" ? format.vcodec : "";
  const audio = format?.acodec && format.acodec !== "none" ? format.acodec : "";
  if (video && audio) return `${video} / ${audio}`;
  return video || audio || "—";
}

function formatBitrate(format: any): string {
  const value = format?.tbr || format?.vbr || format?.abr;
  return value ? `${Math.round(value)}k` : "—";
}

function formatSize(format: any): string {
  const size = format?.filesize || format?.filesize_approx;
  return size ? formatBytes(size) : "—";
}

function selectFormat(format: any) {
  selectedFormatId.value = String(format.format_id);
  formatMode.value = "specific";
}

function viewCount(value?: number | null): string {
  if (!value) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M views`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K views`;
  return `${value} views`;
}

function uploadDate(value?: string | null): string {
  if (!value) return "—";
  if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  return value;
}

function appUrl(value?: string | null): string {
  if (!value) return "";
  return value;
}

function setCookiesPath(path: string) {
  downloadForm.cookiesPath = path;
}

function parseHeaders(): Record<string, string> {  const text = downloadForm.headersText.trim();
  if (!text) return {};
  const headers: Record<string, string> = {};
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const index = trimmed.indexOf(":");
    if (index <= 0) throw new Error(`Invalid header line: ${trimmed}`);
    headers[trimmed.slice(0, index).trim()] = trimmed.slice(index + 1).trim();
  }
  return headers;
}

function networkOptions(): Record<string, any> {
  const options: Record<string, any> = {
    proxy: downloadForm.proxy.trim() || undefined,
    cookies_path: downloadForm.cookiesPath.trim() || undefined,
    cookies_from_browser: downloadForm.cookiesFromBrowser.trim() || undefined,
    user_agent: downloadForm.userAgent.trim() || undefined,
    referer: downloadForm.referer.trim() || undefined,
    no_check_certificate: downloadForm.noCheckCertificate,
    geo_bypass: downloadForm.geoBypass,
    retries: downloadForm.retries,
    fragment_retries: downloadForm.fragmentRetries,
    concurrent_fragments: downloadForm.concurrentFragments,
    rate_limit: downloadForm.rateLimit.trim() || undefined,
    socket_timeout: downloadForm.socketTimeout,
  };
  const headers = parseHeaders();
  if (Object.keys(headers).length) options.headers = headers;
  if (downloadForm.extractorArgs.trim()) options.extractor_args = [downloadForm.extractorArgs.trim()];
  return Object.fromEntries(Object.entries(options).filter(([, value]) => value !== undefined && value !== ""));
}

async function analyze() {
  const target = url.value.trim();
  if (!target) {
    toasts.error("Paste a media URL first.");
    return;
  }
  analyzing.value = true;
  analyzeError.value = "";
  try {
    if (DEMO) {
      await new Promise((resolve) => window.setTimeout(resolve, 350));
      info.value = demoYtInfo;
      selectedFormatId.value = "137";
      formatMode.value = "preset";
      toasts.success("Demo metadata loaded");
      return;
    }
    info.value = await api.post<any>("/ytdlp/info", { url: target, ...networkOptions() });
    const firstVideo = (info.value?.formats || []).find((format: any) => format.vcodec && format.vcodec !== "none" && format.filesize);
    if (firstVideo) selectedFormatId.value = String(firstVideo.format_id);
    toasts.success(`Found ${info.value?.formats?.length || 0} formats`);
  } catch (error: any) {
    analyzeError.value = error?.message || "Analysis failed";
    toasts.error(analyzeError.value);
  } finally {
    analyzing.value = false;
  }
}

function selectedPlaylistItems(): string {
  if (!downloadForm.playlistItems.trim()) return "";
  const parts = downloadForm.playlistItems.split(",").map((part) => part.trim()).filter(Boolean);
  return downloadForm.reverse ? parts.reverse().join(",") : parts.join(",");
}

function buildDownloadParams(overrides: Record<string, any> = {}): Record<string, any> {
  const sponsorblock: any = downloadForm.sponsorMark ? "all" : false;
  const sponsorblockRemove: any = downloadForm.sponsorRemove ? "sponsor" : false;
  return {
    url: overrides.url || url.value.trim(),
    format: formatSelector.value,
    format_sort: downloadForm.format_sort.trim() || undefined,
    merge_output_format: downloadForm.merge_output_format,
    output_template: downloadForm.output_template.trim() || undefined,
    output_path: downloadForm.output_path.trim() || "ytdlp/downloads",
    subtitles: downloadForm.subtitleWrite,
    subtitle_langs: downloadForm.subtitleLangs.trim() || undefined,
    embed_subs: downloadForm.embedSubs,
    convert_subs: downloadForm.convertSubs || undefined,
    write_subs: downloadForm.subtitleWrite,
    write_thumbnail: downloadForm.writeThumbnail,
    embed_thumbnail: downloadForm.embedThumbnail,
    write_info_json: downloadForm.writeInfoJson,
    write_description: downloadForm.writeDescription,
    write_comments: downloadForm.writeComments,
    extract_audio: downloadForm.extractAudio || formatMode.value === "audio",
    audio_format: downloadForm.audioFormat,
    audio_quality: downloadForm.audioQuality,
    playlist: downloadForm.playlist,
    playlist_items: selectedPlaylistItems() || undefined,
    max_downloads: downloadForm.maxDownloads || undefined,
    match_filter: downloadForm.matchFilter.trim() || undefined,
    dateafter: downloadForm.dateafter.trim() || undefined,
    datebefore: downloadForm.datebefore.trim() || undefined,
    sponsorblock,
    sponsorblock_remove: sponsorblockRemove,
    archive_path: downloadForm.archivePath.trim() || undefined,
    keep_video: downloadForm.keepVideo,
    no_check_certificate: downloadForm.noCheckCertificate,
    geo_bypass: downloadForm.geoBypass,
    user_agent: downloadForm.userAgent.trim() || undefined,
    referer: downloadForm.referer.trim() || undefined,
    remux: downloadForm.remux || undefined,
    recode: downloadForm.recode || undefined,
    prefer_free_formats: downloadForm.preferFreeFormats,
    no_part: downloadForm.noPart,
    continue_dl: downloadForm.continueDl,
    sleep_interval: downloadForm.sleepInterval || undefined,
    max_sleep_interval: downloadForm.sleepInterval ? Math.max(downloadForm.sleepInterval, downloadForm.sleepInterval * 2) : undefined,
    socket_timeout: downloadForm.socketTimeout,
    source_address: downloadForm.sourceAddress.trim() || undefined,
    timeout: downloadForm.timeout,
    ...networkOptions(),
    ...overrides,
  };
}

function validateConfig() {
  try {
    buildDownloadParams();
    toasts.success("Configuration valid — headers and network options parsed");
  } catch (error: any) {
    toasts.error(error?.message || "Configuration is not valid");
  }
}

async function submitDownload(overrides: Record<string, any> = {}, titleOverride?: string) {  const target = overrides.url || url.value.trim();
  if (!target) {
    toasts.error("Paste a media URL first.");
    return;
  }
  try {
    let params: Record<string, any>;
    try {
      params = buildDownloadParams(overrides);
    } catch (error: any) {
      toasts.error(error.message);
      return;
    }
    const title = titleOverride || `yt-dlp · ${info.value?.title || target}`;
    if (DEMO) {
      const job = cloneJob(buildDemoJob());
      job.id = `job_dl_${Date.now().toString(36)}`;
      job.title = title;
      job.params = params;
      job.message = "Demo download completed from the yt-dlp container.";
      job.created_at = isoAgo(0);
      job.started_at = isoAgo(0);
      job.finished_at = new Date().toISOString();
      demoActiveJob.value = job;
      demoHistory.value = [job, ...demoHistory.value.filter((item) => item.id !== job.id)];
      await new Promise((resolve) => window.setTimeout(resolve, 400));
      toasts.success("yt-dlp demo download completed");
      return;
    }
    const job = await api.post<Job>("/ytdlp/download", { ...params, title });
    jobs.upsert(job);
    activeJobId.value = job.id;
    toasts.success("Download queued");
  } catch (error: any) {
    toasts.error(error?.message || "Could not start the download");
  }
}

async function cancelJob(id: string) {
  if (DEMO) {
    if (demoActiveJob.value?.id === id) demoActiveJob.value = { ...demoActiveJob.value, status: "canceled", message: "Cancelled by the user." };
    toasts.info("Demo download cancelled");
    return;
  }
  try {
    await jobs.cancel(id);
    toasts.info("Cancellation requested");
  } catch (error: any) {
    toasts.error(error?.message || "Could not cancel the job");
  }
}

async function retryJob(id: string) {
  if (DEMO) {
    const found = demoHistory.value.find((entry) => entry.id === id);
    if (found) demoActiveJob.value = { ...cloneJob(found), status: "running", progress: 24, message: "Re-queued in demo mode." };
    toasts.info("Demo download restarted");
    return;
  }
  try {
    const job = await jobs.retry(id);
    activeJobId.value = job.id;
    toasts.success("Download restarted");
  } catch (error: any) {
    toasts.error(error?.message || "Could not retry the download");
  }
}

async function removeJob(id: string) {
  if (DEMO) {
    demoHistory.value = demoHistory.value.filter((entry) => entry.id !== id);
    if (demoActiveJob.value?.id === id) demoActiveJob.value = null;
    toasts.success("Demo download removed");
    return;
  }
  try {
    await jobs.remove(id);
    if (activeJobId.value === id) activeJobId.value = "";
    toasts.success("Download record removed");
  } catch (error: any) {
    toasts.error(error?.message || "Could not remove the download");
  }
}

/* ------------------------------------------------------------------ */
/* Playlist                                                             */
/* ------------------------------------------------------------------ */

const demoPlaylist = {
  id: "PLfieldnotes",
  title: "Field Notes · Iberia — night recordings",
  uploader: "Open Studio Field Notes",
  entry_count: 6,
  entries: [
    { index: 1, id: "dQw4w9WgXcQ", title: "Field Recording — Lisbon at 4am (binaural)", uploader: "Open Studio Field Notes", duration: 1842, thumbnail: "/demo/art-08.png", webpage_url: demoYtInfo.webpage_url },
    { index: 2, id: "fn002", title: "Tram 28 — interior, rain on glass", uploader: "Open Studio Field Notes", duration: 1268, thumbnail: "/demo/art-04.png", webpage_url: "https://www.youtube.com/watch?v=fn002" },
    { index: 3, id: "fn003", title: "Alfama rooftops — distant fado, 3am", uploader: "Open Studio Field Notes", duration: 2214, thumbnail: "/demo/art-06.png", webpage_url: "https://www.youtube.com/watch?v=fn003" },
    { index: 4, id: "fn004", title: "Under the 25 de Abril bridge — wind and cables", uploader: "Open Studio Field Notes", duration: 1560, thumbnail: "/demo/art-02.png", webpage_url: "https://www.youtube.com/watch?v=fn004" },
    { index: 5, id: "fn005", title: "Cais do Sodré — last train, station reverb", uploader: "Open Studio Field Notes", duration: 1985, thumbnail: "/demo/art-05.png", webpage_url: "https://www.youtube.com/watch?v=fn005" },
    { index: 6, id: "fn006", title: "Cascais coastline — Atlantic at dawn", uploader: "Open Studio Field Notes", duration: 2742, thumbnail: "/demo/art-01.png", webpage_url: "https://www.youtube.com/watch?v=fn006" },
  ],
};

const playlistUrl = ref(DEMO ? "https://www.youtube.com/playlist?list=PLfieldnotes" : "");
const playlistInfo = ref<any>(DEMO ? demoPlaylist : null);
const playlistEntries = computed<any[]>(() => (Array.isArray(playlistInfo.value?.entries) ? playlistInfo.value.entries : []));
const playlistLoading = ref(false);
const playlistLimit = ref(25);
const selectedEntries = ref<Set<number>>(new Set(DEMO ? [1, 2, 3] : []));

async function analyzePlaylist() {
  const target = playlistUrl.value.trim();
  if (!target) {
    toasts.error("Paste a playlist URL first.");
    return;
  }
  playlistLoading.value = true;
  try {
    if (DEMO) {
      await new Promise((resolve) => window.setTimeout(resolve, 350));
      playlistInfo.value = demoPlaylist;
      selectedEntries.value = new Set([1, 2, 3]);
      toasts.success("Demo playlist loaded");
      return;
    }
    playlistInfo.value = await api.post<any>("/ytdlp/playlist", { url: target, limit: playlistLimit.value, flat_playlist: true, ...networkOptions() });
    selectedEntries.value = new Set();
    toasts.success(`Found ${playlistInfo.value?.entries?.length || 0} entries`);
  } catch (error: any) {
    toasts.error(error?.message || "Could not read the playlist");
  } finally {
    playlistLoading.value = false;
  }
}

function toggleEntry(item: any, index = 0) {
  const next = new Set(selectedEntries.value);
  const key = playlistIndex(item, index);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  selectedEntries.value = next;
}

function playlistIndex(item: any, index = 0): number {
  const value = Number(item?.index);
  return Number.isFinite(value) && value > 0 ? value : index + 1;
}

function selectAllEntries() {
  if (selectedEntries.value.size === playlistEntries.value.length) {
    selectedEntries.value = new Set();
  } else {
    selectedEntries.value = new Set(playlistEntries.value.map((entry, index) => playlistIndex(entry, index)));
  }
}

function downloadPlaylistSelection() {
  if (!selectedEntries.value.size) {
    toasts.error("Select at least one playlist entry.");
    return;
  }
  const items = [...selectedEntries.value].sort((a, b) => a - b).join(",");
  submitDownload(
    {
      url: playlistUrl.value.trim(),
      playlist: true,
      playlist_items: items,
      title: `yt-dlp · ${playlistInfo.value?.title || "Playlist"} · ${selectedEntries.value.size} items`,
    },
    `yt-dlp · ${playlistInfo.value?.title || "Playlist"} · ${selectedEntries.value.size} items`,
  );
}

/* ------------------------------------------------------------------ */
/* Search                                                               */
/* ------------------------------------------------------------------ */

const demoSearchResults = [
  { id: "sr01", title: "Field Recording — Lisbon at 4am (binaural)", uploader: "Open Studio Field Notes", duration: 1842, view_count: 182034, thumbnail: "/demo/art-08.png", webpage_url: demoYtInfo.webpage_url, extractor: "youtube" },
  { id: "sr02", title: "Nocturno — analog synth improvisation, one take", uploader: "Helena Rocha", duration: 946, view_count: 94310, thumbnail: "/demo/art-03.png", webpage_url: "https://www.youtube.com/watch?v=sr02", extractor: "youtube" },
  { id: "sr03", title: "Rain on a Lisbon tram — 60 minutes ambience", uploader: "Open Studio Field Notes", duration: 3600, view_count: 512880, thumbnail: "/demo/art-04.png", webpage_url: "https://www.youtube.com/watch?v=sr03", extractor: "youtube" },
  { id: "sr04", title: "How to build a local-first creative studio", uploader: "Open Studio", duration: 2142, view_count: 28410, thumbnail: "/demo/art-07.png", webpage_url: "https://www.youtube.com/watch?v=sr04", extractor: "youtube" },
  { id: "sr05", title: "Atravessar a Noite — official music video", uploader: "Helena Rocha", duration: 287, view_count: 1204000, thumbnail: "/demo/art-02.png", webpage_url: "https://www.youtube.com/watch?v=sr05", extractor: "youtube" },
  { id: "sr06", title: "Binaural microphone comparison — six mics, one room", uploader: "Field Notes Lab", duration: 1634, view_count: 76120, thumbnail: "/demo/art-06.png", webpage_url: "https://www.youtube.com/watch?v=sr06", extractor: "youtube" },
];

const searchQuery = ref("Lisbon field recording binaural");
const searchLimit = ref(12);
const searchResults = ref<any[]>(DEMO ? demoSearchResults : []);
const searching = ref(false);

async function search() {
  if (!searchQuery.value.trim()) {
    toasts.error("Enter a search query.");
    return;
  }
  searching.value = true;
  try {
    if (DEMO) {
      await new Promise((resolve) => window.setTimeout(resolve, 350));
      searchResults.value = demoSearchResults;
      toasts.success("Demo search results loaded");
      return;
    }
    const data = await api.post<any>("/ytdlp/search", { query: searchQuery.value.trim(), limit: searchLimit.value, ...networkOptions() });
    searchResults.value = Array.isArray(data.items) ? data.items : [];
    toasts.success(`${searchResults.value.length} results`);
  } catch (error: any) {
    toasts.error(error?.message || "Search failed");
  } finally {
    searching.value = false;
  }
}

function downloadSearchResult(item: any) {
  submitDownload({ url: item.webpage_url || item.url }, `yt-dlp · ${item.title || "Search result"}`);
}

function formatKind(file: any): string {
  return file?.kind || "file";
}

function kindIcon(file: any) {
  if (file?.kind === "audio") return FileAudio;
  if (file?.kind === "video") return FileVideo;
  if (file?.kind === "image") return FileImage;
  return FileText;
}

const extractorCount = computed(() => catalog.value?.extractors?.count || 1842);
const ytVersion = computed(() => catalog.value?.yt_dlp?.version || catalog.value?.version || "2026.10.11");
import ServiceNotice from "@/components/ServiceNotice.vue";
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="Extractor · downloader · playlist · search"
      title="yt-dlp"
      subtitle="Pull media from every extractor yt-dlp supports inside its own Docker image. Analyze formats, choose streams, write subtitles, thumbnails and metadata, then send downloads to the shared job queue and file tree."
    >
      <template #actions>
        <span class="chip" :class="ytdlpService?.online ? 'success' : ''">
          <span class="dot" :class="ytdlpService?.online ? 'online' : 'busy'" />
          {{ ytdlpService?.online ? "yt-dlp online" : "yt-dlp worker" }}
        </span>
        <span class="chip"><DownloadCloud :size="11" /> {{ extractorCount.toLocaleString() }} extractors</span>
        <span class="chip"><Sparkles :size="11" /> v{{ ytVersion }}</span>
        <button class="btn btn-sm" :disabled="catalogLoading" @click="loadCatalog"><RefreshCw :size="13" :class="{ spin: catalogLoading }" /> Catalog</button>
      </template>
    </PageHeader>

    <ServiceNotice
      :services="[{ name: 'ytdlp', label: 'yt-dlp' }]"
      title="This workspace needs yt-dlp"
    />

    <div class="row-between" style="margin-bottom: 14px; flex-wrap: wrap; gap: 10px">
      <TabsBar v-model="tab" :tabs="tabs" />
      <div class="row" style="gap: 7px">
        <span class="chip" :class="activeDownloads.length ? 'warn' : ''">{{ activeDownloads.length }} active downloads</span>
        <span class="chip">FFmpeg {{ catalog?.ffmpeg || "7.0.2" }}</span>
        <span class="chip">Cookies · SponsorBlock · archive</span>
      </div>
    </div>

    <!-- ------------------------------------------------------------ -->
    <!-- Downloader tab                                                -->
    <!-- ------------------------------------------------------------ -->
    <div v-if="tab === 'download'" class="stack">
      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>Analyze a URL</h3>
            <p>Metadata, thumbnails, uploader details and every available format.</p>
          </div>
          <span class="chip"><Link2 :size="11" /> Extract first, download second</span>
        </div>
        <div class="panel-body stack">
          <div class="url-row">
            <div class="input-group grow">
              <Search :size="15" class="muted" />
              <input v-model="url" class="input" placeholder="https://www.youtube.com/watch?v=…" @keydown.enter="analyze" />
            </div>
            <button class="btn btn-primary" :disabled="analyzing" @click="analyze">
              <Loader2 v-if="analyzing" :size="14" class="spin" />
              <Sparkles v-else :size="14" />
              {{ analyzing ? "Analyzing…" : "Analyze" }}
            </button>
          </div>
          <div v-if="analyzeError" class="alert error">{{ analyzeError }}</div>

          <template v-if="info">
            <div class="media-summary">
              <div class="media-thumb">
                <img :src="mediaUrl(info.thumbnail_path || info.thumbnail)" alt="" />
                <span class="media-badge">{{ info.extractor || "youtube" }}</span>
              </div>
              <div class="media-copy">
                <div class="row" style="gap: 6px">
                  <span class="chip success"><Check :size="10" /> analyzed</span>
                  <span class="chip">{{ info.id }}</span>
                  <span v-if="info.upload_date" class="chip"><Calendar :size="10" /> {{ uploadDate(info.upload_date) }}</span>
                </div>
                <h3 style="font-size: 20px; margin-top: 8px">{{ info.title }}</h3>
                <div class="row" style="gap: 12px; margin-top: 7px">
                  <span class="row small muted" style="gap: 5px"><User :size="12" /> {{ info.uploader || info.channel || "Unknown uploader" }}</span>
                  <span class="row small muted" style="gap: 5px"><Clock :size="12" /> {{ formatDuration(info.duration) }}</span>
                  <span class="row small muted" style="gap: 5px"><Eye :size="12" /> {{ viewCount(info.view_count) }}</span>
                  <a v-if="info.webpage_url" class="small" :href="info.webpage_url" target="_blank" rel="noopener"><ExternalLink :size="11" style="vertical-align: -2px" /> source</a>
                </div>
                <p v-if="info.description" class="media-description">{{ info.description }}</p>
              </div>
              <div class="media-stats">
                <div><span>Formats</span><strong>{{ formats.length }}</strong></div>
                <div><span>Duration</span><strong>{{ formatDuration(info.duration) }}</strong></div>
                <div><span>Views</span><strong>{{ viewCount(info.view_count).replace(" views", "") }}</strong></div>
              </div>
            </div>

            <div class="row-between">
              <div class="row" style="gap: 7px">
                <span class="label"><ListVideo :size="12" /> Available formats</span>
                <span class="chip">{{ formats.length }}</span>
              </div>
              <button class="btn btn-sm btn-ghost" @click="formatTableOpen = !formatTableOpen">{{ formatTableOpen ? "Hide" : "Show" }} formats <ChevronRight :size="12" :style="{ transform: formatTableOpen ? 'rotate(90deg)' : '' }" /></button>
            </div>
            <div v-if="formatTableOpen" class="format-scroll">
              <table class="table format-table">
                <thead>
                  <tr><th style="width: 34px"></th><th>ID</th><th>Container</th><th>Resolution</th><th>FPS</th><th>Codecs</th><th>Size</th><th>Bitrate</th><th>Note</th></tr>
                </thead>
                <tbody>
                  <tr v-for="format in formats" :key="format.format_id" :class="{ selected: selectedFormatId === String(format.format_id) && formatMode === 'specific' }" @click="selectFormat(format)">
                    <td><span class="radio-dot" :class="{ on: selectedFormatId === String(format.format_id) && formatMode === 'specific' }" /></td>
                    <td class="mono strong">{{ format.format_id }}</td>
                    <td class="mono">{{ format.ext }}</td>
                    <td>{{ formatLabel(format) }}</td>
                    <td>{{ formatFps(format) }}</td>
                    <td class="mono small">{{ formatCodec(format) }}</td>
                    <td class="nowrap">{{ formatSize(format) }}</td>
                    <td class="mono">{{ formatBitrate(format) }}</td>
                    <td class="small muted truncate" style="max-width: 180px">{{ format.format_note || (format.acodec === 'none' ? 'video only' : '') || "—" }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
          <EmptyState v-else :icon="DownloadCloud" title="No URL analyzed" message="Paste a video, track or playlist URL and analyze it to see every stream yt-dlp can extract before you download anything." />
        </div>
      </section>

      <div class="split split-wide">
        <section class="panel">
          <div class="panel-head">
            <div><h3>Download options</h3><p>Every extractor, postprocessor and network control exposed by the service contract.</p></div>
            <span class="chip">{{ formatSummary }}</span>
          </div>
          <div class="panel-body stack">
            <div>
              <div class="label" style="margin-bottom: 7px">Format selection</div>
              <div class="segmented">
                <button class="seg" :class="{ active: formatMode === 'preset' }" @click="formatMode = 'preset'">Preset</button>
                <button class="seg" :class="{ active: formatMode === 'specific' }" @click="formatMode = 'specific'">Format ID</button>
                <button class="seg" :class="{ active: formatMode === 'custom' }" @click="formatMode = 'custom'">Custom</button>
                <button class="seg" :class="{ active: formatMode === 'audio' }" @click="formatMode = 'audio'">Audio only</button>
              </div>
            </div>
            <div class="form-grid">
              <div class="field" v-if="formatMode === 'preset'">
                <label>Preset</label>
                <select v-model="preset" class="select"><option v-for="item in presets" :key="item.id" :value="item.id">{{ item.label }}</option></select>
                <span class="hint mono">{{ formatSelector }}</span>
              </div>
              <div class="field" v-else-if="formatMode === 'specific'">
                <label>Selected format</label>
                <select v-model="selectedFormatId" class="select"><option value="" disabled>Choose a format below</option><option v-for="format in formats" :key="format.format_id" :value="String(format.format_id)">{{ format.format_id }} · {{ formatLabel(format) }} · {{ format.ext }}</option></select>
                <span class="hint">Video-only formats are paired with the best audio automatically.</span>
              </div>
              <div class="field" v-else-if="formatMode === 'custom'">
                <label>Custom format selector</label>
                <input v-model="customFormat" class="input mono" placeholder="bv*[height<=1440]+ba/b" />
                <span class="hint">Raw yt-dlp selector: filters, brackets and fallbacks are supported.</span>
              </div>
              <div class="field" v-else>
                <label>Audio format</label>
                <select v-model="downloadForm.audioFormat" class="select"><option v-for="format in ['mp3', 'wav', 'flac', 'aac', 'opus', 'vorbis', 'm4a', 'best']" :key="format">{{ format }}</option></select>
                <span class="hint">Audio-only extraction with FFmpeg postprocessing.</span>
              </div>
              <div class="field"><label>Format sort</label><input v-model="downloadForm.format_sort" class="input mono" placeholder="res:1080,codec:h264" /></div>
              <div class="field"><label>Merge output</label><select v-model="downloadForm.merge_output_format" class="select"><option>mp4</option><option>mkv</option><option>webm</option></select></div>
              <div class="field"><label>Output template</label><input v-model="downloadForm.output_template" class="input mono" /></div>
              <div class="field"><label>Output folder</label><input v-model="downloadForm.output_path" class="input mono" placeholder="ytdlp/downloads" /></div>
              <div class="field"><label>Audio quality</label><input v-model="downloadForm.audioQuality" class="input" placeholder="0 = best" /></div>
              <div class="field"><label>Max downloads</label><input v-model.number="downloadForm.maxDownloads" type="number" min="1" class="input" placeholder="No limit" /></div>
            </div>

            <div class="option-block">
              <div class="option-title"><Captions :size="13" /> Subtitles</div>
              <div class="form-grid cols-3">
                <div class="field"><label>Write subtitles</label><button class="switch" :class="{ on: downloadForm.subtitleWrite }" style="align-self: flex-start" @click="downloadForm.subtitleWrite = !downloadForm.subtitleWrite" /></div>
                <div class="field"><label>Languages</label><input v-model="downloadForm.subtitleLangs" class="input" placeholder="en,pt,es" /></div>
                <div class="field"><label>Convert to</label><select v-model="downloadForm.convertSubs" class="select"><option value="">Keep original</option><option>srt</option><option>vtt</option><option>ass</option><option>lrc</option></select></div>
              </div>
              <div class="switch-row"><div><div class="switch-label">Embed subtitles</div><div class="switch-hint">Mux subtitle tracks into the downloaded media.</div></div><button class="switch" :class="{ on: downloadForm.embedSubs }" @click="downloadForm.embedSubs = !downloadForm.embedSubs" /></div>
            </div>

            <div class="option-block">
              <div class="option-title"><ImageIcon :size="13" /> Thumbnail & metadata</div>
              <div class="switch-grid">
                <div class="switch-row"><div><div class="switch-label">Write thumbnail</div><div class="switch-hint">Save cover art as a separate image.</div></div><button class="switch" :class="{ on: downloadForm.writeThumbnail }" @click="downloadForm.writeThumbnail = !downloadForm.writeThumbnail" /></div>
                <div class="switch-row"><div><div class="switch-label">Embed thumbnail</div><div class="switch-hint">Attach cover art inside the media file.</div></div><button class="switch" :class="{ on: downloadForm.embedThumbnail }" @click="downloadForm.embedThumbnail = !downloadForm.embedThumbnail" /></div>
                <div class="switch-row"><div><div class="switch-label">Info JSON</div><div class="switch-hint">Full extractor metadata sidecar.</div></div><button class="switch" :class="{ on: downloadForm.writeInfoJson }" @click="downloadForm.writeInfoJson = !downloadForm.writeInfoJson" /></div>
                <div class="switch-row"><div><div class="switch-label">Description</div><div class="switch-hint">Write the description to a text file.</div></div><button class="switch" :class="{ on: downloadForm.writeDescription }" @click="downloadForm.writeDescription = !downloadForm.writeDescription" /></div>
                <div class="switch-row"><div><div class="switch-label">Comments</div><div class="switch-hint">Store comments when the extractor provides them.</div></div><button class="switch" :class="{ on: downloadForm.writeComments }" @click="downloadForm.writeComments = !downloadForm.writeComments" /></div>
                <div class="switch-row"><div><div class="switch-label">Keep original video</div><div class="switch-hint">Keep the pre-postprocessing source.</div></div><button class="switch" :class="{ on: downloadForm.keepVideo }" @click="downloadForm.keepVideo = !downloadForm.keepVideo" /></div>
              </div>
            </div>

            <div class="option-block">
              <div class="option-title"><ListChecks :size="13" /> Playlist & filters</div>
              <div class="form-grid cols-3">
                <div class="field"><label>Playlist</label><button class="switch" :class="{ on: downloadForm.playlist }" style="align-self: flex-start" @click="downloadForm.playlist = !downloadForm.playlist" /></div>
                <div class="field"><label>Items</label><input v-model="downloadForm.playlistItems" class="input mono" placeholder="1-5,8" /></div>
                <div class="field"><label>Max downloads</label><input v-model.number="downloadForm.maxDownloads" type="number" min="1" class="input" placeholder="No limit" /></div>
                <div class="field"><label>Date after</label><input v-model="downloadForm.dateafter" class="input" placeholder="20260101" /></div>
                <div class="field"><label>Date before</label><input v-model="downloadForm.datebefore" class="input" placeholder="20261231" /></div>
                <div class="field"><label>Match filter</label><input v-model="downloadForm.matchFilter" class="input mono" placeholder="duration > 120" /></div>
              </div>
              <div class="switch-row"><div><div class="switch-label">Reverse selected items</div><div class="switch-hint">Reverse the explicit playlist item list before downloading.</div></div><button class="switch" :class="{ on: downloadForm.reverse }" @click="downloadForm.reverse = !downloadForm.reverse" /></div>
            </div>

            <div class="option-block">
              <div class="option-title"><Globe2 :size="13" /> Network, cookies & safety</div>
              <div class="form-grid cols-3">
                <div class="field"><label>Rate limit</label><input v-model="downloadForm.rateLimit" class="input" placeholder="2M" /></div>
                <div class="field"><label>Retries</label><input v-model.number="downloadForm.retries" type="number" min="0" max="100" class="input" /></div>
                <div class="field"><label>Fragment retries</label><input v-model.number="downloadForm.fragmentRetries" type="number" min="0" max="100" class="input" /></div>
                <div class="field"><label>Concurrent fragments</label><input v-model.number="downloadForm.concurrentFragments" type="number" min="1" max="32" class="input" /></div>
                <div class="field"><label>Proxy</label><input v-model="downloadForm.proxy" class="input mono" placeholder="socks5://127.0.0.1:1080" /></div>
                <div class="field"><label>Cookies from browser</label><input v-model="downloadForm.cookiesFromBrowser" class="input" placeholder="chrome or firefox:profile" /></div>
                <div class="field">
                  <label>Cookies file</label>
                  <div class="input-group">
                    <input v-model="downloadForm.cookiesPath" class="input mono" placeholder="uploads/cookies.txt" />
                    <button class="btn btn-sm" @click="cookiePicker = true">Browse</button>
                  </div>
                </div>
                <div class="field"><label>User agent</label><input v-model="downloadForm.userAgent" class="input" placeholder="Default yt-dlp UA" /></div>
                <div class="field"><label>Referer</label><input v-model="downloadForm.referer" class="input" placeholder="https://example.com" /></div>
                <div class="field"><label>Extractor args</label><input v-model="downloadForm.extractorArgs" class="input mono" placeholder="youtube:player_client=web" /></div>
              </div>
              <div class="field" style="margin-top: 9px"><label>Extra headers <span class="muted small">one per line</span></label><textarea v-model="downloadForm.headersText" class="textarea mono" style="min-height: 56px" placeholder="Accept-Language: en-US,en;q=0.9" spellcheck="false" /></div>
              <div class="switch-grid">
                <div class="switch-row"><div><div class="switch-label">No certificate check</div><div class="switch-hint">Disable TLS verification for broken extractors.</div></div><button class="switch" :class="{ on: downloadForm.noCheckCertificate }" @click="downloadForm.noCheckCertificate = !downloadForm.noCheckCertificate" /></div>
                <div class="switch-row"><div><div class="switch-label">Geo bypass</div><div class="switch-hint">Try to bypass regional restrictions.</div></div><button class="switch" :class="{ on: downloadForm.geoBypass }" @click="downloadForm.geoBypass = !downloadForm.geoBypass" /></div>
                <div class="switch-row"><div><div class="switch-label">Prefer free formats</div><div class="switch-hint">Prefer WebM/Opus when quality is equal.</div></div><button class="switch" :class="{ on: downloadForm.preferFreeFormats }" @click="downloadForm.preferFreeFormats = !downloadForm.preferFreeFormats" /></div>
                <div class="switch-row"><div><div class="switch-label">Continue partial files</div><div class="switch-hint">Resume interrupted downloads.</div></div><button class="switch" :class="{ on: downloadForm.continueDl }" @click="downloadForm.continueDl = !downloadForm.continueDl" /></div>
              </div>
            </div>

            <div class="option-block">
              <div class="option-title"><Settings2 :size="13" /> Postprocessing & advanced</div>
              <div class="form-grid cols-3">
                <div class="field"><label>SponsorBlock mark</label><button class="switch" :class="{ on: downloadForm.sponsorMark }" style="align-self: flex-start" @click="downloadForm.sponsorMark = !downloadForm.sponsorMark" /></div>
                <div class="field"><label>SponsorBlock remove</label><button class="switch" :class="{ on: downloadForm.sponsorRemove }" style="align-self: flex-start" @click="downloadForm.sponsorRemove = !downloadForm.sponsorRemove" /></div>
                <div class="field"><label>Archive path</label><input v-model="downloadForm.archivePath" class="input mono" placeholder="ytdlp/archive.txt" /></div>
                <div class="field"><label>Remux to</label><select v-model="downloadForm.remux" class="select"><option value="">Never</option><option>mp4</option><option>mkv</option><option>webm</option></select></div>
                <div class="field"><label>Re-encode to</label><select v-model="downloadForm.recode" class="select"><option value="">Never</option><option>mp4</option><option>mkv</option><option>webm</option></select></div>
                <div class="field"><label>Sleep interval</label><input v-model.number="downloadForm.sleepInterval" type="number" min="0" step="0.5" class="input" /></div>
                <div class="field"><label>Socket timeout</label><input v-model.number="downloadForm.socketTimeout" type="number" min="1" class="input" /></div>
                <div class="field"><label>Source address</label><input v-model="downloadForm.sourceAddress" class="input mono" placeholder="192.168.1.10" /></div>
                <div class="field"><label>Job timeout</label><input v-model.number="downloadForm.timeout" type="number" min="1" class="input" /></div>
              </div>
              <div class="switch-grid">
                <div class="switch-row"><div><div class="switch-label">Extract audio</div><div class="switch-hint">Force audio-only postprocessing.</div></div><button class="switch" :class="{ on: downloadForm.extractAudio }" @click="downloadForm.extractAudio = !downloadForm.extractAudio" /></div>
                <div class="switch-row"><div><div class="switch-label">No .part files</div><div class="switch-hint">Write directly to the final file name.</div></div><button class="switch" :class="{ on: downloadForm.noPart }" @click="downloadForm.noPart = !downloadForm.noPart" /></div>
              </div>
            </div>

            <div class="row-between" style="flex-wrap: wrap; gap: 9px">
              <div class="row" style="gap: 7px">
                <span class="chip">{{ formatSummary }}</span>
                <span class="chip">{{ downloadForm.merge_output_format.toUpperCase() }}</span>
                <span class="chip" v-if="downloadForm.subtitleWrite">{{ downloadForm.subtitleLangs || "all" }} subs</span>
              </div>
              <div class="row">
                <button class="btn" @click="validateConfig"><ShieldCheck :size="14" /> Validate</button>
                <button class="btn btn-primary btn-lg" @click="submitDownload()"><Download :size="16" /> Download</button>
              </div>
            </div>
          </div>
        </section>

        <aside class="stack">
          <section class="panel">
            <div class="panel-head"><div><h3>Download status</h3><p>{{ activeJob ? activeJob.title : "Nothing queued" }}</p></div><span class="badge" :class="activeJob?.status || 'queued'">{{ activeJob?.status || "idle" }}</span></div>
            <div class="panel-body stack">
              <JobCard v-if="activeJob" :job="activeJob" @cancel="cancelJob" @retry="retryJob" @remove="removeJob" />
              <div v-else class="empty" style="padding: 22px"><DownloadCloud :size="26" style="opacity: .45; margin-bottom: 7px" /><h3>Ready when you are</h3><p>Analyze a URL, choose a format and start a job. Progress streams live from yt-dlp and FFmpeg.</p></div>
              <div v-if="activeDownloads.length" class="alert success">{{ activeDownloads.length }} download worker(s) busy. The global queue keeps other components running in parallel.</div>
            </div>
          </section>

          <section class="panel" v-if="activeJob?.result">
            <div class="panel-head"><div><h3>Result</h3><p>{{ resultTitle }}</p></div><span class="chip success">complete</span></div>
            <div class="panel-body stack">
              <div class="result-meta">
                <img v-if="resultData?.thumbnail_path || resultData?.thumbnail || info?.thumbnail_path || info?.thumbnail" :src="mediaUrl(resultData?.thumbnail_path || resultData?.thumbnail || info?.thumbnail_path || info?.thumbnail)" alt="" class="result-thumb" />
                <div class="grow" style="min-width: 0">
                  <div class="small strong">{{ resultTitle }}</div>
                  <div class="small muted">{{ resultData?.uploader || info?.uploader || "yt-dlp" }} · {{ formatDuration(resultDuration) }}</div>
                  <div class="row small muted" style="gap: 8px; margin-top: 5px">
                    <span>{{ resultData?.extractor || "youtube" }}</span>
                    <span v-if="resultData?.download_seconds">{{ Math.round(resultData.download_seconds) }}s</span>
                    <span v-if="resultData?.entry_count">{{ resultData.entry_count }} entries</span>
                  </div>
                </div>
                <a v-if="resultData?.webpage_url" class="icon-btn" :href="resultData.webpage_url" target="_blank" rel="noopener"><ExternalLink :size="14" /></a>
              </div>
              <div class="stack" style="gap: 8px">
                <div v-for="file in resultFiles" :key="file.path" class="result-file">
                  <div class="row-between" style="margin-bottom: 5px">
                    <div class="row" style="gap: 7px; min-width: 0">
                      <component :is="kindIcon(file)" :size="14" />
                      <span class="small strong truncate">{{ file.name || file.path.split('/').pop() }}</span>
                      <span class="badge">{{ formatKind(file) }}</span>
                    </div>
                    <div class="row" style="gap: 6px">
                      <span class="small muted">{{ formatBytes(file.size || 0) }}</span>
                      <a class="icon-btn" :href="downloadUrl(file.path)" title="Download"><Download :size="14" /></a>
                    </div>
                  </div>
                  <AudioPlayer v-if="file.kind === 'audio'" :src="file.path" :title="file.name" :download-path="file.path" compact />
                  <video v-else-if="file.kind === 'video' && !DEMO" :src="fileUrl(file.path)" controls preload="metadata" class="result-video" />
                  <div v-else-if="file.kind === 'video'" class="video-poster">
                    <img :src="mediaUrl(resultData?.thumbnail || info?.thumbnail)" alt="" />
                    <span class="play-chip"><Play :size="16" /> video ready</span>
                  </div>
                  <img v-else-if="file.kind === 'image'" :src="mediaUrl(file.path)" alt="" class="result-image" />
                </div>
              </div>
              <div v-if="resultData?.info_json" class="alert">Metadata sidecar: <span class="mono">{{ resultData.info_json }}</span></div>
            </div>
          </section>

          <section class="panel">
            <div class="panel-head"><div><h3>Recent downloads</h3><p>ytdlp component only</p></div><span class="chip">{{ history.length }}</span></div>
            <div class="panel-body" style="padding: 8px">
              <div v-for="job in history" :key="job.id" class="history-row">
                <span class="dot" :class="job.status === 'completed' ? 'online' : job.status === 'failed' ? 'offline' : job.status === 'running' ? 'busy' : ''" />
                <span class="grow" style="min-width: 0">
                  <span class="small strong truncate" style="display: block">{{ job.title }}</span>
                  <span class="small muted truncate" style="display: block">{{ job.message || job.action }} · {{ relativeTime(job.created_at) }}</span>
                </span>
                <span class="badge" :class="job.status">{{ job.status }}</span>
              </div>
              <div v-if="!history.length" class="small muted" style="padding: 10px">No yt-dlp jobs yet.</div>
            </div>
          </section>
        </aside>
      </div>
    </div>

    <!-- ------------------------------------------------------------ -->
    <!-- Playlist tab                                                  -->
    <!-- ------------------------------------------------------------ -->
    <div v-else-if="tab === 'playlist'" class="split split-wide">
      <section class="panel">
        <div class="panel-head">
          <div><h3>Playlist analyzer</h3><p>List entries, select the ones you need and download them as a single job.</p></div>
          <span class="chip"><ListVideo :size="11" /> flat playlist</span>
        </div>
        <div class="panel-body stack">
          <div class="url-row">
            <div class="input-group grow"><Link2 :size="14" class="muted" /><input v-model="playlistUrl" class="input" placeholder="https://www.youtube.com/playlist?list=…" @keydown.enter="analyzePlaylist" /></div>
            <input v-model.number="playlistLimit" type="number" min="1" max="500" class="input" style="width: 86px" title="Entry limit" />
            <button class="btn btn-primary" :disabled="playlistLoading" @click="analyzePlaylist"><Loader2 v-if="playlistLoading" :size="14" class="spin" /><ListVideo v-else :size="14" /> Analyze</button>
          </div>
          <template v-if="playlistInfo">
            <div class="row-between">
              <div>
                <div style="font-family: var(--display); font-size: 17px; font-weight: 700">{{ playlistInfo.title || "Playlist" }}</div>
                <div class="small muted">{{ playlistInfo.uploader || "Unknown uploader" }} · {{ playlistInfo.entry_count || playlistEntries.length }} entries</div>
              </div>
              <div class="row" style="gap: 6px">
                <button class="btn btn-sm" @click="selectAllEntries">{{ selectedEntries.size === playlistEntries.length ? "Clear" : "Select all" }}</button>
                <span class="chip active">{{ selectedEntries.size }} selected</span>
              </div>
            </div>
            <div class="playlist-list">
              <div v-for="(entry, entryIndex) in playlistEntries" :key="entry.index || entry.id" class="playlist-row" :class="{ selected: selectedEntries.has(playlistIndex(entry, entryIndex)) }" @click="toggleEntry(entry, entryIndex)">
                <span class="check-box" :class="{ on: selectedEntries.has(playlistIndex(entry, entryIndex)) }"><Check v-if="selectedEntries.has(playlistIndex(entry, entryIndex))" :size="11" /></span>
                <img :src="mediaUrl(entry.thumbnail)" alt="" class="playlist-thumb" />
                <span class="grow" style="min-width: 0">
                  <span class="small strong truncate" style="display: block">{{ entry.title }}</span>
                  <span class="small muted truncate" style="display: block">{{ entry.uploader || playlistInfo.uploader }} · {{ formatDuration(entry.duration) }}</span>
                </span>
                <span class="chip">{{ entryIndex + 1 }}</span>
                <a v-if="entry.webpage_url" class="icon-btn" :href="entry.webpage_url" target="_blank" rel="noopener" @click.stop><ExternalLink :size="13" /></a>
              </div>
            </div>
            <div class="row-between" style="flex-wrap: wrap; gap: 8px">
              <span class="small muted">{{ selectedEntries.size }} of {{ playlistEntries.length }} entries selected · playlist items {{ [...selectedEntries].sort((a, b) => a - b).join(",") || "—" }}</span>
              <button class="btn btn-primary" :disabled="!selectedEntries.size" @click="downloadPlaylistSelection"><Download :size="14" /> Download selected</button>
            </div>
          </template>
          <EmptyState v-else :icon="ListVideo" title="No playlist analyzed" message="Paste a playlist URL, analyze it, then tick the entries you want. Playlist items are passed to yt-dlp as a range, so one job downloads the whole selection." />
        </div>
      </section>

      <aside class="stack">
        <section class="panel">
          <div class="panel-head"><div><h3>Playlist download</h3><p>Job progress</p></div><span class="badge" :class="activeJob?.status || 'queued'">{{ activeJob?.status || "idle" }}</span></div>
          <div class="panel-body stack">
            <JobCard v-if="activeJob" :job="activeJob" @cancel="cancelJob" @retry="retryJob" @remove="removeJob" />
            <div v-else class="small muted">Selected entries will appear here as a queued download.</div>
            <div class="alert">Playlist jobs honour the same format, subtitle and postprocessing options as the Downloader tab.</div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><div><h3>Recent downloads</h3><p>Shared queue</p></div><span class="chip">{{ history.length }}</span></div>
          <div class="panel-body" style="padding: 8px">
            <div v-for="job in history" :key="job.id" class="history-row">
              <span class="dot" :class="job.status === 'completed' ? 'online' : job.status === 'failed' ? 'offline' : ''" />
              <span class="grow" style="min-width: 0"><span class="small strong truncate" style="display: block">{{ job.title }}</span><span class="small muted">{{ relativeTime(job.created_at) }}</span></span>
              <span class="badge" :class="job.status">{{ job.status }}</span>
            </div>
          </div>
        </section>
      </aside>
    </div>

    <!-- ------------------------------------------------------------ -->
    <!-- Search tab                                                    -->
    <!-- ------------------------------------------------------------ -->
    <div v-else class="split split-wide">
      <section class="panel">
        <div class="panel-head">
          <div><h3>Search extractors</h3><p>Search yt-dlp's extractor index and download any result without leaving the page.</p></div>
          <span class="chip"><Search :size="11" /> ytsearch</span>
        </div>
        <div class="panel-body stack">
          <div class="url-row">
            <div class="input-group grow"><Search :size="15" class="muted" /><input v-model="searchQuery" class="input" placeholder="Search videos, tracks, channels…" @keydown.enter="search" /></div>
            <input v-model.number="searchLimit" type="number" min="1" max="100" class="input" style="width: 86px" title="Result limit" />
            <button class="btn btn-primary" :disabled="searching" @click="search"><Loader2 v-if="searching" :size="14" class="spin" /><Search v-else :size="14" /> Search</button>
          </div>
          <div v-if="searchResults.length" class="search-grid">
            <article v-for="item in searchResults" :key="item.id || item.webpage_url" class="search-card">
              <div class="search-thumb">
                <img :src="mediaUrl(item.thumbnail)" alt="" />
                <span class="duration-badge">{{ formatDuration(item.duration) }}</span>
              </div>
              <div class="search-body">
                <div class="small strong search-title">{{ item.title }}</div>
                <div class="small muted truncate">{{ item.uploader || item.channel || "Unknown" }}</div>
                <div class="row-between small muted" style="margin-top: 3px">
                  <span class="row" style="gap: 4px"><Eye :size="11" /> {{ viewCount(item.view_count).replace(" views", "") }}</span>
                  <span class="badge">{{ item.extractor || "youtube" }}</span>
                </div>
                <div class="row" style="gap: 6px; margin-top: 8px">
                  <a v-if="item.webpage_url" class="btn btn-sm btn-ghost" :href="item.webpage_url" target="_blank" rel="noopener"><ExternalLink :size="12" /> Open</a>
                  <button class="btn btn-sm" style="margin-left: auto" @click="downloadSearchResult(item)"><Download :size="12" /> Download</button>
                </div>
              </div>
            </article>
          </div>
          <EmptyState v-else :icon="Search" title="Search the extractor index" message="Type a query to search YouTube and the other extractors yt-dlp supports. Results include thumbnails, durations and direct download actions." />
        </div>
      </section>

      <aside class="stack">
        <section class="panel">
          <div class="panel-head"><div><h3>Search download</h3><p>Job progress</p></div><span class="badge" :class="activeJob?.status || 'queued'">{{ activeJob?.status || "idle" }}</span></div>
          <div class="panel-body stack">
            <JobCard v-if="activeJob" :job="activeJob" @cancel="cancelJob" @retry="retryJob" @remove="removeJob" />
            <div v-else class="small muted">Pick a search result to download it with the current options.</div>
            <div v-if="resultFiles.length" class="stack" style="gap: 6px">
              <div v-for="file in resultFiles" :key="`search-${file.path}`" class="result-file">
                <component :is="kindIcon(file)" :size="14" />
                <span class="small strong truncate grow">{{ file.name || file.path.split('/').pop() }}</span>
                <a class="icon-btn" :href="downloadUrl(file.path)"><Download :size="13" /></a>
              </div>
            </div>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><div><h3>Catalog</h3><p>Extractor runtime</p></div><span class="chip">{{ extractorCount.toLocaleString() }}</span></div>
          <div class="panel-body stack" style="gap: 8px">
            <div class="row-between small"><span class="muted">yt-dlp</span><span class="mono">{{ ytVersion }}</span></div>
            <div class="row-between small"><span class="muted">FFmpeg</span><span class="mono">{{ catalog?.ffmpeg || "7.0.2" }}</span></div>
            <div class="row-between small"><span class="muted">Cookie sources</span><span>file · browser</span></div>
            <div class="row-between small"><span class="muted">Postprocessors</span><span>10</span></div>
            <div class="tag-list">
              <span class="chip">SponsorBlock</span><span class="chip">Embed subs</span><span class="chip">Remux</span><span class="chip">Archive</span>
            </div>
          </div>
        </section>
      </aside>
    </div>

    <FilePicker v-model="cookiePicker" kind="document" start-path="uploads" title="Choose a Netscape cookies.txt file" @selected="setCookiesPath" />
  </div>
</template>

<style scoped>
.url-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.media-summary {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr) 130px;
  gap: 15px;
  align-items: start;
}
.media-thumb {
  position: relative;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--line);
  background: #080a0f;
}
.media-thumb img {
  width: 100%;
  height: 146px;
  object-fit: cover;
  display: block;
}
.media-badge {
  position: absolute;
  left: 8px;
  bottom: 8px;
  padding: 3px 7px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.72);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}
.media-copy { min-width: 0; }
.media-description {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
  margin-top: 9px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.media-stats {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.media-stats > div {
  border: 1px solid var(--line);
  border-radius: 9px;
  padding: 8px 10px;
  background: rgba(8, 10, 15, 0.3);
}
.media-stats span { display: block; font-size: 9px; text-transform: uppercase; letter-spacing: 0.09em; color: var(--muted-2); }
.media-stats strong { display: block; font-family: var(--display); font-size: 15px; margin-top: 2px; }
.format-scroll { max-height: 330px; overflow: auto; border: 1px solid var(--line); border-radius: 10px; }
.format-table { min-width: 760px; }
.format-table tbody tr { cursor: pointer; }
.format-table tr.selected td { background: rgba(139, 92, 246, 0.09); }
.radio-dot {
  display: inline-block;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1px solid var(--line-strong);
  background: rgba(8, 10, 15, 0.6);
}
.radio-dot.on {
  border: 4px solid var(--accent);
  background: white;
  box-shadow: 0 0 8px rgba(139, 92, 246, 0.55);
}
.segmented {
  display: inline-flex;
  gap: 3px;
  padding: 3px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: rgba(8, 10, 15, 0.4);
}
.seg {
  border: none;
  background: transparent;
  color: var(--muted);
  padding: 7px 12px;
  border-radius: 7px;
  font-size: 11.5px;
  font-weight: 600;
}
.seg:hover { color: var(--text); }
.seg.active { background: var(--panel-3); color: var(--text); }
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.form-grid.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.option-block {
  border: 1px solid var(--line);
  border-radius: 11px;
  padding: 11px 12px;
  background: rgba(8, 10, 15, 0.22);
}
.option-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--muted);
  margin-bottom: 9px;
}
.switch-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}
.result-meta {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px;
  background: rgba(8, 10, 15, 0.3);
}
.result-thumb {
  width: 78px;
  height: 48px;
  object-fit: cover;
  border-radius: 7px;
  border: 1px solid var(--line);
  flex: none;
}
.result-file {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px 10px;
  background: rgba(8, 10, 15, 0.26);
}
.result-video { width: 100%; border-radius: 8px; background: #000; margin-top: 6px; }
.result-image { width: 100%; border-radius: 8px; margin-top: 6px; border: 1px solid var(--line); }
.video-poster {
  position: relative;
  border-radius: 8px;
  overflow: hidden;
  margin-top: 6px;
  border: 1px solid var(--line);
}
.video-poster img { width: 100%; height: 120px; object-fit: cover; display: block; opacity: 0.8; }
.play-chip {
  position: absolute;
  left: 9px;
  bottom: 9px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(0, 0, 0, 0.72);
  border-radius: 999px;
  padding: 5px 9px;
  font-size: 10px;
  font-weight: 700;
}
.history-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-radius: 9px;
}
.history-row:hover { background: rgba(255, 255, 255, 0.035); }
.playlist-list {
  display: flex;
  flex-direction: column;
  max-height: 470px;
  overflow-y: auto;
  border: 1px solid var(--line);
  border-radius: 10px;
}
.playlist-row {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7px 9px;
  border-bottom: 1px solid rgba(35, 42, 58, 0.55);
  cursor: pointer;
}
.playlist-row:last-child { border-bottom: none; }
.playlist-row:hover { background: rgba(255, 255, 255, 0.025); }
.playlist-row.selected { background: rgba(139, 92, 246, 0.07); }
.playlist-thumb {
  width: 66px;
  height: 40px;
  border-radius: 6px;
  object-fit: cover;
  border: 1px solid var(--line);
  flex: none;
}
.check-box {
  width: 17px;
  height: 17px;
  border-radius: 5px;
  border: 1px solid var(--line-strong);
  display: grid;
  place-items: center;
  flex: none;
  color: white;
}
.check-box.on { background: var(--accent); border-color: var(--accent); }
.search-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(225px, 1fr));
  gap: 11px;
}
.search-card {
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
  background: var(--panel);
  transition: 160ms ease;
}
.search-card:hover { border-color: var(--line-strong); transform: translateY(-2px); }
.search-thumb { position: relative; }
.search-thumb img { width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; background: #080a0f; }
.duration-badge {
  position: absolute;
  right: 6px;
  bottom: 6px;
  padding: 2px 5px;
  border-radius: 5px;
  background: rgba(0, 0, 0, 0.76);
  font-family: var(--mono);
  font-size: 9.5px;
}
.search-body { padding: 9px 10px; }
.search-title {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 30px;
}
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1250px) {
  .media-summary { grid-template-columns: 210px minmax(0, 1fr); }
  .media-stats { grid-column: 1 / -1; flex-direction: row; }
  .media-stats > div { flex: 1; }
  .form-grid.cols-3 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 780px) {
  .url-row { flex-direction: column; align-items: stretch; }
  .media-summary { grid-template-columns: 1fr; }
  .form-grid, .form-grid.cols-3, .switch-grid { grid-template-columns: 1fr; }
}
</style>
