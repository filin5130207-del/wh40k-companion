"""Own-unit characteristics, host-cancel payload, and draw results."""

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

from .common import Wh40kPlayerMixin

PROFILE_FIELDS = ("M", "T", "Sv", "W", "LD", "OC", "InSv")


@tagged("post_install", "-at_install", "wh40k")
class TestWh40kDrawAndUnitProfiles(Wh40kPlayerMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_wh40k_players()

    def _stamp_model(self, roster, **vals):
        model = roster.force_ids.detachment_ids.unit_ids.model_ids[:1]
        model.sudo().write(vals)
        return model

    def test_own_unit_payload_matches_opponent_characteristics(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host Chars")
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest Chars")
        self._stamp_model(
            host_roster,
            movement='6"',
            toughness="5",
            save="3+",
            wounds="4",
            leadership="6+",
            objective_control="2",
            invuln_save="4+",
        )
        self._stamp_model(
            guest_roster,
            movement='5"',
            toughness="4",
            save="5+",
            wounds="1",
            leadership="7+",
            objective_control="1",
            invuln_save="",
        )
        match = self._activate_match(
            self.user_a, self.user_b, host_roster, guest_roster
        )
        host_view = match.to_state_dict(self.user_a.partner_id)
        guest_view = match.to_state_dict(self.user_b.partner_id)
        own = host_view["unit_state"]["host"][0]
        opponent = host_view["unit_state"]["guest"][0]
        self.assertIn("profiles", own)
        self.assertIn("profiles", opponent)
        self.assertTrue(own["profiles"])
        self.assertTrue(opponent["profiles"])
        self.assertEqual(set(own["profiles"][0]), set(opponent["profiles"][0]))
        for field in PROFILE_FIELDS:
            self.assertIn(field, own["profiles"][0])
            self.assertIn(field, opponent["profiles"][0])
        self.assertEqual(own["profiles"][0]["T"], "5")
        self.assertEqual(own["profiles"][0]["Sv"], "3+")
        self.assertEqual(own["profiles"][0]["W"], "4")
        self.assertEqual(opponent["profiles"][0]["T"], "4")
        self.assertEqual(opponent["profiles"][0]["Sv"], "5+")
        self.assertEqual(opponent["profiles"][0]["W"], "1")
        guest_own = guest_view["unit_state"]["guest"][0]
        self.assertEqual(set(guest_own["profiles"][0]), set(opponent["profiles"][0]))
        self.assertEqual(guest_own["profiles"][0]["T"], "4")
        # Wound deltas stay a line snapshot. Characteristics ride the full state.
        host_line = match.unit_line_ids.filtered(lambda line: line.side == "host")[:1]
        self.assertNotIn("profiles", host_line.to_state_entry())

    def test_host_cancel_payload_leaves_the_waiting_screen(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host Cancel")
        match = self._publish_match(self.user_a, host_roster)
        match.with_user(self.user_a).action_cancel(reason="Cancelled by host")
        payload = match.to_state_dict(self.user_a.partner_id)
        self.assertEqual(payload["state"], "cancelled")
        self.assertEqual(payload["cancel_reason"], "Cancelled by host")
        self.assertFalse(payload["match_token"])
        self.assertFalse(payload["join_url"])

        selecting = self._publish_match(self.user_a, host_roster)
        selecting.with_user(self.user_b).action_accept_invite(self.user_b.partner_id)
        selecting.with_user(self.user_a).action_cancel(reason="Cancelled by host")
        guest_view = selecting.to_state_dict(self.user_b.partner_id)
        self.assertEqual(guest_view["state"], "cancelled")
        self.assertFalse(guest_view["match_token"])
        self.assertNotIn("timeout", (guest_view["cancel_reason"] or "").lower())

    def test_draw_is_a_persisted_terminal_result(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host Draw")
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest Draw")
        match = self._activate_match(
            self.user_a, self.user_b, host_roster, guest_roster
        )
        host = self.user_a.partner_id
        guest = self.user_b.partner_id
        wins_h, losses_h, draws_h = host.wh40k_wins, host.wh40k_losses, host.wh40k_draws
        wins_g, losses_g, draws_g = guest.wh40k_wins, guest.wh40k_losses, guest.wh40k_draws

        with self.assertRaises(AccessError):
            match.with_user(self.user_stranger).action_draw(
                self.user_stranger.partner_id
            )
        self.assertEqual(match.state, "active")

        match.with_user(self.user_b).action_draw(guest)
        self.assertEqual(match.state, "finished")
        self.assertEqual(match.result, "draw")
        self.assertFalse(match.winner_id)
        self.assertTrue(match.finished_at)
        host.invalidate_recordset()
        guest.invalidate_recordset()
        self.assertEqual(host.wh40k_draws, draws_h + 1)
        self.assertEqual(guest.wh40k_draws, draws_g + 1)
        self.assertEqual(host.wh40k_wins, wins_h)
        self.assertEqual(guest.wh40k_wins, wins_g)
        self.assertEqual(host.wh40k_losses, losses_h)
        self.assertEqual(guest.wh40k_losses, losses_g)
        self.assertEqual(host.wh40k_total_match, wins_h + losses_h + draws_h + 1)
        self.assertEqual(guest.wh40k_total_match, wins_g + losses_g + draws_g + 1)

        host_view = match.to_state_dict(host)
        guest_view = match.to_state_dict(guest)
        self.assertEqual(host_view["result"], "draw")
        self.assertEqual(host_view["you_result"], "draw")
        self.assertEqual(guest_view["you_result"], "draw")
        self.assertFalse(host_view["winner_id"])
        drawn = match.to_draw_result_dict(host)
        self.assertTrue(drawn["is_draw"])
        self.assertEqual(drawn["you_result"], "draw")
        self.assertFalse(drawn["you_won"])

        with self.assertRaises(UserError):
            match.with_user(self.user_a).action_draw(host)

    def test_host_can_record_draw_and_surrender_is_not_a_draw(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host Draw 2")
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest Draw 2")
        drawn = self._activate_match(
            self.user_a, self.user_b, host_roster, guest_roster
        )
        before = self.user_a.partner_id.wh40k_draws
        drawn.with_user(self.user_a).action_draw(self.user_a.partner_id)
        self.user_a.partner_id.invalidate_recordset()
        self.assertEqual(drawn.result, "draw")
        self.assertEqual(self.user_a.partner_id.wh40k_draws, before + 1)

        host_roster_s = self._make_tiny_roster(self.user_a, name="Host Sur")
        guest_roster_s = self._make_tiny_roster(self.user_b, name="Guest Sur")
        surrendered = self._activate_match(
            self.user_a, self.user_b, host_roster_s, guest_roster_s
        )
        draws_before = self.user_b.partner_id.wh40k_draws
        surrendered.with_user(self.user_b).action_surrender(self.user_b.partner_id)
        self.assertEqual(surrendered.result, "surrender")
        self.assertEqual(surrendered.winner_id, self.user_a.partner_id)
        result = surrendered.to_surrender_result_dict(self.user_b.partner_id)
        self.assertEqual(result["you_result"], "surrender")
        self.assertEqual(
            surrendered.you_result_for(self.user_a.partner_id),
            "win",
        )
        self.user_b.partner_id.invalidate_recordset()
        self.assertEqual(self.user_b.partner_id.wh40k_draws, draws_before)
