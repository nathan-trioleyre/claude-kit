# org/ — couche entreprise optionnelle

Tout ce qui est ici s'applique à **chaque** projet configuré avec le kit, entre `base/` et les profils de stack.
La couche est additive : elle peut ajouter des règles, des permissions et des fichiers, jamais retirer ce que `base/` ou le projet ont déjà.
Supprime les fichiers dont tu n'as pas besoin ; un `org/` vide ne fait rien.

| Fichier / dossier | Effet dans le projet |
|---|---|
| `rules.md` | Ajouté à la section « Mandatory Rules » de `CLAUDE.md` (lignes à puces markdown simples). |
| `settings.json` | `permissions.allow` / `permissions.deny` et `hooks` supplémentaires, fusionnés dans `.claude/settings.json`. Même structure que `base/settings.base.json`. |
| `mcp.json` | `{"mcpServers": {...}}`, fusionné dans le `.mcp.json` du projet. Les noms de serveurs existants ne sont jamais écrasés. N'y mets jamais de secrets : utilise des références `${ENV_VAR}`. |
| `agents/*.md` | Copiés dans `.claude/agents/` (sous-agents), sans écraser. |
| `commands/*.md` | Copiées dans `.claude/commands/` (commandes slash), sans écraser. |
| `rules/*.md` | Copiées dans `.claude/rules/` (règles modulaires scopées par `paths`), sans écraser. |
| `skills/<nom>/SKILL.md` | Copiés dans `.claude/skills/<nom>/` (workflows réutilisables à la demande), sans écraser. |

`base/agents/`, `base/commands/`, `base/rules/` et `base/skills/` fonctionnent de la même façon pour ce qui appartient à tous les projets, quelle que soit l'entreprise.

Applique-les aux projets avec `/claude-kit` (première fois) ou `/claude-kit sync` (ensuite). Ignore la couche avec `--no-org`.
