<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import {
  PanelLeftClose,
  PanelLeftOpen,
  RotateCcw,
  ChevronDown,
  Check,
} from "lucide-vue-next";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useFiltersStore } from "@/stores/filters";
import type { FontFilters } from "@/types/api";

const filtersStore = useFiltersStore();

const collapsed = ref(false);

// Stats-based script options
const availableScripts = ref<{ script: string; count: number }[]>([]);

onMounted(async () => {
  try {
    const res = await fetch("/api/stats");
    if (res.ok) {
      const stats = await res.json();
      availableScripts.value = stats.byScript ?? [];
    }
  } catch {
    // Stats unavailable — scripts filter will be hidden
  }
});

const CLASSIFICATIONS = [
  { value: "serif", label: "Serif" },
  { value: "sans-serif", label: "Sans-serif" },
  { value: "monospace", label: "Monospace" },
  { value: "display", label: "Display" },
  { value: "handwriting", label: "Manuscrite" },
  { value: "symbol", label: "Symbole" },
];

const FORMATS = [
  { value: "ttf", label: "TTF" },
  { value: "otf", label: "OTF" },
  { value: "woff", label: "WOFF" },
  { value: "woff2", label: "WOFF2" },
];

const WEIGHTS = [
  { value: 100, label: "Thin (100)" },
  { value: 200, label: "Extra-light (200)" },
  { value: 300, label: "Light (300)" },
  { value: 400, label: "Regular (400)" },
  { value: 500, label: "Medium (500)" },
  { value: 600, label: "Semi-bold (600)" },
  { value: 700, label: "Bold (700)" },
  { value: 800, label: "Extra-bold (800)" },
  { value: 900, label: "Black (900)" },
];

const SORT_OPTIONS: { value: FontFilters["sort"]; label: string }[] = [
  { value: "created_at", label: "Date d'ajout" },
  { value: "family_name", label: "Nom" },
  { value: "file_size", label: "Taille" },
  { value: "weight_class", label: "Graisse" },
];

function toggleScript(script: string) {
  const idx = filtersStore.scripts.indexOf(script);
  if (idx >= 0) {
    filtersStore.scripts.splice(idx, 1);
  } else {
    filtersStore.scripts.push(script);
  }
}

function setClassification(value: string) {
  filtersStore.classification =
    filtersStore.classification === value ? undefined : value;
}

function setFormat(value: string) {
  filtersStore.format = filtersStore.format === value ? undefined : value;
}

function setWeightMin(value: string) {
  filtersStore.weightMin = value === "any" ? undefined : Number(value);
}

function setWeightMax(value: string) {
  filtersStore.weightMax = value === "any" ? undefined : Number(value);
}

function setSort(value: string) {
  filtersStore.sort = value as FontFilters["sort"];
}

function toggleOrder() {
  filtersStore.order = filtersStore.order === "asc" ? "desc" : "asc";
}

function toggleVariable(checked: boolean | "indeterminate") {
  filtersStore.isVariable = checked === true ? true : undefined;
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

        <!-- Format -->
        <div>
          <Label
            class="text-xs font-medium text-muted-foreground uppercase tracking-wider"
          >
            Format
          </Label>
          <div class="mt-2 flex flex-wrap gap-1.5">
            <button
              v-for="fmt in FORMATS"
              :key="fmt.value"
              class="rounded-full border px-2.5 py-0.5 text-xs transition-colors"
              :class="
                filtersStore.format === fmt.value
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'hover:bg-accent'
              "
              @click="setFormat(fmt.value)"
            >
              {{ fmt.label }}
            </button>
          </div>
        </div>

        <!-- Weight -->
        <div>
          <Label
            class="text-xs font-medium text-muted-foreground uppercase tracking-wider"
          >
            Graisse
          </Label>
          <div class="mt-2 grid grid-cols-2 gap-2">
            <div>
              <span class="text-[11px] text-muted-foreground">Min</span>
              <Select
                :model-value="
                  filtersStore.weightMin !== undefined
                    ? String(filtersStore.weightMin)
                    : 'any'
                "
                @update:model-value="setWeightMin"
              >
                <SelectTrigger class="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">Tous</SelectItem>
                  <SelectItem
                    v-for="w in WEIGHTS"
                    :key="w.value"
                    :value="String(w.value)"
                  >
                    {{ w.label }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <span class="text-[11px] text-muted-foreground">Max</span>
              <Select
                :model-value="
                  filtersStore.weightMax !== undefined
                    ? String(filtersStore.weightMax)
                    : 'any'
                "
                @update:model-value="setWeightMax"
              >
                <SelectTrigger class="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="any">Tous</SelectItem>
                  <SelectItem
                    v-for="w in WEIGHTS"
                    :key="w.value"
                    :value="String(w.value)"
                  >
                    {{ w.label }}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        <!-- Variable fonts -->
        <div class="flex items-center gap-2">
          <Checkbox
            id="variable-filter"
            :checked="filtersStore.isVariable === true"
            @update:checked="toggleVariable"
          />
          <Label for="variable-filter" class="text-sm cursor-pointer">
            Variable fonts uniquement
          </Label>
        </div>

        <!-- Scripts -->
        <div v-if="availableScripts.length > 0">
          <Label
            class="text-xs font-medium text-muted-foreground uppercase tracking-wider"
          >
            Scripts
          </Label>
          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <Button
                variant="outline"
                class="mt-2 w-full justify-between h-8 text-xs"
              >
                <span v-if="filtersStore.scripts.length === 0"
                  >Tous les scripts</span
                >
                <span v-else
                  >{{ filtersStore.scripts.length }} sélectionné{{
                    filtersStore.scripts.length > 1 ? "s" : ""
                  }}</span
                >
                <ChevronDown class="h-3.5 w-3.5 opacity-50" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent class="w-56 max-h-64 overflow-y-auto">
              <DropdownMenuCheckboxItem
                v-for="s in availableScripts"
                :key="s.script"
                :checked="filtersStore.scripts.includes(s.script)"
                @select="
                  (e: Event) => {
                    e.preventDefault();
                    toggleScript(s.script);
                  }
                "
              >
                <span class="capitalize">{{ s.script }}</span>
                <span class="ml-auto text-xs text-muted-foreground">{{
                  s.count
                }}</span>
              </DropdownMenuCheckboxItem>
            </DropdownMenuContent>
          </DropdownMenu>
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
    class="fixed left-14 top-[4.5rem] z-10"
    @click="collapsed = false"
  >
    <PanelLeftOpen class="h-4 w-4" />
  </Button>
</template>
