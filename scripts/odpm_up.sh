#!/usr/bin/env bash
# Persistent ODPM start for WH40k Companion.
# Keeps Docker volume wh40k-odpm_postgres-data. Never uses --db-drop.
# Also strips baked-in -i/-u from compose so restarts do not reinstall modules.
set -euo pipefail

ODPM_DIR="${ODPM_DIR:-/home/odoo/wh40k-odpm}"
cd "$ODPM_DIR"

COMPOSE_FILE="${ODPM_DIR}/docker-compose.yml"
if [[ -f "$COMPOSE_FILE" ]]; then
  python3 - <<'PY'
from pathlib import Path
p = Path("/home/odoo/wh40k-odpm/docker-compose.yml")
text = p.read_text()
# Remove install/upgrade flags ODPM leaves in the default odoo command.
for old, new in (
    ("      - -d\n      - wh40k\n      - -i\n      - wh40k_companion\n", "      - -d\n      - wh40k\n"),
    ("      - -d\n      - wh40k\n      - -u\n      - wh40k_companion\n", "      - -d\n      - wh40k\n"),
):
    if old in text:
        text = text.replace(old, new)
        print(f"stripped install/upgrade flags from {p}")
p.write_text(text)
PY
fi

echo "==== ODPM persistent up (no --db-drop) cwd=$(pwd) ===="
docker compose up -d db
echo "==== waiting for postgres ===="
for i in $(seq 1 40); do
  if docker compose exec -T db pg_isready -U postgres >/dev/null 2>&1; then
    echo "postgres ready ($i)"
    break
  fi
  sleep 2
done
docker compose up -d
# Recreate odoo if its command still embeds -i/-u from an old container
CMD=$(docker inspect wh40k-odpm-odoo-1 --format '{{json .Config.Cmd}}' 2>/dev/null || true)
if echo "$CMD" | grep -q -- '"-i"' || echo "$CMD" | grep -q -- '"-u"'; then
  echo "==== recreating odoo without -i/-u (was: $CMD) ===="
  docker compose up -d --force-recreate --no-deps odoo
fi

echo "==== waiting for /web/login ===="
for i in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8069/web/login || true)
  echo "try $i HTTP=$code"
  if [ "$code" = "200" ]; then
    break
  fi
  sleep 3
done

docker compose ps
echo "==== Cmd (must not include -i/-u) ===="
docker inspect wh40k-odpm-odoo-1 --format '{{json .Config.Cmd}}'
echo "==== module + active users ===="
docker exec wh40k-odpm-db-1 psql -U postgres -d wh40k -c \
  "SELECT name, state, latest_version FROM ir_module_module WHERE name='wh40k_companion';" || true
docker exec wh40k-odpm-db-1 psql -U postgres -d wh40k -c \
  "SELECT id, login, active FROM res_users WHERE active ORDER BY id;" || true

echo "Open http://localhost:8069  (admin/admin). Volume: wh40k-odpm_postgres-data"
echo "Do NOT use: odpm --db-drop  or  docker compose down -v"
echo "Upgrades: odpm -d wh40k -u wh40k_companion   (then re-run this script to strip -u from compose)"