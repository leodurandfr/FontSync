<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  Type,
  RotateCcw,
  ChevronDown,
} from 'lucide-vue-next'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarRail,
  SidebarSeparator,
} from '@/components/ui/sidebar'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Checkbox } from '@/components/ui/checkbox'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useFiltersStore } from '@/stores/filters'
import type { AcceptableValue } from 'reka-ui'
import type { FontFilters } from '@/types/api'

const filtersStore = useFiltersStore()

// Scripts
const availableScripts = ref<{ script: string; count: number }[]>([])

onMounted(async () => {
  try {
    const res = await fetch('/api/stats')
    if (res.ok) {
      const stats = await res.json()
      availableScripts.value = stats.byScript ?? []
    }
  } catch {
    // Stats unavailable
  }
})

const CLASSIFICATIONS = [
  { value: 'serif', label: 'Serif' },
  { value: 'sans-serif', label: 'Sans-serif' },
  { value: 'monospace', label: 'Monospace' },
  { value: 'display', label: 'Display' },
  { value: 'handwriting', label: 'Manuscrite' },
  { value: 'symbol', label: 'Symbole' },
]

const FORMATS = [
  { value: 'ttf', label: 'TTF' },
  { value: 'otf', label: 'OTF' },
  { value: 'woff', label: 'WOFF' },
  { value: 'woff2', label: 'WOFF2' },
]

const WEIGHTS = [
  { value: 100, label: 'Thin (100)' },
  { value: 200, label: 'Extra-light (200)' },
  { value: 300, label: 'Light (300)' },
  { value: 400, label: 'Regular (400)' },
  { value: 500, label: 'Medium (500)' },
  { value: 600, label: 'Semi-bold (600)' },
  { value: 700, label: 'Bold (700)' },
  { value: 800, label: 'Extra-bold (800)' },
  { value: 900, label: 'Black (900)' },
]

const SORT_OPTIONS: { value: FontFilters['sort']; label: string }[] = [
  { value: 'created_at', label: "Date d'ajout" },
  { value: 'family_name', label: 'Nom' },
  { value: 'file_size', label: 'Taille' },
  { value: 'weight_class', label: 'Graisse' },
]

function toggleScript(script: string) {
  const idx = filtersStore.scripts.indexOf(script)
  if (idx >= 0) {
    filtersStore.scripts.splice(idx, 1)
  } else {
    filtersStore.scripts.push(script)
  }
}

function setClassification(value: AcceptableValue) {
  if (typeof value !== 'string') return
  filtersStore.classification =
    filtersStore.classification === value ? undefined : value
}

function setFormat(value: AcceptableValue) {
  if (typeof value !== 'string') return
  filtersStore.format = filtersStore.format === value ? undefined : value
}

function setWeightMin(value: AcceptableValue) {
  const v = String(value)
  filtersStore.weightMin = v === 'any' ? undefined : Number(v)
}

function setWeightMax(value: AcceptableValue) {
  const v = String(value)
  filtersStore.weightMax = v === 'any' ? undefined : Number(v)
}

function setSort(value: AcceptableValue) {
  if (typeof value !== 'string') return
  filtersStore.sort = value as FontFilters['sort']
}

function toggleOrder() {
  filtersStore.order = filtersStore.order === 'asc' ? 'desc' : 'asc'
}

function toggleVariable(checked: boolean | 'indeterminate') {
  filtersStore.isVariable = checked === true ? true : undefined
}
</script>

<template>
  <Sidebar collapsible="icon">
    <!-- Logo -->
    <SidebarHeader class="p-4">
      <RouterLink to="/" class="flex items-center gap-2 group-data-[collapsible=icon]:justify-center">
        <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-foreground text-background">
          <Type class="h-4 w-4" />
        </div>
        <span class="text-lg font-bold tracking-tight group-data-[collapsible=icon]:hidden">
          FontSync
        </span>
      </RouterLink>
    </SidebarHeader>

    <SidebarSeparator />

    <SidebarContent>
      <!-- Filters header -->
      <SidebarGroup>
        <div class="flex items-center justify-between px-2 group-data-[collapsible=icon]:hidden">
          <SidebarGroupLabel class="p-0">Filtres</SidebarGroupLabel>
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
          </div>
        </div>
      </SidebarGroup>

      <!-- Classification -->
      <SidebarGroup>
        <SidebarGroupLabel>Classification</SidebarGroupLabel>
        <SidebarGroupContent class="px-2 group-data-[collapsible=icon]:hidden">
          <div class="flex flex-wrap gap-1.5">
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
        </SidebarGroupContent>
      </SidebarGroup>

      <!-- Format -->
      <SidebarGroup>
        <SidebarGroupLabel>Format</SidebarGroupLabel>
        <SidebarGroupContent class="px-2 group-data-[collapsible=icon]:hidden">
          <div class="flex flex-wrap gap-1.5">
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
        </SidebarGroupContent>
      </SidebarGroup>

      <!-- Weight -->
      <SidebarGroup>
        <SidebarGroupLabel>Graisse</SidebarGroupLabel>
        <SidebarGroupContent class="px-2 group-data-[collapsible=icon]:hidden">
          <div class="grid grid-cols-2 gap-2">
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
        </SidebarGroupContent>
      </SidebarGroup>

      <!-- Variable fonts -->
      <SidebarGroup>
        <SidebarGroupContent class="px-2 group-data-[collapsible=icon]:hidden">
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
        </SidebarGroupContent>
      </SidebarGroup>

      <!-- Scripts -->
      <SidebarGroup v-if="availableScripts.length > 0">
        <SidebarGroupLabel>Scripts</SidebarGroupLabel>
        <SidebarGroupContent class="px-2 group-data-[collapsible=icon]:hidden">
          <DropdownMenu>
            <DropdownMenuTrigger as-child>
              <Button
                variant="outline"
                class="w-full justify-between h-8 text-xs"
              >
                <span v-if="filtersStore.scripts.length === 0">Tous les scripts</span>
                <span v-else>
                  {{ filtersStore.scripts.length }} sélectionné{{
                    filtersStore.scripts.length > 1 ? 's' : ''
                  }}
                </span>
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
                    e.preventDefault()
                    toggleScript(s.script)
                  }
                "
              >
                <span class="capitalize">{{ s.script }}</span>
                <span class="ml-auto text-xs text-muted-foreground">{{ s.count }}</span>
              </DropdownMenuCheckboxItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SidebarGroupContent>
      </SidebarGroup>

      <SidebarSeparator class="group-data-[collapsible=icon]:hidden" />

      <!-- Sort -->
      <SidebarGroup>
        <SidebarGroupLabel>Tri</SidebarGroupLabel>
        <SidebarGroupContent class="px-2 group-data-[collapsible=icon]:hidden">
          <Select
            :model-value="filtersStore.sort"
            @update:model-value="setSort"
          >
            <SelectTrigger class="h-8 text-xs">
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
            {{ filtersStore.order === 'asc' ? '↑ Croissant' : '↓ Décroissant' }}
          </Button>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>

    <SidebarFooter class="p-4 group-data-[collapsible=icon]:p-2">
      <p class="text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
        FontSync v0.1
      </p>
    </SidebarFooter>

    <SidebarRail />
  </Sidebar>
</template>
