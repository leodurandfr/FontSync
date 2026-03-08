import { storeToRefs } from 'pinia'
import { useWsStore } from '@/stores/ws'
import { useFontsStore } from '@/stores/fonts'
import { useDevicesStore } from '@/stores/devices'
import type { WsMessage, Font } from '@/types/api'

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000]

let socket: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let isManualClose = false

function getWsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws/client`
}

function dispatch(message: WsMessage) {
  const fontsStore = useFontsStore()
  const devicesStore = useDevicesStore()

  switch (message.type) {
    case 'font.added':
      fontsStore.addFont(message.data as unknown as Font)
      break
    case 'font.deleted':
      if (typeof message.data.id === 'string') {
        fontsStore.removeFont(message.data.id)
      }
      break
    case 'font.updated':
      if (typeof message.data.id === 'string') {
        fontsStore.updateFont(message.data.id, message.data as unknown as Partial<Font>)
      }
      break
    case 'device.connected':
      if (typeof message.data.deviceId === 'string') {
        devicesStore.setDeviceOnline(message.data.deviceId)
      }
      break
    case 'device.disconnected':
      if (typeof message.data.deviceId === 'string') {
        devicesStore.setDeviceOffline(message.data.deviceId)
      }
      break
  }
}

function connect() {
  const wsStore = useWsStore()

  if (socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING) {
    return
  }

  isManualClose = false
  wsStore.status = 'connecting'

  socket = new WebSocket(getWsUrl())

  socket.onopen = () => {
    wsStore.status = 'connected'
    wsStore.reconnectAttempts = 0
  }

  socket.onmessage = (event) => {
    try {
      const message: WsMessage = JSON.parse(event.data)
      dispatch(message)
    } catch {
      // ignore malformed messages
    }
  }

  socket.onclose = () => {
    socket = null
    wsStore.status = 'disconnected'

    if (!isManualClose) {
      scheduleReconnect()
    }
  }

  socket.onerror = () => {
    socket?.close()
  }
}

function scheduleReconnect() {
  const wsStore = useWsStore()
  const delay = RECONNECT_DELAYS[
    Math.min(wsStore.reconnectAttempts, RECONNECT_DELAYS.length - 1)
  ]
  wsStore.reconnectAttempts++

  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connect()
  }, delay)
}

function disconnect() {
  isManualClose = true
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  socket?.close()
  socket = null
  const wsStore = useWsStore()
  wsStore.status = 'disconnected'
  wsStore.reconnectAttempts = 0
}

// Cleanup on HMR to avoid dangling WebSocket connections
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    disconnect()
  })
}

export function useWebSocket() {
  const wsStore = useWsStore()
  const { status, reconnectAttempts } = storeToRefs(wsStore)

  connect()

  return {
    status,
    reconnectAttempts,
    connect,
    disconnect,
  }
}
