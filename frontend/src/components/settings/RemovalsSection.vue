<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { useI18n } from "vue-i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { SectionLabel } from "@/components/ui/section-label";
import { apiJson } from "@/lib/api";
import { useLocale } from "@/composables/useLocale";
import type { FontRemoval } from "@/types/api";

/**
 * Mes polices retirées : supprimées sur un de mes Mac, elles restent dans la
 * bibliothèque partagée mais mes Mac ne les réinstallent plus. Chacun ne voit
 * que les siennes, l'admin compris.
 */
const { t } = useI18n();
const { dateLocale } = useLocale();

const removals = ref<FontRemoval[]>([]);
const errorMsg = ref<string | null>(null);
const busy = ref(false);

const pendingCount = computed(
  () => removals.value.filter((r) => !r.confirmed).length,
);

async function load() {
  try {
    removals.value = await apiJson<FontRemoval[]>("/api/me/removals");
  } catch (err) {
    errorMsg.value = (err as Error).message;
  }
}

onMounted(load);

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(dateLocale.value, {
    dateStyle: "medium",
  });
}

function label(removal: FontRemoval): string {
  return removal.fullName || removal.familyName || removal.originalFilename;
}

async function run(action: () => Promise<unknown>) {
  errorMsg.value = null;
  busy.value = true;
  try {
    await action();
    await load();
  } catch (err) {
    errorMsg.value = (err as Error).message;
  } finally {
    busy.value = false;
  }
}

function confirmAll() {
  return run(() => apiJson("/api/me/removals/confirm", "POST"));
}

function undo(removal: FontRemoval) {
  return run(() => apiJson(`/api/me/removals/${removal.fontId}`, "DELETE"));
}
</script>

<template>
  <section>
    <SectionLabel class="mb-3">{{ t("removals.title") }}</SectionLabel>
    <Panel class="space-y-4 p-6">
      <p class="text-[13px] text-muted-foreground">{{ t("removals.desc") }}</p>

      <div
        v-if="pendingCount"
        class="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-separator bg-muted/50 px-3 py-2"
        role="alert"
      >
        <div>
          <p class="text-[13px] font-medium">
            {{ t("removals.pendingTitle", { n: pendingCount }, pendingCount) }}
          </p>
          <p class="text-[13px] text-muted-foreground">
            {{ t("removals.pendingDesc") }}
          </p>
        </div>
        <Button size="sm" :disabled="busy" @click="confirmAll">
          {{ t("removals.confirm") }}
        </Button>
      </div>

      <p v-if="errorMsg" class="text-[13px] text-destructive" role="alert">
        {{ errorMsg }}
      </p>

      <p v-if="!removals.length" class="text-[13px] text-muted-foreground">
        {{ t("removals.empty") }}
      </p>
      <ul
        v-else
        class="divide-y divide-separator rounded-lg border border-separator"
      >
        <li
          v-for="removal in removals"
          :key="removal.fontId"
          class="flex items-center justify-between gap-3 px-3 py-2"
        >
          <div class="min-w-0">
            <p class="flex items-center gap-2 truncate text-[13px]">
              <RouterLink
                :to="{ name: 'font-detail', params: { id: removal.fontId } }"
                class="truncate hover:underline"
                >{{ label(removal) }}</RouterLink
              >
              <Badge v-if="!removal.confirmed" variant="secondary">{{
                t("removals.pending")
              }}</Badge>
            </p>
            <p class="text-xs text-muted-foreground">
              {{
                removal.sourceDeviceName
                  ? t("removals.removedFrom", {
                      device: removal.sourceDeviceName,
                      date: formatDate(removal.removedAt),
                    })
                  : t("removals.removedOn", {
                      date: formatDate(removal.removedAt),
                    })
              }}
            </p>
          </div>
          <Button
            variant="ghost"
            size="sm"
            :disabled="busy"
            @click="undo(removal)"
          >
            {{ t("removals.undo") }}
          </Button>
        </li>
      </ul>
    </Panel>
  </section>
</template>
