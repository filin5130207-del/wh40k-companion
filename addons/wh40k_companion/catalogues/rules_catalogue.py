"""Rules catalogue for text rosters, bundle standard-r4-s1-e1.

Army-rule bodies, detachment rule text, and stratagem when/target/effect
stay on the catalogue. The list owner and the opponent receive the same
text on roster detail, match state, and match watch.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

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
    """Full catalogue, including rules prose."""
    return load_catalogue()


def rule_for_viewer(rule, owner=True):
    """Roster rule payload. The list owner and the opponent get the same text.

    Name, scope, CP, restrictions, army and detachment bodies (``description``
    and ``flavor``), and stratagem when/target/effect are all included.
    ``owner`` is kept so existing callers stay valid; it does not drop prose.
    """
    row = {
        "name": (rule or {}).get("name") or "",
        "scope": (rule or {}).get("scope") or "",
    }
    cp = (rule or {}).get("cp") or ""
    if cp:
        row["cp"] = cp
    restrictions = (rule or {}).get("restrictions") or ""
    if restrictions:
        row["restrictions"] = restrictions
    description = (rule or {}).get("description") or ""
    if description:
        row["description"] = description
    flavor = (rule or {}).get("flavor") or ""
    if flavor:
        row["flavor"] = flavor
    for key in ("when", "target", "effect"):
        text = (rule or {}).get(key) or ""
        if text:
            row[key] = text
    return row


def public_catalogue() -> dict:
    """Same catalogue as the list owner, including rule bodies."""
    return load_catalogue()
