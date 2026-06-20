import { ref } from "vue";
import { defineStore } from "pinia";

const WIDTH_KEY = "fontsync_sidebar_width";
const OPEN_KEY = "fontsync_sidebar_open";

const MIN_WIDTH = 180;
const MAX_WIDTH = 360;

function clampWidth(w: number): number {
  return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, w));
}

/** État de la coquille (sidebar) — persistant entre sessions via localStorage. */
export const useLayoutStore = defineStore("layout", () => {
  const sidebarOpen = ref(localStorage.getItem(OPEN_KEY) !== "false");
  const sidebarWidth = ref(
    clampWidth(Number(localStorage.getItem(WIDTH_KEY)) || 220),
  );

  function setSidebarOpen(value: boolean) {
    sidebarOpen.value = value;
    localStorage.setItem(OPEN_KEY, String(value));
  }

  function toggleSidebar() {
    setSidebarOpen(!sidebarOpen.value);
  }

  function setSidebarWidth(value: number) {
    sidebarWidth.value = clampWidth(value);
    localStorage.setItem(WIDTH_KEY, String(sidebarWidth.value));
  }

  return {
    sidebarOpen,
    sidebarWidth,
    minWidth: MIN_WIDTH,
    maxWidth: MAX_WIDTH,
    setSidebarOpen,
    toggleSidebar,
    setSidebarWidth,
  };
});
