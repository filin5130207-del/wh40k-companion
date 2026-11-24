import json
import logging
import os
import re

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from odoo.http.session import authenticate

from wh40k_token import secret_from_env, service_url, verify_token

_logger = logging.getLogger(__name__)


class Wh40kSessionController(http.Controller):
    """Accounts, the PWA shell, and the bearer token. Not rosters or matches."""

    def _secret(self):
        try:
            return secret_from_env()
        except ValueError as exc:
            raise AccessError(str(exc)) from exc

    def _json_error(self, exc):
        if isinstance(exc, AccessError):
            _logger.warning("WH40k session access denied: %s", exc)
            return {"ok": False, "error": str(exc)}
        if isinstance(exc, (UserError, ValidationError)):
            return {"ok": False, "error": str(exc)}
        _logger.exception("WH40k session error")
        return {"ok": False, "error": "Internal server error."}

    def _wrap(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — normalized JSON for the PWA
            return self._json_error(exc)

    def _ok(self, **payload):
        data = {"ok": True}
        data.update(payload)
        return data

    def _user(self):
        user = request.env.user
        if not user or user._is_public():
            raise AccessError("Login required.")
        return user

    def _service_actor(self):
        header = request.httprequest.headers.get("Authorization") or ""
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        try:
            payload = verify_token(token, self._secret(), audience="session")
        except ValueError as exc:
            raise AccessError(str(exc)) from exc
        if payload.get("role") != "service":
            raise AccessError("Service token required.")
        return payload

    def _browser_host(self):
        host = (request.httprequest.host or "").split(":")[0]
        scheme = request.httprequest.scheme or "http"
        return host, scheme

    def _service_urls(self):
        host, scheme = self._browser_host()
        roster_port = os.environ.get("WH40K_ROSTER_PUBLIC_PORT", "8070")
        match_port = os.environ.get("WH40K_MATCH_PUBLIC_PORT", "8071")
        return {
            "session": "",
            "roster": service_url(
                os.environ.get("WH40K_ROSTER_PUBLIC_URL", ""),
                hostname=host,
                scheme=scheme,
                port=roster_port,
            ),
            "match": service_url(
                os.environ.get("WH40K_MATCH_PUBLIC_URL", ""),
                hostname=host,
                scheme=scheme,
                port=match_port,
            ),
        }

    def _pwa_render_values(self):
        return {
            "session_info": request.env["ir.http"].get_frontend_session_info(),
            "debug": request.session.debug if hasattr(request.session, "debug") else "",
            "service_urls": self._service_urls(),
        }

    def _public_base_url(self):
        host_url = (request.httprequest.url_root or "").rstrip("/")

        def _is_loopback(url):
            low = (url or "").lower()
            return "://127.0.0.1" in low or "://localhost" in low or "://[::1]" in low

        if host_url and not _is_loopback(host_url):
            return host_url
        configured = os.environ.get("WH40K_PWA_BASE_URL") or ""
        return (configured or host_url).rstrip("/")

    @http.route("/wh40k", type="http", auth="public", website=False, sitemap=False)
    def wh40k_landing(self, **kwargs):
        return request.render(
            "wh40k_session.landing_page",
            {"error": kwargs.get("error"), "message": kwargs.get("message")},
        )

    @http.route(
        "/wh40k/signup",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        website=False,
        csrf=True,
        sitemap=False,
    )
    def wh40k_signup(self, **post):
        error = ""
        join = (post.get("join") or request.httprequest.args.get("join") or "").strip()
        if request.httprequest.method == "POST":
            email = (post.get("email") or "").strip().lower()
            password = post.get("password") or ""
            nickname = (post.get("nickname") or "").strip()
            try:
                request.env["res.users"].action_wh40k_signup(
                    email=email, password=password, nickname=nickname
                )
                authenticate(
                    request.session,
                    request.env,
                    {"login": email, "password": password, "type": "password"},
                )
                if join:
                    request.session["wh40k_pending_join"] = join
                    return request.redirect(f"/wh40k/join/{join}")
                return request.redirect("/wh40k/app")
            except (UserError, ValidationError) as exc:
                error = str(exc)
            except Exception:
                _logger.exception("WH40k signup failed")
                error = "Could not create the account. Please try again."
        return request.render(
            "wh40k_session.signup_page",
            {
                "error": error,
                "email": post.get("email") or "",
                "nickname": post.get("nickname") or "",
                "join": join,
            },
        )

    @http.route(
        ["/wh40k/app", "/wh40k/app/<path:_rest>"],
        type="http",
        auth="user",
        website=False,
        sitemap=False,
    )
    def wh40k_app(self, _rest=None, **kwargs):
        join = (
            kwargs.get("wh40k_join")
            or kwargs.get("join")
            or request.session.get("wh40k_pending_join")
            or ""
        )
        if join:
            request.session["wh40k_pending_join"] = join
        return request.render("wh40k_session.pwa_shell", self._pwa_render_values())

    @http.route(
        "/wh40k/manifest.webmanifest",
        type="http",
        auth="public",
        methods=["GET"],
        website=False,
        sitemap=False,
        csrf=False,
    )
    def wh40k_manifest(self, **kwargs):
        base = self._public_base_url() or ""
        manifest = {
            "name": "WH40k Battle Companion",
            "short_name": "Battle App",
            "description": "Rosters, QR matchmaking, and in-game wound tracking.",
            "start_url": "/wh40k/app",
            "scope": "/wh40k/",
            "display": "standalone",
            "background_color": "#0e1319",
            "theme_color": "#b85324",
            "lang": "ru",
            "icons": [
                {
                    "src": f"{base}/wh40k_session/static/description/icon.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                }
            ],
        }
        return request.make_response(
            json.dumps(manifest),
            headers=[
                ("Content-Type", "application/manifest+json"),
                ("Cache-Control", "public, max-age=300"),
            ],
        )

    @http.route(
        "/wh40k/sw.js",
        type="http",
        auth="public",
        methods=["GET"],
        website=False,
        sitemap=False,
        csrf=False,
    )
    def wh40k_service_worker(self, **kwargs):
        from odoo.tools.misc import file_path

        path = file_path("wh40k_session/static/src/pwa/sw.js")
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
        return request.make_response(
            content,
            headers=[
                ("Content-Type", "application/javascript; charset=utf-8"),
                ("Service-Worker-Allowed", "/wh40k/"),
                ("Cache-Control", "no-cache"),
            ],
        )

    @http.route(
        ["/wh40k/qr.png", "/wh40k/qr.svg"],
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        website=False,
        sitemap=False,
    )
    def qr_png(self, data="", size="260", **kwargs):
        from ..utils.qr_png import render_join_qr_png

        try:
            size_i = max(80, min(512, int(size or 260)))
        except (TypeError, ValueError):
            size_i = 260
        try:
            content = render_join_qr_png(data, size=size_i)
        except Exception:
            _logger.exception("Local QR render failed")
            return request.not_found()
        return request.make_response(
            content,
            headers=[
                ("Content-Type", "image/png"),
                ("Cache-Control", "public, max-age=120"),
            ],
        )

    @http.route(
        "/wh40k/join/<string:match_token>",
        type="http",
        auth="public",
        website=False,
        sitemap=False,
    )
    def join_redirect(self, match_token, **kwargs):
        token = (match_token or "").strip()
        if not re.match(r"^[a-fA-F0-9-]{16,64}$", token):
            return request.redirect("/wh40k?error=Invalid+join+link")
        request.session["wh40k_pending_join"] = token
        if not request.session.uid:
            return request.render(
                "wh40k_session.join_gate",
                {
                    "match_token": token,
                    "login_url": f"/web/login?redirect=/wh40k/join/{token}",
                    "signup_url": f"/wh40k/signup?join={token}",
                },
            )
        return request.redirect(f"/wh40k/app?wh40k_join={token}")

    def _api_token(self, **kwargs):
        user = self._user()
        names = user._wh40k_group_names()
        if "player" not in names:
            raise AccessError("Player group required.")
        return self._ok(token=user._wh40k_issue_token(self._secret()))

    def _api_me(self, **kwargs):
        user = self._user()
        partner = user.partner_id
        return self._ok(
            player=partner.to_wh40k_player_dict(user),
            pending_join_token=request.session.get("wh40k_pending_join") or "",
        )

    def _api_clear_join(self, **kwargs):
        self._user()
        request.session.pop("wh40k_pending_join", None)
        return self._ok()

    def _api_nickname(self, nickname=None, **kwargs):
        user = self._user()
        value = user.partner_id.action_wh40k_set_nickname(nickname)
        return self._ok(nickname=value)

    def _api_record_result(self, results=None, **kwargs):
        self._service_actor()
        applied = request.env["wh40k.stat.event"].record_results(results or [])
        return self._ok(applied=applied)

    @http.route("/wh40k/api/session/token", type="jsonrpc", auth="user")
    def api_token(self, **kwargs):
        return self._wrap(self._api_token, **kwargs)

    @http.route("/wh40k/api/session/me", type="jsonrpc", auth="user")
    def api_me(self, **kwargs):
        return self._wrap(self._api_me, **kwargs)

    @http.route("/wh40k/api/session/clear_join", type="jsonrpc", auth="user")
    def api_clear_join(self, **kwargs):
        return self._wrap(self._api_clear_join, **kwargs)

    @http.route("/wh40k/api/player/nickname", type="jsonrpc", auth="user")
    def api_nickname(self, nickname=None, **kwargs):
        return self._wrap(self._api_nickname, nickname=nickname, **kwargs)

    @http.route(
        "/wh40k/api/session/record_result",
        type="jsonrpc",
        auth="public",
        csrf=False,
        cors="*",
        methods=["POST"],
    )
    def api_record_result(self, results=None, **kwargs):
        return self._wrap(self._api_record_result, results=results, **kwargs)

    @http.route("/wh40k/api/health", type="http", auth="public", csrf=False)
    def health(self, **kwargs):
        return request.make_response(
            json.dumps({"ok": True, "service": "session"}),
            headers=[("Content-Type", "application/json")],
        )
