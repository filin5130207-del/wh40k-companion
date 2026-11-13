import importlib.util
import json
from pathlib import Path

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from .common import Wh40kPlayerMixin


@tagged("post_install", "-at_install", "wh40k")
class TestWh40kUnitLinesUndoMigration(Wh40kPlayerMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_wh40k_players()

    def test_lines_created_update_own_side_block_opponent(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host UL")
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest UL")
        match = self._activate_match(
            self.user_a, self.user_b, host_roster, guest_roster
        )
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
                payload.setdefault("undo", {})[str(entry["unit_id"])] = [
                    {
                        "models_remaining": guest_line.models,
                        "wounds_remaining": guest_line.wounds,
                        "destroyed": False,
                    }
                ]
        match.with_user(self.user_b).action_update_unit_state(
            payload, updating_partner=self.user_b.partner_id
        )
        guest_line.invalidate_recordset()
        self.assertTrue(guest_line.destroyed)
        self.assertTrue(guest_line._undo_list())

        # Host payload cannot revive guest lines
        payload_host = match.unit_state_dict()
        for entry in payload_host["guest"]:
            entry["destroyed"] = False
            entry["wounds_remaining"] = entry["wounds"]
            entry["models_remaining"] = entry["models"]
        match.with_user(self.user_a).action_update_unit_state(
            payload_host, updating_partner=self.user_a.partner_id
        )
        guest_line.invalidate_recordset()
        self.assertTrue(guest_line.destroyed)

    def test_undo_stack_roundtrip(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host Undo")
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest Undo")
        match = self._activate_match(
            self.user_a, self.user_b, host_roster, guest_roster
        )
        host_line = match.unit_line_ids.filtered(lambda l: l.side == "host")[:1]
        payload = match.unit_state_dict()
        unit_id = host_line.unit_id.id
        snap = {
            "models_remaining": host_line.models_remaining,
            "wounds_remaining": host_line.wounds_remaining,
            "destroyed": False,
        }
        for entry in payload["host"]:
            if entry["unit_id"] == unit_id:
                entry["wounds_remaining"] = max(0, entry["wounds_remaining"] - 1)
                if entry["wounds_remaining"] == 0:
                    entry["destroyed"] = True
                    entry["models_remaining"] = 0
        payload["undo"] = {str(unit_id): [snap]}
        match.with_user(self.user_a).action_update_unit_state(
            payload, updating_partner=self.user_a.partner_id
        )
        host_line.invalidate_recordset()
        self.assertEqual(host_line._undo_list(), [snap])

        # Undo restore via second update
        restored = match.unit_state_dict()
        for entry in restored["host"]:
            if entry["unit_id"] == unit_id:
                entry.update(snap)
        restored["undo"] = {str(unit_id): []}
        match.with_user(self.user_a).action_update_unit_state(
            restored, updating_partner=self.user_a.partner_id
        )
        host_line.invalidate_recordset()
        self.assertEqual(host_line.wounds_remaining, snap["wounds_remaining"])
        self.assertFalse(host_line.destroyed)

    def test_update_rejects_non_active_and_stranger(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host NA")
        match = self._publish_match(self.user_a, host_roster)
        with self.assertRaises(UserError):
            match.with_user(self.user_a).action_update_unit_state(
                {"host": [], "guest": [], "undo": {}},
                updating_partner=self.user_a.partner_id,
            )
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest NA")
        match = self._activate_match(
            self.user_a, self.user_b, host_roster, guest_roster
        )
        with self.assertRaises(UserError):
            match.action_update_unit_state(
                {"host": [], "guest": [], "undo": {}},
                updating_partner=self.user_stranger.partner_id,
            )

    def test_legacy_unit_state_migration_helper(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host Mig")
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest Mig")
        # Create finished match without lines, only legacy JSON
        host_unit = host_roster.force_ids.detachment_ids.unit_ids[:1]
        guest_unit = guest_roster.force_ids.detachment_ids.unit_ids[:1]
        legacy = {
            "host": [
                {
                    "unit_id": host_unit.id,
                    "name": host_unit.name,
                    "models": 2,
                    "models_remaining": 1,
                    "wounds": 4,
                    "wounds_remaining": 2,
                    "destroyed": False,
                }
            ],
            "guest": [
                {
                    "unit_id": guest_unit.id,
                    "name": guest_unit.name,
                    "models": 2,
                    "models_remaining": 0,
                    "wounds": 4,
                    "wounds_remaining": 0,
                    "destroyed": True,
                }
            ],
            "undo": {
                str(host_unit.id): [
                    {
                        "models_remaining": 2,
                        "wounds_remaining": 4,
                        "destroyed": False,
                    }
                ]
            },
        }
        match = self.env["wh40k.match"].sudo().create(
            {
                "host_id": self.user_a.partner_id.id,
                "guest_id": self.user_b.partner_id.id,
                "host_roster_id": host_roster.id,
                "guest_roster_id": guest_roster.id,
                "mission_id": self.mission.id,
                "points": "2000",
                "state": "finished",
                "unit_state": json.dumps(legacy),
            }
        )
        self.assertFalse(match.unit_line_ids)

        migrate_path = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "20.0.1.15.0"
            / "post-migrate.py"
        )
        spec = importlib.util.spec_from_file_location(
            "wh40k_post_migrate_15_test", migrate_path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.migrate(self.env.cr, "20.0.1.15.0")
        match.invalidate_recordset()
        self.assertEqual(len(match.unit_line_ids), 2)
        guest_line = match.unit_line_ids.filtered(lambda l: l.side == "guest")
        self.assertTrue(guest_line.destroyed)
        host_line = match.unit_line_ids.filtered(lambda l: l.side == "host")
        self.assertEqual(host_line.wounds_remaining, 2)
        self.assertTrue(host_line._undo_list())
