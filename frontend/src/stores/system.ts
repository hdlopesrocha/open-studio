import { defineStore } from "pinia";
import { api } from "@/lib/api";
import type { SystemStatus } from "@/lib/types";
import { DEMO, demoStatus } from "@/lib/demo";

export const useSystemStore = defineStore("system", {
  state: () => ({
    status: null as SystemStatus | null,
    loading: false,
    error: "",
    lastLoaded: 0,
  }),
  getters: {
    services: (state) => state.status?.services || [],
    online: (state) => state.status?.online || 0,
    total: (state) => state.status?.total || 0,
    healthy: (state) => Boolean(state.status && state.status.online === state.status.total),
    service: (state) => (name: string) => state.status?.services.find((service) => service.name === name) || null,
  },
  actions: {
    async load(force = false) {
      if (!force && Date.now() - this.lastLoaded < 8000) return;
      this.loading = true;
      this.error = "";
      if (DEMO) {
        this.status = demoStatus;
        this.lastLoaded = Date.now();
        this.loading = false;
        return;
      }
      try {
        this.status = await api.get<SystemStatus>("/status");
        this.lastLoaded = Date.now();
      } catch (error: any) {
        this.error = error?.message || "Could not load system status";
      } finally {
        this.loading = false;
      }
    },
    startPolling() {
      this.load(true);
      const timer = window.setInterval(() => this.load(true), 20000);
      return () => window.clearInterval(timer);
    },
  },
});
