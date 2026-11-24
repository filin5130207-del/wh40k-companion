"""Unit keys stored on a match snapshot.

Host and guest rosters both number units from 1. The PWA undo map is keyed
only by ``unit_id``, so the two sides must not share a key.
"""


def side_unit_key(side, raw_key):
    key = int(raw_key)
    if key <= 0:
        raise ValueError("unit_key must be positive.")
    if side == "host":
        return key
    if side == "guest":
        return -key
    raise ValueError("side must be host or guest.")
