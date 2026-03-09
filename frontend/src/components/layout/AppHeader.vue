<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import {
  LayoutDashboard,
  Type,
  Layers,
  Monitor,
  Settings,
} from "lucide-vue-next";
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
  navigationMenuTriggerStyle,
} from "@/components/ui/navigation-menu";

const route = useRoute();

const navItems = [
  { label: "Dashboard", icon: LayoutDashboard, to: "/" },
  { label: "Polices", icon: Type, to: "/fonts" },
  { label: "Familles", icon: Layers, to: "/families" },
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
  </header>
</template>
