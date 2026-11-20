"""Import binding and own/opponent stratagem payloads."""

from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.wh40k_companion.catalogues import stratagems as stratagems_mod
from odoo.addons.wh40k_companion.catalogues.stratagems import (
    NO_DECK_MESSAGE,
    resolve_stratagem_deck,
)
from odoo.addons.wh40k_companion.parsers.battlescribe_parser import BattlescribeParser

from .common import Wh40kPlayerMixin, load_sample_roster_json, minimal_roster_json


SAMPLE_TEXT = "Test rules text."
SAMPLE_CATALOGUE = {
    ("Orks", "Waaaagh! Tribe"): [
        {
            "name": "Get Stuck In",
            "cp": 1,
            "when": "Fight phase",
            "target": "One friendly unit",
            "rules": SAMPLE_TEXT,
        }
    ]
}


@tagged("post_install", "-at_install", "wh40k")
class TestStratagemDeck(Wh40kPlayerMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_wh40k_players()

    def test_import_binds_selected_detachment_names(self):
        parsed = BattlescribeParser(load_sample_roster_json()).parse()
        roster = self.env["wh40k.roster"].action_import_parsed(
            self.user_a.partner_id, parsed
        )
        self.assertEqual(
            roster.detachment_name.splitlines(),
            [
                "Saga of the Beastslayer",
                "Assault Brethren",
                "Stormlance Task Force",
            ],
        )
        stored_rules = " ".join(
            (
                roster.force_ids.army_rule_ids | roster.force_ids.detachment_ids.detachment_rule_ids
            ).mapped("description")
        )
        detail = roster.to_detail_dict(self.user_a.partner_id)
        self.assertEqual(detail["stratagems"], [])
        self.assertEqual(detail["stratagem_message"], NO_DECK_MESSAGE)
        self.assertNotIn(NO_DECK_MESSAGE, stored_rules)

    def test_unknown_detachment_imports_with_empty_deck(self):
        data = minimal_roster_json(name="Unknown Detachment Army")
        child = data["roster"]["forces"][0]["selections"][0]["selections"][0]
        child["name"] = "Nope Detachment"
        child["number"] = 1
        parsed = BattlescribeParser(data).parse()
        roster = (
            self.env["wh40k.roster"]
            .with_user(self.user_a)
            .action_import_parsed(self.user_a.partner_id, parsed)
        )
        self.assertTrue(roster.id)
        self.assertEqual(roster.detachment_name, "Nope Detachment")
        detail = roster.to_detail_dict(self.user_a.partner_id)
        self.assertEqual(detail["stratagems"], [])
        self.assertEqual(detail["stratagem_message"], "no deck for this detachment")
        self.assertEqual(
            resolve_stratagem_deck(roster._detachment_catalogue_pairs())["missing"][0][
                "detachment"
            ],
            "Nope Detachment",
        )

    def test_own_and_opponent_receive_stratagem_text(self):
        host = self._import_minimal(self.user_a, name="Host Orks")
        guest = self._import_minimal(self.user_b, name="Guest Orks")
        self.assertEqual(host.detachment_name, "Waaaagh! Tribe")
        self.assertEqual(guest.detachment_name, "Waaaagh! Tribe")
        self._activate_match(self.user_a, self.user_b, host, guest)
        with patch.dict(stratagems_mod.STRATAGEM_CATALOGUE, SAMPLE_CATALOGUE, clear=False):
            own = host.to_detail_dict(self.user_a.partner_id)
            as_opponent = host.to_detail_dict(self.user_b.partner_id)
            opponent_roster = guest.to_detail_dict(self.user_a.partner_id)
        for payload in (own, as_opponent, opponent_roster):
            self.assertEqual(payload["stratagem_message"], "")
            self.assertEqual(len(payload["stratagems"]), 1)
            row = payload["stratagems"][0]
            self.assertEqual(row["name"], "Get Stuck In")
            self.assertEqual(row["cp"], 1)
            self.assertIn(SAMPLE_TEXT, row["rules"])
        stored = " ".join((host.force_ids.detachment_ids.detachment_rule_ids).mapped("description"))
        self.assertNotIn(SAMPLE_TEXT, host.detachment_name or "")
        self.assertNotIn(SAMPLE_TEXT, stored)
