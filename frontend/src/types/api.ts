export interface Font {
  id: string;
  fileHash: string;
  originalFilename: string;
  fileSize: number;
  fileFormat: string;
  storagePath: string;
  familyName: string | null;
  subfamilyName: string | null;
  fullName: string | null;
  postscriptName: string | null;
  version: string | null;
  designer: string | null;
  manufacturer: string | null;
  license: string | null;
  licenseUrl: string | null;
  description: string | null;
  weightClass: number | null;
  widthClass: number | null;
  isItalic: boolean;
  isOblique: boolean;
  panose: string | null;
  classification: string | null;
  unicodeRanges: Record<string, unknown> | null;
  supportedScripts: string[] | null;
  glyphCount: number | null;
  isVariable: boolean;
  variableAxes: unknown[] | null;
  familyId: string | null;
  source: string;
  sourceDeviceId: string | null;
  sourceDeviceName: string | null;
  createdAt: string;
  updatedAt: string;
  /** Pierre tombale — nul pour une police de la bibliothèque. */
  deletedAt?: string | null;
  deletedReason?: DeletionReason | null;
  /**
   * Fichier retiré du stockage lors d'un vidage de corbeille. L'empreinte, elle,
   * est conservée : c'est ce qui empêche la police de revenir au push suivant.
   * Une police purgée n'est plus restaurable — il faut la ré-importer.
   */
  purgedAt?: string | null;
}

/**
 * `quarantine_pending` : disparition détectée **au-delà du seuil**. La police est
 * en corbeille mais sa suppression n'est propagée à aucune machine tant que
 * l'utilisateur n'a pas tranché.
 */
export type DeletionReason = "manual" | "quarantine" | "quarantine_pending";

export interface FontListResponse {
  items: Font[];
  total: number;
  page: number;
  perPage: number;
  pages: number;
}

export interface TrashListResponse extends FontListResponse {
  pendingConfirmation: number;
}

export interface FontUploadResponse {
  imported: Font[];
  duplicates: Font[];
  errors: { filename: string; detail: string }[];
}

export interface FontFilters {
  search?: string;
  classification?: string;
  format?: string;
  scripts?: string[];
  isVariable?: boolean;
  weightMin?: number;
  weightMax?: number;
  familyId?: string;
  orphan?: boolean;
  sort?:
    | "name"
    | "family_name"
    | "created_at"
    | "updated_at"
    | "file_size"
    | "weight_class"
    | "glyph_count";
  order?: "asc" | "desc";
  page?: number;
  perPage?: number;
}

export interface Device {
  id: string;
  name: string;
  hostname: string;
  os: string;
  osVersion: string | null;
  agentVersion: string | null;
  lastSeenAt: string | null;
  lastSyncAt: string | null;
  syncStatus: "idle" | "scanning" | "syncing" | "error";
  fontDirectories: string[] | null;
  autoPull: boolean;
  autoPush: boolean;
  /**
   * Cet appareil participe-t-il à la propagation des suppressions ? Réglage
   * distinct d'autoPull/autoPush à dessein : ces deux-là ne promettent
   * qu'envoyer et installer, les activer ne doit pas devenir destructeur.
   */
  propagateDeletions: boolean;
  createdAt: string;
  /** Présence « en ligne » (connexion SSE `listen` active), calculée serveur. */
  isOnline?: boolean;
}

export interface SystemInfo {
  /** Version de l'image en cours d'exécution ; `dev` hors image publiée. */
  version: string;
  /**
   * Le serveur sait-il se mettre à jour lui-même (Watchtower configuré) ? Si
   * non, on masque le bouton plutôt que de proposer une action qui échouerait.
   */
  updateAvailable: boolean;
}

export interface Stats {
  totalFonts: number;
  byClassification: { classification: string | null; count: number }[];
  byFormat: { format: string; count: number }[];
  byScript: { script: string; count: number }[];
}

// Font Families

export interface FontPreviewRef {
  id: string;
  fullName: string | null;
  fileFormat: string;
}

export interface FontFamily {
  id: string;
  name: string;
  slug: string;
  classification: string | null;
  description: string | null;
  designer: string | null;
  manufacturer: string | null;
  styleCount: number;
  isAutoGrouped: boolean;
  previewFont: FontPreviewRef | null;
  createdAt: string;
  updatedAt: string;
}

export interface FamilyMember {
  fontId: string;
  sortOrder: number;
  originalFilename: string;
  fullName: string | null;
  subfamilyName: string | null;
  postscriptName: string | null;
  fileFormat: string;
  fileSize: number;
  weightClass: number | null;
  isItalic: boolean;
  isVariable: boolean;
}

export interface FontFamilyDetail extends FontFamily {
  members: FamilyMember[];
}

export interface FontFamilyListResponse {
  items: FontFamily[];
  total: number;
  page: number;
  perPage: number;
  pages: number;
}

export interface FamilyFilters {
  search?: string;
  classification?: string;
  sort?: "name" | "style_count" | "created_at";
  order?: "asc" | "desc";
  page?: number;
  perPage?: number;
}

export type WsEventType =
  | "font.added"
  | "font.deleted"
  | "font.updated"
  | "device.connected"
  | "device.disconnected"
  | "device.updated"
  | "sync.progress"
  | "sync.completed"
  | "family.created"
  | "family.updated"
  | "family.deleted"
  | "family.merged"
  | "families.regrouped";

export interface WsMessage {
  type: WsEventType;
  data: Record<string, unknown>;
}
