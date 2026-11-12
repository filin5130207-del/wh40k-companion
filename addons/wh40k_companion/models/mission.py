from odoo import api, fields, models


class Wh40kMission(models.Model):
    _name = "wh40k.mission"
    _description = "WH40k Mission"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    description = fields.Text(translate=True)
    deployment = fields.Char(translate=True)
    active = fields.Boolean(default=True)

    def to_dict(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description or "",
            "deployment": self.deployment or "",
        }

    @api.model
    def list_active_dicts(self):
        return [m.to_dict() for m in self.search([("active", "=", True)])]
