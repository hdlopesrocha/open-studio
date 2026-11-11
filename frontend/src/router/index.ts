import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "@/stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/setup", name: "setup", component: () => import("@/views/AuthView.vue"), props: { mode: "setup" }, meta: { public: true, title: "Set up Open Studio" } },
    { path: "/login", name: "login", component: () => import("@/views/AuthView.vue"), props: { mode: "login" }, meta: { public: true, title: "Sign in" } },
    { path: "/", name: "dashboard", component: () => import("@/views/DashboardView.vue"), meta: { title: "Dashboard" } },
    { path: "/music", name: "music", component: () => import("@/views/MusicView.vue"), meta: { title: "Music Studio" } },
    { path: "/video", name: "video", component: () => import("@/views/VideoView.vue"), meta: { title: "Video Studio" } },
    { path: "/voice", name: "voice", component: () => import("@/views/VoiceView.vue"), meta: { title: "Voice Studio" } },
    { path: "/subtitles", name: "subtitles", component: () => import("@/views/SubtitlesView.vue"), meta: { title: "AI Subtitles" } },
    { path: "/images", name: "images", component: () => import("@/views/ImagesView.vue"), meta: { title: "Picture Studio" } },
    { path: "/documents", name: "documents", component: () => import("@/views/DocumentsView.vue"), meta: { title: "Documents" } },
    { path: "/translate", name: "translate", component: () => import("@/views/TranslateView.vue"), meta: { title: "Translation" } },
    { path: "/summary", name: "summary", component: () => import("@/views/SummaryView.vue"), meta: { title: "Summaries" } },
    { path: "/ffmpeg", name: "ffmpeg", component: () => import("@/views/FFmpegView.vue"), meta: { title: "FFmpeg Workbench" } },
    { path: "/ytdlp", name: "ytdlp", component: () => import("@/views/YtDlpView.vue"), meta: { title: "yt-dlp Downloader" } },
    { path: "/qvac", name: "qvac", component: () => import("@/views/QvacView.vue"), meta: { title: "QVAC Video" } },
    { path: "/files", name: "files", component: () => import("@/views/FilesView.vue"), meta: { title: "Files" } },
    { path: "/jobs", name: "jobs", component: () => import("@/views/JobsView.vue"), meta: { title: "Job Center" } },
    { path: "/settings", name: "settings", component: () => import("@/views/SettingsView.vue"), meta: { title: "Settings" } },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
  scrollBehavior() {
    return { top: 0 };
  },
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (!auth.ready) await auth.load();
  if (auth.setupRequired && to.path !== "/setup") {
    return { path: "/setup", query: { next: to.fullPath } };
  }
  if (!auth.setupRequired && to.path === "/setup") {
    return { path: auth.authenticated ? "/" : "/login" };
  }
  if (!to.meta.public && !auth.authenticated) {
    return { path: "/login", query: { next: to.fullPath } };
  }
  if (auth.authenticated && (to.path === "/login" || to.path === "/setup")) {
    return "/";
  }
  return true;
});

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · Open Studio` : "Open Studio";
});

export default router;
