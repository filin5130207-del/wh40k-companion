from odoo import fields, models


class Wh40kUnit(models.Model):
    _name = "wh40k.unit"
    _description = "WH40k Unit"
    _order = "id"

    name = fields.Char(required=True)
    detachment_id = fields.Many2one(
        "wh40k.detachment",
        required=True,
        ondelete="cascade",
        index=True,
    )
    quantity = fields.Integer(default=1)
    points = fields.Integer(default=0)
    keywords = fields.Char()
    model_ids = fields.One2many("wh40k.model", "unit_id", string="Models")
    ability_ids = fields.One2many("wh40k.ability", "unit_id", string="Abilities")
    # Live game tracking (per match copy kept on match.unit_state JSON;
    # these fields hold imported defaults / optional overrides)
    current_models = fields.Integer(string="Models Remaining")
    current_wounds = fields.Integer(string="Wounds Remaining")
