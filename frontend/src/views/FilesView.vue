<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  ChevronLeft,
  Copy,
  Download,
  File,
  FileAudio,
  FileImage,
  FileText,
  FileVideo,
  Folder,
  FolderPlus,
  Grid2x2,
  Home,
  List,
  Move,
  Pencil,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-vue-next";
import { api, downloadUrl, fileUrl, formatBytes, relativeTime, uploadFile } from "@/lib/api";
import type { FileInfo } from "@/lib/types";
import { DEMO, demoFiles } from "@/lib/demo";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import BaseModal from "@/components/BaseModal.vue";
import AudioPlayer from "@/components/AudioPlayer.vue";
import EmptyState from "@/components/EmptyState.vue";

const toasts = useToastStore();
const path = ref("");
const items = ref<FileInfo[]>([]);
const breadcrumbs = ref<Array<{ name: string; path: string }>>([{ name: "Files", path: "" }]);
const selected = ref(new Set<string>());
const query = ref("");
const loading = ref(false);
const view = ref<"list" | "grid">("list");
const preview = ref<FileInfo | null>(null);
const previewText = ref("");
const uploading = ref(false);
const uploadProgress = ref(0);
const uploadInput = ref<HTMLInputElement | null>(null);

const folderModal = ref(false);
const folderName = ref("New folder");
const renameModal = ref(false);
const renameValue = ref("");
const moveModal = ref(false);
const moveTarget = ref("");
const deleteModal = ref(false);
const busy = ref(false);

const visible = computed(() => {
  const needle = query.value.trim().toLowerCase();
  if (!needle) return items.value;
  return items.value.filter((item) => item.name.toLowerCase().includes(needle));
});
const selectedItems = computed(() => items.value.filter((item) => selected.value.has(item.path)));
const totalSize = computed(() => items.value.reduce((sum, item) => sum + item.size, 0));

async function load(target = path.value) {
  loading.value = true;
  if (DEMO) {
    items.value = target ? demoFiles.filter((item) => item.path.startsWith(target)) : demoFiles;
    breadcrumbs.value = [{ name: "Files", path: "" }, ...target.split("/").filter(Boolean).map((part, index, all) => ({ name: part, path: all.slice(0, index + 1).join("/") }))];
    path.value = target;
    loading.value = false;
    return;
  }
  try {
    const data = await api.get<{ path: string; parent: string | null; items: FileInfo[]; breadcrumbs: any[] }>(`/files/list?path=${encodeURIComponent(target)}`);
    path.value = data.path;
    items.value = data.items;
    breadcrumbs.value = data.breadcrumbs || [];
    selected.value = new Set();
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    loading.value = false;
  }
}

onMounted(() => load(""));

function choose(item: FileInfo) {
  if (item.is_dir) {
    load(item.path);
    return;
  }
  selected.value = new Set([item.path]);
  preview.value = item;
  previewText.value = "";
  if (["document", "subtitle"].includes(item.kind) || item.mime.startsWith("text/")) {
    if (DEMO) {
      previewText.value = item.kind === "subtitle" ? "1\n00:00:00,420 --> 00:00:04,800\nA cidade fecha os olhos devagar\n\n2\n00:00:04,800 --> 00:00:09,100\nEu conto os passos até te encontrar" : "Open Studio demo file.\n\nThis text can be edited from the file explorer.";
    } else {
      api.get<{ content: string }>(`/files/read?path=${encodeURIComponent(item.path)}`).then((data) => (previewText.value = data.content)).catch(() => {});
    }
  }
}

function selectAll() {
  selected.value = new Set(visible.value.map((item) => item.path));
}

function toggleSelection(item: FileInfo) {
  const next = new Set(selected.value);
  if (next.has(item.path)) next.delete(item.path);
  else next.add(item.path);
  selected.value = next;
}

function toggle(item: FileInfo, event: MouseEvent) {
  if (event.ctrlKey || event.metaKey) {
    const next = new Set(selected.value);
    if (next.has(item.path)) next.delete(item.path);
    else next.add(item.path);
    selected.value = next;
  } else if (selected.value.size === 1 && selected.value.has(item.path)) {
    selected.value = new Set();
  } else {
    selected.value = new Set([item.path]);
  }
}

function icon(file: FileInfo) {
  if (file.is_dir) return Folder;
  if (file.kind === "audio") return FileAudio;
  if (file.kind === "video") return FileVideo;
  if (file.kind === "image") return FileImage;
  if (file.kind === "subtitle" || file.kind === "document") return FileText;
  return File;
}

function goUp() {
  if (!path.value) return;
  const parts = path.value.split("/");
  parts.pop();
  load(parts.join("/"));
}

async function createFolder() {
  busy.value = true;
  try {
    if (DEMO) toasts.success(`Created ${folderName.value}`);
    else {
      await api.post("/files/mkdir", { path: path.value, name: folderName.value });
      await load();
    }
    folderModal.value = false;
    folderName.value = "New folder";
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    busy.value = false;
  }
}

async function rename() {
  const item = selectedItems.value[0];
  if (!item) return;
  busy.value = true;
  try {
    if (DEMO) toasts.success(`Renamed to ${renameValue.value}`);
    else {
      await api.post("/files/rename", { path: item.path, new_name: renameValue.value });
      await load();
      if (preview.value?.path === item.path) preview.value = null;
    }
    renameModal.value = false;
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    busy.value = false;
  }
}

async function move(copy = false) {
  busy.value = true;
  try {
    if (DEMO) toasts.success(`${copy ? "Copied" : "Moved"} ${selectedItems.value.length} item(s)`);
    else {
      await api.post("/files/move", { paths: selectedItems.value.map((item) => item.path), destination: moveTarget.value, copy });
      await load();
    }
    moveModal.value = false;
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    busy.value = false;
  }
}

async function remove() {
  busy.value = true;
  try {
    if (DEMO) toasts.success("Deleted selected items");
    else {
      await api.delete("/files", { paths: selectedItems.value.map((item) => item.path) });
      await load();
      preview.value = null;
    }
    deleteModal.value = false;
    selected.value = new Set();
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    busy.value = false;
  }
}

async function onUpload(event: Event) {
  const input = event.target as HTMLInputElement;
  if (!input.files?.length) return;
  uploading.value = true;
  try {
    for (const file of Array.from(input.files)) {
      if (DEMO) {
        toasts.success(`Uploaded ${file.name}`);
        continue;
      }
      await uploadFile(path.value || "uploads", file, (value) => (uploadProgress.value = value));
    }
    await load();
    toasts.success("Upload complete");
  } catch (error: any) {
    toasts.error(error.message);
  } finally {
    uploading.value = false;
    input.value = "";
  }
}

async function makeZip() {
  try {
    if (DEMO) toasts.success("Archive created: tmp/selection.zip");
    else {
      const result = await api.post<any>("/files/zip", { paths: selectedItems.value.map((item) => item.path), name: "selection" });
      toasts.success(`Archive created: ${result.path}`);
      await load();
    }
  } catch (error: any) {
    toasts.error(error.message);
  }
}

function openRename() {
  renameValue.value = selectedItems.value[0]?.name || "";
  renameModal.value = true;
}
</script>

<template>
  <div class="page">
    <PageHeader
      eyebrow="Shared storage"
      title="Files"
      subtitle="One folder for every service. Create folders, upload, rename, move, copy, delete, preview, zip and share files between music, video, voice, documents and media tools."
    >
      <template #actions>
        <button class="btn btn-sm btn-ghost" @click="load(path)"><RefreshCw :size="13" /> Refresh</button>
      </template>
    </PageHeader>

    <div v-if="uploading" class="panel" style="margin-bottom: 12px">
      <div class="panel-body" style="padding: 12px">
        <div class="row-between small"><span>Uploading…</span><span class="mono">{{ uploadProgress }}%</span></div>
        <div class="progress thin" style="margin-top: 6px"><span :style="{ width: `${uploadProgress}%` }" /></div>
      </div>
    </div>

    <div class="split-wide">
      <section class="panel">
        <div class="panel-head" style="gap: 8px; flex-wrap: wrap">
          <div class="row" style="gap: 3px; flex-wrap: wrap; min-width: 0">
            <button class="icon-btn" :disabled="!path" @click="goUp"><ChevronLeft :size="15" /></button>
            <button class="btn btn-sm btn-ghost" @click="load('')"><Home :size="12" /> Files</button>
            <template v-for="crumb in breadcrumbs.slice(1)" :key="crumb.path">
              <span class="muted small">/</span>
              <button class="btn btn-sm btn-ghost" @click="load(crumb.path)">{{ crumb.name }}</button>
            </template>
          </div>
          <div class="row" style="gap: 6px">
            <div class="input-group" style="width: 170px"><Search :size="13" class="muted" /><input v-model="query" class="input input-sm" placeholder="Filter folder…" /></div>
            <div class="tabs" style="padding: 2px">
              <button class="tab" :class="{ active: view === 'list' }" @click="view = 'list'"><List :size="13" /></button>
              <button class="tab" :class="{ active: view === 'grid' }" @click="view = 'grid'"><Grid2x2 :size="13" /></button>
            </div>
          </div>
        </div>

        <div v-if="loading" class="panel-body stack"><div v-for="i in 6" :key="i" class="skeleton" style="height: 42px" /></div>
        <div v-else-if="!visible.length" class="panel-body">
          <EmptyState :icon="Folder" title="This folder is empty" message="Upload a file, create a folder, or generate something from one of the studio pages. Every service shares this tree." />
        </div>
        <div v-else-if="view === 'list'" class="panel-body" style="padding: 8px">
          <div
            v-for="item in visible"
            :key="item.path"
            class="file-row"
            :class="{ selected: selected.has(item.path) }"
            style="cursor: pointer"
            @click="choose(item)"
            @mousedown="toggle(item, $event)"
          >
            <input type="checkbox" :checked="selected.has(item.path)" aria-label="Select" @click.stop @change="toggleSelection(item)" />
            <span class="file-icon" :class="{ dir: item.is_dir }"><component :is="icon(item)" :size="16" /></span>
            <span class="grow" style="min-width: 0">
              <span class="small strong truncate" style="display: block">{{ item.name }}</span>
              <span class="small muted truncate" style="display: block">{{ item.path }}</span>
            </span>
            <span class="small muted nowrap" style="width: 74px; text-align: right">{{ item.is_dir ? `${item.children ?? 0} items` : item.size_label }}</span>
            <span class="small muted nowrap" style="width: 74px; text-align: right">{{ relativeTime(item.modified) }}</span>
            <a v-if="!item.is_dir" class="icon-btn" :href="downloadUrl(item.path)" title="Download" @click.stop><Download :size="14" /></a>
          </div>
        </div>
        <div v-else class="panel-body">
          <div class="gallery">
            <div v-for="item in visible" :key="item.path" class="gallery-item" :style="selected.has(item.path) ? 'border-color: rgba(139,92,246,.6)' : ''" @click="choose(item)" @mousedown="toggle(item, $event)">
              <input class="gallery-select" type="checkbox" :checked="selected.has(item.path)" aria-label="Select" @click.stop @change="toggleSelection(item)" />
              <img v-if="item.kind === 'image'" :src="fileUrl(item.path)" :alt="item.name" />
              <div v-else style="aspect-ratio: 1/1; display: grid; place-items: center; background: rgba(8,10,15,.5)">
                <component :is="icon(item)" :size="34" style="color: var(--muted)" />
              </div>
              <div class="meta">
                <div class="small strong truncate">{{ item.name }}</div>
                <div class="small muted">{{ item.is_dir ? `${item.children ?? 0} items` : item.size_label }}</div>
              </div>
            </div>
          </div>
        </div>
        <div class="explorer-bottombar">
          <div class="row" style="gap: 8px; min-width: 0">
            <span class="chip" :class="{ active: selectedItems.length }">{{ selectedItems.length ? `${selectedItems.length} selected` : "No selection" }}</span>
            <span class="small muted">{{ visible.length }} items · {{ formatBytes(totalSize) }}</span>
          </div>
          <div class="row" style="gap: 5px; flex-wrap: wrap; justify-content: flex-end">
            <button type="button" class="btn btn-sm" @click="uploadInput?.click()"><Upload :size="12" /> Upload</button>
            <button type="button" class="btn btn-sm" @click="folderModal = true"><FolderPlus :size="12" /> Folder</button>
            <button type="button" class="btn btn-sm" :disabled="selectedItems.length !== 1" @click="openRename"><Pencil :size="12" /> Rename</button>
            <button type="button" class="btn btn-sm" :disabled="!selectedItems.length" @click="moveTarget = ''; moveModal = true"><Move :size="12" /> Move</button>
            <button type="button" class="btn btn-sm" :disabled="!selectedItems.length" @click="moveTarget = ''; moveModal = true"><Copy :size="12" /> Copy</button>
            <button type="button" class="btn btn-sm" :disabled="!selectedItems.length" @click="makeZip"><FileText :size="12" /> Zip</button>
            <button type="button" class="btn btn-sm btn-danger" :disabled="!selectedItems.length" @click="deleteModal = true"><Trash2 :size="12" /> Delete</button>
            <button type="button" class="btn btn-sm btn-ghost" @click="selectAll">Select all</button>
            <button type="button" class="btn btn-sm btn-ghost" :disabled="!selectedItems.length" @click="selected = new Set()">Clear</button>
            <input ref="uploadInput" type="file" multiple hidden @change="onUpload" />
          </div>
        </div>
      </section>

      <aside class="panel">
        <div class="panel-head">
          <div><h3>Preview</h3><p>{{ preview ? preview.name : "Select a file" }}</p></div>
          <a v-if="preview" class="icon-btn" :href="downloadUrl(preview.path)"><Download :size="15" /></a>
        </div>
        <div class="panel-body">
          <template v-if="preview">
            <img v-if="preview.kind === 'image'" :src="fileUrl(preview.path)" style="width: 100%; border-radius: 10px; border: 1px solid var(--line)" :alt="preview.name" />
            <AudioPlayer v-else-if="preview.kind === 'audio'" :src="preview.path" :title="preview.name" :download-path="preview.path" />
            <video v-else-if="preview.kind === 'video'" :src="fileUrl(preview.path)" controls style="width: 100%; border-radius: 10px; background: #000" />
            <pre v-else-if="previewText" class="code" style="max-height: 320px">{{ previewText }}</pre>
            <div v-else class="empty"><File :size="28" style="opacity: .4" /><h3>{{ preview.name }}</h3><p>{{ preview.mime }}</p></div>
            <div class="stack" style="gap: 7px; margin-top: 12px">
              <div class="row-between small"><span class="muted">Path</span><span class="mono truncate" style="max-width: 230px">{{ preview.path }}</span></div>
              <div class="row-between small"><span class="muted">Size</span><span>{{ preview.size_label }}</span></div>
              <div class="row-between small"><span class="muted">Modified</span><span>{{ relativeTime(preview.modified) }}</span></div>
              <div class="row-between small"><span class="muted">Type</span><span>{{ preview.mime }}</span></div>
            </div>
          </template>
          <EmptyState v-else :icon="FileText" title="Nothing selected" message="Click a file to preview it here. Images, audio and video play inline; text and subtitles are shown as editable text." />
        </div>
      </aside>
    </div>

    <BaseModal v-model="folderModal" title="New folder" subtitle="Folders are created inside the current location." width="narrow">
      <div class="field"><label>Folder name</label><input v-model="folderName" class="input" @keydown.enter="createFolder" /></div>
      <template #footer><button class="btn" @click="folderModal = false">Cancel</button><button class="btn btn-primary" :disabled="busy" @click="createFolder">Create</button></template>
    </BaseModal>

    <BaseModal v-model="renameModal" title="Rename" width="narrow">
      <div class="field"><label>New name</label><input v-model="renameValue" class="input" @keydown.enter="rename" /></div>
      <template #footer><button class="btn" @click="renameModal = false">Cancel</button><button class="btn btn-primary" :disabled="busy" @click="rename">Rename</button></template>
    </BaseModal>

    <BaseModal v-model="moveModal" title="Move or copy" subtitle="Enter a destination folder relative to /data/files." width="narrow">
      <div class="field"><label>Destination</label><input v-model="moveTarget" class="input" placeholder="music/nocturno" /></div>
      <template #footer>
        <button class="btn" @click="moveModal = false">Cancel</button>
        <button class="btn" :disabled="busy || !moveTarget" @click="move(true)">Copy</button>
        <button class="btn btn-primary" :disabled="busy || !moveTarget" @click="move(false)">Move</button>
      </template>
    </BaseModal>

    <BaseModal v-model="deleteModal" title="Delete files" subtitle="This cannot be undone." width="narrow">
      <div class="alert error">{{ selectedItems.length }} item(s) will be permanently deleted.</div>
      <template #footer><button class="btn" @click="deleteModal = false">Cancel</button><button class="btn btn-danger" :disabled="busy" @click="remove">Delete</button></template>
    </BaseModal>
  </div>
</template>
