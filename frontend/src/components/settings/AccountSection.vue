<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Laptop, Loader2, LogOut, Monitor } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Panel } from "@/components/ui/panel";
import { SectionLabel } from "@/components/ui/section-label";
import { apiJson } from "@/lib/api";
import { useLocale } from "@/composables/useLocale";
import { useAuthStore } from "@/stores/auth";
import type { AuthSession } from "@/types/api";

/** Mon compte : identité, mot de passe, sessions (navigateurs et Mac). */
const { t } = useI18n();
const { dateLocale } = useLocale();
const auth = useAuthStore();

const sessions = ref<AuthSession[]>([]);
const currentPassword = ref("");
const newPassword = ref("");
const savingPassword = ref(false);
const passwordMsg = ref<{ ok: boolean; text: string } | null>(null);
const showPasswordForm = ref(false);

const user = computed(() => auth.me?.user ?? null);

async function loadSessions() {
  if (!user.value) return;
  sessions.value = await apiJson<AuthSession[]>("/api/auth/sessions");
}

onMounted(() => {
  void loadSessions();
});

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(dateLocale.value, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

const BROWSERS: [string, string][] = [
  ["Edg/", "Edge"],
  ["Firefox/", "Firefox"],
  ["Chrome/", "Chrome"],
  ["Safari/", "Safari"],
];
const SYSTEMS: [string, string][] = [
  ["iPhone", "iOS"],
  ["iPad", "iPadOS"],
  ["Mac OS X", "macOS"],
  ["Windows", "Windows"],
  ["Android", "Android"],
  ["Linux", "Linux"],
];

function firstMatch(label: string, table: [string, string][]): string | null {
  return table.find(([needle]) => label.includes(needle))?.[1] ?? null;
}

/** « Chrome · macOS » plutôt que l'en-tête User-Agent brut. */
function describeAgent(label: string): string {
  const parts = [firstMatch(label, BROWSERS), firstMatch(label, SYSTEMS)];
  const known = parts.filter((part): part is string => part !== null);
  return known.length ? known.join(" · ") : label;
}

function sessionName(session: AuthSession): string {
  if (session.kind === "device") return session.label || t("account.mac");
  return session.label ? describeAgent(session.label) : t("account.browser");
}

async function changePassword() {
  passwordMsg.value = null;
  if (newPassword.value.length < 10) {
    passwordMsg.value = {
      ok: false,
      text: t("auth.errors.passwordTooShort", { n: 10 }),
    };
    return;
  }
  savingPassword.value = true;
  try {
    await apiJson("/api/auth/me/password", "POST", {
      currentPassword: currentPassword.value,
      newPassword: newPassword.value,
    });
    currentPassword.value = "";
    newPassword.value = "";
    showPasswordForm.value = false;
    passwordMsg.value = { ok: true, text: t("account.passwordChanged") };
    await loadSessions();
  } catch (err) {
    passwordMsg.value = { ok: false, text: (err as Error).message };
  } finally {
    savingPassword.value = false;
  }
}

async function revoke(session: AuthSession) {
  await apiJson(`/api/auth/sessions/${session.id}`, "DELETE");
  if (session.current) {
    await auth.logout();
    return;
  }
  await loadSessions();
}
</script>

<template>
  <section>
    <SectionLabel class="mb-3">{{ t("account.title") }}</SectionLabel>
    <Panel class="space-y-5 p-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="flex items-center gap-2">
          <p class="text-[13px]">
            {{
              user
                ? t("account.signedInAs", { email: user.email })
                : t("account.legacySession")
            }}
          </p>
          <Badge variant="secondary">
            {{
              auth.me?.role === "admin"
                ? t("account.roleAdmin")
                : t("account.roleMember")
            }}
          </Badge>
        </div>
        <Button variant="outline" size="sm" @click="auth.logout()">
          <LogOut class="mr-2 h-4 w-4" />
          {{ t("account.logout") }}
        </Button>
      </div>

      <p
        v-if="auth.isAdmin && auth.legacyTokenEnabled"
        class="rounded-lg border border-separator bg-muted/50 px-3 py-2 text-[13px] text-muted-foreground"
      >
        {{ t("account.legacyTokenActive") }}
      </p>

      <template v-if="user">
        <div>
          <Button
            v-if="!showPasswordForm"
            variant="outline"
            size="sm"
            @click="showPasswordForm = true"
          >
            {{ t("account.changePassword") }}
          </Button>
          <form
            v-else
            class="grid max-w-sm gap-3"
            @submit.prevent="changePassword"
          >
            <div class="space-y-1.5">
              <Label for="current-password">{{
                t("account.currentPassword")
              }}</Label>
              <Input
                id="current-password"
                v-model="currentPassword"
                type="password"
                autocomplete="current-password"
                required
              />
            </div>
            <div class="space-y-1.5">
              <Label for="new-password">{{ t("account.newPassword") }}</Label>
              <Input
                id="new-password"
                v-model="newPassword"
                type="password"
                autocomplete="new-password"
                required
              />
            </div>
            <div class="flex gap-2">
              <Button type="submit" size="sm" :disabled="savingPassword">
                <Loader2
                  v-if="savingPassword"
                  class="mr-2 h-4 w-4 animate-spin"
                />
                {{ t("account.save") }}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                @click="showPasswordForm = false"
              >
                {{ t("users.cancel") }}
              </Button>
            </div>
          </form>
          <p
            v-if="passwordMsg"
            class="mt-2 text-[13px]"
            :class="
              passwordMsg.ok ? 'text-muted-foreground' : 'text-destructive'
            "
          >
            {{ passwordMsg.text }}
          </p>
        </div>

        <div>
          <SectionLabel as="p" class="mb-1.5">{{
            t("account.sessions")
          }}</SectionLabel>
          <p class="mb-3 text-[13px] text-muted-foreground">
            {{ t("account.sessionsDesc") }}
          </p>
          <ul
            class="divide-y divide-separator rounded-lg border border-separator"
          >
            <li
              v-for="session in sessions"
              :key="session.id"
              class="flex items-center justify-between gap-3 px-3 py-2"
            >
              <div class="flex min-w-0 items-center gap-2">
                <Laptop
                  v-if="session.kind === 'device'"
                  class="h-4 w-4 shrink-0 text-muted-foreground"
                />
                <Monitor
                  v-else
                  class="h-4 w-4 shrink-0 text-muted-foreground"
                />
                <div class="min-w-0">
                  <p class="truncate text-[13px]">
                    {{ sessionName(session) }}
                    <Badge
                      v-if="session.current"
                      variant="secondary"
                      class="ml-1"
                      >{{ t("account.thisSession") }}</Badge
                    >
                  </p>
                  <p class="text-xs text-muted-foreground">
                    {{
                      t("account.lastUsed", {
                        date: formatDate(session.lastUsedAt),
                      })
                    }}
                  </p>
                </div>
              </div>
              <Button variant="ghost" size="sm" @click="revoke(session)">
                {{ t("account.revoke") }}
              </Button>
            </li>
          </ul>
        </div>
      </template>
    </Panel>
  </section>
</template>
