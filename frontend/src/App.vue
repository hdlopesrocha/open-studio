<script setup lang="ts">
import { computed } from "vue";
import { RouterView, useRoute } from "vue-router";
import AppShell from "@/components/AppShell.vue";

const route = useRoute();
const isPublic = computed(() => Boolean(route.meta.public));
</script>

<template>
  <RouterView v-if="isPublic" />
  <AppShell v-else />
</template>
