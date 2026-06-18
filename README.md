# FontSync

Font manager **self-hosted** avec synchronisation multi-machines en temps réel :
un serveur Docker centralise la bibliothèque de polices, un agent Python détecte et
synchronise automatiquement les fonts entre machines, une interface web permet de
naviguer et gérer la collection.

> ℹ️ README minimal (mention de licence — P0.1). Le guide d'installation et le
> quickstart « 2 machines » arrivent en **P4.2** (cf. `PLAN-PUBLICATION.md`).
> Voir `SPECS.md` pour la vision produit et l'architecture.

## Licence

FontSync est distribué sous **GNU Affero General Public License v3.0 ou ultérieure**
(AGPL-3.0-or-later) — voir [`LICENSE`](LICENSE).

L'AGPL garantit que la version **self-hosted reste libre et gratuite** : quiconque
exécute une version modifiée comme service réseau doit en publier les sources
(copyleft réseau, §13). C'est le modèle des projets « self-host gratuit + cloud
payant » comme Plausible et Cal.com.

Le détenteur du copyright (Leo Durand) conserve l'intégralité des droits et se
réserve la possibilité de proposer des **licences commerciales** et d'opérer un
service cloud — l'AGPL ne lie pas l'auteur. Pour préserver cette faculté, les
contributions externes sont acceptées sous **DCO** (`Signed-off-by`), garantissant
que l'auteur peut continuer à relicencier le projet.

```
Copyright (C) 2026 Leo Durand
This program is free software: you can redistribute it and/or modify it under the
terms of the GNU Affero General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later version.
```
