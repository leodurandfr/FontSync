import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
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
      const res = await fetch('/api/devices')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      devices.value = await res.json()
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
    const res = await fetch(`/api/devices/${deviceId}`, {
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
