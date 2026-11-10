from odoo import fields, models


class Wh40kMission(models.Model):
    _name = "wh40k.mission"
    _description = "WH40k Mission"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    description = fields.Text()
    deployment = fields.Char()
    active = fields.Boolean(default=True)
