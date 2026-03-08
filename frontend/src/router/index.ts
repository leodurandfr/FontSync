import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/pages/DashboardPage.vue'),
    },
    {
      path: '/fonts',
      name: 'fonts',
      component: () => import('@/pages/FontsPage.vue'),
    },
    {
      path: '/fonts/:id',
      name: 'font-detail',
      component: () => import('@/pages/FontDetailPage.vue'),
      props: true,
    },
    {
      path: '/devices',
      name: 'devices',
      component: () => import('@/pages/DevicesPage.vue'),
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('@/pages/SettingsPage.vue'),
    },
  ],
})

export default router
