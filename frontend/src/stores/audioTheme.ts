import { defineStore } from "pinia";

export interface AudioBands {
  bass: number;
  drums: number;
  snare: number;
  voice: number;
  air: number;
}

const DEFAULTS = {
  accent: "#8b5cf6",
  accent2: "#22d3ee",
  accent3: "#f59e0b",
};

function clamp(value: number): number {
  return Math.max(0, Math.min(1, Number(value) || 0));
}

function hsl(h: number, s: number, l: number): string {
  return `hsl(${Math.round((h + 360) % 360)} ${Math.round(s)}% ${Math.round(l)}%)`;
}

export const useAudioThemeStore = defineStore("audioTheme", {
  state: () => ({
    activeId: "",
    active: false,
    bands: { bass: 0, drums: 0, snare: 0, voice: 0, air: 0 } as AudioBands,
    energy: 0,
  }),
  actions: {
    begin(id: string) {
      this.activeId = id;
      this.active = true;
    },
    update(id: string, bands: AudioBands) {
      if (this.activeId !== id) return;
      const bass = clamp(bands.bass);
      const drums = clamp(bands.drums);
      const snare = clamp(bands.snare);
      const voice = clamp(bands.voice);
      const air = clamp(bands.air);
      this.bands = { bass, drums, snare, voice, air };
      this.energy = clamp(bass * 0.38 + drums * 0.22 + snare * 0.14 + voice * 0.16 + air * 0.1);
      const root = document.documentElement;
      const hue = 248 + bass * 74 + voice * 24 - air * 25;
      root.style.setProperty("--accent", hsl(hue, 76 + snare * 18, 60 + voice * 8));
      root.style.setProperty("--accent-2", hsl(hue + 58 + air * 82, 72 + snare * 20, 56 + air * 8));
      root.style.setProperty("--accent-3", hsl(hue - 52 + snare * 90, 78 + drums * 15, 57 + snare * 8));
      root.style.setProperty("--audio-bass", String(bass));
      root.style.setProperty("--audio-drums", String(drums));
      root.style.setProperty("--audio-snare", String(snare));
      root.style.setProperty("--audio-voice", String(voice));
      root.style.setProperty("--audio-air", String(air));
      root.style.setProperty("--audio-energy", String(this.energy));
    },
    reset(id: string) {
      if (id && this.activeId !== id) return;
      this.activeId = "";
      this.active = false;
      this.energy = 0;
      this.bands = { bass: 0, drums: 0, snare: 0, voice: 0, air: 0 };
      const root = document.documentElement;
      root.style.setProperty("--accent", DEFAULTS.accent);
      root.style.setProperty("--accent-2", DEFAULTS.accent2);
      root.style.setProperty("--accent-3", DEFAULTS.accent3);
      root.style.setProperty("--audio-bass", "0");
      root.style.setProperty("--audio-drums", "0");
      root.style.setProperty("--audio-snare", "0");
      root.style.setProperty("--audio-voice", "0");
      root.style.setProperty("--audio-air", "0");
      root.style.setProperty("--audio-energy", "0");
    },
  },
});
