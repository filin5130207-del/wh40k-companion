"""Pure tests for the token bridge. No Odoo runtime."""

import json
import unittest

from wh40k_token.lines import side_unit_key
from wh40k_token.rpc import RpcError, parse_jsonrpc_response
from wh40k_token.tokens import (
    issue_service_token,
    issue_user_token,
    verify_token,
)
from wh40k_token.urls import service_url


class TokenTests(unittest.TestCase):
    def test_user_roundtrip(self):
        token = issue_user_token(
            uid=7,
            login="a@b.c",
            nickname="Azrael",
            groups=["player"],
            secret="test-secret",
            now=1_700_000_000,
        )
        payload = verify_token(token, "test-secret", now=1_700_000_000)
        self.assertEqual(payload["role"], "user")
        self.assertEqual(payload["uid"], 7)
        self.assertEqual(payload["groups"], ["player"])

    def test_rejects_tamper_and_expiry(self):
        token = issue_user_token(
            uid=1,
            login="a@b.c",
            nickname="A",
            groups=["player"],
            secret="test-secret",
            now=100,
            ttl=10,
        )
        with self.assertRaises(ValueError):
            verify_token(token + "x", "test-secret", now=100)
        with self.assertRaises(ValueError):
            verify_token(token, "other-secret", now=100)
        with self.assertRaises(ValueError):
            verify_token(token, "test-secret", now=200)

    def test_service_audience(self):
        token = issue_service_token(
            secret="test-secret", audience="session", now=100
        )
        payload = verify_token(token, "test-secret", audience="session", now=100)
        self.assertEqual(payload["role"], "service")
        with self.assertRaises(ValueError):
            verify_token(token, "test-secret", audience="roster", now=100)
        user = issue_user_token(
            uid=1,
            login="a@b.c",
            nickname="A",
            groups=["player"],
            secret="test-secret",
            now=100,
        )
        with self.assertRaises(ValueError):
            verify_token(user, "test-secret", audience="session", now=100)


class LineKeyTests(unittest.TestCase):
    def test_sides_do_not_collide(self):
        self.assertEqual(side_unit_key("host", 1), 1)
        self.assertEqual(side_unit_key("guest", 1), -1)
        self.assertNotEqual(side_unit_key("host", 1), side_unit_key("guest", 1))
        with self.assertRaises(ValueError):
            side_unit_key("host", 0)


class RpcTests(unittest.TestCase):
    def test_ok_and_business_error(self):
        self.assertEqual(
            parse_jsonrpc_response(json.dumps({"result": {"ok": True, "id": 3}})),
            {"ok": True, "id": 3},
        )
        with self.assertRaises(RpcError):
            parse_jsonrpc_response(
                json.dumps({"result": {"ok": False, "error": "nope"}})
            )
        with self.assertRaises(RpcError):
            parse_jsonrpc_response(
                json.dumps({"error": {"data": {"message": "boom"}, "message": "x"}})
            )


class UrlTests(unittest.TestCase):
    def test_rewrites_loopback_keeps_public_host(self):
        self.assertEqual(
            service_url(
                "http://127.0.0.1:8070",
                hostname="192.168.1.20",
                scheme="http",
                port=8070,
            ),
            "http://192.168.1.20:8070",
        )
        self.assertEqual(
            service_url(
                "https://roster.example.com",
                hostname="192.168.1.20",
                scheme="http",
                port=8070,
            ),
            "https://roster.example.com",
        )


if __name__ == "__main__":
    unittest.main()
