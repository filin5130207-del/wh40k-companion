# ODPM notes

This repository ships an `odpm.json` for **Odoo 20.0** so teams can use [ODPM](https://github.com/aayartsev/odpm) as the package/module workflow.

```json
{
  "odpm_version": "4.0",
  "odoo_version": "20.0",
  "python_version": "3.14",
  "distro_name": "debian",
  "distro_version": "13",
  "postgres_version": "18",
  "odoo_git_link": "https://github.com/odoo/odoo.git",
  "platform_name": "odoo"
}
```

## Persistent local stack (keeps user accounts)

On `DESKTOP-KU75OSC` the live ODPM project is `/home/odoo/wh40k-odpm` (WSL Debian). Postgres data is in Docker volume **`wh40k-odpm_postgres-data`** — keep it.

**Start / restart (no DB wipe):**

```bash
# Windows:
scripts\odpm_up.bat

# WSL:
bash scripts/odpm_up.sh
# or:
cd /home/odoo/wh40k-odpm && docker compose up -d
```

**Upgrade module after code sync (still no drop):**

```bash
cd /home/odoo/wh40k-odpm
odpm -d wh40k -u wh40k_companion
```

**Stop without deleting data:** `docker compose stop` or `docker compose down` (omit `-v`).

Important: `odpm -d wh40k -i|-u wh40k_companion` rewrites `docker-compose.yml` so the odoo service `command` includes `-i`/`-u`. Those flags run on every container start and can wipe accounts. Always finish with `scripts/odpm_up.sh` (strips the flags; keeps volume `wh40k-odpm_postgres-data`).

Never use `docker compose down -v` or `docker volume rm wh40k-odpm_postgres-data` for a normal restart.

## First-time install

```bash
pip install odpm   # on Linux/WSL; Windows native odpm lacks `grp`
cd /home/odoo/wh40k-odpm
odpm plan
odpm -d wh40k -i wh40k_companion
```

## When `--db-drop` is needed

Only for an **intentional wipe** of database `wh40k` (all users and app data): broken first install that cannot be upgraded, or a deliberate clean slate.

```bash
cd /home/odoo/wh40k-odpm
odpm --db-drop -d wh40k -i wh40k_companion   # deletes all accounts
```

Helper (nuclear only): `scripts/_odpm_reinstall.sh`.

For a lighter path without generating the full ODPM workspace, use the committed `docker-compose.yml` (official `odoo:20.0` image + Postgres) described in the root README.
