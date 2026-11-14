from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from .common import Wh40kPlayerMixin


@tagged("post_install", "-at_install", "wh40k")
class TestWh40kWoundDelta(Wh40kPlayerMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_wh40k_players()

    def _field_cached(self, record, fname):
        field = record._fields[fname]
        contains = getattr(record.env.cache, "contains", None)
        if not contains:
            return None
        try:
            return bool(contains(record, field))
        except TypeError:
            return None

    def _active(self):
        host = self._make_tiny_roster(self.user_a, name="Delta Host")
        guest = self._make_tiny_roster(self.user_b, name="Delta Guest")
        match = self._activate_match(self.user_a, self.user_b, host, guest)
        self.env.flush_all()
        return match

    def test_delta_does_not_rewrite_match_or_opponent(self):
        match = self._active()
        host_line = match.unit_line_ids.filtered(lambda line: line.side == "host")[:1]
        guest_line = match.unit_line_ids.filtered(lambda line: line.side == "guest")[:1]
        self.env.cr.execute(
            "SELECT write_date FROM wh40k_match WHERE id = %s",
            (match.id,),
        )
        match_wd = self.env.cr.fetchone()[0]
        self.env.cr.execute(
            "SELECT write_date, wounds_remaining FROM wh40k_match_unit_line WHERE id = %s",
            (guest_line.id,),
        )
        guest_before = self.env.cr.fetchone()

        result = match.with_user(self.user_a).action_apply_wound_delta(
            {
                "line_id": host_line.id,
                "unit_id": host_line.unit_id.id,
                "side": "host",
                "wounds_remaining": max(0, host_line.wounds_remaining - 1),
                "models_remaining": host_line.models_remaining,
                "destroyed": False,
                "undo": [
                    {
                        "models_remaining": host_line.models_remaining,
                        "wounds_remaining": host_line.wounds,
                        "destroyed": False,
                    }
                ],
            },
            updating_partner=self.user_a.partner_id,
        )
        self.assertEqual(len(result["delta"]["lines"]), 1)
        self.assertEqual(result["delta"]["lines"][0]["line_id"], host_line.id)
        self.assertNotIn("match", result)
        self.assertGreater(result["lines_rev"], 0)

        self.env.cr.execute(
            "SELECT write_date FROM wh40k_match WHERE id = %s",
            (match.id,),
        )
        self.assertEqual(self.env.cr.fetchone()[0], match_wd)
        self.env.cr.execute(
            "SELECT write_date, wounds_remaining FROM wh40k_match_unit_line WHERE id = %s",
            (guest_line.id,),
        )
        self.assertEqual(self.env.cr.fetchone(), guest_before)

        watched = match.watch_payload(
            self.user_b.partner_id,
            since_write_date=match._db_write_date_string(),
            since_rev=0,
            wait=False,
        )
        self.assertTrue(watched["lines_only"])
        self.assertNotIn("match", watched)
        self.assertEqual(watched["delta"]["lines"][0]["unit_id"], host_line.unit_id.id)
        self.assertNotIn("weapons", watched["delta"]["lines"][0])
        self.assertNotIn("rules", watched["delta"])

    def test_opponent_line_in_delta_is_ignored(self):
        match = self._active()
        guest_line = match.unit_line_ids.filtered(lambda line: line.side == "guest")[:1]
        result = match.with_user(self.user_a).action_apply_wound_delta(
            {
                "line_id": guest_line.id,
                "unit_id": guest_line.unit_id.id,
                "side": "guest",
                "wounds_remaining": 0,
                "models_remaining": 0,
                "destroyed": True,
                "undo": [],
            },
            updating_partner=self.user_a.partner_id,
        )
        self.assertEqual(result["delta"]["lines"], [])
        guest_line.invalidate_recordset()
        self.assertFalse(guest_line.destroyed)

    def test_lifecycle_watch_still_returns_match(self):
        match = self._active()
        since = match._db_write_date_string()
        since_rev = match._lines_rev()
        match.with_user(self.user_a).action_surrender(self.user_a.partner_id)
        watched = match.watch_payload(
            self.user_b.partner_id,
            since_write_date=since,
            since_rev=since_rev,
            wait=False,
        )
        self.assertTrue(watched["changed"])
        self.assertFalse(watched["lines_only"])
        self.assertEqual(watched["match"]["state"], "finished")
        self.assertIn("unit_state", watched["match"])

    def _assert_no_full_poll_sleep(self):
        def fail_sleep(seconds):
            if seconds >= 0.5:
                raise AssertionError(
                    "watch slept %.3f instead of returning the finish" % seconds
                )

        return patch("time.sleep", fail_sleep)

    def test_finished_watch_returns_without_parking(self):
        """Opponent surrender is visible even when write_date did not move."""
        match = self._active()
        match.with_user(self.user_b).action_surrender(self.user_b.partner_id)
        since = match._db_write_date_string()
        since_rev = match._lines_rev()

        def park(_record, _timeout):
            raise AssertionError("parked on an already finished match")

        with patch.object(type(match), "_park_for_signal", park), self._assert_no_full_poll_sleep():
            watched = match.watch_payload(
                self.user_a.partner_id,
                since_write_date=since,
                since_rev=since_rev,
                timeout_seconds=20,
                wait=True,
            )
        self.assertTrue(watched["changed"])
        self.assertFalse(watched["lines_only"])
        self.assertNotIn("delta", watched)
        self.assertEqual(watched["match"]["state"], "finished")
        self.assertEqual(watched["match"]["winner_id"], self.user_a.partner_id.id)

    def test_inflight_watch_wakes_on_surrender_without_full_sleep(self):
        """The long-poll returns the finish from the wake, not after timeout."""
        match = self._active()
        since = match._db_write_date_string()
        since_rev = match._lines_rev()
        parked = {}

        def park(record, timeout):
            parked["timeout"] = timeout
            record.with_user(self.user_a).action_surrender(self.user_a.partner_id)
            return True

        with patch.object(type(match), "_park_for_signal", park), self._assert_no_full_poll_sleep():
            watched = match.watch_payload(
                self.user_b.partner_id,
                since_write_date=since,
                since_rev=since_rev,
                timeout_seconds=20,
                wait=True,
            )
        self.assertGreater(parked["timeout"], 1)
        self.assertTrue(watched["changed"])
        self.assertFalse(watched["lines_only"])
        self.assertEqual(watched["match"]["state"], "finished")
        self.assertEqual(watched["match"]["winner_id"], self.user_b.partner_id.id)

    def test_import_does_not_touch_unrelated_match(self):
        match = self._active()
        self.env.flush_all()
        self.assertEqual(match.state, "active")
        cached_before = self._field_cached(match, "state")
        if cached_before:
            self.assertTrue(cached_before)
        self.env.cr.execute(
            "SELECT write_date, state FROM wh40k_match WHERE id = %s",
            (match.id,),
        )
        before = self.env.cr.fetchone()
        line_before = {}
        for line in match.unit_line_ids:
            self.env.cr.execute(
                """
                SELECT write_date, wounds_remaining, rev
                  FROM wh40k_match_unit_line
                 WHERE id = %s
                """,
                (line.id,),
            )
            line_before[line.id] = self.env.cr.fetchone()

        self._import_minimal(self.user_a, name="Import Beside Match")

        if cached_before:
            self.assertTrue(self._field_cached(match, "state"))
        self.env.cr.execute(
            "SELECT write_date, state FROM wh40k_match WHERE id = %s",
            (match.id,),
        )
        self.assertEqual(self.env.cr.fetchone(), before)
        for line_id, row in line_before.items():
            self.env.cr.execute(
                """
                SELECT write_date, wounds_remaining, rev
                  FROM wh40k_match_unit_line
                 WHERE id = %s
                """,
                (line_id,),
            )
            self.assertEqual(self.env.cr.fetchone(), row)

    def test_lookup_indexes(self):
        self.assertTrue(self.env["wh40k.match"]._fields["match_token"].index)
        self.assertTrue(self.env["wh40k.roster"]._fields["partner_id"].index)
        self.assertTrue(self.env["wh40k.match"]._fields["host_id"].index)
        self.assertTrue(self.env["wh40k.match"]._fields["guest_id"].index)

        def defs(table):
            self.env.cr.execute(
                "SELECT indexdef FROM pg_indexes WHERE tablename = %s",
                (table,),
            )
            return "\n".join(row[0].lower() for row in self.env.cr.fetchall())

        match_idx = defs("wh40k_match")
        self.assertIn("match_token", match_idx)
        self.assertIn("host_id", match_idx)
        self.assertIn("guest_id", match_idx)
        self.assertIn("partner_id", defs("wh40k_roster"))
        line_idx = defs("wh40k_match_unit_line")
        self.assertRegex(line_idx, r"match_id,\s*side")
        self.assertRegex(line_idx, r"match_id,\s*rev")
