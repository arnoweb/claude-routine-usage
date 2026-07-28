# Claude Routine Usage

Suivi quotidien automatisé de la consommation Claude (API pay-as-you-go **et**
abonnement Pro/Max), écrit dans un unique fichier JSON consommable en HTTP par
une routine externe (ex. un "CTO Daily Brief").

Le JSON est mis à jour par deux exécutions indépendantes qui fusionnent leurs
résultats dans le même fichier :

| Source | Où ça tourne | Fréquence | Champs écrits |
|---|---|---|---|
| **Admin API** Anthropic (usage/coût facturé) | ☁️ GitHub Actions — indépendant de l'état du Mac | 6h00 UTC, tous les jours | `total_input_tokens`, `total_output_tokens`, `total_cost_usd` |
| **CLI Claude Code** (`claude -p "/usage"` + transcripts locaux) | 💻 Ce Mac uniquement (launchd) | 7h heure locale, tous les jours | `session_usage`, `model_usage_7d` |

## Pourquoi deux sources ?

- L'**Admin API** ne reporte que l'usage facturé à l'API (organisation avec
  clé API pay-as-you-go). Elle ne voit rien de l'abonnement Pro/Max.
- Les quotas de **session/semaine** et la **répartition par modèle** d'un
  abonnement Pro/Max n'existent nulle part côté API publique — ce sont des
  données locales à la machine, exposées uniquement par le CLI `claude` et
  par les transcripts qu'il écrit sur disque. Elles ne peuvent donc être
  produites que **localement**, jamais depuis un runner cloud.

Résultat : le fichier reste à jour pour la partie facturation même Mac
éteint, mais les champs de session/modèle ne se rafraîchissent que lorsque
ce Mac tourne à 7h.

## Fichier de sortie — `claude_usage_weekly.json`

```json
{
  "generated_at": "2026-07-28T08:28:59Z",
  "window_start": "2026-07-21T08:28:59Z",
  "window_end": "2026-07-28T08:28:59Z",
  "total_input_tokens": 0,
  "total_output_tokens": 0,
  "total_tokens": 0,
  "total_cost_usd": 0.0,
  "session_usage": {
    "session_used_pct": 14,
    "session_resets_at": "Jul 28 at 2:30pm (Europe/Paris)",
    "week_used_pct": 37,
    "week_resets_at": "Jul 31 at 9pm (Europe/Paris)",
    "captured_at": "2026-07-28T08:28:59Z"
  },
  "model_usage_7d": {
    "claude-sonnet-5": {
      "display_name": "Sonnet 5",
      "input_tokens": 1494921533,
      "output_tokens": 3248424,
      "pct_of_output": 58.4
    }
  }
}
```

`pct_of_output` = part du modèle dans le total des tokens de sortie sur la
fenêtre (`--days`, 7 par défaut) — c'est la métrique la plus proche de ce
qu'affiche l'écran `/usage` de Claude Code.

## Composants du repo

- **`claude_usage_weekly.py`** — le script. Toujours exécutable seul ; les
  parties liées au CLI local (`session_usage`, `model_usage_7d`) sont
  best-effort et s'effacent silencieusement si `claude` n'est pas présent
  (cas du runner GitHub Actions), sans écraser la dernière valeur connue
  dans le JSON.
- **`.github/workflows/usage-report.yml`** — workflow planifié (cron
  `0 6 * * *` = 6h UTC) + déclenchable manuellement (`workflow_dispatch`).
  Commit le JSON mis à jour dans le repo à chaque run.
- **`run_local.sh`** — wrapper appelé par launchd : `git pull --rebase`,
  exécution du script, puis commit + push si le fichier a changé.
- **`.env`** (non commité) — `ANTHROPIC_ADMIN_API_KEY`, utilisé par le run
  local. Le run cloud utilise le secret GitHub du même nom.

## Prérequis

- Une **clé Admin API** Anthropic (`sk-ant-admin-...`), créée sur
  console.anthropic.com → Settings → Admin API keys (rôle admin requis dans
  l'organisation).
- Pour `session_usage` / `model_usage_7d` : être connecté localement à
  Claude Code avec un abonnement Pro/Max (`claude login`).
- Python 3.8+ avec `requests` (`pip install -r requirements.txt`).

## Utilisation manuelle

```bash
export ANTHROPIC_ADMIN_API_KEY="sk-ant-admin-..."
python3 claude_usage_weekly.py            # écrit claude_usage_weekly.json
python3 claude_usage_weekly.py --days 14  # fenêtre personnalisée
```

## Mise en place de l'automatisation

Deux mécanismes à configurer séparément — un cloud (GitHub Actions), un local
(launchd) — car aucun des deux ne peut couvrir toutes les données à lui seul.

### 1. Partie cloud — GitHub Actions

Le workflow (`.github/workflows/usage-report.yml`) est déjà présent dans le
repo, il ne manque que le secret :

1. Sur la page du repo → **Settings → Secrets and variables → Actions**
2. **New repository secret** → nom `ANTHROPIC_ADMIN_API_KEY` → coller la clé
3. Le job tourne alors automatiquement tous les jours à 6h00 UTC (voir le
   `cron` dans le fichier de workflow). Pour tester sans attendre : onglet
   **Actions** → sélectionner le workflow → **Run workflow**.

Le job checkout le repo, installe `requirements.txt`, lance le script avec
la clé en variable d'environnement, puis commit+push le JSON s'il a changé
(`permissions: contents: write` dans le workflow autorise ce push).

### 2. Partie locale — launchd (macOS)

`session_usage` et `model_usage_7d` ne peuvent être produits que sur la
machine où tourne `claude login` — il faut donc un planificateur **local**
qui déclenche `run_local.sh` chaque jour. launchd est l'équivalent macOS de
cron, mais capable de rattraper l'exécution manquée au réveil de la machine.

**a) Créer le fichier plist**, par exemple
`~/Library/LaunchAgents/com.<toi>.claude-usage-local.plist` (remplace
`<toi>` par un identifiant à toi — c'est juste un label local, sans lien
avec le repo) :

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.<toi>.claude-usage-local</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/chemin/absolu/vers/ce/repo/run_local.sh</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>7</integer>
        <key>Minute</key><integer>0</integer>
    </dict>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>

    <key>StandardOutPath</key>
    <string>/chemin/absolu/vers/ce/repo/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/chemin/absolu/vers/ce/repo/launchd.error.log</string>

    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
```

> ⚠️ Le champ `PATH` doit lister les dossiers où se trouvent tes binaires
> `python3`, `git` et `claude` — launchd n'hérite **pas** du `PATH` de ton
> shell interactif. Vérifie avec `which python3 git claude` et ajoute les
> dossiers correspondants si besoin.

**b) Charger et tester le job :**

```bash
launchctl load ~/Library/LaunchAgents/com.<toi>.claude-usage-local.plist

# Vérifier qu'il est bien enregistré (statut 0 = OK)
launchctl list | grep claude-usage

# Déclencher un run immédiat sans attendre 7h
launchctl start com.<toi>.claude-usage-local

# Suivre les logs
cat launchd.log launchd.error.log
```

Le job reste chargé après redémarrage du Mac. S'il est éteint/endormi à 7h,
l'exécution du jour est simplement sautée — seul `session_usage` /
`model_usage_7d` sont impactés, la partie Admin API reste à jour via le
cloud.

**Pour désactiver le job local** :

```bash
launchctl unload ~/Library/LaunchAgents/com.<toi>.claude-usage-local.plist
```

## Limites connues

- `claude -p "/usage"` et le format des transcripts (`~/.claude/projects/*.jsonl`)
  ne sont pas des interfaces documentées/stables — un futur changement de
  Claude Code peut casser le parsing sans préavis.
- `session_usage` et `model_usage_7d` ne reflètent que l'activité **sur cette
  machine** — pas claude.ai, pas les autres appareils.
- Le cron GitHub Actions est en UTC fixe (pas de fuseau horaire/DST géré) :
  6h00 UTC = 7h Paris en hiver, 8h en été.
