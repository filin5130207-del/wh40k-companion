import logging
import re

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def _wh40k_player_group(self):
        return self.env.ref("wh40k_session.group_player", raise_if_not_found=False)

    @api.model
    def _wh40k_battle_action(self):
        return self.env.ref("wh40k_session.action_wh40k_pwa", raise_if_not_found=False)

    def _wh40k_group_names(self):
        self.ensure_one()
        names = []
        if self.has_group("wh40k_session.group_manager"):
            names.append("manager")
        if self.has_group("wh40k_session.group_player") or "manager" in names:
            names.append("player")
        return names

    def _wh40k_issue_token(self, secret):
        self.ensure_one()
        from wh40k_token import issue_user_token

        partner = self.partner_id
        nickname = partner.wh40k_nickname or partner.name or self.name
        return issue_user_token(
            uid=self.id,
            login=self.login,
            nickname=nickname,
            groups=self._wh40k_group_names(),
            secret=secret,
        )

    @api.model
    def action_wh40k_signup(self, email, password, nickname):
        """Create a Player user. The only sudo boundary for public signup."""
        email = (email or "").strip().lower()
        nickname = (nickname or "").strip()
        password = password or ""
        if not email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise UserError("Enter a valid email address.")
        if len(password) < 8:
            raise UserError("Password must be at least 8 characters.")
        if not nickname or len(nickname) < 3:
            raise UserError("Nickname must be at least 3 characters.")

        Users = self.sudo()
        if Users.search([("login", "=", email)], limit=1):
            raise UserError("An account with this email already exists.")
        Partner = self.env["res.partner"].sudo()
        if Partner.search([("wh40k_nickname", "=", nickname)], limit=1):
            raise UserError("This nickname is already taken.")

        group_player = self.env.ref("wh40k_session.group_player")
        action = self._wh40k_battle_action()
        user = Users.with_context(no_reset_password=True).create(
            {
                "name": nickname,
                "login": email,
                "email": email,
                "password": password,
                "group_ids": [(6, 0, [group_player.id])],
                "action_id": action.id if action else False,
            }
        )
        user.partner_id.write({"wh40k_nickname": nickname})
        return user

    def _wh40k_grant_player_access(self):
        group = self._wh40k_player_group()
        action = self._wh40k_battle_action()
        if not group:
            return self.browse()
        portal = self.env.ref("base.group_portal", raise_if_not_found=False)
        public = self.env.ref("base.group_public", raise_if_not_found=False)
        for user in self:
            groups = user.group_ids
            if portal:
                groups -= portal
            if public:
                groups -= public
            groups |= group
            vals = {"group_ids": [(6, 0, groups.ids)]}
            if action and not user.action_id:
                vals["action_id"] = action.id
            user.sudo().write(vals)
        return self

    @api.model
    def _wh40k_repair_player_access(self):
        Partner = self.env["res.partner"].sudo()
        nicknamed = Partner.search([("wh40k_nickname", "!=", False)]).user_ids
        portal = self.env.ref("base.group_portal", raise_if_not_found=False)
        stuck = self.browse()
        if portal:
            skip_xmlids = (
                "base.user_root",
                "base.user_admin",
                "base.public_user",
                "base.template_portal_user_id",
            )
            skip_ids = set()
            for xid in skip_xmlids:
                rec = self.env.ref(xid, raise_if_not_found=False)
                if rec:
                    skip_ids.add(rec.id)
            stuck = self.sudo().search(
                [
                    ("active", "=", True),
                    ("share", "=", True),
                    ("group_ids", "in", [portal.id]),
                    ("id", "not in", list(skip_ids) or [0]),
                    ("login", "not in", ("portal", "public", "portaltemplate")),
                ]
            )
        users = nicknamed | stuck
        if not users:
            _logger.info("WH40k session: no users needed player access repair")
            return
        _logger.info("WH40k session: granting player access to %s users", len(users))
        users._wh40k_grant_player_access()
