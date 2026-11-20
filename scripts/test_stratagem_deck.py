#!/usr/bin/env python3
"""Stratagem import binding and deck lookup. No Odoo, no network."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addons" / "wh40k_companion"
sys.path.insert(0, str(ADDON))

from catalogues.stratagems import (  # noqa: E402
    NO_DECK_MESSAGE,
    UNSEEDED_DETACHMENTS,
    resolve_stratagem_deck,
)
from parsers.battlescribe_parser import BattlescribeParser  # noqa: E402


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestSelectedDetachmentBinding(unittest.TestCase):
    def test_aufychi_binds_taken_detachments_only(self):
        parsed = BattlescribeParser(
            _load(ADDON / "testdata" / "aufychi.json")
        ).parse()
        self.assertEqual(
            parsed["detachment_names"],
            [
                "Saga of the Beastslayer",
                "Assault Brethren",
                "Stormlance Task Force",
            ],
        )
        force = parsed["forces"][0]
        self.assertEqual(force["catalogue_name"], "Imperium - Adeptus Astartes - Space Wolves")
        self.assertEqual(
            [det["name"] for det in force["detachments"]],
            parsed["detachment_names"],
        )
        # Rule titles under a detachment are not extra detachment names.
        self.assertNotIn("Legendary Slayers", parsed["detachment_names"])
        self.assertNotIn("Purge the Foe", parsed["detachment_names"])
        self.assertGreater(len(force["detachments"][0]["units"]), 0)
        self.assertEqual(force["detachments"][1]["units"], [])

    def test_ptichki_binds_creations_of_bile(self):
        parsed = BattlescribeParser(
            _load(ADDON / "testdata" / "ptichki.json")
        ).parse()
        self.assertEqual(parsed["detachment_names"], ["Creations of Bile"])
        self.assertEqual(
            parsed["forces"][0]["catalogue_name"],
            "Chaos - Chaos Space Marines",
        )

    def test_number_zero_is_not_selected(self):
        data = {
            "roster": {
                "name": "Pick One",
                "gameSystemName": "Warhammer 40,000 11th Edition",
                "forces": [
                    {
                        "name": "Army Roster",
                        "catalogueName": "Orks",
                        "selections": [
                            {
                                "name": "Detachment",
                                "type": "upgrade",
                                "selections": [
                                    {
                                        "name": "Saga of the Beastslayer",
                                        "type": "upgrade",
                                        "number": 0,
                                        "group": "Detachment",
                                        "rules": [{"name": "Legendary Slayers", "description": "nope"}],
                                    },
                                    {
                                        "name": "Creations of Bile",
                                        "type": "upgrade",
                                        "number": 1,
                                        "group": "Detachment",
                                    },
                                    {
                                        "name": "Stormlance Task Force",
                                        "type": "upgrade",
                                        "number": 0,
                                        "group": "Detachment",
                                    },
                                ],
                            },
                            {
                                "name": "Boyz",
                                "type": "unit",
                                "number": 1,
                                "profiles": [],
                            },
                        ],
                    }
                ],
            }
        }
        parsed = BattlescribeParser(data).parse()
        self.assertEqual(parsed["detachment_names"], ["Creations of Bile"])
        self.assertEqual(len(parsed["forces"][0]["detachments"]), 1)
        self.assertEqual(parsed["forces"][0]["detachments"][0]["units"][0]["name"], "Boyz")

    def test_unseeded_detachments_have_no_text(self):
        for catalogue_name, detachment_name in UNSEEDED_DETACHMENTS:
            deck = resolve_stratagem_deck([(catalogue_name, detachment_name)])
            self.assertEqual(deck["stratagems"], [], detachment_name)
            self.assertEqual(deck["message"], NO_DECK_MESSAGE)
            self.assertEqual(deck["missing"], [{"catalogue": catalogue_name, "detachment": detachment_name}])

    def test_known_catalogue_returns_text_without_mutating_the_roster_names(self):
        catalogue = {
            ("Orks", "Waaaagh! Tribe"): [
                {
                    "name": "Get Stuck In",
                    "cp": 1,
                    "when": "Fight phase",
                    "target": "One friendly unit",
                    "rules": "Test rules text.",
                }
            ]
        }
        deck = resolve_stratagem_deck([("Orks", "Waaaagh! Tribe")], catalogue=catalogue)
        self.assertEqual(deck["message"], "")
        self.assertEqual(deck["stratagems"][0]["name"], "Get Stuck In")
        self.assertEqual(deck["stratagems"][0]["cp"], 1)
        self.assertIn("Test rules text.", deck["stratagems"][0]["rules"])
        deck["stratagems"][0]["rules"] = "changed"
        again = resolve_stratagem_deck([("Orks", "Waaaagh! Tribe")], catalogue=catalogue)
        self.assertEqual(again["stratagems"][0]["rules"], "Test rules text.")

    def test_unknown_detachment_message(self):
        deck = resolve_stratagem_deck([("Orks", "Nope")])
        self.assertEqual(deck["stratagems"], [])
        self.assertEqual(deck["message"], "no deck for this detachment")


if __name__ == "__main__":
    unittest.main()
