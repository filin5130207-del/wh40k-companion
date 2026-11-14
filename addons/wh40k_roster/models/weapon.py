from odoo import fields, models


class Wh40kWeapon(models.Model):
    _name = "wh40k.weapon"
    _description = "WH40k Weapon"
    _order = "weapon_type, name"

    name = fields.Char(required=True)
    model_id = fields.Many2one("wh40k.model", required=True, ondelete="cascade", index=True)
    weapon_type = fields.Selection(
        [
            ("melee", "Melee"),
            ("ranged", "Ranged"),
        ],
        required=True,
        default="ranged",
    )
    range = fields.Char()
    attacks = fields.Char(string="A")
    skill = fields.Char(string="WS/BS")
    strength = fields.Char(string="S")
    ap = fields.Char(string="AP")
    damage = fields.Char(string="D")
    keywords = fields.Char()
