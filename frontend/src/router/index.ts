import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "@/stores/auth";

declare module "vue-router" {
  interface RouteMeta {
    /** Page réservée aux administrateurs (corbeille, doublons). */
    adminOnly?: boolean;
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "fonts",
      component: () => import("@/pages/FontsPage.vue"),
    },
    {
      path: "/fonts/:id",
      name: "font-detail",
      component: () => import("@/pages/FontDetailPage.vue"),
      props: true,
    },
    {
      path: "/duplicates",
      name: "duplicates",
      component: () => import("@/pages/DuplicatesPage.vue"),
      meta: { adminOnly: true },
    },
    {
      path: "/trash",
      name: "trash",
      component: () => import("@/pages/TrashPage.vue"),
      meta: { adminOnly: true },
    },
    {
      path: "/settings",
      name: "settings",
      component: () => import("@/pages/SettingsPage.vue"),
    },
    {
      path: "/design-system",
      name: "design-system",
      component: () => import("@/pages/DesignSystemPage.vue"),
    },
  ],
});

// Tant que l'identité n'est pas connue (`checking`), App.vue n'affiche rien :
// on laisse passer, et App.vue revérifie une fois l'identité chargée.
router.beforeEach((to) => {
  const auth = useAuthStore();
  if (to.meta.adminOnly && auth.phase === "ready" && !auth.isAdmin) {
    return { name: "fonts" };
  }
});

export default router;
