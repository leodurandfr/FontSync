import { storeToRefs } from "pinia";
import { useWsStore } from "@/stores/ws";
import { useAuthStore } from "@/stores/auth";
import { useFontsStore } from "@/stores/fonts";
import { useDevicesStore } from "@/stores/devices";
import { useFamiliesStore } from "@/stores/families";
import { useFamilyFiltersStore } from "@/stores/familyFilters";
import type { WsMessage, Font, FontFamily } from "@/types/api";

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000, 30000];

let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let isManualClose = false;

function getWsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const base = `${proto}//${window.location.host}/ws/client`;
  // Le handshake WebSocket du navigateur ne peut pas poser d'en-tête : le token
  // (P1.4) passe en query param `?token=` (cf. `verify_websocket_token` côté
  // serveur).
  const token = useAuthStore().token;
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

function dispatch(message: WsMessage) {
  const fontsStore = useFontsStore();
  const devicesStore = useDevicesStore();
  const familiesStore = useFamiliesStore();

  switch (message.type) {
    case "font.added":
      fontsStore.addFont(message.data as unknown as Font);
      break;
    case "font.deleted":
      if (typeof message.data.id === "string") {
        fontsStore.removeFont(message.data.id);
      }
      break;
    case "font.updated":
      if (typeof message.data.id === "string") {
        fontsStore.updateFont(
          message.data.id,
          message.data as unknown as Partial<Font>,
        );
      }
      break;
    case "device.connected":
      if (typeof message.data.deviceId === "string") {
        devicesStore.setDeviceOnline(message.data.deviceId);
      }
      break;
    case "device.disconnected":
      if (typeof message.data.deviceId === "string") {
        devicesStore.setDeviceOffline(message.data.deviceId);
      }
      break;
    case "device.updated":
      if (typeof message.data.deviceId === "string") {
        devicesStore.updateDeviceFields(
          message.data.deviceId,
          message.data as Record<string, unknown>,
        );
      }
      break;
    case "family.created":
      familiesStore.addFamily(message.data as unknown as FontFamily);
      break;
    case "family.updated":
      if (typeof message.data.id === "string") {
        familiesStore.updateFamily(
          message.data.id,
          message.data as unknown as Partial<FontFamily>,
        );
      }
      break;
    case "family.deleted":
      if (typeof message.data.id === "string") {
        familiesStore.removeFamily(message.data.id);
      }
      break;
    case "family.merged":
    case "families.regrouped":
      if (familiesStore.initialized) {
        const filtersStore = useFamilyFiltersStore();
        familiesStore.fetchFamilies(filtersStore.toFilters());
      }
      break;
  }
}

function connect() {
  const wsStore = useWsStore();

  if (
    socket?.readyState === WebSocket.OPEN ||
    socket?.readyState === WebSocket.CONNECTING
  ) {
    return;
  }

  isManualClose = false;
  wsStore.status = "connecting";

  socket = new WebSocket(getWsUrl());

  socket.onopen = () => {
    wsStore.status = "connected";
    wsStore.reconnectAttempts = 0;
  };

  socket.onmessage = (event) => {
    try {
      const message: WsMessage = JSON.parse(event.data);
      dispatch(message);
    } catch {
      // ignore malformed messages
    }
  };

  socket.onclose = (event) => {
    socket = null;
    wsStore.status = "disconnected";

    // 1008 = WS_1008_POLICY_VIOLATION : le serveur a refusé le token (absent,
    // invalide, ou tourné). Inutile de reconnecter avec le même token — on
    // redemande la saisie et on s'arrête.
    if (event.code === 1008) {
      useAuthStore().markUnauthorized();
      return;
    }

    if (!isManualClose) {
      scheduleReconnect();
    }
  };

  socket.onerror = () => {
    socket?.close();
  };
}

function scheduleReconnect() {
  const wsStore = useWsStore();
  const delay =
    RECONNECT_DELAYS[
      Math.min(wsStore.reconnectAttempts, RECONNECT_DELAYS.length - 1)
    ];
  wsStore.reconnectAttempts++;

  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function disconnect() {
  isManualClose = true;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  socket?.close();
  socket = null;
  const wsStore = useWsStore();
  wsStore.status = "disconnected";
  wsStore.reconnectAttempts = 0;
}

// Cleanup on HMR to avoid dangling WebSocket connections
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    disconnect();
  });
}

export function useWebSocket() {
  const wsStore = useWsStore();
  const { status, reconnectAttempts } = storeToRefs(wsStore);

  connect();

  return {
    status,
    reconnectAttempts,
    connect,
    disconnect,
  };
}
