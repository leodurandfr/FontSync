<script setup lang="ts">
import { computed, ref } from "vue";
import {
  Copy,
  Download,
  Server,
  Check,
  KeyRound,
  Palette,
  Sun,
  Moon,
  Monitor,
  Languages,
} from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import DevicesSection from "@/components/settings/DevicesSection.vue";
import { useWsStore } from "@/stores/ws";
import { useAuthStore } from "@/stores/auth";
import { useTheme, type Theme } from "@/composables/useTheme";
import { useLocale } from "@/composables/useLocale";
import type { Locale } from "@/i18n";
import { storeToRefs } from "pinia";

const { t } = useI18n();

const wsStore = useWsStore();
const { status } = storeToRefs(wsStore);

const authStore = useAuthStore();

const { theme, setTheme } = useTheme();
const { locale, setLocale } = useLocale();

const themeOptions = computed<
  { value: Theme; label: string; icon: typeof Sun }[]
>(() => [
  { value: "light", label: t("theme.light"), icon: Sun },
  { value: "dark", label: t("theme.dark"), icon: Moon },
  { value: "system", label: t("theme.system"), icon: Monitor },
]);

const localeOptions: { value: Locale; label: string }[] = [
  { value: "en", label: "English" },
  { value: "fr", label: "Français" },
];

function onThemeChange(value: unknown) {
  // ToggleGroup `single` peut émettre une valeur vide si on déclique l'option
  // active : on ignore ce cas pour garder un thème toujours sélectionné.
  if (value === "light" || value === "dark" || value === "system") {
    setTheme(value);
  }
}

function onLocaleChange(value: unknown) {
  if (value === "en" || value === "fr") {
    setLocale(value);
  }
}

// Redemander le token : on efface celui mémorisé, ce qui réaffiche l'écran de
// saisie (App.vue gate sur `needsToken`).
function changeToken() {
  authStore.clearToken();
}

const serverUrl = computed(() => window.location.origin);
const copied = ref(false);

async function copyUrl() {
  await navigator.clipboard.writeText(serverUrl.value);
  copied.value = true;
  setTimeout(() => (copied.value = false), 2000);
}

const wsStatusLabel = computed(() => {
  switch (status.value) {
    case "connected":
      return t("settings.wsConnected");
    case "connecting":
      return t("settings.wsConnecting");
    default:
      return t("settings.wsDisconnected");
  }
});

const wsStatusVariant = computed<"default" | "secondary" | "destructive">(
  () => {
    switch (status.value) {
      case "connected":
        return "default";
      case "connecting":
        return "secondary";
      default:
        return "destructive";
    }
  },
);
</script>

<template>
  <div class="mx-auto max-w-3xl px-4 py-8 sm:px-6">
    <h1 class="text-3xl font-bold tracking-tight">{{ t("settings.title") }}</h1>
    <p class="text-muted-foreground mt-1">
      {{ t("settings.subtitle") }}
    </p>

    <div class="mt-8 space-y-6">
      <!-- Apparence -->
      <div class="rounded-xl border bg-card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <Palette class="h-5 w-5 text-muted-foreground" />
          <h2 class="text-lg font-semibold">{{ t("settings.appearance") }}</h2>
        </div>

        <div class="flex items-center justify-between gap-4">
          <div>
            <p class="text-sm font-medium">{{ t("settings.theme") }}</p>
            <p class="text-sm text-muted-foreground">
              {{ t("settings.themeDesc") }}
            </p>
          </div>
          <ToggleGroup
            type="single"
            variant="outline"
            :model-value="theme"
            @update:model-value="onThemeChange"
          >
            <ToggleGroupItem
              v-for="option in themeOptions"
              :key="option.value"
              :value="option.value"
              :aria-label="option.label"
            >
              <component :is="option.icon" class="h-4 w-4 sm:mr-1.5" />
              <span class="hidden sm:inline">{{ option.label }}</span>
            </ToggleGroupItem>
          </ToggleGroup>
        </div>

        <div class="flex items-center justify-between gap-4">
          <div>
            <p class="text-sm font-medium">{{ t("settings.language") }}</p>
            <p class="text-sm text-muted-foreground">
              {{ t("settings.languageDesc") }}
            </p>
          </div>
          <ToggleGroup
            type="single"
            variant="outline"
            :model-value="locale"
            @update:model-value="onLocaleChange"
          >
            <ToggleGroupItem
              v-for="option in localeOptions"
              :key="option.value"
              :value="option.value"
              :aria-label="option.label"
            >
              <Languages class="h-4 w-4 sm:mr-1.5" />
              <span class="hidden sm:inline">{{ option.label }}</span>
            </ToggleGroupItem>
          </ToggleGroup>
        </div>
      </div>

      <!-- Appareils -->
      <DevicesSection />

      <!-- Server info -->
      <div class="rounded-xl border bg-card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <Server class="h-5 w-5 text-muted-foreground" />
          <h2 class="text-lg font-semibold">{{ t("settings.server") }}</h2>
        </div>

        <div class="space-y-3">
          <div>
            <p class="text-sm text-muted-foreground mb-1">
              {{ t("settings.serverUrl") }}
            </p>
            <div class="flex items-center gap-2">
              <code
                class="flex-1 rounded-lg border bg-muted/50 px-3 py-2 text-sm font-mono"
              >
                {{ serverUrl }}
              </code>
              <Button variant="outline" size="icon" @click="copyUrl">
                <Check v-if="copied" class="h-4 w-4 text-green-500" />
                <Copy v-else class="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div>
            <p class="text-sm text-muted-foreground mb-1">
              {{ t("settings.websocket") }}
            </p>
            <Badge :variant="wsStatusVariant">{{ wsStatusLabel }}</Badge>
          </div>
        </div>
      </div>

      <!-- Token d'accès -->
      <div class="rounded-xl border bg-card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <KeyRound class="h-5 w-5 text-muted-foreground" />
          <h2 class="text-lg font-semibold">
            {{ t("settings.accessToken") }}
          </h2>
        </div>

        <i18n-t
          keypath="settings.tokenDesc"
          tag="p"
          class="text-sm text-muted-foreground"
          scope="global"
        >
          <template #code
            ><code class="font-mono">FONTSYNC_TOKEN</code></template
          >
        </i18n-t>

        <Button variant="outline" @click="changeToken">
          <KeyRound class="mr-2 h-4 w-4" />
          {{ t("settings.changeToken") }}
        </Button>
      </div>

      <!-- Agent download -->
      <div class="rounded-xl border bg-card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <Download class="h-5 w-5 text-muted-foreground" />
          <h2 class="text-lg font-semibold">{{ t("settings.agent") }}</h2>
        </div>

        <p class="text-sm text-muted-foreground">
          {{ t("settings.agentDesc") }}
        </p>

        <Button variant="outline" disabled>
          <Download class="mr-2 h-4 w-4" />
          {{ t("settings.downloadAgent") }}
        </Button>
        <p class="text-xs text-muted-foreground">
          {{ t("settings.agentSoon") }}
        </p>
      </div>
    </div>
  </div>
</template>
