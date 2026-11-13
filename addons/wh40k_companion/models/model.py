from odoo import fields, models


class Wh40kModel(models.Model):
    _name = "wh40k.model"
    _description = "WH40k Model Profile"
    _order = "id"

    name = fields.Char(required=True)
    unit_id = fields.Many2one("wh40k.unit", required=True, ondelete="cascade", index=True)
    quantity = fields.Integer(default=1)
    movement = fields.Char(string="M")
    toughness = fields.Char(string="T")
    save = fields.Char(string="Sv")
    wounds = fields.Char(string="W")
    leadership = fields.Char(string="LD")
    objective_control = fields.Char(string="OC")
    invuln_save = fields.Char(string="InSv")
    base = fields.Char(string="Base")
    weapon_ids = fields.One2many("wh40k.weapon", "model_id", string="Weapons")
    ability_ids = fields.One2many("wh40k.ability", "model_id", string="Abilities")
