import { defineStore } from "pinia";
import { api } from "@/lib/api";
import type { AuthStatus, Identity } from "@/lib/types";
import { DEMO, demoAuthStatus } from "@/lib/demo";

export const useAuthStore = defineStore("auth", {
  state: () => ({
    status: null as AuthStatus | null,
    identity: null as Identity | null,
    loading: false,
    error: "",
    ready: false,
  }),
  getters: {
    authenticated: (state) => Boolean(state.status?.authenticated),
    setupRequired: (state) => Boolean(state.status?.setup_required),
  },
  actions: {
    async load() {
      this.loading = true;
      this.error = "";
      if (DEMO) {
        const demoAuth = new URLSearchParams(window.location.search).get("demo-auth");
        if (demoAuth === "setup") {
          this.status = { ...demoAuthStatus, setup_required: true, authenticated: false, identity: null, password_set_at: null } as AuthStatus;
          this.identity = null;
        } else if (demoAuth === "login") {
          this.status = { ...demoAuthStatus, setup_required: false, authenticated: false, identity: null } as AuthStatus;
          this.identity = null;
        } else {
          this.status = demoAuthStatus as AuthStatus;
          this.identity = { authenticated: true, identity: { type: "session", id: "demo_session" }, setup_at: demoAuthStatus.password_set_at, version: "1.0.0" };
        }
        this.loading = false;
        this.ready = true;
        return;
      }
      try {
        this.status = await api.get<AuthStatus>("/auth/status");
        if (this.status.authenticated) {
          this.identity = await api.get<Identity>("/auth/me");
        } else {
          this.identity = null;
        }
      } catch (error: any) {
        this.error = error?.message || "Cannot reach the Open Studio gateway";
      } finally {
        this.loading = false;
        this.ready = true;
      }
    },
    async setup(password: string, confirm: string) {
      this.error = "";
      await api.post("/auth/setup", { password, confirm });
      await this.load();
    },
    async login(password: string) {
      this.error = "";
      await api.post("/auth/login", { password });
      await this.load();
    },
    async logout() {
      await api.post("/auth/logout");
      this.status = null;
      this.identity = null;
      await this.load();
    },
    async changePassword(currentPassword: string, newPassword: string) {
      await api.post("/auth/change-password", { current_password: currentPassword, new_password: newPassword });
      await this.load();
    },
  },
});
