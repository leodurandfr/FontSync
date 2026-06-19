import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { apiFetch } from '@/lib/api'
import type { Device } from '@/types/api'

export const useDevicesStore = defineStore('devices', () => {
  const devices = ref<Device[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** IDs des devices actuellement connectés via WS */
  const onlineDeviceIds = ref<Set<string>>(new Set())

  const onlineCount = computed(() => onlineDeviceIds.value.size)

  function isOnline(deviceId: string): boolean {
    return onlineDeviceIds.value.has(deviceId)
  }

  async function fetchDevices() {
    loading.value = true
    error.value = null
    try {
      const res = await apiFetch('/api/devices')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const list: Device[] = await res.json()
      devices.value = list
      // Amorce la présence « en ligne » depuis le REST : sinon un device déjà
      // connecté (SSE établi avant l'ouverture de l'UI) resterait affiché
      // « non connecté » faute d'événement WS device.connected à rejouer.
      onlineDeviceIds.value = new Set(list.filter((d) => d.isOnline).map((d) => d.id))
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Erreur inconnue'
    } finally {
      loading.value = false
    }
  }

  function setDeviceOnline(deviceId: string) {
    onlineDeviceIds.value = new Set([...onlineDeviceIds.value, deviceId])
  }

  function setDeviceOffline(deviceId: string) {
    const next = new Set(onlineDeviceIds.value)
    next.delete(deviceId)
    onlineDeviceIds.value = next
  }

  function updateDeviceFields(deviceId: string, fields: Record<string, unknown>) {
    const device = devices.value.find((d) => d.id === deviceId)
    if (device && fields.syncStatus !== undefined) {
      device.syncStatus = fields.syncStatus as Device['syncStatus']
    }
  }

  async function updateDevice(deviceId: string, fields: Partial<Pick<Device, 'name' | 'autoPull' | 'autoPush'>>) {
    const res = await apiFetch(`/api/devices/${deviceId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const updated: Device = await res.json()
    const idx = devices.value.findIndex((d) => d.id === deviceId)
    if (idx !== -1) {
      devices.value[idx] = updated
    }
    return updated
  }

  return {
    devices,
    loading,
    error,
    onlineDeviceIds,
    onlineCount,
    isOnline,
    fetchDevices,
    setDeviceOnline,
    setDeviceOffline,
    updateDeviceFields,
    updateDevice,
  }
})
