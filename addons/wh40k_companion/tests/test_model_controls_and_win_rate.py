"""Win rate ignores draws. One miniature's wounds roll up to the squad."""

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged

from .common import Wh40kPlayerMixin


@tagged("post_install", "-at_install", "wh40k")
class TestWh40kModelControlsAndWinRate(Wh40kPlayerMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_wh40k_players()

    def test_win_rate_ignores_draws(self):
        partner = self.user_a.partner_id
        partner.sudo().write({"wh40k_wins": 2, "wh40k_losses": 2, "wh40k_draws": 6})
        partner.invalidate_recordset()
        self.assertEqual(partner.wh40k_wins, 2)
        self.assertEqual(partner.wh40k_losses, 2)
        self.assertEqual(partner.wh40k_draws, 6)
        self.assertEqual(partner.wh40k_total_match, 10)
        # 2 / (2 + 2), not 2 / 10.
        self.assertAlmostEqual(partner.wh40k_win_rate, 50.0)

        partner.sudo().write({"wh40k_wins": 1, "wh40k_losses": 0, "wh40k_draws": 5})
        partner.invalidate_recordset()
        self.assertEqual(partner.wh40k_total_match, 6)
        self.assertAlmostEqual(partner.wh40k_win_rate, 100.0)

        partner.sudo().write({"wh40k_wins": 0, "wh40k_losses": 0, "wh40k_draws": 4})
        partner.invalidate_recordset()
        self.assertEqual(partner.wh40k_total_match, 4)
        self.assertAlmostEqual(partner.wh40k_win_rate, 0.0)
        dash = partner.get_wh40k_dashboard()
        self.assertEqual(dash["player"]["draws"], 4)
        self.assertEqual(dash["player"]["wins"], 0)
        self.assertEqual(dash["player"]["losses"], 0)
        self.assertAlmostEqual(dash["player"]["win_rate"], 0.0)

    def test_single_model_squad_has_one_row(self):
        host = self._make_tiny_roster(self.user_a, name="One Host")
        guest = self._make_tiny_roster(self.user_b, name="One Guest")
        model = guest.force_ids.detachment_ids.unit_ids.model_ids[:1]
        model.sudo().write({"quantity": 1, "wounds": "6", "name": "Warboss"})
        match = self._activate_match(self.user_a, self.user_b, host, guest)
        line = match.unit_line_ids.filtered(lambda item: item.side == "guest")[:1]
        rows = line.model_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Warboss")
        self.assertEqual(line.models, 1)
        self.assertEqual(line.wounds, 6)
        self.assertEqual(line.models_remaining, 1)
        self.assertEqual(line.wounds_remaining, 6)

    def test_model_wound_and_destroy_roll_up_to_squad(self):
        host = self._make_tiny_roster(self.user_a, name="Roll Host")
        guest = self._make_tiny_roster(self.user_b, name="Roll Guest")
        match = self._activate_match(self.user_a, self.user_b, host, guest)
        guest_line = match.unit_line_ids.filtered(lambda item: item.side == "guest")[:1]
        host_line = match.unit_line_ids.filtered(lambda item: item.side == "host")[:1]
        # Tiny roster model is quantity 2, wounds 2 → squad M 2, W 4, two rows.
        self.assertEqual(guest_line.models, 2)
        self.assertEqual(guest_line.wounds, 4)
        rows = guest_line.model_rows()
        self.assertEqual(len(rows), 2)
        key = rows[0]["key"]
        other_key = rows[1]["key"]

        with self.assertRaises(AccessError):
            match.with_user(self.user_stranger).action_apply_wound_delta(
                {
                    "line_id": guest_line.id,
                    "unit_id": guest_line.unit_id.id,
                    "side": "guest",
                    "model_key": key,
                    "op": "wounds",
                    "delta": -1,
                },
                updating_partner=self.user_stranger.partner_id,
            )
        guest_line.invalidate_recordset()
        self.assertEqual(guest_line.wounds_remaining, 4)
        self.assertEqual(guest_line.models_remaining, 2)

        # Host wounds one enemy miniature. Squad M stays, squad W drops by 1.
        match.with_user(self.user_a).action_apply_wound_delta(
            {
                "line_id": guest_line.id,
                "unit_id": guest_line.unit_id.id,
                "side": "guest",
                "model_key": key,
                "op": "wounds",
                "delta": -1,
            },
            updating_partner=self.user_a.partner_id,
        )
        guest_line.invalidate_recordset()
        self.assertEqual(guest_line.models_remaining, 2)
        self.assertEqual(guest_line.wounds_remaining, 3)
        self.assertFalse(guest_line.destroyed)
        wounded = {row["key"]: row for row in guest_line.model_rows()}
        self.assertEqual(wounded[key]["wounds_remaining"], 1)
        self.assertEqual(wounded[key]["models_remaining"], 1)
        self.assertEqual(wounded[other_key]["wounds_remaining"], 2)
        self.assertFalse(wounded[key]["destroyed"])

        # Guest destroys that same miniature. Squad loses the model and its remaining wound.
        match.with_user(self.user_b).action_apply_wound_delta(
            {
                "line_id": guest_line.id,
                "unit_id": guest_line.unit_id.id,
                "side": "guest",
                "model_key": key,
                "op": "destroy",
            },
            updating_partner=self.user_b.partner_id,
        )
        guest_line.invalidate_recordset()
        self.assertEqual(guest_line.models_remaining, 1)
        self.assertEqual(guest_line.wounds_remaining, 2)
        self.assertFalse(guest_line.destroyed)
        destroyed = {row["key"]: row for row in guest_line.model_rows()}
        self.assertTrue(destroyed[key]["destroyed"])
        self.assertEqual(destroyed[key]["models_remaining"], 0)
        self.assertEqual(destroyed[key]["wounds_remaining"], 0)
        self.assertEqual(destroyed[other_key]["models_remaining"], 1)
        self.assertEqual(destroyed[other_key]["wounds_remaining"], 2)

        # Undo restores the miniature and the squad totals from before the kill.
        match.with_user(self.user_a).action_apply_wound_delta(
            {
                "line_id": guest_line.id,
                "unit_id": guest_line.unit_id.id,
                "side": "guest",
                "model_key": key,
                "op": "undo",
            },
            updating_partner=self.user_a.partner_id,
        )
        guest_line.invalidate_recordset()
        self.assertEqual(guest_line.models_remaining, 2)
        self.assertEqual(guest_line.wounds_remaining, 3)
        restored = {row["key"]: row for row in guest_line.model_rows()}
        self.assertFalse(restored[key]["destroyed"])
        self.assertEqual(restored[key]["wounds_remaining"], 1)
        self.assertEqual(restored[key]["models_remaining"], 1)

        # The other player can do the same to the host's models.
        host_key = host_line.model_rows()[0]["key"]
        match.with_user(self.user_b).action_apply_wound_delta(
            {
                "line_id": host_line.id,
                "unit_id": host_line.unit_id.id,
                "side": "host",
                "model_key": host_key,
                "op": "models",
                "delta": -1,
            },
            updating_partner=self.user_b.partner_id,
        )
        host_line.invalidate_recordset()
        self.assertEqual(host_line.models_remaining, 1)
        self.assertEqual(host_line.wounds_remaining, 2)
        host_rows = {row["key"]: row for row in host_line.model_rows()}
        self.assertTrue(host_rows[host_key]["destroyed"])
        self.assertEqual(host_rows[host_key]["models_remaining"], 0)
        self.assertEqual(host_rows[host_key]["wounds_remaining"], 0)
