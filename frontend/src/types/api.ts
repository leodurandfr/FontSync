export interface Font {
  id: string
  fileHash: string
  originalFilename: string
  fileSize: number
  fileFormat: string
  storagePath: string
  familyName: string | null
  subfamilyName: string | null
  fullName: string | null
  postscriptName: string | null
  version: string | null
  designer: string | null
  manufacturer: string | null
  license: string | null
  licenseUrl: string | null
  description: string | null
  weightClass: number | null
  widthClass: number | null
  isItalic: boolean
  isOblique: boolean
  panose: string | null
  classification: string | null
  unicodeRanges: Record<string, unknown> | null
  supportedScripts: string[] | null
  glyphCount: number | null
  isVariable: boolean
  variableAxes: unknown[] | null
  source: string
  createdAt: string
  updatedAt: string
}

export interface FontListResponse {
  items: Font[]
  total: number
  page: number
  perPage: number
  pages: number
}

export interface FontFilters {
  search?: string
  classification?: string
  format?: string
  scripts?: string[]
  isVariable?: boolean
  weightMin?: number
  weightMax?: number
  sort?: 'family_name' | 'created_at' | 'updated_at' | 'file_size' | 'weight_class'
  order?: 'asc' | 'desc'
  page?: number
  perPage?: number
}

export interface Device {
  id: string
  name: string
  hostname: string
  os: string
  osVersion: string | null
  agentVersion: string | null
  lastSeenAt: string | null
  lastSyncAt: string | null
  syncStatus: 'idle' | 'scanning' | 'syncing' | 'error'
  fontDirectories: string[] | null
  autoPull: boolean
  createdAt: string
}

export interface Stats {
  totalFonts: number
  byClassification: { classification: string | null; count: number }[]
  byFormat: { format: string; count: number }[]
  byScript: { script: string; count: number }[]
}

export type WsEventType =
  | 'font.added'
  | 'font.deleted'
  | 'font.updated'
  | 'device.connected'
  | 'device.disconnected'
  | 'device.updated'
  | 'sync.progress'
  | 'sync.completed'

export interface WsMessage {
  type: WsEventType
  data: Record<string, unknown>
}
