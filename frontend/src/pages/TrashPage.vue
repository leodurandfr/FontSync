<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import {
  AlertTriangle,
  ArrowLeft,
  Loader2,
  RotateCcw,
  Trash2,
} from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { SectionLabel } from "@/components/ui/section-label";
import { Skeleton } from "@/components/ui/skeleton";
import { useTrashStore } from "@/stores/trash";
import { useDevicesStore } from "@/stores/devices";
import { useLocale } from "@/composables/useLocale";
import type { Font, PurgeResult } from "@/types/api";

const { t } = useI18n();
const { dateLocale } = useLocale();

const trash = useTrashStore();
const devices = useDevicesStore();

const busy = ref<Set<string>>(new Set());
const bulkBusy = ref(false);
const actionError = ref<string | null>(null);
const emptyOutcome = ref<PurgeResult | null>(null);

onMounted(() => {
  trash.fetchTrash();
  devices.fetchDevices();
});

/**
 * Restaurer remet la police dans la bibliothèque ; encore faut-il qu'une machine
 * la réinstalle. Celles dont le « pull automatique » est coupé ne le feront pas,
 * et le silence passerait pour un bug. On le dit plutôt que de forcer : couper
 * ce réglage est un choix explicite de l'utilisateur.
 */
const devicesWithoutAutoPull = computed(() =>
  devices.devices.filter((d) => !d.autoPull).map((d) => d.name),
);

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString(dateLocale.value, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function label(font: Font): string {
  return font.fullName || font.familyName || font.originalFilename;
}

function markBusy(id: string, active: boolean) {
  const next = new Set(busy.value);
  if (active) next.add(id);
  else next.delete(id);
  busy.value = next;
}

async function run(id: string, action: () => Promise<void>) {
  actionError.value = null;
  markBusy(id, true);
  try {
    await action();
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e);
  } finally {
    markBusy(id, false);
  }
}

async function runBulk(action: () => Promise<void>) {
  actionError.value = null;
  bulkBusy.value = true;
  try {
    await action();
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e);
  } finally {
    bulkBusy.value = false;
  }
}

async function emptyTrash() {
  // Remis à zéro d'abord : en cas d'échec, le bilan du vidage précédent ne doit
  // pas rester affiché sous le message d'erreur.
  emptyOutcome.value = null;
  emptyOutcome.value = await trash.emptyTrash();
}
</script>

<template>
  <div class="scrollbar-thin h-full overflow-y-auto">
    <div class="mx-auto max-w-4xl space-y-8 px-4 py-8 sm:px-8 sm:py-10">
      <header>
        <RouterLink
          :to="{ name: 'fonts' }"
          class="mb-5 inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.12em] text-foreground-subtle transition-colors hover:text-foreground"
        >
          <ArrowLeft class="size-3" :stroke-width="2" />
          {{ t("common.back") }}
        </RouterLink>

        <h1 class="text-3xl font-semibold tracking-tight">
          {{ t("trash.title") }}
        </h1>
        <p class="mt-2 text-[13px] text-muted-foreground">
          {{ t("trash.subtitle") }}
        </p>
      </header>

      <!-- Quarantaines retenues par le seuil : le seul écran où l'utilisateur
           peut rendre une suppression destructrice ailleurs. -->
      <Panel
        v-if="trash.pendingConfirmation > 0"
        class="space-y-3 border-amber-500/40 p-6"
      >
        <div class="flex items-start gap-3">
          <AlertTriangle class="mt-0.5 size-4 shrink-0 text-amber-500" />
          <div class="space-y-1">
            <p class="text-[13px] font-medium">
              {{ t("trash.pendingTitle", { n: trash.pendingConfirmation }) }}
            </p>
            <p class="text-[13px] text-muted-foreground">
              {{ t("trash.pendingDesc") }}
            </p>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          :disabled="bulkBusy"
          @click="runBulk(() => trash.confirmPending())"
        >
          <Loader2 v-if="bulkBusy" class="mr-2 size-4 animate-spin" />
          {{ t("trash.confirmPending") }}
        </Button>
      </Panel>

      <section>
        <div class="mb-3 flex items-center justify-between gap-4">
          <SectionLabel>{{ t("trash.deletedFonts") }}</SectionLabel>
          <Button
            v-if="trash.items.length"
            variant="outline"
            size="sm"
            :disabled="bulkBusy"
            @click="runBulk(emptyTrash)"
          >
            <Trash2 class="mr-2 size-4" />
            {{ t("trash.empty") }}
          </Button>
        </div>

        <Panel class="space-y-4 p-6">
          <p class="text-[13px] text-muted-foreground">
            {{ t("trash.emptyExplainer") }}
          </p>

          <!-- Un vidage qui épargne des lignes doit dire lesquelles, sinon
               l'écran donne l'impression d'avoir échoué à moitié. -->
          <p v-if="emptyOutcome" class="text-[13px] text-foreground">
            {{ t("trash.emptyDone", { n: emptyOutcome.purged }) }}
            <template v-if="emptyOutcome.retained">
              {{ t("trash.emptyRetained", { n: emptyOutcome.retained }) }}
            </template>
          </p>

          <p
            v-if="devicesWithoutAutoPull.length"
            class="text-[13px] text-muted-foreground"
          >
            {{
              t("trash.restoreAutoPullNote", {
                devices: devicesWithoutAutoPull.join(", "),
              })
            }}
          </p>

          <p v-if="actionError" class="text-[13px] text-destructive">
            {{ actionError }}
          </p>

          <div v-if="trash.loading" class="space-y-2">
            <Skeleton v-for="i in 3" :key="i" class="h-14 w-full rounded-lg" />
          </div>

          <div
            v-else-if="trash.isEmpty"
            class="rounded-lg border border-dashed border-separator p-8 text-center"
          >
            <p class="text-muted-foreground">{{ t("trash.none") }}</p>
          </div>

          <div v-else class="space-y-2">
            <div
              v-for="font in trash.items"
              :key="font.id"
              class="flex items-center justify-between gap-4 rounded-lg border border-separator bg-muted/30 p-3"
            >
              <div class="min-w-0">
                <p class="truncate text-[13px] font-medium">
                  {{ label(font) }}
                </p>
                <p class="truncate text-xs text-muted-foreground">
                  {{ font.originalFilename }} &middot;
                  {{
                    t("trash.deletedOn", { date: formatDate(font.deletedAt) })
                  }}
                </p>
              </div>

              <div class="flex shrink-0 items-center gap-2">
                <Badge
                  v-if="font.deletedReason === 'quarantine_pending'"
                  variant="secondary"
                >
                  {{ t("trash.reasons.quarantine_pending") }}
                </Badge>
                <Badge
                  v-else-if="font.deletedReason === 'quarantine'"
                  variant="secondary"
                >
                  {{ t("trash.reasons.quarantine") }}
                </Badge>

                <Loader2
                  v-if="busy.has(font.id)"
                  class="size-4 animate-spin text-muted-foreground"
                />
                <!-- Toute ligne listée ici a encore son fichier : le serveur ne
                     renvoie plus les polices purgées. Restaurer est donc
                     toujours offert, jamais grisé. -->
                <Button
                  variant="outline"
                  size="sm"
                  :disabled="busy.has(font.id) || bulkBusy"
                  @click="run(font.id, () => trash.restore(font.id))"
                >
                  <RotateCcw class="mr-2 size-4" />
                  {{ t("trash.restore") }}
                </Button>
              </div>
            </div>
          </div>
        </Panel>
      </section>
    </div>
  </div>
</template>
