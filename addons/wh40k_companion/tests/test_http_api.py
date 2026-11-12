import json
import re

from odoo.tests import tagged
from odoo.tests.common import HttpCase

from .common import minimal_roster_json


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
        cls.user_stranger = Users.create(
            {
                "name": "Http Stranger",
                "login": "wh40k_http_stranger@example.com",
                "email": "wh40k_http_stranger@example.com",
                "password": cls.password,
                "group_ids": [(6, 0, [group.id])],
            }
        )
        cls.user_a.partner_id.wh40k_nickname = "HttpAlpha"
        cls.user_b.partner_id.wh40k_nickname = "HttpBeta"
        cls.user_stranger.partner_id.wh40k_nickname = "HttpStranger"
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
        force = cls.env["wh40k.force"].create(
            {"name": "Http Force B", "roster_id": cls.roster_b.id}
        )
        det = cls.env["wh40k.detachment"].create(
            {"name": "Http Det B", "force_id": force.id}
        )
        unit = cls.env["wh40k.unit"].create(
            {"name": "Http Unit B", "detachment_id": det.id, "quantity": 1}
        )
        cls.env["wh40k.model"].create(
            {"name": "Http Model B", "unit_id": unit.id, "quantity": 1, "wounds": "1"}
        )
        cls.mission = cls.env["wh40k.mission"].create(
            {"name": "Http Mission", "sequence": 99}
        )

    def _jsonrpc_raw(self, url, params=None):
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": 1,
            "params": params or {},
        }
        return self.url_open(
            url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )

    def _jsonrpc(self, url, params=None):
        response = self._jsonrpc_raw(url, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertNotIn("error", body, body)
        return body.get("result") or {}

    def _jsonrpc_result_or_rpc_error(self, url, params=None):
        response = self._jsonrpc_raw(url, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

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

        # Short watch poll (timeout 1s) for host
        self.authenticate(self.user_a.login, self.password)
        watched = self._jsonrpc(
            "/wh40k/api/match/watch",
            {"match_id": match_id, "since": state["match"].get("write_date"), "timeout": 1},
        )
        self.assertTrue(watched.get("ok"), watched)
        self.assertIn("changed", watched)

        surrendered = self._jsonrpc(
            "/wh40k/api/match/surrender", {"match_id": match_id}
        )
        self.assertTrue(surrendered.get("ok"), surrendered)
        self.assertEqual(surrendered.get("state"), "finished")

    def test_dashboard_nickname_missions_preview_import(self):
        self.authenticate(self.user_a.login, self.password)
        dash = self._jsonrpc("/wh40k/api/player/dashboard", {})
        self.assertTrue(dash.get("ok"), dash)
        self.assertEqual(dash["player"]["nickname"], "HttpAlpha")
        self.assertTrue(any(r["id"] == self.roster_a.id for r in dash["rosters"]))

        nick = self._jsonrpc(
            "/wh40k/api/player/nickname", {"nickname": "HttpAlphaRenamed"}
        )
        self.assertTrue(nick.get("ok"), nick)
        self.assertEqual(nick["nickname"], "HttpAlphaRenamed")

        missions = self._jsonrpc("/wh40k/api/missions", {})
        self.assertTrue(missions.get("ok"), missions)
        self.assertTrue(
            any(m["id"] == self.mission.id for m in missions["missions"])
        )

        payload = minimal_roster_json(name="Http Import", points=120)
        preview = self._jsonrpc(
            "/wh40k/api/roster/preview", {"roster_json": payload}
        )
        self.assertTrue(preview.get("ok"), preview)
        self.assertEqual(preview["preview"]["name"], "Http Import")

        imported = self._jsonrpc(
            "/wh40k/api/roster/import",
            {"roster_json": payload, "name": "Http Imported Name"},
        )
        self.assertTrue(imported.get("ok"), imported)
        self.assertEqual(imported["name"], "Http Imported Name")
        detail = self._jsonrpc(
            f"/wh40k/api/roster/{imported['roster_id']}/detail", {}
        )
        self.assertTrue(detail.get("ok"), detail)
        self.assertTrue(detail["roster"]["units"])

    def test_match_cancel_and_stranger_state_denied(self):
        self.authenticate(self.user_a.login, self.password)
        created = self._jsonrpc(
            "/wh40k/api/match/create",
            {
                "roster_id": self.roster_a.id,
                "mission_id": self.mission.id,
                "points": "2000",
            },
        )
        match_id = created["match_id"]
        published = self._jsonrpc("/wh40k/api/match/publish", {"match_id": match_id})
        self.assertTrue(published.get("ok"))

        self.authenticate(self.user_stranger.login, self.password)
        denied = self._jsonrpc("/wh40k/api/match/state", {"match_id": match_id})
        self.assertFalse(denied.get("ok"))
        self.assertTrue(denied.get("error"))

        missing = self._jsonrpc("/wh40k/api/match/state", {"match_id": 0})
        self.assertFalse(missing.get("ok"))

        self.authenticate(self.user_a.login, self.password)
        cancelled = self._jsonrpc(
            "/wh40k/api/match/cancel",
            {"match_id": match_id, "reason": "Http cancel"},
        )
        self.assertTrue(cancelled.get("ok"), cancelled)
        self.assertEqual(cancelled.get("state"), "cancelled")

    def _signup_csrf(self):
        page = self.url_open("/wh40k/signup")
        self.assertEqual(page.status_code, 200, page.text[:300])
        match = re.search(
            r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)["\']',
            page.text,
        )
        if not match:
            match = re.search(
                r'value=["\']([^"\']+)["\'][^>]*name=["\']csrf_token["\']',
                page.text,
            )
        self.assertTrue(match, "csrf_token missing on signup page")
        return match.group(1)

    def test_unauthenticated_api_rejected(self):
        # Drop any prior HttpCase session from sibling tests.
        if hasattr(self, "logout"):
            self.logout()
        else:
            self.url_open("/web/session/logout")
        body = self._jsonrpc_result_or_rpc_error(
            "/wh40k/api/player/dashboard", {}
        )
        # Odoo jsonrpc auth=user without session → RPC error envelope
        self.assertTrue(
            body.get("error") or (body.get("result") or {}).get("ok") is False,
            body,
        )

    def test_signup_happy_and_duplicate(self):
        if hasattr(self, "logout"):
            self.logout()
        else:
            self.url_open("/web/session/logout")
        email = "wh40k_signup_new@example.com"
        csrf = self._signup_csrf()
        response = self.url_open(
            "/wh40k/signup",
            data={
                "email": email,
                "password": "signup-pass-99",
                "nickname": "SignupNick99",
                "csrf_token": csrf,
            },
            allow_redirects=False,
        )
        # Redirect to /wh40k/app on success
        self.assertIn(
            response.status_code,
            (303, 302, 200),
            response.text[:500],
        )
        user = self.env["res.users"].sudo().search([("login", "=", email)], limit=1)
        self.assertTrue(user)
        self.assertEqual(user.partner_id.wh40k_nickname, "SignupNick99")

        # Duplicate email (fresh csrf; may still be logged in after signup)
        if hasattr(self, "logout"):
            self.logout()
        else:
            self.url_open("/web/session/logout")
        csrf2 = self._signup_csrf()
        dup = self.url_open(
            "/wh40k/signup",
            data={
                "email": email,
                "password": "signup-pass-99",
                "nickname": "OtherNick99",
                "csrf_token": csrf2,
            },
        )
        self.assertEqual(dup.status_code, 200)
        self.assertIn(b"already exists", dup.content.lower())

    def test_qr_rejects_arbitrary_payload(self):
        response = self.url_open("/wh40k/qr.png?data=https://example.com/evil")
        self.assertEqual(response.status_code, 404)

    def test_qr_accepts_valid_join_url(self):
        token = "12345678-1234-1234-1234-1234567890ab"
        url = f"http://127.0.0.1:8069/wh40k/join/{token}"
        response = self.url_open(f"/wh40k/qr.png?data={url}")
        self.assertEqual(response.status_code, 200, response.text[:200])
        self.assertTrue(response.content.startswith(b"\x89PNG"))
