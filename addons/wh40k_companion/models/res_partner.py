from odoo import api, fields, models
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    wh40k_nickname = fields.Char(string="WH40k Nickname", index=True, copy=False)
    wh40k_wins = fields.Integer(string="Wins", default=0)
    wh40k_losses = fields.Integer(string="Losses", default=0)
    wh40k_draws = fields.Integer(string="Draws", default=0)
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
    wh40k_roster_ids = fields.One2many(
        "wh40k.roster",
        "partner_id",
        string="Rosters",
    )

    _wh40k_nickname_uniq = models.Constraint(
        "unique(wh40k_nickname)",
        "WH40k nickname must be unique.",
    )

    @api.depends("wh40k_wins", "wh40k_losses", "wh40k_draws")
    def _compute_wh40k_stats(self):
        for partner in self:
            wins = partner.wh40k_wins or 0
            losses = partner.wh40k_losses or 0
            draws = partner.wh40k_draws or 0
            total = wins + losses + draws
            partner.wh40k_total_match = total
            partner.wh40k_win_rate = (wins * 100.0 / total) if total else 0.0

    def action_wh40k_record_result(self, won=None, outcome=None):
        """Update win/loss/draw counters after a finished match.

        ``won`` remains the surrender/win path. ``outcome`` is ``win``,
        ``loss``, or ``draw``.
        """
        self.ensure_one()
        if outcome is None:
            if won is None:
                raise UserError("Match result is required.")
            outcome = "win" if won else "loss"
        if outcome == "win":
            self.wh40k_wins += 1
        elif outcome == "loss":
            self.wh40k_losses += 1
        elif outcome == "draw":
            self.wh40k_draws += 1
        else:
            raise UserError("Unknown match result.")

    def to_wh40k_player_dict(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "nickname": self.wh40k_nickname or self.name,
            "has_nickname": bool(self.wh40k_nickname),
            "wins": self.wh40k_wins,
            "losses": self.wh40k_losses,
            "draws": self.wh40k_draws,
            "total_match": self.wh40k_total_match,
            "win_rate": self.wh40k_win_rate,
        }

    def get_wh40k_dashboard(self, pending_join_token=""):
        """Player home payload for the Battle App PWA."""
        self.ensure_one()
        rosters = self.env["wh40k.roster"].search(
            [("partner_id", "=", self.id)], order="create_date desc"
        )
        return {
            "player": self.to_wh40k_player_dict(),
            "pending_join_token": pending_join_token or "",
            "active_match": self.env["wh40k.match"].get_active_summary_for_partner(self),
            "rosters": [r.to_list_dict() for r in rosters],
        }

    def action_wh40k_set_nickname(self, nickname):
        self.ensure_one()
        if not nickname or not str(nickname).strip():
            raise UserError("Nickname is required.")
        self.wh40k_nickname = str(nickname).strip()
        return self.wh40k_nickname
