from odoo import fields, models


class Wh40kDetachment(models.Model):
    _name = "wh40k.detachment"
    _description = "WH40k Detachment"
    _order = "id"

    name = fields.Char(required=True)
    force_id = fields.Many2one("wh40k.force", required=True, ondelete="cascade", index=True)
    detachment_rule_ids = fields.Many2many(
        "wh40k.rule",
        "wh40k_detachment_rule_rel",
        "detachment_id",
        "rule_id",
        string="Detachment Rules",
    )
    unit_ids = fields.One2many("wh40k.unit", "detachment_id", string="Units")
