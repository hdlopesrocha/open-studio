<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  Bot,
  Check,
  Copy,
  Loader2,
  MessageSquarePlus,
  Paperclip,
  Pencil,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  Undo2,
  UserRound,
  Wrench,
  X,
} from "lucide-vue-next";
import { api, fileUrl, relativeTime } from "@/lib/api";
import { DEMO } from "@/lib/types";
import type { FileInfo } from "@/lib/types";
import { useSystemStore } from "@/stores/system";
import { useToastStore } from "@/stores/toasts";
import PageHeader from "@/components/PageHeader.vue";
import EmptyState from "@/components/EmptyState.vue";
import ServiceNotice from "@/components/ServiceNotice.vue";
import FilePicker from "@/components/FilePicker.vue";

interface ChatSession {
  id: string;
  title: string;
  system_prompt: string;
  model: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message?: string;
}

interface ChatMessage {
  id: string;
  session_id: string;
  role: string;
  content: string;
  metadata?: Record<string, any>;
  created_at: string;
}

const system = useSystemStore();
const toasts = useToastStore();
const router = useRouter();
const llmOnline = computed(() => DEMO || !system.status || system.service("llm")?.online === true);
const sessions = ref<ChatSession[]>([]);
const messages = ref<ChatMessage[]>([]);
const activeId = ref("");
const draft = ref("");
const query = ref("");
const model = ref("llama3.2:3b");
const models = ref<Array<{ id: string; name?: string }>>([]);
const loading = ref(false);
const sending = ref(false);
const error = ref("");
const copiedId = ref("");
const failedImages = ref<Record<string, boolean>>({});
const attachments = ref<Array<{ path: string; name: string; size?: number }>>([]);
const attachmentPickerOpen = ref(false);
const messageEnd = ref<HTMLElement | null>(null);
const composer = ref<HTMLTextAreaElement | null>(null);

const activeSession = computed(() => sessions.value.find((session) => session.id === activeId.value) || null);
const attachmentStartPath = computed(() => activeId.value ? `chat/uploads/${activeId.value}` : "chat/uploads");
const filteredSessions = computed(() => {
  const needle = query.value.trim().toLowerCase();
  if (!needle) return sessions.value;
  return sessions.value.filter((session) => `${session.title} ${session.last_message || ""}`.toLowerCase().includes(needle));
});
const presets = [
  { label: "Audio", to: "/music", prompt: "Help me write, arrange or mix audio. Ask for the genre, mood, reference artists, language, vocal direction and whether I need songwriting, DJ mixing or subtitles." },
  { label: "DJ / Mix", to: "/music?tab=dj-library", prompt: "Help me plan a DJ mix. Ask for my tracks, target BPM, energy arc and transition style, then suggest a section-by-section plan." },
  { label: "Video", to: "/video", prompt: "Help me plan a music video. Ask for the track, visual references, shot list and pacing, then outline scenes and transitions." },
  { label: "Voice", to: "/voice", prompt: "Help me choose a voice and prepare a script. Ask for language, accent, gender, pace and emotion." },
  { label: "Images", to: "/images", prompt: "Help me write a high-quality image prompt. Ask for subject, lighting, lens, composition, palette and negative constraints." },
  { label: "Documents / PDF", to: "/documents", prompt: "Help me process a document. Ask what I need: extract text, OCR, translate, summarize, narrate or export subtitles." },
  { label: "Translate", to: "/documents?tab=translate", prompt: "Help me translate a text. Ask for source language, target variant, tone and whether names or technical terms must remain unchanged." },
  { label: "Summary", to: "/documents?tab=summary", prompt: "Help me summarize a long document. Ask for the audience, target language, desired length and what decisions the summary must support." },
  { label: "SRT", to: "/music?tab=srt", prompt: "Help me create subtitles or align lyrics. Ask for the audio, language and whether I need SRT, VTT or partial lyric alignment." },
  { label: "FFmpeg", to: "/ffmpeg", prompt: "Help me build an FFmpeg workflow. Ask for input files, desired output, codec, resolution, loudness and timing constraints." },
  { label: "yt-dlp", to: "/ytdlp", prompt: "Help me prepare a media download. Ask for the URL, desired quality, audio-only or video, subtitles and output format." },
  { label: "QVAC", to: "/video?tab=qvac", prompt: "Help me plan a QVAC generation. Ask for prompts, dimensions, frames, duration and whether I need image-to-video or upscaling." },
];

async function loadModels() {
  try {
    const data = await api.get<{ items: Array<{ id: string; name?: string }>; default?: string }>("/chat/models");
    models.value = data.items || [];
    if (data.default) model.value = data.default;
    if (!models.value.length) models.value = [{ id: model.value }];
  } catch {
    models.value = [{ id: model.value }];
  }
}

async function loadSessions() {
  loading.value = true;
  error.value = "";
  try {
    if (DEMO) {
      sessions.value = [
        { id: "demo-chat", title: "Studio planning", system_prompt: "", model: "llama3.2:3b", created_at: new Date().toISOString(), updated_at: new Date().toISOString(), message_count: 2, last_message: "A 124 BPM deep house set with a warm opening." },
      ];
      await openSession("demo-chat");
      return;
    }
    const data = await api.get<{ items: ChatSession[] }>("/chat/sessions");
    sessions.value = data.items || [];
    if (!activeId.value && sessions.value.length) await openSession(sessions.value[0].id);
    if (activeId.value && !sessions.value.some((session) => session.id === activeId.value)) {
      activeId.value = "";
      messages.value = [];
    }
  } catch (err: any) {
    error.value = err?.message || "Could not load conversations.";
  } finally {
    loading.value = false;
  }
}

async function newSession() {
  error.value = "";
  try {
    if (DEMO) {
      toasts.info("Demo mode: conversations are local only.");
      return;
    }
    const session = await api.post<ChatSession>("/chat/sessions", { title: "New chat", model: model.value });
    sessions.value.unshift(session);
    await openSession(session.id);
    await nextTick();
  } catch (err: any) {
    error.value = err?.message || "Could not create a conversation.";
  }
}

async function openSession(id: string) {
  activeId.value = id;
  error.value = "";
  messages.value = [];
  try {
    if (DEMO) {
      const session = sessions.value.find((item) => item.id === id);
      model.value = session?.model || model.value;
      messages.value = [
        { id: "d1", session_id: id, role: "user", content: "Help me plan a deep house set.", created_at: new Date().toISOString() },
        { id: "d2", session_id: id, role: "assistant", content: "Great. Start with a warm 120–122 BPM opening, then introduce the bassline around minute 8. What tracks and energy arc do you have in mind?", created_at: new Date().toISOString() },
      ];
      return;
    }
    const data = await api.get<ChatSession & { messages: ChatMessage[] }>(`/chat/sessions/${id}`);
    const session = sessions.value.find((item) => item.id === id);
    if (session) Object.assign(session, data);
    model.value = data.model || model.value;
    messages.value = data.messages || [];
    await scrollToBottom();
  } catch (err: any) {
    error.value = err?.message || "Could not open the conversation.";
  }
}

async function renameSession(session: ChatSession) {
  const title = window.prompt("Conversation title", session.title);
  if (!title?.trim() || title.trim() === session.title) return;
  try {
    const updated = await api.patch<ChatSession>(`/chat/sessions/${session.id}`, { title: title.trim() });
    Object.assign(session, updated);
  } catch (err: any) {
    toasts.error(err?.message || "Could not rename the conversation.");
  }
}

async function deleteSession(session: ChatSession) {
  if (!window.confirm(`Delete “${session.title}”?`)) return;
  try {
    await api.delete(`/chat/sessions/${session.id}`);
    sessions.value = sessions.value.filter((item) => item.id !== session.id);
    if (activeId.value === session.id) {
      activeId.value = "";
      messages.value = [];
    }
  } catch (err: any) {
    toasts.error(err?.message || "Could not delete the conversation.");
  }
}

function attachmentName(path: string): string {
  return path.split("/").filter(Boolean).pop() || path;
}

const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "webp", "gif", "bmp", "avif", "svg"]);

function messageAttachments(message: ChatMessage): string[] {
  const paths = message.metadata?.attachments;
  return Array.isArray(paths) ? paths.filter((path): path is string => typeof path === "string" && Boolean(path)) : [];
}

function isImageAttachment(path: string): boolean {
  const extension = path.split(".").pop()?.toLowerCase() || "";
  return IMAGE_EXTENSIONS.has(extension) && !failedImages.value[path];
}

function imageAttachments(message: ChatMessage): string[] {
  return messageAttachments(message).filter(isImageAttachment);
}

function fileAttachments(message: ChatMessage): string[] {
  return messageAttachments(message).filter((path) => !isImageAttachment(path));
}

function markImageFailed(path: string): void {
  failedImages.value = { ...failedImages.value, [path]: true };
}

async function revertMessage(message: ChatMessage, edit = false) {
  if (sending.value || !activeId.value) return;
  if (!window.confirm(edit ? "Revert to this message and edit it? Later messages will be removed." : "Revert the conversation to this point? Later messages will be removed.")) return;
  try {
    if (DEMO || message.id.startsWith("local-")) {
      const index = messages.value.findIndex((item) => item.id === message.id);
      if (index >= 0) messages.value = messages.value.slice(0, index);
      if (edit) {
        draft.value = message.content;
        attachments.value = (message.metadata?.attachments || []).map((path: string) => ({ path, name: attachmentName(path) }));
      }
      return;
    }
    const data = await api.post<{ messages: ChatMessage[]; session: ChatSession }>(
      `/chat/sessions/${activeId.value}/messages/${message.id}/revert`,
      {},
    );
    messages.value = data.messages || [];
    const session = sessions.value.find((item) => item.id === activeId.value);
    if (session && data.session) Object.assign(session, data.session);
    if (edit) {
      draft.value = message.content;
      attachments.value = (message.metadata?.attachments || []).map((path: string) => ({ path, name: attachmentName(path) }));
      await nextTick();
      composer.value?.focus();
    } else {
      toasts.success("Conversation reverted");
    }
    await scrollToBottom();
  } catch (err: any) {
    toasts.error(err?.message || "Could not revert the conversation.");
  }
}

async function deleteMessage(message: ChatMessage) {
  if (sending.value || !activeId.value) return;
  if (!window.confirm("Delete this message?")) return;
  try {
    if (!DEMO && !message.id.startsWith("local-")) {
      await api.delete(`/chat/sessions/${activeId.value}/messages/${message.id}`);
    }
    messages.value = messages.value.filter((item) => item.id !== message.id);
    const session = sessions.value.find((item) => item.id === activeId.value);
    if (session) session.message_count = messages.value.length;
  } catch (err: any) {
    toasts.error(err?.message || "Could not delete the message.");
  }
}

function askAgentToFix(detail: string) {
  if (sending.value) return;
  draft.value = `Diagnose and fix this Open Studio error if possible. Read the relevant service logs, repair or restart the affected service, retry the operation, and if it is a code bug write a ready-to-paste OpenCode prompt.\n\nError: ${detail}`;
  error.value = "";
  void send();
}

function askAgentToFixAction(action: any) {
  const detail = action?.error || JSON.stringify(action?.data || action || {}).slice(0, 1200);
  askAgentToFix(`The ${action?.tool || "tool"} action failed: ${detail}`);
}

function onAttachmentSelected(path: string, file: FileInfo) {
  if (attachments.value.length >= 8) {
    toasts.info("A message can include at most 8 attachments.");
    return;
  }
  if (!attachments.value.some((item) => item.path === path)) {
    attachments.value.push({ path, name: file.name, size: file.size });
  }
  attachmentPickerOpen.value = false;
}

function removeAttachment(index: number) {
  attachments.value.splice(index, 1);
}

async function send() {
  const text = draft.value.trim();
  if (!text || sending.value) return;
  if (!activeId.value) await newSession();
  if (!activeId.value) return;
  const outgoingAttachments = attachments.value.map((item) => item.path);
  sending.value = true;
  error.value = "";
  draft.value = "";
  attachments.value = [];
  try {
    if (DEMO) {
      messages.value.push({ id: `u-${Date.now()}`, session_id: activeId.value, role: "user", content: text, created_at: new Date().toISOString() });
      await new Promise((resolve) => window.setTimeout(resolve, 450));
      messages.value.push({ id: `a-${Date.now()}`, session_id: activeId.value, role: "assistant", content: "Demo mode: connect the Chat service and local LLM to get a real answer.", created_at: new Date().toISOString() });
      return;
    }
    const data = await api.post<{ messages: ChatMessage[]; session: ChatSession; model: string; actions?: Array<any> }>(
      `/chat/sessions/${activeId.value}/messages`,
      { content: text, model: model.value, attachments: outgoingAttachments },
    );
    messages.value.push(...(data.messages || []));
    const session = sessions.value.find((item) => item.id === activeId.value);
    if (session && data.session) Object.assign(session, data.session);
    await scrollToBottom();
    const navigation = (data.actions || []).find((action: any) => action.tool === "navigate" && action.data?.path);
    if (navigation?.data?.path) router.push(navigation.data.path);
  } catch (err: any) {
    error.value = err?.message || "The local model could not answer.";
    // Keep the user's attempted message visible so it can be retried or edited.
    messages.value.push({ id: `local-${Date.now()}`, session_id: activeId.value, role: "user", content: text, created_at: new Date().toISOString() });
    await scrollToBottom();
  } finally {
    sending.value = false;
  }
}

function usePreset(prompt: string) {
  draft.value = prompt;
}

async function copyMessage(message: ChatMessage) {
  try {
    await navigator.clipboard.writeText(message.content);
    copiedId.value = message.id;
    window.setTimeout(() => {
      if (copiedId.value === message.id) copiedId.value = "";
    }, 1400);
  } catch {
    toasts.error("Could not copy the message.");
  }
}

async function copyOpencodePrompt(prompt: string) {
  try {
    await navigator.clipboard.writeText(prompt);
    toasts.success("OpenCode prompt copied");
  } catch {
    toasts.error("Could not copy the OpenCode prompt.");
  }
}

async function scrollToBottom() {
  await nextTick();
  messageEnd.value?.scrollIntoView({ behavior: "smooth", block: "end" });
}

function onComposerKeydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void send();
  }
}

onMounted(async () => {
  await loadModels();
  await loadSessions();
});
</script>

<template>
  <div class="page chat-page">
    <PageHeader
      eyebrow="Local AI workspace"
      title="Chat"
      subtitle="Talk to your local model with persistent conversations, then jump into any studio tool. Sessions are stored locally in your shared state."
    >
      <template #actions>
        <span class="chip success"><span class="dot online" /> {{ DEMO ? "demo" : "local" }}</span>
        <button class="btn btn-sm" :disabled="loading" @click="loadSessions"><RefreshCw :size="12" :class="{ spin: loading }" /> Refresh</button>
      </template>
    </PageHeader>

    <div class="chat-layout">
      <aside class="panel chat-sidebar">
        <div class="panel-head chat-sidebar-head">
          <div><h3>Conversations</h3><p>{{ sessions.length }} saved</p></div>
          <button class="btn btn-sm btn-primary" @click="newSession"><MessageSquarePlus :size="13" /> New</button>
        </div>
        <div class="panel-body stack" style="gap: 8px">
          <input v-model="query" class="input input-sm" placeholder="Search conversations…" />
          <div v-if="loading" class="stack">
            <div v-for="i in 4" :key="i" class="skeleton" style="height: 52px" />
          </div>
          <div v-else-if="!filteredSessions.length" class="small muted" style="padding: 12px 4px">No conversations yet. Start a new chat.</div>
          <div v-for="session in filteredSessions" :key="session.id" class="chat-session" :class="{ active: session.id === activeId }" @click="openSession(session.id)">
            <div class="grow" style="min-width: 0">
              <button class="chat-session-title" @click.stop="renameSession(session)">{{ session.title }}</button>
              <div class="small muted truncate">{{ session.last_message || "New conversation" }}</div>
              <div class="chat-session-meta"><span>{{ relativeTime(session.updated_at) }}</span><span>{{ session.message_count }} messages</span></div>
            </div>
            <button class="icon-btn chat-delete" title="Delete conversation" @click.stop="deleteSession(session)"><Trash2 :size="13" /></button>
          </div>
        </div>
      </aside>

      <section class="panel chat-main">
        <div class="panel-head chat-main-head">
          <div>
            <h3>{{ activeSession?.title || "New conversation" }}</h3>
            <p>{{ activeSession?.message_count ? `${activeSession.message_count} messages · ${relativeTime(activeSession.updated_at)}` : "Ask anything about your studio or local AI workflow." }}</p>
          </div>
          <div class="row" style="gap: 7px">
            <select v-model="model" class="select input-sm" style="max-width: 190px" title="Model">
              <option v-for="item in models" :key="item.id" :value="item.id">{{ item.name || item.id }}</option>
            </select>
          </div>
        </div>

        <ServiceNotice :services="[{ name: 'llm', label: 'LLM Bridge + Ollama' }]" title="Chat needs the local LLM" />

        <div v-if="error" class="alert error chat-error">
          <strong>The local model did not answer.</strong>
          <span>{{ error }}</span>
          <button class="btn btn-sm" style="margin-left: auto" @click="askAgentToFix(error)"><Wrench :size="12" /> Ask agent to fix</button>
          <RouterLink to="/settings" class="btn btn-sm">Open Settings</RouterLink>
        </div>

        <div class="chat-transcript">
          <EmptyState v-if="!messages.length && !loading" :icon="Bot" title="Start a conversation" message="Ask a question, plan a project or use an AI workspace preset below. Messages and sessions stay local." />
          <article v-for="message in messages" :key="message.id" class="chat-message" :class="message.role">
            <div class="chat-avatar"><Bot v-if="message.role === 'assistant'" :size="15" /><UserRound v-else :size="15" /></div>
            <div class="chat-bubble-wrap">
              <div class="chat-bubble">{{ message.content }}</div>
              <div v-if="messageAttachments(message).length" class="chat-message-attachments">
                <a
                  v-for="path in imageAttachments(message)"
                  :key="`img-${path}`"
                  class="chat-message-image"
                  :href="fileUrl(path)"
                  target="_blank"
                  rel="noopener"
                  :title="attachmentName(path)"
                >
                  <img :src="fileUrl(path)" :alt="attachmentName(path)" loading="lazy" @error="markImageFailed(path)" />
                </a>
                <a
                  v-for="path in fileAttachments(message)"
                  :key="`file-${path}`"
                  class="chip clickable"
                  :href="fileUrl(path)"
                  target="_blank"
                  rel="noopener"
                  :title="path"
                >
                  <Paperclip :size="10" /> {{ attachmentName(path) }}
                </a>
              </div>
              <div v-if="message.metadata?.actions?.length" class="chat-agent-actions">
                <template v-for="(action, actionIndex) in message.metadata.actions" :key="actionIndex">
                  <RouterLink v-if="action.tool === 'navigate' && action.data?.path" :to="action.data.path" class="chip clickable">
                    Open {{ action.data.label || action.data.path }}
                  </RouterLink>
                  <button v-else-if="action.tool === 'opencode_prompt' && action.data?.prompt" class="chip clickable" @click="copyOpencodePrompt(action.data.prompt)">
                    Copy OpenCode prompt
                  </button>
                  <span v-else class="chip" :class="action.ok ? 'success' : 'danger'">{{ action.tool }} {{ action.ok ? "done" : "failed" }}</span>
                  <button v-if="!action.ok" class="chip clickable" @click="askAgentToFixAction(action)"><Wrench :size="10" /> Fix</button>
                </template>
              </div>
              <div class="chat-message-actions">
                <span>{{ relativeTime(message.created_at) }}</span>
                <button v-if="message.role === 'user'" class="icon-btn" title="Edit and resubmit" @click="revertMessage(message, true)">
                  <Pencil :size="12" />
                </button>
                <button v-if="message.role === 'user'" class="icon-btn" title="Revert to this message" @click="revertMessage(message, false)">
                  <Undo2 :size="12" />
                </button>
                <button class="icon-btn" title="Delete message" @click="deleteMessage(message)">
                  <Trash2 :size="12" />
                </button>
                <button class="icon-btn" :title="copiedId === message.id ? 'Copied' : 'Copy message'" @click="copyMessage(message)">
                  <Check v-if="copiedId === message.id" :size="12" /><Copy v-else :size="12" />
                </button>
              </div>
            </div>
          </article>
          <div v-if="sending" class="chat-message assistant">
            <div class="chat-avatar"><Bot :size="15" /></div>
            <div class="chat-bubble-wrap"><div class="chat-bubble typing"><Loader2 :size="14" class="spin" /> Thinking locally…</div></div>
          </div>
          <div ref="messageEnd" />
        </div>

        <div class="chat-presets">
          <div class="row" style="gap: 5px; margin-bottom: 7px"><Wrench :size="12" class="muted" /><span class="small muted">AI workspaces</span></div>
          <div class="row" style="gap: 5px; flex-wrap: wrap">
            <button v-for="preset in presets" :key="preset.label" class="chip clickable" :title="`Use the ${preset.label} workspace prompt`" @click="usePreset(preset.prompt)">{{ preset.label }}</button>
          </div>
          <details class="chat-context">
            <summary>What the assistant knows</summary>
            <p>It knows the Audio (songwriting, DJ and SRT), Video/QVAC, Documents (PDF, translation and summary), Voice, Images, FFmpeg, yt-dlp, Files, Jobs and Settings workspaces, the complete external API, and which models and services must be enabled. It can execute whitelisted tools, inspect logs, repair services, read attachments, chain actions and generate OpenCode prompts for code-level fixes. Tool commands run on Qwen3 4B.</p>
          </details>
        </div>

        <div class="chat-composer">
          <div v-if="attachments.length" class="chat-attachments">
            <span v-for="(attachment, index) in attachments" :key="attachment.path" class="chip">
              <Paperclip :size="10" /> {{ attachment.name }}
              <button class="icon-btn" style="padding: 0; margin-left: 3px" title="Remove attachment" @click="removeAttachment(index)"><X :size="10" /></button>
            </span>
          </div>

          <textarea ref="composer" v-model="draft" class="textarea" rows="3" :disabled="!llmOnline" placeholder="Message your local model…  Shift+Enter for a new line" @keydown="onComposerKeydown" />
          <div class="row-between" style="margin-top: 8px">
            <span class="row small muted" style="gap: 7px"><Sparkles :size="11" /> {{ model }} · local session context
              <button class="icon-btn" title="Attach or choose a shared file" :disabled="attachments.length >= 8" @click="attachmentPickerOpen = true"><Paperclip :size="13" /></button>
            </span>
            <button class="btn btn-primary" :disabled="sending || !draft.trim() || !llmOnline" @click="send"><Loader2 v-if="sending" :size="14" class="spin" /><Send v-else :size="14" /> Send</button>
          </div>
        </div>
      </section>
    </div>
    <FilePicker v-model="attachmentPickerOpen" :start-path="attachmentStartPath" title="Attach files" kind="all" @selected="onAttachmentSelected" />
  </div>
</template>

<style scoped>
.chat-layout { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 14px; min-height: 680px; }
.chat-sidebar { display: flex; flex-direction: column; min-height: 0; }
.chat-sidebar-head { padding: 14px; }
.chat-sidebar .panel-body { overflow: auto; }
.chat-session { display: flex; align-items: flex-start; gap: 6px; padding: 9px 8px; border: 1px solid transparent; border-radius: 9px; cursor: pointer; }
.chat-session:hover { background: rgba(255,255,255,.035); }
.chat-session.active { background: rgba(139,92,246,.12); border-color: rgba(139,92,246,.35); }
.chat-session-title { display: block; width: 100%; padding: 0; border: 0; background: transparent; color: var(--text); text-align: left; font-weight: 650; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.chat-session-meta { display: flex; justify-content: space-between; gap: 6px; margin-top: 4px; color: var(--muted); font-size: 10px; }
.chat-delete { opacity: 0; flex: 0 0 auto; }
.chat-session:hover .chat-delete, .chat-session.active .chat-delete { opacity: 1; }
.chat-main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.chat-main-head { flex: 0 0 auto; }
.chat-error { margin: 10px 14px 0; display: flex; gap: 8px; align-items: center; }
.chat-transcript { flex: 1 1 auto; overflow: auto; padding: 18px 20px; min-height: 300px; max-height: 58vh; }
.chat-message { display: flex; align-items: flex-start; gap: 10px; margin: 0 auto 16px; max-width: 900px; }
.chat-message.user { flex-direction: row-reverse; }
.chat-avatar { display: grid; place-items: center; width: 28px; height: 28px; flex: 0 0 28px; border-radius: 8px; background: rgba(139,92,246,.16); color: #c4b5fd; }
.chat-message.user .chat-avatar { background: rgba(34,211,238,.12); color: #67e8f9; }
.chat-bubble-wrap { min-width: 0; max-width: min(760px, 86%); }
.chat-message.user .chat-bubble-wrap { text-align: right; }
.chat-bubble { display: inline-block; padding: 10px 13px; border: 1px solid var(--line); border-radius: 12px; background: rgba(17,21,30,.72); white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; font-size: 13px; text-align: left; }
.chat-message.user .chat-bubble { background: rgba(34,211,238,.08); border-color: rgba(34,211,238,.24); }
.chat-message.assistant .chat-bubble { border-top-left-radius: 4px; }
.chat-message.user .chat-bubble { border-top-right-radius: 4px; }
.chat-bubble.typing { display: inline-flex; align-items: center; gap: 7px; color: var(--muted); }
.chat-message-actions { display: flex; align-items: center; gap: 6px; margin-top: 3px; color: var(--muted); font-size: 10px; }
.chat-message-actions .icon-btn { opacity: 0; transition: opacity 120ms ease; }
.chat-message:hover .chat-message-actions .icon-btn, .chat-message-actions .icon-btn:focus-visible { opacity: 1; }
.chat-message.user .chat-message-actions { justify-content: flex-end; }
.chat-presets { flex: 0 0 auto; padding: 0 20px 9px; }
.chat-composer { flex: 0 0 auto; padding: 10px 20px 18px; border-top: 1px solid var(--line); }
.chat-composer .textarea { min-height: 72px; resize: vertical; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .chat-layout { grid-template-columns: 1fr; } .chat-transcript { max-height: 50vh; } }
</style>

<style scoped>
.chat-context { margin-top: 7px; color: var(--muted); font-size: 10px; }
.chat-context summary { cursor: pointer; }
.chat-context p { margin: 5px 0 0; line-height: 1.5; }
</style>

<style scoped>
.chat-attachments { display: flex; gap: 5px; flex-wrap: wrap; margin-bottom: 7px; }
.chat-agent-actions { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 5px; }
.chat-message-attachments { display: flex; gap: 6px; flex-wrap: wrap; align-items: flex-start; margin-top: 7px; }
.chat-message.user .chat-message-attachments { justify-content: flex-end; }
.chat-message-image { display: block; width: 148px; height: 106px; overflow: hidden; border: 1px solid var(--line-strong); border-radius: 9px; background: var(--panel-2); }
.chat-message-image img { display: block; width: 100%; height: 100%; object-fit: cover; transition: transform 150ms ease; }
.chat-message-image:hover img { transform: scale(1.04); }
</style>
