<script setup lang="ts">
import { X } from "lucide-vue-next";

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    title: string;
    subtitle?: string;
    width?: "narrow" | "normal" | "wide";
    closeOnBackdrop?: boolean;
  }>(),
  { width: "normal", closeOnBackdrop: true },
);
const emit = defineEmits<{ "update:modelValue": [value: boolean] }>();

function close() {
  emit("update:modelValue", false);
}

function backdrop(event: MouseEvent) {
  if (props.closeOnBackdrop && event.target === event.currentTarget) close();
}
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="modal-backdrop" @mousedown="backdrop">
      <div class="modal" :class="width" @keydown.esc="close">
        <div class="modal-head">
          <div>
            <h3>{{ title }}</h3>
            <p v-if="subtitle">{{ subtitle }}</p>
          </div>
          <button type="button" class="icon-btn" aria-label="Close" @click="close"><X :size="17" /></button>
        </div>
        <div class="modal-body"><slot /></div>
        <div v-if="$slots.footer" class="modal-foot"><slot name="footer" /></div>
      </div>
    </div>
  </Teleport>
</template>
