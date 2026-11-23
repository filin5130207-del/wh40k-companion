"""Static detachment stratagem catalogue.

Stratagems are not stored on a roster. Import keeps the selected detachment
name; the deck is resolved here at read time. This module does not fetch a
website and does not embed a New Recruit catalogue.

``STRATAGEM_CATALOGUE`` is keyed by ``(catalogue_name, detachment_name)`` as
they appear on the New Recruit force (``catalogueName`` and the selected
Detachment child). Each public entry is ``name``, ``type``, and ``cp`` only.
WHEN, TARGET, EFFECT, and other codex wording are not stored or returned.

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


_PUBLIC_STRATAGEM_KEYS = ("name", "type", "cp")


def public_stratagem(entry):
    """Name, type, and CP. Rules prose is dropped even if the source has it."""
    entry = entry or {}
    return {
        "name": (entry.get("name") or "").strip(),
        "type": (entry.get("type") or "").strip(),
        "cp": entry.get("cp"),
    }


def resolve_stratagem_deck(pairs, catalogue=None):
    """Resolve stratagem dicts for ``(catalogue_name, detachment_name)`` pairs.

    A detachment with no catalogue entry contributes nothing. When the whole
    deck is empty the message is ``NO_DECK_MESSAGE``. Returned dicts are
    copies with only name, type, and CP; the catalogue itself is not mutated.
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
            card = public_stratagem(entry)
            if set(card) != set(_PUBLIC_STRATAGEM_KEYS):
                card = {field: card.get(field) for field in _PUBLIC_STRATAGEM_KEYS}
            stratagems.append(card)
    return {
        "stratagems": stratagems,
        "missing": missing,
        "message": "" if stratagems else NO_DECK_MESSAGE,
    }


def stratagem_fields_for_viewer(deck, is_owner):
    """Owner receives the deck. A non-owner receives no stratagem keys at all."""
    if not is_owner:
        return {}
    deck = deck or {}
    return {
        "stratagems": list(deck.get("stratagems") or []),
        "stratagem_message": deck.get("message") or "",
    }
