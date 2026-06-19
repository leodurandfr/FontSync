# Canal Homebrew (CLI) — `fontsync-agent`

Canal de distribution **optionnel** (PLAN-PUBLICATION.md P5.1), destiné aux power-users
et aux serveurs/postes headless qui veulent l'agent **sans l'app Mac**. Le canal grand
public reste l'app menu bar signée (Phase P3), qui embarque déjà l'agent.

La formule installe `fontsync-agent` dans un virtualenv isolé via
`virtualenv_install_with_resources` : toutes les dépendances Python (httpx, pyyaml,
pyobjc…) sont déclarées en `resource` et pip-installées. pyobjc est ainsi construit par
son **chemin d'install supporté** (pip), cohérent avec la décision P0.3 (« pas de freezer »).

## Installation (utilisateur final)

```bash
brew install leodurandfr/tap/fontsync-agent
fontsync-agent setup          # enregistre les LaunchAgents (sync + listen)
```

Configurer ensuite `~/.fontsync/config.yaml` (`server.url` + `server.token`).
Désinstaller les LaunchAgents : `fontsync-agent teardown`.

## Fichier canonique vs tap

- **Source canonique** : [`Formula/fontsync-agent.rb`](Formula/fontsync-agent.rb) (dans ce dépôt, versionnée avec le code).
- **Tap publié** : dépôt séparé `leodurandfr/homebrew-tap`, où Homebrew lit la formule.
  `brew install <user>/tap/<formula>` résout `<user>/homebrew-tap` → `Formula/<formula>.rb`.

Mirroring vers le tap (à la main ou en CI) :

```bash
# Une fois : créer le dépôt GitHub `homebrew-tap` puis
git clone git@github.com:leodurandfr/homebrew-tap.git
cp packaging/homebrew/Formula/fontsync-agent.rb homebrew-tap/Formula/
cd homebrew-tap && git add Formula/fontsync-agent.rb && git commit -m "fontsync-agent X.Y.Z" && git push
```

## Procédure de release (mettre à jour la formule)

À chaque tag `vX.Y.Z` (cf. `docs/RELEASE.md`) :

1. **Tarball source** — mettre à jour `url` (tag) + `version`, puis régénérer le `sha256` :
   ```bash
   curl -sL https://github.com/leodurandfr/FontSync/archive/refs/tags/vX.Y.Z.tar.gz | shasum -a 256
   ```
   (Le placeholder `0000…` dans la formule **doit** être remplacé : le tag n'existe pas encore.)

2. **Dépendances Python** — régénérer les blocs `resource` si les versions ont bougé :
   ```bash
   brew update-python-resources packaging/homebrew/Formula/fontsync-agent.rb
   ```
   Les versions épinglées actuelles ont été résolues pour Python 3.12 / macOS via
   `uv pip compile` (httpx, pyyaml, pyobjc-framework-CoreText + transitifs).

3. **Valider la formule** :
   ```bash
   brew style packaging/homebrew/Formula/fontsync-agent.rb
   brew audit --new --formula packaging/homebrew/Formula/fontsync-agent.rb
   brew install --build-from-source packaging/homebrew/Formula/fontsync-agent.rb
   brew test fontsync-agent
   ```

4. **Mirorer** la formule vers le tap (cf. ci-dessus).

> Note : la formule construit l'agent depuis le tarball **source complet** du dépôt
> (`pyproject.toml` à la racine ne package que `agent*`, cf. `[tool.setuptools.packages.find]`),
> donc l'installation ne tire que l'agent, pas le backend.
