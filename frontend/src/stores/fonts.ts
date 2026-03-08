import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import type { Font, FontListResponse, FontFilters } from '@/types/api'

export const useFontsStore = defineStore('fonts', () => {
  const fonts = ref<Font[]>([])
  const total = ref(0)
  const page = ref(1)
  const pages = ref(0)
  const perPage = ref(50)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const isEmpty = computed(() => fonts.value.length === 0 && !loading.value)

  async function fetchFonts(filters?: FontFilters) {
    loading.value = true
    error.value = null
    try {
      const params = new URLSearchParams()
      if (filters?.search) params.set('search', filters.search)
      if (filters?.classification) params.set('classification', filters.classification)
      if (filters?.format) params.set('file_format', filters.format)
      if (filters?.isVariable !== undefined) params.set('is_variable', String(filters.isVariable))
      if (filters?.weightMin !== undefined) params.set('weight_min', String(filters.weightMin))
      if (filters?.weightMax !== undefined) params.set('weight_max', String(filters.weightMax))
      if (filters?.sort) params.set('sort', filters.sort)
      if (filters?.order) params.set('order', filters.order)
      if (filters?.page) params.set('page', String(filters.page))
      if (filters?.perPage) params.set('per_page', String(filters.perPage))
      if (filters?.scripts) {
        for (const s of filters.scripts) params.append('scripts', s)
      }

      const res = await fetch(`/api/fonts?${params}`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: FontListResponse = await res.json()

      fonts.value = data.items
      total.value = data.total
      page.value = data.page
      pages.value = data.pages
      perPage.value = data.perPage
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Erreur inconnue'
    } finally {
      loading.value = false
    }
  }

  function addFont(font: Font) {
    const exists = fonts.value.find((f) => f.id === font.id)
    if (!exists) {
      fonts.value.unshift(font)
      total.value++
    }
  }

  function removeFont(fontId: string) {
    fonts.value = fonts.value.filter((f) => f.id !== fontId)
    total.value = Math.max(0, total.value - 1)
  }

  function updateFont(fontId: string, data: Partial<Font>) {
    const idx = fonts.value.findIndex((f) => f.id === fontId)
    const existing = fonts.value[idx]
    if (existing) {
      fonts.value[idx] = { ...existing, ...data }
    }
  }

  return {
    fonts,
    total,
    page,
    pages,
    perPage,
    loading,
    error,
    isEmpty,
    fetchFonts,
    addFont,
    removeFont,
    updateFont,
  }
})
