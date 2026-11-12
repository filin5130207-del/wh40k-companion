from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install", "wh40k")
class TestLocalQrPngOdoo(TransactionCase):
    def test_helper_available(self):
        from odoo.addons.wh40k_companion.utils.qr_png import render_join_qr_png

        png = render_join_qr_png(
            "https://lan.example/wh40k/join/12345678-1234-1234-1234-1234567890ab"
        )
        self.assertTrue(png.startswith(b"\x89PNG"))
        with self.assertRaises(ValueError):
            render_join_qr_png("https://example.com/not-join")
