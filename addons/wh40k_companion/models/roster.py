from odoo import fields, models


class Wh40kRoster(models.Model):
    _name = "wh40k.roster"
    _description = "WH40k Roster"
    _order = "create_date desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, tracking=True)
    game_system = fields.Char()
    points_limit = fields.Integer(default=2000)
    points_used = fields.Integer(default=0)
    partner_id = fields.Many2one(
        "res.partner",
        string="Owner",
        required=True,
        default=lambda self: self.env.user.partner_id,
        index=True,
        ondelete="cascade",
    )
    force_ids = fields.One2many("wh40k.force", "roster_id", string="Forces")
    unit_count = fields.Integer(compute="_compute_counts")
    weapon_count = fields.Integer(compute="_compute_counts")
    ability_count = fields.Integer(compute="_compute_counts")

    def _compute_counts(self):
        for roster in self:
            units = roster.force_ids.mapped("detachment_ids.unit_ids")
            models = units.mapped("model_ids")
            roster.unit_count = len(units)
            roster.weapon_count = len(models.mapped("weapon_ids"))
            roster.ability_count = len(units.mapped("ability_ids")) + len(
                models.mapped("ability_ids")
            )
