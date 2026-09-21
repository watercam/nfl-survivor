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

## Sleeper alt lines

Sleeper ALT (PrizePicks-style) posts a **threshold** (`40+ rushing yards`) and a **multiplier** (`1.34x`). The juice is in both, so the card is not a 50/50. Price it against a sportsbook main O/U (or the book’s American price at the same alt).

Phone: dashboard → **Alt lines** (`web/alt.html`). Laptop:

```bash
# screenshot-style goblin: 40+ MORE at 1.34x vs a 52.5 rush O/U
python -m src.sleeper.run \
  --player "Cam Skattebo" --stat rush_yds --alt 40 --side more --mult 1.34 --main 52.5

# two-leg slip
python -m src.sleeper.run \
  --pick 'rush_yds,40,more,1.34,52.5' \
  --pick 'pass_yds,200,more,1.26,245.5'

# skip the curve: book already has this alt
python -m src.sleeper.run --stat rush_yds --alt 40 --side more --mult 1.34 --book-odds -250 --book-opp 170
```

`edge = p_fair × multiplier − 1`. Positive means Sleeper pays more than the book implies. Yards use a normal residual SD; receptions/TDs use Poisson. `--list-stats` prints defaults. Same-game correlation is not priced.

This is **not** the survivor pick. Pinnacle h2h + DP are unchanged.

## Tests

```bash
pytest
```
