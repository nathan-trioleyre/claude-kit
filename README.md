# claude-kit

Un kit personnel qui prépare Claude Code pour n'importe quel projet (Python, C#, Angular, et toute future stack) avec une seule commande : `/claude-kit`.

## L'idée en 30 secondes

Quand tu arrives sur un projet, `/claude-kit` :

1. **inspecte** le projet pour comprendre sa stack ;
2. **vérifie** dans `profiles/` si cette stack est déjà connue ;
   - oui → il réutilise le profil sans refaire de recherche ;
   - non → il consulte la documentation officielle, valide et te montre le profil proposé, puis **l'enregistre dans ce dépôt après ton accord** ;
3. **génère** dans le projet un `CLAUDE.md` (plus des `.claude/rules/<stack>.md` optionnels limités à certains chemins), des permissions et des hooks (sécurité + formatage), sans jamais écraser ce qui existe déjà.

Ensuite, le kit garde les projets alignés sur lui :

| Commande | Ce qu'elle fait |
|---|---|
| `/claude-kit` | première configuration (ou nouvelle passe complète) d'un projet |
| `/claude-kit local` | configuration **personnelle et invisible** pour un repo d'équipe (`CLAUDE.local.md`, `.claude/settings.local.json`, `.git/info/exclude` — ne touche jamais au `.gitignore`, au `CLAUDE.md` ni au `settings.json` de l'équipe) |
| `/claude-kit doctor` | signale les écarts : hooks périmés, permissions manquantes, profils obsolètes, nouvelles stacks, trous dans `CLAUDE.md`, conflits d'outillage non résolus |
| `/claude-kit sync` | rafraîchit uniquement les fichiers gérés par le kit (settings, hooks, agents/commandes, `.mcp.json`) ; ne touche jamais à `CLAUDE.md` |
| `/claude-kit-refresh [stack\|all]` | relit les sources officielles d'un profil et propose des mises à jour |
| `/claude-kit-learn` | fait remonter les leçons durables du `CLAUDE.md` d'un projet vers le kit (profil, `org/` ou `base/`) |

## Projets qui ont déjà leur propre configuration

Sur un projet qui a son propre `CLAUDE.md`, ses hooks, son formateur, son linter ou son gestionnaire de paquets, `/claude-kit` n'écrase jamais rien en silence :

1. `apply.py audit` fait l'inventaire de l'existant et liste les **conflits** entre les outils du projet et ceux du profil (par exemple `black` dans `pyproject.toml` face au `ruff` du kit, `pnpm-lock.yaml` face à `npm`, un hook de formatage fait main).
2. Pour chaque conflit, tu choisis, un par un : **garder l'outil existant** (le kit retient ses commandes, permissions, règle de formatage et lignes de conventions qui font doublon, et utilise les équivalents de l'outil existant), **adopter celui du kit** (Claude propose un plan de migration : ancienne config et hooks à supprimer, reformatage unique ; rien n'est touché avant ton accord) ou **garder les deux**.
3. La réponse est enregistrée dans `.claude/kit.json` (`decisions`), donc `sync` et `doctor` la respectent. `doctor` signale les conflits non tranchés et les migrations à moitié faites ; `apply.py decide` change une décision plus tard.
4. Tant que tu n'as pas décidé, le kit se comporte comme si tu avais choisi de garder l'outil existant.
5. Un `CLAUDE.md` existant est comparé section par section (seulement dans le kit / seulement chez toi / différent) avant toute fusion.

La détection des conflits vient de la section optionnelle `tooling` de chaque profil (voir [profiles/README.md](profiles/README.md)).

## Les couches (modèle en 5 layers)

`base/` (tous les projets) → `org/` (optionnel, ton entreprise) → `profiles/<stack>/` (par stack) → le projet lui-même.
Chaque couche ne fait qu'**ajouter** à la précédente. Voir [org/README.md](org/README.md) pour la couche entreprise (règles partagées, permissions, serveurs MCP, agents, commandes, règles modulaires, skills).

Dans chaque projet configuré, le kit s'aligne sur les **5 couches Claude Code** :
1. **`CLAUDE.md`** : identité, commandes, architecture et pièges (< 200 lignes, imports `@fichier` possibles).
2. **`.claude/rules/*.md`** : règles modulaires scopées par `paths` (monorepos, `base/rules/`, `org/rules/`).
3. **`.claude/skills/`** (et `commands/`) : workflows réutilisables à la demande (`/verify` et `/wrap-up` fournis dans `base/skills/`).
4. **`.claude/agents/`** : sous-agents isolés (ex: `code-reviewer` en lecture seule pour relire le diff sans biais).
5. **Hooks (`.claude/settings.json`)** : garde-fous déterministes (`SessionStart` avec `session-check.py`, `PreToolUse` avec `guard.py`, `PostToolUse` avec `format.py`, et `Stop` opt-in avec `verify-stop.py` via `"stop_verify": true` dans `.claude/kit.json`).

## Qui fait quoi

| Le script (`apply.py`) | Claude (via les skills) |
|---|---|
| Détecte les stacks connues (jusqu'à la profondeur 5, en ignorant `node_modules`, `.venv`, etc.) | Comprend le projet |
| Copie les hooks ; ne les met à jour que si la copie du projet n'a pas été modifiée (hashes dans `.claude/kit.json`) | Crée et rafraîchit les profils à partir de la doc officielle |
| Fusionne `settings.json` sans retirer les règles personnalisées | Écrit l'architecture du projet, les pièges et les `rule_paths` des monorepos |
| Génère `CLAUDE.md` et `.claude/rules/*.md` (sans écraser) | Montre les diffs et demande confirmation |
| `audit` / `decide` / `doctor` / `sync` / `validate` | Explique les problèmes, te fait trancher chaque conflit, propose et exécute la migration approuvée |

Règle de base : **ce qui doit être identique à chaque fois est du code ; ce qui demande de la compréhension est délégué à Claude.**

## Installation (une fois par machine)

```bash
git clone https://github.com/nathan-trioleyre/claude-kit.git
cd claude-kit
python install.py --link     # les skills sont liés : les modifications de ce dépôt sont prises en compte en direct
```

`--link` utilise un lien symbolique (une jonction sous Windows). Sans lui, les skills sont copiés et il faut relancer `python install.py` après avoir modifié un `SKILL.md`.
Ensuite, dans n'importe quel projet : ouvre Claude Code et tape `/claude-kit`.

## Contenu du dépôt

```
claude-kit/
├── VERSION                     version du kit (enregistrée dans le kit.json de chaque projet)
├── install.py                  installe les skills (copie ou --link) + enregistre les chemins du kit et de Python
├── base/                       commun à TOUS les projets
│   ├── CLAUDE.md.template      squelette du CLAUDE.md
│   ├── settings.base.json      permissions renforcées + branchement des hooks
│   ├── hooks/                  run-hook.sh, guard.py, format.py, session-check.py, verify-stop.py
│   ├── agents/                 code-reviewer.md (copié dans chaque projet)
│   ├── skills/                 verify/SKILL.md, wrap-up/SKILL.md (copiés dans chaque projet)
│   └── commands/  rules/       optionnel : copiés dans chaque projet
├── org/                        couche entreprise optionnelle (règles, permissions, MCP, agents, commandes, skills)
├── profiles/                   un dossier par stack
│   ├── python/ csharp-dotnet/ angular/ typescript/ nextjs/ docker/ rust/   profils intégrés
│   └── _TEMPLATE/              modèle pour écrire un profil à la main
├── skills/
│   ├── claude-kit/             /claude-kit (+ scripts/apply.py)
│   ├── claude-kit-refresh/     /claude-kit-refresh
│   └── claude-kit-learn/       /claude-kit-learn
└── tests/                      suite unittest sans dépendance
```

### Fraîcheur des profils

Tout profil dont `last_verified` dépasse 90 jours est signalé comme obsolète (`stale`) par `doctor` et `apply`. Lance `/claude-kit-refresh [stack|all]` pour relire les sources officielles, vérifier les changements et mettre à jour la date de vérification après ton accord.

## Ce que le script ne fait jamais

- écraser un `CLAUDE.md` ou un `.claude/rules/<stack>.md` existant (il écrit un `.proposed` à côté, et affiche des diffs unifiés avec `--dry-run`). Si tu as personnalisé un fichier et que la sortie du kit n'a pas changé depuis la dernière exécution, il reste silencieux au lieu de reproposer ;
- retirer une permission ou un hook personnalisé (fusion additive ; il ne met à jour que les commandes et matchers de hooks gérés par le kit) ;
- écraser un hook que tu as modifié localement (seul `sync --force-hooks` le fait, explicitement) ;
- écrire quoi que ce soit quand `--dry-run` est passé.

## Modèle de sécurité

- Les règles `deny` de `settings.json` bloquent la lecture des secrets, `sudo`, `rm -rf`, les force push et `reset --hard`.
- `guard.py` (hook PreToolUse) ajoute : les shells imbriqués (`bash -c "…"`, `pwsh -Command "…"`), la lecture, la copie ou la redirection vers des fichiers secrets via Bash, `find -delete`, `git branch -D`, la suppression de branche distante, l'abandon des modifications de l'arbre de travail, `curl | sh`, les instructions DROP et les suppressions dangereuses sous Windows.
- `apply.py validate` rejette les permissions de profil qui autorisent l'exécution de code arbitraire (`python *`, `bash *`, `npx *`, `find *`, `curl *`…) ou qui commencent par un joker.
- `guard.py` reste un **filet de sécurité contre les accidents**, pas une frontière de sécurité : l'isolation stricte relève des règles `deny` et d'un environnement isolé.

## Pourquoi pas un plugin Claude Code ?

Les profils sont *réécrits* dans ce dépôt (et rafraîchis là). Un plugin s'installe dans un cache remplacé à chaque mise à jour : il ne peut donc pas être la source de vérité de données que tu modifies. Le kit garde le dépôt comme source de vérité et supprime les inconvénients de la copie grâce à `--link`, aux hashes des hooks, à `sync` et à `doctor`. Si tu veux plus tard distribuer à des collègues seulement la partie en lecture seule (hooks et skills), l'emballer en plugin reste possible.

## Faire évoluer le kit

- Une règle utile dans tous tes projets → `base/` ; dans toute ton entreprise → `org/` ; propre à une stack → son profil.
- Valider les profils → `python skills/claude-kit/scripts/apply.py validate`.
- Lancer les tests → `python -m unittest discover -s tests -v`.
- Incrémente `VERSION` quand tu modifies `base/`, pour que `doctor` signale les projets à resynchroniser ; incrémente le marqueur `claude-kit-hook-version` d'un hook quand tu le modifies.
- Commite les changements dans `profiles/` et `org/` : ils sont la mémoire de tes stacks et de ton entreprise.

## À vérifier au premier lancement

1. **Les skills apparaissent** : dans Claude Code, tape `/` et cherche `claude-kit`. Sinon, vérifie `~/.claude/skills/`.
2. **Les hooks fonctionnent sur toutes les plateformes** : les hooks appellent `.claude/hooks/run-hook.sh`, qui cherche dans le `PATH` un `python3`/`python` fonctionnel (en ignorant les faux exécutables du Windows Store), se rabat sur l'interpréteur enregistré dans `~/.claude/claude-kit.json`, puis essaie `py -3`. Tape `/hooks` pour vérifier l'enregistrement, puis demande à Claude de lancer `git push --force` : il doit être bloqué.
3. **Les hooks sont chargés au démarrage** : après avoir lancé `/claude-kit`, redémarre la session.
