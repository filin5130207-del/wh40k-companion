"""Query-count and wall-time benchmark for the battle hot path.

Run (no --db-drop), from an Odoo environment that has this addon:

    odoo-bin -d wh40k --test-enable --stop-after-init \\
        --http-port=8079 \\
        --test-tags /wh40k_companion:TestWh40kPerfBench

Prints one ``WH40K_BENCH`` JSON line. This file does not assert timings.
"""

import json
import os
import time

from odoo.tests.common import TransactionCase, tagged

from .common import Wh40kPlayerMixin


class QueryCounter:
    """Count cursor execute() calls. Wall time is measured by the caller."""

    def __init__(self, cr):
        self.cr = cr
        self.count = 0
        self._orig = cr.execute

    def __enter__(self):
        def execute(*args, **kwargs):
            self.count += 1
            return self._orig(*args, **kwargs)

        self.cr.execute = execute
        return self

    def __exit__(self, exc_type, exc, tb):
        self.cr.execute = self._orig
        return False


@tagged("post_install", "-at_install", "wh40k", "wh40k_bench")
class TestWh40kPerfBench(Wh40kPlayerMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_wh40k_players()

    def _measure(self, fn):
        self.env.flush_all()
        self.env.invalidate_all()
        started = time.perf_counter()
        with QueryCounter(self.env.cr) as counter:
            result = fn()
        return result, {
            "queries": counter.count,
            "seconds": round(time.perf_counter() - started, 6),
        }

    def test_bench_dashboard_detail_wound_watch(self):
        host_roster = self._import_minimal(self.user_a, name="Bench Host", points=500)
        guest_roster = self._import_minimal(self.user_b, name="Bench Guest", points=400)
        match = self._activate_match(
            self.user_a, self.user_b, host_roster, guest_roster
        )
        host_line = match.unit_line_ids.filtered(lambda line: line.side == "host")[:1]
        self.assertTrue(host_line)
        partner = self.user_a.partner_id

        def dashboard():
            return partner.get_wh40k_dashboard()

        def detail():
            return host_roster.to_detail_dict(partner)

        # Duck-typed so this file can also be copied onto main (30d391e) for a
        # baseline: that revision has no wound delta and watch returns to_state_dict.
        has_delta = hasattr(match, "action_apply_wound_delta")
        before_rev = match._lines_rev() if hasattr(match, "_lines_rev") else None
        before_wd = match._db_write_date_string()

        def wound():
            if has_delta:
                return match.action_apply_wound_delta(
                    {
                        "line_id": host_line.id,
                        "unit_id": host_line.unit_id.id,
                        "side": "host",
                        "models_remaining": host_line.models_remaining,
                        "wounds_remaining": max(0, host_line.wounds_remaining - 1),
                        "destroyed": False,
                        "undo": [],
                    },
                    updating_partner=partner,
                )
            payload = match.unit_state_dict()
            for entry in payload.get("host") or []:
                if entry.get("unit_id") == host_line.unit_id.id:
                    entry["wounds_remaining"] = max(0, entry.get("wounds_remaining", 1) - 1)
            match.action_update_unit_state(payload, updating_partner=partner)
            return {"legacy_full_state": True, "unit_state": payload}

        def watch():
            if hasattr(match, "watch_payload"):
                return match.watch_payload(
                    partner,
                    since_write_date=before_wd,
                    since_rev=before_rev,
                    wait=False,
                )
            return {"legacy_full_match": True, "match": match.to_state_dict(partner)}

        dash, dash_m = self._measure(dashboard)
        roster_detail, detail_m = self._measure(detail)
        delta, wound_m = self._measure(wound)
        watched, watch_m = self._measure(watch)

        self.assertTrue(dash["rosters"])
        self.assertNotIn("units", dash["rosters"][0])
        self.assertIn("unit_count", dash["rosters"][0])
        self.assertTrue(roster_detail["units"])
        if has_delta:
            self.assertNotIn("match", delta)
            self.assertEqual(len(delta["delta"]["lines"]), 1)
            self.assertNotIn("weapons", delta["delta"]["lines"][0])
            self.assertTrue(watched["lines_only"])
            self.assertNotIn("match", watched)
            self.assertEqual(len(watched["delta"]["lines"]), 1)
            self.env.flush_all()
            self.assertEqual(match._db_write_date_string(), before_wd)
        else:
            self.assertTrue(delta.get("legacy_full_state"))
            self.assertIn("match", watched)

        report = {
            "label": os.environ.get("WH40K_BENCH_LABEL", "wh40k_bench"),
            "module": "wh40k_companion",
            "wound_api": "delta" if has_delta else "full_unit_state",
            "note": (
                "Cold cache. Watch does not include long-poll sleep. "
                "delta: watch_payload(wait=False). "
                "full_unit_state: to_state_dict. "
                "seconds are wall time inside this Odoo test transaction."
            ),
            "dashboard": dash_m,
            "roster_detail": detail_m,
            "wound_update": wound_m,
            "watch_after_wound": watch_m,
        }
        line = "WH40K_BENCH " + json.dumps(report, sort_keys=True)
        print(line)
        out_path = os.environ.get("WH40K_BENCH_OUT")
        if out_path:
            with open(out_path, "w", encoding="utf-8") as handle:
                handle.write(line + "\n")
