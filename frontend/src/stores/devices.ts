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
  }
})
