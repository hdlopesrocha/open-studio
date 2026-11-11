<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ChevronLeft, FileAudio, FileImage, FileText, FileVideo, Folder, Search, Upload, X, Home, Film, Music2 } from "lucide-vue-next";
import { api, fileUrl, formatBytes, uploadFile } from "@/lib/api";
import type { FileInfo } from "@/lib/types";
import BaseModal from "./BaseModal.vue";
import { useToastStore } from "@/stores/toasts";

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    title?: string;
    kind?: "audio" | "video" | "image" | "subtitle" | "document" | "all";
    accept?: string;
    startPath?: string;
  }>(),
  { title: "Choose a file", kind: "all", accept: "", startPath: "" },
);
const emit = defineEmits<{ "update:modelValue": [value: boolean]; selected: [path: string, file: FileInfo] }>();
const toasts = useToastStore();

const path = ref(props.startPath || "");
const items = ref<FileInfo[]>([]);
const breadcrumbs = ref<Array<{ name: string; path: string }>>([]);
const loading = ref(false);
const uploading = ref(false);
const progress = ref(0);
const query = ref("");
const input = ref<HTMLInputElement | null>(null);

const visible = computed(() => {
  const needle = query.value.trim().toLowerCase();
  return items.value.filter((item) => {
    if (needle && !item.name.toLowerCase().includes(needle)) return false;
    if (item.is_dir) return true;
    if (props.kind === "all") return true;
    return item.kind === props.kind;
  });
});

async function load(target = path.value) {
  loading.value = true;
  try {
    const data = await api.get<{ path: string; items: FileInfo[]; breadcrumbs: any[] }>(`/files/list?path=${encodeURIComponent(target)}`);
    path.value = data.path;
    items.value = data.items;
    breadcrumbs.value = data.breadcrumbs || [];
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      path.value = props.startPath || "";
      query.value = "";
      load();
    }
  },
);

function choose(file: FileInfo) {
  if (file.is_dir) {
    load(file.path);
    return;
  }
  if (props.kind !== "all" && file.kind !== props.kind) return;
  emit("selected", file.path, file);
  emit("update:modelValue", false);
}

async function onUpload(event: Event) {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;
  uploading.value = true;
  progress.value = 0;
  try {
    const result = await uploadFile(path.value || "uploads", file, (value) => (progress.value = value));
    toasts.success(`Uploaded ${file.name}`);
    await load(path.value);
    if (result.file) {
      emit("selected", result.file.path, result.file);
      emit("update:modelValue", false);
    }
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    uploading.value = false;
    if (input.value) input.value.value = "";
  }
}

function icon(file: FileInfo) {
  if (file.is_dir) return Folder;
  if (file.kind === "audio") return FileAudio;
  if (file.kind === "video") return FileVideo;
  if (file.kind === "image") return FileImage;
  if (file.kind === "subtitle") return FileText;
  return FileText;
}

function goBack() {
  if (!path.value) return;
  const parts = path.value.split("/");
  parts.pop();
  load(parts.join("/"));
}
</script>

<template>
  <BaseModal :model-value="modelValue" :title="title" subtitle="Files are shared across every Open Studio service." width="wide" @update:model-value="emit('update:modelValue', $event)">
    <div class="row-between" style="margin-bottom: 10px">
      <div class="row" style="gap: 4px; flex-wrap: wrap">
        <button type="button" class="icon-btn" :disabled="!path" title="Back" @click="goBack"><ChevronLeft :size="16" /></button>
        <button type="button" class="btn btn-sm btn-ghost" @click="load('')"><Home :size="13" /> Files</button>
        <template v-for="crumb in breadcrumbs" :key="crumb.path">
          <span class="muted small">/</span>
          <button type="button" class="btn btn-sm btn-ghost" @click="load(crumb.path)">{{ crumb.name }}</button>
        </template>
      </div>
      <div class="row" style="gap: 7px">
        <div class="input-group" style="width: 180px">
          <Search :size="14" class="muted" />
          <input v-model="query" class="input input-sm" placeholder="Filter…" />
        </div>
        <button type="button" class="btn btn-sm" :disabled="uploading" @click="input?.click()">
          <Upload :size="13" /> {{ uploading ? `${progress}%` : "Upload" }}
        </button>
        <input ref="input" type="file" :accept="accept" hidden @change="onUpload" />
      </div>
    </div>
    <div v-if="uploading" class="progress thin" style="margin-bottom: 8px"><span :style="{ width: `${progress}%` }" /></div>
    <div v-if="loading" class="stack">
      <div v-for="i in 5" :key="i" class="skeleton" style="height: 44px" />
    </div>
    <div v-else-if="!visible.length" class="empty">
      <Folder :size="26" style="margin-bottom: 8px; opacity: 0.5" />
      <h3>No matching files</h3>
      <p>Upload a file or browse another folder. Everything you upload here is available to every service.</p>
    </div>
    <div v-else class="list">
      <button
        v-for="file in visible"
        :key="file.path"
        class="file-row"
        style="width: 100%; background: none; text-align: left; border: 1px solid transparent"
        @click="choose(file)"
      >
        <span class="file-icon" :class="{ dir: file.is_dir }">
          <component :is="icon(file)" :size="16" />
        </span>
        <span class="grow" style="min-width: 0">
          <span class="small strong truncate" style="display: block">{{ file.name }}</span>
          <span class="small muted truncate" style="display: block">{{ file.path }}</span>
        </span>
        <img v-if="file.kind === 'image'" :src="fileUrl(file.path)" style="width: 38px; height: 30px; object-fit: cover; border-radius: 6px" alt="" />
        <span class="small muted nowrap">{{ file.is_dir ? `${file.children ?? ""} items` : file.size_label }}</span>
        <span class="small muted mono nowrap">{{ file.modified?.slice(0, 10) }}</span>
      </button>
    </div>
  </BaseModal>
</template>
