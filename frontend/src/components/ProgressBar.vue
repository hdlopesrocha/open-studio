<script setup lang="ts">
withDefaults(defineProps<{ value: number; label?: string; showLabel?: boolean; warn?: boolean; thin?: boolean }>(), {
  showLabel: false,
  warn: false,
  thin: false,
});
</script>

<template>
  <div>
    <div v-if="showLabel" class="row-between" style="margin-bottom: 5px">
      <span class="small muted truncate">{{ label }}</span>
      <span class="small mono">{{ Math.round(value) }}%</span>
    </div>
    <div class="progress" :class="{ warn, thin }"><span :style="{ width: `${Math.max(0, Math.min(100, value))}%` }" /></div>
  </div>
</template>
