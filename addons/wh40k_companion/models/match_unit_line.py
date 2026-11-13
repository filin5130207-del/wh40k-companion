import json

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class Wh40kMatchUnitLine(models.Model):
    _name = "wh40k.match.unit.line"
    _description = "WH40k Match Unit Line"
    _order = "side, id"

    match_id = fields.Many2one(
        "wh40k.match",
        required=True,
        ondelete="cascade",
        index=True,
    )
    unit_id = fields.Many2one("wh40k.unit", required=True, ondelete="restrict", index=True)
    side = fields.Selection(
        [
            ("host", "Host"),
            ("guest", "Guest"),
        ],
        required=True,
        index=True,
    )
    name = fields.Char(required=True)
    models = fields.Integer(string="Models", default=1)
    models_remaining = fields.Integer(string="Models Remaining", default=1)
    wounds = fields.Integer(string="Wounds", default=1)
    wounds_remaining = fields.Integer(string="Wounds Remaining", default=1)
    destroyed = fields.Boolean(default=False)
    undo_stack = fields.Text(
        string="Undo Stack JSON",
        help="List of prior snapshots for undo (own side only).",
        default="[]",
    )

    def _undo_list(self):
        self.ensure_one()
        try:
            data = json.loads(self.undo_stack or "[]")
        except json.JSONDecodeError:
            data = []
        return data if isinstance(data, list) else []

    def set_undo_list(self, stack):
        self.ensure_one()
        if not isinstance(stack, list):
            stack = []
        self.undo_stack = json.dumps(stack[-20:])

    def to_state_entry(self):
        self.ensure_one()
        return {
            "line_id": self.id,
            "unit_id": self.unit_id.id,
            "side": self.side,
            "name": self.name,
            "models": self.models,
            "models_remaining": self.models_remaining,
            "wounds": self.wounds,
            "wounds_remaining": self.wounds_remaining,
            "destroyed": bool(self.destroyed),
        }

    @api.model
    def _assert_side_owner(self, match, side, partner):
        if side == "host" and match.host_id.id == partner.id:
            return
        if side == "guest" and match.guest_id and match.guest_id.id == partner.id:
            return
        raise AccessError("You can only update your own army lines.")

    def action_apply_snapshot(self, values, undo_stack=None):
        """Update tracking fields from a client snapshot (own side)."""
        self.ensure_one()
        if self.match_id.state != "active":
            raise UserError("Unit state can only be updated during an active match.")
        vals = {
            "models_remaining": int(values.get("models_remaining", self.models_remaining)),
            "wounds_remaining": int(values.get("wounds_remaining", self.wounds_remaining)),
            "destroyed": bool(values.get("destroyed", self.destroyed)),
        }
        vals["models_remaining"] = max(0, min(self.models, vals["models_remaining"]))
        vals["wounds_remaining"] = max(0, min(self.wounds, vals["wounds_remaining"]))
        if vals["models_remaining"] == 0 or vals["wounds_remaining"] == 0:
            vals["destroyed"] = True
            vals["models_remaining"] = 0
            vals["wounds_remaining"] = 0
        self.write(vals)
        if undo_stack is not None:
            self.set_undo_list(undo_stack)
        return True
