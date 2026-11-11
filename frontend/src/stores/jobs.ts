import { defineStore } from "pinia";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";
import { DEMO, demoJobs, demoStatus } from "@/lib/demo";

const ACTIVE = new Set(["queued", "running", "canceling"]);

export const useJobsStore = defineStore("jobs", {
  state: () => ({
    items: [] as Job[],
    total: 0,
    queues: [] as any[],
    loading: false,
    error: "",
    source: null as EventSource | null,
    connected: false,
    reconnectTimer: 0 as any,
    filter: "active" as "active" | "all" | "completed" | "failed",
  }),
  getters: {
    active: (state) => state.items.filter((job) => ACTIVE.has(job.status)),
    activeCount: (state) => state.items.filter((job) => ACTIVE.has(job.status)).length,
    byId: (state) => (id: string) => state.items.find((job) => job.id === id),
    recent: (state) => [...state.items].sort((a, b) => b.created_at.localeCompare(a.created_at)),
    filtered: (state) => {
      if (state.filter === "all") return state.items;
      if (state.filter === "active") return state.items.filter((job) => ACTIVE.has(job.status));
      if (state.filter === "completed") return state.items.filter((job) => job.status === "completed");
      return state.items.filter((job) => job.status === "failed" || job.status === "canceled");
    },
  },
  actions: {
    upsert(job: Job) {
      const index = this.items.findIndex((item) => item.id === job.id);
      if (index >= 0) this.items[index] = job;
      else this.items.unshift(job);
      if (this.items.length > 300) this.items.length = 300;
    },
    async refresh() {
      this.loading = true;
      this.error = "";
      if (DEMO) {
        this.items = demoJobs;
        this.total = demoJobs.length;
        this.queues = demoStatus.queues?.components || [];
        this.loading = false;
        return;
      }
      try {
        const data = await api.get<{ items: Job[]; total: number }>("/jobs?limit=150");
        this.items = data.items;
        this.total = data.total;
        await this.loadQueues();
      } catch (error: any) {
        this.error = error?.message || "Could not load jobs";
      } finally {
        this.loading = false;
      }
    },
    async loadQueues() {
      if (DEMO) {
        this.queues = demoStatus.queues?.components || [];
        return;
      }
      try {
        const data = await api.get<{ components: any[] }>("/jobs/queues");
        this.queues = data.components;
      } catch {
        this.queues = [];
      }
    },
    connect() {
      if (DEMO) {
        this.connected = true;
        return;
      }
      if (this.source) return;
      this.disconnect();
      const source = new EventSource("/api/jobs/events");
      this.source = source;
      const handle = (event: MessageEvent) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.job) this.upsert(payload.job);
        } catch {}
      };
      source.addEventListener("job.created", handle as any);
      source.addEventListener("job.updated", handle as any);
      source.onopen = () => {
        this.connected = true;
      };
      source.onerror = () => {
        this.connected = false;
        source.close();
        this.source = null;
        window.clearTimeout(this.reconnectTimer);
        this.reconnectTimer = window.setTimeout(() => this.connect(), 4000);
      };
    },
    disconnect() {
      if (this.source) {
        this.source.close();
        this.source = null;
      }
      this.connected = false;
      window.clearTimeout(this.reconnectTimer);
    },
    async submit(component: string, action: string, title: string, params: Record<string, any>) {
      const job = await api.post<Job>("/jobs", { component, action, title, params });
      this.upsert(job);
      this.connect();
      return job;
    },
    async cancel(id: string) {
      const job = await api.post<Job>(`/jobs/${id}/cancel`);
      this.upsert(job);
      return job;
    },
    async retry(id: string) {
      const job = await api.post<Job>(`/jobs/${id}/retry`);
      this.upsert(job);
      return job;
    },
    async remove(id: string) {
      await api.delete(`/jobs/${id}`);
      this.items = this.items.filter((job) => job.id !== id);
    },
  },
});

export function isActive(job: Job | null | undefined): boolean {
  return Boolean(job && ACTIVE.has(job.status));
}
