from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

from .common import Wh40kPlayerMixin


@tagged("post_install", "-at_install", "wh40k")
class TestWh40kRosterModel(Wh40kPlayerMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_wh40k_players()

    def test_import_and_compute_counts(self):
        roster = self._import_minimal(self.user_a, name="Count Army", points=150)
        self.assertEqual(roster.partner_id, self.user_a.partner_id)
        self.assertEqual(roster.points_used, 150)
        count_field = self.env["wh40k.roster"]._fields["weapon_count"]
        self.assertTrue(count_field.store)
        self.assertTrue(self.env["wh40k.roster"]._fields["unit_count"].store)
        self.assertTrue(self.env["wh40k.roster"]._fields["ability_count"].store)
        self.assertTrue(any("weapon_ids" in dep for dep in count_field.depends))
        self.assertGreaterEqual(roster.unit_count, 1)
        self.assertGreaterEqual(roster.weapon_count, 1)
        self.assertGreaterEqual(roster.ability_count, 1)
        # Adding a model weapon bumps the stored count via @api.depends.
        unit = roster.force_ids.detachment_ids.unit_ids[:1]
        model = unit.model_ids[:1]
        before = roster.weapon_count
        self.env["wh40k.weapon"].with_user(self.user_a).create(
            {
                "name": "Choppa",
                "model_id": model.id,
                "weapon_type": "melee",
            }
        )
        self.assertEqual(roster.weapon_count, before + 1)

    def test_owner_acl_blocks_other_player(self):
        roster_a = self._make_tiny_roster(self.user_a, name="A Only")
        env_b = self.env["wh40k.roster"].with_user(self.user_b)
        self.assertFalse(env_b.search([("id", "=", roster_a.id)]))
        with self.assertRaises(AccessError):
            roster_a.with_user(self.user_b).read(["name"])

    def test_detail_owner_vs_participant_vs_stranger(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host Detail")
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest Detail")
        # Owner OK
        detail = host_roster.with_user(self.user_a).to_detail_dict(self.user_a.partner_id)
        self.assertEqual(detail["id"], host_roster.id)
        self.assertTrue(detail["units"])
        # Stranger blocked before match
        with self.assertRaises(AccessError):
            host_roster.check_detail_access(self.user_b.partner_id)
        # After join, guest (participant) may see host roster detail
        match = self._activate_match(
            self.user_a, self.user_b, host_roster, guest_roster
        )
        self.assertEqual(match.state, "active")
        host_roster.check_detail_access(self.user_b.partner_id)
        as_guest = host_roster.to_detail_dict(self.user_b.partner_id)
        self.assertEqual(as_guest["id"], host_roster.id)
        # Unrelated player still blocked
        with self.assertRaises(AccessError):
            host_roster.check_detail_access(self.user_stranger.partner_id)

    def test_owner_rename_and_delete(self):
        roster = self._make_tiny_roster(self.user_a, name="Rename Me")
        renamed = roster.with_user(self.user_a).rename_for_owner(
            self.user_a.partner_id, "  New Name  "
        )
        self.assertEqual(renamed["name"], "New Name")
        self.assertEqual(roster.name, "New Name")
        with self.assertRaises(UserError):
            roster.rename_for_owner(self.user_a.partner_id, "   ")
        self.assertEqual(roster.name, "New Name")
        with self.assertRaises(AccessError):
            roster.unlink_for_owner(self.user_b.partner_id)
        with self.assertRaises(AccessError):
            roster.rename_for_owner(self.user_b.partner_id, "Stolen")
        self.assertEqual(roster.name, "New Name")
        self.assertTrue(roster.exists())
        roster.with_user(self.user_a).unlink_for_owner(self.user_a.partner_id)
        self.assertFalse(roster.exists())

    def test_cannot_delete_roster_used_in_match(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Locked Host")
        guest_roster = self._make_tiny_roster(self.user_b, name="Locked Guest")
        self._activate_match(self.user_a, self.user_b, host_roster, guest_roster)
        with self.assertRaises(UserError):
            host_roster.with_user(self.user_a).unlink_for_owner(self.user_a.partner_id)
        self.assertTrue(host_roster.exists())
        self.assertEqual(host_roster.name, "Locked Host")
