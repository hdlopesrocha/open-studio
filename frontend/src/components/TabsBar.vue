<script setup lang="ts">
defineProps<{
  tabs: Array<{ id: string; label: string; count?: number }>;
  modelValue: string;
}>();
defineEmits<{ "update:modelValue": [value: string] }>();
</script>

<template>
  <div class="tabs">
    <button
      v-for="tab in tabs"
      :key="tab.id"
      class="tab"
      :class="{ active: tab.id === modelValue }"
      @click="$emit('update:modelValue', tab.id)"
    >
      {{ tab.label }}
      <span v-if="tab.count !== undefined" class="chip" style="padding: 0 5px; min-width: 17px; justify-content: center">{{ tab.count }}</span>
    </button>
  </div>
</template>
