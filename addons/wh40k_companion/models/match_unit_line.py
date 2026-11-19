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
    # Monotonic per match. Watch uses (match_id, rev) to return changed lines only.
    rev = fields.Integer(default=0)
    # Own-side updates filter (match_id, side); delta reads filter (match_id, rev).
    _match_side_idx = models.Index("(match_id, side)")
    _match_rev_idx = models.Index("(match_id, rev)")
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
    # One JSON object per miniature, expanded from the roster's wh40k.model rows.
    model_state = fields.Text(
        string="Model State JSON",
        help="Living miniatures for this squad. Squad M and W are the sum of these rows.",
        default="[]",
    )
    MODEL_UNDO_LIMIT = 20

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

    @api.model
    def _wound_value(self, value):
        text = str(value if value not in (None, False) else "1").replace("+", "").strip() or "1"
        try:
            parsed = int(text)
        except ValueError:
            parsed = 1
        return max(parsed, 1)

    @api.model
    def _slots_from_unit(self, unit):
        """One dropdown row per miniature on the roster models of ``unit``."""
        slots = []
        if not unit:
            return slots
        for model in unit.model_ids:
            qty = int(model.quantity or 1)
            if qty < 1:
                qty = 1
            wounds = self._wound_value(model.wounds)
            name = model.name or unit.name or "Model"
            for index in range(qty):
                slots.append(
                    {
                        "key": "%s:%s" % (model.id, index),
                        "model_id": model.id,
                        "index": index,
                        "name": name if qty == 1 else "%s %s" % (name, index + 1),
                        "models": 1,
                        "models_remaining": 1,
                        "wounds": wounds,
                        "wounds_remaining": wounds,
                        "destroyed": False,
                        "undo": [],
                    }
                )
        if slots:
            return slots
        count = int(unit.quantity or 1) or 1
        if count < 1:
            count = 1
        name = unit.name or "Model"
        for index in range(count):
            slots.append(
                {
                    "key": "unit:%s:%s" % (unit.id, index),
                    "model_id": False,
                    "index": index,
                    "name": name if count == 1 else "%s %s" % (name, index + 1),
                    "models": 1,
                    "models_remaining": 1,
                    "wounds": 1,
                    "wounds_remaining": 1,
                    "destroyed": False,
                    "undo": [],
                }
            )
        return slots

    def _parsed_model_state(self):
        self.ensure_one()
        try:
            data = json.loads(self.model_state or "[]")
        except json.JSONDecodeError:
            data = []
        return data if isinstance(data, list) else []

    def model_rows(self):
        """Stored miniatures, or a roster seed fitted to the current squad totals."""
        self.ensure_one()
        rows = self._parsed_model_state()
        if rows:
            return rows
        unit = self.unit_id.sudo() if self.unit_id else self.unit_id
        seeded = self._slots_from_unit(unit)
        return self._fit_rows(seeded, self.models_remaining, self.wounds_remaining)

    @api.model
    def _fit_rows(self, rows, target_models, target_wounds):
        """Reset roster rows to full health, then shave them down to squad totals."""
        fitted = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            models = max(1, int(row.get("models") or 1))
            wounds = max(1, int(row.get("wounds") or 1))
            fitted.append(
                {
                    "key": row.get("key"),
                    "model_id": row.get("model_id"),
                    "index": int(row.get("index") or 0),
                    "name": row.get("name") or "",
                    "models": models,
                    "models_remaining": models,
                    "wounds": wounds,
                    "wounds_remaining": wounds,
                    "destroyed": False,
                    "undo": [],
                }
            )
        if not fitted:
            return fitted
        try:
            target_models = max(0, int(target_models))
            target_wounds = max(0, int(target_wounds))
        except (TypeError, ValueError):
            target_models = 0
            target_wounds = 0
        if target_models == 0 or target_wounds == 0:
            for item in fitted:
                item["models_remaining"] = 0
                item["wounds_remaining"] = 0
                item["destroyed"] = True
            return fitted
        guard = 0
        while sum(item["models_remaining"] for item in fitted) > target_models and guard < 10000:
            guard += 1
            for item in reversed(fitted):
                if item["models_remaining"] <= 0:
                    continue
                item["models_remaining"] -= 1
                if item["models_remaining"] <= 0:
                    item["models_remaining"] = 0
                    item["wounds_remaining"] = 0
                    item["destroyed"] = True
                else:
                    share = item["wounds"] // item["models"] if item["models"] else item["wounds"]
                    item["wounds_remaining"] = max(0, item["wounds_remaining"] - share)
                break
        guard = 0
        while sum(item["wounds_remaining"] for item in fitted) > target_wounds and guard < 10000:
            guard += 1
            progressed = False
            for item in reversed(fitted):
                if item["wounds_remaining"] <= 0:
                    continue
                item["wounds_remaining"] -= 1
                progressed = True
                if item["wounds_remaining"] <= 0:
                    item["models_remaining"] = 0
                    item["wounds_remaining"] = 0
                    item["destroyed"] = True
                break
            if not progressed:
                break
        return fitted

    def _rollup_rows(self, rows):
        models_remaining = sum(int(row.get("models_remaining") or 0) for row in rows)
        wounds_remaining = sum(int(row.get("wounds_remaining") or 0) for row in rows)
        destroyed = models_remaining == 0 or wounds_remaining == 0
        if destroyed:
            models_remaining = 0
            wounds_remaining = 0
            for row in rows:
                row["models_remaining"] = 0
                row["wounds_remaining"] = 0
                row["destroyed"] = True
        return models_remaining, wounds_remaining, destroyed

    def adjust_model(self, model_key, op, delta=0, rev=None):
        """Change one miniature and roll the squad M and W up from every row.

        Returns False when the miniature is missing or the action changes nothing.
        """
        self.ensure_one()
        if self.match_id.state != "active":
            raise UserError("Unit state can only be updated during an active match.")
        rows = [dict(row, undo=list(row.get("undo") or [])) for row in self.model_rows()]
        row = next((item for item in rows if item.get("key") == model_key), None)
        if not row:
            raise UserError("Unknown model.")
        op = str(op or "")
        if op == "undo":
            stack = row.get("undo") if isinstance(row.get("undo"), list) else []
            if not stack:
                return False
            prev = stack.pop()
            row["undo"] = stack
            row["models_remaining"] = int(prev.get("models_remaining") or 0)
            row["wounds_remaining"] = int(prev.get("wounds_remaining") or 0)
            row["destroyed"] = bool(prev.get("destroyed"))
        else:
            if row.get("destroyed"):
                return False
            try:
                step = int(delta)
            except (TypeError, ValueError):
                step = 0
            before = (
                int(row.get("models_remaining") or 0),
                int(row.get("wounds_remaining") or 0),
                bool(row.get("destroyed")),
            )
            cap_models = int(row.get("models") or 1)
            cap_wounds = int(row.get("wounds") or 1)
            if op == "destroy":
                row["models_remaining"] = 0
                row["wounds_remaining"] = 0
                row["destroyed"] = True
            elif op == "wounds":
                row["wounds_remaining"] = max(0, min(cap_wounds, before[1] + step))
                if row["wounds_remaining"] == 0:
                    row["models_remaining"] = 0
                    row["destroyed"] = True
            elif op == "models":
                row["models_remaining"] = max(0, min(cap_models, before[0] + step))
                if row["models_remaining"] == 0:
                    row["wounds_remaining"] = 0
                    row["destroyed"] = True
            else:
                raise UserError("Unknown model action.")
            after = (
                int(row["models_remaining"]),
                int(row["wounds_remaining"]),
                bool(row["destroyed"]),
            )
            if after == before:
                return False
            stack = row.get("undo") if isinstance(row.get("undo"), list) else []
            stack.append(
                {
                    "models_remaining": before[0],
                    "wounds_remaining": before[1],
                    "destroyed": before[2],
                }
            )
            row["undo"] = stack[-self.MODEL_UNDO_LIMIT :]
        models_remaining, wounds_remaining, destroyed = self._rollup_rows(rows)
        vals = {
            "model_state": json.dumps(rows),
            "models_remaining": models_remaining,
            "wounds_remaining": wounds_remaining,
            "destroyed": destroyed,
        }
        if rev is not None:
            vals["rev"] = int(rev)
        self.write(vals)
        return True

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
            "model_rows": self.model_rows(),
        }

    @api.model
    def _assert_side_owner(self, match, side, partner):
        if side == "host" and match.host_id.id == partner.id:
            return
        if side == "guest" and match.guest_id and match.guest_id.id == partner.id:
            return
        raise AccessError("You can only update your own army lines.")

    def action_apply_snapshot(self, values, undo_stack=None, rev=None):
        """Update tracking fields from a client snapshot (own side). One write."""
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
        if undo_stack is not None:
            stack = undo_stack if isinstance(undo_stack, list) else []
            vals["undo_stack"] = json.dumps(stack[-20:])
        if rev is not None:
            vals["rev"] = int(rev)
        # Legacy squad edits carry absolute totals. Refit miniatures so the
        # dropdown still adds up to those totals.
        vals["model_state"] = json.dumps(
            self._fit_rows(self.model_rows(), vals["models_remaining"], vals["wounds_remaining"])
        )
        self.write(vals)
        return True
