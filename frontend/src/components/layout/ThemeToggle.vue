<script setup lang="ts">
import { computed } from "vue";
import { Sun, Moon, Monitor, Check } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { useTheme, type Theme } from "@/composables/useTheme";

const { t } = useI18n();

const { theme, setTheme } = useTheme();

const OPTIONS = computed<{ value: Theme; label: string; icon: typeof Sun }[]>(
  () => [
    { value: "light", label: t("theme.light"), icon: Sun },
    { value: "dark", label: t("theme.dark"), icon: Moon },
    { value: "system", label: t("theme.system"), icon: Monitor },
  ],
);

const currentIcon = computed(
  () => OPTIONS.value.find((o) => o.value === theme.value)?.icon ?? Sun,
);
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger
      class="flex size-8 flex-shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent data-[state=open]:bg-accent"
      :aria-label="t('theme.aria')"
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
