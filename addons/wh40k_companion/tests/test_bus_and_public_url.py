"""Bus payload on surrender, and public vs LAN join links."""

import json

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.wh40k_companion.utils.public_url import is_private_base

from .common import Wh40kPlayerMixin


def _bus_payloads(env, match_id):
    """Notifications queued for this match, after the bus precommit hook."""
    env.cr.precommit.run()
    found = []
    for row in env["bus.bus"].sudo().search([]):
        try:
            message = json.loads(row.message or "{}")
            channel = json.loads(row.channel or "null")
        except (TypeError, json.JSONDecodeError):
            continue
        if message.get("type") != "wh40k.match/updated":
            continue
        payload = message.get("payload") or {}
        if payload.get("match_id") != match_id:
            continue
        if isinstance(channel, list) and len(channel) == 2:
            channel_name = channel[1]
        else:
            channel_name = channel
        found.append((channel_name, payload))
    return found


@tagged("post_install", "-at_install", "wh40k")
class TestWh40kBusAndPublicUrl(Wh40kPlayerMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_wh40k_players()

    def test_private_hosts_are_not_public(self):
        private = [
            "http://127.0.0.1:8069",
            "http://localhost:8069",
            "http://[::1]:8069",
            "http://10.1.2.3:8069",
            "http://192.168.0.163:8069",
            "http://172.16.0.1:8069",
            "http://172.31.255.9:8069",
            "http://169.254.1.1:8069",
        ]
        for url in private:
            self.assertTrue(is_private_base(url), url)
        self.assertFalse(is_private_base("https://example.com"))
        self.assertFalse(is_private_base("https://example.com:8443"))
        self.assertFalse(is_private_base("http://172.32.0.1:8069"))
        self.assertFalse(is_private_base("http://8.8.8.8"))

    def test_join_url_uses_public_base_and_hides_private(self):
        icp = self.env["ir.config_parameter"].sudo()
        host_roster = self._make_tiny_roster(self.user_a, name="Host Pub")
        match = self._publish_match(self.user_a, host_roster)
        token_path = f"/wh40k/join/{match.match_token}"

        icp.set_param("web.base.url", "http://192.168.0.163:8069")
        icp.set_param("wh40k.public_base_url", "https://example.com")
        published = match.to_publish_dict(request_host="http://192.168.0.163:8069")
        self.assertEqual(published["join_url"], f"https://example.com{token_path}")
        self.assertTrue(published["join_url_public"])

        # A private web.base.url is not a public fallback, and not advertised.
        icp.set_param("wh40k.public_base_url", "")
        icp.set_param("web.base.url", "http://192.168.0.163:8069")
        lan = match.join_link_dict(request_host="http://10.0.0.8:8069")
        self.assertEqual(lan["join_url"], f"http://192.168.0.163:8069{token_path}")
        self.assertFalse(lan["join_url_public"])

        # Loopback web.base.url yields the non-loopback request host, still LAN-only.
        icp.set_param("web.base.url", "http://127.0.0.1:8069")
        from_request = match.join_link_dict(request_host="http://192.168.0.163:8069")
        self.assertEqual(
            from_request["join_url"], f"http://192.168.0.163:8069{token_path}"
        )
        self.assertFalse(from_request["join_url_public"])

        # Public web.base.url is used only when the dedicated parameter is empty.
        icp.set_param("web.base.url", "https://example.com")
        fallback = match.join_link_dict(request_host="http://192.168.0.163:8069")
        self.assertEqual(fallback["join_url"], f"https://example.com{token_path}")
        self.assertTrue(fallback["join_url_public"])

        # An explicitly configured private base is still not called public.
        icp.set_param("wh40k.public_base_url", "http://10.8.0.2:8069")
        forced = match.to_publish_dict(request_host="https://example.com")
        self.assertTrue(forced["join_url"].startswith("http://10.8.0.2:8069/"))
        self.assertFalse(forced["join_url_public"])

    def test_surrender_emits_bus_payload_for_both_players(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host Bus")
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest Bus")
        match = self._activate_match(
            self.user_a, self.user_b, host_roster, guest_roster
        )
        match.with_user(self.user_b).action_surrender(self.user_b.partner_id)
        self.assertEqual(match.state, "finished")

        payloads = _bus_payloads(self.env, match.id)
        finished = [
            (channel, payload)
            for channel, payload in payloads
            if payload.get("state") == "finished" and not payload.get("lines_only")
        ]
        channels = {channel for channel, _payload in finished}
        host_channel = f"wh40k.match.{self.user_a.partner_id.id}"
        guest_channel = f"wh40k.match.{self.user_b.partner_id.id}"
        self.assertIn(host_channel, channels)
        self.assertIn(guest_channel, channels)
        for _channel, payload in finished:
            self.assertEqual(payload["match_id"], match.id)
            self.assertEqual(payload["state"], "finished")
            self.assertFalse(payload["lines_only"])

    def test_wound_emits_lines_only_bus_payload(self):
        host_roster = self._make_tiny_roster(self.user_a, name="Host Wound Bus")
        guest_roster = self._make_tiny_roster(self.user_b, name="Guest Wound Bus")
        match = self._activate_match(
            self.user_a, self.user_b, host_roster, guest_roster
        )
        guest_line = match.unit_line_ids.filtered(lambda line: line.side == "guest")[:1]
        self.assertTrue(guest_line)
        match.with_user(self.user_b).action_apply_wound_delta(
            {
                "line_id": guest_line.id,
                "unit_id": guest_line.unit_id.id,
                "side": "guest",
                "models_remaining": 0,
                "wounds_remaining": 0,
                "destroyed": True,
                "undo": [],
            },
            updating_partner=self.user_b.partner_id,
        )
        payloads = _bus_payloads(self.env, match.id)
        line_notes = [
            payload
            for _channel, payload in payloads
            if payload.get("lines_only") and payload.get("lines_rev")
        ]
        self.assertTrue(line_notes)
        self.assertTrue(all(note["match_id"] == match.id for note in line_notes))
