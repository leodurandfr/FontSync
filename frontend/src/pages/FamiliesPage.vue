<script setup lang="ts">
import { ref, watch } from "vue";
import {
  Search,
  RotateCcw,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-vue-next";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useFamilyFiltersStore } from "@/stores/familyFilters";
import { useFamiliesStore } from "@/stores/families";
import FamilyGrid from "@/components/families/FamilyGrid.vue";
import type { FamilyFilters } from "@/types/api";
import type { AcceptableValue } from "reka-ui";

const filtersStore = useFamilyFiltersStore();
const familiesStore = useFamiliesStore();
const previewText = ref("Portez ce vieux whisky au juge blond qui fume");
const collapsed = ref(false);

const searchInput = ref(filtersStore.search);
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

watch(searchInput, (val) => {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    filtersStore.search = val;
  }, 300);
});

const CLASSIFICATIONS = [
  { value: "serif", label: "Serif" },
  { value: "sans-serif", label: "Sans-serif" },
  { value: "monospace", label: "Monospace" },
  { value: "display", label: "Display" },
  { value: "handwriting", label: "Manuscrite" },
  { value: "symbol", label: "Symbole" },
];

const SORT_OPTIONS: { value: FamilyFilters["sort"]; label: string }[] = [
  { value: "name", label: "Nom" },
  { value: "style_count", label: "Nombre de styles" },
  { value: "created_at", label: "Date de creation" },
];

function setClassification(value: string) {
  filtersStore.classification =
    filtersStore.classification === value ? undefined : value;
}

function setSort(value: AcceptableValue) {
  if (typeof value !== "string") return;
  filtersStore.sort = value as FamilyFilters["sort"];
}

function toggleOrder() {
  filtersStore.order = filtersStore.order === "asc" ? "desc" : "asc";
}

const regrouping = ref(false);

async function handleRegroup() {
  regrouping.value = true;
  try {
    const res = await fetch("/api/font-families/regroup", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    familiesStore.fetchFamilies(filtersStore.toFilters());
  } catch {
    // Regroup failed silently
  } finally {
    regrouping.value = false;
  }
}
</script>

<template>
  <div class="flex h-full overflow-hidden">
    <!-- Filter panel -->
    <aside
      class="shrink-0 border-r bg-card transition-all duration-200 overflow-hidden"
      :class="collapsed ? 'w-0 border-r-0' : 'w-64'"
    >
      <div class="flex h-full w-64 flex-col">
        <!-- Header -->
        <div class="flex items-center justify-between px-4 py-3">
          <h2 class="text-sm font-semibold">Filtres</h2>
          <div class="flex items-center gap-1">
            <Badge
              v-if="filtersStore.activeCount > 0"
              variant="secondary"
              class="text-[10px] px-1.5"
            >
              {{ filtersStore.activeCount }}
            </Badge>
            <Button
              v-if="filtersStore.activeCount > 0"
              variant="ghost"
              size="icon-sm"
              @click="filtersStore.reset()"
              title="Reinitialiser"
            >
              <RotateCcw class="h-3.5 w-3.5" />
            </Button>
            <Button variant="ghost" size="icon-sm" @click="collapsed = true">
              <PanelLeftClose class="h-4 w-4" />
            </Button>
          </div>
        </div>

        <Separator />

        <!-- Scrollable filters -->
        <div class="flex-1 overflow-y-auto px-4 py-3 space-y-5">
          <!-- Classification -->
          <div>
            <Label
              class="text-xs font-medium text-muted-foreground uppercase tracking-wider"
            >
              Classification
            </Label>
            <div class="mt-2 flex flex-wrap gap-1.5">
              <button
                v-for="cls in CLASSIFICATIONS"
                :key="cls.value"
                class="rounded-full border px-2.5 py-0.5 text-xs transition-colors"
                :class="
                  filtersStore.classification === cls.value
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'hover:bg-accent'
                "
                @click="setClassification(cls.value)"
              >
                {{ cls.label }}
              </button>
            </div>
          </div>

          <Separator />

          <!-- Sort -->
          <div>
            <Label
              class="text-xs font-medium text-muted-foreground uppercase tracking-wider"
            >
              Tri
            </Label>
            <Select
              :model-value="filtersStore.sort"
              @update:model-value="setSort"
            >
              <SelectTrigger class="mt-2 h-8 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  v-for="opt in SORT_OPTIONS"
                  :key="opt.value"
                  :value="opt.value!"
                >
                  {{ opt.label }}
                </SelectItem>
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="sm"
              class="mt-2 w-full text-xs h-8"
              @click="toggleOrder"
            >
              {{
                filtersStore.order === "asc" ? "↑ Croissant" : "↓ Decroissant"
              }}
            </Button>
          </div>
        </div>
      </div>
    </aside>

    <!-- Collapsed toggle -->
    <Button
      v-if="collapsed"
      variant="ghost"
      size="icon-sm"
      class="fixed left-0 top-[4.5rem] z-10"
      @click="collapsed = false"
    >
      <PanelLeftOpen class="h-4 w-4" />
    </Button>

    <!-- Main content -->
    <main class="flex-1 overflow-y-auto p-6">
      <div class="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 class="text-3xl font-bold tracking-tight">Familles</h1>
          <p class="text-muted-foreground mt-1">
            Parcourez et gerez vos familles de polices.
          </p>
        </div>
        <div class="flex items-center gap-3 shrink-0 mt-1">
          <Button
            variant="outline"
            size="sm"
            :disabled="regrouping"
            @click="handleRegroup"
          >
            <RotateCcw
              class="mr-1.5 h-3.5 w-3.5"
              :class="{ 'animate-spin': regrouping }"
            />
            Regrouper
          </Button>
          <div class="relative">
            <Search
              class="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              v-model="searchInput"
              type="search"
              placeholder="Rechercher une famille..."
              class="pl-9 h-9 w-64"
            />
          </div>
        </div>
      </div>

      <!-- Preview toolbar (reuses font count from families store) -->
      <div class="flex items-center gap-4 pb-4">
        <div class="relative flex-1">
          <Input
            v-model="previewText"
            placeholder="Texte de previsualisation..."
            class="h-9"
          />
        </div>
        <span class="text-sm text-muted-foreground whitespace-nowrap">
          {{ familiesStore.total }} famille{{
            familiesStore.total !== 1 ? "s" : ""
          }}
        </span>
      </div>

      <FamilyGrid :preview-text="previewText" />
    </main>
  </div>
</template>
