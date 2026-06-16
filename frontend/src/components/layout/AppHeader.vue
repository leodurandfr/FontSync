<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import {
  LayoutDashboard,
  Type,
  Monitor,
  Settings,
  Loader2,
} from "lucide-vue-next";
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  navigationMenuTriggerStyle,
} from "@/components/ui/navigation-menu";
import { useWsStore } from "@/stores/ws";

const route = useRoute();
const wsStore = useWsStore();

const navItems = [
  { label: "Dashboard", icon: LayoutDashboard, to: "/" },
  { label: "Polices", icon: Type, to: "/fonts" },
  { label: "Appareils", icon: Monitor, to: "/devices" },
  { label: "Paramètres", icon: Settings, to: "/settings" },
];

const isActive = computed(() => (path: string) => {
  if (path === "/") return route.path === "/";
  return route.path.startsWith(path);
});
</script>

<template>
  <header class="flex h-14 shrink-0 items-center border-b px-4">
    <!-- Logo -->
    <RouterLink to="/" class="flex items-center gap-2 shrink-0">
      <div
        class="flex h-7 w-7 items-center justify-center rounded-lg bg-foreground text-background"
      >
        <Type class="h-3.5 w-3.5" />
      </div>
      <span class="text-base font-bold tracking-tight hidden sm:inline"
        >FontSync</span
      >
    </RouterLink>

    <!-- Navigation (centered) -->
    <NavigationMenu class="mx-auto">
      <NavigationMenuList>
        <NavigationMenuItem v-for="item in navItems" :key="item.to">
          <NavigationMenuLink as-child :active="isActive(item.to)">
            <RouterLink :to="item.to" :class="navigationMenuTriggerStyle()">
              <component :is="item.icon" class="h-4 w-4 mr-1.5" />
              <span class="hidden md:inline">{{ item.label }}</span>
            </RouterLink>
          </NavigationMenuLink>
        </NavigationMenuItem>
      </NavigationMenuList>
    </NavigationMenu>

    <!-- Connection status -->
    <div
      class="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground"
    >
      <template v-if="wsStore.status === 'connected'">
        <span class="h-2 w-2 rounded-full bg-green-500" />
        <span class="hidden lg:inline">Connecté</span>
      </template>
      <template v-else>
        <Loader2 class="h-3 w-3 animate-spin text-amber-500" />
        <span class="hidden sm:inline">Reconnexion…</span>
      </template>
    </div>
  </header>
</template>
