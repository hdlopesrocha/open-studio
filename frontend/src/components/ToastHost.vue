<script setup lang="ts">
import { useToastStore } from "@/stores/toasts";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-vue-next";
const toasts = useToastStore();
</script>

<template>
  <div class="toast-host">
    <div v-for="toast in toasts.items" :key="toast.id" class="toast" :class="toast.kind">
      <CheckCircle2 v-if="toast.kind === 'success'" :size="17" style="color: var(--success); flex: none" />
      <AlertTriangle v-else-if="toast.kind === 'error'" :size="17" style="color: var(--danger); flex: none" />
      <Info v-else :size="17" style="color: var(--accent-2); flex: none" />
      <span class="grow">{{ toast.message }}</span>
      <button class="icon-btn" style="width: 20px; height: 20px" @click="toasts.dismiss(toast.id)">
        <X :size="13" />
      </button>
    </div>
  </div>
</template>
