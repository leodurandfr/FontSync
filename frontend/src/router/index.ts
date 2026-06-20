import { createRouter, createWebHistory } from "vue-router";

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

export default router;
