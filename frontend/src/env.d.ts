/// <reference types="vite/client" />

declare const __DEMO__: boolean;

interface ImportMetaEnv {
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
