# WH40k Battle Companion

Odoo **20** module `wh40k_companion`: import NewRecruit/Battlescribe JSON rosters, player profiles, mission picker, QR match join, in-game wound/model tracking, and surrender stats.

## Stack

- Odoo 20 + PostgreSQL via Docker Compose
- Standalone Battle App PWA at `/wh40k/app` + thin `@http.route` JSON API under `/wh40k/api/`
- **ODPM** (`odpm.json`) for the Odoo package/module workflow
- Match updates via `/wh40k/api/match/watch` long-poll + `bus.bus` notify (standalone PWA; offline S7 still out of scope)

## Three services

A single Odoo database cannot share `res.users`, groups, or `Many2one` links across registries. The split therefore runs three Odoo processes and three databases. Accounts stay on **session**. Roster stores `owner_uid`. Match copies a roster snapshot at create/join. The PWA on session calls the other two with a bearer token. Research notes: the project Context file `docs/odoo-microservices.md`.

The monolith module `wh40k_companion` is unchanged and still runs from `docker-compose.yml`. Do not point the service stack at that volume, and do not pass `--db-drop`.

```bash
docker compose -f docker-compose.services.yml up -d
```

| Service | Published port | Database | Owns |
| --- | --- | --- | --- |
| session | 8069 | `wh40k_session` | signup, login, Player/Manager, nickname, win/loss, PWA, bearer token |
| roster | 8070 | `wh40k_roster` | Battlescribe/NewRecruit import, datasheets, `owner_uid` |
| match | 8071 | `wh40k_match` | create, join token, wounds, undo, surrender, watch, mission list |

Open http://localhost:8069/wh40k/app after the first boot finishes installing each module (the boot script installs only when that module is missing). `WH40K_TOKEN_SECRET` must be the same on all three services. The compose file ships a dev default.

Inside the Docker network each Odoo listens on 8069. Match calls `http://roster:8069` and `http://session:8069`. The browser uses ports 8070 and 8071. On a LAN phone the PWA rewrites loopback URLs to the host it was opened on.

## Quick start (monolith)

```bash
docker compose up -d
```

Open http://localhost:8069, create a database, then install **WH40k Battle Companion** from Apps (enable developer mode / update apps list if needed).

Custom addons are mounted from `./addons` into `/mnt/extra-addons`.

Default DB credentials (see `docker-compose.yml` / `config/odoo.conf`):

- user / password: `odoo` / `odoo`
- master password: `admin`

### Install / upgrade module inside the container

```bash
docker compose exec odoo odoo -d <database> -i wh40k_companion --stop-after-init
# after code changes:
docker compose exec odoo odoo -d <database> -u wh40k_companion --stop-after-init
docker compose restart odoo
```

## ODPM workflow

This repo includes `odpm.json` targeting Odoo **20.0**.

**Persistent start** (keeps Docker volume / user accounts — no `--db-drop`):

```bash
scripts/odpm_up.bat          # Windows → WSL Debian
# or in WSL: bash scripts/odpm_up.sh
```

```bash
pip install odpm             # Linux/WSL (Windows native odpm lacks `grp`)
# from the ODPM project cwd (e.g. /home/odoo/wh40k-odpm), not only the git root:
odpm plan --plan-no-docker   # inspect planned steps; with Docker: odpm plan
odpm -d wh40k -i wh40k_companion   # first install only
odpm -d wh40k -u wh40k_companion   # later upgrades — do not use --db-drop
```

Use `odpm --db-drop` only when you intentionally wipe the database. Details: [docs/odpm.md](docs/odpm.md).

See [aayartsev/odpm](https://github.com/aayartsev/odpm) for full developer/server/CI scenarios.

## Import sample roster

Sample NewRecruit export:

`addons/wh40k_companion/testdata/aufychi.json`

1. Open **http://\<host\>:8069/wh40k/app** (or **WH40k Companion → Battle App**, which opens the PWA URL)
2. On the dashboard, choose the JSON file and click **Import JSON**
3. Or call `POST /wh40k/api/roster/import` (JSON-RPC, auth user) with `roster_json`

Parser smoke test (no Odoo required):

```bash
python3 scripts/smoke_parse_aufychi.py
```

## Features by phase

| Phase | Deliverable |
|------|-------------|
| 0 | Docker Compose, ODPM manifest, module skeleton |
| 1 | Roster models + BattlescribeParser (`$text`) + `/wh40k/roster/import` |
| 2 | `res.partner` WH40k stats + OWL PlayerDashboard |
| 3 | `wh40k.mission` seeds + mission picker |
| 4–5 | Match create/publish/verify/join + QR waiting screen |
| 6–7 | GameScreen, datasheet modal, `unit_state`, surrender + result |
| 8–9 | Cron cancel waiting >15m, dark mobile CSS, README + smoke test |
| 10 | Battle App as standalone PWA (`/wh40k/app`) + `/wh40k/api/*`; logic in models |

## Module layout

```
addons/wh40k_companion/
  models/ controllers/ views/ security/ data/
  parsers/battlescribe_parser.py
  static/src/pwa/          # standalone OWL PWA (not backend client action)
  static/src/css/          # shared public-page CSS
  testdata/aufychi.json
  tests/
```

PWA notes: [docs in project store] see `docs/battle-app-pwa.md` on the agent Context, and open `/wh40k/app` after `odpm -d wh40k -u wh40k_companion`.
