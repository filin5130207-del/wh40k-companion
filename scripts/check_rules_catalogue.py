#!/usr/bin/env python3
"""Check the shipped rules catalogue without starting Odoo."""

from __future__ import annotations

import importlib.util
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
    if public["bundle"] != owner["bundle"] or public["factionCount"] != owner["factionCount"]:
        raise SystemExit("public catalogue differs from the owner catalogue")
    wolves = next(row for row in public["factions"] if row["id"] == "space-wolves")
    if wolves["armyRule"]["name"] != "Combat Doctrines":
        raise SystemExit("space wolves army rule name")
    body = wolves["armyRule"].get("body") or ""
    det = wolves["detachments"][0]
    strat = det["stratagems"][0]
    if len(body) < 20 or not det.get("ruleBody"):
        raise SystemExit("catalogue missing army or detachment body")
    if not strat.get("name") or not strat.get("cp"):
        raise SystemExit("stratagem missing name or cp")
    for key in ("when", "target", "effect"):
        if not strat.get(key):
            raise SystemExit(f"stratagem missing {key}")
    viewer = module.rule_for_viewer(
        {
            "name": wolves["armyRule"]["name"],
            "scope": "army",
            "description": body,
            "cp": strat["cp"],
            "when": strat["when"],
            "target": strat["target"],
            "effect": strat["effect"],
        },
        False,
    )
    if viewer["name"] != "Combat Doctrines" or viewer.get("cp") != strat["cp"]:
        raise SystemExit("viewer payload missing name or cp")
    if viewer.get("description") != body:
        raise SystemExit("viewer payload missing army body")
    if (
        viewer.get("when") != strat["when"]
        or viewer.get("target") != strat["target"]
        or viewer.get("effect") != strat["effect"]
    ):
        raise SystemExit("viewer payload missing stratagem prose")
    match_src = (
        ROOT / "addons" / "wh40k_companion" / "models" / "match.py"
    ).read_text(encoding="utf-8")
    if "strip_rule_prose(" in match_src:
        raise SystemExit("match state still strips catalogue prose")
    if "host_rules" not in match_src or "guest_rules" not in match_src:
        raise SystemExit("match state does not carry roster rules")
    print("ok factions", owner["factionCount"], "shared prose", sorted(found))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — this script is the check
        print(exc, file=sys.stderr)
        raise
