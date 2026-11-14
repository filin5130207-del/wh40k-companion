#!/bin/bash
# Boot one WH40k Odoo service. Creates the database on first run.
# Never passes --db-drop: an existing database is installed or started as-is.
set -euo pipefail

DB_NAME="${1:?database name}"
MODULE="${2:?module name}"
ADDONS="/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons"
export PYTHONPATH="/opt/wh40k${PYTHONPATH:+:$PYTHONPATH}"
export HOST="${HOST:-db}"
export USER="${USER:-odoo}"
export PASSWORD="${PASSWORD:-odoo}"
export DB_NAME MODULE

if [ "$(id -u)" = "0" ] && command -v gosu >/dev/null 2>&1; then
  mkdir -p /var/lib/odoo
  chown -R odoo:odoo /var/lib/odoo
  exec gosu odoo "$0" "$@"
fi

python3 - <<'PY'
import os
import sys
import time

import psycopg2

host, user, password = os.environ["HOST"], os.environ["USER"], os.environ["PASSWORD"]
for _ in range(60):
    try:
        psycopg2.connect(host=host, user=user, password=password, dbname="postgres").close()
        sys.exit(0)
    except Exception:
        time.sleep(1)
sys.exit("postgres not ready")
PY

set +e
python3 - <<'PY'
import os
import sys

import psycopg2

db = os.environ["DB_NAME"]
mod = os.environ["MODULE"]
try:
    conn = psycopg2.connect(
        host=os.environ["HOST"],
        user=os.environ["USER"],
        password=os.environ["PASSWORD"],
        dbname=db,
    )
except Exception:
    sys.exit(2)
cur = conn.cursor()
cur.execute("SELECT to_regclass('public.ir_module_module')")
if not cur.fetchone()[0]:
    sys.exit(2)
cur.execute("SELECT state FROM ir_module_module WHERE name=%s", (mod,))
row = cur.fetchone()
sys.exit(0 if row and row[0] == "installed" else 2)
PY
installed=$?
set -e

COMMON=(
  --db_host="$HOST"
  --db_port=5432
  --db_user="$USER"
  --db_password="$PASSWORD"
  --db-filter="^${DB_NAME}$"
  --addons-path="$ADDONS"
  --data-dir=/var/lib/odoo
  --without-demo=all
  --no-database-list
)

if [ "$installed" -ne 0 ]; then
  echo "Installing ${MODULE} into ${DB_NAME} (no --db-drop)"
  odoo -d "$DB_NAME" -i "$MODULE" --stop-after-init "${COMMON[@]}"
fi

exec odoo -d "$DB_NAME" --http-interface=0.0.0.0 --http-port=8069 --workers=0 "${COMMON[@]}"
