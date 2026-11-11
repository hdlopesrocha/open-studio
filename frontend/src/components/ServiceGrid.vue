<script setup lang="ts">
import { computed } from "vue";
import { useSystemStore } from "@/stores/system";

const props = withDefaults(defineProps<{ only?: string[]; compact?: boolean }>(), { compact: false });
const system = useSystemStore();
const services = computed(() =>
  props.only ? system.services.filter((service) => props.only!.includes(service.name)) : system.services,
);
</script>

<template>
  <div class="service-grid">
    <div v-for="service in services" :key="service.name" class="service-card">
      <span class="dot" :class="service.online ? 'online' : 'offline'" />
      <span class="grow">
        <span class="name" style="display: block">{{ service.label }}</span>
        <span v-if="!compact" class="meta">{{ service.online ? (service.version ? `v${service.version}` : "online") : service.detail || "offline" }}</span>
      </span>
      <span class="small muted mono" v-if="service.online && service.latency_ms">{{ service.latency_ms }}ms</span>
    </div>
  </div>
</template>
