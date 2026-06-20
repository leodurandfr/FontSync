<script setup lang="ts">
import { ref } from "vue";
import {
  Type,
  AlignLeft,
  List,
  Heart,
  FolderPlus,
  Settings,
} from "lucide-vue-next";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import { SectionLabel } from "@/components/ui/section-label";
import { TogglePill } from "@/components/ui/toggle-pill";
import { TypoInput } from "@/components/ui/typo-input";
import {
  SegmentedControl,
  type SegmentedOption,
} from "@/components/ui/segmented";
import SidebarNavButton from "@/components/layout/SidebarNavButton.vue";
import ThemeToggle from "@/components/layout/ThemeToggle.vue";

// ── Démos interactives ────────────────────────────────────────
type Layout = "specimen" | "list";
const layout = ref<Layout>("specimen");
const layoutOptions: SegmentedOption<Layout>[] = [
  { value: "specimen", icon: AlignLeft, label: "Specimen" },
  { value: "list", icon: List, label: "List" },
];

const fontSize = ref(40);
const lineHeight = ref(1.1);
const letterSpacing = ref(0);

const active = ref(true);
const favorite = ref(false);
const navActive = ref("all");

// ── Tokens à montrer ──────────────────────────────────────────
const COLORS = [
  { name: "background", className: "bg-background", border: true },
  { name: "card", className: "bg-card", border: true },
  { name: "foreground", className: "bg-foreground" },
  { name: "muted", className: "bg-muted", border: true },
  { name: "muted-foreground", className: "bg-muted-foreground" },
  { name: "foreground-subtle", className: "bg-foreground-subtle" },
  { name: "primary", className: "bg-primary" },
  { name: "accent", className: "bg-accent", border: true },
  { name: "border", className: "bg-border" },
  { name: "separator", className: "bg-separator" },
  { name: "destructive", className: "bg-destructive" },
];

const RADII = [
  { name: "rounded-lg", className: "rounded-lg" },
  { name: "rounded-xl", className: "rounded-xl" },
  { name: "rounded-panel", className: "rounded-panel" },
];

const TYPE_CHROME = [
  {
    size: "text-[9px]",
    label: "9px · uppercase label",
    cls: "text-[9px] uppercase tracking-[0.14em] text-foreground-subtle",
  },
  {
    size: "text-[10px]",
    label: "10px · value mono",
    cls: "text-[10px] font-mono text-muted-foreground",
  },
  { size: "text-[11px]", label: "11px · nav / chrome", cls: "text-[11px]" },
  { size: "text-[13px]", label: "13px · list item", cls: "text-[13px]" },
];
</script>

<template>
  <div class="h-full overflow-y-auto">
    <div class="mx-auto max-w-4xl px-8 py-10">
      <!-- Header -->
      <header class="mb-10">
        <SectionLabel>Design system</SectionLabel>
        <h1 class="mt-2 text-3xl font-semibold tracking-tight">
          Foundations &amp; components
        </h1>
        <p class="mt-2 text-sm text-muted-foreground">
          Palette, typographie et composants de base de FontSync. Bascule le
          thème en haut à droite pour voir light / dark.
        </p>
      </header>

      <!-- ── Colors ─────────────────────────────────────────── -->
      <section class="mb-12">
        <h2 class="mb-4 text-sm font-semibold">Colors</h2>
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
          <div v-for="c in COLORS" :key="c.name" class="flex flex-col gap-1.5">
            <div
              class="h-14 w-full rounded-lg"
              :class="[c.className, c.border ? 'border border-border' : '']"
            />
            <span class="font-mono text-[10px] text-muted-foreground">{{
              c.name
            }}</span>
          </div>
        </div>
      </section>

      <!-- ── Typography ─────────────────────────────────────── -->
      <section class="mb-12">
        <h2 class="mb-4 text-sm font-semibold">Typography</h2>
        <div class="grid gap-6 md:grid-cols-2">
          <Panel class="p-6">
            <SectionLabel class="mb-3">Geist Sans — display</SectionLabel>
            <p class="font-sans text-4xl tracking-tight">Ag</p>
            <p class="mt-1 font-sans text-xl">The quick brown fox</p>
            <p class="mt-1 font-sans text-sm text-muted-foreground">
              The quick brown fox jumps over the lazy dog
            </p>
          </Panel>
          <Panel class="p-6">
            <SectionLabel class="mb-3">Geist Mono — chrome</SectionLabel>
            <div class="space-y-2.5">
              <div
                v-for="t in TYPE_CHROME"
                :key="t.size"
                class="flex items-baseline justify-between gap-3"
              >
                <span :class="t.cls">FontSync</span>
                <span class="font-mono text-[10px] text-foreground-subtle">{{
                  t.label
                }}</span>
              </div>
            </div>
          </Panel>
        </div>
      </section>

      <!-- ── Radius & elevation ─────────────────────────────── -->
      <section class="mb-12">
        <h2 class="mb-4 text-sm font-semibold">Radius &amp; elevation</h2>
        <div class="flex flex-wrap items-end gap-6">
          <div
            v-for="r in RADII"
            :key="r.name"
            class="flex flex-col items-center gap-2"
          >
            <div
              class="size-16 border border-border bg-muted"
              :class="r.className"
            />
            <span class="font-mono text-[10px] text-muted-foreground">{{
              r.name
            }}</span>
          </div>
          <div class="flex flex-col items-center gap-2">
            <Panel class="size-16" />
            <span class="font-mono text-[10px] text-muted-foreground"
              >shadow-panel</span
            >
          </div>
        </div>
      </section>

      <!-- ── Buttons ────────────────────────────────────────── -->
      <section class="mb-12">
        <h2 class="mb-4 text-sm font-semibold">Buttons</h2>
        <div class="flex flex-wrap items-center gap-3">
          <Button>Default</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destructive</Button>
          <Button size="icon" variant="ghost" aria-label="Settings">
            <Settings class="size-4" />
          </Button>
        </div>
      </section>

      <!-- ── Pills & controls ───────────────────────────────── -->
      <section class="mb-12">
        <h2 class="mb-4 text-sm font-semibold">Pills &amp; controls</h2>
        <Panel class="flex flex-wrap items-center gap-6 p-6">
          <TogglePill :pressed="active" @click="active = !active">
            <span
              class="size-1.5 rounded-full"
              :class="active ? 'bg-primary-foreground' : 'bg-foreground-subtle'"
            />
            {{ active ? "Active" : "Inactive" }}
          </TogglePill>

          <TogglePill :pressed="favorite" @click="favorite = !favorite">
            <Heart class="size-3" :stroke-width="1.5" />
            Favorite
          </TogglePill>

          <TogglePill>
            <FolderPlus class="size-3" :stroke-width="1.5" />
            Collect
          </TogglePill>

          <SegmentedControl v-model="layout" :options="layoutOptions" />
          <span class="font-mono text-[10px] text-muted-foreground"
            >layout: {{ layout }}</span
          >

          <div class="flex items-center gap-3">
            <TypoInput
              :icon="Type"
              v-model="fontSize"
              :min="10"
              :max="160"
              :step="1"
              suffix="px"
            />
            <TypoInput
              :icon="AlignLeft"
              v-model="lineHeight"
              :min="0.8"
              :max="3"
              :step="0.1"
              :digits="1"
            />
            <TypoInput
              :icon="List"
              v-model="letterSpacing"
              :min="-0.1"
              :max="0.3"
              :step="0.01"
              :digits="2"
            />
          </div>
        </Panel>
      </section>

      <!-- ── Nav & chrome ───────────────────────────────────── -->
      <section class="mb-12">
        <h2 class="mb-4 text-sm font-semibold">Nav &amp; chrome</h2>
        <Panel class="max-w-xs p-3">
          <SectionLabel class="px-2 pb-1.5">Library</SectionLabel>
          <SidebarNavButton
            label="All fonts"
            :count="128"
            :active="navActive === 'all'"
            @click="navActive = 'all'"
          />
          <SidebarNavButton
            label="Serif"
            :count="42"
            :active="navActive === 'serif'"
            @click="navActive = 'serif'"
          />
          <SidebarNavButton
            label="Sans-serif"
            :count="61"
            :active="navActive === 'sans'"
            @click="navActive = 'sans'"
          />
          <div class="mt-3 flex items-center justify-between px-2">
            <span class="text-[11px] text-muted-foreground">Theme</span>
            <ThemeToggle />
          </div>
        </Panel>
      </section>
    </div>
  </div>
</template>
