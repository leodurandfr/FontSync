<script setup lang="ts">
import { computed } from "vue";
import { Sun, Moon, Monitor, Check } from "lucide-vue-next";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { useTheme, type Theme } from "@/composables/useTheme";

const { theme, setTheme } = useTheme();

const OPTIONS: { value: Theme; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

const currentIcon = computed(
  () => OPTIONS.find((o) => o.value === theme.value)?.icon ?? Sun,
);
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger
      class="flex size-8 flex-shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent data-[state=open]:bg-accent"
      aria-label="Thème"
    >
      <component :is="currentIcon" class="size-3.5" :stroke-width="1.5" />
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end" class="w-44">
      <DropdownMenuItem
        v-for="opt in OPTIONS"
        :key="opt.value"
        class="font-mono text-[11px]"
        @select="setTheme(opt.value)"
      >
        <component :is="opt.icon" class="size-3.5" :stroke-width="1.5" />
        <span class="flex-1">{{ opt.label }}</span>
        <Check
          v-if="theme === opt.value"
          class="size-3 text-primary"
          :stroke-width="2.5"
        />
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
</template>
