import json
from pathlib import Path

from odoo.tests.common import TransactionCase, tagged

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

    def test_text_import_shares_rules_with_opponent_and_match(self):
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
        self.assertTrue(stratagem.get("name"))
        self.assertTrue(stratagem.get("cp"))
        self.assertTrue(stratagem.get("when"))
        self.assertTrue(stratagem.get("target"))
        self.assertTrue(stratagem.get("effect"))
        detachment = next(rule for rule in owner["rules"] if rule["scope"] == "detachment")
        self.assertGreater(len(detachment["description"]), 20)
        body = army["description"]
        effect = stratagem["effect"]
        prose_needle = "assault doctrine is active"
        self.assertIn(prose_needle, effect)
        self.assertIn(body[:80], json.dumps(owner))

        guest_roster = self._make_tiny_roster(self.user_b, name="Guest Text")
        match = self._activate_match(
            self.user_a, self.user_b, roster, guest_roster
        )
        opponent = roster.with_user(self.user_b).to_detail_dict(self.user_b.partner_id)
        self.assertEqual(opponent["rules"], owner["rules"])

        state = match.with_user(self.user_b).to_state_dict(self.user_b.partner_id)
        owner_state = match.with_user(self.user_a).to_state_dict(self.user_a.partner_id)
        self.assertEqual(state["host_rules"], owner["rules"])
        self.assertEqual(owner_state["host_rules"], owner["rules"])
        self.assertEqual(state["guest_rules"], owner_state["guest_rules"])
        self.assertTrue(
            any("Fight harder" in (rule.get("description") or "") for rule in state["guest_rules"])
        )
        self.assertTrue(
            any("More Dakka" in (rule.get("description") or "") for rule in state["guest_rules"])
        )
        watched = match.with_user(self.user_b).watch_payload(
            self.user_b.partner_id,
            since_write_date="2000-01-01 00:00:00",
            since_rev=0,
            wait=False,
        )
        self.assertTrue(watched["changed"])
        self.assertFalse(watched["lines_only"])
        self.assertEqual(watched["match"]["host_rules"], owner["rules"])
        self.assertEqual(watched["match"]["guest_rules"], state["guest_rules"])

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
        self.assertEqual(
            readable(body),
            next(rule["description"] for rule in opponent["rules"] if rule["scope"] == "army"),
        )
