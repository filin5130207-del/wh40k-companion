"""Static detachment stratagem catalogue.

Stratagems are not stored on a roster. Import keeps the selected detachment
name; the deck is resolved here at read time. This module does not fetch a
website and does not embed a New Recruit catalogue.

``STRATAGEM_CATALOGUE`` is keyed by ``(catalogue_name, detachment_name)`` as
they appear on the New Recruit force (``catalogueName`` and the selected
Detachment child). Each entry is a list of dicts with ``name``, ``cp``,
``when``, ``target``, and ``rules``.

The sample rosters use the detachments in ``UNSEEDED_DETACHMENTS``. Their
stratagem text is not in the roster file. The published wording is Games
Workshop material (community catalogues redistribute it and do not grant a
license to copy it), so those keys are intentionally absent.
"""

from __future__ import annotations

NO_DECK_MESSAGE = "no deck for this detachment"

# (catalogue name, detachment name) for decks this module does not carry.
UNSEEDED_DETACHMENTS = (
    ("Imperium - Adeptus Astartes - Space Wolves", "Saga of the Beastslayer"),
    ("Imperium - Adeptus Astartes - Space Wolves", "Assault Brethren"),
    ("Imperium - Adeptus Astartes - Space Wolves", "Stormlance Task Force"),
    ("Chaos - Chaos Space Marines", "Creations of Bile"),
)

STRATAGEM_CATALOGUE: dict[tuple[str, str], list[dict]] = {}


def resolve_stratagem_deck(pairs, catalogue=None):
    """Resolve stratagem dicts for ``(catalogue_name, detachment_name)`` pairs.

    A detachment with no catalogue entry contributes nothing. When the whole
    deck is empty the message is ``NO_DECK_MESSAGE``. Returned dicts are
    copies; the catalogue itself is not mutated.
    """
    source = STRATAGEM_CATALOGUE if catalogue is None else catalogue
    stratagems = []
    missing = []
    seen = set()
    for catalogue_name, detachment_name in pairs or []:
        catalogue_key = (catalogue_name or "").strip()
        detachment_key = (detachment_name or "").strip()
        if not detachment_key:
            continue
        key = (catalogue_key, detachment_key)
        if key in seen:
            continue
        seen.add(key)
        entries = source.get(key) if source else None
        if not entries:
            missing.append({"catalogue": catalogue_key, "detachment": detachment_key})
            continue
        for entry in entries:
            stratagems.append(
                {
                    "name": (entry.get("name") or "").strip(),
                    "cp": entry.get("cp"),
                    "when": entry.get("when") or "",
                    "target": entry.get("target") or "",
                    "rules": entry.get("rules") or "",
                    "detachment": detachment_key,
                    "catalogue": catalogue_key,
                }
            )
    return {
        "stratagems": stratagems,
        "missing": missing,
        "message": "" if stratagems else NO_DECK_MESSAGE,
    }
