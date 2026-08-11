export interface Font {
  id: string;
  fileHash: string;
  originalFilename: string;
  fileSize: number;
  fileFormat: string;
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
  /**
   * Le verrou de propagation : `false` tant qu'une suppression détectée
   * au-delà du seuil de quarantaine attend un arbitrage (`/trash/confirm`).
   */
  deletionConfirmed: boolean;
  /**
   * Fichier retiré du stockage lors d'un vidage de corbeille. L'empreinte, elle,
   * est conservée : c'est ce qui empêche la police de revenir au push suivant.
   * Une police purgée n'est plus restaurable — il faut la ré-importer, et elle
   * ne figure plus dans la corbeille.
   */
  purgedAt?: string | null;
}

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

/** Bilan d'un vidage de corbeille. */
export interface PurgeResult {
  /** Fichiers retirés du stockage. */
  purged: number;
  /**
   * Suppressions épargnées faute de confirmation — elles restent en corbeille.
   * Le dire est ce qui distingue « épargnées » de « oubliées ».
   */
  retained: number;
}

/**
 * Une face portée par plusieurs fichiers.
 *
 * Le doublon qui gêne n'est pas le fichier identique — celui-là, la
 * déduplication par empreinte l'attrape déjà à l'import — mais la même face
 * sous plusieurs noms, qui a donc autant d'empreintes différentes.
 */
export interface DuplicateFaceGroup {
  family: string;
  subfamily: string;
  /** Identité normalisée ; c'est elle que `resolve` attend. */
  key: string;
  keeper: Font;
  redundant: Font[];
  /** Gardés sans être *le* gardé (plusieurs fichiers multi-styles). */
  alsoKept: Font[];
  bytesFreed: number;
}

export interface DuplicateFacesResponse {
  items: DuplicateFaceGroup[];
  totalGroups: number;
  totalRedundant: number;
  bytesFreed: number;
  scanned: number;
  page: number;
  perPage: number;
  pages: number;
}

export interface ResolveDuplicatesResponse {
  groups: number;
  trashed: number;
  bytesFreed: number;
  dryRun: boolean;
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
