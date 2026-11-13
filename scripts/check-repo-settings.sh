#!/usr/bin/env bash
#
# Vérifie (lecture seule, `gh api` en GET) les réglages de sécurité du dépôt
# GitHub attendus par docs/RELEASE.md. Sort en erreur si l'un manque.
#
# Usage : scripts/check-repo-settings.sh [owner/repo]   (défaut : le dépôt courant)
# Prérequis : gh authentifié avec le scope `repo` (droits admin pour lire les rulesets).

set -uo pipefail

gh api user --silent 2>/dev/null || {
  echo "gh n'est pas authentifié (gh auth login) : aucun réglage n'a pu être lu" >&2
  exit 2
}
repo="${1:-$(gh repo view --json nameWithOwner --jq .nameWithOwner)}"
fail=0
ok() { echo "OK    $1"; }
ko() { echo "ÉCHEC $1"; fail=1; }

if gh api "repos/$repo/vulnerability-alerts" --silent 2>/dev/null; then
  ok "alertes Dependabot actives"
else
  ko "alertes Dependabot désactivées"
fi

[ "$(gh api "repos/$repo/automated-security-fixes" --jq .enabled 2>/dev/null)" = "true" ] \
  && ok "correctifs de sécurité Dependabot actifs" || ko "correctifs de sécurité Dependabot inactifs"

perms="$(gh api "repos/$repo/actions/permissions" --jq '"\(.allowed_actions) \(.sha_pinning_required)"' 2>/dev/null)"
[ "$perms" = "selected true" ] \
  && ok "actions restreintes et épinglage par SHA exigé" || ko "permissions d'actions : '$perms' (attendu : 'selected true')"

sel="$(gh api "repos/$repo/actions/permissions/selected-actions" \
  --jq '"\(.github_owned_allowed) \(.patterns_allowed | sort | join(","))"' 2>/dev/null)"
[ "$sel" = "true docker/*" ] \
  && ok "actions autorisées : GitHub + docker/*" || ko "actions autorisées : '$sel' (attendu : 'true docker/*')"

rules="$(gh api "repos/$repo/rulesets?includes_parents=false" --jq '[.[] | select(.enforcement == "active") | .name] | sort | join(",")' 2>/dev/null)"
case ",$rules," in *",protect-main,"*) ok "ruleset protect-main actif" ;; *) ko "ruleset protect-main absent ou inactif" ;; esac
case ",$rules," in *",protect-release-tags,"*) ok "ruleset protect-release-tags actif" ;; *) ko "ruleset protect-release-tags absent ou inactif" ;; esac

exit "$fail"
