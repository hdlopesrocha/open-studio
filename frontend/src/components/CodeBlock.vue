<script setup lang="ts">
import { ref } from "vue";
import { Check, Copy } from "lucide-vue-next";
const props = defineProps<{ code: string; label?: string }>();
const copied = ref(false);
async function copy() {
  try {
    await navigator.clipboard.writeText(props.code);
    copied.value = true;
    window.setTimeout(() => (copied.value = false), 1500);
  } catch {}
}
</script>

<template>
  <div>
    <div v-if="label" class="row-between" style="margin-bottom: 6px">
      <span class="small muted">{{ label }}</span>
      <button class="icon-btn" @click="copy"><Check v-if="copied" :size="13" /><Copy v-else :size="13" /></button>
    </div>
    <pre class="code">{{ code }}</pre>
  </div>
</template>
