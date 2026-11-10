# WH40k Battle Companion

Odoo **20** module `wh40k_companion`: import NewRecruit/Battlescribe JSON rosters, player profiles, mission picker, QR match join, in-game wound/model tracking, and surrender stats.

## Stack

- Odoo 20 + PostgreSQL via Docker Compose
- Custom OWL frontend + `@http.route` JSON API
- **ODPM** (`odpm.json`) for the Odoo package/module workflow
- No Odoo Bus / no offline mode

## Quick start (Docker Compose)

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

```bash
pip install odpm
# from a parent workspace directory, initialize against this repo, or place odpm.json
# at the project root (already present) and follow odpm prepare/run docs for your scenario.
odpm plan --plan-no-docker   # inspect planned steps when Docker is available use: odpm plan
odpm -d wh40k -i wh40k_companion
```

See [aayartsev/odpm](https://github.com/aayartsev/odpm) for full developer/server/CI scenarios.

## Import sample roster

Sample NewRecruit export:

`addons/wh40k_companion/testdata/aufychi.json`

1. Open **WH40k Companion → Battle App**
2. On the dashboard, choose the JSON file and click **Import JSON**
3. Or call `POST /wh40k/roster/import` (JSON-RPC, auth user) with `roster_json`

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

## Module layout

```
addons/wh40k_companion/
  models/ controllers/ views/ security/ data/
  parsers/battlescribe_parser.py
  static/src/{js,xml,css}
  testdata/aufychi.json
  tests/
```
