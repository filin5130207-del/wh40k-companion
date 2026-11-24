"""Rules catalogue for text rosters, bundle standard-r4-s1-e1.

The file keeps army-rule bodies, detachment rule text, and stratagem
when/target/effect so the owning player can resolve a list. Those fields are
not part of match state. ``public_catalogue`` and ``strip_rule_prose`` drop
them before anything is handed to the other player.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

PROSE_KEYS = frozenset({"body", "ruleBody", "when", "target", "effect"})

_CATALOGUE_PATH = Path(__file__).resolve().parent.parent / "data" / "rules_catalogue.json"


def catalogue_path() -> Path:
    return _CATALOGUE_PATH


@lru_cache(maxsize=1)
def load_catalogue() -> dict:
    raw = catalogue_path().read_text(encoding="utf-8")
    data = json.loads(raw)
    if data.get("bundle") != "standard-r4-s1-e1":
        raise ValueError("rules catalogue bundle is not standard-r4-s1-e1")
    return data


def owner_catalogue() -> dict:
    """Full catalogue, including rules prose. Owner-only."""
    return load_catalogue()


def strip_rule_prose(value):
    """Copy ``value`` without army/detachment bodies or stratagem when/target/effect.

    Stats, names, CP, restrictions, and weapon profiles stay. The catalogue
    cache is not mutated.
    """
    if isinstance(value, dict):
        return {
            key: strip_rule_prose(item)
            for key, item in value.items()
            if key not in PROSE_KEYS
        }
    if isinstance(value, list):
        return [strip_rule_prose(item) for item in value]
    return value


def public_catalogue() -> dict:
    """Catalogue safe to show outside the owner's own rules view."""
    return strip_rule_prose(load_catalogue())
