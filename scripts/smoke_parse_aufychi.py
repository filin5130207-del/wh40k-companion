#!/usr/bin/env python3
"""Smoke-test BattlescribeParser against testdata/aufychi.json (no Odoo required)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSER_PATH = ROOT / "addons" / "wh40k_companion" / "parsers" / "battlescribe_parser.py"


def load_parser():
    spec = importlib.util.spec_from_file_location("battlescribe_parser", PARSER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.BattlescribeParser


def main() -> int:
    BattlescribeParser = load_parser()
    sample = ROOT / "addons" / "wh40k_companion" / "testdata" / "aufychi.json"
    data = json.loads(sample.read_text(encoding="utf-8"))
    parser = BattlescribeParser(data)
    summary = parser.summary()
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    for key in ("units", "models", "weapons", "abilities", "points_used"):
        if summary.get(key, 0) <= 0:
            print(f"FAIL: expected non-zero {key}, got {summary.get(key)}", file=sys.stderr)
            return 1
    parsed = parser.parse()
    first_unit = parsed["forces"][0]["detachments"][0]["units"][0]
    first_model = first_unit["models"][0]
    if not first_model.get("toughness"):
        print("FAIL: expected toughness from Unit profile $text", file=sys.stderr)
        return 1
    if not first_model.get("weapons"):
        print("FAIL: expected weapons on first model", file=sys.stderr)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
