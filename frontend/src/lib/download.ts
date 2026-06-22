import { apiFetch } from "./api";

/**
 * Télécharge un fichier depuis une route `/api` protégée via un blob
 * authentifié : un `<a href>` direct ne peut pas porter le token sur une route
 * protégée. Le nom de fichier est lu depuis l'en-tête `Content-Disposition`
 * renvoyé par le serveur, avec repli sur `fallbackName`.
 */
export async function downloadFromApi(
  path: string,
  fallbackName: string,
): Promise<void> {
  const res = await apiFetch(path);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const filename =
    filenameFromDisposition(res.headers.get("Content-Disposition")) ??
    fallbackName;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null;
  // `filename*=UTF-8''<encoded>` est prioritaire (RFC 5987).
  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star) {
    try {
      return decodeURIComponent(star[1]);
    } catch {
      return null;
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : null;
}
