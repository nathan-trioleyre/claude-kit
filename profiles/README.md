# Profils de stack

Un dossier par stack (`python/`, `csharp/`, `angular/`...), créé par `/claude-kit`
la première fois qu'il rencontre la stack, puis réutilisé sur les projets suivants.

Chaque profil contient :
- `profile.json` : données lisibles par le script (détection, commandes, permissions,
  règles de formatage, `paths` optionnel pour `.claude/rules/<stack>.md`, détection
  de conflits `tooling` optionnelle, sources, date de dernière vérification).
- `practices.md` : résumé des bonnes pratiques (copié dans `CLAUDE.md` ou dans
  `.claude/rules/<stack>.md` quand des chemins sont définis).

Règles :
- Un profil n'est enregistré qu'après validation (`apply.py validate`) et ton accord.
- Chaque profil cite ses sources (documentation officielle de préférence).
- Un profil de plus de 90 jours est considéré comme obsolète : `/claude-kit-refresh <stack>`.
- Copie `_TEMPLATE/` pour en écrire un à la main.

## `tooling` (optionnel) : cohabiter avec ce qu'un projet a déjà

Déclare, par sujet (`formatter`, `linter`, `package-manager`...), l'outil que préfère le kit
(`kit`) et des `alternatives` connues. Quand un projet utilise déjà une alternative, `apply.py`
retient les règles du kit qui font doublon jusqu'à ce que l'utilisateur décide
(`keep_existing`, `adopt_kit`, `keep_both`).

- `kit` : `name`, `markers` (ce qui révèle l'outil du kit), `commands` (clés de commandes dont il
  est responsable), `format_rules` (vrai s'il porte la règle de formatage), `permissions` (règles
  dont il est responsable), `practice_terms` (les lignes de pratiques qui les mentionnent sont
  retirées quand l'outil existant est conservé).
- `alternatives[]` : `name`, `markers` (`{"file": glob, "contains": texte}`), `hooks` (mots qui
  révèlent un hook fait main), et des remplacements optionnels utilisés quand l'outil est
  conservé : `commands`, `permissions_allow`, `format_rule`. N'ajoute que des remplacements dont
  tu es sûr.
