import { defineStore } from "pinia";

export interface Toast {
  id: number;
  kind: "success" | "error" | "info";
  message: string;
}

let counter = 0;

export const useToastStore = defineStore("toasts", {
  state: () => ({ items: [] as Toast[] }),
  actions: {
    push(kind: Toast["kind"], message: string) {
      const id = ++counter;
      this.items.push({ id, kind, message });
      window.setTimeout(() => this.dismiss(id), 5200);
      return id;
    },
    success(message: string) {
      return this.push("success", message);
    },
    error(message: string) {
      return this.push("error", message);
    },
    info(message: string) {
      return this.push("info", message);
    },
    dismiss(id: number) {
      this.items = this.items.filter((item) => item.id !== id);
    },
  },
});
