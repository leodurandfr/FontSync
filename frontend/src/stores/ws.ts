import { ref } from 'vue'
import { defineStore } from 'pinia'

export type WsStatus = 'connecting' | 'connected' | 'disconnected'

export const useWsStore = defineStore('ws', () => {
  const status = ref<WsStatus>('disconnected')
  const reconnectAttempts = ref(0)

  return {
    status,
    reconnectAttempts,
  }
})
