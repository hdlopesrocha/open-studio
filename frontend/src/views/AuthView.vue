<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowRight, Eye, EyeOff, KeyRound, Loader2, ShieldCheck } from "lucide-vue-next";
import { useAuthStore } from "@/stores/auth";
import { useToastStore } from "@/stores/toasts";

const props = defineProps<{ mode: "setup" | "login" }>();
const auth = useAuthStore();
const toasts = useToastStore();
const router = useRouter();
const route = useRoute();

const password = ref("");
const confirm = ref("");
const show = ref(false);
const busy = ref(false);
const error = ref("");

const isSetup = computed(() => props.mode === "setup");
const canSubmit = computed(() => {
  if (password.value.length < 8) return false;
  if (isSetup.value && password.value !== confirm.value) return false;
  return true;
});

watch(
  () => props.mode,
  () => {
    password.value = "";
    confirm.value = "";
    error.value = "";
  },
);

async function submit() {
  if (!canSubmit.value) return;
  busy.value = true;
  error.value = "";
  try {
    if (isSetup.value) {
      await auth.setup(password.value, confirm.value);
      toasts.success("Open Studio is protected. Welcome.");
    } else {
      await auth.login(password.value);
    }
    const next = typeof route.query.next === "string" ? route.query.next : "/";
    router.push(next);
  } catch (err: any) {
    error.value = err?.message || "Authentication failed";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="brand-mark" style="width: 48px; height: 48px">
        <svg width="26" height="26" viewBox="0 0 64 64" aria-hidden="true">
          <circle cx="32" cy="32" r="17" fill="none" stroke="url(#authGrad)" stroke-width="4" />
          <circle cx="32" cy="32" r="6" fill="url(#authGrad)" />
          <defs>
            <linearGradient id="authGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stop-color="#a78bfa" />
              <stop offset="0.6" stop-color="#22d3ee" />
              <stop offset="1" stop-color="#f59e0b" />
            </linearGradient>
          </defs>
        </svg>
      </div>
      <h1>{{ isSetup ? "Create your studio password" : "Welcome back" }}</h1>
      <p v-if="isSetup">
        Open Studio is single-user and local-first. Set a password now to protect the app, every API and all of your files.
        This is the first and only time you will see this screen.
      </p>
      <p v-else>Enter the password you created on first use. Your data never leaves this machine.</p>

      <form @submit.prevent="submit">
        <div class="field">
          <label for="password">{{ isSetup ? "New password" : "Password" }}</label>
          <div class="input-group">
            <input
              id="password"
              v-model="password"
              class="input"
              :type="show ? 'text' : 'password'"
              autocomplete="current-password"
              :placeholder="isSetup ? 'At least 8 characters' : 'Your studio password'"
              autofocus
            />
            <button type="button" class="icon-btn" @click="show = !show" :title="show ? 'Hide' : 'Show'">
              <EyeOff v-if="show" :size="16" />
              <Eye v-else :size="16" />
            </button>
          </div>
        </div>
        <div v-if="isSetup" class="field">
          <label for="confirm">Confirm password</label>
          <input id="confirm" v-model="confirm" class="input" :type="show ? 'text' : 'password'" autocomplete="new-password" placeholder="Repeat the password" />
        </div>
        <div v-if="error" class="alert error">{{ error }}</div>
        <button class="btn btn-primary btn-lg btn-block" :disabled="!canSubmit || busy" type="submit">
          <Loader2 v-if="busy" :size="16" class="spin" />
          <ShieldCheck v-else-if="isSetup" :size="16" />
          <KeyRound v-else :size="16" />
          {{ isSetup ? "Protect my studio" : "Unlock studio" }}
          <ArrowRight :size="15" v-if="!busy" />
        </button>
      </form>

      <div class="row" style="margin-top: 18px; gap: 7px; justify-content: center">
        <span class="chip"><ShieldCheck :size="11" /> Local only</span>
        <span class="chip">Scrypt password</span>
        <span class="chip">Session cookie</span>
      </div>
      <p v-if="isSetup" class="small muted" style="margin-top: 16px; text-align: center">
        You can change it later in Settings → Security. API keys for external clients are also managed there.
      </p>
    </div>
  </div>
</template>

<style scoped>
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
