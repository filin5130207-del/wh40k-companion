import json
import logging
import re

from odoo import http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from odoo.http.session import authenticate

from ..parsers.battlescribe_parser import BattlescribeParser

_logger = logging.getLogger(__name__)


class Wh40kCompanionController(http.Controller):
    """Thin HTTP/JSON layer for the Battle App PWA.

    Business rules live on model methods; routes authenticate, call models, return DTO.
    Canonical JSON prefix: ``/wh40k/api/...``. Legacy ``/wh40k/...`` paths stay as aliases.
    """

    def _partner(self):
        partner = request.env.user.partner_id
        if not partner:
            raise AccessError("No partner linked to the current user.")
        return partner

    def _json_error(self, exc):
        if isinstance(exc, AccessError):
            _logger.warning("WH40k access denied: %s", exc)
            return {"ok": False, "error": str(exc)}
        if isinstance(exc, (UserError, ValidationError)):
            return {"ok": False, "error": str(exc)}
        _logger.exception("WH40k companion error")
        return {"ok": False, "error": "Internal server error."}

    def _ok(self, **payload):
        data = {"ok": True}
        data.update(payload)
        return data

    def _public_base_url(self):
        """Prefer a non-loopback host so QR/join links work on LAN phones."""
        icp = request.env["ir.config_parameter"].sudo()
        configured = (icp.get_str("web.base.url") or "").rstrip("/")
        host_url = (request.httprequest.url_root or "").rstrip("/")

        def _is_loopback(url):
            low = (url or "").lower()
            return (
                "://127.0.0.1" in low
                or "://localhost" in low
                or "://[::1]" in low
            )

        if host_url and not _is_loopback(host_url):
            return host_url
        if configured and not _is_loopback(configured):
            return configured
        return host_url or configured

    def _parse_roster_payload(self, roster_json=None, **kwargs):
        if roster_json is None:
            roster_json = kwargs.get("params", {}).get("roster_json") if kwargs else None
        if not roster_json:
            raise UserError("Missing roster_json payload.")
        if isinstance(roster_json, str):
            data = json.loads(roster_json)
        else:
            data = roster_json
        return BattlescribeParser(data)

    def _pwa_render_values(self):
        return {
            "session_info": request.env["ir.http"].get_frontend_session_info(),
            "debug": request.session.debug if hasattr(request.session, "debug") else "",
        }

    # ------------------------------------------------------------ public pages
    @http.route("/wh40k", type="http", auth="public", website=False, sitemap=False)
    def wh40k_landing(self, **kwargs):
        return request.render(
            "wh40k_companion.landing_page",
            {
                "error": kwargs.get("error"),
                "message": kwargs.get("message"),
            },
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
                credential = {
                    "login": email,
                    "password": password,
                    "type": "password",
                }
                authenticate(request.session, request.env, credential)
                if join:
                    request.session["wh40k_pending_join"] = join
                    return request.redirect(f"/wh40k/join/{join}")
                return request.redirect("/wh40k/app")
            except (UserError, ValidationError) as exc:
                error = str(exc)
            except Exception:  # noqa: BLE001 — never leak internals on public form
                _logger.exception("WH40k signup failed")
                error = "Could not create the account. Please try again."
        return request.render(
            "wh40k_companion.signup_page",
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
        """Battle App PWA shell (standalone OWL), not the backend client action."""
        join = (
            kwargs.get("wh40k_join")
            or kwargs.get("join")
            or request.session.get("wh40k_pending_join")
            or ""
        )
        if join:
            request.session["wh40k_pending_join"] = join
        return request.render("wh40k_companion.pwa_shell", self._pwa_render_values())

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
                    "src": f"{base}/wh40k_companion/static/description/icon.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": f"{base}/wh40k_companion/static/description/icon.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
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
        """Served from /wh40k/ so SW scope covers the PWA entry."""
        try:
            from odoo.tools.misc import file_path

            path = file_path("wh40k_companion/static/src/pwa/sw.js")
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except Exception:
            _logger.exception("Failed to load PWA service worker")
            content = (
                "/* WH40k Battle App SW fallback */\n"
                "self.addEventListener('install', (e) => self.skipWaiting());\n"
                "self.addEventListener('activate', (e) => "
                "e.waitUntil(self.clients.claim()));\n"
            )
        return request.make_response(
            content,
            headers=[
                ("Content-Type", "application/javascript; charset=utf-8"),
                ("Service-Worker-Allowed", "/wh40k/"),
                ("Cache-Control", "no-cache"),
            ],
        )

    # ================================================================ JSON API
    def _api_roster_preview(self, roster_json=None, **kwargs):
        parser = self._parse_roster_payload(roster_json=roster_json, **kwargs)
        return self._ok(preview=parser.preview())

    def _api_roster_import(self, roster_json=None, name=None, **kwargs):
        partner = self._partner()
        parser = self._parse_roster_payload(roster_json=roster_json, **kwargs)
        parsed = parser.parse()
        if name:
            parsed["name"] = name
        roster = request.env["wh40k.roster"].action_import_parsed(partner, parsed)
        return self._ok(
            roster_id=roster.id,
            name=roster.name,
            points_used=roster.points_used,
            points_limit=roster.points_limit,
            summary=parser.summary(),
            preview=parser.preview(),
        )

    def _api_dashboard(self, **kwargs):
        partner = self._partner()
        payload = partner.get_wh40k_dashboard(
            pending_join_token=request.session.get("wh40k_pending_join") or ""
        )
        return self._ok(**payload)

    def _api_match_active(self, **kwargs):
        partner = self._partner()
        return self._ok(
            active_match=request.env["wh40k.match"].get_active_summary_for_partner(
                partner
            )
        )

    def _api_set_nickname(self, nickname=None, **kwargs):
        partner = self._partner()
        value = partner.action_wh40k_set_nickname(nickname)
        return self._ok(nickname=value)

    def _api_list_missions(self, **kwargs):
        return self._ok(missions=request.env["wh40k.mission"].list_active_dicts())

    def _api_match_create(self, roster_id=None, mission_id=None, points="2000", **kwargs):
        partner = self._partner()
        roster = request.env["wh40k.roster"].browse(int(roster_id))
        mission = (
            request.env["wh40k.mission"].browse(int(mission_id)) if mission_id else False
        )
        match = request.env["wh40k.match"].action_create_for_host(
            partner, roster, mission, points
        )
        return self._ok(match_id=match.id, match_token=match.match_token)

    def _api_match_publish(self, match_id=None, **kwargs):
        partner = self._partner()
        match = request.env["wh40k.match"].browse(int(match_id))
        if not match.exists() or match.host_id.id != partner.id:
            raise UserError("Match not found.")
        match.action_publish()
        return self._ok(**match.to_publish_dict(base_url=self._public_base_url()))

    def _api_match_verify(self, match_token=None, **kwargs):
        match = request.env["wh40k.match"].find_by_token(match_token)
        payload = match.to_verify_dict()
        pending = request.session.get("wh40k_pending_join")
        if pending and match_token and pending == match_token:
            request.session.pop("wh40k_pending_join", None)
        return self._ok(**payload)

    def _api_match_accept(self, match_token=None, **kwargs):
        partner = self._partner()
        match = request.env["wh40k.match"].find_by_token(match_token)
        match.action_accept_invite(partner)
        return self._ok(**match.to_eligible_rosters_dict(partner))

    def _api_match_join(self, match_token=None, roster_id=None, **kwargs):
        partner = self._partner()
        match = request.env["wh40k.match"].find_by_token(match_token)
        roster = request.env["wh40k.roster"].browse(int(roster_id))
        if not roster.exists():
            raise UserError("Invalid roster.")
        if match.state == "waiting":
            match.action_accept_invite(partner)
        match.action_join(partner, roster)
        return self._ok(match_id=match.id, state=match.state)

    def _api_eligible_rosters(self, match_token=None, **kwargs):
        partner = self._partner()
        match = request.env["wh40k.match"].find_by_token(match_token)
        return self._ok(**match.to_eligible_rosters_dict(partner))

    def _api_match_state(self, match_id=None, **kwargs):
        partner = self._partner()
        match = request.env["wh40k.match"].browse(int(match_id))
        if not match.exists():
            raise UserError("Match not found.")
        return self._ok(
            match=match.to_state_dict(partner, base_url=self._public_base_url())
        )

    def _api_match_unit_state(self, match_id=None, unit_state=None, **kwargs):
        partner = self._partner()
        match = request.env["wh40k.match"].browse(int(match_id))
        if not match.exists():
            raise UserError("Match not found.")
        match._assert_participant(partner)
        match.action_update_unit_state(unit_state, updating_partner=partner)
        return self._ok()

    def _api_match_surrender(self, match_id=None, **kwargs):
        partner = self._partner()
        match = request.env["wh40k.match"].browse(int(match_id))
        if not match.exists():
            raise UserError("Match not found.")
        match.action_surrender(partner)
        return self._ok(**match.to_surrender_result_dict(partner))

    def _api_match_cancel(self, match_id=None, reason=None, **kwargs):
        partner = self._partner()
        match = request.env["wh40k.match"].browse(int(match_id))
        if not match.exists() or match.host_id.id != partner.id:
            raise UserError("Match not found.")
        if match.state == "cancelled":
            return self._ok(
                state=match.state, cancel_reason=match.cancel_reason or ""
            )
        cancel_reason = (reason or "").strip() or "Cancelled by host"
        match.action_cancel(reason=cancel_reason)
        return self._ok(state=match.state, cancel_reason=match.cancel_reason or "")

    def _api_match_watch(self, match_id=None, since=None, timeout=20, **kwargs):
        """Long-poll match changes (server-driven updates without blind 5s spam)."""
        partner = self._partner()
        match = request.env["wh40k.match"].browse(int(match_id))
        if not match.exists():
            raise UserError("Match not found.")
        changed, write_date = match.wait_for_change(
            since_write_date=since, timeout_seconds=timeout
        )
        return self._ok(
            changed=bool(changed),
            write_date=write_date,
            match=match.to_state_dict(partner, base_url=self._public_base_url()),
        )

    def _api_roster_detail(self, roster_id, **kwargs):
        partner = self._partner()
        # Browse with sudo so owner-domain ACL does not 404 opponent reads;
        # to_detail_dict enforces owner / active-match participant checks.
        roster = request.env["wh40k.roster"].sudo().browse(int(roster_id))
        if not roster.exists():
            raise UserError("Roster not found.")
        return self._ok(roster=roster.to_detail_dict(partner))

    def _wrap(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — normalized JSON errors for PWA
            return self._json_error(exc)

    # ---- canonical /wh40k/api/* ------------------------------------------------
    @http.route("/wh40k/api/roster/preview", type="jsonrpc", auth="user", methods=["POST"])
    def api_roster_preview(self, roster_json=None, **kwargs):
        return self._wrap(self._api_roster_preview, roster_json=roster_json, **kwargs)

    @http.route("/wh40k/api/roster/import", type="jsonrpc", auth="user", methods=["POST"])
    def api_roster_import(self, roster_json=None, name=None, **kwargs):
        return self._wrap(
            self._api_roster_import, roster_json=roster_json, name=name, **kwargs
        )

    @http.route("/wh40k/api/player/dashboard", type="jsonrpc", auth="user")
    def api_player_dashboard(self, **kwargs):
        return self._wrap(self._api_dashboard, **kwargs)

    @http.route("/wh40k/api/match/active", type="jsonrpc", auth="user")
    def api_match_active(self, **kwargs):
        return self._wrap(self._api_match_active, **kwargs)

    @http.route("/wh40k/api/player/nickname", type="jsonrpc", auth="user")
    def api_set_nickname(self, nickname=None, **kwargs):
        return self._wrap(self._api_set_nickname, nickname=nickname, **kwargs)

    @http.route("/wh40k/api/missions", type="jsonrpc", auth="user")
    def api_list_missions(self, **kwargs):
        return self._wrap(self._api_list_missions, **kwargs)

    @http.route("/wh40k/api/match/create", type="jsonrpc", auth="user")
    def api_match_create(self, roster_id=None, mission_id=None, points="2000", **kwargs):
        return self._wrap(
            self._api_match_create,
            roster_id=roster_id,
            mission_id=mission_id,
            points=points,
            **kwargs,
        )

    @http.route("/wh40k/api/match/publish", type="jsonrpc", auth="user")
    def api_match_publish(self, match_id=None, **kwargs):
        return self._wrap(self._api_match_publish, match_id=match_id, **kwargs)

    @http.route("/wh40k/api/match/verify", type="jsonrpc", auth="user")
    def api_match_verify(self, match_token=None, **kwargs):
        return self._wrap(self._api_match_verify, match_token=match_token, **kwargs)

    @http.route("/wh40k/api/match/accept", type="jsonrpc", auth="user")
    def api_match_accept(self, match_token=None, **kwargs):
        return self._wrap(self._api_match_accept, match_token=match_token, **kwargs)

    @http.route("/wh40k/api/match/join", type="jsonrpc", auth="user")
    def api_match_join(self, match_token=None, roster_id=None, **kwargs):
        return self._wrap(
            self._api_match_join, match_token=match_token, roster_id=roster_id, **kwargs
        )

    @http.route("/wh40k/api/match/eligible_rosters", type="jsonrpc", auth="user")
    def api_eligible_rosters(self, match_token=None, **kwargs):
        return self._wrap(self._api_eligible_rosters, match_token=match_token, **kwargs)

    @http.route("/wh40k/api/match/state", type="jsonrpc", auth="user")
    def api_match_state(self, match_id=None, **kwargs):
        return self._wrap(self._api_match_state, match_id=match_id, **kwargs)

    @http.route(
        "/wh40k/api/match/unit_state", type="jsonrpc", auth="user", methods=["POST"]
    )
    def api_match_unit_state(self, match_id=None, unit_state=None, **kwargs):
        return self._wrap(
            self._api_match_unit_state,
            match_id=match_id,
            unit_state=unit_state,
            **kwargs,
        )

    @http.route("/wh40k/api/match/surrender", type="jsonrpc", auth="user")
    def api_match_surrender(self, match_id=None, **kwargs):
        return self._wrap(self._api_match_surrender, match_id=match_id, **kwargs)

    @http.route("/wh40k/api/match/cancel", type="jsonrpc", auth="user")
    def api_match_cancel(self, match_id=None, reason=None, **kwargs):
        return self._wrap(
            self._api_match_cancel, match_id=match_id, reason=reason, **kwargs
        )

    @http.route("/wh40k/api/match/watch", type="jsonrpc", auth="user")
    def api_match_watch(self, match_id=None, since=None, timeout=20, **kwargs):
        return self._wrap(
            self._api_match_watch,
            match_id=match_id,
            since=since,
            timeout=timeout,
            **kwargs,
        )

    @http.route(
        "/wh40k/api/roster/<int:roster_id>/detail", type="jsonrpc", auth="user"
    )
    def api_roster_detail(self, roster_id, **kwargs):
        return self._wrap(self._api_roster_detail, roster_id, **kwargs)

    # ---- legacy aliases (same handlers) ---------------------------------------
    @http.route("/wh40k/roster/preview", type="jsonrpc", auth="user", methods=["POST"])
    def roster_preview(self, roster_json=None, **kwargs):
        return self.api_roster_preview(roster_json=roster_json, **kwargs)

    @http.route("/wh40k/roster/import", type="jsonrpc", auth="user", methods=["POST"])
    def roster_import(self, roster_json=None, name=None, **kwargs):
        return self.api_roster_import(roster_json=roster_json, name=name, **kwargs)

    @http.route("/wh40k/player/dashboard", type="jsonrpc", auth="user")
    def player_dashboard(self, **kwargs):
        return self.api_player_dashboard(**kwargs)

    @http.route("/wh40k/match/active", type="jsonrpc", auth="user")
    def match_active(self, **kwargs):
        return self.api_match_active(**kwargs)

    @http.route("/wh40k/player/nickname", type="jsonrpc", auth="user")
    def set_nickname(self, nickname=None, **kwargs):
        return self.api_set_nickname(nickname=nickname, **kwargs)

    @http.route("/wh40k/missions", type="jsonrpc", auth="user")
    def list_missions(self, **kwargs):
        return self.api_list_missions(**kwargs)

    @http.route("/wh40k/match/create", type="jsonrpc", auth="user")
    def match_create(self, roster_id=None, mission_id=None, points="2000", **kwargs):
        return self.api_match_create(
            roster_id=roster_id, mission_id=mission_id, points=points, **kwargs
        )

    @http.route("/wh40k/match/publish", type="jsonrpc", auth="user")
    def match_publish(self, match_id=None, **kwargs):
        return self.api_match_publish(match_id=match_id, **kwargs)

    @http.route("/wh40k/match/verify", type="jsonrpc", auth="user")
    def match_verify(self, match_token=None, **kwargs):
        return self.api_match_verify(match_token=match_token, **kwargs)

    @http.route("/wh40k/match/accept", type="jsonrpc", auth="user")
    def match_accept(self, match_token=None, **kwargs):
        return self.api_match_accept(match_token=match_token, **kwargs)

    @http.route("/wh40k/match/join", type="jsonrpc", auth="user")
    def match_join(self, match_token=None, roster_id=None, **kwargs):
        return self.api_match_join(
            match_token=match_token, roster_id=roster_id, **kwargs
        )

    @http.route("/wh40k/match/eligible_rosters", type="jsonrpc", auth="user")
    def eligible_rosters(self, match_token=None, **kwargs):
        return self.api_eligible_rosters(match_token=match_token, **kwargs)

    @http.route("/wh40k/match/state", type="jsonrpc", auth="user")
    def match_state(self, match_id=None, **kwargs):
        return self.api_match_state(match_id=match_id, **kwargs)

    @http.route("/wh40k/match/unit_state", type="jsonrpc", auth="user", methods=["POST"])
    def match_unit_state(self, match_id=None, unit_state=None, **kwargs):
        return self.api_match_unit_state(
            match_id=match_id, unit_state=unit_state, **kwargs
        )

    @http.route("/wh40k/match/surrender", type="jsonrpc", auth="user")
    def match_surrender(self, match_id=None, **kwargs):
        return self.api_match_surrender(match_id=match_id, **kwargs)

    @http.route("/wh40k/match/cancel", type="jsonrpc", auth="user")
    def match_cancel(self, match_id=None, reason=None, **kwargs):
        return self.api_match_cancel(match_id=match_id, reason=reason, **kwargs)

    @http.route("/wh40k/match/watch", type="jsonrpc", auth="user")
    def match_watch(self, match_id=None, since=None, timeout=20, **kwargs):
        return self.api_match_watch(
            match_id=match_id, since=since, timeout=timeout, **kwargs
        )

    @http.route("/wh40k/roster/<int:roster_id>/detail", type="jsonrpc", auth="user")
    def roster_detail(self, roster_id, **kwargs):
        return self.api_roster_detail(roster_id, **kwargs)

    # ------------------------------------------------------------------- misc
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
        """Local QR for join URLs only (no public open-proxy to QR CDNs)."""
        from ..utils.qr_png import render_join_qr_png

        try:
            size_i = max(80, min(512, int(size or 260)))
        except (TypeError, ValueError):
            size_i = 260
        try:
            content = render_join_qr_png(data, size=size_i)
        except ValueError:
            return request.not_found()
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
        """QR / deep-link entry: stash token and open PWA join (after login if needed)."""
        token = (match_token or "").strip()
        if not re.match(r"^[a-fA-F0-9-]{16,64}$", token):
            return request.redirect("/wh40k?error=Invalid+join+link")
        request.session["wh40k_pending_join"] = token
        if not request.session.uid:
            return request.render(
                "wh40k_companion.join_gate",
                {
                    "match_token": token,
                    "login_url": f"/web/login?redirect=/wh40k/join/{token}",
                    "signup_url": f"/wh40k/signup?join={token}",
                },
            )
        return request.redirect(f"/wh40k/app?wh40k_join={token}")
