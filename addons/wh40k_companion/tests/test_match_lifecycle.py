from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from .common import Wh40kPlayerMixin


@tagged("post_install", "-at_install", "wh40k")
class TestWh40kMatchLifecycle(Wh40kPlayerMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_wh40k_players()

    def test_create_publish_accept_join_cancel(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host L")
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest L")
        match = (
            self.env["wh40k.match"]
            .with_user(self.user_a)
            .action_create_for_host(
                self.user_a.partner_id, host_roster, self.mission, "2000"
            )
        )
        self.assertEqual(match.state, "draft")
        self.assertTrue(match.match_token)
        match.with_user(self.user_a).action_publish()
        self.assertEqual(match.state, "waiting")
        self.assertTrue(match.published_at)

        verified = match.with_user(self.user_b).find_by_token(match.match_token)
        payload = verified.to_verify_dict()
        self.assertEqual(payload["host"]["nickname"], self.user_a.partner_id.wh40k_nickname)

        match.with_user(self.user_b).action_accept_invite(self.user_b.partner_id)
        self.assertEqual(match.state, "selecting")
        eligible = match.to_eligible_rosters_dict(self.user_b.partner_id)
        self.assertTrue(any(r["id"] == guest_roster.id for r in eligible["rosters"]))

        match.with_user(self.user_b).action_join(self.user_b.partner_id, guest_roster)
        self.assertEqual(match.state, "active")

        # New draft for cancel path
        draft = (
            self.env["wh40k.match"]
            .with_user(self.user_a)
            .action_create_for_host(
                self.user_a.partner_id, host_roster, self.mission, "1000"
            )
        )
        draft.with_user(self.user_a).action_publish()
        draft.with_user(self.user_a).action_cancel(reason="Host left")
        self.assertEqual(draft.state, "cancelled")
        self.assertEqual(draft.cancel_reason, "Host left")

    def test_surrender_and_partner_stats(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host S")
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest S")
        match = self._activate_match(
            self.user_a, self.user_b, host_roster, guest_roster
        )
        host_wins = self.user_a.partner_id.wh40k_wins
        guest_losses = self.user_b.partner_id.wh40k_losses
        match.with_user(self.user_b).action_surrender(self.user_b.partner_id)
        self.assertEqual(match.state, "finished")
        self.assertEqual(match.winner_id, self.user_a.partner_id)
        self.user_a.partner_id.invalidate_recordset()
        self.user_b.partner_id.invalidate_recordset()
        self.assertEqual(self.user_a.partner_id.wh40k_wins, host_wins + 1)
        self.assertEqual(self.user_b.partner_id.wh40k_losses, guest_losses + 1)
        result = match.to_surrender_result_dict(self.user_b.partner_id)
        self.assertTrue(result["you_surrendered"])
        self.assertFalse(result["you_won"])

    def test_stranger_blocked_from_lifecycle(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host X")
        match = self._publish_match(self.user_a, host_roster)
        # Stranger cannot search waiting match
        self.assertFalse(
            self.env["wh40k.match"]
            .with_user(self.user_stranger)
            .search([("id", "=", match.id)])
        )
        # After B accepts, stranger cannot accept / join
        match.with_user(self.user_b).action_accept_invite(self.user_b.partner_id)
        with self.assertRaises(UserError):
            match.with_user(self.user_stranger).action_accept_invite(
                self.user_stranger.partner_id
            )
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest X")
        with self.assertRaises(UserError):
            match.with_user(self.user_stranger).action_join(
                self.user_stranger.partner_id, guest_roster
            )
        # State DTO blocked for stranger
        with self.assertRaises(AccessError):
            match.to_state_dict(self.user_stranger.partner_id)

    def test_point_limit_eligible_rosters(self):
        host_roster = self._make_tiny_roster(
            self.user_a, name="Host Pts", points_used=900, points_limit=1000
        )
        ok = self._make_tiny_roster(
            self.user_b, name="Fits", points_used=800, points_limit=1000
        )
        too_big = self._make_tiny_roster(
            self.user_b, name="TooBig", points_used=1500, points_limit=2000
        )
        match = self._publish_match(self.user_a, host_roster, points="1000")
        match.with_user(self.user_b).action_accept_invite(self.user_b.partner_id)
        eligible_ids = {r.id for r in match.eligible_rosters_for(self.user_b.partner_id)}
        self.assertIn(ok.id, eligible_ids)
        self.assertNotIn(too_big.id, eligible_ids)
        with self.assertRaises(ValidationError):
            match.with_user(self.user_b).action_join(self.user_b.partner_id, too_big)

    def test_stale_waiting_cron(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host Cron")
        match = self._publish_match(self.user_a, host_roster)
        # Backdate published_at beyond timeout
        match.sudo().write(
            {
                "published_at": fields.Datetime.now()
                - timedelta(minutes=match.WAITING_TIMEOUT_MINUTES + 1)
            }
        )
        self.env["wh40k.match"].cron_cancel_stale_waiting()
        match.invalidate_recordset()
        self.assertEqual(match.state, "cancelled")
        self.assertEqual(match.cancel_reason, "Waiting timeout expired")

    def test_host_cannot_join_as_guest(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host Self")
        match = self._publish_match(self.user_a, host_roster)
        with self.assertRaises(UserError):
            match.with_user(self.user_a).action_accept_invite(self.user_a.partner_id)
