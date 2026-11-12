#!/usr/bin/env bash
# NUCLEAR ONLY: drops the wh40k database and reinstalls the module.
# All user accounts, rosters, and matches are DELETED.
# For normal start use: scripts/odpm_up.sh
# For module code changes use: odpm -d wh40k -u wh40k_companion  (no --db-drop)
set -euo pipefail

cd /home/odoo/wh40k-odpm
echo "==== WARNING: odpm --db-drop will wipe ALL accounts in database wh40k ===="
echo "==== CWD=$(pwd) ===="
odpm --db-drop -d wh40k -i wh40k_companion
echo "==== DONE ===="
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
