# FontSync — Tester en local (sans NAS)

Ce guide explique comment faire tourner **le serveur et les clients en local**,
sur un seul Mac, sans jamais pousser sur le NAS ni toucher ton vrai
`~/Library/Fonts`.

Rappel d'architecture : le **serveur est la source de vérité**, l'**agent est
stateless** (chaque `sync` repart de l'état réel du disque). Une « machine B »
n'est donc rien d'autre qu'**un 2ᵉ device_id + un dossier de fonts isolé** qui
pointe sur le même serveur — tout ça tient sur une seule machine.

> Un 2ᵉ Mac physique n'est utile qu'**une seule fois**, comme smoke test final
> avant publication (vraie découverte Core Text + launchd + activation des fonts
> dans les apps). Pas pour le dev courant.

## Prérequis

Un virtualenv avec les deps backend **et** agent :

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r agent/requirements.txt
```

## 1. Lancer le serveur

Deux options, au choix :

```bash
# A) Hôte (boucle la plus rapide, reload à chaud, SQLite jetable dans .dev/) :
scripts/dev/run-server.sh

# B) Proche-prod (Docker) :
docker compose up
```

Les deux exposent le serveur sur **http://localhost:8080** — qui est déjà le
défaut de l'agent (`server.url` dans la config). Vérifier :

```bash
curl http://localhost:8080/health   # → {"status":"ok"}
```

## 2. Simuler plusieurs machines

`scripts/dev/run-agent.sh <profil> <commande>` lance l'agent sous un **profil**
de device isolé (`A`, `B`, …). Chaque profil a, sous `.dev/<profil>/` :

- son propre état (config + cache de hash + `disabled/`) ;
- son propre dossier de fonts (`.dev/<profil>/fonts`) ;
- un **hostname distinct** → le serveur le voit comme un device séparé
  (l'enregistrement est un upsert par hostname).

Cela repose sur des variables d'environnement neutres en production
(résolues dans [`agent/paths.py`](agent/paths.py) et `agent/config.py`) :

| Variable              | Rôle                                            |
|-----------------------|-------------------------------------------------|
| `FONTSYNC_HOME`       | dossier d'état (au lieu de `~/.fontsync`)       |
| `FONTSYNC_FONTS_DIR`  | dossier d'install (au lieu de `~/Library/Fonts`)|
| `FONTSYNC_DISCOVERY`  | `directories` → scan du dossier isolé, pas Core Text |
| `FONTSYNC_HOSTNAME`   | hostname (clé d'upsert serveur)                 |
| `FONTSYNC_DEVICE_NAME`| nom affiché du device                           |

## 3. Démo de bout en bout

```bash
# Serveur lancé (étape 1), puis :
scripts/dev/demo.sh
```

Le script : graine une font chez le device A → `sync A` (push) →
`sync B` (pull + install) → vérifie que la font est arrivée chez B. C'est la
preuve que la boucle **A → serveur → B** fonctionne.

Manuellement, pas à pas :

```bash
# Poser une font de test chez A (génère une vraie TTF valide) :
.venv/bin/python scripts/dev/seed-font.py .dev/A/fonts --family "Inter" --style Regular

scripts/dev/run-agent.sh A sync     # A pousse vers le serveur
scripts/dev/run-agent.sh B sync     # B pull + installe dans .dev/B/fonts
ls .dev/B/fonts                      # → la font est là
```

## 4. Tester la sync réactive (SSE)

Le `listen` ouvre un flux SSE et relance `sync` à chaque signal serveur :

```bash
scripts/dev/run-agent.sh B listen     # laisse tourner dans un terminal
# dans un autre terminal, pousse une nouvelle font chez A :
.venv/bin/python scripts/dev/seed-font.py .dev/A/fonts --family "Roboto" --style Bold
scripts/dev/run-agent.sh A sync
# → B reçoit le signal SSE et installe automatiquement la nouvelle font
```

## 5. Frontend (optionnel)

```bash
cd frontend && npm install && npm run dev   # proxy vers localhost:8080
```

## Remettre à zéro

Tout l'état local de dev vit dans `.dev/` (gitignoré). Pour repartir propre :

```bash
rm -rf .dev
```
