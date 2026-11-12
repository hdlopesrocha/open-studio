<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { Download, Pause, Play, Volume2 } from "lucide-vue-next";
import { downloadUrl, fileUrl, formatDuration } from "@/lib/api";
import { DEMO } from "@/lib/types";
import { useAudioThemeStore } from "@/stores/audioTheme";

const props = withDefaults(
  defineProps<{
    src?: string | null;
    title?: string;
    subtitle?: string;
    downloadPath?: string | null;
    bars?: number;
    compact?: boolean;
    waveform?: number[] | null;
  }>(),
  { title: "", subtitle: "", downloadPath: null, bars: 96, compact: false, waveform: null },
);

const emit = defineEmits<{
  timeupdate: [payload: { current: number; duration: number }];
  play: [];
  pause: [];
  ended: [];
}>();

const theme = useAudioThemeStore();
const playerId = `audio-${Math.random().toString(36).slice(2)}`;
let analysisCtx: AudioContext | null = null;
let analyser: AnalyserNode | null = null;
let mediaSource: MediaElementAudioSourceNode | null = null;
let analysisFrame = 0;

const audio = ref<HTMLAudioElement | null>(null);
const peaks = ref<number[]>([]);
const playing = ref(false);
const current = ref(0);
const duration = ref(0);
const volume = ref(0.9);
const pendingSeek = ref<number | null>(null);
let pendingPlay = false;
let ctx: AudioContext | null = null;

const resolved = computed(() => {
  if (!props.src) return "";
  if (props.src.startsWith("/api/") || props.src.startsWith("blob:") || props.src.startsWith("data:")) return props.src;
  return fileUrl(props.src);
});

const progress = computed(() => (duration.value ? (current.value / duration.value) * 100 : 0));

function seedWave() {
  const text = resolved.value || props.title || "open-studio";
  let hash = 0;
  for (let i = 0; i < text.length; i++) hash = (hash * 31 + text.charCodeAt(i)) | 0;
  const values: number[] = [];
  for (let i = 0; i < props.bars; i++) {
    const n = Math.abs(Math.sin(hash * 0.0001 + i * 0.42) * Math.cos(i * 0.17 + hash * 0.001));
    values.push(0.16 + n * 0.82);
  }
  peaks.value = values;
}

function applyWaveform() {
  const values = props.waveform || [];
  if (!values.length) return false;
  const step = Math.max(1, Math.floor(values.length / props.bars));
  peaks.value = values.filter((_, index) => index % step === 0).slice(0, props.bars);
  return true;
}

async function decode() {
  if (applyWaveform()) return;
  if (DEMO) {
    // Demo captures use deterministic peaks; never fetch a backend in demo mode.
    seedWave();
    return;
  }
  if (!resolved.value) {
    seedWave();
    return;
  }
  try {
    const response = await fetch(resolved.value, { credentials: "include" });
    if (!response.ok) throw new Error("audio fetch failed");
    const buffer = await response.arrayBuffer();
    ctx = ctx || new AudioContext();
    const decoded = await ctx.decodeAudioData(buffer);
    const channel = decoded.getChannelData(0);
    const block = Math.max(1, Math.floor(channel.length / props.bars));
    const values: number[] = [];
    for (let i = 0; i < props.bars; i++) {
      let sum = 0;
      const start = i * block;
      const end = Math.min(channel.length, start + block);
      for (let j = start; j < end; j += 8) sum += Math.abs(channel[j]);
      values.push(Math.max(0.08, Math.min(1, sum / Math.max(1, (end - start) / 8) * 3.2)));
    }
    peaks.value = values;
  } catch {
    seedWave();
  }
}

function pause() {
  audio.value?.pause();
}

function seekTo(seconds: number, autoplay = false) {
  const element = audio.value;
  if (!element) return;
  const target = Math.max(0, Number(seconds) || 0);
  const apply = () => {
    try {
      const limit = Number.isFinite(element.duration) && element.duration > 0 ? element.duration : target;
      element.currentTime = Math.min(target, limit);
      current.value = element.currentTime;
      emit("timeupdate", { current: current.value, duration: duration.value });
      if (autoplay) element.play().catch(() => {});
    } catch {
      pendingSeek.value = target;
      pendingPlay = autoplay;
    }
  };
  if (element.readyState >= 1) apply();
  else {
    pendingSeek.value = target;
    pendingPlay = autoplay;
  }
}

function toggle() {
  const element = audio.value;
  if (!element || !resolved.value) return;
  if (element.paused) {
    element.play().catch(seedWave);
  } else {
    element.pause();
  }
}

function seek(event: MouseEvent) {
  const element = audio.value;
  if (!element || !duration.value) return;
  const target = event.currentTarget as HTMLElement;
  const rect = target.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  element.currentTime = ratio * duration.value;
  current.value = element.currentTime;
  emit("timeupdate", { current: current.value, duration: duration.value });
}

function refresh() {
  const element = audio.value;
  if (!element) return;
  current.value = element.currentTime || 0;
  duration.value = Number.isFinite(element.duration) ? element.duration : 0;
  emit("timeupdate", { current: current.value, duration: duration.value });
  if (pendingSeek.value !== null && element.readyState >= 1) {
    const target = pendingSeek.value;
    pendingSeek.value = null;
    try {
      element.currentTime = Math.min(target, Number.isFinite(element.duration) ? element.duration : target);
      current.value = element.currentTime;
      if (pendingPlay) element.play().catch(() => {});
    } catch {}
    pendingPlay = false;
  }
}

defineExpose({ seekTo, pause });

function bandAverage(data: Uint8Array, sampleRate: number, low: number, high: number): number {
  const nyquist = sampleRate / 2;
  const width = nyquist / Math.max(1, data.length);
  const first = Math.max(0, Math.floor(low / width));
  const last = Math.min(data.length - 1, Math.ceil(high / width));
  if (last < first) return 0;
  let sum = 0;
  for (let index = first; index <= last; index += 1) sum += data[index];
  return Math.min(1, (sum / (last - first + 1) / 255) * 1.5);
}

function analyse() {
  if (!analyser || !analysisCtx) return;
  const data = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(data);
  const sampleRate = analysisCtx.sampleRate;
  const bass = bandAverage(data, sampleRate, 20, 160);
  const drums = Math.max(bass * 0.72, bandAverage(data, sampleRate, 45, 220));
  const snare = Math.max(bandAverage(data, sampleRate, 150, 450) * 0.9, bandAverage(data, sampleRate, 1200, 4200) * 0.7);
  const voice = bandAverage(data, sampleRate, 260, 3200);
  const air = bandAverage(data, sampleRate, 6000, 12000);
  theme.update(playerId, { bass, drums, snare, voice, air });
  analysisFrame = window.requestAnimationFrame(analyse);
}

async function startAnalysis() {
  if (!audio.value || DEMO) return;
  try {
    analysisCtx = analysisCtx || new AudioContext();
    if (!mediaSource) {
      analyser = analysisCtx.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.78;
      mediaSource = analysisCtx.createMediaElementSource(audio.value);
      mediaSource.connect(analyser);
      analyser.connect(analysisCtx.destination);
    }
    await analysisCtx.resume();
    theme.begin(playerId);
    if (!analysisFrame) analysisFrame = window.requestAnimationFrame(analyse);
  } catch {
    // Some browsers disallow MediaElementSource on hidden/CORS audio. Playback
    // and seeking still work; only the reactive palette is skipped.
    theme.reset(playerId);
  }
}

function stopAnalysis() {
  if (analysisFrame) window.cancelAnimationFrame(analysisFrame);
  analysisFrame = 0;
  theme.reset(playerId);
}

function onPlay() {
  playing.value = true;
  void startAnalysis();
  emit("play");
}

function onPause() {
  playing.value = false;
  stopAnalysis();
  emit("pause");
}

function onEnded() {
  playing.value = false;
  stopAnalysis();
  emit("ended");
}

function setVolume() {
  if (audio.value) audio.value.volume = volume.value;
}

onMounted(() => {
  seedWave();
  decode();
});
onBeforeUnmount(() => {
  stopAnalysis();
  ctx?.close();
  analysisCtx?.close().catch(() => {});
  mediaSource?.disconnect();
  analyser?.disconnect();
});

watch(resolved, () => decode());
watch(() => props.waveform, () => applyWaveform());
</script>

<template>
  <div class="audio-player" :class="{ compact }">
    <div class="row-between" v-if="title || subtitle || downloadPath">
      <div style="min-width: 0">
        <div class="small strong truncate">{{ title || "Audio" }}</div>
        <div v-if="subtitle" class="small muted truncate">{{ subtitle }}</div>
      </div>
      <a v-if="downloadPath" class="icon-btn" :href="downloadUrl(downloadPath)" title="Download"><Download :size="15" /></a>
    </div>
    <div class="row" style="gap: 10px; align-items: stretch">
      <button class="btn btn-icon" :disabled="!resolved" style="align-self: center" :title="playing ? 'Pause' : 'Play'" @click="toggle">
        <Pause v-if="playing" :size="15" />
        <Play v-else :size="15" />
      </button>
      <div class="grow" style="min-width: 0; cursor: pointer" @click="seek">
        <div class="wave">
          <span
            v-for="(peak, index) in peaks"
            :key="index"
            :style="{
              height: `${peak * 100}%`,
              opacity: index / peaks.length <= progress / 100 ? 1 : 0.35,
            }"
          />
        </div>
      </div>
    </div>
    <div class="row-between small muted">
      <span class="mono">{{ formatDuration(current) }} / {{ formatDuration(duration) }}</span>
      <span class="row" style="gap: 5px">
        <Volume2 :size="12" />
        <input v-model.number="volume" type="range" min="0" max="1" step="0.05" style="width: 66px" @input="setVolume" />
      </span>
    </div>
    <audio
      ref="audio"
      :src="resolved || undefined"
      preload="metadata"
      @timeupdate="refresh"
      @loadedmetadata="refresh"
      @play="onPlay"
      @pause="onPause"
      @ended="onEnded"
    />
  </div>
</template>

<style scoped>
.audio-player audio { display: none; }
.audio-player.compact { padding: 9px; }
.audio-player.compact .wave { height: 30px; }
</style>
