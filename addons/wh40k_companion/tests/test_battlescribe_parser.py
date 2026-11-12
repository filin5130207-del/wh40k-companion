import json

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.wh40k_companion.parsers.battlescribe_parser import BattlescribeParser

from .common import load_sample_roster_json, minimal_roster_json


@tagged("post_install", "-at_install", "wh40k")
class TestBattlescribeParser(TransactionCase):
    def test_parse_aufychi_sample(self):
        data = load_sample_roster_json()
        parser = BattlescribeParser(data)
        summary = parser.summary()
        self.assertGreater(summary["units"], 0)
        self.assertGreater(summary["models"], 0)
        self.assertGreater(summary["weapons"], 0)
        self.assertGreater(summary["abilities"], 0)
        self.assertGreater(summary["points_used"], 0)

    def test_import_route_creates_records(self):
        data = load_sample_roster_json()
        parsed = BattlescribeParser(data).parse()
        partner = self.env.user.partner_id
        roster = self.env["wh40k.roster"].action_import_parsed(partner, parsed)
        self.assertTrue(roster.id)
        self.assertGreater(roster.unit_count, 0)
        self.assertGreater(roster.weapon_count, 0)
        self.assertGreater(roster.ability_count, 0)
        self.assertGreater(roster.points_used, 0)

    def test_roster_detail_blocks_strangers(self):
        partner = self.env.user.partner_id
        roster = self.env["wh40k.roster"].create(
            {
                "name": "Secret Army",
                "partner_id": partner.id,
                "points_used": 100,
            }
        )
        other = self.env["res.partner"].create({"name": "Other Player"})
        with self.assertRaises(AccessError):
            roster.to_detail_dict(other)

    def test_malformed_json_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            BattlescribeParser("{not-json")
        with self.assertRaises(ValueError):
            BattlescribeParser([1, 2, 3])

    def test_missing_text_falls_back_to_value(self):
        data = minimal_roster_json(wounds_text=None, wounds_fallback="3")
        # Ensure characteristic has value but no $text
        chars = data["roster"]["forces"][0]["selections"][1]["profiles"][0]["characteristics"]
        wound = next(c for c in chars if c["name"] == "W")
        self.assertNotIn("$text", wound)
        self.assertEqual(wound["value"], "3")
        parsed = BattlescribeParser(data).parse()
        model = parsed["forces"][0]["detachments"][0]["units"][0]["models"][0]
        self.assertEqual(model["wounds"], "3")
        # Movement uses value-only in fixture
        self.assertEqual(model["movement"], '6"')

    def test_nested_weapons_and_abilities(self):
        data = minimal_roster_json(with_nested_weapon=True)
        parsed = BattlescribeParser(data).parse()
        unit = parsed["forces"][0]["detachments"][0]["units"][0]
        self.assertTrue(unit["abilities"])
        self.assertEqual(unit["abilities"][0]["name"], "Mob Rule")
        weapons = unit["models"][0]["weapons"]
        self.assertTrue(weapons)
        self.assertEqual(weapons[0]["name"], "Slugga")
        self.assertEqual(weapons[0]["weapon_type"], "ranged")
        preview = BattlescribeParser(data).preview()
        self.assertEqual(preview["faction"], "Orks")
        self.assertIn("Boyz", preview["units"])

    def test_empty_forces(self):
        data = minimal_roster_json(empty_forces=True)
        parsed = BattlescribeParser(data).parse()
        self.assertEqual(parsed["forces"], [])
        summary = BattlescribeParser(data).summary()
        self.assertEqual(summary["units"], 0)
        self.assertEqual(summary["models"], 0)
        preview = BattlescribeParser(data).preview()
        self.assertEqual(preview["unit_count"], 0)

    def test_import_rejects_invalid_payload(self):
        partner = self.env.user.partner_id
        with self.assertRaises(UserError):
            self.env["wh40k.roster"].action_import_parsed(partner, {})
        with self.assertRaises(UserError):
            self.env["wh40k.roster"].action_import_parsed(False, {"name": "X"})
