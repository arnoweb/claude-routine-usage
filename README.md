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
  exécution du script avec l'interpréteur Python qui a `requests` installé,
  puis commit + push si le fichier a changé.
- **`~/Library/LaunchAgents/com.arnaudbreton.claude-usage-local.plist`**
  (hors repo, propre à la machine) — déclenche `run_local.sh` tous les jours
  à 7h heure locale.
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

## Limites connues

- `claude -p "/usage"` et le format des transcripts (`~/.claude/projects/*.jsonl`)
  ne sont pas des interfaces documentées/stables — un futur changement de
  Claude Code peut casser le parsing sans préavis.
- `session_usage` et `model_usage_7d` ne reflètent que l'activité **sur cette
  machine** — pas claude.ai, pas les autres appareils.
- Le cron GitHub Actions est en UTC fixe (pas de fuseau horaire/DST géré) :
  6h00 UTC = 7h Paris en hiver, 8h en été.
