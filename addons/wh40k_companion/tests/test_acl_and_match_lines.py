import json
from pathlib import Path

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.wh40k_companion.parsers.battlescribe_parser import BattlescribeParser


@tagged("post_install", "-at_install", "wh40k")
class TestWh40kAclAndUnitLines(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = cls.env.ref("wh40k_companion.group_player")
        Users = cls.env["res.users"].with_context(no_reset_password=True)
        cls.user_a = Users.create(
            {
                "name": "Player A",
                "login": "wh40k_player_a@example.com",
                "email": "wh40k_player_a@example.com",
                "group_ids": [(6, 0, [group.id])],
            }
        )
        cls.user_b = Users.create(
            {
                "name": "Player B",
                "login": "wh40k_player_b@example.com",
                "email": "wh40k_player_b@example.com",
                "group_ids": [(6, 0, [group.id])],
            }
        )
        cls.user_a.partner_id.wh40k_nickname = "AlphaHost"
        cls.user_b.partner_id.wh40k_nickname = "BetaGuest"
        cls.mission = cls.env["wh40k.mission"].create(
            {"name": "ACL Test Mission", "sequence": 1}
        )

    def _import_sample(self, user):
        sample = Path(__file__).resolve().parents[1] / "testdata" / "aufychi.json"
        data = json.loads(sample.read_text(encoding="utf-8"))
        parsed = BattlescribeParser(data).parse()
        return (
            self.env["wh40k.roster"]
            .with_user(user)
            .action_import_parsed(user.partner_id, parsed)
        )

    def test_player_cannot_read_foreign_roster(self):
        roster_a = self.env["wh40k.roster"].create(
            {
                "name": "A Army",
                "partner_id": self.user_a.partner_id.id,
                "points_used": 500,
            }
        )
        env_b = self.env["wh40k.roster"].with_user(self.user_b)
        self.assertFalse(env_b.search([("id", "=", roster_a.id)]))
        with self.assertRaises(AccessError):
            roster_a.with_user(self.user_b).check_detail_access(self.user_b.partner_id)

    def test_match_acl_host_guest_and_stranger(self):
        roster_a = self.env["wh40k.roster"].create(
            {
                "name": "Host list",
                "partner_id": self.user_a.partner_id.id,
                "points_used": 1000,
                "points_limit": 2000,
            }
        )
        match = (
            self.env["wh40k.match"]
            .with_user(self.user_a)
            .action_create_for_host(
                self.user_a.partner_id, roster_a, self.mission, "2000"
            )
        )
        match.with_user(self.user_a).action_publish()
        # Stranger cannot see waiting match via ACL domain.
        self.assertFalse(
            self.env["wh40k.match"].with_user(self.user_b).search([("id", "=", match.id)])
        )
        # Direct guest write without method checks stays blocked (not yet guest).
        with self.assertRaises(AccessError):
            match.with_user(self.user_b).write({"state": "selecting"})
        # Token capability still works.
        found = self.env["wh40k.match"].with_user(self.user_b).find_by_token(match.match_token)
        self.assertEqual(found.id, match.id)
        # Accept must work as the real guest user (no ambient sudo): method
        # elevates only after host/seat checks so strangers stay blocked.
        found.with_user(self.user_b).action_accept_invite(self.user_b.partner_id)
        self.assertEqual(found.guest_id, self.user_b.partner_id)
        # After accept, guest can search the match.
        self.assertTrue(
            self.env["wh40k.match"].with_user(self.user_b).search([("id", "=", match.id)])
        )

    def test_unit_lines_created_on_join_and_update_own_side(self):
        roster_a = self._import_sample(self.user_a)
        # Shrink points for faster fixture if needed
        if roster_a.points_used > 2000:
            roster_a.points_used = 2000
        roster_b = self.env["wh40k.roster"].with_user(self.user_b).create(
            {
                "name": "Guest tiny",
                "partner_id": self.user_b.partner_id.id,
                "points_used": 100,
                "points_limit": 2000,
            }
        )
        # Minimal unit tree for guest so join builds guest lines.
        force = self.env["wh40k.force"].with_user(self.user_b).create(
            {"name": "Force B", "roster_id": roster_b.id}
        )
        det = self.env["wh40k.detachment"].with_user(self.user_b).create(
            {"name": "Det B", "force_id": force.id}
        )
        unit = self.env["wh40k.unit"].with_user(self.user_b).create(
            {"name": "Boyz", "detachment_id": det.id, "quantity": 1}
        )
        self.env["wh40k.model"].with_user(self.user_b).create(
            {
                "name": "Boy",
                "unit_id": unit.id,
                "quantity": 1,
                "wounds": "1",
            }
        )

        match = (
            self.env["wh40k.match"]
            .with_user(self.user_a)
            .action_create_for_host(
                self.user_a.partner_id, roster_a, self.mission, "2000"
            )
        )
        match.with_user(self.user_a).action_publish()
        match.with_user(self.user_b).action_accept_invite(self.user_b.partner_id)
        match.with_user(self.user_b).action_join(self.user_b.partner_id, roster_b)
        self.assertEqual(match.state, "active")
        self.assertTrue(match.unit_line_ids)
        self.assertTrue(any(l.side == "host" for l in match.unit_line_ids))
        self.assertTrue(any(l.side == "guest" for l in match.unit_line_ids))

        guest_line = match.unit_line_ids.filtered(lambda l: l.side == "guest")[:1]
        payload = match.unit_state_dict()
        for entry in payload["guest"]:
            if entry["unit_id"] == guest_line.unit_id.id:
                entry["wounds_remaining"] = 0
                entry["models_remaining"] = 0
                entry["destroyed"] = True
        match.with_user(self.user_b).action_update_unit_state(
            payload, updating_partner=self.user_b.partner_id
        )
        guest_line.invalidate_recordset()
        self.assertTrue(guest_line.destroyed)

        # Host cannot wipe guest lines through update API.
        payload_host = match.unit_state_dict()
        for entry in payload_host["guest"]:
            entry["destroyed"] = False
            entry["wounds_remaining"] = entry["wounds"]
        match.with_user(self.user_a).action_update_unit_state(
            payload_host, updating_partner=self.user_a.partner_id
        )
        guest_line.invalidate_recordset()
        self.assertTrue(guest_line.destroyed)

    def test_mission_player_readonly(self):
        mission = self.mission
        with self.assertRaises(AccessError):
            mission.with_user(self.user_a).write({"name": "Hacked"})
