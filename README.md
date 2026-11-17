# WH40k Battle Companion

Odoo **20** module `wh40k_companion`: import NewRecruit/Battlescribe JSON rosters, player profiles, mission picker, QR match join, in-game wound/model tracking, and surrender stats.

## Stack

- Odoo 20 + PostgreSQL via Docker Compose
- Standalone Battle App PWA at `/wh40k/app` + thin `@http.route` JSON API under `/wh40k/api/`
- **ODPM** (`odpm.json`) for the Odoo package/module workflow
- Match updates via the Odoo bus websocket (`/websocket`, channel `wh40k.match.<partner_id>`). `/wh40k/api/match/watch` stays as the fallback when the socket fails, and a finish still wakes an in-flight watch. Offline S7 is still out of scope
- Join / QR links use system parameter `wh40k.public_base_url` (a tunnel or a real host). `web.base.url` is used only when it is not loopback or a private address. A private link is shown as LAN-only

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

### Bus websocket

With `workers = 0` (the default in `config/odoo.conf`, and the single `odoo` process in `docker-compose.yml`) Odoo serves `/websocket` on port **8069**. The Battle App uses that same origin. Check:

```bash
curl -s http://127.0.0.1:8069/websocket/health
# {"status": "pass"}
```

Do not set `--workers` above 0 unless a reverse proxy on the public port forwards paths starting with `/websocket` to `gevent_port` (8072) and every other path to `http_port`. Players should not open 8072. See [docs/odpm.md](docs/odpm.md).

### Public join links

Set system parameter `wh40k.public_base_url` to the public origin (scheme, host, optional port, no trailing slash), for example the URL printed by a Cloudflare tunnel or ngrok. Leave it empty only when `web.base.url` is already a public host. A LAN address is still encoded in the QR for same-Wi-Fi play, and the waiting screen says that link works only on this LAN. `scripts/lan_tcp_proxy.py` stays an optional same-Wi-Fi helper.

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
