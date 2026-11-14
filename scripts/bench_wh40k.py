#!/usr/bin/env python3
"""Benchmark WH40k companion hot paths: SQL queries and wall time.

Scenarios (Odoo test ``TestWh40kPerfBench``):
  - player dashboard
  - roster detail
  - one wound update
  - watch payload after that update (no long-poll sleep)

This script does not invent numbers. It prints a ``WH40K_BENCH`` JSON line
only when Odoo actually runs the test. Without Odoo it exits 2 and prints
the command to run on the PC.

``TestWh40kPerfBench`` is duck-typed: on this branch it measures the wound
delta and line-only watch; on main (30d391e) the same file measures
``action_update_unit_state`` plus ``to_state_dict`` (the old full payload).
Copy the test file and its ``tests/__init__.py`` import onto main to take
the baseline. Do not pass ``--db-drop``.

    cd /home/odoo/wh40k-odpm
    odpm -d wh40k --test-enable --stop-after-init -u wh40k_companion \\
        --test-tags=/wh40k_companion:TestWh40kPerfBench

The test prints one ``WH40K_BENCH`` JSON line. Set ``WH40K_BENCH_LABEL``
to ``baseline`` or ``after``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
TEST_TAG = "/wh40k_companion:TestWh40kPerfBench"
PC_COMMAND = """
# ПК (WSL + ODPM). База wh40k уже есть. Не использовать --db-drop.
# Аддон в контейнере — тот коммит, который измеряем (синхронизировать дерево).
#
# Baseline: git checkout 30d391e, затем скопировать с этой ветки
#   addons/wh40k_companion/tests/test_perf_bench.py
# и строку импорта в tests/__init__.py. Тест сам вызовет старый полный payload.
# After: эта ветка целиком.
cd /home/odoo/wh40k-odpm

WH40K_BENCH_LABEL=baseline \\
  odpm -d wh40k --test-enable --stop-after-init -u wh40k_companion \\
  --test-tags=/wh40k_companion:TestWh40kPerfBench

WH40K_BENCH_LABEL=after \\
  odpm -d wh40k --test-enable --stop-after-init -u wh40k_companion \\
  --test-tags=/wh40k_companion:TestWh40kPerfBench

# Если odpm недоступен, из каталога compose (сервер на 8069 лучше остановить):
# docker compose exec -e WH40K_BENCH_LABEL=after odoo \\
#   odoo -d wh40k --test-enable --stop-after-init --http-port=8079 \\
#   -u wh40k_companion --test-tags=/wh40k_companion:TestWh40kPerfBench
#
# В логе одна строка WH40K_BENCH {...} с queries и seconds.
# Затем снова поднять стенд без -i/-u в command:
#   bash /mnt/c/Users/Павел/wh40k-companion/scripts/odpm_up.sh
""".strip()


def _find_odoo_bin(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    for name in ("odoo", "odoo-bin"):
        found = shutil.which(name)
        if found:
            return found
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--odoo-bin", help="Path to the Odoo 20 odoo-bin executable")
    parser.add_argument("--db", default=os.environ.get("WH40K_DB", "wh40k"))
    parser.add_argument(
        "--label",
        default=os.environ.get("WH40K_BENCH_LABEL", "wh40k_bench"),
        help="Recorded in the JSON line (baseline or after)",
    )
    parser.add_argument(
        "--http-port",
        default="8079",
        help="Port for the one-shot test process (avoid the live 8069 server)",
    )
    args = parser.parse_args()

    odoo_bin = _find_odoo_bin(args.odoo_bin)
    if not odoo_bin:
        print("Odoo is not available on this machine. No timings were measured.", file=sys.stderr)
        print(PC_COMMAND, file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["WH40K_BENCH_LABEL"] = args.label
    cmd = [
        odoo_bin,
        "-d",
        args.db,
        "--test-enable",
        "--stop-after-init",
        f"--http-port={args.http_port}",
        "--test-tags",
        TEST_TAG,
    ]
    print("Running:", " ".join(cmd), file=sys.stderr)
    completed = subprocess.run(cmd, cwd=str(REPO), env=env)
    if completed.returncode != 0:
        print(
            f"Odoo exited {completed.returncode}. No bench JSON was accepted.",
            file=sys.stderr,
        )
        return completed.returncode or 1
    print(
        "Look for the WH40K_BENCH JSON line in the Odoo log above. "
        "This script does not rewrite those numbers.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
