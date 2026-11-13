from odoo import http
from odoo.http import request

try:
    from odoo.addons.auth_signup.controllers.main import AuthSignupHome
except ImportError:  # pragma: no cover
    AuthSignupHome = object


class Wh40kAuthSignupRedirect(AuthSignupHome):
    """Send Odoo default Sign Up to /wh40k/signup (portal signup has no Battle App)."""

    @http.route()
    def web_auth_signup(self, *args, **kw):
        return request.redirect("/wh40k/signup")