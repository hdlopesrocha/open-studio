export const DEMO = typeof __DEMO__ !== "undefined" ? __DEMO__ : false;

export interface ServiceInfo {
  name: string;
  label: string;
  category: string;
  online: boolean;
  status: string;
  version?: string | null;
  latency_ms?: number | null;
  detail?: string | null;
}

export interface SystemStatus {
  app: { name: string; version: string; uptime_seconds: number };
  setup_required: boolean;
  services: ServiceInfo[];
  online: number;
  total: number;
  queues?: {
    components: Array<{
      component: string;
      concurrency: number;
      queued: number;
      running: number;
      completed: number;
      failed: number;
    }>;
  };
  storage: { root: string; total: number; used: number; free: number; free_label: string };
  system: {
    cpu_percent: number;
    cpu_count: number;
    memory_total: number;
    memory_used: number;
    memory_percent: number;
    gpu: Array<{ name: string; memory_total_mb: number; memory_used_mb: number; driver: string }> | null;
  };
}

export interface JobArtifact {
  path: string;
  kind?: string;
  mime?: string;
  name?: string;
  size?: number;
}

export interface Job {
  id: string;
  component: string;
  action: string;
  title: string;
  status: "queued" | "running" | "canceling" | "completed" | "failed" | "canceled";
  stage?: string | null;
  message?: string | null;
  progress: number;
  params: Record<string, any>;
  result?: Record<string, any> | null;
  error?: string | null;
  warnings: string[];
  artifacts: JobArtifact[];
  cancel_requested: boolean;
  parent_id?: string | null;
  attempts: number;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at: string;
}

export interface FileInfo {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  size_label: string;
  modified: string;
  mime: string;
  kind: string;
  url: string;
  children?: number;
}

export interface AuthStatus {
  setup_required: boolean;
  authenticated: boolean;
  password_set_at: string | null;
  identity: { type: string; id: string } | null;
  version: string;
}

export interface Identity {
  authenticated: boolean;
  identity: { type: string; id: string };
  setup_at: string | null;
  version: string;
}
