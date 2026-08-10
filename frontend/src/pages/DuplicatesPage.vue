<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { ArrowLeft, Check, Copy, Loader2, Undo2 } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { SectionLabel } from "@/components/ui/section-label";
import { Skeleton } from "@/components/ui/skeleton";
import { useDuplicatesStore } from "@/stores/duplicates";
import type { DuplicateFaceGroup } from "@/types/api";

const { t } = useI18n();
const duplicates = useDuplicatesStore();

const actionError = ref<string | null>(null);
const resolved = ref<{ trashed: number; bytesFreed: number } | null>(null);
const confirming = ref(false);

onMounted(() => duplicates.fetchDuplicates());

/**
 * Le recensement peut dépasser la page ramenée. Le dire, plutôt que de laisser
 * croire que la liste *est* le total : le geste, lui, porte bien sur tout.
 */
const hasMoreThanShown = computed(
  () => duplicates.totalGroups > duplicates.items.length,
);

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isExcluded(group: DuplicateFaceGroup): boolean {
  return duplicates.excluded.has(group.key);
}

async function confirm() {
  actionError.value = null;
  confirming.value = true;
  try {
    const outcome = await duplicates.resolve();
    resolved.value = {
      trashed: outcome.trashed,
      bytesFreed: outcome.bytesFreed,
    };
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e);
  } finally {
    confirming.value = false;
  }
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
          {{ t("duplicates.title") }}
        </h1>
        <p class="mt-2 text-[13px] text-muted-foreground">
          {{ t("duplicates.subtitle") }}
        </p>
      </header>

      <div v-if="duplicates.loading" class="space-y-3">
        <Skeleton class="h-28 w-full rounded-lg" />
        <Skeleton v-for="i in 4" :key="i" class="h-20 w-full rounded-lg" />
      </div>

      <Panel
        v-else-if="resolved"
        class="space-y-3 border-emerald-500/40 p-6"
        data-testid="duplicates-done"
      >
        <div class="flex items-start gap-3">
          <Check class="mt-0.5 size-4 shrink-0 text-emerald-500" />
          <div class="space-y-1">
            <p class="text-[13px] font-medium">
              {{ t("duplicates.doneTitle", { n: resolved.trashed }) }}
            </p>
            <p class="text-[13px] text-muted-foreground">
              {{
                t("duplicates.doneDesc", {
                  size: formatFileSize(resolved.bytesFreed),
                })
              }}
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" as-child>
          <RouterLink :to="{ name: 'trash' }">
            <Undo2 class="mr-2 size-4" />
            {{ t("duplicates.seeTrash") }}
          </RouterLink>
        </Button>
      </Panel>

      <div
        v-else-if="duplicates.isEmpty"
        class="rounded-lg border border-dashed border-separator p-8 text-center"
      >
        <p class="text-muted-foreground">{{ t("duplicates.none") }}</p>
        <p class="mt-1 text-[13px] text-foreground-subtle">
          {{ t("duplicates.noneDesc", { n: duplicates.scanned }) }}
        </p>
      </div>

      <template v-else>
        <!-- Le geste. Il est en haut parce que c'est lui qu'on vient faire :
             la liste en dessous sert à le vérifier, pas à le composer. -->
        <Panel class="space-y-4 p-6">
          <div class="space-y-1">
            <p class="text-[13px] font-medium">
              {{
                t("duplicates.summary", {
                  files: duplicates.pendingCount,
                  faces: duplicates.selected.length,
                  size: formatFileSize(duplicates.pendingBytes),
                })
              }}
            </p>
            <p class="text-[13px] text-muted-foreground">
              {{ t("duplicates.rule") }}
            </p>
            <p class="text-[13px] text-muted-foreground">
              {{ t("duplicates.reversible") }}
            </p>
          </div>

          <p v-if="actionError" class="text-[13px] text-destructive">
            {{ actionError }}
          </p>

          <Button
            :disabled="duplicates.resolving || duplicates.pendingCount === 0"
            @click="confirm"
          >
            <Loader2 v-if="confirming" class="mr-2 size-4 animate-spin" />
            <Copy v-else class="mr-2 size-4" />
            {{ t("duplicates.resolve", { n: duplicates.pendingCount }) }}
          </Button>
        </Panel>

        <section>
          <div class="mb-3 flex items-center justify-between gap-4">
            <SectionLabel>{{ t("duplicates.review") }}</SectionLabel>
            <span
              v-if="hasMoreThanShown"
              class="text-xs text-muted-foreground"
              >{{
                t("duplicates.showing", {
                  shown: duplicates.items.length,
                  total: duplicates.totalGroups,
                })
              }}</span
            >
          </div>

          <div class="space-y-2">
            <div
              v-for="group in duplicates.items"
              :key="group.key"
              class="rounded-lg border border-separator p-3 transition-opacity"
              :class="isExcluded(group) ? 'opacity-50' : 'bg-muted/30'"
            >
              <div class="flex items-start justify-between gap-4">
                <div class="min-w-0">
                  <p class="truncate text-[13px] font-medium">
                    {{ group.family }}
                    <span class="text-muted-foreground">{{
                      group.subfamily
                    }}</span>
                  </p>
                  <p
                    class="mt-1 truncate text-xs text-emerald-600 dark:text-emerald-400"
                  >
                    {{ t("duplicates.kept") }}
                    {{ group.keeper.originalFilename }}
                  </p>
                  <p
                    v-for="font in group.redundant"
                    :key="font.id"
                    class="truncate text-xs text-muted-foreground line-through"
                  >
                    {{ font.originalFilename }}
                  </p>
                  <p
                    v-for="font in group.alsoKept"
                    :key="font.id"
                    class="truncate text-xs text-muted-foreground"
                  >
                    {{ t("duplicates.kept") }} {{ font.originalFilename }}
                  </p>
                </div>

                <div class="flex shrink-0 items-center gap-2">
                  <Badge variant="outline">{{
                    formatFileSize(group.bytesFreed)
                  }}</Badge>
                  <Button
                    variant="outline"
                    size="sm"
                    :disabled="duplicates.resolving"
                    @click="duplicates.toggleExcluded(group.key)"
                  >
                    {{
                      isExcluded(group)
                        ? t("duplicates.include")
                        : t("duplicates.exclude")
                    }}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>
