from odoo import fields, models


class Wh40kRule(models.Model):
    _name = "wh40k.rule"
    _description = "WH40k Army / Detachment Rule"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    description = fields.Text(translate=True)
    external_id = fields.Char(index=True)
    owner_uid = fields.Integer(
        string="Owner user id",
        index=True,
        help="External session user id. Not a res.partner in this database.",
    )
    force_ids = fields.Many2many(
        "wh40k.force",
        "wh40k_force_army_rule_rel",
        "rule_id",
        "force_id",
        string="Forces",
    )
    detachment_ids = fields.Many2many(
        "wh40k.detachment",
        "wh40k_detachment_rule_rel",
        "rule_id",
        "detachment_id",
        string="Detachments",
    )
