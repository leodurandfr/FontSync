import { ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { useFontsStore } from './fonts'
import type { FontFilters } from '@/types/api'

export const useFiltersStore = defineStore('filters', () => {
  const search = ref('')
  const classification = ref<string | undefined>()
  const format = ref<string | undefined>()
  const scripts = ref<string[]>([])
  const isVariable = ref<boolean | undefined>()
  const sort = ref<FontFilters['sort']>('created_at')
  const order = ref<FontFilters['order']>('desc')
  const page = ref(1)
  const perPage = ref(50)

  function toFilters(): FontFilters {
    return {
      search: search.value || undefined,
      classification: classification.value,
      format: format.value,
      scripts: scripts.value.length > 0 ? scripts.value : undefined,
      isVariable: isVariable.value,
      sort: sort.value,
      order: order.value,
      page: page.value,
      perPage: perPage.value,
    }
  }

  function reset() {
    search.value = ''
    classification.value = undefined
    format.value = undefined
    scripts.value = []
    isVariable.value = undefined
    sort.value = 'created_at'
    order.value = 'desc'
    page.value = 1
  }

  // Auto-fetch quand les filtres changent
  watch(
    [search, classification, format, scripts, isVariable, sort, order, page],
    () => {
      const fontsStore = useFontsStore()
      fontsStore.fetchFonts(toFilters())
    },
    { deep: true },
  )

  return {
    search,
    classification,
    format,
    scripts,
    isVariable,
    sort,
    order,
    page,
    perPage,
    toFilters,
    reset,
  }
})
