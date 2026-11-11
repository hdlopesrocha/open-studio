<script setup lang="ts">
import { computed } from "vue";
import { Loader2, CheckCircle2, XCircle, Clock, Ban } from "lucide-vue-next";

const props = defineProps<{ status: string }>();
const label = computed(() => props.status.replace("canceling", "cancelling"));
const icon = computed(() => {
  if (props.status === "running") return Loader2;
  if (props.status === "completed") return CheckCircle2;
  if (props.status === "failed") return XCircle;
  if (props.status === "canceled") return Ban;
  if (props.status === "canceling") return Loader2;
  return Clock;
});
</script>

<template>
  <span class="badge" :class="{ success: status === 'completed', running: status === 'running' || status === 'canceling', failed: status === 'failed' || status === 'canceled', queued: status === 'queued' }">
    <component :is="icon" :size="10" :class="{ spin: status === 'running' || status === 'canceling' }" />
    {{ label }}
  </span>
</template>

<style scoped>
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
