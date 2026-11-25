<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { KeyRound, Loader2, Type } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthError, useAuthStore } from "@/stores/auth";

/**
 * Écran d'avant l'application : création du premier administrateur, connexion,
 * acceptation d'une invitation (`/invite#<jeton>`), ou, pour la migration,
 * connexion par le token d'instance hérité.
 */
const props = defineProps<{ invitationToken?: string | null }>();
const emit = defineEmits<{ invitationDone: [] }>();

const { t } = useI18n();
const auth = useAuthStore();

const email = ref("");
const password = ref("");
const confirm = ref("");
const legacyToken = ref("");
const useToken = ref(false);
const busy = ref(false);
const errorMsg = ref<string | null>(null);
const invitation = ref<{ email: string; role: string } | null>(null);

const MIN_PASSWORD = 10;

const mode = computed<"invite" | "setup" | "token" | "login">(() => {
  if (props.invitationToken) return "invite";
  if (auth.phase === "setup") return "setup";
  if (useToken.value) return "token";
  return "login";
});

const subtitle = computed(() => {
  switch (mode.value) {
    case "invite":
      return t("auth.inviteSubtitle", { email: invitation.value?.email ?? "" });
    case "setup":
      return t("auth.setupSubtitle");
    case "token":
      return t("auth.tokenSubtitle");
    default:
      return t("auth.loginSubtitle");
  }
});

const needsNewPassword = computed(
  () => mode.value === "setup" || mode.value === "invite",
);

// Serveur déjà installé : prouver qu'on en est le propriétaire. Le token déjà
// mémorisé par ce navigateur suffit, sans rien ressaisir.
const showTokenField = computed(
  () =>
    mode.value === "token" ||
    (mode.value === "setup" && auth.setupNeedsLegacyToken && !auth.token),
);

onMounted(async () => {
  if (!props.invitationToken) return;
  try {
    invitation.value = await auth.lookupInvitation(props.invitationToken);
  } catch {
    errorMsg.value = t("auth.errors.invitationInvalid");
  }
});

function describe(err: unknown): string {
  if (err instanceof AuthError) {
    if (err.status === 429) return t("auth.errors.tooManyAttempts");
    if (err.status === 401) {
      return mode.value === "token"
        ? t("auth.errors.invalidToken")
        : t("auth.errors.badCredentials");
    }
    return err.message;
  }
  return t("auth.errors.unreachable");
}

async function submit() {
  errorMsg.value = null;
  if (needsNewPassword.value) {
    if (password.value.length < MIN_PASSWORD) {
      errorMsg.value = t("auth.errors.passwordTooShort", { n: MIN_PASSWORD });
      return;
    }
    if (password.value !== confirm.value) {
      errorMsg.value = t("auth.errors.passwordMismatch");
      return;
    }
  }
  busy.value = true;
  try {
    if (mode.value === "invite" && props.invitationToken) {
      await auth.acceptInvitation(props.invitationToken, password.value);
      emit("invitationDone");
    } else if (mode.value === "setup") {
      await auth.setup(email.value.trim(), password.value, legacyToken.value);
    } else if (mode.value === "token") {
      await auth.loginWithToken(legacyToken.value);
    } else {
      await auth.login(email.value.trim(), password.value);
    }
  } catch (err) {
    errorMsg.value = describe(err);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-background p-4">
    <div class="w-full max-w-sm space-y-6 rounded-xl border bg-card p-8">
      <div class="flex flex-col items-center gap-3 text-center">
        <div
          class="flex h-11 w-11 items-center justify-center rounded-xl bg-foreground text-background"
        >
          <Type class="h-5 w-5" />
        </div>
        <div>
          <h1 class="text-xl font-bold tracking-tight">
            {{ mode === "setup" ? t("auth.setupTitle") : "FontSync" }}
          </h1>
          <p class="mt-1 text-sm text-muted-foreground">{{ subtitle }}</p>
        </div>
      </div>

      <form class="space-y-3" @submit.prevent="submit">
        <div v-if="mode === 'setup' || mode === 'login'" class="space-y-1.5">
          <Label for="email">{{ t("auth.email") }}</Label>
          <Input
            id="email"
            v-model="email"
            type="email"
            autocomplete="username"
            :disabled="busy"
            required
            autofocus
          />
        </div>

        <div v-if="mode !== 'token'" class="space-y-1.5">
          <Label for="password">{{
            needsNewPassword ? t("auth.newPassword") : t("auth.password")
          }}</Label>
          <Input
            id="password"
            v-model="password"
            type="password"
            :autocomplete="
              needsNewPassword ? 'new-password' : 'current-password'
            "
            :disabled="busy"
            required
          />
        </div>

        <div v-if="needsNewPassword" class="space-y-1.5">
          <Label for="confirm">{{ t("auth.confirmPassword") }}</Label>
          <Input
            id="confirm"
            v-model="confirm"
            type="password"
            autocomplete="new-password"
            :disabled="busy"
            required
          />
          <p class="text-xs text-muted-foreground">
            {{ t("auth.passwordHint", { n: MIN_PASSWORD }) }}
          </p>
        </div>

        <div v-if="showTokenField" class="space-y-1.5">
          <Label for="token">{{ t("auth.instanceToken") }}</Label>
          <Input
            id="token"
            v-model="legacyToken"
            type="password"
            autocomplete="off"
            placeholder="FONTSYNC_TOKEN"
            :disabled="busy"
            required
          />
          <p v-if="mode === 'setup'" class="text-xs text-muted-foreground">
            {{ t("auth.setupTokenHint") }}
          </p>
        </div>

        <p v-if="errorMsg" class="text-sm text-destructive" role="alert">
          {{ errorMsg }}
        </p>

        <Button
          type="submit"
          class="w-full"
          :disabled="busy || (mode === 'invite' && !invitation)"
        >
          <Loader2 v-if="busy" class="mr-2 h-4 w-4 animate-spin" />
          {{
            mode === "setup"
              ? t("auth.createAdmin")
              : mode === "invite"
                ? t("auth.acceptInvite")
                : t("auth.signIn")
          }}
        </Button>
      </form>

      <div
        v-if="mode === 'login' || mode === 'token'"
        class="space-y-2 text-center text-xs text-muted-foreground"
      >
        <button
          v-if="mode === 'login' && auth.legacyTokenEnabled"
          type="button"
          class="inline-flex items-center gap-1.5 underline-offset-2 hover:underline"
          @click="useToken = true"
        >
          <KeyRound class="h-3 w-3" />
          {{ t("auth.useToken") }}
        </button>
        <button
          v-else-if="mode === 'token'"
          type="button"
          class="underline-offset-2 hover:underline"
          @click="useToken = false"
        >
          {{ t("auth.useAccount") }}
        </button>
        <p v-if="mode === 'login'">{{ t("auth.forgotPassword") }}</p>
      </div>
    </div>
  </div>
</template>
