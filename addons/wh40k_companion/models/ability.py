from odoo import fields, models


class Wh40kAbility(models.Model):
    _name = "wh40k.ability"
    _description = "WH40k Ability"
    _order = "name"

    name = fields.Char(required=True)
    description = fields.Text()
    unit_id = fields.Many2one("wh40k.unit", ondelete="cascade", index=True)
    model_id = fields.Many2one("wh40k.model", ondelete="cascade", index=True)
