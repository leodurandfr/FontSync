<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Check, Copy, Loader2, UserPlus } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Panel } from "@/components/ui/panel";
import { SectionLabel } from "@/components/ui/section-label";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { apiJson } from "@/lib/api";
import { useLocale } from "@/composables/useLocale";
import { useAuthStore } from "@/stores/auth";
import type { Invitation, InvitationCreated, Role, User } from "@/types/api";

/**
 * Administration des comptes (admin seulement) : ajout par lien d'invitation
 * ou création directe, rôle, désactivation, nouveau mot de passe.
 */
const { t } = useI18n();
const { dateLocale } = useLocale();
const auth = useAuthStore();

const MIN_PASSWORD = 10;

const users = ref<User[]>([]);
const invitations = ref<Invitation[]>([]);
const errorMsg = ref<string | null>(null);

const adding = ref(false);
const addMode = ref<"invite" | "create">("invite");
const addEmail = ref("");
const addPassword = ref("");
const addRole = ref<Role>("member");
const addBusy = ref(false);
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

function openAdd() {
  adding.value = true;
  inviteLink.value = null;
  addEmail.value = "";
  addPassword.value = "";
  addRole.value = "member";
  errorMsg.value = null;
}

async function submitAdd() {
  errorMsg.value = null;
  if (addMode.value === "create" && addPassword.value.length < MIN_PASSWORD) {
    errorMsg.value = t("auth.errors.passwordTooShort", { n: MIN_PASSWORD });
    return;
  }
  addBusy.value = true;
  try {
    if (addMode.value === "invite") {
      const created = await apiJson<InvitationCreated>(
        "/api/invitations",
        "POST",
        { email: addEmail.value.trim(), role: addRole.value },
      );
      // Le jeton voyage dans le fragment : jamais envoyé au serveur ni journalisé.
      inviteLink.value = `${window.location.origin}/invite#${created.token}`;
    } else {
      await apiJson("/api/users", "POST", {
        email: addEmail.value.trim(),
        password: addPassword.value,
        role: addRole.value,
      });
      adding.value = false;
    }
    await load();
  } catch (err) {
    errorMsg.value = (err as Error).message;
  } finally {
    addBusy.value = false;
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

function onModeChange(value: unknown) {
  if (value === "invite" || value === "create") addMode.value = value;
}

function onRoleChange(value: unknown) {
  if (value === "admin" || value === "member") addRole.value = value;
}
</script>

<template>
  <section>
    <SectionLabel class="mb-3">{{ t("users.title") }}</SectionLabel>
    <Panel class="space-y-5 p-6">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-[13px] text-muted-foreground">{{ t("users.desc") }}</p>
        <Button v-if="!adding" variant="outline" size="sm" @click="openAdd">
          <UserPlus class="mr-2 h-4 w-4" />
          {{ t("users.add") }}
        </Button>
      </div>

      <!-- Ajout : lien d'invitation ou création directe -->
      <div
        v-if="adding"
        class="space-y-3 rounded-lg border border-separator p-4"
      >
        <ToggleGroup
          type="single"
          variant="outline"
          :model-value="addMode"
          @update:model-value="onModeChange"
        >
          <ToggleGroupItem value="invite">{{
            t("users.modeInvite")
          }}</ToggleGroupItem>
          <ToggleGroupItem value="create">{{
            t("users.modeCreate")
          }}</ToggleGroupItem>
        </ToggleGroup>
        <p class="text-[13px] text-muted-foreground">
          {{
            addMode === "invite" ? t("users.inviteDesc") : t("users.createDesc")
          }}
        </p>

        <div v-if="inviteLink" class="space-y-2">
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
          <Button variant="ghost" size="sm" @click="adding = false">
            {{ t("users.confirm") }}
          </Button>
        </div>

        <form v-else class="grid max-w-sm gap-3" @submit.prevent="submitAdd">
          <div class="space-y-1.5">
            <Label for="add-email">{{ t("auth.email") }}</Label>
            <Input
              id="add-email"
              v-model="addEmail"
              type="email"
              autocomplete="off"
              required
            />
          </div>
          <div v-if="addMode === 'create'" class="space-y-1.5">
            <Label for="add-password">{{ t("auth.password") }}</Label>
            <Input
              id="add-password"
              v-model="addPassword"
              type="password"
              autocomplete="new-password"
              required
            />
          </div>
          <div class="space-y-1.5">
            <Label>{{ t("users.role") }}</Label>
            <ToggleGroup
              type="single"
              variant="outline"
              :model-value="addRole"
              @update:model-value="onRoleChange"
            >
              <ToggleGroupItem value="member">{{
                t("account.roleMember")
              }}</ToggleGroupItem>
              <ToggleGroupItem value="admin">{{
                t("account.roleAdmin")
              }}</ToggleGroupItem>
            </ToggleGroup>
          </div>
          <div class="flex gap-2">
            <Button type="submit" size="sm" :disabled="addBusy">
              <Loader2 v-if="addBusy" class="mr-2 h-4 w-4 animate-spin" />
              {{
                addMode === "invite"
                  ? t("users.createInvite")
                  : t("users.createAccount")
              }}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              @click="adding = false"
            >
              {{ t("users.cancel") }}
            </Button>
          </div>
        </form>
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
              <p class="truncate text-[13px]">{{ invitation.email }}</p>
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
