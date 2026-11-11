import json
import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class Wh40kMatch(models.Model):
    _name = "wh40k.match"
    _description = "WH40k Match"
    _order = "create_date desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(compute="_compute_name", store=True)
    match_token = fields.Char(index=True, copy=False, readonly=True)
    host_id = fields.Many2one(
        "res.partner",
        string="Host",
        required=True,
        default=lambda self: self.env.user.partner_id,
        index=True,
    )
    guest_id = fields.Many2one("res.partner", string="Guest", index=True)
    host_roster_id = fields.Many2one("wh40k.roster", string="Host Roster")
    guest_roster_id = fields.Many2one("wh40k.roster", string="Guest Roster")
    points = fields.Selection(
        [
            ("1000", "1000"),
            ("2000", "2000"),
        ],
        string="Points Limit",
        required=True,
        default="2000",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("waiting", "Waiting"),
            ("selecting", "Selecting Roster"),
            ("active", "Active"),
            ("finished", "Finished"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    winner_id = fields.Many2one("res.partner", string="Winner")
    mission_id = fields.Many2one("wh40k.mission", string="Mission")
    unit_state = fields.Text(
        string="Unit State JSON",
        help="Per-unit wound/model tracking for the active match.",
        default="{}",
    )
    published_at = fields.Datetime()
    finished_at = fields.Datetime()

    @api.depends("host_id", "guest_id", "points", "state")
    def _compute_name(self):
        for match in self:
            host = match.host_id.wh40k_nickname or match.host_id.name or "Host"
            guest = match.guest_id.wh40k_nickname or match.guest_id.name or "TBD"
            match.name = f"{host} vs {guest} ({match.points}pts)"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("match_token", str(uuid.uuid4()))
        return super().create(vals_list)

    def action_publish(self):
        for match in self:
            if match.state != "draft":
                raise UserError("Only draft matches can be published.")
            if not match.host_roster_id:
                raise UserError("Select a host roster before publishing.")
            if not match.mission_id:
                raise UserError("Select a mission before publishing.")
            match.write(
                {
                    "state": "waiting",
                    "published_at": fields.Datetime.now(),
                    "match_token": match.match_token or str(uuid.uuid4()),
                }
            )
        return True

    def action_cancel(self):
        self.write({"state": "cancelled"})
        return True

    def get_join_url(self, base_url=None):
        self.ensure_one()
        icp = self.env["ir.config_parameter"].sudo()
        base = (base_url or icp.get_str("web.base.url") or "").rstrip("/")
        return f"{base}/wh40k/join/{self.match_token}"

    def _roster_fits_points(self, roster):
        self.ensure_one()
        limit = int(self.points)
        return roster.points_used <= limit and (
            not roster.points_limit or roster.points_limit == limit or roster.points_used <= limit
        )

    def action_join(self, guest_partner, guest_roster):
        self.ensure_one()
        if self.state not in ("waiting", "selecting"):
            raise UserError("This match is not open for joining.")
        if guest_partner.id == self.host_id.id:
            raise UserError("Host cannot join as guest.")
        if guest_roster.partner_id.id != guest_partner.id:
            raise UserError("Roster does not belong to the joining player.")
        if not self._roster_fits_points(guest_roster):
            raise ValidationError(
                f"Guest roster points ({guest_roster.points_used}) exceed match limit ({self.points})."
            )
        unit_state = self._build_initial_unit_state(self.host_roster_id, guest_roster)
        self.write(
            {
                "guest_id": guest_partner.id,
                "guest_roster_id": guest_roster.id,
                "state": "active",
                "unit_state": json.dumps(unit_state),
            }
        )
        return True

    def _build_initial_unit_state(self, host_roster, guest_roster):
        def side_state(roster, side):
            entries = []
            for unit in roster.force_ids.mapped("detachment_ids.unit_ids"):
                wounds = 0
                models_count = 0
                for model in unit.model_ids:
                    qty = model.quantity or 1
                    models_count += qty
                    try:
                        w = int(str(model.wounds or "1").replace("+", "").strip() or "1")
                    except ValueError:
                        w = 1
                    wounds += w * qty
                entries.append(
                    {
                        "unit_id": unit.id,
                        "side": side,
                        "name": unit.name,
                        "models": models_count or unit.quantity or 1,
                        "models_remaining": models_count or unit.quantity or 1,
                        "wounds": wounds or 1,
                        "wounds_remaining": wounds or 1,
                        "destroyed": False,
                    }
                )
            return entries

        return {
            "host": side_state(host_roster, "host"),
            "guest": side_state(guest_roster, "guest"),
        }

    def action_update_unit_state(self, payload):
        self.ensure_one()
        if self.state != "active":
            raise UserError("Unit state can only be updated during an active match.")
        if isinstance(payload, str):
            data = json.loads(payload)
        else:
            data = payload
        self.unit_state = json.dumps(data)
        return True

    def action_surrender(self, surrendering_partner):
        self.ensure_one()
        if self.state != "active":
            raise UserError("Only active matches can be surrendered.")
        if surrendering_partner.id == self.host_id.id:
            winner = self.guest_id
            loser = self.host_id
        elif surrendering_partner.id == self.guest_id.id:
            winner = self.host_id
            loser = self.guest_id
        else:
            raise UserError("Only match participants can surrender.")
        if not winner:
            raise UserError("Cannot resolve winner.")
        self.write(
            {
                "state": "finished",
                "winner_id": winner.id,
                "finished_at": fields.Datetime.now(),
            }
        )
        winner.action_wh40k_record_result(won=True)
        loser.action_wh40k_record_result(won=False)
        return True

    @api.model
    def cron_cancel_stale_waiting(self):
        cutoff = fields.Datetime.now() - timedelta(minutes=15)
        stale = self.search(
            [
                ("state", "=", "waiting"),
                ("published_at", "!=", False),
                ("published_at", "<", cutoff),
            ]
        )
        if stale:
            stale.write({"state": "cancelled"})
        return True
