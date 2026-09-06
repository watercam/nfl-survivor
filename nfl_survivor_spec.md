# NFL Survivor Pool — Analysis → Recommendation → Notification Spec

Give this file to an agent in a **new empty repo**. It is the product spec, architecture, and implementation goal. Do not depend on the CFB Pick’em git tree. Copy **patterns** (Pinnacle-only, Incoming Webhook Slack, GHA cron, Netlify snapshot dashboard, fixture tests without keys). Do not import CFB code.

**Sibling product (reference only):** ESPN CFB Pick’em confidence ranking. Same operator, same secrets names. Different sport, different game, different optimizer.

---

## 0. Goal prompt (paste this as the implementation Goal)

> Implement a greenfield Python NFL survivor engine from `nfl_survivor_spec.md`. Product: each NFL week recommend **one straight-up winner**; **each team may be used at most once**; pool is **double elimination** (out after two losses). Loop: ESPN NFL scoreboard slate + full remaining regular-season schedule → The Odds API **Pinnacle only** (`americanfootball_nfl`, h2h + spreads) → no-vig `p_win` (calibration `none` in production) → lookahead survival optimizer with lives + used-teams state → write `web/recommendations.json` → Slack Incoming Webhook → GitHub Actions cron + Netlify. Secrets: `ODDS_API_KEY`, `SLACK_WEBHOOK_URL`, `NETLIFY_AUTH_TOKEN`, `NETLIFY_SITE_ID` (same values as the CFB Pick’em repo; never commit them). Do not auto-commit a pick into `used_teams` — only `state.yaml` / `--commit` / `record-pick.yml`. Every Slack success post includes a **Record pick** link to that workflow’s Actions page (not the refresh run). Empty `team` input locks the live dashboard primary. Fixture mode must run with no API keys. Out of scope: auto-submit to a pool website, Slack app / slash-command write-back, other books, parlays, spreads as the pick, research backtest V1, Playwright.

---

## 1. Pool rules (invariants)

| Rule | Meaning |
| --- | --- |
| One pick per NFL week | Select the **winner** of **one** game (straight-up moneyline / against the field). Not ATS. Not a confidence slate. |
| Unique teams | A franchise may appear in `used_teams` at most once for the season. You cannot pick Kansas City in week 3 and week 12. |
| Double elimination | Start with `lives_remaining: 2`. A losing pick decrements lives by 1. `lives_remaining == 0` → eliminated; engine still runs but marks `status: eliminated` and does not recommend. A winning pick does not restore a life. |
| Byes | A team on bye that week is not a legal pick. |
| Kickoff lock | Once a game has started (`now >= kickoff`), that game’s teams are not legal picks for the current week. Other games that week remain legal until they start. |
| Ties | NFL regular-season ties count as a **loss** for survivor (treat `p_win` as P(team wins in regulation+OT); ties are in the complement). Do not special-case pick’em ties as pushes unless `state.pool.tie_rule` is later set; default `tie_rule: loss`. |
| Season | NFL regular season only (`seasontype=2`). No wild-card / playoffs unless config enables it later. Default `last_week: 18`. |

The operator’s actual pick may differ from the recommendation. **Used-team and lives state is source-of-truth in `config/state.yaml`**, edited by the operator via laptop CLI (`--commit` / `--loss`), hand-edit + git, or phone-friendly **`record-pick.yml` `workflow_dispatch`**. The scheduled **refresh** job must **never** append the recommended team to `used_teams` by itself. Slack is outbound-only (Incoming Webhook); it does not parse replies. Write-back is GitHub auth on Actions, not a Slack bot.

---

## 2. What “closed loop” means (mirror CFB ops)

```text
GHA cron / laptop
  → GET live recommendations.json (preserve notes; diff for alerts)
  → ESPN scoreboard (current week + remaining weeks)
  → Pinnacle current + T-72 (this week) + current lines for future weeks that have them
  → score every legal side; optimize this week given lives + used teams + lookahead
  → write web/recommendations.json
  → Slack webhook (summary + change/urgency alerts + Record pick Actions link)
  → netlify deploy --prod
```

On workflow failure: short Slack error with the Actions run URL.

**Do not** use Playwright. Slack is POST JSON to an Incoming Webhook. ESPN is an unauthenticated public scoreboard JSON API.

---

## 3. Modeling

### 3A. Base win probability (this week, market)

Same math as CFB Pick’em:

1. American odds → implied probability.
2. No-vig: `p = implied_team / (implied_team + implied_opp)`.
3. Current snapshot: latest Pinnacle row with `snapshot_ts <= min(now, kickoff)`.
4. Reference snapshot: latest Pinnacle row with `snapshot_ts <= kickoff - 72h` and `<= current`. Missing T-72 → `spread_move = 0`, flag `REFERENCE_MISSING`, still use `p_current`.
5. `spread_move = spread_reference - spread_current` from the **team’s** spread (negative favorite). Positive move is favorable to that team.
6. `adj = movement_adjustment(p_current, spread_move)` from a calibration adapter (`none` | `handwritten` | `matrix_csv`). Production default **`none`**.
7. `p_final = clamp(p_current + adj, 0.01, 0.99)`.

**Pinnacle only.** `allow_book_fallback: false`. Never Circa/consensus.

The Odds API:

- Host: `https://api.the-odds-api.com`
- Live: `GET /v4/sports/americanfootball_nfl/odds`
- Historical: `GET /v4/historical/sports/americanfootball_nfl/odds` with `date` floored to a 5-minute grid
- Query: `regions=eu`, `markets=h2h,spreads`, `bookmakers=pinnacle`, `oddsFormat=american`
- Strip `apiKey` from any logged URL (query-string leak).

### 3B. Future weeks without a Pinnacle line

Lookahead needs a `p_win` for remaining unused teams on future slates.

| Situation | `p_win` | Flag |
| --- | --- | --- |
| Pinnacle h2h present | no-vig current (no T-72 required) | — |
| Game scheduled, no market yet | home `home_prior` (default **0.58**), away `1 - home_prior` | `PRIOR_NO_MARKET` |
| Team on bye | not a candidate that week | — |
| Unmapped / missing opponent | skip that side | `UNMAPPED_TEAM` / `SCHEDULE_GAP` |

Do not invent spreads. Do not scrape ESPN FPI into `p_win` in V1.

### 3C. Legal candidates this week

A team T is legal iff all of:

- T is in this week’s ESPN slate (has an opponent, not on bye)
- T’s game has not started
- T ∉ `used_teams`
- `lives_remaining >= 1`
- T maps to a canonical franchise id

Score **both sides** of each game; only legal sides enter the optimizer.

### 3D. Optimizer (maximize season survival, not this-week p_win)

Naive “pick the biggest favorite this week” **burns** later must-have teams and is **wrong** for unique-team survivor.

**Objective:** maximize probability of still being alive after `last_week`, given current `lives_remaining`, independence across weeks, and a **greedy future policy**.

**This-week evaluation:** for each legal candidate T this week:

1. `p0 = p_final(T)` this week.
2. Build remaining used set `U' = used_teams ∪ {T}`.
3. For each future week `w = current_week+1 … last_week`, among teams not in `U'` who play that week, choose the team with highest `p_win` (tie-break: higher `p_current`, then home, then `game_id`). Append that `p` to the path; add the team to `U'` so it cannot be reused. If a future week has **no** legal team (all unused teams on bye / already used), append `p = 0` and flag `FUTURE_STARVE` for this candidate.
4. Let the path be `p0, p1, …, pK`. Compute survival probability with L lives:

```text
S(i, L) = 0                         if L <= 0
S(K+1, L) = 1                       if L >= 1
S(i, L) = p_i * S(i+1, L)
        + (1 - p_i) * S(i+1, L-1)   otherwise
```

`survive_p(T) = S(0, lives_remaining)`.

5. Recommend `argmax_T survive_p(T)`. Tie-break: higher this-week `p_final`, then higher `p_current`, then earlier kickoff (leave later games available if the pick is a toss-up), then `game_id`.

Also return:

- **Primary pick** (the argmax)
- **Top 5 alternatives** with `survive_p`, this-week `p_final`, kickoff, flags
- **Projected path** after taking the primary: week → team → `p_win` → `source: market|prior` (display only; not a lock)
- **Greedy this-week** team (`argmax p_final`) if it differs from primary, so Slack can say “saved X for later”

**Independence** is an approximation (weather, injuries correlate). V1 accepts it.

**Do not** mix public betting percentages into `p_win` or `survive_p`.

**Lives after a loss:** when `lives_remaining == 1`, the same DP automatically becomes more conservative (one loss is death). No separate heuristic required.

### 3E. Calibration adapter (same interface as CFB; production `none`)

```python
def movement_adjustment(current_probability: float, delta_spread: float) -> float: ...
```

- `none` → always 0
- `handwritten` → CFB buckets: `>2.5` → +0.03; `1.0…2.5` → +0.015; `-0.5…+0.5` → 0; `-2.5…-1.0` → -0.015; `<-2.5` → -0.03; gaps 0.5–1.0 → 0; cap `|adj|` at 0.03
- `matrix_csv` → optional future file; missing cell → 0

---

## 4. State (operator-owned)

`config/state.yaml` is committed **without secrets**. Example:

```yaml
season: 2026
lives_remaining: 2
used_teams: []          # canonical names, e.g. "Kansas City Chiefs"
committed: {}           # week number -> canonical team actually picked
notes: ""               # free text; preserved across refreshes if dashboard merge copies it
pool:
  name: "NFL Survivor"
  tie_rule: loss        # loss | win | push (push = treat as neither; do not decrement life)
  last_week: 18
```

CLI:

```bash
python -m src.survivor.run --commit "Buffalo Bills" --week 1
```

`--commit` appends to `used_teams` if absent, sets `committed[week]`, does **not** change lives (operator decrements lives after a loss, or add `--loss` to decrement and record).

```bash
python -m src.survivor.run --loss --week 1   # lives_remaining -= 1, min 0
```

Live ranking reads `state.yaml` from the repo (Actions checkout). After `--commit` / `--loss` / `record-pick.yml`, the yaml must be on the default branch (CLI: operator git commit; Actions: the workflow commits). Dashboard displays it; it is not source of truth.

**Phone path (no laptop):** Slack → **Record pick** URL → GitHub **Run workflow** (requires logged-in user with **write** on the repo). GitHub does **not** prefill `workflow_dispatch` inputs from query params; Slack therefore prints week + suggested team to copy. Empty **Team** input = lock the current dashboard primary (see §10). Clicking the Slack link does not mutate state.

If `committed[current_week]` is set, the recommendation payload still ranks alternatives but labels the committed team `locked: true`. Slack says “locked pick: …” and only alerts if the **model** primary diverges from locked (informational, not a panic to change an already-filed pick unless kickoff has not occurred).

---

## 5. Data sources

### 5A. ESPN NFL scoreboard (slate + schedule)

Unauthenticated GET. Record sanitized fixtures.

Current week:

`https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?seasontype=2&week={N}`

If `week` omitted, ESPN returns “this week”. Parser must still persist `week` from the payload.

Remaining season: fetch weeks `current…last_week` (18 small JSON files is fine; cache in-memory per run). Parse per game:

- ESPN event id
- away / home display names
- kickoff UTC
- status (scheduled / in / final)
- scores if final (optional; not required for V1 picks)
- bye teams if present

User-Agent: a descriptive bot string (e.g. `nfl-survivor/0.1`). No cookies.

If ESPN fails in CI: Slack + non-zero exit. **No silent fixture fallback** on the scheduled job. `--fixture` is tests/laptop only.

### 5B. Team identity

32 NFL franchises. Config `config/team_aliases.yaml`:

```yaml
- canonical: Kansas City Chiefs
  espn_team: Kansas City Chiefs
  odds_team: Kansas City Chiefs
  abbr: KC
```

Canonicalize with **exact** alias match only (no fuzzy). Unmapped → `UNMAPPED_TEAM`, skip that side.

### 5C. Odds join

Match ESPN home/away → canonical → Odds API `home_team` / `away_team` strings (Pinnacle uses Odds API names). One current NFL odds request covers the posted slate; unique T-72 timestamps only for **this week’s** games that have kickoffs.

Future weeks: use teams present in the **same current odds payload** if The Odds API already lists those events; otherwise prior.

---

## 6. Package layout

New repo, Python 3.12, `pip install -e ".[dev]"`.

```text
config/
  survivor.yaml          # horizons, odds, calibration, urls, cron-facing defaults
  state.yaml             # lives, used teams, committed picks
  team_aliases.yaml
src/survivor/
  __init__.py
  run.py                 # python -m src.survivor.run
  types.py
  slate.py               # ESPN scoreboard
  odds.py                # Pinnacle current + T-72
  probability.py         # American → no-vig; snapshot pick-at-or-before
  calibration.py
  schedule.py            # remaining weeks + byes
  optimize.py            # DP survival + greedy path
  alerts.py
  slack.py
  state.py               # load/save state.yaml
src/settings.py          # load yaml, ODDS_API_KEY
web/
  index.html             # phone dashboard
  recommendations.json
  _headers
tests/fixtures/
  survivor_week.json     # slate + snapshots + remaining schedule
tests/test_survivor_*.py
.github/workflows/survivor-refresh.yml
.github/workflows/record-pick.yml
.env.example
README.md
```

`config/survivor.yaml`:

```yaml
horizons:
  reference_hours: 72
odds_api:
  sport: americanfootball_nfl
  markets: [h2h, spreads]
  regions: [eu]
  preferred_bookmaker: pinnacle
  allow_book_fallback: false
  odds_format: american
  snapshot_grid_minutes: 5
calibration:
  source: none
  clamp_min: 0.01
  clamp_max: 0.99
  max_adjustment: 0.03
slate:
  espn_scoreboard_url: https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
  dashboard_url: ""        # set after Netlify site exists
  last_week: 18
  home_prior: 0.58
ops:
  github_repo: ""          # owner/name; set after the GitHub repo exists
  record_pick_workflow: record-pick.yml
```

`record_pick_url` = `https://github.com/{ops.github_repo}/actions/workflows/{ops.record_pick_workflow}` (omit the Record pick line if `github_repo` is empty). In Actions, if `github_repo` is empty, fall back to `GITHUB_REPOSITORY`.

---

## 7. CLI

```bash
python -m src.survivor.run --fixture tests/fixtures/survivor_week.json --web
python -m src.survivor.run --web
python -m src.survivor.run --web --no-slack
python -m src.survivor.run --commit "Buffalo Bills" --week 1
python -m src.survivor.run --loss --week 1
```

Stdout table (live or fixture):

```text
week: 1
lives: 2
used: 0
status: active
calibration: none

pick     opponent           kickoff              p_week   survive_p  source   flags
BUF      ARI                2026-09-13T17:00Z    0.78     0.41       market   -
...
```

Then alternatives + projected path (compact). `--json` dumps the dashboard payload to stdout.

`--web` writes `web/recommendations.json`.

Live mode requires `ODDS_API_KEY`. Fixture mode must succeed with **no** env keys and **no** ESPN/Odds network.

---

## 8. Dashboard payload

`web/recommendations.json` (illustrative):

```json
{
  "week": 1,
  "season": 2026,
  "lives_remaining": 2,
  "status": "active",
  "calibration": "none",
  "generated_at": "2026-09-06T16:00:00Z",
  "used_teams": [],
  "committed_this_week": null,
  "primary": {
    "team": "Buffalo Bills",
    "opponent": "Arizona Cardinals",
    "is_home": false,
    "kickoff": "2026-09-13T17:00:00Z",
    "p_current": 0.78,
    "spread_move": 0.5,
    "adj": 0.0,
    "p_final": 0.78,
    "survive_p": 0.41,
    "source": "market",
    "flags": [],
    "game_id": "espn-401..."
  },
  "greedy_this_week": {"team": "Kansas City Chiefs", "p_final": 0.84},
  "alternatives": [],
  "projected_path": [],
  "slate": [],
  "alerts": [],
  "notes": null,
  "record_pick_url": "https://github.com/owner/nfl-survivor/actions/workflows/record-pick.yml"
}
```

Phone `web/index.html`: lives, used chips, **this week’s pick** large, kickoff, `p_final` / `survive_p`, why-not-greedy if different, alternatives, projected path, generated_at, and a **Record pick** link when `record_pick_url` is in the payload. Preserve `notes` across refreshes by GETting live `recommendations.json` before overwrite (same merge pattern as CFB: copy `notes` when week matches).

Static site. No auth.

---

## 9. Alerts and Slack

Skip Slack entirely if `SLACK_WEBHOOK_URL` is unset (tests stay key-free).

**Success message prefix:** `NFL Survivor week {N} · lives {L} · used {k}` so it is distinguishable in the **same Slack channel** as CFB Pick’em.

Always include: `generated_at`, dashboard URL, primary pick + opponent + kickoff + `p_final` + `survive_p`, one-line reason if primary ≠ greedy favorite, compact top-3 alternatives.

**Record pick footer** (every success post, including heartbeat):

- Link labeled **Record pick** → `record_pick_url` (the `record-pick.yml` workflow page that has **Run workflow**, **not** `survivor-refresh.yml` and **not** `GITHUB_RUN_ID` of this refresh).
- Plain text to copy: `week {N} · suggested {primary.team}` plus `empty Team = lock suggested`.
- Optional second link **Refresh rankings** → `https://github.com/{ops.github_repo}/actions/workflows/survivor-refresh.yml` so a lock can show up as `locked` without waiting for cron.

If already locked this week, still include the Record pick link (for `replace` / `loss`). GitHub cannot prefill inputs via URL.

Plus:

| Kind | When |
| --- | --- |
| `new_week_slate` | previous payload missing or `week` changed |
| `pick_change` | primary team changed vs previous same week |
| `survive_drop` | `survive_p` fell by ≥ 0.03 vs previous same week |
| `kickoff_soon` | primary (or locked) kickoff within 6 hours and game not started |
| `thursday_risk` | primary plays Thursday and `now` is after Wednesday 12:00 America/New_York |
| `locked_diverges` | committed pick ≠ model primary |
| `eliminated` | `lives_remaining == 0` |
| `future_starve` | primary path hits a week with no legal team |

**Do not** spam: if nothing changed except `generated_at`, still post on cron (operator wants a heartbeat) **unless** config `slack.heartbeat: changes_only` is true. Default: **always post on success** (same as CFB).

Failure: `python -m src.survivor.slack --failure "NFL Survivor refresh failed: {RUN_URL}"`.

---

## 10. GitHub Actions + Netlify

`.github/workflows/survivor-refresh.yml`:

- `workflow_dispatch` + cron (UTC covering America/New_York):
  - Tue 23:00 (after MNF, new slate)
  - Wed 16:00
  - Thu 11:00 and 16:00 (TNF)
  - Sat 16:00
  - Sun 12:00 and 16:00
- **No** `pull_request` / `pull_request_target`
- `concurrency` group `survivor-refresh`, `cancel-in-progress: false`
- Steps: checkout → Python 3.12 → `pip install -e .` → require `ODDS_API_KEY`, `NETLIFY_AUTH_TOKEN`, `NETLIFY_SITE_ID` → `python -m src.survivor.run --web` with `ODDS_API_KEY` + `SLACK_WEBHOOK_URL` → `npx --yes netlify-cli deploy --dir=web --prod` → `if: failure()` Slack
- Live run GETs `{dashboard_url}/recommendations.json` for previous snapshot (alerts + notes). Do not commit snapshot JSON every run.
- Do not upload `data/raw/` or `.env` as artifacts.

**New Netlify site** (do not reuse the CFB site id). After `netlify init`, put the public URL in `slate.dashboard_url`.

Laptop: `scripts/publish_survivor.sh --live` analogous to CFB (`run --web` then netlify prod).

### `record-pick.yml` (operator write-back; phone)

Separate workflow. **Do not** fold this into `survivor-refresh.yml`.

- Triggers: `workflow_dispatch` **only**. No cron. **No** `pull_request` / `pull_request_target`.
- `concurrency` group `record-pick`, `cancel-in-progress: false`
- `permissions: contents: write` (commit `config/state.yaml` with `GITHUB_TOKEN`). No Odds / Netlify secrets required.
- Inputs:

| Input | Type | Default | Meaning |
| --- | --- | --- | --- |
| `team` | string | `""` | Canonical name, alias, or abbr. **Empty** = lock live dashboard `primary.team`. |
| `week` | string | `""` | NFL week. **Empty** = `week` from live `recommendations.json`. |
| `loss` | boolean | `false` | After resolving the pick (or if already committed that week), `lives_remaining -= 1` (min 0). |
| `replace` | boolean | `false` | If `committed[week]` is already a **different** team, fail unless true. Same team is a no-op success. |

- Steps:
  1. Checkout default branch.
  2. `pip install -e .` (or a tiny path that only needs `state.py` + aliases).
  3. Resolve week/team: if `team` or `week` empty, GET `{dashboard_url}/recommendations.json`. Fail non-zero if that GET is required and missing/unparseable — do not guess.
  4. Canonicalize `team` with **exact** alias match (canonical, `espn_team`, `odds_team`, `abbr`). Unmapped → fail.
  5. Apply the same mutations as CLI `--commit` / `--loss` (append `used_teams`, set `committed[week]`, optional life decrement). If `team` is empty and `committed[week]` is already set, do **not** overwrite with dashboard primary (loss-only / no-op). Only fill from `primary.team` when that week is unset.
  6. If yaml unchanged, exit 0 with “no-op”.
  7. Commit + push to the default branch. Message: `ops: lock week {N} {Team}` (append ` · loss` if `loss`). User-facing commit author may be `github-actions`.
- Do **not** call the Odds API, do **not** rewrite `recommendations.json`, do **not** Netlify deploy. Next `survivor-refresh` (cron or the Refresh rankings link) reads the new yaml.
- Do not upload `.env` or `data/raw/`.

Safety: Slack’s URL is navigation only. Mutation requires GitHub login + write access + **Run workflow**. Channel readers without repo write cannot change state.

---

## 11. Secrets (reuse, do not commit)

Same names and values as CFB Pick’em:

| Secret | Use |
| --- | --- |
| `ODDS_API_KEY` | The Odds API |
| `SLACK_WEBHOOK_URL` | Incoming Webhook (same channel is OK) |
| `NETLIFY_AUTH_TOKEN` | Personal access token |
| `NETLIFY_SITE_ID` | **This** new site’s id, not the CFB one |

`.env.example`:

```
ODDS_API_KEY=
SLACK_WEBHOOK_URL=
```

Public repo is fine; Actions secrets stay off the tree.

---

## 12. Tests (must pass without keys / network)

- No-vig: `-150` / `+130` style pair → probabilities sum to 1.
- `none` calibration → adj 0; ranking uses `p_current`.
- Handwritten buckets including 0.5–1.0 gap = 0.
- Unique-team: used team is not a legal candidate.
- Bye: team absent from week slate is not a candidate.
- Kickoff lock: `now >= kickoff` removes both sides of that game.
- Double-elim DP: path `[0.8, 0.8]` with 1 life < same path with 2 lives; path with a 0.0 week → `survive_p == 0` if lives cannot cover it as required by the recurrence.
- Lookahead save: construct a fixture where this week’s 0.90 favorite is the only 0.85+ option in week 15 and a 0.78 other team is available now → primary is the 0.78 team (assert by team id).
- `PRIOR_NO_MARKET` on future games without snapshots; this-week games without ML → `NO_CURRENT_ML`, skip side.
- Unmapped ESPN name → `UNMAPPED_TEAM`, not fuzzy.
- Fixture CLI smoke: `--fixture … --no-slack` exit 0, no env.
- Alerts: pick_change / new week; Slack formatter unit tests, no HTTP.
- Slack success formatter includes **Record pick** URL when `ops.github_repo` is set; never uses a refresh `run_id` as that URL.
- `--commit` updates `used_teams` + `committed` on a temp state file.
- Empty-`team` lock reads a fixture `recommendations.json` primary; unmapped team fails; `replace: false` refuses a conflicting `committed[week]`.

---

## 13. README (write this in the new repo)

Lead with weekly live run, secrets, Slack, Actions, Netlify, how to record a pick from a phone (**Record pick** link → Run workflow; empty Team = lock suggested), and laptop `--commit` / `--loss`. Do not bury the operator path under research.

---

## 14. Out of scope (V1)

- Auto-submit to ESPN / Yahoo / office-pool websites
- Slack app, slash commands, or any Slack write-back (Incoming Webhook stays outbound-only)
- Prefilling GitHub `workflow_dispatch` inputs via URL (unsupported)
- Playwright, Slack UI scraping
- Book fallback, consensus lines, public % in the objective
- Season-long historical backtest / calibration matrix generation
- Multi-entry portfolios / hedge entries
- Injury news NLP, weather models
- Playoffs
- Sharing a Netlify site with CFB Pick’em
- Committing Odds snapshots on every cron

---

## 15. Implementation order

1. Config + aliases (32 teams) + types + state load/save  
2. Probability + calibration + snapshot-at-or-before  
3. Fixture slate/odds parser + `optimize.py` with DP tests (no network)  
4. `run.py` CLI table + `--web` JSON  
5. ESPN + Odds live clients (Pinnacle only, strip apiKey)  
6. Alerts + Slack  
7. Static dashboard  
8. GHA refresh + `record-pick.yml` + Netlify script + README  
9. `workflow_dispatch` refresh once secrets exist; confirm Slack **Record pick** link opens the lock workflow  

---

## 16. Operator checklist (human, once)

1. Create empty GitHub repo; paste this spec; agent implements.  
2. Copy `ODDS_API_KEY` and `SLACK_WEBHOOK_URL` into the new repo Actions secrets and local `.env`.  
3. Create a **new** Netlify site (publish dir `web`); add `NETLIFY_AUTH_TOKEN` + `NETLIFY_SITE_ID`; set `slate.dashboard_url` and `ops.github_repo`.  
4. Fill `config/state.yaml` as the season progresses (Slack **Record pick** → Run workflow, or laptop `--commit` / `--loss`).  
5. Run **Actions → Survivor refresh → Run workflow** once; confirm Slack + dashboard + Record pick URL.  
