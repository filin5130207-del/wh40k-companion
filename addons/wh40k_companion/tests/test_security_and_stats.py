from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from .common import Wh40kPlayerMixin


@tagged("post_install", "-at_install", "wh40k")
class TestWh40kSecurityAndStats(Wh40kPlayerMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_wh40k_players()

    def test_player_readonly_missions_manager_can_write(self):
        mission = self.mission
        with self.assertRaises(AccessError):
            mission.with_user(self.user_a).write({"name": "Hacked by player"})
        mission.with_user(self.user_manager).write({"name": "Managed Mission"})
        self.assertEqual(mission.name, "Managed Mission")

    def test_manager_can_read_foreign_roster_and_match(self):
        roster = self._make_tiny_roster(self.user_a, name="Mgr Sees")
        match = self._publish_match(self.user_a, roster)
        found_roster = (
            self.env["wh40k.roster"]
            .with_user(self.user_manager)
            .search([("id", "=", roster.id)])
        )
        self.assertTrue(found_roster)
        found_match = (
            self.env["wh40k.match"]
            .with_user(self.user_manager)
            .search([("id", "=", match.id)])
        )
        self.assertTrue(found_match)
        # Manager group implies player; token/legacy JSON are form-groups only,
        # but fields themselves remain readable via ORM for managers.
        self.assertTrue(found_match.match_token)
        self.assertIsNotNone(found_match.unit_state)

    def test_find_by_token_does_not_leak_stranger_mutations(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Token Host")
        match = self._publish_match(self.user_a, host_roster)
        token = match.match_token
        found = self.env["wh40k.match"].with_user(self.user_stranger).find_by_token(token)
        self.assertEqual(found.id, match.id)
        # Direct write still blocked by ACL until guest seat claimed via actions
        with self.assertRaises(AccessError):
            found.with_user(self.user_stranger).write({"state": "active"})

    def test_partner_stats_compute(self):
        partner = self.user_a.partner_id
        partner.sudo().write({"wh40k_wins": 3, "wh40k_losses": 1})
        partner.invalidate_recordset()
        self.assertEqual(partner.wh40k_total_match, 4)
        self.assertAlmostEqual(partner.wh40k_win_rate, 75.0)
        partner.sudo().action_wh40k_record_result(won=True)
        self.assertEqual(partner.wh40k_wins, 4)

    def test_dashboard_payload(self):
        self._make_tiny_roster(self.user_a, name="Dash Roster")
        dash = self.user_a.partner_id.get_wh40k_dashboard(pending_join_token="abc")
        self.assertEqual(dash["player"]["nickname"], self.user_a.partner_id.wh40k_nickname)
        self.assertEqual(dash["pending_join_token"], "abc")
        self.assertTrue(dash["rosters"])
        self.assertIsNone(dash["active_match"])
