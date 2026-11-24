#!/usr/bin/env python3
"""Check the shipped rules catalogue without starting Odoo."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "addons" / "wh40k_companion" / "catalogues" / "rules_catalogue.py"
PROSE = {"body", "ruleBody", "when", "target", "effect"}


def load_module():
    spec = importlib.util.spec_from_file_location("rules_catalogue", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prose_keys(value, found):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in PROSE:
                found.add(key)
            prose_keys(item, found)
    elif isinstance(value, list):
        for item in value:
            prose_keys(item, found)


def main():
    module = load_module()
    owner = module.owner_catalogue()
    public = module.public_catalogue()
    if owner["factionCount"] != 30 or len(owner["factions"]) != 30:
        raise SystemExit(f"faction count {owner['factionCount']}")
    if owner["bundle"] != "standard-r4-s1-e1":
        raise SystemExit("bundle")
    found = set()
    prose_keys(owner, found)
    missing = PROSE - found
    if missing:
        raise SystemExit(f"owner catalogue missing {missing}")
    leaked = set()
    prose_keys(public, leaked)
    if leaked:
        raise SystemExit(f"public catalogue still has {leaked}")
    wolves = next(row for row in public["factions"] if row["id"] == "space-wolves")
    if wolves["armyRule"]["name"] != "Combat Doctrines":
        raise SystemExit("space wolves army rule name")
    if "body" in wolves["armyRule"] or "ruleBody" in wolves["detachments"][0]:
        raise SystemExit("public space wolves still has prose")
    sample = {
        "mission": {"name": "Take and Hold", "description": "Hold the objective."},
        "armyRule": {"name": "Combat Doctrines", "body": "SECRET BODY"},
        "stratagems": [{"name": "Fangs", "cp": "1CP", "when": "WHEN", "effect": "EFFECT"}],
    }
    stripped = module.strip_rule_prose(sample)
    blob = json.dumps(stripped)
    if "SECRET BODY" in blob or "WHEN" in blob or "EFFECT" in blob:
        raise SystemExit(f"strip left prose in {blob}")
    if stripped["mission"]["description"] != "Hold the objective.":
        raise SystemExit("strip removed a non-catalogue field")
    if "strip_rule_prose(" not in (
        ROOT / "addons" / "wh40k_companion" / "models" / "match.py"
    ).read_text(encoding="utf-8"):
        raise SystemExit("match state does not strip catalogue prose")
    print("ok factions", owner["factionCount"], "public prose", sorted(leaked))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — this script is the check
        print(exc, file=sys.stderr)
        raise
