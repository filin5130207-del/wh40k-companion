from odoo import fields, models


class Wh40kForce(models.Model):
    _name = "wh40k.force"
    _description = "WH40k Force"
    _order = "id"

    name = fields.Char(required=True)
    roster_id = fields.Many2one("wh40k.roster", required=True, ondelete="cascade", index=True)
    catalogue_name = fields.Char()
    army_rule_ids = fields.Many2many(
        "wh40k.rule",
        "wh40k_force_army_rule_rel",
        "force_id",
        "rule_id",
        string="Army Rules",
    )
    detachment_ids = fields.One2many("wh40k.detachment", "force_id", string="Detachments")
