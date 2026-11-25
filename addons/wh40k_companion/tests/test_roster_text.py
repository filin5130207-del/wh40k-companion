import json
from pathlib import Path

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.wh40k_companion.catalogues.rules_catalogue import (
    rule_for_viewer,
    strip_rule_prose,
)
from odoo.addons.wh40k_companion.parsers.roster_text import readable

from .common import Wh40kPlayerMixin


def _fixture(name):
    root = Path(__file__).resolve().parents[1] / "testdata" / "text_rosters"
    return (root / name).read_text(encoding="utf-8")


@tagged("post_install", "-at_install", "wh40k")
class TestRosterTextImport(Wh40kPlayerMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_wh40k_players()

    def test_text_import_owner_rules_stay_off_opponent_and_match(self):
        text = _fixture("gg.txt")
        roster = self.env["wh40k.roster"].action_import_text(
            self.user_a.partner_id, text
        )
        self.assertEqual(roster.partner_id, self.user_a.partner_id)
        self.assertEqual(roster.points_used, 1945)
        self.assertEqual(roster.points_limit, 2000)
        self.assertGreaterEqual(roster.unit_count, 9)
        self.assertGreater(roster.weapon_count, 0)

        owner = roster.with_user(self.user_a).to_detail_dict(self.user_a.partner_id)
        army = next(rule for rule in owner["rules"] if rule["scope"] == "army")
        self.assertEqual(army["name"], "Combat Doctrines")
        self.assertGreater(len(army["description"]), 40)
        stratagem = next(rule for rule in owner["rules"] if rule["scope"] == "stratagem")
        self.assertTrue(stratagem.get("when"))
        self.assertTrue(stratagem.get("target"))
        self.assertTrue(stratagem.get("effect"))
        body = army["description"]
        effect = stratagem["effect"]
        prose_needle = "assault doctrine is active"
        self.assertIn(prose_needle, effect)
        self.assertIn(body[:80], json.dumps(owner))

        guest_roster = self._make_tiny_roster(self.user_b, name="Guest Text")
        match = self._activate_match(
            self.user_a, self.user_b, roster, guest_roster
        )
        state = match.to_state_dict(self.user_b.partner_id)
        state_blob = json.dumps(state)
        self.assertNotIn(body[:80], state_blob)
        self.assertNotIn(prose_needle, state_blob)
        public_state = strip_rule_prose(state)
        self.assertNotIn(body[:80], json.dumps(public_state))
        self.assertNotIn(prose_needle, json.dumps(public_state))

        opponent = roster.to_detail_dict(self.user_b.partner_id)
        for rule in opponent["rules"]:
            self.assertNotIn("description", rule)
            self.assertNotIn("when", rule)
            self.assertNotIn("target", rule)
            self.assertNotIn("effect", rule)
            self.assertNotIn("body", rule)
            self.assertNotIn("ruleBody", rule)
        opponent_blob = json.dumps(opponent)
        self.assertNotIn(body[:80], opponent_blob)
        self.assertNotIn(prose_needle, opponent_blob)
        self.assertIn("Combat Doctrines", opponent_blob)

        logan = next(unit for unit in owner["units"] if unit["name"] == "Logan Grimnar")
        self.assertEqual(logan["models"][0]["M"], '6"')
        self.assertEqual(logan["models"][0]["W"], "8")
        axe = next(
            weapon
            for weapon in logan["models"][0]["weapons"]
            if weapon["name"] == "Axe Morkai – strike"
        )
        self.assertTrue(axe["A"])
        self.assertTrue(axe["S"])
        self.assertTrue(axe["D"])

        def storm_shield(payload):
            return next(
                weapon
                for unit in payload["units"]
                if unit["name"] == "Wolf Guard Terminators"
                for model in unit["models"]
                for weapon in model["weapons"]
                if weapon["name"].lower() == "storm shield"
            )

        shield = storm_shield(owner)
        for key in ("range", "A", "skill", "S", "AP", "D"):
            self.assertFalse(shield[key])
        opp_shield = storm_shield(opponent)
        self.assertEqual(opp_shield["name"].lower(), "storm shield")
        for key in ("range", "A", "skill", "S", "AP", "D"):
            self.assertFalse(opp_shield[key])
        self.assertNotIn('"when"', state_blob)
        self.assertNotIn('"target"', state_blob)
        self.assertNotIn('"effect"', state_blob)
        self.assertNotIn(
            "description",
            rule_for_viewer(
                {"name": "Combat Doctrines", "scope": "army", "description": readable(body)},
                False,
            ),
        )
