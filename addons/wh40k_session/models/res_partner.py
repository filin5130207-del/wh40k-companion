from odoo import api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    wh40k_nickname = fields.Char(string="WH40k Nickname", index=True, copy=False)
    wh40k_wins = fields.Integer(string="Wins", default=0)
    wh40k_losses = fields.Integer(string="Losses", default=0)
    wh40k_total_match = fields.Integer(
        string="Total Matches",
        compute="_compute_wh40k_stats",
        store=True,
    )
    wh40k_win_rate = fields.Float(
        string="Win Rate %",
        compute="_compute_wh40k_stats",
        store=True,
        digits=(16, 2),
    )

    _wh40k_nickname_uniq = models.Constraint(
        "unique(wh40k_nickname)",
        "WH40k nickname must be unique.",
    )

    @api.depends("wh40k_wins", "wh40k_losses")
    def _compute_wh40k_stats(self):
        for partner in self:
            total = (partner.wh40k_wins or 0) + (partner.wh40k_losses or 0)
            partner.wh40k_total_match = total
            partner.wh40k_win_rate = (partner.wh40k_wins * 100.0 / total) if total else 0.0

    def action_wh40k_record_result(self, won):
        """Update win/loss counters. Called once per stat event."""
        self.ensure_one()
        if won:
            self.wh40k_wins += 1
        else:
            self.wh40k_losses += 1

    def to_wh40k_player_dict(self, user):
        """``id`` is res.users id, the external id roster and match store."""
        self.ensure_one()
        return {
            "id": user.id,
            "name": self.name,
            "nickname": self.wh40k_nickname or self.name,
            "has_nickname": bool(self.wh40k_nickname),
            "wins": self.wh40k_wins,
            "losses": self.wh40k_losses,
            "total_match": self.wh40k_total_match,
            "win_rate": self.wh40k_win_rate,
        }

    def action_wh40k_set_nickname(self, nickname):
        self.ensure_one()
        if not nickname or not str(nickname).strip():
            raise UserError("Nickname is required.")
        self.wh40k_nickname = str(nickname).strip()
        return self.wh40k_nickname
