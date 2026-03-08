<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  LayoutDashboard,
  Type,
  Monitor,
  Settings,
} from 'lucide-vue-next'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from '@/components/ui/sidebar'

const route = useRoute()

const navItems = [
  { label: 'Dashboard', icon: LayoutDashboard, to: '/' },
  { label: 'Polices', icon: Type, to: '/fonts' },
  { label: 'Appareils', icon: Monitor, to: '/devices' },
  { label: 'Paramètres', icon: Settings, to: '/settings' },
]

const isActive = computed(() => (path: string) => {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
})
</script>

<template>
  <Sidebar collapsible="icon">
    <SidebarHeader class="p-4">
      <RouterLink to="/" class="flex items-center gap-2 group-data-[collapsible=icon]:justify-center">
        <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-foreground text-background">
          <Type class="h-4 w-4" />
        </div>
        <span class="text-lg font-bold tracking-tight group-data-[collapsible=icon]:hidden">
          FontSync
        </span>
      </RouterLink>
    </SidebarHeader>

    <SidebarContent>
      <SidebarGroup>
        <SidebarGroupLabel>Navigation</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem v-for="item in navItems" :key="item.to">
              <SidebarMenuButton
                as-child
                :is-active="isActive(item.to)"
                :tooltip="item.label"
              >
                <RouterLink :to="item.to">
                  <component :is="item.icon" />
                  <span>{{ item.label }}</span>
                </RouterLink>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>

    <SidebarFooter class="p-4 group-data-[collapsible=icon]:p-2">
      <p class="text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
        FontSync v0.1
      </p>
    </SidebarFooter>

    <SidebarRail />
  </Sidebar>
</template>
