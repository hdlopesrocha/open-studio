<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  Boxes,
  Check,
  ChevronDown,
  CircleGauge,
  Clock,
  Cpu,
  Database,
  Download,
  Film,
  Gauge,
  HardDrive,
  Image as ImageIcon,
  Layers,
  Loader2,
  Maximize2,
  MemoryStick,
  MonitorPlay,
  Play,
  Plus,
  RefreshCw,
  Server,
  Shield,
  Shuffle,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Video,
  Wand2,
  X,
} from "lucide-vue-next";
import { api, downloadUrl, fileUrl, formatBytes, formatDuration, relativeTime } from "@/lib/api";
import type { Job } from "@/lib/types";
import { DEMO } from "@/lib/types";
import { demoImagePaths, demoJobs, demoQvacCatalog, demoQvacStatus } from "@/lib/demo";
import { useJobsStore } from "@/stores/jobs";
import { useSystemStore } from "@/stores/system";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import TabsBar from "@/components/TabsBar.vue";
import FilePicker from "@/components/FilePicker.vue";
import JobCard from "@/components/JobCard.vue";
import CodeBlock from "@/components/CodeBlock.vue";
import EmptyState from "@/components/EmptyState.vue";
import ProgressBar from "@/components/ProgressBar.vue";

const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false });

const jobs = useJobsStore();
const system = useSystemStore();
const toasts = useToastStore();

const tab = ref("video");
const tabs = [
  { id: "video", label: "Video" },
  { id: "image", label: "Image" },
  { id: "upscale", label: "Upscale" },
];

const catalog = ref<any>(DEMO ? demoQvacCatalog : null);
const status = ref<any>(DEMO ? demoQvacStatus : null);
const busy = ref(false);
const qvacService = computed(() => system.service("qvac"));

const activeVideoId = ref("");
const activeImageId = ref("");
const activeUpscaleId = ref("");
const demoVideoJob = ref<Job | null>(null);
const demoImageJob = ref<Job | null>(null);
const demoUpscaleJob = ref<Job | null>(null);
const demoHistory = ref<Job[]>([]);

const initPicker = ref(false);
const referencePicker = ref(false);
const imageInitPicker = ref(false);
const imageInitMultiPicker = ref(false);
const upscalePicker = ref(false);

/* ------------------------------------------------------------------ */
/* Catalog adapters                                                     */
/* ------------------------------------------------------------------ */

function demoConstraints(id: string): Record<string, any> {
  const key = id.toLowerCase();
  if (key.includes("ltx")) {
    return { dimensionMultipleOf: 32, frames: "8k+1", maxFrames: 257, minFrames: 9, defaultFps: 24, supportsTemporalTiling: true, supportsReferenceConditioning: true };
  }
  if (key.includes("minimax")) {
    return { dimensionMultipleOf: 32, frames: "17k+5", maxFrames: 260, minFrames: 5, fixedFps: 24, defaultFps: 24, rejectsStrength: true };
  }
  if (key.includes("wan22")) {
    return { dimensionMultipleOf: 32, frames: "4k+1", maxFrames: 257, minFrames: 5, defaultFps: 24 };
  }
  return { dimensionMultipleOf: 16, frames: "4k+1", maxFrames: 81, minFrames: 17, defaultFps: 16 };
}

const mockRuntime = computed(() => DEMO || Boolean(status.value?.mock ?? catalog.value?.mock));

function familyInstalled(value: any): boolean {
  if (!value?.install) return true;
  return mockRuntime.value || Boolean(value.install.installed);
}

function modelInstalled(value: any): boolean {
  const installed = value?.installed;
  if (typeof installed === "boolean") return mockRuntime.value || installed;
  return mockRuntime.value || Boolean(value?.available || value?.resolved || value?.mockAvailable);
}

function installedModelsFor(family: string, kind?: string): any[] {
  return (catalog.value?.models || []).filter(
    (model: any) =>
      model.family === family &&
      (!kind || model.kind === kind) &&
      modelInstalled(model),
  );
}

function firstDiffusionModel(family: string, modePart: string): string {
  const models = installedModelsFor(family).filter(
    (model: any) =>
      model.kind === "diffusion" &&
      (!modePart || (model.modes || []).some((mode: string) => mode.includes(modePart))),
  );
  return models[0]?.name || "";
}

const videoFamilies = computed<any[]>(() => {
  if (DEMO) {
    return demoQvacCatalog.families
      .filter((family) => family.id.includes("wan") || family.id.includes("ltx") || family.id.includes("minimax"))
      .map((family) => ({
        key: family.id,
        label: family.name,
        modes: family.id.includes("t2v") && !family.id.includes("ti2v") ? ["txt2vid"] : family.id.includes("i2v") && !family.id.includes("ti2v") ? ["img2vid"] : ["txt2vid", "img2vid"],
        constraints: demoConstraints(family.id),
        params: family.params,
        vram: family.vram,
        installed: family.installed,
        modelSrc: defaultModelForFamily(family.id),
        requires: {},
      }));
  }
  const families = catalog.value?.model_families?.video || {};
  return Object.entries(families)
    .filter(([, value]: [string, any]) => familyInstalled(value))
    .map(([key, value]: [string, any]) => ({
      key,
      label: value.label || key,
      modes: value.modes || ["txt2vid"],
      constraints: value.constraints || {},
      params: "",
      vram: "",
      installed: true,
      modelSrc: firstDiffusionModel(key, "vid"),
      requires: value.requires || {},
      install: value.install || {},
    }));
});

const imageFamilies = computed<any[]>(() => {
  if (DEMO) {
    return [
      { key: "flux2_klein", label: "FLUX.2-klein", modes: ["txt2img", "img2img"], params: "4B", vram: "8 GB", installed: true, modelSrc: "FLUX_2_KLEIN_4B_Q4_0", constraints: { dimensionMultipleOf: 8, supportsUpscale: true }, requires: {} },
      { key: "qwen_image_2_1", label: "Qwen-Image-2.1", modes: ["txt2img", "img2img", "reference"], params: "20B", vram: "16 GB", installed: false, modelSrc: "QWEN_IMAGE_2_1", constraints: { dimensionMultipleOf: 8, supportsUpscale: false }, requires: {} },
      { key: "ideogram4", label: "Ideogram 4", modes: ["txt2img"], params: "9B", vram: "16 GB", installed: false, modelSrc: "IDEOGRAM_4", constraints: { dimensionMultipleOf: 8, supportsUpscale: true }, requires: {} },
      { key: "sd1_sd2", label: "Stable Diffusion 1.x / 2.x", modes: ["txt2img", "img2img"], params: "1B", vram: "4 GB", installed: true, modelSrc: "SD_V2_1_1B_Q8_0", constraints: { dimensionMultipleOf: 8, supportsUpscale: true }, requires: {} },
    ];
  }
  const families = catalog.value?.model_families?.image || {};
  return Object.entries(families)
    .filter(([, value]: [string, any]) => familyInstalled(value) && (value.modes || []).some((mode: string) => mode !== "upscale"))
    .map(([key, value]: [string, any]) => ({
      key,
      label: value.label || key,
      modes: value.modes || [],
      params: "",
      vram: "",
      installed: true,
      modelSrc: firstDiffusionModel(key, "img"),
      constraints: value.constraints || {},
      requires: value.requires || {},
      install: value.install || {},
    }));
});

const upscaleModels = computed<string[]>(() => {
  if (DEMO) return ["REALESRGAN_X4PLUS", "REALESRGAN_X4PLUS_ANIME_6B"];
  const models = (catalog.value?.models || [])
    .filter(
      (model: any) =>
        model.family === "esrgan" &&
        modelInstalled(model) &&
        (model.modes || []).includes("upscale"),
    )
    .map((model: any) => model.name);
  return models;
});

const hasInstalledFamilies = computed(
  () => videoFamilies.value.length > 0 || imageFamilies.value.length > 0 || upscaleModels.value.length > 0,
);
const installedModelCount = computed(() => {
  if (DEMO) return 5;
  return (catalog.value?.models || []).filter((model: any) => modelInstalled(model)).length;
});

function defaultModelForFamily(family: string): string {
  const key = family.toLowerCase();
  if (key.includes("ltx")) return "LTX_2_3_22B_Q5_K_M";
  if (key.includes("minimax")) return "MINIMAX_H3";
  if (key.includes("a14b")) return "WAN2_2_A14B_LOW_NOISE";
  if (key.includes("ti2v")) return "WAN2_2_TI2V_5B_Q5_K_S";
  if (key.includes("i2v")) return "WAN2_1_I2V_14B_Q4_K_M";
  return "WAN2_1_T2V_1_3B_FP16";
}

function defaultImageModel(family: string): string {
  if (family === "flux2_klein") return "FLUX_2_KLEIN_4B_Q4_0";
  if (family === "qwen_image_2_1") return "QWEN_IMAGE_2_1";
  if (family === "ideogram4") return "IDEOGRAM_4";
  if (family === "sdxl_sd3") return "SDXL_BASE_1_0";
  return "SD_V2_1_1B_Q8_0";
}

const videoModelOptions = computed<string[]>(() => {
  if (DEMO) {
    const fallback = ["WAN2_1_T2V_1_3B_FP16", "WAN2_1_I2V_14B_Q4_K_M", "WAN2_2_TI2V_5B_Q5_K_S", "LTX_2_3_22B_Q5_K_M", "MINIMAX_H3"];
    return fallback.includes(video.model) ? fallback : [video.model, ...fallback];
  }
  return installedModelsFor(video.family)
    .filter(
      (model: any) =>
        model.kind === "diffusion" &&
        (model.modes || []).some((mode: string) => mode.includes("vid")),
    )
    .map((model: any) => model.name);
});

const imageModelOptions = computed<string[]>(() => {
  if (DEMO) {
    const fallback = ["FLUX_2_KLEIN_4B_Q4_0", "QWEN_IMAGE_2_1", "IDEOGRAM_4", "SD_V2_1_1B_Q8_0"];
    return fallback.includes(image.model) ? fallback : [image.model, ...fallback];
  }
  return installedModelsFor(image.family)
    .filter(
      (model: any) =>
        model.kind === "diffusion" &&
        (model.modes || []).some((mode: string) => mode.includes("img")),
    )
    .map((model: any) => model.name);
});

/* ------------------------------------------------------------------ */
/* Video form                                                           */
/* ------------------------------------------------------------------ */

const video = reactive({
  family: DEMO ? "wan21-t2v" : "wan2.1_t2v",
  model: "WAN2_1_T2V_1_3B_FP16",
  mode: "txt2vid",
  prompt: "A slow dolly shot through a rain-soaked Lisbon street at 4am, neon reflections on wet cobblestones, cinematic teal and amber grade, volumetric fog, 35mm film grain, shallow depth of field",
  negative_prompt: "blurry, low quality, static, jittery, watermark, text, distorted faces, extra limbs",
  init_image: "",
  width: 480,
  height: 832,
  video_frames: 33,
  fps: 16,
  steps: 30,
  cfg_scale: 6,
  flow_shift: 3,
  seed: 42,
  scheduler: "",
  strength: 0.85,
  reference_images: [] as string[],
  lora: "",
  lora_strength: 1,
  stg_scale: 0,
  stg_block: null as number | null,
  reference_attention_strength: 1,
  reference_downscale_factor: 1,
  temporal_tiling: false,
  vae_tile_size: null as number | null,
  high_noise_steps: null as number | null,
  high_noise_sample_method: "",
  high_noise_scheduler: "",
  high_noise_cfg_scale: null as number | null,
  high_noise_flow_shift: null as number | null,
  moe_boundary: null as number | null,
});

const modelConfig = reactive({
  modelSrc: "WAN2_1_T2V_1_3B_FP16",
  modelType: "sdcpp-generation",
  t5XxlModelSrc: "UMT5_XXL_FP16",
  llmModelSrc: "",
  vaeModelSrc: "WAN_2_1_COMFYUI_REPACKAGED_VAE",
  clipVisionModelSrc: "",
  audioVaeModelSrc: "",
  embeddingsConnectorsModelSrc: "",
  projectionModelSrc: "",
  uncondModelSrc: "",
  highNoiseDiffusionModelSrc: "",
  clipLModelSrc: "",
  clipGModelSrc: "",
  device: "gpu",
  threads: 8,
  offload_to_cpu: true,
  vae_tiling: true,
  backend: "",
  max_vram: "",
  diffusion_fa: true,
  params_backend: "vae=cpu",
  stream_layers: false,
  flash_attn: false,
});

const selectedVideoFamily = computed(() => videoFamilies.value.find((family) => family.key === video.family));
const videoConstraints = computed(() => selectedVideoFamily.value?.constraints || {});
const dimensionMultiple = computed(() => Number(videoConstraints.value.dimensionMultipleOf) || 16);
const frameRule = computed(() => String(videoConstraints.value.frames || "4k+1"));
const frameHint = computed(() => {
  if (frameRule.value === "8k+1") return "8k + 1 frames (9, 17, 25, 33 … max 257)";
  if (frameRule.value === "17k+5") return "17k + 5 frames (5, 22, 39, 56 … max 260)";
  return "4k + 1 frames (5, 9, 13, 17, 21, 25, 29, 33 …)";
});
const fixedFps = computed(() => Number(videoConstraints.value.fixedFps) || 0);
const rejectsStrength = computed(() => Boolean(videoConstraints.value.rejectsStrength) || video.family.toLowerCase().includes("minimax"));
const isLtx = computed(() => video.family.toLowerCase().includes("ltx"));
const isWan22A14b = computed(() => video.family.toLowerCase().includes("a14b"));
const isMinimax = computed(() => video.family.toLowerCase().includes("minimax"));

function onVideoFamilyChange() {
  const family = selectedVideoFamily.value;
  video.model = family?.modelSrc || defaultModelForFamily(video.family);
  modelConfig.modelSrc = video.model;
  if (family?.modes?.length && !family.modes.includes(video.mode)) {
    video.mode = family.modes[0];
  }
  if (video.mode === "img2vid" && !video.init_image) {
    video.init_image = "images/album-art/cover-porcelain-city.png";
  }
  const key = video.family.toLowerCase();
  if (key.includes("ltx")) {
    video.width = 512;
    video.height = 768;
    video.video_frames = 121;
    video.fps = 24;
    video.flow_shift = 3;
    modelConfig.t5XxlModelSrc = "";
    modelConfig.llmModelSrc = "GEMMA_3_12B_Q4_K_XL";
    modelConfig.vaeModelSrc = "LTX_2_3_VIDEO_VAE";
    modelConfig.audioVaeModelSrc = "LTX_2_3_AUDIO_VAE";
    modelConfig.embeddingsConnectorsModelSrc = "LTX_2_3_22B_DISTILLED_EMBEDDINGS_CONNECTORS";
    modelConfig.clipVisionModelSrc = "";
  } else if (key.includes("minimax")) {
    video.width = 512;
    video.height = 768;
    video.video_frames = 39;
    video.fps = 24;
    video.flow_shift = 3;
    modelConfig.t5XxlModelSrc = "";
    modelConfig.llmModelSrc = "QWEN3_VL_8B_TEXT_ENCODER";
    modelConfig.vaeModelSrc = "MINIMAX_H3_VIDEO_VAE";
    modelConfig.audioVaeModelSrc = "MINIMAX_H3_AUDIO_VAE";
    modelConfig.embeddingsConnectorsModelSrc = "";
    modelConfig.clipVisionModelSrc = "";
  } else if (key.includes("i2v") && !key.includes("ti2v")) {
    video.mode = "img2vid";
    video.width = 480;
    video.height = 832;
    video.video_frames = 33;
    video.fps = 16;
    modelConfig.t5XxlModelSrc = "UMT5_XXL_FP16";
    modelConfig.vaeModelSrc = "WAN_2_1_COMFYUI_REPACKAGED_VAE";
    modelConfig.clipVisionModelSrc = "CLIP_VISION_H";
    modelConfig.llmModelSrc = "";
    modelConfig.audioVaeModelSrc = "";
    modelConfig.embeddingsConnectorsModelSrc = "";
    if (!video.init_image) video.init_image = "images/album-art/cover-porcelain-city.png";
  } else {
    video.width = 480;
    video.height = 832;
    video.video_frames = 33;
    video.fps = 16;
    video.flow_shift = key.includes("wan22") ? 5 : 3;
    modelConfig.t5XxlModelSrc = "UMT5_XXL_FP16";
    modelConfig.vaeModelSrc = key.includes("wan22") ? "WAN_2_2_COMFYUI_REPACKAGED_VAE" : "WAN_2_1_COMFYUI_REPACKAGED_VAE";
    modelConfig.clipVisionModelSrc = "";
    modelConfig.llmModelSrc = "";
    modelConfig.audioVaeModelSrc = "";
    modelConfig.embeddingsConnectorsModelSrc = "";
  }
  modelConfig.modelSrc = video.model;
  if (isWan22A14b.value) {
    modelConfig.highNoiseDiffusionModelSrc = "WAN2_2_A14B_HIGH_NOISE";
    modelConfig.t5XxlModelSrc = "UMT5_XXL_FP16";
    modelConfig.vaeModelSrc = "WAN_2_2_COMFYUI_REPACKAGED_VAE";
  }
}

function syncModelSource() {
  modelConfig.modelSrc = video.model;
}

function randomSeed() {
  video.seed = Math.floor(Math.random() * 2_147_483_647);
}

function setVideoInit(path: string) {
  video.init_image = path;
}

function addReferenceImage(path: string) {
  if (video.reference_images.includes(path)) return;
  if (video.reference_images.length >= 8) {
    toasts.error("QVAC accepts at most 8 reference images.");
    return;
  }
  video.reference_images.push(path);
}

function removeReferenceImage(index: number) {
  video.reference_images.splice(index, 1);
}

function compact(values: Record<string, any>): Record<string, any> {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => value !== undefined && value !== null && value !== ""));
}

function modelSourcesFor(family: string, kind: "video" | "image"): Record<string, string> {
  const requires = catalog.value?.model_families?.[kind]?.[family]?.requires || {};
  const result: Record<string, string> = {};
  for (const [field, values] of Object.entries(requires)) {
    if (field === "modelSrc" || !Array.isArray(values)) continue;
    const candidate = values.find(
      (value) => typeof value === "string" && value.trim() && !value.trim().startsWith("<"),
    );
    if (candidate) result[field] = candidate;
  }
  return result;
}

function buildModelConfig(overrides: { modelSrc?: string; family?: string; kind?: string } = {}): Record<string, any> {
  const kind = overrides.kind || "video";
  const family = overrides.family || video.family;
  const config: Record<string, any> = compact({
    modelSrc: overrides.modelSrc || video.model,
    modelType: modelConfig.modelType,
    device: modelConfig.device,
    threads: Number(modelConfig.threads) || undefined,
    diffusion_fa: modelConfig.diffusion_fa,
    offload_to_cpu: modelConfig.offload_to_cpu,
    vae_tiling: modelConfig.vae_tiling,
    backend: modelConfig.backend,
    max_vram: modelConfig.max_vram,
    params_backend: modelConfig.params_backend,
    stream_layers: modelConfig.stream_layers,
    flash_attn: modelConfig.flash_attn,
  });
  if (kind === "video") {
    config.mode = "video";
    const catalogFamily = Boolean(catalog.value?.model_families?.video?.[family]);
    const generatedSources = modelSourcesFor(family, "video");
    Object.assign(
      config,
      catalogFamily
        ? generatedSources
        : compact({
            t5XxlModelSrc: modelConfig.t5XxlModelSrc,
            llmModelSrc: modelConfig.llmModelSrc,
            vaeModelSrc: modelConfig.vaeModelSrc,
            clipVisionModelSrc: modelConfig.clipVisionModelSrc,
            audioVaeModelSrc: modelConfig.audioVaeModelSrc,
            embeddingsConnectorsModelSrc: modelConfig.embeddingsConnectorsModelSrc,
            projectionModelSrc: modelConfig.projectionModelSrc,
            uncondModelSrc: modelConfig.uncondModelSrc,
            highNoiseDiffusionModelSrc: modelConfig.highNoiseDiffusionModelSrc,
            clipLModelSrc: modelConfig.clipLModelSrc,
            clipGModelSrc: modelConfig.clipGModelSrc,
          }),
    );
  }
  if (kind === "upscale") config.mode = "upscale";
  return config;
}

function validateVideo(): string | null {
  if (!selectedVideoFamily.value) return "Install a QVAC video model in Settings → Models first.";
  if (!video.model.trim()) return "Choose an installed QVAC video model.";
  if (!video.prompt.trim()) return "Enter a prompt for the video.";
  if (video.mode === "img2vid" && !video.init_image.trim()) return "img2vid needs an init image.";
  const familyModes = selectedVideoFamily.value?.modes || [];
  if (familyModes.length && !familyModes.includes(video.mode)) return `${selectedVideoFamily.value?.label || video.family} does not support ${video.mode}.`;
  if (video.width > 4096 || video.height > 4096) return "Width and height must be 4096 or less.";
  if (video.width % dimensionMultiple.value !== 0) return `Width must be a multiple of ${dimensionMultiple.value} for this family.`;
  if (video.height % dimensionMultiple.value !== 0) return `Height must be a multiple of ${dimensionMultiple.value} for this family.`;
  if (video.video_frames < 1) return "Frame count must be positive.";
  if (frameRule.value === "4k+1" && (video.video_frames - 1) % 4 !== 0) return "Wan frame counts must satisfy 4k + 1.";
  if (frameRule.value === "8k+1" && ((video.video_frames - 1) % 8 !== 0 || video.video_frames > 257)) return "LTX-2 frames must satisfy 8k + 1 with a maximum of 257.";
  if (frameRule.value === "17k+5" && (video.video_frames - 5) % 17 !== 0) return "MiniMax-H3 frames must satisfy 17k + 5.";
  if (videoConstraints.value.minFrames && video.video_frames < videoConstraints.value.minFrames) return `This family needs at least ${videoConstraints.value.minFrames} frames.`;
  if (videoConstraints.value.maxFrames && video.video_frames > videoConstraints.value.maxFrames) return `This family supports at most ${videoConstraints.value.maxFrames} frames.`;
  if (fixedFps.value && video.fps !== fixedFps.value) return `This family runs at ${fixedFps.value} fps.`;
  if (video.reference_images.length && !isLtx.value) return "Reference image conditioning is only supported by LTX-2.";
  if (video.reference_images.length && !video.lora.trim()) return "LTX-2 reference conditioning needs a LoRA path.";
  if (video.reference_images.length && video.video_frames < 121) return "LTX-2 reference conditioning needs at least 121 frames.";
  if (isMinimax.value && video.mode === "img2vid" && !video.init_image.trim()) return "MiniMax img2vid needs a keyframe image.";
  return null;
}

function buildVideoParams(): Record<string, any> {
  const params: Record<string, any> = compact({
    family: video.family,
    model: video.model,
    mode: video.mode,
    prompt: video.prompt.trim(),
    negative_prompt: video.negative_prompt.trim(),
    init_image: video.mode === "img2vid" ? video.init_image.trim() : undefined,
    width: Number(video.width),
    height: Number(video.height),
    video_frames: Number(video.video_frames),
    fps: Number(video.fps),
    steps: Number(video.steps),
    cfg_scale: Number(video.cfg_scale),
    flow_shift: Number(video.flow_shift),
    seed: Number(video.seed),
    scheduler: video.scheduler.trim() || undefined,
    strength: rejectsStrength.value ? undefined : Number(video.strength),
    lora: video.lora.trim() || undefined,
    lora_strength: Number(video.lora_strength),
    stg_scale: Number(video.stg_scale),
    stg_block: video.stg_block === null ? undefined : Number(video.stg_block),
    reference_attention_strength: Number(video.reference_attention_strength),
    reference_downscale_factor: Number(video.reference_downscale_factor),
    temporal_tiling: video.temporal_tiling,
    vae_tile_size: video.vae_tile_size === null ? undefined : Number(video.vae_tile_size),
    vae_tiling: modelConfig.vae_tiling,
    high_noise_steps: video.high_noise_steps === null ? undefined : Number(video.high_noise_steps),
    high_noise_sample_method: video.high_noise_sample_method.trim() || undefined,
    high_noise_scheduler: video.high_noise_scheduler.trim() || undefined,
    high_noise_cfg_scale: video.high_noise_cfg_scale === null ? undefined : Number(video.high_noise_cfg_scale),
    high_noise_flow_shift: video.high_noise_flow_shift === null ? undefined : Number(video.high_noise_flow_shift),
    moe_boundary: video.moe_boundary === null ? undefined : Number(video.moe_boundary),
    output_format: "both",
    timeout: 86400,
    model_config: buildModelConfig(),
  });
  if (video.reference_images.length) params.reference_images = [...video.reference_images];
  if (!isWan22A14b.value) {
    delete params.high_noise_steps;
    delete params.high_noise_sample_method;
    delete params.high_noise_scheduler;
    delete params.high_noise_cfg_scale;
    delete params.high_noise_flow_shift;
    delete params.moe_boundary;
  }
  return params;
}

/* ------------------------------------------------------------------ */
/* Image form                                                           */
/* ------------------------------------------------------------------ */

const image = reactive({
  family: "flux2_klein",
  model: "FLUX_2_KLEIN_4B_Q4_0",
  prompt: "Porcelain city at dusk, flooded avenue, neon reflections, cinematic wide shot, violet haze, 35mm grain",
  negative_prompt: "blurry, low quality, watermark, text, oversaturated",
  width: 768,
  height: 1024,
  steps: 24,
  guidance: 3.5,
  cfg_scale: 1,
  seed: -1,
  batch_count: 2,
  sampling_method: "euler",
  scheduler: "",
  init_image: "",
  init_images: [] as string[],
  strength: 0.7,
  lora: "",
  lora_strength: 1,
  upscale: true,
  upscaleRepeats: 1,
  output_format: "png",
});

const selectedImageFamily = computed(() => imageFamilies.value.find((family) => family.key === image.family));
const imageDimensionMultiple = computed(() => Number(selectedImageFamily.value?.constraints?.dimensionMultipleOf) || 8);

function onImageFamilyChange() {
  const family = selectedImageFamily.value;
  image.model = family?.modelSrc || defaultImageModel(image.family);
  if (family?.modes?.length && !family.modes.includes("txt2img")) {
    // All image families in this catalog support txt2img at minimum.
  }
}

function randomImageSeed() {
  image.seed = Math.floor(Math.random() * 2_147_483_647);
}

function setImageInit(path: string) {
  image.init_image = path;
}

function addImageInitImage(path: string) {
  if (image.init_images.includes(path)) return;
  if (image.init_images.length >= 8) {
    toasts.error("QVAC accepts at most 8 reference images.");
    return;
  }
  image.init_images.push(path);
}

function removeImageInitImage(index: number) {
  image.init_images.splice(index, 1);
}

function buildImageConfig(): Record<string, any> {
  const fallbackSources: Record<string, Record<string, string>> = {
    flux2_klein: { llmModelSrc: "QWEN3_4B_Q4_K_M", vaeModelSrc: "FLUX_2_KLEIN_4B_VAE" },
  };
  const catalogFamily = Boolean(catalog.value?.model_families?.image?.[image.family]);
  const generatedSources = modelSourcesFor(image.family, "image");
  return compact({
    modelSrc: image.model,
    modelType: "sdcpp-generation",
    device: modelConfig.device,
    threads: Number(modelConfig.threads) || undefined,
    diffusion_fa: modelConfig.diffusion_fa,
    offload_to_cpu: modelConfig.offload_to_cpu,
    vae_tiling: modelConfig.vae_tiling,
    backend: modelConfig.backend,
    max_vram: modelConfig.max_vram,
    prediction: image.family === "flux2_klein" && image.init_image ? "flux2_flow" : undefined,
    ...(catalogFamily ? generatedSources : fallbackSources[image.family] || {}),
  });
}

function validateImage(): string | null {
  if (!selectedImageFamily.value) return "Install a QVAC image model in Settings → Models first.";
  if (!image.model.trim()) return "Choose an installed QVAC image model.";
  if (!image.prompt.trim()) return "Enter an image prompt.";
  if (image.width % imageDimensionMultiple.value !== 0) return `Width must be a multiple of ${imageDimensionMultiple.value}.`;
  if (image.height % imageDimensionMultiple.value !== 0) return `Height must be a multiple of ${imageDimensionMultiple.value}.`;
  if (image.init_image && image.init_images.length) return "init_image and the multi-reference init_images list are mutually exclusive.";
  if (image.init_images.length && image.family !== "qwen_image_2_1") return "Multi-reference init images are only supported by Qwen-Image-2.1.";
  if (image.family === "qwen_image_2_1" && image.upscale) return "Qwen-Image-2.1 produces RGBA and rejects post-generation upscaling.";
  return null;
}

function buildImageParams(): Record<string, any> {
  return compact({
    family: image.family,
    model: image.model,
    prompt: image.prompt.trim(),
    negative_prompt: image.negative_prompt.trim(),
    width: Number(image.width),
    height: Number(image.height),
    steps: Number(image.steps),
    guidance: Number(image.guidance),
    cfg_scale: Number(image.cfg_scale),
    seed: Number(image.seed),
    batch_count: Number(image.batch_count),
    sampling_method: image.sampling_method.trim() || undefined,
    scheduler: image.scheduler.trim() || undefined,
    init_image: image.init_image.trim() || undefined,
    init_images: image.init_images.length ? [...image.init_images] : undefined,
    strength: Number(image.strength),
    lora: image.lora.trim() || undefined,
    lora_strength: Number(image.lora_strength),
    upscale: image.upscale ? { repeats: Number(image.upscaleRepeats) } : false,
    output_format: "png",
    timeout: 86400,
    model_config: buildImageConfig(),
  });
}

/* ------------------------------------------------------------------ */
/* Upscale form                                                         */
/* ------------------------------------------------------------------ */

const upscale = reactive({
  image_path: "images/album-art/cover-porcelain-city.png",
  model: "REALESRGAN_X4PLUS",
  repeats: 2,
  tile_size: 128,
  model_id: "",
});

function setUpscaleImage(path: string) {
  upscale.image_path = path;
}

function validateUpscale(): string | null {
  if (!upscaleModels.value.length || !upscale.model) return "Install the QVAC Real-ESRGAN pack in Settings → Models first.";
  if (!upscale.image_path.trim()) return "Choose an image to upscale.";
  if (upscale.repeats < 1 || upscale.repeats > 4) return "Upscale repeats must be between 1 and 4.";
  return null;
}

function buildUpscaleParams(): Record<string, any> {
  return compact({
    image_path: upscale.image_path.trim(),
    model: upscale.model,
    repeats: Number(upscale.repeats),
    tile_size: Number(upscale.tile_size),
    output_format: "png",
    model_id: upscale.model_id.trim() || undefined,
  });
}

/* ------------------------------------------------------------------ */
/* Jobs                                                                 */
/* ------------------------------------------------------------------ */

const videoJob = computed<Job | null>(() => {
  if (DEMO) return demoVideoJob.value;
  if (activeVideoId.value) return jobs.byId(activeVideoId.value) || null;
  return jobs.items.find((job) => job.component === "qvac" && job.action === "video" && ["queued", "running", "canceling"].includes(job.status)) || null;
});
const imageJob = computed<Job | null>(() => {
  if (DEMO) return demoImageJob.value;
  if (activeImageId.value) return jobs.byId(activeImageId.value) || null;
  return jobs.items.find((job) => job.component === "qvac" && job.action === "image" && ["queued", "running", "canceling"].includes(job.status)) || null;
});
const upscaleJob = computed<Job | null>(() => {
  if (DEMO) return demoUpscaleJob.value;
  if (activeUpscaleId.value) return jobs.byId(activeUpscaleId.value) || null;
  return jobs.items.find((job) => job.component === "qvac" && job.action === "upscale" && ["queued", "running", "canceling"].includes(job.status)) || null;
});

const videoData = computed<any>(() => videoJob.value?.result?.data || null);
const imageData = computed<any>(() => imageJob.value?.result?.data || null);
const upscaleData = computed<any>(() => upscaleJob.value?.result?.data || null);

const videoOutput = computed<string>(() => videoData.value?.primary_file || videoData.value?.paths?.[0] || "");
const videoPoster = computed<string>(() => videoData.value?.poster || (DEMO ? "/demo/film-01.jpg" : ""));
const imagePaths = computed<string[]>(() => {
  const paths = imageData.value?.paths;
  if (Array.isArray(paths) && paths.length) return paths;
  const files = imageJob.value?.result?.files;
  if (Array.isArray(files)) return files.filter((file: any) => file.kind === "image").map((file: any) => file.path);
  return [];
});
const upscalePath = computed<string>(() => upscaleData.value?.paths?.[0] || upscaleJob.value?.result?.files?.[0]?.path || "");
const videoStats = computed<any>(() => videoData.value?.stats || null);
const imageStats = computed<any>(() => imageData.value?.stats || null);
const upscaleStats = computed<any>(() => upscaleData.value?.stats || null);

const activeJobs = computed(() => {
  const list = DEMO
    ? [demoVideoJob.value, demoImageJob.value, demoUpscaleJob.value]
    : jobs.items.filter((job) => job.component === "qvac");
  return list.filter((job): job is Job => Boolean(job && ["queued", "running", "canceling"].includes(job.status)));
});

function isoAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

function cloneJob(job: Job): Job {
  return JSON.parse(JSON.stringify(job));
}

function buildDemoVideoJob(): Job {
  const poster = "/demo/film-01.jpg";
  const output = {
    path: "qvac/demo/film-01.mp4",
    name: "film-01.mp4",
    kind: "video",
    mime: "video/mp4",
    size: 8_412_000,
  };
  return {
    id: "job_qvac_video_01",
    component: "qvac",
    action: "video",
    title: "QVAC · Wan 2.1 T2V · Lisbon rain dolly",
    status: "completed",
    stage: "Complete",
    message: "Generated 33 frames at 480×832 · 2.06s",
    progress: 100,
    params: {
      family: "wan21-t2v",
      mode: "txt2vid",
      prompt: video.prompt,
      width: 480,
      height: 832,
      video_frames: 33,
      fps: 16,
      seed: 42,
    },
    result: {
      message: "Generated 1 video output",
      files: [output],
      data: {
        operation: "video",
        mock: true,
        model_id: "wan21-t2v",
        model: "WAN 2.1 T2V 1.3B",
        family: "wan2.1_t2v",
        mode: "txt2vid",
        prompt: video.prompt,
        width: 480,
        height: 832,
        video_frames: 33,
        fps: 16,
        seed: 42,
        duration_seconds: 2.062,
        output_format: "both",
        primary_file: "qvac/demo/film-01.mp4",
        paths: ["qvac/demo/film-01.mp4"],
        poster,
        stats: { totalSteps: 30, stepMs: 842, denoiseSeconds: 24.8, vaeSeconds: 3.2, peakVramGb: 9.8, tokens: 8_920 },
        warnings: ["Preview generated with deterministic mock weights."],
      },
    },
    error: null,
    warnings: ["Preview generated with deterministic mock weights."],
    artifacts: [{ ...output, path: "qvac/demo/film-01.mp4" }],
    cancel_requested: false,
    attempts: 1,
    created_at: isoAgo(34),
    started_at: isoAgo(34),
    finished_at: isoAgo(32),
    updated_at: isoAgo(32),
  };
}

function buildDemoImageJob(): Job {
  const paths = demoImagePaths.slice(0, 4);
  const files = paths.map((path, index) => ({
    path,
    name: `art-${String(index + 1).padStart(2, "0")}.png`,
    kind: "image",
    mime: "image/png",
    size: 1_820_000 + index * 44_000,
  }));
  return {
    id: "job_qvac_image_01",
    component: "qvac",
    action: "image",
    title: "QVAC · FLUX.2-klein · porcelain city",
    status: "completed",
    stage: "Complete",
    message: "Generated 4 images at 768×1024 · 24 steps",
    progress: 100,
    params: { family: "flux2_klein", prompt: image.prompt, batch_count: 4, steps: 24 },
    result: {
      message: "Generated 4 image(s)",
      files,
      data: {
        operation: "image",
        mock: true,
        model_id: "flux2_klein",
        model: "FLUX.2-klein 4B",
        family: "flux2_klein",
        prompt: image.prompt,
        width: 768,
        height: 1024,
        batch_count: 4,
        seed: 1042,
        upscale: false,
        paths,
        stats: { totalSteps: 24, images: 4, secondsPerImage: 5.4 },
        warnings: ["Preview generated with deterministic mock weights."],
      },
    },
    error: null,
    warnings: ["Preview generated with deterministic mock weights."],
    artifacts: files.slice(0, 2).map((file) => ({ ...file })),
    cancel_requested: false,
    attempts: 1,
    created_at: isoAgo(72),
    started_at: isoAgo(72),
    finished_at: isoAgo(69),
    updated_at: isoAgo(69),
  };
}

function buildDemoUpscaleJob(): Job {
  const output = { path: "/demo/art-05.png", name: "cover-porcelain-city_4x.png", kind: "image", mime: "image/png", size: 8_240_000 };
  return {
    id: "job_qvac_upscale_01",
    component: "qvac",
    action: "upscale",
    title: "QVAC · Real-ESRGAN x4plus · album cover",
    status: "completed",
    stage: "Complete",
    message: "Upscaled 2× passes with 128 px tiles",
    progress: 100,
    params: { image_path: upscale.image_path, model: "REALESRGAN_X4PLUS", repeats: 2 },
    result: {
      message: "Upscaled image 2x",
      files: [output],
      data: {
        operation: "upscale",
        mock: true,
        model_id: "esrgan",
        repeats: 2,
        input: { path: "images/album-art/cover-porcelain-city.png", kind: "image", name: "cover-porcelain-city.png", size: 2_884_301 },
        paths: ["/demo/art-05.png"],
        stats: { tiles: 24, seconds: 12.6 },
        warnings: [],
      },
    },
    error: null,
    warnings: [],
    artifacts: [{ ...output }],
    cancel_requested: false,
    attempts: 1,
    created_at: isoAgo(116),
    started_at: isoAgo(116),
    finished_at: isoAgo(115),
    updated_at: isoAgo(115),
  };
}

onMounted(async () => {
  if (DEMO) {
    demoVideoJob.value = buildDemoVideoJob();
    demoImageJob.value = buildDemoImageJob();
    demoUpscaleJob.value = buildDemoUpscaleJob();
    demoHistory.value = [demoVideoJob.value, demoImageJob.value, demoUpscaleJob.value, ...demoJobs.filter((job) => job.component === "qvac").map(cloneJob)];
    return;
  }
  if (!jobs.items.length) jobs.refresh();
  await refreshRuntime();
});

async function refreshRuntime() {
  busy.value = true;
  try {
    if (DEMO) {
      catalog.value = demoQvacCatalog;
      status.value = demoQvacStatus;
      toasts.info("Demo QVAC runtime refreshed");
      return;
    }
    const [catalogData, statusData] = await Promise.all([
      api.get<any>("/qvac/catalog"),
      api.get<any>("/qvac/status"),
    ]);
    catalog.value = catalogData;
    status.value = statusData;
    const mockMode = Boolean(catalogData?.mock ?? statusData?.mock);
    const installedVideo = Object.entries(catalogData?.model_families?.video || {})
      .filter(([, value]: [string, any]) => !value?.install || mockMode || Boolean(value.install.installed))
      .map(([key]) => key);
    if (!installedVideo.includes(video.family)) {
      const first = installedVideo[0] || "";
      video.family = first;
      if (first) onVideoFamilyChange();
      else video.model = "";
    } else if (!videoModelOptions.value.includes(video.model)) {
      onVideoFamilyChange();
    }
    const installedImages = Object.entries(catalogData?.model_families?.image || {})
      .filter(
        ([, value]: [string, any]) =>
          (!value?.install || mockMode || Boolean(value.install.installed)) &&
          (value?.modes || []).some((mode: string) => mode !== "upscale"),
      )
      .map(([key]) => key);
    if (!installedImages.includes(image.family)) {
      const first = installedImages[0] || "";
      image.family = first;
      if (first) onImageFamilyChange();
      else image.model = "";
    } else if (!imageModelOptions.value.includes(image.model)) {
      onImageFamilyChange();
    }
    const upscalers = (catalogData?.models || [])
      .filter(
        (model: any) =>
          model.family === "esrgan" &&
          (mockMode || typeof model.installed !== "boolean" || model.installed) &&
          (model.modes || []).includes("upscale"),
      )
      .map((model: any) => model.name);
    if (!upscalers.includes(upscale.model)) upscale.model = upscalers[0] || "";
    if (!upscaleModels.value.includes(upscale.model)) upscale.model = upscaleModels.value[0] || "";
  } catch (error: any) {
    toasts.error(error?.message || "Could not load QVAC runtime information");
  } finally {
    busy.value = false;
  }
}

async function generateVideo() {
  const problem = validateVideo();
  if (problem) {
    toasts.error(problem);
    return;
  }
  busy.value = true;
  try {
    const params = buildVideoParams();
    if (DEMO) {
      const job = cloneJob(buildDemoVideoJob());
      job.id = `job_qvac_video_${Date.now().toString(36)}`;
      job.params = params;
      job.title = `QVAC · ${selectedVideoFamily.value?.label || video.family} · ${video.prompt.slice(0, 38)}`;
      job.message = "Demo video generated with the mock renderer.";
      job.result!.data = { ...job.result!.data, prompt: video.prompt, width: video.width, height: video.height, video_frames: video.video_frames, fps: video.fps, seed: video.seed, family: video.family, model: video.model, poster: "/demo/film-01.jpg" };
      job.created_at = isoAgo(0);
      job.started_at = isoAgo(0);
      job.finished_at = new Date().toISOString();
      demoVideoJob.value = job;
      demoHistory.value = [job, ...demoHistory.value.filter((entry) => entry.id !== job.id)];
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      toasts.success("QVAC demo video generated");
      return;
    }
    const job = await api.post<Job>("/qvac/video", { ...params, title: `QVAC · ${selectedVideoFamily.value?.label || video.family} · ${video.prompt.slice(0, 38)}` });
    jobs.upsert(job);
    activeVideoId.value = job.id;
    toasts.success("QVAC video job queued");
  } catch (error: any) {
    toasts.error(error?.message || "Could not start video generation");
  } finally {
    busy.value = false;
  }
}

async function generateImage() {
  const problem = validateImage();
  if (problem) {
    toasts.error(problem);
    return;
  }
  busy.value = true;
  try {
    const params = buildImageParams();
    if (DEMO) {
      const job = cloneJob(buildDemoImageJob());
      job.id = `job_qvac_image_${Date.now().toString(36)}`;
      job.params = params;
      job.title = `QVAC · ${selectedImageFamily.value?.label || image.family} · ${image.prompt.slice(0, 38)}`;
      job.message = "Demo image batch generated with the mock renderer.";
      job.result!.data = { ...job.result!.data, prompt: image.prompt, width: image.width, height: image.height, batch_count: image.batch_count, seed: image.seed, family: image.family, model: image.model, paths: demoImagePaths.slice(0, Math.max(1, Math.min(image.batch_count, 8))) };
      job.result!.files = job.result!.data.paths.map((path: string, index: number) => ({ path, name: `art-${index + 1}.png`, kind: "image", mime: "image/png", size: 1_900_000 }));
      job.created_at = isoAgo(0);
      job.started_at = isoAgo(0);
      job.finished_at = new Date().toISOString();
      demoImageJob.value = job;
      demoHistory.value = [job, ...demoHistory.value.filter((entry) => entry.id !== job.id)];
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      toasts.success("QVAC demo image batch generated");
      return;
    }
    const job = await api.post<Job>("/qvac/image", { ...params, title: `QVAC · ${selectedImageFamily.value?.label || image.family} · ${image.prompt.slice(0, 38)}` });
    jobs.upsert(job);
    activeImageId.value = job.id;
    toasts.success("QVAC image job queued");
  } catch (error: any) {
    toasts.error(error?.message || "Could not start image generation");
  } finally {
    busy.value = false;
  }
}

async function generateUpscale() {
  const problem = validateUpscale();
  if (problem) {
    toasts.error(problem);
    return;
  }
  busy.value = true;
  try {
    const params = buildUpscaleParams();
    if (DEMO) {
      const job = cloneJob(buildDemoUpscaleJob());
      job.id = `job_qvac_upscale_${Date.now().toString(36)}`;
      job.params = params;
      job.title = `QVAC · Real-ESRGAN · ${upscale.image_path.split("/").pop()}`;
      job.message = `Demo upscale completed ${upscale.repeats}×.`;
      job.result!.data = { ...job.result!.data, repeats: upscale.repeats, input: { path: upscale.image_path, kind: "image", name: upscale.image_path.split("/").pop(), size: 2_884_301 }, paths: ["/demo/art-05.png"] };
      job.created_at = isoAgo(0);
      job.started_at = isoAgo(0);
      job.finished_at = new Date().toISOString();
      demoUpscaleJob.value = job;
      demoHistory.value = [job, ...demoHistory.value.filter((entry) => entry.id !== job.id)];
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      toasts.success("QVAC demo upscale completed");
      return;
    }
    const job = await api.post<Job>("/qvac/upscale", { ...params, title: `QVAC · Real-ESRGAN · ${upscale.image_path.split("/").pop()}` });
    jobs.upsert(job);
    activeUpscaleId.value = job.id;
    toasts.success("QVAC upscale job queued");
  } catch (error: any) {
    toasts.error(error?.message || "Could not start upscaling");
  } finally {
    busy.value = false;
  }
}

async function cancelJob(id: string) {
  if (DEMO) {
    for (const target of [demoVideoJob, demoImageJob, demoUpscaleJob]) {
      if (target.value?.id === id) target.value = { ...target.value, status: "canceled", message: "Cancelled by the user." };
    }
    toasts.info("Demo job cancelled");
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
    if (found) {
      const running: Job = { ...cloneJob(found), status: "running", progress: 12, message: "Re-queued in demo mode." };
      if (running.action === "video") demoVideoJob.value = running;
      else if (running.action === "image") demoImageJob.value = running;
      else demoUpscaleJob.value = running;
    }
    toasts.info("Demo job restarted");
    return;
  }
  try {
    const job = await jobs.retry(id);
    if (job.action === "video") activeVideoId.value = job.id;
    else if (job.action === "image") activeImageId.value = job.id;
    else activeUpscaleId.value = job.id;
    toasts.success("Job restarted");
  } catch (error: any) {
    toasts.error(error?.message || "Could not retry the job");
  }
}

async function removeJob(id: string) {
  if (DEMO) {
    demoHistory.value = demoHistory.value.filter((entry) => entry.id !== id);
    if (demoVideoJob.value?.id === id) demoVideoJob.value = null;
    if (demoImageJob.value?.id === id) demoImageJob.value = null;
    if (demoUpscaleJob.value?.id === id) demoUpscaleJob.value = null;
    toasts.success("Demo job removed");
    return;
  }
  try {
    await jobs.remove(id);
    if (activeVideoId.value === id) activeVideoId.value = "";
    if (activeImageId.value === id) activeImageId.value = "";
    if (activeUpscaleId.value === id) activeUpscaleId.value = "";
    toasts.success("Job record removed");
  } catch (error: any) {
    toasts.error(error?.message || "Could not remove the job");
  }
}

/* ------------------------------------------------------------------ */
/* Runtime status and model catalog                                     */
/* ------------------------------------------------------------------ */

const sdkVersion = computed(() => {
  if (!status.value) return catalog.value?.version || "0.23.0";
  const sdk = status.value.sdk;
  if (typeof sdk === "string") return sdk;
  return status.value.sdk_declared_version || sdk?.sdk_version || sdk?.version || catalog.value?.version || "0.23.0";
});
const deviceLabel = computed(() => String(status.value?.device || catalog.value?.device || "gpu").toUpperCase());
const isMock = computed(() => DEMO || Boolean(status.value?.mock ?? catalog.value?.mock));
const backendLabel = computed(() => {
  if (status.value?.backend) return String(status.value.backend);
  if (isMock.value) return "Mock · deterministic renderer";
  if (status.value?.sdk?.available) return "Tether QVAC SDK";
  return "Tether QVAC SDK · unavailable";
});
const loadedModel = computed<any>(() => {
  const loaded = status.value?.loaded_models?.[0] || status.value?.loaded || null;
  if (!loaded) return null;
  return {
    raw: loaded,
    id: loaded.model_id || loaded.modelId || loaded.id || loaded.name || "loaded",
    name: loaded.model || loaded.name || loaded.model_id || "Loaded model",
    family: loaded.family || loaded.model_id || loaded.id || "",
    kind: loaded.kind || loaded.mode || "video",
    mock: loaded.mock,
  };
});
const memoryInfo = computed(() => {
  const memory = status.value?.memory;
  if (!memory) return { label: "—", percent: 0, detail: "Memory telemetry unavailable" };
  if (typeof memory.total_gb === "number") {
    const used = Number(memory.used_gb ?? memory.used ?? 0);
    return { label: `${used.toFixed(1)} / ${memory.total_gb} GB`, percent: Math.min(100, (used / memory.total_gb) * 100), detail: memory.unified ? "Unified memory" : "GPU memory" };
  }
  if (memory.gpu?.totalGb) {
    const total = Number(memory.gpu.totalGb);
    const free = Number(memory.gpu.freeGb || 0);
    const used = Math.max(0, total - free);
    return { label: `${used.toFixed(1)} / ${total} GB`, percent: Math.min(100, (used / total) * 100), detail: memory.gpu.devices?.[0]?.name || "GPU memory" };
  }
  if (memory.system?.totalGb) {
    const total = Number(memory.system.totalGb);
    const free = Number(memory.system.freeGb || 0);
    const used = Math.max(0, total - free);
    return { label: `${used.toFixed(1)} / ${total} GB`, percent: Math.min(100, (used / total) * 100), detail: "System memory" };
  }
  return { label: "—", percent: 0, detail: "Memory telemetry unavailable" };
});

const statusRequirements = computed(() => status.value?.requirements || {});
const hardwareNote = computed(
  () =>
    catalog.value?.constraints?.hardware?.note ||
    statusRequirements.value?.note ||
    "QVAC video generation requires at least 16 GB of VRAM or 20 GB of unified memory. Wan 2.1 T2V 1.3B runs from 8 GB; 14B/22B families need more.",
);

const activeJobCount = computed(() => activeJobs.value.length);

function resultUrl(path?: string | null): string {
  if (!path) return "";
  if (/^(https?:|data:|blob:|\/demo\/|\/api\/)/.test(path)) return path;
  return fileUrl(path);
}

function downloadFor(path?: string | null): string {
  if (!path) return "";
  if (/^(https?:|data:|blob:|\/demo\/)/.test(path)) return path;
  return downloadUrl(path);
}

function promptShort(value?: string | null): string {
  if (!value) return "—";
  return value.length > 90 ? `${value.slice(0, 90)}…` : value;
}

function resultMeta(job: Job | null): Array<{ label: string; value: string }> {
  if (!job?.result?.data) return [];
  const data = job.result.data;
  return [
    { label: "Model", value: data.model || data.model_id || "—" },
    { label: "Family", value: data.family || "—" },
    { label: "Resolution", value: data.width && data.height ? `${data.width} × ${data.height}` : "—" },
    { label: "Frames", value: data.video_frames ? `${data.video_frames} @ ${data.fps || "—"} fps` : "—" },
    { label: "Duration", value: data.duration_seconds ? formatDuration(data.duration_seconds) : "—" },
    { label: "Seed", value: data.seed !== undefined && data.seed !== null ? String(data.seed) : "—" },
    { label: "Batch", value: data.batch_count ? String(data.batch_count) : data.repeats ? `${data.repeats}×` : "—" },
  ];
}
</script>

<template>
  <div class="page qvac-page" :class="{ 'qvac-embedded': embedded }">
    <PageHeader
      v-if="!embedded"
      eyebrow="Local video generation · Tether QVAC SDK · own Docker image"
      title="QVAC video"
      subtitle="Text-to-video and image-to-video with Wan 2.1/2.2, LTX-2 and MiniMax-H3, plus QVAC image diffusion and ESRGAN upscaling. Model packs are installed in Settings → Models; this page picks from the installed packs and executes inside the QVAC Docker image."
    >
      <template #actions>
        <span class="chip" :class="qvacService?.online ? 'success' : ''">
          <span class="dot" :class="qvacService?.online ? 'online' : 'busy'" />
          {{ qvacService?.online ? "QVAC online" : "QVAC runtime" }}
        </span>
        <span class="chip"><Sparkles :size="11" /> SDK {{ sdkVersion }}</span>
        <span class="chip" :class="isMock ? 'warn' : 'success'">{{ isMock ? "mock" : "real" }}</span>
        <button class="btn btn-sm" :disabled="busy" @click="refreshRuntime"><RefreshCw :size="13" :class="{ spin: busy }" /> Refresh</button>
      </template>
    </PageHeader>

    <!-- Runtime status ------------------------------------------------- -->
    <section class="panel status-panel">
      <div class="panel-head">
        <div class="row" style="gap: 11px; min-width: 0">
          <span class="file-icon" style="width: 40px; height: 40px"><Cpu :size="19" /></span>
          <div style="min-width: 0">
            <h3>QVAC runtime</h3>
            <p>{{ isMock ? "Deterministic mock renderer · safe preview mode" : "Tether QVAC SDK · native Vulkan / CPU execution" }}</p>
          </div>
        </div>
        <div class="row" style="gap: 7px">
          <span class="badge" :class="isMock ? 'warn' : 'success'">{{ isMock ? "mock mode" : "real SDK" }}</span>
          <span class="badge" :class="loadedModel ? 'success' : 'queued'">{{ loadedModel ? "model loaded" : "idle" }}</span>
        </div>
      </div>
      <div class="panel-body">
        <div class="status-grid">
          <div class="status-cell">
            <span class="status-label"><Cpu :size="12" /> Device</span>
            <strong>{{ deviceLabel }}</strong>
            <span class="status-sub">{{ backendLabel }}</span>
          </div>
          <div class="status-cell">
            <span class="status-label"><MemoryStick :size="12" /> Memory</span>
            <strong>{{ memoryInfo.label }}</strong>
            <ProgressBar :value="memoryInfo.percent" thin style="margin-top: 6px" />
            <span class="status-sub">{{ memoryInfo.detail }}</span>
          </div>
          <div class="status-cell">
            <span class="status-label"><Boxes :size="12" /> Loaded model</span>
            <strong class="truncate">{{ loadedModel?.name || "No model loaded" }}</strong>
            <span class="status-sub mono">{{ loadedModel ? `${loadedModel.id} · ${loadedModel.family}` : "Loads automatically from the selected installed pack" }}</span>
          </div>
          <div class="status-cell">
            <span class="status-label"><Server :size="12" /> SDK</span>
            <strong>{{ sdkVersion }}</strong>
            <span class="status-sub">{{ isMock ? "Mock weights · no native load" : "Tether QVAC · @qvac/sdk" }}</span>
          </div>
          <div class="status-cell">
            <span class="status-label"><CircleGauge :size="12" /> Active jobs</span>
            <strong>{{ activeJobCount }}</strong>
            <span class="status-sub">{{ status?.queue ? `${status.queue.running || 0} running · ${status.queue.queued || 0} queued` : "Global QVAC queue" }}</span>
          </div>
          <div class="status-cell">
            <span class="status-label"><Film :size="12" /> Installed</span>
            <strong>{{ videoFamilies.length }} video · {{ imageFamilies.length }} image</strong>
            <span class="status-sub">{{ installedModelCount }} model assets ready</span>
          </div>
        </div>
      </div>
    </section>

    <div v-if="!hasInstalledFamilies && !mockRuntime" class="alert warn" style="margin-top: 14px">
      <strong>No QVAC models installed.</strong>
      Install QVAC model packs in
      <RouterLink to="/settings?tab=models">Settings → Models</RouterLink>
      before generating video, images or upscales.
    </div>

    <div class="row-between" style="margin: 16px 0 14px; flex-wrap: wrap; gap: 10px">
      <TabsBar v-model="tab" :tabs="tabs" />
      <div class="row" style="gap: 7px">
        <span class="chip" :class="isMock ? 'warn' : 'success'">{{ isMock ? "Mock outputs are deterministic" : "Native SDK execution" }}</span>
        <span class="chip"><Shield :size="11" /> Private · local</span>
        <span class="chip"><Layers :size="11" /> {{ modelConfig.vae_tiling ? "VAE tiling on" : "VAE tiling off" }}</span>
      </div>
    </div>

    <!-- Video tab ------------------------------------------------------ -->
    <div v-if="tab === 'video'" class="qvac-layout">
      <section class="panel">
        <div class="panel-head">
          <div><h3>Video generation</h3><p>Wan 2.1/2.2 · LTX-2 · MiniMax-H3 · all diffusion / reference controls.</p></div>
          <span class="chip"><Video :size="11" /> {{ selectedVideoFamily?.label || video.family }}</span>
        </div>
        <div class="panel-body stack">
          <div class="form-grid">
            <div class="field">
              <label>Installed model pack</label>
              <select v-model="video.family" class="select" :disabled="!videoFamilies.length" @change="onVideoFamilyChange">
                <option v-if="!videoFamilies.length" value="">No QVAC video packs installed</option>
                <option v-for="family in videoFamilies" :key="family.key" :value="family.key">{{ family.label }}</option>
              </select>
              <span class="hint">{{ selectedVideoFamily?.params || "SDK constant" }} · {{ selectedVideoFamily?.vram || "VRAM varies" }} · {{ (selectedVideoFamily?.modes || []).join(" / ") }}</span>
            </div>
            <div class="field">
              <label>Diffusion model</label>
              <select v-model="video.model" class="select" :disabled="!videoModelOptions.length" @change="syncModelSource">
                <option v-if="!videoModelOptions.length" value="">No installed model</option>
                <option v-for="model in videoModelOptions" :key="model" :value="model">{{ model }}</option>
              </select>
              <span class="hint">Only models installed from Settings → Models are listed here.</span>
            </div>
          </div>

          <div class="field">
            <label>Prompt</label>
            <textarea v-model="video.prompt" class="textarea" style="min-height: 92px" placeholder="Describe the shot, camera movement, light and grade…" />
            <span class="hint">{{ video.prompt.length }} chars · shared files and prompts stay local</span>
          </div>
          <div class="field">
            <label>Negative prompt</label>
            <textarea v-model="video.negative_prompt" class="textarea" style="min-height: 56px" placeholder="blurry, low quality, watermark…" />
          </div>

          <div class="mode-row">
            <div class="segmented">
              <button class="seg" :class="{ active: video.mode === 'txt2vid' }" :disabled="!((selectedVideoFamily?.modes || []).includes('txt2vid'))" @click="video.mode = 'txt2vid'">txt2vid</button>
              <button class="seg" :class="{ active: video.mode === 'img2vid' }" :disabled="!((selectedVideoFamily?.modes || []).includes('img2vid'))" @click="video.mode = 'img2vid'">img2vid</button>
            </div>
            <span class="small muted">{{ video.mode === "txt2vid" ? "Prompt-only generation" : "Animate a keyframe image" }}</span>
          </div>

          <div class="field" v-if="video.mode === 'img2vid'">
            <label>Init image <span class="muted small">first frame</span></label>
            <div class="input-group">
              <input v-model="video.init_image" class="input mono" placeholder="images/keyframe.png" />
              <button class="btn btn-sm" @click="initPicker = true">Browse</button>
            </div>
            <div v-if="video.init_image" class="image-peek">
              <img :src="resultUrl(video.init_image)" alt="" />
              <span class="small muted mono">{{ video.init_image }}</span>
            </div>
          </div>

          <div class="form-grid">
            <div class="field"><label>Width</label><input v-model.number="video.width" type="number" class="input" /><span class="hint">Multiple of {{ dimensionMultiple }} · max 4096</span></div>
            <div class="field"><label>Height</label><input v-model.number="video.height" type="number" class="input" /><span class="hint">Multiple of {{ dimensionMultiple }} · max 4096</span></div>
            <div class="field"><label>Video frames</label><input v-model.number="video.video_frames" type="number" min="1" class="input" /><span class="hint">{{ frameHint }}</span></div>
            <div class="field"><label>FPS</label><input v-model.number="video.fps" type="number" min="1" max="120" class="input" :disabled="Boolean(fixedFps)" /><span class="hint">{{ fixedFps ? `Fixed at ${fixedFps} fps for this family` : "1–120 fps" }}</span></div>
            <div class="field"><label>Steps</label><input v-model.number="video.steps" type="number" min="1" max="200" class="input" /></div>
            <div class="field"><label>Seed</label><div class="input-group"><input v-model.number="video.seed" type="number" min="-1" class="input" /><button class="btn btn-sm" title="Random seed" @click="randomSeed"><Shuffle :size="13" /></button></div><span class="hint">-1 means random</span></div>
            <div class="field"><label>CFG scale</label><input v-model.number="video.cfg_scale" type="number" min="0" max="30" step="0.1" class="input" /></div>
            <div class="field"><label>Flow shift</label><input v-model.number="video.flow_shift" type="number" min="0" max="20" step="0.1" class="input" /></div>
            <div class="field"><label>Scheduler</label><input v-model="video.scheduler" class="input" placeholder="SDK default, or ltx2" /></div>
            <div class="field"><label>Strength <span class="muted small">img2vid</span></label><input v-model.number="video.strength" type="number" min="0" max="1" step="0.01" class="input" :disabled="rejectsStrength" /><span class="hint">{{ rejectsStrength ? "MiniMax-H3 rejects strength" : "SDEdit denoise strength" }}</span></div>
          </div>

          <div class="option-block">
            <div class="option-title"><ImageIcon :size="13" /> Reference conditioning</div>
            <div class="field">
              <label>Reference images <span class="muted small">{{ video.reference_images.length }}/8 · LTX-2 IC-LoRA</span></label>
              <div class="stack" style="gap: 5px">
                <div v-for="(path, index) in video.reference_images" :key="path" class="mini-file-row">
                  <ImageIcon :size="13" />
                  <span class="small mono truncate grow">{{ path }}</span>
                  <button class="icon-btn" @click="removeReferenceImage(index)"><Trash2 :size="13" /></button>
                </div>
                <button class="btn btn-sm" style="align-self: flex-start" @click="referencePicker = true"><Plus :size="12" /> Add reference image</button>
              </div>
              <span class="hint">LTX-2 only. Requires a LoRA path and a scheduler of “ltx2”.</span>
            </div>
            <div class="form-grid">
              <div class="field"><label>LoRA path</label><input v-model="video.lora" class="input mono" placeholder="models/loras/ltx2-ic-lora.safetensors" /></div>
              <div class="field"><label>LoRA strength</label><input v-model.number="video.lora_strength" type="number" min="-10" max="10" step="0.05" class="input" /></div>
              <div class="field"><label>Reference attention</label><input v-model.number="video.reference_attention_strength" type="number" min="0" max="10" step="0.1" class="input" /><span class="hint">How strongly the output follows the reference.</span></div>
              <div class="field"><label>Reference downscale</label><input v-model.number="video.reference_downscale_factor" type="number" min="1" max="16" class="input" /><span class="hint">LTX-2 requires 1.</span></div>
            </div>
          </div>

          <div class="option-block">
            <div class="option-title"><SlidersHorizontal :size="13" /> Guidance, tiling & memory</div>
            <div class="form-grid">
              <div class="field"><label>STG scale</label><input v-model.number="video.stg_scale" type="number" step="0.1" class="input" /></div>
              <div class="field"><label>STG block</label><input v-model.number="video.stg_block" type="number" min="0" class="input" placeholder="SDK default" /></div>
              <div class="field"><label>VAE tile size</label><input v-model.number="video.vae_tile_size" type="number" min="1" max="128" class="input" placeholder="Auto" /><span class="hint">Used by temporal tiling.</span></div>
              <div class="field"><label>Temporal tiling</label><button class="switch" :class="{ on: video.temporal_tiling }" style="align-self: flex-start" @click="video.temporal_tiling = !video.temporal_tiling" /><span class="hint">LTX-2 only; caps peak VRAM.</span></div>
            </div>
          </div>

          <details class="option-block" :open="isWan22A14b">
            <summary class="option-title" style="cursor: pointer; list-style: none"><Layers :size="13" /> Dual-expert / high-noise controls <span class="small muted" style="text-transform: none; letter-spacing: 0">Wan 2.2 A14B only</span><ChevronDown :size="14" style="margin-left: auto" /></summary>
            <div class="form-grid" style="margin-top: 9px">
              <div class="field"><label>High-noise steps</label><input v-model.number="video.high_noise_steps" type="number" min="1" max="200" class="input" placeholder="Low-noise steps" /></div>
              <div class="field"><label>High-noise sampler</label><input v-model="video.high_noise_sample_method" class="input" placeholder="euler / dpmpp" /></div>
              <div class="field"><label>High-noise scheduler</label><input v-model="video.high_noise_scheduler" class="input" placeholder="SDK default" /></div>
              <div class="field"><label>High-noise CFG</label><input v-model.number="video.high_noise_cfg_scale" type="number" step="0.1" class="input" placeholder="Same as CFG" /></div>
              <div class="field"><label>High-noise flow shift</label><input v-model.number="video.high_noise_flow_shift" type="number" step="0.1" class="input" placeholder="Same as flow shift" /></div>
              <div class="field"><label>MoE boundary</label><input v-model.number="video.moe_boundary" type="number" min="0" max="1" step="0.01" class="input" placeholder="Auto" /></div>
            </div>
          </details>

          <details class="option-block">
            <summary class="option-title" style="cursor: pointer; list-style: none"><SlidersHorizontal :size="13" /> Runtime configuration <span class="small muted" style="text-transform: none; letter-spacing: 0">device · memory · tiling</span><ChevronDown :size="14" style="margin-left: auto" /></summary>
            <div class="form-grid" style="margin-top: 10px">
              <div class="field"><label>Device</label><select v-model="modelConfig.device" class="select"><option value="gpu">gpu</option><option value="cpu">cpu</option></select></div>
              <div class="field"><label>Threads</label><input v-model.number="modelConfig.threads" type="number" min="1" max="128" class="input" /></div>
              <div class="field"><label>Backend</label><input v-model="modelConfig.backend" class="input mono" placeholder="SDK auto" /></div>
              <div class="field"><label>Max VRAM</label><input v-model="modelConfig.max_vram" class="input mono" placeholder="e.g. 12G" /></div>
              <div class="field"><label>Params backend</label><input v-model="modelConfig.params_backend" class="input mono" placeholder="vae=cpu" /></div>
              <div class="field"><label>Flash attention</label><button class="switch" :class="{ on: modelConfig.diffusion_fa }" style="align-self: flex-start" @click="modelConfig.diffusion_fa = !modelConfig.diffusion_fa" /></div>
              <div class="field"><label>Offload to CPU</label><button class="switch" :class="{ on: modelConfig.offload_to_cpu }" style="align-self: flex-start" @click="modelConfig.offload_to_cpu = !modelConfig.offload_to_cpu" /></div>
              <div class="field"><label>VAE tiling</label><button class="switch" :class="{ on: modelConfig.vae_tiling }" style="align-self: flex-start" @click="modelConfig.vae_tiling = !modelConfig.vae_tiling" /></div>
              <div class="field"><label>Stream layers</label><button class="switch" :class="{ on: modelConfig.stream_layers }" style="align-self: flex-start" @click="modelConfig.stream_layers = !modelConfig.stream_layers" /></div>
              <div class="field"><label>Flash attention (Qwen)</label><button class="switch" :class="{ on: modelConfig.flash_attn }" style="align-self: flex-start" @click="modelConfig.flash_attn = !modelConfig.flash_attn" /></div>
            </div>
          </details>

          <div class="row-between" style="flex-wrap: wrap; gap: 8px">
            <div class="row" style="gap: 7px">
              <span class="chip">{{ video.width }} × {{ video.height }}</span>
              <span class="chip">{{ video.video_frames }} frames</span>
              <span class="chip">{{ video.steps }} steps</span>
              <span class="chip">{{ video.mode }}</span>
            </div>
            <button class="btn btn-primary btn-lg" :disabled="busy || !videoFamilies.length || !videoModelOptions.length" @click="generateVideo">
              <Loader2 v-if="busy" :size="15" class="spin" />
              <Wand2 v-else :size="15" />
              {{ busy ? "Submitting…" : "Generate video" }}
            </button>
          </div>
        </div>
      </section>

      <aside class="stack">
        <section class="panel">
          <div class="panel-head"><div><h3>Video job</h3><p>{{ videoJob ? videoJob.title : "Ready to generate" }}</p></div><span class="badge" :class="videoJob?.status || 'queued'">{{ videoJob?.status || "idle" }}</span></div>
          <div class="panel-body stack">
            <JobCard v-if="videoJob" :job="videoJob" @cancel="cancelJob" @retry="retryJob" @remove="removeJob" />
            <div v-else class="empty" style="padding: 24px"><MonitorPlay :size="27" style="opacity: .45; margin-bottom: 7px" /><h3>No video yet</h3><p>Describe a shot, choose a family and generate. Progress reports every step from the QVAC worker.</p></div>
            <div v-if="videoOutput || videoPoster" class="video-preview">
              <video v-if="videoOutput && !DEMO" :src="fileUrl(videoOutput)" controls preload="metadata" class="preview-media" />
              <img v-else :src="resultUrl(videoPoster)" alt="" class="preview-media" />
              <div class="preview-overlay">
                <span class="chip" :class="isMock ? 'warn' : 'success'">{{ isMock ? "mock preview" : "generated" }}</span>
                <span v-if="videoOutput" class="chip mono">{{ videoOutput.split("/").pop() }}</span>
              </div>
            </div>
            <div v-if="videoJob?.result" class="row" style="gap: 6px">
              <a v-if="videoOutput || videoPoster" class="btn btn-sm" :href="downloadFor(DEMO ? videoPoster : videoOutput)" target="_blank" rel="noopener"><Download :size="12" /> Download {{ DEMO ? "preview still" : "video" }}</a>
              <a v-if="videoData?.poster" class="btn btn-sm btn-ghost" :href="resultUrl(videoData.poster)" target="_blank" rel="noopener"><ImageIcon :size="12" /> Poster</a>
            </div>
            <div v-if="videoJob?.result" class="meta-table">
              <div v-for="row in resultMeta(videoJob)" :key="row.label" class="meta-row"><span>{{ row.label }}</span><strong class="truncate">{{ row.value }}</strong></div>
            </div>
            <details v-if="videoStats" class="extra-box">
              <summary><span><Gauge :size="12" /> Generation stats</span><ChevronDown :size="13" /></summary>
              <CodeBlock :code="JSON.stringify(videoStats, null, 2)" label="SDK stats" />
            </details>
            <div class="alert" v-if="isMock">Mock mode never touches native libraries. Set <span class="mono">QVAC_MOCK=0</span> with the QVAC SDK and model files present for real generation.</div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div><h3>Runtime notes</h3><p>QVAC constraints</p></div><span class="chip">{{ sdkVersion }}</span></div>
          <div class="panel-body stack" style="gap: 8px">
            <div class="row-between small"><span class="muted">Width / height</span><span>multiple of {{ dimensionMultiple }}</span></div>
            <div class="row-between small"><span class="muted">Frames</span><span>{{ frameRule }}</span></div>
            <div class="row-between small"><span class="muted">Strength</span><span>{{ rejectsStrength ? "rejected by this family" : "0.0 – 1.0" }}</span></div>
            <div class="row-between small"><span class="muted">Reference images</span><span>LTX-2 · max 8</span></div>
            <div class="row-between small"><span class="muted">Output</span><span>AVI buffer + MP4 transcode</span></div>
            <div class="alert warn" style="margin-top: 3px">{{ hardwareNote }}</div>
          </div>
        </section>
      </aside>
    </div>

    <!-- Image tab ------------------------------------------------------ -->
    <div v-else-if="tab === 'image'" class="qvac-layout">
      <section class="panel">
        <div class="panel-head">
          <div><h3>Image diffusion</h3><p>FLUX.2-klein · Qwen-Image · Ideogram · SDXL/SD · txt2img, img2img and reference edits.</p></div>
          <span class="chip"><ImageIcon :size="11" /> {{ selectedImageFamily?.label || image.family }}</span>
        </div>
        <div class="panel-body stack">
          <div class="form-grid">
            <div class="field"><label>Installed model pack</label><select v-model="image.family" class="select" :disabled="!imageFamilies.length" @change="onImageFamilyChange"><option v-if="!imageFamilies.length" value="">No QVAC image packs installed</option><option v-for="family in imageFamilies" :key="family.key" :value="family.key">{{ family.label }}</option></select><span class="hint">{{ (selectedImageFamily?.modes || []).join(" / ") }}</span></div>
            <div class="field"><label>Diffusion model</label><select v-model="image.model" class="select" :disabled="!imageModelOptions.length"><option v-if="!imageModelOptions.length" value="">No installed model</option><option v-for="model in imageModelOptions" :key="model" :value="model">{{ model }}</option></select></div>
          </div>
          <div class="field"><label>Prompt</label><textarea v-model="image.prompt" class="textarea" style="min-height: 82px" /></div>
          <div class="field"><label>Negative prompt</label><textarea v-model="image.negative_prompt" class="textarea" style="min-height: 52px" /></div>
          <div class="form-grid">
            <div class="field"><label>Width</label><input v-model.number="image.width" type="number" class="input" /><span class="hint">Multiple of {{ imageDimensionMultiple }}</span></div>
            <div class="field"><label>Height</label><input v-model.number="image.height" type="number" class="input" /><span class="hint">Multiple of {{ imageDimensionMultiple }}</span></div>
            <div class="field"><label>Steps</label><input v-model.number="image.steps" type="number" min="1" max="200" class="input" /></div>
            <div class="field"><label>Guidance</label><input v-model.number="image.guidance" type="number" min="0" max="30" step="0.1" class="input" /></div>
            <div class="field"><label>CFG scale</label><input v-model.number="image.cfg_scale" type="number" min="0" max="30" step="0.1" class="input" /></div>
            <div class="field"><label>Seed</label><div class="input-group"><input v-model.number="image.seed" type="number" min="-1" class="input" /><button class="btn btn-sm" @click="randomImageSeed"><Shuffle :size="13" /></button></div></div>
            <div class="field"><label>Batch count</label><input v-model.number="image.batch_count" type="number" min="1" max="8" class="input" /></div>
            <div class="field"><label>Sampling method</label><input v-model="image.sampling_method" class="input" placeholder="euler / dpmpp" /></div>
            <div class="field"><label>Scheduler</label><input v-model="image.scheduler" class="input" placeholder="SDK default" /></div>
            <div class="field"><label>Strength</label><input v-model.number="image.strength" type="number" min="0" max="1" step="0.01" class="input" /></div>
          </div>

          <div class="option-block">
            <div class="option-title"><ImageIcon :size="13" /> Init image / reference edits</div>
            <div class="field">
              <label>Single init image <span class="muted small">img2img</span></label>
              <div class="input-group">
                <input v-model="image.init_image" class="input mono" placeholder="images/source.png" />
                <button class="btn btn-sm" @click="imageInitPicker = true">Browse</button>
              </div>
            </div>
            <div class="field">
              <label>Multi-reference images <span class="muted small">{{ image.init_images.length }}/8 · Qwen-Image</span></label>
              <div class="stack" style="gap: 5px">
                <div v-for="(path, index) in image.init_images" :key="path" class="mini-file-row">
                  <ImageIcon :size="13" /><span class="small mono truncate grow">{{ path }}</span><button class="icon-btn" @click="removeImageInitImage(index)"><Trash2 :size="13" /></button>
                </div>
                <button class="btn btn-sm" style="align-self: flex-start" @click="imageInitMultiPicker = true"><Plus :size="12" /> Add reference</button>
              </div>
              <span class="hint">init_image and init_images are mutually exclusive. Multi-reference editing is Qwen-Image only.</span>
            </div>
            <div class="form-grid">
              <div class="field"><label>LoRA path</label><input v-model="image.lora" class="input mono" placeholder="models/loras/style.safetensors" /></div>
              <div class="field"><label>LoRA strength</label><input v-model.number="image.lora_strength" type="number" min="-10" max="10" step="0.05" class="input" /></div>
            </div>
          </div>

          <div class="option-block">
            <div class="option-title"><Maximize2 :size="13" /> Post-generation upscale</div>
            <div class="form-grid">
              <div class="field"><label>Upscale</label><button class="switch" :class="{ on: image.upscale }" style="align-self: flex-start" @click="image.upscale = !image.upscale" /><span class="hint">ESRGAN pass after diffusion.</span></div>
              <div class="field"><label>Upscale repeats</label><input v-model.number="image.upscaleRepeats" type="number" min="1" max="4" class="input" :disabled="!image.upscale" /></div>
            </div>
          </div>

          <div class="row-between" style="flex-wrap: wrap; gap: 8px">
            <div class="row" style="gap: 7px"><span class="chip">{{ image.width }} × {{ image.height }}</span><span class="chip">{{ image.batch_count }} images</span><span class="chip">{{ image.steps }} steps</span></div>
            <button class="btn btn-primary btn-lg" :disabled="busy || !imageFamilies.length || !imageModelOptions.length" @click="generateImage"><Loader2 v-if="busy" :size="15" class="spin" /><Wand2 v-else :size="15" /> Generate images</button>
          </div>
        </div>
      </section>

      <aside class="stack">
        <section class="panel">
          <div class="panel-head"><div><h3>Image job</h3><p>{{ imageJob ? imageJob.title : "Ready to generate" }}</p></div><span class="badge" :class="imageJob?.status || 'queued'">{{ imageJob?.status || "idle" }}</span></div>
          <div class="panel-body stack">
            <JobCard v-if="imageJob" :job="imageJob" @cancel="cancelJob" @retry="retryJob" @remove="removeJob" />
            <div v-else class="empty" style="padding: 22px"><ImageIcon :size="26" style="opacity: .45; margin-bottom: 7px" /><h3>No image batch yet</h3><p>Generate a set of stills and they will appear in the gallery below.</p></div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div><h3>Gallery</h3><p>{{ imagePaths.length }} images · {{ imageData?.width || image.width }} × {{ imageData?.height || image.height }}</p></div><span class="chip">{{ imageData?.model || image.model }}</span></div>
          <div class="panel-body">
            <div v-if="imagePaths.length" class="gallery">
              <a v-for="(path, index) in imagePaths" :key="path" class="gallery-item" :href="resultUrl(path)" target="_blank" rel="noopener">
                <img :src="resultUrl(path)" :alt="`Image ${index + 1}`" />
                <div class="meta">
                  <div class="small strong truncate">Image {{ index + 1 }}</div>
                  <div class="small muted truncate">{{ promptShort(imageData?.prompt || image.prompt) }}</div>
                  <div class="row-between small muted" style="margin-top: 4px"><span>seed {{ imageData?.seed ?? image.seed }}</span><a :href="downloadFor(path)" @click.stop><Download :size="12" /></a></div>
                </div>
              </a>
            </div>
            <EmptyState v-else :icon="ImageIcon" title="No images yet" message="Generate a batch on the left. Results appear here with seed, prompt and download links." />
            <details v-if="imageStats" class="extra-box" style="margin-top: 10px">
              <summary><span><Gauge :size="12" /> Image stats</span><ChevronDown :size="13" /></summary>
              <CodeBlock :code="JSON.stringify(imageStats, null, 2)" label="SDK stats" />
            </details>
          </div>
        </section>
      </aside>
    </div>

    <!-- Upscale tab ---------------------------------------------------- -->
    <div v-else-if="tab === 'upscale'" class="qvac-layout">
      <section class="panel">
        <div class="panel-head">
          <div><h3>ESRGAN upscale</h3><p>Real-ESRGAN x4plus and anime models with tiled inference and repeat passes.</p></div>
          <span class="chip"><Maximize2 :size="11" /> up to 4 passes</span>
        </div>
        <div class="panel-body stack">
          <div class="field">
            <label>Image</label>
            <div class="input-group">
              <input v-model="upscale.image_path" class="input mono" placeholder="images/artwork.png" />
              <button class="btn btn-sm" @click="upscalePicker = true">Browse</button>
            </div>
          </div>
          <div v-if="upscale.image_path" class="image-peek">
            <img :src="resultUrl(upscale.image_path)" alt="" />
            <span class="small muted mono">{{ upscale.image_path }}</span>
          </div>
          <div class="form-grid">
            <div class="field"><label>Upscaler</label><select v-model="upscale.model" class="select" :disabled="!upscaleModels.length"><option v-if="!upscaleModels.length" value="">Install the Real-ESRGAN pack in Settings</option><option v-for="model in upscaleModels" :key="model" :value="model">{{ model }}</option></select></div>
            <div class="field"><label>Repeats</label><input v-model.number="upscale.repeats" type="number" min="1" max="4" class="input" /><span class="hint">Sequential 4× passes; 2 repeats = 16×.</span></div>
            <div class="field"><label>Tile size</label><input v-model.number="upscale.tile_size" type="number" min="16" max="1024" class="input" /><span class="hint">Lower tiles use less VRAM.</span></div>
            <div class="field"><label>Loaded model ID <span class="muted small">optional</span></label><input v-model="upscale.model_id" class="input mono" placeholder="Reuse an already loaded ESRGAN" /></div>
          </div>
          <div class="row-between">
            <div class="row" style="gap: 7px"><span class="chip">PNG output</span><span class="chip">{{ upscale.repeats }}× passes</span></div>
            <button class="btn btn-primary btn-lg" :disabled="busy || !upscaleModels.length" @click="generateUpscale"><Loader2 v-if="busy" :size="15" class="spin" /><Maximize2 v-else :size="15" /> Upscale image</button>
          </div>
        </div>
      </section>

      <aside class="stack">
        <section class="panel">
          <div class="panel-head"><div><h3>Upscale job</h3><p>{{ upscaleJob ? upscaleJob.title : "Ready to upscale" }}</p></div><span class="badge" :class="upscaleJob?.status || 'queued'">{{ upscaleJob?.status || "idle" }}</span></div>
          <div class="panel-body stack">
            <JobCard v-if="upscaleJob" :job="upscaleJob" @cancel="cancelJob" @retry="retryJob" @remove="removeJob" />
            <div v-if="upscalePath" class="preview-box">
              <img :src="resultUrl(upscalePath)" alt="Upscaled result" class="preview-media" />
              <div class="row-between" style="margin-top: 8px"><span class="small muted">{{ formatBytes(upscaleJob?.result?.files?.[0]?.size || 0) }}</span><a class="btn btn-sm" :href="downloadFor(upscalePath)" target="_blank" rel="noopener"><Download :size="12" /> Download</a></div>
            </div>
            <div v-if="upscaleJob?.result" class="meta-table">
              <div class="meta-row"><span>Repeats</span><strong>{{ upscaleData?.repeats || upscale.repeats }}×</strong></div>
              <div class="meta-row"><span>Output</span><strong class="truncate">{{ upscalePath.split("/").pop() }}</strong></div>
              <div class="meta-row"><span>Model</span><strong class="truncate">{{ upscale.model }}</strong></div>
            </div>
            <details v-if="upscaleStats" class="extra-box"><summary><span><Gauge :size="12" /> Upscale stats</span><ChevronDown :size="13" /></summary><CodeBlock :code="JSON.stringify(upscaleStats, null, 2)" label="SDK stats" /></details>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><div><h3>Tips</h3><p>ESRGAN in QVAC</p></div><span class="chip"><Sparkles :size="11" /></span></div>
          <div class="panel-body stack" style="gap: 8px">
            <div class="alert">Use 2 repeats for wallpaper-sized outputs, 3–4 for print. Tiled inference keeps 4× passes inside the VRAM budget.</div>
            <div class="row-between small"><span class="muted">Max repeats</span><span>4</span></div>
            <div class="row-between small"><span class="muted">Tile range</span><span>16 – 1024 px</span></div>
            <div class="row-between small"><span class="muted">Output</span><span>PNG · RGB</span></div>
          </div>
        </section>
      </aside>
    </div>

    <FilePicker v-model="initPicker" kind="image" title="Choose the first frame for img2vid" @selected="setVideoInit" />
    <FilePicker v-model="referencePicker" kind="image" title="Add an LTX-2 reference image" @selected="addReferenceImage" />
    <FilePicker v-model="imageInitPicker" kind="image" title="Choose an init image" @selected="setImageInit" />
    <FilePicker v-model="imageInitMultiPicker" kind="image" title="Add a multi-reference image" @selected="addImageInitImage" />
    <FilePicker v-model="upscalePicker" kind="image" title="Choose an image to upscale" @selected="setUpscaleImage" />
  </div>
</template>

<style scoped>
.status-panel { margin-bottom: 2px; }
.status-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 9px;
}
.status-cell {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px 10px;
  background: rgba(8, 10, 15, 0.3);
  min-width: 0;
}
.status-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--muted-2);
  margin-bottom: 4px;
}
.status-cell strong {
  display: block;
  font-size: 12.5px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-sub {
  display: block;
  font-size: 10px;
  color: var(--muted);
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.qvac-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 390px;
  gap: 16px;
  align-items: start;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
}
.mode-row {
  display: flex;
  align-items: center;
  gap: 11px;
  flex-wrap: wrap;
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
  padding: 7px 14px;
  border-radius: 7px;
  font-size: 11.5px;
  font-weight: 600;
}
.seg:hover { color: var(--text); }
.seg:disabled { opacity: 0.35; cursor: not-allowed; }
.seg.active { background: var(--panel-3); color: var(--text); }
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
details.option-block > summary::-webkit-details-marker { display: none; }
details.option-block[open] > summary { margin-bottom: 2px; }
.image-peek {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-top: 7px;
  padding: 7px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 10, 15, 0.3);
}
.image-peek img {
  width: 74px;
  height: 46px;
  object-fit: cover;
  border-radius: 6px;
  border: 1px solid var(--line);
}
.mini-file-row {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(8, 10, 15, 0.3);
}
.video-preview {
  position: relative;
  border-radius: 11px;
  overflow: hidden;
  border: 1px solid var(--line);
  background: #07090d;
}
.preview-media {
  width: 100%;
  max-height: 260px;
  object-fit: cover;
  display: block;
}
.preview-overlay {
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: 8px;
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.preview-box { border: 1px solid var(--line); border-radius: 11px; padding: 8px; background: rgba(8, 10, 15, 0.3); }
.meta-table {
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
}
.meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 10px;
  border-bottom: 1px solid rgba(35, 42, 58, 0.55);
  font-size: 11.5px;
}
.meta-row:last-child { border-bottom: none; }
.meta-row span { color: var(--muted); flex: none; }
.meta-row strong { font-weight: 600; text-align: right; min-width: 0; }
.extra-box {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px 11px;
  background: rgba(8, 10, 15, 0.3);
}
.extra-box summary {
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  list-style: none;
  font-size: 11.5px;
  font-weight: 600;
  color: var(--muted);
}
.extra-box summary span { display: inline-flex; align-items: center; gap: 6px; }
.extra-box summary::-webkit-details-marker { display: none; }
.model-table { min-width: 850px; }
.gallery {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
.gallery-item img { aspect-ratio: 1/1; }
.history-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
  border-radius: 9px;
}
.history-row:hover { background: rgba(255, 255, 255, 0.035); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 1420px) {
  .status-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 1180px) {
  .qvac-layout { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  .status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .form-grid { grid-template-columns: 1fr; }
}
</style>

<style scoped>
.qvac-embedded { padding: 0; }
</style>
