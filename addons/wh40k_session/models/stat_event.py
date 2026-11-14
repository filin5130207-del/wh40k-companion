from odoo import api, fields, models
from odoo.exceptions import UserError


class Wh40kStatEvent(models.Model):
    """Idempotent win/loss applied from the match service.

    Match ids are not foreign keys: they belong to another database.
    """

    _name = "wh40k.stat.event"
    _description = "WH40k Match Stat Event"
    _order = "id desc"

    match_ref = fields.Integer(required=True, index=True)
    user_uid = fields.Integer(required=True, index=True)
    won = fields.Boolean()

    _wh40k_stat_event_uniq = models.Constraint(
        "unique(match_ref, user_uid)",
        "This match result was already recorded for the user.",
    )

    @api.model
    def record_results(self, results):
        if not isinstance(results, list) or not results:
            raise UserError("Missing results.")
        Users = self.env["res.users"].sudo()
        applied = 0
        for item in results:
            if not isinstance(item, dict):
                continue
            match_ref = int(item.get("match_ref") or 0)
            uid = int(item.get("uid") or 0)
            if not match_ref or not uid:
                continue
            existing = self.sudo().search(
                [("match_ref", "=", match_ref), ("user_uid", "=", uid)],
                limit=1,
            )
            if existing:
                continue
            user = Users.browse(uid)
            if not user.exists() or not user.partner_id:
                continue
            won = bool(item.get("won"))
            self.sudo().create(
                {"match_ref": match_ref, "user_uid": uid, "won": won}
            )
            user.partner_id.sudo().action_wh40k_record_result(won)
            applied += 1
        return applied
