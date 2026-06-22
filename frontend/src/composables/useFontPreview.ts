import { ref, reactive, onScopeDispose } from "vue";
import { apiFetch } from "@/lib/api";

export function useFontPreview() {
  const observer = ref<IntersectionObserver | null>(null);
  const entries = new Map<Element, string>();
  const loadedFonts = new Map<string, FontFace>();
  const loadingFonts = new Set<string>();
  // IDs des fontes « résolues » (chargées OU en échec). Réactif : les cartes
  // s'en servent pour ne révéler leur aperçu qu'une fois la fonte prête, ce qui
  // évite tout flash fallback→vraie-fonte (FOUT) et le reflow associé au scroll.
  const ready = reactive(new Set<string>());

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

  function unloadFont(fontId: string) {
    const face = loadedFonts.get(fontId);
    if (face) {
      document.fonts.delete(face);
      loadedFonts.delete(fontId);
    }
    ready.delete(fontId);
  }

  function initObserver() {
    if (observer.value) return;

    observer.value = new IntersectionObserver(
      (intersections) => {
        for (const entry of intersections) {
          const fontId = entries.get(entry.target);
          if (!fontId) continue;

          // Only load on intersect — never unload via observer.
          // Fonts are unloaded only on explicit unobserve (component unmount).
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
    observer.value!.observe(el);
  }

  function unobserve(el: Element) {
    const fontId = entries.get(el);
    entries.delete(el);
    observer.value?.unobserve(el);

    // Only unload if no other element still references this font
    if (fontId) {
      const stillUsed = [...entries.values()].includes(fontId);
      if (!stillUsed) {
        unloadFont(fontId);
      }
    }
  }

  onScopeDispose(() => {
    observer.value?.disconnect();
    for (const fontId of loadedFonts.keys()) {
      unloadFont(fontId);
    }
    entries.clear();
  });

  return {
    getFontFamily,
    isFontReady,
    observe,
    unobserve,
    // Chargement direct (sans passer par l'IntersectionObserver), pour
    // précharger des fontes dont l'élément n'est pas encore visible/observable.
    preload: loadFont,
  };
}
