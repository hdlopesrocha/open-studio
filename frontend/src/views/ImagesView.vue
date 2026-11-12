<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import {
  Aperture,
  ArrowRight,
  Check,
  ChevronRight,
  Crop,
  Download,
  Expand,
  ExternalLink,
  Images,
  Layers,
  Loader2,
  Maximize2,
  RefreshCw,
  Search,
  Shuffle,
  SlidersHorizontal,
  Sparkles,
  Upload,
  Wand2,
  X,
  Zap,
} from "lucide-vue-next";
import type { Job } from "@/lib/types";
import { DEMO } from "@/lib/types";
import { demoGallery, demoImagePaths } from "@/lib/demo";
import { api, downloadUrl, fileUrl, formatBytes, formatDuration, relativeTime } from "@/lib/api";
import { useJobsStore } from "@/stores/jobs";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import BaseModal from "@/components/BaseModal.vue";
import FilePicker from "@/components/FilePicker.vue";
import JobCard from "@/components/JobCard.vue";
import EmptyState from "@/components/EmptyState.vue";
import TabsBar from "@/components/TabsBar.vue";

const jobs = useJobsStore();
const toasts = useToastStore();

const DEMO_PROVIDERS = [
  {
    id: "diffusers",
    name: "Diffusers",
    available: true,
    detail: "2 local checkpoints · CUDA · float16",
    models: [
      { id: "black-forest-labs/FLUX.1-dev", name: "FLUX.1 dev", detail: "12B rectified flow · 28 steps", downloaded: true },
      { id: "stabilityai/stable-diffusion-xl-base-1.0", name: "SDXL Base 1.0", detail: "Dual text encoders · 30 steps", downloaded: true },
      { id: "stable-diffusion-v1-5/stable-diffusion-v1-5", name: "Stable Diffusion 1.5", detail: "Fast 512px classic", downloaded: true },
    ],
  },
  {
    id: "procedural",
    name: "Procedural",
    available: true,
    detail: "Always available · deterministic Pillow artwork",
    models: [
      { id: "cinematic", name: "Cinematic", detail: "Anamorphic light and grain" },
      { id: "editorial", name: "Editorial", detail: "Bold type and paper texture" },
      { id: "botanical", name: "Botanical", detail: "Organic line work and pigment" },
      { id: "noir", name: "Noir", detail: "High contrast monochrome" },
    ],
  },
  {
    id: "comfyui",
    name: "ComfyUI",
    available: true,
    detail: "Workflow server · 2 checkpoints found",
    models: [
      { id: "juggernautXL_v9.safetensors", name: "Juggernaut XL v9", detail: "Photoreal SDXL checkpoint" },
      { id: "dreamshaperXL_v21TurboDPMSDE.safetensors", name: "DreamShaper XL Turbo", detail: "Fast 4-step checkpoint" },
    ],
  },
  {
    id: "qvac",
    name: "QVAC",
    available: true,
    detail: "Vulkan · stable-diffusion.cpp",
    models: [{ id: "qvac:default", name: "QVAC image model", detail: "Loads on demand from the QVAC worker" }],
  },
];

const SAMPLERS = ["euler", "euler_a", "dpm++_2m", "dpm++_sde", "ddim", "lcm", "unipc"];
const SCHEDULERS = ["karras", "normal", "exponential", "sgm_uniform", "simple"];

const sizePresets = [
  { id: "square", label: "Square", width: 1024, height: 1024, hint: "1:1" },
  { id: "portrait", label: "Portrait", width: 832, height: 1216, hint: "2:3" },
  { id: "landscape", label: "Landscape", width: 1216, height: 832, hint: "3:2" },
  { id: "wide", label: "Wide", width: 1536, height: 864, hint: "16:9" },
  { id: "story", label: "Story", width: 1080, height: 1920, hint: "9:16" },
  { id: "hd", label: "HD", width: 1920, height: 1080, hint: "16:9" },
];

const promptIdeas = [
  "Porcelain city at dusk, cinematic, violet haze",
  "A lone figure crossing a flooded avenue, neon reflections",
  "Analog synthesizer cathedral, warm dust and light",
  "Botanical instrument, macro photography",
  "Brutalist listening room, amber light",
  "Night train window, motion blur, teal",
];

const tab = ref("generate");
const providers = ref<any[]>(DEMO ? DEMO_PROVIDERS : DEMO_PROVIDERS);
const modelCatalog = ref<any[]>(
  DEMO
    ? DEMO_PROVIDERS.flatMap((provider) => (provider.models || []).map((model) => ({ ...model, provider: provider.id })))
    : [],
);
const gallery = ref<any[]>(
  DEMO
    ? demoGallery.map((item, index) => ({
        ...item,
        model: ["FLUX.1 dev", "Procedural · cinematic", "DreamShaper XL Turbo"][index % 3],
        thumbnail_path: item.path,
        title: ["Porcelain city", "Flooded avenue", "Synth cathedral", "Ocean cliff", "Botanical instrument", "Brutalist room", "Night train", "Desert radio"][index] || "",
      }))
    : [],
);
const galleryQuery = ref("");
const galleryProvider = ref("all");
const galleryLoading = ref(false);
const galleryOpen = ref(false);
const galleryItem = ref<any>(null);

const form = reactive({
  provider: "diffusers",
  model: "black-forest-labs/FLUX.1-dev",
  prompt: DEMO ? "Porcelain city at dusk, cinematic, violet haze, wet asphalt, anamorphic light" : "",
  negative_prompt: "low quality, text, watermark, extra fingers, oversaturated",
  width: 1024,
  height: 1024,
  steps: 28,
  guidance: 3.5,
  cfg_scale: 3.5,
  seed: 428193 as number | null,
  batch_count: 4,
  sampler: "euler",
  scheduler: "karras",
  output_format: "png",
  strength: 0.62,
});

const generated = ref<any[]>(
  DEMO
    ? demoImagePaths.slice(0, 4).map((url, index) => ({
        index,
        path: demoGallery[index]?.path || `images/gallery/art-0${index + 1}.png`,
        url,
        thumbnail_url: url,
        prompt: demoGallery[index]?.prompt || form.prompt,
        provider: "diffusers",
        model: form.model,
        width: 1024,
        height: 1024,
        seed: 428193 + index * 7,
        created_at: demoGallery[index]?.created_at || new Date().toISOString(),
      }))
    : [],
);
const img2imgResults = ref<any[]>([]);
const initImage = ref<any>(
  DEMO
    ? {
        path: demoGallery[2]?.path || "images/gallery/art-03.png",
        name: "art-03.png",
        size_label: "1.8 MB",
        preview: demoGallery[2]?.url || "/demo/art-03.png",
      }
    : null,
);
const initPickerOpen = ref(false);
const img2imgStrength = ref(0.62);

const upscale = reactive({
  path: DEMO ? demoGallery[4]?.path || "images/gallery/art-05.png" : "",
  name: "art-05.png",
  preview: DEMO ? demoGallery[4]?.url || "/demo/art-05.png" : "",
  repeats: 1,
  provider: "diffusers",
  model: "Real-ESRGAN x4",
  output_format: "png",
  sharpen: true,
});
const upscalePickerOpen = ref(false);
const upscaleResult = ref<any>(
  DEMO
    ? {
        path: demoGallery[4]?.path || "images/gallery/art-05.png",
        url: demoGallery[4]?.url || "/demo/art-05.png",
        width: 2048,
        height: 2048,
        source_path: demoGallery[4]?.path || "images/gallery/art-05.png",
        source_width: 1024,
        source_height: 1024,
        format: "png",
      }
    : null,
);

const activeJobId = ref("");
const submittedJob = ref<Job | null>(null);
const activeKind = ref<"generate" | "img2img" | "upscale">("generate");
const processedJobId = ref("");
const busy = ref(false);
let pollTimer: number | undefined;
let demoProgressTimer: number | undefined;

const tabs = computed(() => [
  { id: "generate", label: "Generate", count: generated.value.length },
  { id: "img2img", label: "Image-to-image", count: img2imgResults.value.length },
  { id: "upscale", label: "Upscale" },
  { id: "gallery", label: "Gallery", count: gallery.value.length },
]);

const selectedProvider = computed(() => providers.value.find((provider) => provider.id === form.provider) || null);
const providerModels = computed(() => {
  const fromCatalog = modelCatalog.value.filter((model) => model.provider === form.provider);
  if (fromCatalog.length) return fromCatalog;
  const provider = selectedProvider.value;
  return (provider?.models || []).map((model: any) => ({ ...model, provider: form.provider }));
});
const providerAvailable = computed(() => Boolean(selectedProvider.value?.available));
const availableProviders = computed(() => providers.value.filter((provider) => provider.available).length);
const sizeActive = computed(() => sizePresets.find((preset) => preset.width === form.width && preset.height === form.height)?.id || "custom");
const galleryProviders = computed(() => ["all", ...Array.from(new Set(gallery.value.map((item) => item.provider).filter(Boolean)))]);
const filteredGallery = computed(() => {
  const needle = galleryQuery.value.trim().toLowerCase();
  return gallery.value.filter((item) => {
    if (galleryProvider.value !== "all" && item.provider !== galleryProvider.value) return false;
    if (!needle) return true;
    return `${item.prompt || ""} ${item.title || ""} ${item.model || ""} ${item.provider || ""}`.toLowerCase().includes(needle);
  });
});
const activeJob = computed<Job | null>(() => (activeJobId.value ? jobs.byId(activeJobId.value) || submittedJob.value : submittedJob.value));
const activeRunning = computed(() => (activeJob.value ? ["queued", "running", "canceling"].includes(activeJob.value.status) : false));
const scale = computed(() => Math.min(8, Math.pow(2, Math.max(1, Number(upscale.repeats) || 1))));
const scaleLabel = computed(() => `${Math.round(scale.value)}×`);
const upscaleTarget = computed(() => {
  const sourceWidth = upscaleResult.value?.source_width || 1024;
  const sourceHeight = upscaleResult.value?.source_height || 1024;
  return `${Math.min(8192, Math.round(sourceWidth * scale.value))} × ${Math.min(8192, Math.round(sourceHeight * scale.value))}`;
});
const currentResults = computed(() => (tab.value === "img2img" ? img2imgResults.value : generated.value));
const currentResultsLabel = computed(() => (tab.value === "img2img" ? "Image-to-image set" : "Generated set"));

function providerName(id?: string | null) {
  return providers.value.find((provider) => provider.id === id)?.name || id || "Image provider";
}

function modelName(id?: string | null) {
  const all = [...modelCatalog.value, ...DEMO_PROVIDERS.flatMap((provider) => provider.models || [])];
  return all.find((model: any) => model.id === id)?.name || id || "auto";
}

function imageSrc(item: any) {
  if (!item) return "";
  const value = item.url || item.thumbnail_url || (item.path ? fileUrl(item.path) : "");
  if (!value) return "";
  if (value.startsWith("/api/") || value.startsWith("/demo/") || value.startsWith("http") || value.startsWith("data:") || value.startsWith("blob:")) return value;
  return fileUrl(value);
}

function imageDownload(item: any) {
  if (!item) return "#";
  if (String(item.url || "").startsWith("/demo/")) return item.url;
  if (item.path) return downloadUrl(item.path);
  return imageSrc(item) || "#";
}

function randomSeed() {
  form.seed = Math.floor(Math.random() * 2_000_000_000);
}

function applySize(preset: any) {
  form.width = preset.width;
  form.height = preset.height;
}

function applyModelDefaults(model: any) {
  const defaults = model?.defaults;
  if (!defaults) return;
  if (defaults.width) form.width = Number(defaults.width);
  if (defaults.height) form.height = Number(defaults.height);
  if (defaults.steps) form.steps = Number(defaults.steps);
  if (defaults.guidance !== undefined && defaults.guidance !== null) form.guidance = Number(defaults.guidance);
  if (defaults.cfg_scale !== undefined && defaults.cfg_scale !== null) form.cfg_scale = Number(defaults.cfg_scale);
  if (defaults.batch_count) form.batch_count = Number(defaults.batch_count);
}

function changeProvider() {
  const options = providerModels.value;
  if (options.length) {
    form.model = options[0].id;
    applyModelDefaults(options[0]);
  }
}

function changeModel() {
  const model = providerModels.value.find((entry: any) => entry.id === form.model);
  applyModelDefaults(model);
}

function normalizeImage(item: any) {
  return {
    ...item,
    path: item.path || "",
    url: item.url || (item.path ? fileUrl(item.path) : ""),
    thumbnail_url: item.thumbnail_url || item.thumbnail_path || item.url || (item.path ? fileUrl(item.path) : ""),
    prompt: item.prompt || form.prompt,
    provider: item.provider || form.provider,
    model: item.model || form.model,
    width: item.width || form.width,
    height: item.height || form.height,
    seed: item.seed ?? form.seed,
    created_at: item.created_at || new Date().toISOString(),
  };
}

function buildPayload(mode: "generate" | "img2img") {
  const payload: any = {
    provider: form.provider,
    model: form.model,
    prompt: form.prompt.trim(),
    negative_prompt: form.negative_prompt.trim(),
    width: Number(form.width),
    height: Number(form.height),
    steps: Number(form.steps),
    guidance: Number(form.guidance),
    cfg_scale: Number(form.cfg_scale),
    seed: form.seed === null || form.seed === undefined ? null : Number(form.seed),
    batch_count: Math.max(1, Math.min(8, Number(form.batch_count) || 1)),
    sampler: form.sampler,
    scheduler: form.scheduler || null,
    output_format: form.output_format,
    allow_fallback: form.provider !== "qvac",
    style: form.provider === "procedural" ? form.model.split(":").pop() : undefined,
  };
  if (mode === "img2img") {
    payload.init_image = initImage.value?.path || null;
    payload.strength = Number(img2imgStrength.value);
  }
  return payload;
}

function demoImages(mode: "generate" | "img2img") {
  const offset = mode === "img2img" ? 3 : 0;
  const count = Math.max(1, Math.min(8, Number(form.batch_count) || 1));
  return Array.from({ length: count }, (_, index) => {
    const source = demoGallery[(offset + index) % demoGallery.length];
    const url = demoImagePaths[(offset + index) % demoImagePaths.length];
    return {
      index,
      path: source?.path || `images/gallery/art-${String(((offset + index) % 8) + 1).padStart(2, "0")}.png`,
      url,
      thumbnail_url: url,
      prompt: form.prompt,
      provider: form.provider,
      model: form.model,
      width: Number(form.width),
      height: Number(form.height),
      seed: (Number(form.seed) || 428193) + index * 13,
      created_at: new Date().toISOString(),
      init_image: mode === "img2img" ? initImage.value?.path : null,
      strength: mode === "img2img" ? Number(img2imgStrength.value) : null,
    };
  });
}

function trackJob(raw: any, kind: typeof activeKind.value) {
  const id = raw?.id || raw?.job_id;
  if (!id) throw new Error("The image service did not return a job id");
  const normalized = { ...raw, id } as Job;
  submittedJob.value = normalized;
  activeJobId.value = id;
  activeKind.value = kind;
  processedJobId.value = "";
  jobs.upsert(normalized);
  if (!DEMO) startPollingJob(id);
}

function startPollingJob(id: string) {
  window.clearTimeout(pollTimer);
  const tick = async () => {
    try {
      const fresh = await api.get<Job>(`/jobs/${id}`);
      jobs.upsert(fresh);
      if (!["queued", "running", "canceling"].includes(fresh.status)) return;
    } catch {
      // SSE drives normal updates; polling is only a fallback.
    }
    pollTimer = window.setTimeout(tick, 2600);
  };
  pollTimer = window.setTimeout(tick, 2200);
}

function simulateJob(kind: typeof activeKind.value, title: string, data: any) {
  window.clearInterval(demoProgressTimer);
  const id = `job_demo_img_${Math.random().toString(36).slice(2, 10)}`;
  const now = new Date().toISOString();
  const base: Job = {
    id,
    component: "imagegen",
    action: kind === "upscale" ? "upscale" : "generate",
    title,
    status: "running",
    stage: kind === "upscale" ? "Resizing" : "Diffusion",
    message: kind === "upscale" ? "Loading the source image…" : "Sampling step 4 of 28…",
    progress: 8,
    params: {},
    result: null,
    error: null,
    warnings: [],
    artifacts: [],
    cancel_requested: false,
    attempts: 1,
    created_at: now,
    started_at: now,
    finished_at: null,
    updated_at: now,
  };
  submittedJob.value = base;
  activeJobId.value = id;
  activeKind.value = kind;
  processedJobId.value = "";
  jobs.upsert(base);
  let progress = 8;
  demoProgressTimer = window.setInterval(() => {
    progress = Math.min(96, progress + 6 + Math.random() * 8);
    const running: Job = {
      ...base,
      progress,
      message:
        kind === "upscale"
          ? "Applying Lanczos resize and unsharp mask…"
          : `Sampling step ${Math.min(Number(form.steps), Math.round((progress / 100) * Number(form.steps)))} of ${form.steps}…`,
      updated_at: new Date().toISOString(),
    };
    submittedJob.value = running;
    jobs.upsert(running);
    if (progress >= 96) {
      window.clearInterval(demoProgressTimer);
      const completed: Job = {
        ...running,
        status: "completed",
        stage: "Complete",
        message: "Demo generation complete.",
        progress: 100,
        result: {
          message: "Demo generation complete.",
          files: (data.images || []).map((image: any) => ({
            path: image.path,
            name: image.path.split("/").pop(),
            kind: "image",
            mime: "image/png",
            size: 2_880_000,
          })),
          data,
        },
        finished_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      submittedJob.value = completed;
      jobs.upsert(completed);
    }
  }, 420);
}

async function generate(mode: "generate" | "img2img") {
  if (!form.prompt.trim() && form.provider !== "procedural") {
    toasts.error("Write a prompt first");
    return;
  }
  if (mode === "img2img" && !initImage.value?.path) {
    toasts.error("Choose an initial image");
    return;
  }
  busy.value = true;
  try {
    if (DEMO) {
      const images = demoImages(mode);
      simulateJob(mode, `${mode === "img2img" ? "Image-to-image" : "Generate"} · ${form.prompt.slice(0, 52)}`, {
        provider: form.provider,
        model: form.model,
        prompt: form.prompt,
        negative_prompt: form.negative_prompt,
        images,
        batch_count: images.length,
        seed: form.seed,
        created_at: new Date().toISOString(),
      });
      toasts.info(mode === "img2img" ? "Rendering a demo img2img set…" : "Rendering a demo image set…");
      return;
    }
    const raw = await api.post<any>("/images/generate", buildPayload(mode));
    trackJob(raw, mode);
    toasts.info(mode === "img2img" ? "Image-to-image job queued" : "Image generation queued");
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    busy.value = false;
  }
}

async function runUpscale() {
  if (!upscale.path) {
    toasts.error("Choose an image to upscale");
    return;
  }
  busy.value = true;
  try {
    if (DEMO) {
      const result = {
        path: upscale.path,
        url: upscale.preview || demoGallery[4]?.url || "/demo/art-05.png",
        thumbnail_url: upscale.preview || demoGallery[4]?.url,
        width: Math.min(8192, Math.round(1024 * scale.value)),
        height: Math.min(8192, Math.round(1024 * scale.value)),
        source_path: upscale.path,
        source_width: 1024,
        source_height: 1024,
        format: upscale.output_format,
        provider: upscale.provider,
        model: upscale.model,
        created_at: new Date().toISOString(),
      };
      simulateJob("upscale", `Upscale · ${upscale.name}`, { image: result, images: [result], provider: "upscale" });
      toasts.info("Upscaling the demo image…");
      return;
    }
    const raw = await api.post<any>("/images/upscale", {
      path: upscale.path,
      scale: scale.value,
      output_format: upscale.output_format,
      sharpen: upscale.sharpen,
      provider: upscale.provider,
      model: upscale.model,
      title: `Upscale ${upscale.name}`,
    });
    trackJob(raw, "upscale");
    toasts.info("Upscale queued");
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    busy.value = false;
  }
}

function handleCompleted(job: Job) {
  const data: any = job.result?.data || {};
  if (activeKind.value === "upscale") {
    const image = data.image || data.images?.[0];
    if (image) upscaleResult.value = normalizeImage(image);
    toasts.success("Upscale complete");
    return;
  }
  const images = (data.images || []).map(normalizeImage);
  if (!images.length) {
    toasts.error("The image provider returned no images");
    return;
  }
  if (activeKind.value === "img2img") img2imgResults.value = images;
  else generated.value = images;
  gallery.value = [
    ...images,
    ...gallery.value.filter((item) => !images.some((image: any) => image.path && image.path === item.path)),
  ];
  toasts.success(`${images.length} image${images.length === 1 ? "" : "s"} ready`);
}

watch(
  activeJob,
  (job) => {
    if (!job || job.id === processedJobId.value) return;
    if (["queued", "running", "canceling"].includes(job.status)) return;
    processedJobId.value = job.id;
    if (job.status === "completed") handleCompleted(job);
    else if (job.status === "failed") toasts.error(job.error || "Image job failed");
    else if (job.status === "canceled") toasts.info("Image job canceled");
  },
  { deep: true },
);

async function cancelActive() {
  if (!activeJob.value) return;
  if (DEMO) {
    window.clearInterval(demoProgressTimer);
    const canceled: Job = {
      ...activeJob.value,
      status: "canceled",
      stage: "Cancelled",
      message: "Cancelled by the user.",
      cancel_requested: true,
      finished_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    submittedJob.value = canceled;
    jobs.upsert(canceled);
    toasts.info("Cancellation requested");
    return;
  }
  try {
    await jobs.cancel(activeJob.value.id);
    toasts.info("Cancellation requested");
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function chooseInitImage(path: string, file: any) {
  initImage.value = {
    path,
    name: file?.name || path.split("/").pop() || "init.png",
    size_label: file?.size_label || (file?.size ? formatBytes(file.size) : ""),
    preview: fileUrl(path),
  };
}

function clearInitImage() {
  initImage.value = null;
}

function chooseUpscaleImage(path: string, file: any) {
  upscale.path = path;
  upscale.name = file?.name || path.split("/").pop() || "image.png";
  upscale.preview = fileUrl(path);
}

function openLightbox(item: any) {
  galleryItem.value = item;
  galleryOpen.value = true;
}

function reusePrompt(item: any) {
  if (!item) return;
  form.prompt = item.prompt || form.prompt;
  if (item.negative_prompt) form.negative_prompt = item.negative_prompt;
  if (item.provider && providers.value.some((provider) => provider.id === item.provider)) {
    form.provider = item.provider;
    const nextModel = providerModels.value.find((model: any) => model.id === item.model);
    form.model = nextModel?.id || providerModels.value[0]?.id || form.model;
  }
  if (item.width) form.width = item.width;
  if (item.height) form.height = item.height;
  if (item.seed !== undefined && item.seed !== null) form.seed = item.seed;
  tab.value = "generate";
  galleryOpen.value = false;
  toasts.info("Prompt and settings loaded into Generate");
}

async function loadCatalog() {
  if (DEMO) return;
  try {
    const [providerData, modelData] = await Promise.all([api.get<any>("/images/providers"), api.get<any>("/images/models")]);
    providers.value = providerData.items || providers.value;
    modelCatalog.value = (modelData.items || []).map((model: any) => ({ ...model, provider: model.provider }));
    const available = providers.value.find((provider) => provider.id === form.provider);
    if (!available) form.provider = providers.value[0]?.id || "procedural";
    const options = providerModels.value;
    if (!options.some((model: any) => model.id === form.model)) form.model = options[0]?.id || form.model;
  } catch (error: any) {
    toasts.error(error.message);
  }
}

async function loadGallery() {
  if (DEMO) return;
  galleryLoading.value = true;
  try {
    const data = await api.get<any>("/images/gallery?limit=80");
    gallery.value = (data.items || []).map((item: any) => ({
      ...item,
      thumbnail_url: item.thumbnail_path || item.thumbnail_url || item.url,
    }));
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    galleryLoading.value = false;
  }
}

onMounted(() => {
  if (!DEMO) {
    loadCatalog();
    loadGallery();
  }
});

onBeforeUnmount(() => {
  window.clearTimeout(pollTimer);
  window.clearInterval(demoProgressTimer);
});
import ServiceNotice from "@/components/ServiceNotice.vue";
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="Picture studio · diffusers / ComfyUI / QVAC / procedural"
      title="Picture studio"
      subtitle="Generate artwork, restyle a reference or upscale a finished image with every local backend. Prompts, seeds and full parameter metadata stay beside every file."
    >
      <template #actions>
        <span class="chip success"><span class="dot online" /> {{ availableProviders }}/{{ providers.length }} providers</span>
        <span class="chip"><Aperture :size="11" /> {{ generated.length }} images</span>
        <button class="btn btn-sm" @click="tab = 'gallery'"><Images :size="13" /> Gallery</button>
      </template>
    </PageHeader>

    <ServiceNotice
      :services="[{ name: 'imagegen', label: 'Picture Studio' }]"
      title="This workspace needs Picture Studio"
    />

    <div class="stat-grid" style="margin-bottom: 16px">
      <div class="stat">
        <div class="stat-label">Active provider</div>
        <div class="stat-value" style="font-size: 22px; text-transform: capitalize">{{ selectedProvider?.name || form.provider }}</div>
        <div class="stat-sub">{{ providerAvailable ? "Ready on this machine" : "Unavailable · procedural fallback" }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Model</div>
        <div class="stat-value" style="font-size: 17px">{{ modelName(form.model) }}</div>
        <div class="stat-sub">{{ form.width }} × {{ form.height }} · {{ form.steps }} steps</div>
      </div>
      <div class="stat">
        <div class="stat-label">Last set</div>
        <div class="stat-value">{{ currentResults.length }}</div>
        <div class="stat-sub">{{ form.batch_count }} per batch · seed {{ form.seed ?? "random" }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Gallery</div>
        <div class="stat-value">{{ gallery.length }}</div>
        <div class="stat-sub">Prompt + metadata sidecars</div>
      </div>
    </div>

    <div class="row-between" style="margin-bottom: 16px; align-items: flex-start">
      <TabsBar v-model="tab" :tabs="tabs" />
      <div class="row" style="gap: 5px">
        <span class="chip"><SlidersHorizontal :size="11" /> {{ form.sampler }} / {{ form.scheduler }}</span>
        <span class="chip"><Layers :size="11" /> {{ form.output_format.toUpperCase() }}</span>
      </div>
    </div>

    <section v-if="tab !== 'gallery' && activeJob" class="panel" style="margin-bottom: 16px">
      <div class="panel-head">
        <div><h3>Active image job</h3><p>{{ activeKind === "upscale" ? "Upscale" : activeKind === "img2img" ? "Image-to-image" : "Text-to-image" }} · live progress from the job hub.</p></div>
        <span class="badge running">{{ Math.round(activeJob.progress) }}%</span>
      </div>
      <div class="panel-body"><JobCard :job="activeJob" @cancel="cancelActive" /></div>
    </section>

    <section v-if="tab === 'generate' || tab === 'img2img'" class="stack">
      <div class="split split-wide">
        <div class="stack">
          <div v-if="tab === 'img2img'" class="panel">
            <div class="panel-head">
              <div><h3>Initial image</h3><p>Source pixels guide composition; strength decides how far to travel.</p></div>
              <button class="btn btn-sm" @click="initPickerOpen = true"><Upload :size="13" /> Choose image</button>
            </div>
            <div class="panel-body stack" style="gap: 10px">
              <div v-if="initImage" class="selected-file">
                <img :src="initImage.preview || imageSrc(initImage)" alt="" style="width: 54px; height: 54px; border-radius: 9px; object-fit: cover" />
                <div class="grow" style="min-width: 0">
                  <div class="small strong truncate">{{ initImage.name }}</div>
                  <div class="small muted truncate mono">{{ initImage.path }}</div>
                </div>
                <span class="chip">{{ initImage.size_label || "image" }}</span>
                <button class="icon-btn" title="Remove" @click="clearInitImage"><X :size="14" /></button>
              </div>
              <button v-else class="pick-zone" @click="initPickerOpen = true">
                <Upload :size="23" />
                <span class="strong">Choose an initial image</span>
                <span class="small muted">Any image from shared storage, or upload a new one.</span>
              </button>
              <div class="field">
                <label>Strength <span class="mono small">{{ Number(img2imgStrength).toFixed(2) }}</span></label>
                <input v-model.number="img2imgStrength" type="range" min="0" max="1" step="0.01" />
                <span class="hint">Low keeps the source; high lets the prompt take over.</span>
              </div>
            </div>
          </div>

          <div class="panel">
            <div class="panel-head">
              <div><h3>{{ tab === "img2img" ? "Restyle prompt" : "Prompt" }}</h3><p>Describe the picture, light, material and camera. Negative prompts shape what to avoid.</p></div>
              <span class="chip">{{ form.prompt.length }} chars</span>
            </div>
            <div class="panel-body stack" style="gap: 11px">
              <textarea v-model="form.prompt" class="textarea prompt-area" rows="6" placeholder="A porcelain city at dusk, wet asphalt, anamorphic light, violet haze…" />
              <div class="row" style="gap: 5px">
                <span class="small muted" style="margin-right: 2px">Prompt starters</span>
                <button v-for="idea in promptIdeas" :key="idea" class="chip clickable" @click="form.prompt = idea">{{ idea.split(",")[0] }}</button>
              </div>
              <div class="field">
                <label>Negative prompt</label>
                <textarea v-model="form.negative_prompt" class="textarea" rows="2" placeholder="low quality, text, watermark, extra fingers…" />
              </div>
              <div class="row-between small muted">
                <span>{{ form.batch_count }} image(s) · {{ form.width }} × {{ form.height }}</span>
                <span>Files land in <span class="mono">images/&lt;job&gt;/</span></span>
              </div>
            </div>
          </div>

          <div class="panel">
            <div class="panel-head">
              <div><h3>Composition</h3><p>Use a preset or set an exact size. Providers round dimensions to their supported grid.</p></div>
              <span class="chip">{{ sizeActive === "custom" ? "Custom" : sizePresets.find((preset) => preset.id === sizeActive)?.hint }}</span>
            </div>
            <div class="panel-body stack" style="gap: 11px">
              <div class="row" style="gap: 6px">
                <button v-for="preset in sizePresets" :key="preset.id" class="size-chip" :class="{ active: sizeActive === preset.id }" @click="applySize(preset)">
                  <strong>{{ preset.label }}</strong>
                  <span>{{ preset.width }}×{{ preset.height }}</span>
                </button>
              </div>
              <div class="grid grid-2" style="gap: 11px; max-width: 430px">
                <div class="field"><label>Width</label><input v-model.number="form.width" class="input" type="number" min="64" max="4096" step="8" /></div>
                <div class="field"><label>Height</label><input v-model.number="form.height" class="input" type="number" min="64" max="4096" step="8" /></div>
              </div>
            </div>
          </div>
        </div>

        <aside class="panel settings-sticky">
          <div class="panel-head">
            <div><h3>{{ tab === "img2img" ? "Image-to-image setup" : "Generation setup" }}</h3><p>Provider, sampler and all diffusion controls.</p></div>
            <span class="badge" :class="providerAvailable ? 'success' : 'warn'">{{ providerAvailable ? "Available" : "Fallback" }}</span>
          </div>
          <div class="panel-body stack" style="gap: 11px">
            <div class="grid grid-2" style="gap: 10px">
              <div class="field">
                <label>Provider</label>
                <select v-model="form.provider" class="select" @change="changeProvider">
                  <option v-for="provider in providers" :key="provider.id" :value="provider.id">{{ provider.name }}{{ provider.available ? "" : " · unavailable" }}</option>
                </select>
                <span class="hint">{{ selectedProvider?.detail || "Local image backend" }}</span>
              </div>
              <div class="field">
                <label>Model</label>
                <select v-model="form.model" class="select" @change="changeModel">
                  <option v-for="model in providerModels" :key="model.id" :value="model.id">{{ model.name }}</option>
                </select>
                <span class="hint">{{ providerModels.find((model: any) => model.id === form.model)?.detail || "Model defaults" }}</span>
              </div>
            </div>

            <div v-if="!providerAvailable" class="alert warn">
              {{ providerName(form.provider) }} reports unavailable. The service can fall back to procedural artwork while you install the model.
            </div>

            <div class="grid grid-3" style="gap: 9px">
              <div class="field"><label>Steps</label><input v-model.number="form.steps" class="input" type="number" min="1" max="200" /></div>
              <div class="field"><label>Guidance</label><input v-model.number="form.guidance" class="input" type="number" min="0" max="30" step="0.1" /></div>
              <div class="field"><label>CFG scale</label><input v-model.number="form.cfg_scale" class="input" type="number" min="0" max="30" step="0.1" /></div>
            </div>

            <div class="grid grid-2" style="gap: 10px">
              <div class="field">
                <label>Seed <button class="chip clickable" style="padding: 1px 6px" @click="randomSeed"><Shuffle :size="9" /> random</button></label>
                <input v-model.number="form.seed" class="input mono" type="number" min="0" max="2147483647" placeholder="Random" />
              </div>
              <div class="field">
                <label>Batch count <span class="mono small">{{ form.batch_count }}</span></label>
                <input v-model.number="form.batch_count" type="range" min="1" max="8" step="1" />
                <span class="hint">1–8 images per job.</span>
              </div>
            </div>

            <div class="grid grid-2" style="gap: 10px">
              <div class="field">
                <label>Sampler</label>
                <select v-model="form.sampler" class="select">
                  <option v-for="sampler in SAMPLERS" :key="sampler" :value="sampler">{{ sampler }}</option>
                </select>
              </div>
              <div class="field">
                <label>Scheduler</label>
                <select v-model="form.scheduler" class="select">
                  <option v-for="scheduler in SCHEDULERS" :key="scheduler" :value="scheduler">{{ scheduler }}</option>
                </select>
              </div>
            </div>

            <div class="grid grid-2" style="gap: 10px">
              <div class="field">
                <label>Output format</label>
                <select v-model="form.output_format" class="select">
                  <option value="png">PNG · lossless</option>
                  <option value="jpeg">JPEG · compact</option>
                  <option value="webp">WebP · modern</option>
                </select>
              </div>
              <div class="field">
                <label>Canvas</label>
                <input class="input mono" :value="`${form.width} × ${form.height}`" readonly />
                <span class="hint">Edit width and height in Composition.</span>
              </div>
            </div>

            <button class="btn btn-primary btn-block" :disabled="busy || activeRunning" @click="generate(tab === 'img2img' ? 'img2img' : 'generate')">
              <Loader2 v-if="busy" :size="14" class="spin" />
              <Sparkles v-else :size="14" />
              {{ tab === "img2img" ? "Generate from image" : `Generate ${form.batch_count} image${form.batch_count === 1 ? "" : "s"}` }}
            </button>
            <span class="small muted" style="text-align: center">
              {{ form.provider === "procedural" ? "Deterministic Pillow artwork · no model needed" : "Full parameters are saved in a JSON sidecar" }}
            </span>
          </div>
        </aside>
      </div>

      <div v-if="currentResults.length" class="panel">
        <div class="panel-head">
          <div><h3>{{ currentResultsLabel }}</h3><p>{{ form.provider }} · {{ modelName(form.model) }} · seed {{ form.seed ?? "random" }} · {{ form.width }} × {{ form.height }}</p></div>
          <div class="row" style="gap: 5px">
            <span class="chip success">{{ currentResults.length }} images</span>
            <button class="btn btn-sm btn-ghost" @click="tab = 'gallery'"><Images :size="12" /> Open gallery</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="gallery">
            <div v-for="image in currentResults" :key="image.path || image.url" class="gallery-item image-result">
              <div class="image-frame">
                <img :src="imageSrc(image)" :alt="image.prompt || 'Generated image'" />
                <div class="image-actions">
                  <button class="icon-btn" title="Open full image" @click="openLightbox(image)"><Maximize2 :size="14" /></button>
                  <a class="icon-btn" :href="imageSrc(image)" target="_blank" rel="noopener" title="Open in new tab"><ExternalLink :size="14" /></a>
                  <a class="icon-btn" :href="imageDownload(image)" title="Download"><Download :size="14" /></a>
                </div>
              </div>
              <div class="meta">
                <div class="small strong truncate">{{ image.prompt || form.prompt }}</div>
                <div class="row-between small muted" style="margin-top: 4px">
                  <span class="mono">{{ image.width || form.width }}×{{ image.height || form.height }}</span>
                  <span class="mono">seed {{ image.seed ?? form.seed }}</span>
                </div>
                <div class="row-between small muted" style="margin-top: 2px">
                  <span>{{ providerName(image.provider || form.provider) }}</span>
                  <span>{{ relativeTime(image.created_at) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="tab === 'generate' && gallery.length" class="panel">
        <div class="panel-head">
          <div><h3>Recent gallery</h3><p>Every generated file keeps its prompt and full metadata.</p></div>
          <button class="btn btn-sm btn-ghost" @click="tab = 'gallery'">All images <ArrowRight :size="12" /></button>
        </div>
        <div class="panel-body">
          <div class="gallery">
            <div v-for="item in gallery.slice(0, 8)" :key="item.path" class="gallery-item" style="cursor: pointer" @click="openLightbox(item)">
              <img :src="imageSrc(item)" :alt="item.prompt" loading="lazy" />
              <div class="meta">
                <div class="small strong truncate">{{ item.title || item.prompt }}</div>
                <div class="row-between small muted" style="margin-top: 3px">
                  <span>{{ providerName(item.provider) }}</span>
                  <span class="mono">{{ item.width }}×{{ item.height }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section v-else-if="tab === 'upscale'" class="stack">
      <div class="split split-wide">
        <div class="stack">
          <div class="panel">
            <div class="panel-head">
              <div><h3>Source image</h3><p>Upscale locally with Lanczos resizing and an optional unsharp mask.</p></div>
              <button class="btn btn-sm" @click="upscalePickerOpen = true"><Upload :size="13" /> Choose image</button>
            </div>
            <div class="panel-body stack" style="gap: 11px">
              <div v-if="upscale.path" class="selected-file">
                <img :src="upscale.preview || imageSrc({ path: upscale.path })" alt="" style="width: 58px; height: 58px; border-radius: 9px; object-fit: cover" />
                <div class="grow" style="min-width: 0">
                  <div class="small strong truncate">{{ upscale.name }}</div>
                  <div class="small muted truncate mono">{{ upscale.path }}</div>
                </div>
                <span class="chip">{{ upscaleResult?.source_width || 1024 }} × {{ upscaleResult?.source_height || 1024 }}</span>
              </div>
              <button v-else class="pick-zone" @click="upscalePickerOpen = true">
                <Crop :size="23" />
                <span class="strong">Choose an image to upscale</span>
                <span class="small muted">PNG, JPEG or WebP from shared storage.</span>
              </button>
              <div class="grid grid-3" style="gap: 11px">
                <div class="field">
                  <label>Repeats</label>
                  <input v-model.number="upscale.repeats" class="input" type="number" min="1" max="3" />
                  <span class="hint">{{ scaleLabel }} on the longest edge.</span>
                </div>
                <div class="field">
                  <label>Output format</label>
                  <select v-model="upscale.output_format" class="select">
                    <option value="png">PNG</option>
                    <option value="jpeg">JPEG</option>
                    <option value="webp">WebP</option>
                  </select>
                </div>
                <div class="field">
                  <label>Sharpen</label>
                  <button class="switch" :class="{ on: upscale.sharpen }" style="margin-top: 5px" @click="upscale.sharpen = !upscale.sharpen" />
                  <span class="hint">Unsharp mask after resizing.</span>
                </div>
              </div>
            </div>
          </div>

          <div v-if="upscaleResult" class="panel">
            <div class="panel-head">
              <div><h3>Upscaled result</h3><p>{{ upscaleResult.width }} × {{ upscaleResult.height }} · {{ String(upscaleResult.format || upscale.output_format).toUpperCase() }}</p></div>
              <div class="row" style="gap: 5px">
                <a class="btn btn-sm" :href="imageDownload(upscaleResult)" target="_blank" rel="noopener"><Download :size="12" /> Download</a>
                <button class="icon-btn" @click="openLightbox(upscaleResult)"><Maximize2 :size="15" /></button>
              </div>
            </div>
            <div class="panel-body">
              <div class="compare-grid">
                <div class="compare-tile">
                  <img :src="upscale.preview || imageSrc(upscaleResult)" alt="Source" />
                  <span class="chip">Source · {{ upscaleResult.source_width || 1024 }} px</span>
                </div>
                <div class="compare-tile">
                  <img :src="imageSrc(upscaleResult)" alt="Upscaled" />
                  <span class="chip success">Upscaled · {{ upscaleResult.width }} px</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <aside class="panel settings-sticky">
          <div class="panel-head"><div><h3>Upscale setup</h3><p>Provider and model are recorded with the result.</p></div><Expand :size="16" class="muted" /></div>
          <div class="panel-body stack" style="gap: 12px">
            <div class="field">
              <label>Provider</label>
              <select v-model="upscale.provider" class="select">
                <option value="diffusers">Diffusers</option>
                <option value="procedural">Procedural</option>
                <option value="comfyui">ComfyUI</option>
              </select>
            </div>
            <div class="field">
              <label>Model</label>
              <select v-model="upscale.model" class="select">
                <option value="Real-ESRGAN x4">Real-ESRGAN x4</option>
                <option value="SwinIR large">SwinIR large</option>
                <option value="Pillow Lanczos">Pillow Lanczos</option>
              </select>
              <span class="hint">The image service uses Pillow Lanczos internally and records the requested route.</span>
            </div>
            <div class="field">
              <label>Scale</label>
              <div class="upscale-scale">
                <span>{{ scaleLabel }}</span>
                <span class="small muted">→ {{ upscaleTarget }}</span>
              </div>
              <div class="progress thin"><span :style="{ width: `${(scale / 8) * 100}%` }" /></div>
            </div>
            <div class="alert">
              <Zap :size="12" style="vertical-align: -2px; color: var(--warning)" />
              Runs synchronously inside a job. Large images are capped at 8192 px per side.
            </div>
            <button class="btn btn-primary btn-block" :disabled="busy || activeRunning || !upscale.path" @click="runUpscale">
              <Loader2 v-if="busy" :size="14" class="spin" />
              <Expand v-else :size="14" />
              Upscale {{ scaleLabel }}
            </button>
          </div>
        </aside>
      </div>
    </section>

    <section v-else-if="tab === 'gallery'" class="stack">
      <div class="panel">
        <div class="panel-head" style="flex-wrap: wrap; gap: 10px">
          <div><h3>Image gallery</h3><p>{{ filteredGallery.length }} of {{ gallery.length }} images · prompt search across the shared tree.</p></div>
          <div class="row">
            <div class="input-group" style="width: 260px">
              <Search :size="13" class="muted" />
              <input v-model="galleryQuery" class="input input-sm" placeholder="Search prompt, title or model…" />
            </div>
            <select v-model="galleryProvider" class="select input-sm" style="width: 145px">
              <option v-for="provider in galleryProviders" :key="provider" :value="provider">{{ provider === "all" ? "All providers" : providerName(provider) }}</option>
            </select>
            <button class="btn btn-sm btn-ghost" :disabled="galleryLoading" @click="loadGallery"><RefreshCw :size="13" /> Refresh</button>
          </div>
        </div>
        <div class="panel-body">
          <div v-if="galleryLoading" class="gallery">
            <div v-for="index in 8" :key="index" class="skeleton" style="aspect-ratio: 1/1; border-radius: 12px" />
          </div>
          <div v-else-if="filteredGallery.length" class="gallery">
            <div v-for="item in filteredGallery" :key="item.path || item.url" class="gallery-item gallery-tile" @click="openLightbox(item)">
              <img :src="imageSrc(item)" :alt="item.prompt" loading="lazy" />
              <div class="gallery-overlay">
                <span class="chip success">{{ providerName(item.provider) }}</span>
                <span class="chip">{{ item.width }}×{{ item.height }}</span>
              </div>
              <div class="meta">
                <div class="small strong truncate">{{ item.title || item.prompt }}</div>
                <div class="small muted truncate">{{ item.prompt }}</div>
                <div class="row-between small muted" style="margin-top: 4px">
                  <span class="mono">seed {{ item.seed ?? "—" }}</span>
                  <span>{{ relativeTime(item.created_at) }}</span>
                </div>
              </div>
            </div>
          </div>
          <EmptyState v-else :icon="Images" title="No images match" message="Generate a set, clear the search, or pick another provider. Every generated image writes a JSON sidecar into the shared gallery.">
            <button class="btn btn-sm" @click="tab = 'generate'">Open generator</button>
          </EmptyState>
        </div>
      </div>
    </section>

    <BaseModal v-model="galleryOpen" :title="galleryItem?.title || 'Generated image'" :subtitle="galleryItem ? `${providerName(galleryItem.provider)} · ${galleryItem.width || '?'} × ${galleryItem.height || '?'} · seed ${galleryItem.seed ?? '—'}` : ''" width="wide">
      <div v-if="galleryItem" class="stack" style="gap: 14px">
        <img :src="imageSrc(galleryItem)" :alt="galleryItem.prompt" style="width: 100%; max-height: 56vh; object-fit: contain; border-radius: 12px; border: 1px solid var(--line); background: #07090d" />
        <div class="grid grid-2" style="gap: 14px">
          <div class="stack" style="gap: 10px">
            <div class="field">
              <label>Prompt</label>
              <div class="code">{{ galleryItem.prompt || "No prompt recorded" }}</div>
            </div>
            <div v-if="galleryItem.negative_prompt" class="field">
              <label>Negative prompt</label>
              <div class="code">{{ galleryItem.negative_prompt }}</div>
            </div>
          </div>
          <div class="stack" style="gap: 8px">
            <div class="result-meta">
              <div><span>Provider</span><strong>{{ providerName(galleryItem.provider) }}</strong></div>
              <div><span>Model</span><strong>{{ galleryItem.model || modelName(form.model) }}</strong></div>
              <div><span>Size</span><strong>{{ galleryItem.width }} × {{ galleryItem.height }}</strong></div>
              <div><span>Seed</span><strong class="mono">{{ galleryItem.seed ?? "—" }}</strong></div>
              <div><span>Created</span><strong>{{ relativeTime(galleryItem.created_at) }}</strong></div>
              <div><span>Path</span><strong class="mono truncate" style="font-size: 10px">{{ galleryItem.path }}</strong></div>
            </div>
            <div class="row">
              <a class="btn btn-sm" :href="imageDownload(galleryItem)" target="_blank" rel="noopener"><Download :size="12" /> Download</a>
              <a class="btn btn-sm btn-ghost" :href="imageSrc(galleryItem)" target="_blank" rel="noopener"><ExternalLink :size="12" /> Open full</a>
              <button class="btn btn-sm btn-primary" @click="reusePrompt(galleryItem)"><Wand2 :size="12" /> Reuse prompt</button>
            </div>
          </div>
        </div>
      </div>
    </BaseModal>

    <FilePicker v-model="initPickerOpen" title="Initial image" kind="image" accept="image/*" @selected="chooseInitImage" />
    <FilePicker v-model="upscalePickerOpen" title="Image to upscale" kind="image" accept="image/*" @selected="chooseUpscaleImage" />
  </div>
</template>

<style scoped>
.prompt-area {
  min-height: 132px;
  font-size: 13px;
  line-height: 1.65;
}
.selected-file {
  display: flex;
  align-items: center;
  gap: 11px;
  border: 1px solid rgba(139, 92, 246, 0.3);
  background: rgba(139, 92, 246, 0.07);
  border-radius: 11px;
  padding: 10px 11px;
}
.pick-zone {
  width: 100%;
  min-height: 120px;
  border: 1px dashed var(--line-strong);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.012);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--muted);
  padding: 18px;
}
.pick-zone:hover {
  border-color: rgba(139, 92, 246, 0.5);
  color: var(--text);
  background: rgba(139, 92, 246, 0.04);
}
.settings-sticky {
  position: sticky;
  top: 84px;
}
.size-chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-width: 92px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.35);
  color: var(--muted);
  text-align: left;
}
.size-chip strong {
  font-size: 11px;
  color: var(--text);
}
.size-chip span {
  font-size: 9.5px;
  font-family: var(--mono);
}
.size-chip:hover {
  border-color: var(--line-strong);
}
.size-chip.active {
  border-color: rgba(139, 92, 246, 0.5);
  background: rgba(139, 92, 246, 0.13);
  color: #ddd6fe;
}
.size-chip.active strong {
  color: #ddd6fe;
}
.image-result {
  overflow: hidden;
}
.image-frame {
  position: relative;
  overflow: hidden;
  background: #0b0d13;
}
.image-frame img {
  width: 100%;
  aspect-ratio: 1/1;
  object-fit: cover;
  display: block;
  transition: transform 300ms ease;
}
.image-result:hover .image-frame img {
  transform: scale(1.035);
}
.image-actions {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 3px;
  padding: 3px;
  border-radius: 9px;
  background: rgba(7, 9, 13, 0.72);
  backdrop-filter: blur(8px);
  opacity: 0;
  transition: opacity 160ms ease;
}
.image-result:hover .image-actions {
  opacity: 1;
}
.image-actions .icon-btn {
  color: var(--text);
}
.gallery-tile {
  position: relative;
  cursor: pointer;
  overflow: hidden;
}
.gallery-tile img {
  transition: transform 300ms ease;
}
.gallery-tile:hover img {
  transform: scale(1.04);
}
.gallery-overlay {
  position: absolute;
  top: 8px;
  left: 8px;
  right: 8px;
  display: flex;
  justify-content: space-between;
  gap: 6px;
  opacity: 0;
  transition: opacity 160ms ease;
}
.gallery-tile:hover .gallery-overlay {
  opacity: 1;
}
.compare-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.compare-tile {
  position: relative;
  border: 1px solid var(--line);
  border-radius: 11px;
  overflow: hidden;
  background: #0b0d13;
}
.compare-tile img {
  width: 100%;
  aspect-ratio: 1/1;
  object-fit: contain;
  display: block;
}
.compare-tile .chip {
  position: absolute;
  left: 8px;
  bottom: 8px;
  background: rgba(7, 9, 13, 0.8);
}
.upscale-scale {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.35);
}
.upscale-scale > span:first-child {
  font-family: var(--display);
  font-size: 22px;
  font-weight: 700;
}
.result-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}
.result-meta > div {
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.35);
  padding: 8px 9px;
  min-width: 0;
}
.result-meta span {
  display: block;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted-2);
  font-weight: 700;
}
.result-meta strong {
  display: block;
  font-size: 11.5px;
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 1200px) {
  .settings-sticky {
    position: static;
  }
}
@media (max-width: 780px) {
  .compare-grid,
  .result-meta {
    grid-template-columns: 1fr;
  }
  .size-chip {
    min-width: 76px;
  }
}
</style>
