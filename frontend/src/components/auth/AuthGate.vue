<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Loader2, Type } from "lucide-vue-next";
import { useI18n } from "vue-i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { AuthError, useAuthStore } from "@/stores/auth";

/**
 * Écran d'avant l'application : création du premier administrateur, connexion,
 * ou acceptation d'une invitation (`/invite#<jeton>`).
 */
const props = defineProps<{ invitationToken?: string | null }>();
const emit = defineEmits<{ invitationDone: [] }>();

const { t } = useI18n();
const auth = useAuthStore();

const email = ref("");
const password = ref("");
const confirm = ref("");
const busy = ref(false);
const errorMsg = ref<string | null>(null);
const invitation = ref<{ email: string | null; role: string } | null>(null);

const MIN_PASSWORD = 10;

const mode = computed<"invite" | "setup" | "login">(() => {
  if (props.invitationToken) return "invite";
  if (auth.phase === "setup") return "setup";
  return "login";
});

const subtitle = computed(() => {
  switch (mode.value) {
    case "invite":
      return invitation.value?.email
        ? t("auth.inviteSubtitleFixed", { email: invitation.value.email })
        : t("auth.inviteSubtitle");
    case "setup":
      return t("auth.setupSubtitle");
    default:
      return t("auth.loginSubtitle");
  }
});

const needsNewPassword = computed(
  () => mode.value === "setup" || mode.value === "invite",
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
      return t("auth.errors.badCredentials");
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
      await auth.acceptInvitation(
        props.invitationToken,
        invitation.value?.email ? "" : email.value.trim(),
        password.value,
      );
      emit("invitationDone");
    } else if (mode.value === "setup") {
      await auth.setup(email.value.trim(), password.value);
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
        <div
          v-if="
            mode === 'setup' ||
            mode === 'login' ||
            (mode === 'invite' && invitation && !invitation.email)
          "
          class="space-y-1.5"
        >
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

        <div class="space-y-1.5">
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

      <p
        v-if="mode === 'login'"
        class="text-center text-xs text-muted-foreground"
      >
        {{ t("auth.forgotPassword") }}
      </p>
    </div>
  </div>
</template>
