<script setup lang="ts">
import { computed } from "vue";
import { AlertTriangle, ArrowRight } from "lucide-vue-next";
import { RouterLink } from "vue-router";
import { DEMO } from "@/lib/types";
import { useSystemStore } from "@/stores/system";

const props = withDefaults(
  defineProps<{
    services: Array<string | { name: string; label?: string }>;
    title?: string;
  }>(),
  { title: "More features are available" },
);

const system = useSystemStore();
const entries = computed(() =>
  props.services.map((item) => (typeof item === "string" ? { name: item, label: item } : item)),
);
const missing = computed(() => {
  if (DEMO || !system.status) return [];
  return entries.value.filter((item) => !system.service(item.name)?.online);
});
</script>

<template>
  <div v-if="missing.length" class="alert warn service-notice">
    <AlertTriangle :size="15" style="flex: 0 0 auto" />
    <div class="grow">
      <strong>{{ title }}</strong>
      <div class="small muted" style="margin-top: 2px">
        Enable
        <span v-for="(item, index) in missing" :key="item.name" class="service-notice-name">
          {{ item.label || item.name }}<span v-if="index < missing.length - 1">, </span>
        </span>
        in Settings to unlock the related sections.
      </div>
    </div>
    <RouterLink to="/settings" class="btn btn-sm">Settings <ArrowRight :size="12" /></RouterLink>
  </div>
</template>

<style scoped>
.service-notice { align-items: flex-start; margin-bottom: 14px; }
.service-notice-name { font-weight: 650; color: var(--text); }
</style>
