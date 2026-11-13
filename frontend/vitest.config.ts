import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";

// Config de test dédiée (séparée de `vite.config.ts` pour ne pas toucher au
// build) : les tests unitaires de l'auth (store + `apiFetch`) tournent sous
// jsdom (localStorage, fetch global). Le plugin Vue permet de monter un
// composant `.vue` (rendu de la ligne d'état des appareils, P1-3g).
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.spec.ts"],
  },
});
