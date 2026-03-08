<script setup lang="ts">
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import AppSidebar from './AppSidebar.vue'
import AppHeader from './AppHeader.vue'
import { useWebSocket } from '@/composables/useWebSocket'

useWebSocket()
</script>

<template>
  <SidebarProvider>
    <AppSidebar />
    <SidebarInset>
      <AppHeader />
      <main class="flex-1 overflow-auto p-6">
        <RouterView />
      </main>
    </SidebarInset>
  </SidebarProvider>
</template>
