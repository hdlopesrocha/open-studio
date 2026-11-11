<script setup lang="ts">
defineProps<{ title: string; message?: string; icon?: any }>();
</script>

<template>
  <div class="empty">
    <component :is="icon" v-if="icon" :size="28" style="margin-bottom: 9px; opacity: 0.5" />
    <h3>{{ title }}</h3>
    <p v-if="message">{{ message }}</p>
    <div v-if="$slots.default" style="margin-top: 13px"><slot /></div>
  </div>
</template>
