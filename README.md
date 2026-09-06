# NFL Survivor

Each NFL week this repo recommends **one straight-up winner**. You can use each franchise at most once. The pool is double-elimination (`lives_remaining` starts at 2). Rankings maximize **season survival** (`survive_p`), not this week’s moneyline favorite.

Used teams and lives live in `config/state.yaml`. Scheduled refresh **never** locks a pick for you.

## Phone path (lock a pick in three taps)

After Slack posts the week:

1. Tap **Record pick** (opens the `record-pick.yml` Actions page — not the refresh run).
2. Tap **Run workflow**.
3. Leave **Team** empty to lock the live dashboard primary (copy line is `week N · suggested TEAM`). Hit **Run workflow**.

Empty Team + a week already locked does not overwrite the pick (loss-only / no-op). Check **loss** if the pick lost. Check **replace** only to change a locked team.

Optional: tap **Refresh rankings** in Slack so the dashboard shows `locked`.

You need GitHub write access. Slack itself cannot change state.

## First-time setup (human)

1. Repo Actions secrets: `ODDS_API_KEY`, `SLACK_WEBHOOK_URL`, `NETLIFY_AUTH_TOKEN`, `NETLIFY_SITE_ID` (new Netlify site for this app — do not reuse a CFB site id).
2. Local `.env` from `.env.example` (Odds + Slack). Never commit `.env`.
3. Create a **new** Netlify site with publish directory `web`. Put the public URL in `config/survivor.yaml` → `slate.dashboard_url`. Set `ops.github_repo` to `owner/nfl-survivor`.
4. **Actions → Survivor refresh → Run workflow** once. Confirm Slack (including **Record pick**) and the phone dashboard.

## Weekly live run

GitHub Actions `survivor-refresh.yml` cron (UTC): after MNF, Wed/Thu/Sat/Sun windows. Or **Run workflow**.

Laptop:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m src.survivor.run --web
# or
bash scripts/publish_survivor.sh
```

Fixture (no API keys):

```bash
python -m src.survivor.run --fixture tests/fixtures/survivor_week.json --web --no-slack
```

## Laptop commit / loss

```bash
python -m src.survivor.run --commit "Buffalo Bills" --week 1
python -m src.survivor.run --loss --week 1
```

Then `git add config/state.yaml` and commit on the default branch (or use Record pick from the phone). `--commit` does not change lives.

## Secrets

| Secret | Use |
| --- | --- |
| `ODDS_API_KEY` | The Odds API (Pinnacle only) |
| `SLACK_WEBHOOK_URL` | Incoming Webhook outbound |
| `NETLIFY_AUTH_TOKEN` | Deploy `web/` |
| `NETLIFY_SITE_ID` | **This** site |

## Tests

```bash
pytest
```
