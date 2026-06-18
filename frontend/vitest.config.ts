import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vitest/config";

// Config de test dédiée (séparée de `vite.config.ts` pour ne pas toucher au
// build) : les tests unitaires de l'auth (store + `apiFetch`) tournent sous
// jsdom (localStorage, fetch global).
export default defineConfig({
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
