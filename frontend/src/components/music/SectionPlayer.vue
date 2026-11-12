<script setup lang="ts">
import { computed, ref } from "vue";
import AudioPlayer from "@/components/AudioPlayer.vue";

interface PlayerSection {
  id?: string;
  label: string;
  start?: number;
  end?: number;
  type?: string;
  role?: string;
  color?: string;
}

defineOptions({ inheritAttrs: false });

const props = withDefaults(
  defineProps<{
    src?: string | null;
    title?: string;
    subtitle?: string;
    downloadPath?: string | null;
    bars?: number;
    compact?: boolean;
    waveform?: number[] | null;
    sections?: PlayerSection[];
    duration?: number;
  }>(),
  {
    src: null,
    title: "",
    subtitle: "",
    downloadPath: null,
    bars: 96,
    compact: false,
    waveform: null,
    sections: () => [],
    duration: 0,
  },
);

const emit = defineEmits<{
  timeupdate: [payload: { current: number; duration: number }];
  play: [];
  pause: [];
  ended: [];
}>();

const player = ref<any>(null);
const current = ref(0);
const total = ref(Number(props.duration) || 0);

const spans = computed(() =>
  (props.sections || [])
    .filter((section) => Number.isFinite(Number(section.start)) && Number.isFinite(Number(section.end)))
    .map((section) => ({
      ...section,
      start: Math.max(0, Number(section.start)),
      end: Math.max(Number(section.start), Number(section.end)),
    }))
    .filter((section) => section.end > section.start),
);

const activeId = computed(() => {
  const time = current.value;
  return spans.value.find((section) => time >= section.start && time < section.end)?.id || "";
});

const progress = computed(() => (total.value > 0 ? Math.min(100, (current.value / total.value) * 100) : 0));

function colorFor(section: PlayerSection): string {
  if (section.color) return section.color;
  return {
    intro: "#64748b",
    build: "#f59e0b",
    drop: "#a78bfa",
    chorus: "#22d3ee",
    breakdown: "#38bdf8",
    outro: "#475569",
    verse: "#34d399",
    bridge: "#818cf8",
    theme: "#f472b6",
    rise: "#fbbf24",
    groove: "#2dd4bf",
  }[String(section.type || section.role || "")] || "#8b5cf6";
}

function widthFor(section: { start: number; end: number }): string {
  const base = total.value || Math.max(...spans.value.map((item) => item.end), 1);
  return `${Math.max(2, ((section.end - section.start) / Math.max(1, base)) * 100)}%`;
}

function onTime(payload: { current: number; duration: number }) {
  current.value = Number(payload.current) || 0;
  if (Number(payload.duration) > 0) total.value = Number(payload.duration);
  emit("timeupdate", payload);
}

function seekSection(section: { start: number }) {
  player.value?.seekTo?.(section.start, true);
}

function seekTo(seconds: number, autoplay = false) {
  player.value?.seekTo?.(seconds, autoplay);
}

function pause() {
  player.value?.pause?.();
}

defineExpose({ seekTo, pause });
</script>

<template>
  <div class="section-player" :class="{ compact }">
    <div v-if="spans.length" class="section-player-strip" :style="{ '--section-progress': `${progress}%` }">
      <button
        v-for="section in spans"
        :key="section.id || section.label"
        type="button"
        class="section-player-block"
        :class="{ active: activeId === section.id }"
        :style="{ width: widthFor(section), borderBottomColor: colorFor(section) }"
        :title="`Seek to ${section.label}`"
        @click="seekSection(section)"
      >
        {{ section.label }}
      </button>
    </div>
    <AudioPlayer
      ref="player"
      v-bind="$attrs"
      :src="src"
      :title="title"
      :subtitle="subtitle"
      :download-path="downloadPath"
      :bars="bars"
      :compact="compact"
      :waveform="waveform"
      @timeupdate="onTime"
      @play="emit('play')"
      @pause="emit('pause')"
      @ended="emit('ended')"
    />
  </div>
</template>

<style scoped>
.section-player { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.section-player-strip { display: flex; gap: 2px; min-height: 21px; width: 100%; overflow: hidden; border-radius: 6px; background: rgba(255,255,255,.025); }
.section-player-block { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 3px 5px; border: 0; border-bottom: 2px solid transparent; background: rgba(148,163,184,.09); color: var(--muted); font-size: 9px; cursor: pointer; }
.section-player-block:hover { background: rgba(139,92,246,.16); color: var(--text); }
.section-player-block.active { background: rgba(139,92,246,.24); color: var(--text); font-weight: 650; }
.section-player.compact { gap: 5px; }
.section-player.compact .section-player-strip { min-height: 17px; }
.section-player.compact .section-player-block { font-size: 8px; padding: 2px 4px; }
</style>
