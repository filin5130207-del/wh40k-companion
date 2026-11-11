import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def _wh40k_player_group(self):
        return self.env.ref("wh40k_companion.group_player", raise_if_not_found=False)

    @api.model
    def _wh40k_battle_action(self):
        return self.env.ref(
            "wh40k_companion.action_wh40k_companion_client", raise_if_not_found=False
        )

    def _wh40k_grant_player_access(self):
        """Promote users to internal WH40k players with Battle App as home action."""
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
        """Upgrade hook: grant Player to nickname users and strip accidental portal."""
        Partner = self.env["res.partner"].sudo()
        nicknamed = Partner.search([("wh40k_nickname", "!=", False)]).user_ids
        # Repair active custom portal accounts from auth_signup (/web/signup).
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
            _logger.info("WH40k: no users needed player access repair")
            return
        _logger.info("WH40k: granting player access to %s users", len(users))
        users._wh40k_grant_player_access()