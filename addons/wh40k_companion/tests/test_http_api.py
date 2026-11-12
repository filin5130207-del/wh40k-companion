import json

from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install", "wh40k", "wh40k_http")
class TestWh40kHttpApi(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = cls.env.ref("wh40k_companion.group_player")
        Users = cls.env["res.users"].with_context(no_reset_password=True)
        cls.password = "player-pass-123"
        cls.user_a = Users.create(
            {
                "name": "Http Player A",
                "login": "wh40k_http_a@example.com",
                "email": "wh40k_http_a@example.com",
                "password": cls.password,
                "group_ids": [(6, 0, [group.id])],
            }
        )
        cls.user_b = Users.create(
            {
                "name": "Http Player B",
                "login": "wh40k_http_b@example.com",
                "email": "wh40k_http_b@example.com",
                "password": cls.password,
                "group_ids": [(6, 0, [group.id])],
            }
        )
        cls.user_a.partner_id.wh40k_nickname = "HttpAlpha"
        cls.user_b.partner_id.wh40k_nickname = "HttpBeta"
        cls.roster_a = cls.env["wh40k.roster"].create(
            {
                "name": "Http Host Roster",
                "partner_id": cls.user_a.partner_id.id,
                "points_used": 1000,
                "points_limit": 2000,
            }
        )
        cls.roster_b = cls.env["wh40k.roster"].create(
            {
                "name": "Http Guest Roster",
                "partner_id": cls.user_b.partner_id.id,
                "points_used": 900,
                "points_limit": 2000,
            }
        )
        cls.mission = cls.env["wh40k.mission"].create(
            {"name": "Http Mission", "sequence": 99}
        )

    def _jsonrpc(self, url, params=None):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": 1,
            "params": params or {},
        }
        response = self.url_open(
            url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertNotIn("error", body, body)
        return body.get("result") or {}

    def test_roster_detail_ownership_http(self):
        self.authenticate(self.user_b.login, self.password)
        result = self._jsonrpc(
            f"/wh40k/api/roster/{self.roster_a.id}/detail",
            params={},
        )
        self.assertFalse(result.get("ok"))
        self.assertTrue(result.get("error"))

        self.authenticate(self.user_a.login, self.password)
        ok = self._jsonrpc(
            f"/wh40k/api/roster/{self.roster_a.id}/detail",
            params={},
        )
        self.assertTrue(ok.get("ok"))
        self.assertEqual(ok["roster"]["id"], self.roster_a.id)

    def test_match_create_publish_join_flow_http(self):
        self.authenticate(self.user_a.login, self.password)
        created = self._jsonrpc(
            "/wh40k/api/match/create",
            {
                "roster_id": self.roster_a.id,
                "mission_id": self.mission.id,
                "points": "2000",
            },
        )
        self.assertTrue(created.get("ok"), created)
        match_id = created["match_id"]
        published = self._jsonrpc("/wh40k/api/match/publish", {"match_id": match_id})
        self.assertTrue(published.get("ok"), published)
        token = published["match_token"]
        self.assertTrue(token)
        self.assertIn("/wh40k/join/", published["join_url"])

        self.authenticate(self.user_b.login, self.password)
        verified = self._jsonrpc("/wh40k/api/match/verify", {"match_token": token})
        self.assertTrue(verified.get("ok"), verified)
        accepted = self._jsonrpc("/wh40k/api/match/accept", {"match_token": token})
        self.assertTrue(accepted.get("ok"), accepted)
        joined = self._jsonrpc(
            "/wh40k/api/match/join",
            {"match_token": token, "roster_id": self.roster_b.id},
        )
        self.assertTrue(joined.get("ok"), joined)
        self.assertEqual(joined.get("state"), "active")

        state = self._jsonrpc("/wh40k/api/match/state", {"match_id": match_id})
        self.assertTrue(state.get("ok"), state)
        unit_state = state["match"]["unit_state"]
        self.assertIn("host", unit_state)
        self.assertIn("guest", unit_state)

    def test_qr_rejects_arbitrary_payload(self):
        response = self.url_open("/wh40k/qr.png?data=https://example.com/evil")
        self.assertEqual(response.status_code, 404)
