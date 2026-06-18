import { ref, onScopeDispose } from "vue";
import { apiFetch } from "@/lib/api";

export function useFontPreview() {
  const observer = ref<IntersectionObserver | null>(null);
  const entries = new Map<Element, string>();
  const loadedFonts = new Map<string, FontFace>();
  const loadingFonts = new Set<string>();

  function getFontFamily(fontId: string): string {
    return `preview-${fontId}`;
  }

  function getPreviewUrl(fontId: string): string {
    return `/api/fonts/${fontId}/preview`;
  }

  async function loadFont(fontId: string) {
    if (loadedFonts.has(fontId) || loadingFonts.has(fontId)) return;
    loadingFonts.add(fontId);

    const family = getFontFamily(fontId);
    try {
      // `/api/fonts/:id/preview` exige le token : on récupère les octets avec
      // `apiFetch` (en-tête `Authorization`) puis on construit la `FontFace` à
      // partir du buffer — `url(...)` ne peut pas porter d'en-tête d'auth.
      const res = await apiFetch(getPreviewUrl(fontId));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const buffer = await res.arrayBuffer();
      const face = new FontFace(family, buffer, { display: "swap" });
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
    }
  }

  function unloadFont(fontId: string) {
    const face = loadedFonts.get(fontId);
    if (face) {
      document.fonts.delete(face);
      loadedFonts.delete(fontId);
    }
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
      { rootMargin: "200px 0px" },
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
    observe,
    unobserve,
  };
}
