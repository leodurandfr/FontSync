<script setup lang="ts">
import { PanelLeftClose, PanelLeftOpen, RotateCcw } from "lucide-vue-next";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ref } from "vue";
import { useFamilyFiltersStore } from "@/stores/familyFilters";
import type { FamilyFilters } from "@/types/api";
import type { AcceptableValue } from "reka-ui";

const filtersStore = useFamilyFiltersStore();

const collapsed = ref(false);

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
  { value: "created_at", label: "Date d'ajout" },
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
</script>

<template>
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
            title="Réinitialiser"
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
            {{ filtersStore.order === "asc" ? "↑ Croissant" : "↓ Décroissant" }}
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
</template>
