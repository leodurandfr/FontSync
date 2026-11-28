<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  Copy,
  Download,
  Check,
  Loader2,
  RefreshCw,
  Sun,
  Moon,
  Monitor,
} from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { SectionLabel } from "@/components/ui/section-label";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import AccountSection from "@/components/settings/AccountSection.vue";
import DevicesSection from "@/components/settings/DevicesSection.vue";
import RemovalsSection from "@/components/settings/RemovalsSection.vue";
import UsersSection from "@/components/settings/UsersSection.vue";
import { useWsStore } from "@/stores/ws";
import { useAuthStore } from "@/stores/auth";
import { useTheme, type Theme } from "@/composables/useTheme";
import { useLocale } from "@/composables/useLocale";
import { useServerUpdate } from "@/composables/useServerUpdate";
import { useBackupHealth } from "@/composables/useBackupHealth";
import type { Locale } from "@/i18n";
import { storeToRefs } from "pinia";

const { t } = useI18n();

const wsStore = useWsStore();
const { status } = storeToRefs(wsStore);

const authStore = useAuthStore();

const { theme, setTheme } = useTheme();
const { locale, setLocale, dateLocale } = useLocale();

const {
  info,
  state: updateState,
  error: updateError,
  alreadyUpToDate,
  fetchInfo,
  update,
} = useServerUpdate();

const {
  health: backups,
  warning: backupWarning,
  fetchHealth: fetchBackups,
} = useBackupHealth();

onMounted(() => {
  void fetchInfo();
  void fetchBackups();
});

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(dateLocale.value, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function formatMegabytes(bytes: number): string {
  return new Intl.NumberFormat(dateLocale.value, {
    style: "unit",
    unit: "megabyte",
    maximumFractionDigits: 1,
  }).format(bytes / 1_000_000);
}

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
  <div class="scrollbar-thin h-full overflow-y-auto">
    <div class="mx-auto max-w-4xl space-y-10 px-4 pb-8 pt-14 sm:px-8 sm:py-10">
      <!-- Header -->
      <header>
        <h1 class="text-3xl font-semibold tracking-tight">
          {{ t("settings.title") }}
        </h1>
        <p class="mt-2 text-[13px] text-muted-foreground">
          {{ t("settings.subtitle") }}
        </p>
      </header>

      <!-- Apparence -->
      <section>
        <SectionLabel class="mb-3">{{ t("settings.appearance") }}</SectionLabel>
        <Panel class="space-y-4 p-6">
          <div class="flex items-center justify-between gap-4">
            <div>
              <p class="text-[13px] font-medium">{{ t("settings.theme") }}</p>
              <p class="text-[13px] text-muted-foreground">
                {{ t("settings.themeDesc") }}
              </p>
            </div>
            <ToggleGroup
              type="single"
              :spacing="0.5"
              class="rounded-lg bg-segment-track p-0.5"
              :model-value="theme"
              @update:model-value="onThemeChange"
            >
              <ToggleGroupItem
                v-for="option in themeOptions"
                :key="option.value"
                :value="option.value"
                :aria-label="option.label"
                class="h-7 gap-1.5 rounded-md px-3 text-[12px] font-medium text-muted-foreground hover:bg-transparent hover:text-foreground data-[state=on]:bg-segment-thumb data-[state=on]:text-foreground data-[state=on]:shadow-[0_1px_2px_rgba(0,0,0,0.12)]"
              >
                <component
                  :is="option.icon"
                  class="size-3.5"
                  :stroke-width="1.75"
                />
                <span class="hidden sm:inline">{{ option.label }}</span>
              </ToggleGroupItem>
            </ToggleGroup>
          </div>

          <div class="flex items-center justify-between gap-4">
            <div>
              <p class="text-[13px] font-medium">
                {{ t("settings.language") }}
              </p>
              <p class="text-[13px] text-muted-foreground">
                {{ t("settings.languageDesc") }}
              </p>
            </div>
            <ToggleGroup
              type="single"
              :spacing="0.5"
              class="rounded-lg bg-segment-track p-0.5"
              :model-value="locale"
              @update:model-value="onLocaleChange"
            >
              <ToggleGroupItem
                v-for="option in localeOptions"
                :key="option.value"
                :value="option.value"
                :aria-label="option.label"
                class="h-7 gap-1.5 rounded-md px-3 text-[12px] font-medium text-muted-foreground hover:bg-transparent hover:text-foreground data-[state=on]:bg-segment-thumb data-[state=on]:text-foreground data-[state=on]:shadow-[0_1px_2px_rgba(0,0,0,0.12)]"
              >
                {{ option.label }}
              </ToggleGroupItem>
            </ToggleGroup>
          </div>
        </Panel>
      </section>

      <!-- Appareils -->
      <DevicesSection />
      <RemovalsSection />

      <!-- Server info -->
      <section>
        <SectionLabel class="mb-3">{{ t("settings.server") }}</SectionLabel>
        <Panel class="space-y-4 p-6">
          <div>
            <SectionLabel as="p" class="mb-1.5">{{
              t("settings.serverUrl")
            }}</SectionLabel>
            <div class="flex items-center gap-2">
              <code
                class="flex-1 rounded-lg border border-separator bg-muted/50 px-3 py-2 font-mono text-[13px]"
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
            <SectionLabel as="p" class="mb-1.5">{{
              t("settings.websocket")
            }}</SectionLabel>
            <Badge :variant="wsStatusVariant">{{ wsStatusLabel }}</Badge>
          </div>

          <!-- Version et mise à jour. La mise à jour recrée le conteneur qui
               sert cette page : l'attente est normale, on l'annonce. -->
          <div>
            <SectionLabel as="p" class="mb-1.5">{{
              t("settings.version")
            }}</SectionLabel>
            <div class="flex flex-wrap items-center gap-3">
              <code
                class="rounded-lg border border-separator bg-muted/50 px-3 py-2 font-mono text-[13px]"
              >
                {{ info?.version ?? "…" }}
              </code>
              <Button
                v-if="info?.updateAvailable && authStore.isAdmin"
                variant="outline"
                :disabled="
                  updateState === 'requesting' || updateState === 'restarting'
                "
                @click="update()"
              >
                <Loader2
                  v-if="
                    updateState === 'requesting' || updateState === 'restarting'
                  "
                  class="mr-2 h-4 w-4 animate-spin"
                />
                <RefreshCw v-else class="mr-2 h-4 w-4" />
                {{ t("settings.updateServer") }}
              </Button>
            </div>

            <p
              v-if="updateState === 'restarting'"
              class="mt-2 text-[13px] text-muted-foreground"
            >
              {{ t("settings.updateRestarting") }}
            </p>
            <p
              v-else-if="updateState === 'done' && alreadyUpToDate"
              class="mt-2 text-[13px] text-muted-foreground"
            >
              {{ t("settings.updateAlreadyCurrent") }}
            </p>
            <p
              v-else-if="updateState === 'done'"
              class="mt-2 text-[13px] text-muted-foreground"
            >
              {{ t("settings.updateDone", { version: info?.version ?? "" }) }}
            </p>
            <p
              v-else-if="updateState === 'error'"
              class="mt-2 text-[13px] text-destructive"
            >
              {{
                updateError === "timeout"
                  ? t("settings.updateTimeout")
                  : updateError
              }}
            </p>
            <p
              v-else-if="info && !info.updateAvailable && authStore.isAdmin"
              class="mt-2 text-[13px] text-muted-foreground"
            >
              {{ t("settings.updateNotConfigured") }}
            </p>
          </div>

          <!-- Sauvegardes automatiques. Masqué si le serveur ne connaît pas la
               route (version antérieure) ; avertit si rien de récent. -->
          <div v-if="backups">
            <SectionLabel as="p" class="mb-1.5">{{
              t("settings.backups")
            }}</SectionLabel>
            <p
              v-if="!backups.enabled"
              class="text-[13px] text-muted-foreground"
            >
              {{ t("settings.backupsDisabled") }}
            </p>
            <template v-else>
              <p class="text-[13px]">
                {{
                  backups.lastSnapshotAt
                    ? t("settings.backupsLast", {
                        date: formatDateTime(backups.lastSnapshotAt),
                        size: formatMegabytes(backups.lastSnapshotBytes ?? 0),
                      })
                    : t("settings.backupsNone")
                }}
              </p>
              <p
                v-if="backups.lastMirrorAt"
                class="mt-1 text-[13px] text-muted-foreground"
              >
                {{
                  t("settings.backupsMirror", {
                    date: formatDateTime(backups.lastMirrorAt),
                    copied: backups.mirrorCopied ?? 0,
                    repaired: backups.mirrorRepaired ?? 0,
                    failed: backups.mirrorFailed ?? 0,
                  })
                }}
              </p>
              <p
                v-if="backupWarning"
                role="alert"
                class="mt-2 text-[13px] text-destructive"
              >
                <template v-if="backupWarning === 'stale'">{{
                  backups.lastSnapshotAt
                    ? t("settings.backupsStale")
                    : t("settings.backupsNeverOk")
                }}</template>
                <template v-else-if="backupWarning === 'error'">{{
                  t("settings.backupsError", { error: backups.lastError ?? "" })
                }}</template>
                <template v-else>{{
                  t(
                    "settings.backupsMirrorFailed",
                    { n: backups.mirrorFailed ?? 0 },
                    backups.mirrorFailed ?? 0,
                  )
                }}</template>
              </p>
              <p
                v-if="backupWarning === 'stale' && backups.lastError"
                class="mt-1 break-words font-mono text-[12px] text-muted-foreground"
              >
                {{ backups.lastError }}
              </p>
            </template>
          </div>
        </Panel>
      </section>

      <!-- Comptes -->
      <AccountSection />
      <UsersSection v-if="authStore.isAdmin" />

      <!-- Agent download -->
      <section>
        <SectionLabel class="mb-3">{{ t("settings.agent") }}</SectionLabel>
        <Panel class="space-y-4 p-6">
          <p class="text-[13px] text-muted-foreground">
            {{ t("settings.agentDesc") }}
          </p>

          <Button
            variant="outline"
            disabled
            class="h-auto min-h-9 max-w-full whitespace-normal py-2 text-left"
          >
            <Download class="mr-2 h-4 w-4" />
            {{ t("settings.downloadAgent") }}
          </Button>
          <p class="text-xs text-muted-foreground">
            {{ t("settings.agentSoon") }}
          </p>
        </Panel>
      </section>
    </div>
  </div>
</template>
