<script setup lang="ts">
import { Moon, Sun } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { useTheme } from "@/composables/useTheme";

/** Bouton de thème du pied de la sidebar : un clic bascule clair ↔ sombre. */
const { t } = useI18n();
const { dark, toggleTheme } = useTheme();
</script>

<template>
  <button
    type="button"
    class="flex size-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
    :title="t('theme.quickSwitch')"
    :aria-label="t('theme.quickSwitch')"
    @click="toggleTheme"
  >
    <Sun v-if="dark" class="size-3.5" :stroke-width="1.5" />
    <Moon v-else class="size-3.5" :stroke-width="1.5" />
  </button>
</template>
