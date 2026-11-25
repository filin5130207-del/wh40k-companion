"""Resolve official-app and New Recruit text against the rules catalogue.

Run from the repository root:

    python3 addons/wh40k_companion/static/tests/test_roster_text.py
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path

ADDON = Path(__file__).resolve().parents[2]
pkg = types.ModuleType("wh40k_companion")
pkg.__path__ = [str(ADDON)]
sys.modules["wh40k_companion"] = pkg

from wh40k_companion.catalogues.rules_catalogue import (  # noqa: E402
    load_catalogue,
    rule_for_viewer,
)
from wh40k_companion.parsers.roster_text import (  # noqa: E402
    RosterTextParser,
    readable,
    unmatched_gear,
)

FIXTURES = ADDON / "testdata" / "text_rosters"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def storm_shields(matched) -> list[str]:
    rows = []
    for unit in matched["units"]:
        for item in unit["items"]:
            if item.get("kind") != "gear" or item.get("isModel"):
                continue
            if "storm shield" not in (item.get("name") or "").lower():
                continue
            status = (item.get("match") or {}).get("status")
            rows.append(f"{unit['name']}:{status}")
    return rows


class RosterTextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue = load_catalogue()
        cls.gg = RosterTextParser(load("gg.txt"), cls.catalogue).matched()
        cls.auf = RosterTextParser(load("aufsky-drift.txt"), cls.catalogue).matched()

    def test_units_and_detachments_match(self):
        self.assertEqual(self.gg["meta"]["factionId"], "space-wolves")
        self.assertEqual(self.gg["meta"]["armyRule"]["name"], "Combat Doctrines")
        self.assertGreater(len(self.gg["meta"]["armyRule"]["body"]), 40)
        self.assertEqual(
            [det["id"] for det in self.gg["detachments"]],
            ["assault-brethren", "deathwatch-support", "terminator-storm-force"],
        )
        self.assertTrue(all(unit["datasheetId"] and unit["profiles"] for unit in self.gg["units"]))
        terminators = next(unit for unit in self.gg["units"] if unit["name"] == "Terminator Squad")
        self.assertEqual(terminators["source"], "space-marines")
        deathwatch = next(unit for unit in self.gg["units"] if unit["name"] == "Deathwatch Terminator Squad")
        self.assertEqual(deathwatch["source"], "deathwatch")

        self.assertEqual(self.auf["meta"]["name"], "Ауфский дрифт")
        self.assertEqual(self.auf["meta"]["factionId"], "space-wolves")
        self.assertEqual(self.auf["meta"]["points"], 2000)
        self.assertEqual(
            [det["id"] for det in self.auf["detachments"]],
            ["saga-of-the-beastslayer", "assault-brethren", "stormlance-task-force"],
        )
        self.assertTrue(all(unit["datasheetId"] and unit["profiles"] for unit in self.auf["units"]))

    def test_storm_shield_is_unmatched_weapon(self):
        gg_shields = storm_shields(self.gg)
        auf_shields = storm_shields(self.auf)
        self.assertTrue(gg_shields)
        self.assertTrue(auf_shields)
        self.assertTrue(all(row.endswith(":unmatched") for row in gg_shields), gg_shields)
        self.assertTrue(all(row.endswith(":unmatched") for row in auf_shields), auf_shields)
        self.assertTrue(any("Storm Shield" in row for row in unmatched_gear(self.gg)))

    def test_import_keeps_profiles_and_shared_rules(self):
        imported = RosterTextParser(load("gg.txt"), self.catalogue).parse()
        force = imported["forces"][0]
        self.assertEqual(force["catalogue_name"], "Space Wolves")
        self.assertEqual(force["army_rules"][0]["rule_scope"], "army")
        body = readable(self.gg["meta"]["armyRule"]["body"])
        self.assertEqual(force["army_rules"][0]["description"], body)
        detachments = force["detachments"]
        self.assertEqual(len(detachments), 3)
        self.assertEqual(
            [det["name"] for det in detachments],
            ["Assault Brethren", "Deathwatch Support", "Terminator Storm Force"],
        )
        units = detachments[0]["units"]
        self.assertEqual(len(units), len(self.gg["units"]))
        self.assertEqual(detachments[1]["units"], [])
        logan = next(unit for unit in units if unit["name"] == "Logan Grimnar")
        self.assertEqual(len(logan["models"]), 1)
        profile = logan["models"][0]
        self.assertEqual(profile["movement"], '6"')
        self.assertEqual(profile["toughness"], "6")
        self.assertEqual(profile["save"], "2+")
        self.assertEqual(profile["wounds"], "8")
        self.assertEqual(profile["invuln_save"], "4+")
        weapon_names = [weapon["name"] for weapon in profile["weapons"]]
        self.assertIn("Storm Bolter", weapon_names)
        self.assertIn("Axe Morkai – strike", weapon_names)
        self.assertIn("Axe Morkai – sweep", weapon_names)

        terminators = next(unit for unit in units if unit["name"] == "Terminator Squad")
        by_name = {model["name"]: model for model in terminators["models"]}
        self.assertEqual(by_name["Terminator"]["quantity"], 9)
        self.assertEqual(by_name["Terminator Sergeant"]["quantity"], 1)
        self.assertTrue(by_name["Terminator"]["weapons"])

        wolves = next(unit for unit in units if unit["name"] == "Wolf Guard Terminators")
        shield_names = [
            weapon["name"]
            for model in wolves["models"]
            for weapon in model["weapons"]
            if weapon["name"].lower() == "storm shield"
        ]
        self.assertTrue(shield_names)
        shield = next(
            weapon
            for model in wolves["models"]
            for weapon in model["weapons"]
            if weapon["name"].lower() == "storm shield"
        )
        self.assertEqual(shield["attacks"], "")
        self.assertEqual(shield["damage"], "")

        stratagems = [rule for rule in detachments[0]["rules"] if rule["rule_scope"] == "stratagem"]
        self.assertTrue(stratagems)
        effect = stratagems[0]["effect"]
        self.assertGreater(len(effect), 20)
        owner = rule_for_viewer(
            {
                "name": stratagems[0]["name"],
                "scope": "stratagem",
                "description": "",
                "cp": stratagems[0]["cp"],
                "when": stratagems[0]["when"],
                "target": stratagems[0]["target"],
                "effect": effect,
                "restrictions": stratagems[0]["restrictions"],
            },
            True,
        )
        opponent = rule_for_viewer(
            {
                "name": force["army_rules"][0]["name"],
                "scope": "army",
                "description": body,
                "cp": stratagems[0]["cp"],
                "when": stratagems[0]["when"],
                "target": stratagems[0]["target"],
                "effect": effect,
            },
            False,
        )
        self.assertEqual(rule_for_viewer(
            {
                "name": stratagems[0]["name"],
                "scope": "stratagem",
                "cp": stratagems[0]["cp"],
                "when": stratagems[0]["when"],
                "target": stratagems[0]["target"],
                "effect": effect,
                "restrictions": stratagems[0]["restrictions"],
            },
            True,
        ), rule_for_viewer(
            {
                "name": stratagems[0]["name"],
                "scope": "stratagem",
                "cp": stratagems[0]["cp"],
                "when": stratagems[0]["when"],
                "target": stratagems[0]["target"],
                "effect": effect,
                "restrictions": stratagems[0]["restrictions"],
            },
            False,
        ))
        self.assertEqual(owner["effect"], effect)
        self.assertEqual(owner["name"], stratagems[0]["name"])
        self.assertEqual(owner["cp"], stratagems[0]["cp"])
        self.assertEqual(owner["when"], stratagems[0]["when"])
        self.assertEqual(owner["target"], stratagems[0]["target"])
        self.assertEqual(opponent["name"], force["army_rules"][0]["name"])
        self.assertEqual(opponent["cp"], stratagems[0]["cp"])
        self.assertEqual(opponent["description"], body)
        self.assertEqual(opponent["when"], stratagems[0]["when"])
        self.assertEqual(opponent["target"], stratagems[0]["target"])
        self.assertEqual(opponent["effect"], effect)
        self.assertIn(body[:60], json.dumps(opponent))
        self.assertEqual(imported["points_used"], 1945)
        self.assertEqual(imported["points_limit"], 2000)
        auf_import = RosterTextParser(load("aufsky-drift.txt"), self.catalogue).parse()
        auf_units = auf_import["forces"][0]["detachments"][0]["units"]
        self.assertEqual(len(auf_units), len(self.auf["units"]))
        for unit in auf_units:
            self.assertTrue(unit["models"], unit["name"])
            self.assertTrue(any(model["toughness"] for model in unit["models"]), unit["name"])
        shared = {
            "state": "active",
            "mission": {"name": "Take and Hold", "description": "Hold the centre."},
            "rules": [opponent],
        }
        self.assertEqual(shared["mission"]["description"], "Hold the centre.")
        self.assertEqual(shared["rules"][0]["description"], body)
        self.assertEqual(shared["rules"][0]["when"], stratagems[0]["when"])
        self.assertEqual(shared["rules"][0]["effect"], effect)


if __name__ == "__main__":
    unittest.main()
