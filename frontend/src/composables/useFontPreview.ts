import { reactive } from "vue";
import { apiFetch } from "@/lib/api";

// Registre d'aperçus partagé à l'échelle de l'app (singleton module-level).
//
// Les `FontFace` chargées vivent dans `document.fonts` pour toute la session et
// ne sont JAMAIS déchargées au démontage d'un composant. C'était la cause du
// flash « vraie-fonte → police système » pendant la transition de SORTIE de la
// liste : démonter les cartes (navigation vers le détail) supprimait leurs
// `FontFace` de `document.fonts` alors que la page était encore peinte (en
// fondu out), faisant retomber tous les aperçus sur la police système le temps
// de la sortie. En gardant le cache vivant au-delà du cycle de vie des
// composants, la sortie ne touche plus aux fontes — et le retour à la liste est
// instantané (aperçus déjà prêts).
//
// Conséquence mémoire : le cache croît avec le nombre de fontes parcourues et
// n'est libéré qu'au rechargement de la page. C'était déjà le profil de fait
// (l'IntersectionObserver ne déchargeait jamais au scroll) ; on l'assume.

const loadedFonts = new Map<string, FontFace>();
const loadingFonts = new Set<string>();
// Compteur de références des préchargements directs (`preload`/`release`),
// conservé pour la compatibilité d'appel même si plus rien n'est déchargé.
const preloadRefs = new Map<string, number>();
// IDs des fontes « résolues » (chargées OU en échec). Réactif : les cartes s'en
// servent pour ne révéler leur aperçu qu'une fois la fonte prête (zéro flash
// fallback→vraie-fonte au scroll).
const ready = reactive(new Set<string>());
const entries = new Map<Element, string>();
let observer: IntersectionObserver | null = null;

function getFontFamily(fontId: string): string {
  return `preview-${fontId}`;
}

function isFontReady(fontId: string): boolean {
  return ready.has(fontId);
}

function getPreviewUrl(fontId: string): string {
  return `/api/fonts/${fontId}/preview`;
}

async function loadFont(fontId: string) {
  if (loadedFonts.has(fontId)) {
    ready.add(fontId);
    return;
  }
  if (loadingFonts.has(fontId)) return;
  loadingFonts.add(fontId);

  const family = getFontFamily(fontId);
  try {
    // `/api/fonts/:id/preview` exige le token : on récupère les octets avec
    // `apiFetch` (en-tête `Authorization`) puis on construit la `FontFace` à
    // partir du buffer — `url(...)` ne peut pas porter d'en-tête d'auth.
    const res = await apiFetch(getPreviewUrl(fontId));
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const buffer = await res.arrayBuffer();
    const face = new FontFace(family, buffer, { display: "block" });
    loadedFonts.set(fontId, face);
    document.fonts.add(face);
    await face.load();
  } catch {
    // Font failed to load — card will show fallback
    const face = loadedFonts.get(fontId);
    if (face) document.fonts.delete(face);
    loadedFonts.delete(fontId);
  } finally {
    loadingFonts.delete(fontId);
    // Résolu (succès → vraie fonte, échec → fallback) : la carte peut révéler
    // son aperçu sans risque de bascule visible.
    ready.add(fontId);
  }
}

function initObserver() {
  if (observer) return;

  observer = new IntersectionObserver(
    (intersections) => {
      for (const entry of intersections) {
        const fontId = entries.get(entry.target);
        if (!fontId) continue;

        // On charge uniquement à l'entrée ; jamais de déchargement (cf. en-tête
        // du module : le cache survit pour éviter tout flash en sortie de page).
        if (entry.isIntersecting) {
          loadFont(fontId);
        }
      }
    },
    // Marge large : on précharge les fontes bien avant que la carte entre dans
    // le viewport, pour qu'elles soient déjà prêtes au moment de l'affichage.
    { rootMargin: "1200px 0px" },
  );
}

function observe(el: Element, fontId: string) {
  initObserver();
  entries.set(el, fontId);
  observer!.observe(el);
}

function unobserve(el: Element) {
  entries.delete(el);
  observer?.unobserve(el);
  // On NE décharge PAS la fonte : le cache est volontairement persistant
  // (cf. en-tête du module).
}

// Préchargement direct (sans IntersectionObserver), pour les fontes dont
// l'élément n'est pas observable (lignes repliées/clippées). Le comptage de
// refs est conservé par compatibilité ; `release` ne décharge plus.
function preload(fontId: string) {
  preloadRefs.set(fontId, (preloadRefs.get(fontId) ?? 0) + 1);
  loadFont(fontId);
}

function release(fontId: string) {
  const next = (preloadRefs.get(fontId) ?? 1) - 1;
  if (next > 0) preloadRefs.set(fontId, next);
  else preloadRefs.delete(fontId);
}

export function useFontPreview() {
  return {
    getFontFamily,
    isFontReady,
    observe,
    unobserve,
    // Préchargement/relâche directs (hors IntersectionObserver), pour les fontes
    // dont l'élément n'est pas observable (lignes repliées/clippées).
    preload,
    release,
  };
}
