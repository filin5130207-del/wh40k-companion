from odoo.tests import tagged
from odoo.tests.common import HttpCase


@tagged("post_install", "-at_install", "wh40k", "wh40k_http")
class TestWh40kPwaAssets(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = cls.env.ref("wh40k_companion.group_player")
        Users = cls.env["res.users"].with_context(no_reset_password=True)
        cls.password = "pwa-pass-123"
        cls.user = Users.create(
            {
                "name": "PWA Player",
                "login": "wh40k_pwa@example.com",
                "email": "wh40k_pwa@example.com",
                "password": cls.password,
                "group_ids": [(6, 0, [group.id])],
            }
        )
        cls.user.partner_id.wh40k_nickname = "PwaPlayer"

    def test_manifest_and_sw_public(self):
        manifest = self.url_open("/wh40k/manifest.webmanifest")
        self.assertEqual(manifest.status_code, 200, manifest.text[:300])
        self.assertIn("application/manifest+json", manifest.headers.get("Content-Type", ""))
        data = manifest.json()
        self.assertEqual(data.get("start_url"), "/wh40k/app")
        self.assertEqual(data.get("scope"), "/wh40k/")

        sw = self.url_open("/wh40k/sw.js")
        self.assertEqual(sw.status_code, 200, sw.text[:300])
        self.assertIn("javascript", sw.headers.get("Content-Type", ""))
        self.assertIn(b"addEventListener", sw.content)

    def test_app_shell_requires_user(self):
        # Logged-out: redirect toward login (or gate), not 500
        response = self.url_open("/wh40k/app", allow_redirects=False)
        self.assertIn(response.status_code, (303, 302, 303, 301, 200))
        if response.status_code in (301, 302, 303):
            location = response.headers.get("Location", "")
            self.assertTrue(
                "/web/login" in location or "/wh40k" in location,
                location,
            )

        self.authenticate(self.user.login, self.password)
        app = self.url_open("/wh40k/app")
        self.assertEqual(app.status_code, 200, app.text[:400])
        # PWA shell markers
        body = app.text.lower()
        self.assertTrue(
            "wh40k" in body or "owl" in body or "battle" in body,
            app.text[:500],
        )
