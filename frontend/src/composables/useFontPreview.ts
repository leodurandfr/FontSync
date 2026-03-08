import { ref, onScopeDispose } from "vue";

export function useFontPreview() {
  const observer = ref<IntersectionObserver | null>(null);
  const entries = new Map<Element, string>();
  const loadedFonts = new Map<string, FontFace>();

  function getFontFamily(fontId: string): string {
    return `preview-${fontId}`;
  }

  function getPreviewUrl(fontId: string): string {
    return `/api/fonts/${fontId}/preview`;
  }

  async function loadFont(fontId: string) {
    const family = getFontFamily(fontId);
    if (loadedFonts.has(fontId)) return;

    try {
      const face = new FontFace(family, `url(${getPreviewUrl(fontId)})`, {
        display: "swap",
      });
      loadedFonts.set(fontId, face);
      document.fonts.add(face);
      await face.load();
    } catch {
      // Font failed to load — card will show fallback
      loadedFonts.delete(fontId);
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

          if (entry.isIntersecting) {
            loadFont(fontId);
          } else {
            unloadFont(fontId);
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
    if (fontId) {
      unloadFont(fontId);
      entries.delete(el);
    }
    observer.value?.unobserve(el);
  }

  onScopeDispose(() => {
    observer.value?.disconnect();
    for (const fontId of entries.values()) {
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
