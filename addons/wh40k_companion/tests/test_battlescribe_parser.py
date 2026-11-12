import json
from pathlib import Path

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase

from odoo.addons.wh40k_companion.parsers.battlescribe_parser import BattlescribeParser


class TestBattlescribeParser(TransactionCase):
    def test_parse_aufychi_sample(self):
        sample = Path(__file__).resolve().parents[1] / "testdata" / "aufychi.json"
        data = json.loads(sample.read_text(encoding="utf-8"))
        parser = BattlescribeParser(data)
        summary = parser.summary()
        self.assertGreater(summary["units"], 0)
        self.assertGreater(summary["models"], 0)
        self.assertGreater(summary["weapons"], 0)
        self.assertGreater(summary["abilities"], 0)
        self.assertGreater(summary["points_used"], 0)

    def test_import_route_creates_records(self):
        sample = Path(__file__).resolve().parents[1] / "testdata" / "aufychi.json"
        data = json.loads(sample.read_text(encoding="utf-8"))
        parser = BattlescribeParser(data)
        parsed = parser.parse()
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
