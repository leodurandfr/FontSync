<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Check, Copy, Link, Loader2 } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Panel } from "@/components/ui/panel";
import { SectionLabel } from "@/components/ui/section-label";
import { apiJson } from "@/lib/api";
import { useLocale } from "@/composables/useLocale";
import { useAuthStore } from "@/stores/auth";
import type { Invitation, InvitationCreated, Role, User } from "@/types/api";

/**
 * Administration des comptes (admin seulement) : ajout par lien d'invitation,
 * rôle, désactivation, nouveau mot de passe.
 */
const { t } = useI18n();
const { dateLocale } = useLocale();
const auth = useAuthStore();

const MIN_PASSWORD = 10;

const users = ref<User[]>([]);
const invitations = ref<Invitation[]>([]);
const errorMsg = ref<string | null>(null);

const inviteBusy = ref(false);
const inviteLink = ref<string | null>(null);
const copied = ref(false);

const resetFor = ref<string | null>(null);
const resetPassword = ref("");

const myId = computed(() => auth.me?.user?.id ?? null);

async function load() {
  try {
    const [u, i] = await Promise.all([
      apiJson<User[]>("/api/users"),
      apiJson<Invitation[]>("/api/invitations"),
    ]);
    users.value = u;
    invitations.value = i;
  } catch (err) {
    errorMsg.value = (err as Error).message;
  }
}

onMounted(load);

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(dateLocale.value, {
    dateStyle: "medium",
  });
}

/** Un lien à partager, rien d'autre : l'invité y saisit son email. */
async function createInvite() {
  errorMsg.value = null;
  inviteBusy.value = true;
  try {
    const created = await apiJson<InvitationCreated>(
      "/api/invitations",
      "POST",
      {},
    );
    // Le jeton voyage dans le fragment : jamais envoyé au serveur ni journalisé.
    inviteLink.value = `${window.location.origin}/invite#${created.token}`;
    copied.value = false;
    await load();
  } catch (err) {
    errorMsg.value = (err as Error).message;
  } finally {
    inviteBusy.value = false;
  }
}

async function copyLink() {
  if (!inviteLink.value) return;
  await navigator.clipboard.writeText(inviteLink.value);
  copied.value = true;
  setTimeout(() => (copied.value = false), 2000);
}

async function run(action: () => Promise<unknown>) {
  errorMsg.value = null;
  try {
    await action();
    await load();
  } catch (err) {
    errorMsg.value = (err as Error).message;
  }
}

function setRole(user: User, role: Role) {
  return run(() => apiJson(`/api/users/${user.id}`, "PATCH", { role }));
}

function setDisabled(user: User, disabled: boolean) {
  return run(() => apiJson(`/api/users/${user.id}`, "PATCH", { disabled }));
}

function cancelInvitation(invitation: Invitation) {
  return run(() => apiJson(`/api/invitations/${invitation.id}`, "DELETE"));
}

function openReset(user: User) {
  resetFor.value = user.id;
  resetPassword.value = "";
}

async function submitReset(user: User) {
  if (resetPassword.value.length < MIN_PASSWORD) {
    errorMsg.value = t("auth.errors.passwordTooShort", { n: MIN_PASSWORD });
    return;
  }
  await run(() =>
    apiJson(`/api/users/${user.id}/password`, "POST", {
      password: resetPassword.value,
    }),
  );
  if (!errorMsg.value) resetFor.value = null;
}
</script>

<template>
  <section>
    <SectionLabel class="mb-3">{{ t("users.title") }}</SectionLabel>
    <Panel class="space-y-5 p-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-[13px] text-muted-foreground">{{ t("users.desc") }}</p>
        <Button
          variant="outline"
          size="sm"
          :disabled="inviteBusy"
          @click="createInvite"
        >
          <Loader2 v-if="inviteBusy" class="mr-2 h-4 w-4 animate-spin" />
          <Link v-else class="mr-2 h-4 w-4" />
          {{ t("users.createInvite") }}
        </Button>
      </div>

      <!-- Lien fraîchement créé : à copier et envoyer -->
      <div
        v-if="inviteLink"
        class="space-y-2 rounded-lg border border-separator p-4"
      >
        <p class="text-[13px]">{{ t("users.inviteLink") }}</p>
        <div class="flex gap-2">
          <code
            class="min-w-0 flex-1 truncate rounded-lg border border-separator bg-muted/50 px-3 py-2 font-mono text-[12px]"
            >{{ inviteLink }}</code
          >
          <Button variant="outline" size="sm" @click="copyLink">
            <Check v-if="copied" class="mr-2 h-4 w-4" />
            <Copy v-else class="mr-2 h-4 w-4" />
            {{ copied ? t("users.copied") : t("users.copy") }}
          </Button>
        </div>
        <p class="text-xs text-muted-foreground">{{ t("users.inviteDesc") }}</p>
      </div>

      <p v-if="errorMsg" class="text-[13px] text-destructive" role="alert">
        {{ errorMsg }}
      </p>

      <!-- Comptes -->
      <ul class="divide-y divide-separator rounded-lg border border-separator">
        <li v-for="user in users" :key="user.id" class="space-y-2 px-3 py-2">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex min-w-0 flex-wrap items-center gap-2">
              <span class="truncate text-[13px]">{{ user.email }}</span>
              <span
                v-if="user.id === myId"
                class="text-xs text-muted-foreground"
                >({{ t("users.you") }})</span
              >
              <Badge variant="secondary">{{
                user.role === "admin"
                  ? t("account.roleAdmin")
                  : t("account.roleMember")
              }}</Badge>
              <Badge v-if="user.disabledAt" variant="destructive">{{
                t("users.disabled")
              }}</Badge>
              <span class="text-xs text-muted-foreground">{{
                t("users.devices", { n: user.deviceCount }, user.deviceCount)
              }}</span>
            </div>
            <div v-if="user.id !== myId" class="flex flex-wrap gap-1">
              <Button
                variant="ghost"
                size="sm"
                @click="
                  setRole(user, user.role === 'admin' ? 'member' : 'admin')
                "
              >
                {{
                  user.role === "admin"
                    ? t("users.makeMember")
                    : t("users.makeAdmin")
                }}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                @click="setDisabled(user, !user.disabledAt)"
              >
                {{ user.disabledAt ? t("users.enable") : t("users.disable") }}
              </Button>
              <Button variant="ghost" size="sm" @click="openReset(user)">
                {{ t("users.resetPassword") }}
              </Button>
            </div>
          </div>
          <form
            v-if="resetFor === user.id"
            class="grid max-w-sm gap-2 pb-1"
            @submit.prevent="submitReset(user)"
          >
            <p class="text-xs text-muted-foreground">
              {{ t("users.resetPasswordDesc", { email: user.email }) }}
            </p>
            <Input
              v-model="resetPassword"
              type="password"
              autocomplete="new-password"
              :aria-label="t('account.newPassword')"
              :placeholder="t('account.newPassword')"
              required
            />
            <div class="flex gap-2">
              <Button type="submit" size="sm">{{ t("users.confirm") }}</Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                @click="resetFor = null"
              >
                {{ t("users.cancel") }}
              </Button>
            </div>
          </form>
        </li>
      </ul>

      <!-- Invitations en attente -->
      <div v-if="invitations.length">
        <SectionLabel as="p" class="mb-1.5">{{
          t("users.pending")
        }}</SectionLabel>
        <ul
          class="divide-y divide-separator rounded-lg border border-separator"
        >
          <li
            v-for="invitation in invitations"
            :key="invitation.id"
            class="flex items-center justify-between gap-3 px-3 py-2"
          >
            <div class="min-w-0">
              <p class="truncate text-[13px]">
                {{
                  invitation.email ??
                  t("users.linkCreated", {
                    date: formatDate(invitation.createdAt),
                  })
                }}
              </p>
              <p class="text-xs text-muted-foreground">
                {{
                  t("users.expires", { date: formatDate(invitation.expiresAt) })
                }}
              </p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              @click="cancelInvitation(invitation)"
            >
              {{ t("users.cancelInvite") }}
            </Button>
          </li>
        </ul>
      </div>
    </Panel>
  </section>
</template>
