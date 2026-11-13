import json
import logging
import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


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
    unit_line_ids = fields.One2many(
        "wh40k.match.unit.line",
        "match_id",
        string="Unit Lines",
    )
    # Legacy JSON kept for migration / transport only; live source of truth is unit_line_ids.
    unit_state = fields.Text(
        string="Unit State JSON (legacy)",
        help="Deprecated transport cache. Prefer unit_line_ids.",
        default="{}",
    )
    published_at = fields.Datetime()
    finished_at = fields.Datetime()
    cancel_reason = fields.Char(string="Cancel Reason")

    WAITING_TIMEOUT_MINUTES = 15
    BUS_CHANNEL_PREFIX = "wh40k.match"

    def waiting_expires_at(self):
        self.ensure_one()
        if not self.published_at:
            return False
        return self.published_at + timedelta(minutes=self.WAITING_TIMEOUT_MINUTES)

    def is_waiting_expired(self):
        self.ensure_one()
        expires = self.waiting_expires_at()
        if not expires:
            return False
        return fields.Datetime.now() >= expires

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

    def write(self, vals):
        res = super().write(vals)
        # Notify participants on lifecycle / tracking changes (bus + long-poll wake).
        watched = {"state", "guest_id", "winner_id", "cancel_reason", "finished_at"}
        if watched.intersection(vals):
            self._notify_match_changed()
        return res

    def _bus_channels_for_partners(self):
        self.ensure_one()
        partners = self.host_id | self.guest_id
        return [f"{self.BUS_CHANNEL_PREFIX}.{partner.id}" for partner in partners if partner]

    def _notify_match_changed(self):
        """Push a lightweight bus notification to host/guest when available."""
        Bus = self.env["bus.bus"].sudo()
        for match in self:
            payload = {
                "match_id": match.id,
                "state": match.state,
                "write_date": fields.Datetime.to_string(match.write_date),
            }
            for channel in match._bus_channels_for_partners():
                try:
                    Bus._sendone(channel, "wh40k.match/updated", payload)
                except Exception:  # noqa: BLE001 — bus must never break match writes
                    _logger.debug("WH40k bus notify skipped", exc_info=True)

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

    def action_cancel(self, reason=None):
        vals = {"state": "cancelled"}
        if reason:
            vals["cancel_reason"] = reason
        self.write(vals)
        return True

    def get_join_url(self, base_url=None):
        self.ensure_one()
        # Config parameter is global; sudo is intentional and read-only.
        icp = self.env["ir.config_parameter"].sudo()
        base = (base_url or icp.get_str("web.base.url") or "").rstrip("/")
        return f"{base}/wh40k/join/{self.match_token}"

    def _roster_fits_points(self, roster):
        self.ensure_one()
        limit = int(self.points)
        return roster.points_used <= limit and (
            not roster.points_limit or roster.points_limit == limit or roster.points_used <= limit
        )

    def action_accept_invite(self, guest_partner):
        """Guest accepted invite card: waiting → selecting (claim guest seat)."""
        self.ensure_one()
        if self.is_waiting_expired():
            # Guest is not yet in the match ACL domain; cancel under checked sudo.
            self.sudo().action_cancel(reason="Waiting timeout expired")
            raise UserError("Waiting timeout expired. Match was cancelled.")
        if self.state != "waiting":
            raise UserError("This match is not waiting for a guest.")
        if self.guest_id and self.guest_id.id != guest_partner.id:
            raise UserError("A guest has already joined this match.")
        if guest_partner.id == self.host_id.id:
            raise UserError("Host cannot join as guest.")
        # Claiming the seat must elevate: player ACL is host|guest, and guest_id
        # is still empty. Strangers remain blocked by the checks above.
        self.sudo().write({"state": "selecting", "guest_id": guest_partner.id})
        return True

    def action_join(self, guest_partner, guest_roster):
        self.ensure_one()
        if self.is_waiting_expired() and self.state == "waiting":
            self.sudo().action_cancel(reason="Waiting timeout expired")
            raise UserError("Waiting timeout expired. Match was cancelled.")
        if self.state not in ("waiting", "selecting"):
            raise UserError("This match is not open for joining.")
        if guest_partner.id == self.host_id.id:
            raise UserError("Host cannot join as guest.")
        if self.guest_id and self.guest_id.id != guest_partner.id:
            raise UserError("A guest has already joined this match.")
        if guest_roster.partner_id.id != guest_partner.id:
            raise UserError("Roster does not belong to the joining player.")
        if not self._roster_fits_points(guest_roster):
            raise ValidationError(
                f"Guest roster points ({guest_roster.points_used}) exceed match limit ({self.points})."
            )
        # Elevate only after checks: (1) waiting→active may set guest_id for the
        # first time (outside host|guest ACL), (2) unit-line rebuild reads host
        # roster units the guest cannot read under roster ACL.
        match_sudo = self.sudo()
        match_sudo.write(
            {
                "guest_id": guest_partner.id,
                "guest_roster_id": guest_roster.id,
                "state": "active",
            }
        )
        match_sudo._rebuild_unit_lines(match_sudo.host_roster_id, guest_roster)
        match_sudo._sync_legacy_unit_state()
        match_sudo._notify_match_changed()
        return True

    def _side_line_vals(self, roster, side):
        vals_list = []
        # Rosters of the opponent may be outside player ACL; caller must have checked access.
        roster_rs = roster.sudo() if roster else roster
        if not roster_rs:
            return vals_list
        for unit in roster_rs.force_ids.mapped("detachment_ids.unit_ids"):
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
            vals_list.append(
                {
                    "match_id": self.id,
                    "unit_id": unit.id,
                    "side": side,
                    "name": unit.name,
                    "models": models_count or unit.quantity or 1,
                    "models_remaining": models_count or unit.quantity or 1,
                    "wounds": wounds or 1,
                    "wounds_remaining": wounds or 1,
                    "destroyed": False,
                    "undo_stack": "[]",
                }
            )
        return vals_list

    def _rebuild_unit_lines(self, host_roster, guest_roster):
        self.ensure_one()
        self.unit_line_ids.unlink()
        vals = self._side_line_vals(host_roster, "host") + self._side_line_vals(
            guest_roster, "guest"
        )
        if vals:
            self.env["wh40k.match.unit.line"].create(vals)

    def unit_state_dict(self):
        """DTO still used by the PWA (host/guest lists + undo map)."""
        self.ensure_one()
        host = []
        guest = []
        undo = {}
        for line in self.unit_line_ids:
            entry = line.to_state_entry()
            if line.side == "host":
                host.append(entry)
            else:
                guest.append(entry)
            stack = line._undo_list()
            if stack:
                undo[str(line.unit_id.id)] = stack
        return {"host": host, "guest": guest, "undo": undo}

    def _sync_legacy_unit_state(self):
        for match in self:
            match.unit_state = json.dumps(match.unit_state_dict())

    def action_update_unit_state(self, payload, updating_partner=None):
        """Persist live unit tracking onto ORM lines (own side only)."""
        self.ensure_one()
        if self.state != "active":
            raise UserError("Unit state can only be updated during an active match.")
        if isinstance(payload, str):
            data = json.loads(payload)
        else:
            data = payload or {}
        if not isinstance(data, dict):
            raise UserError("Invalid unit_state payload.")

        partner = updating_partner or self.env.user.partner_id
        if partner.id == self.host_id.id:
            own_key = "host"
        elif self.guest_id and partner.id == self.guest_id.id:
            own_key = "guest"
        else:
            raise UserError("Only match participants can update unit state.")

        own_units = data.get(own_key)
        if not isinstance(own_units, list):
            raise UserError("Missing own-side unit list.")
        incoming_undo = data.get("undo") if isinstance(data.get("undo"), dict) else {}

        lines = {line.unit_id.id: line for line in self.unit_line_ids if line.side == own_key}
        for entry in own_units:
            if not isinstance(entry, dict):
                continue
            unit_id = entry.get("unit_id")
            if unit_id is None:
                continue
            line = lines.get(int(unit_id))
            if not line:
                continue
            stack = incoming_undo.get(str(unit_id), incoming_undo.get(unit_id))
            if not isinstance(stack, list):
                stack = line._undo_list()
            line.action_apply_snapshot(entry, undo_stack=stack)

        self._sync_legacy_unit_state()
        self._notify_match_changed()
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
        # Players cannot write opponent partner stats; narrow sudo around counters only.
        winner.sudo().action_wh40k_record_result(won=True)
        loser.sudo().action_wh40k_record_result(won=False)
        return True

    @api.model
    def cron_cancel_stale_waiting(self):
        cutoff = fields.Datetime.now() - timedelta(minutes=self.WAITING_TIMEOUT_MINUTES)
        stale = self.search(
            [
                ("state", "=", "waiting"),
                ("published_at", "!=", False),
                ("published_at", "<", cutoff),
            ]
        )
        if stale:
            stale.write(
                {
                    "state": "cancelled",
                    "cancel_reason": "Waiting timeout expired",
                }
            )
        return True

    # ---------------------------------------------------------------- API helpers
    def _assert_participant(self, partner):
        self.ensure_one()
        guest_id = self.guest_id.id if self.guest_id else 0
        if partner.id not in (self.host_id.id, guest_id):
            raise AccessError("Not a participant of this match.")
        return True

    def _partner_is_host(self, partner):
        self.ensure_one()
        return bool(partner and self.host_id.id == partner.id)

    @api.model
    def get_active_summary_for_partner(self, partner):
        """Lightweight in-progress match card for dashboard / resume."""
        match = self.search(
            [
                ("state", "=", "active"),
                "|",
                ("host_id", "=", partner.id),
                ("guest_id", "=", partner.id),
            ],
            limit=1,
            order="write_date desc, id desc",
        )
        if not match:
            return None
        is_host = match.host_id.id == partner.id
        opponent = match.guest_id if is_host else match.host_id
        return {
            "id": match.id,
            "state": match.state,
            "points": match.points,
            "mission_name": match.mission_id.name if match.mission_id else "",
            "opponent_nickname": (
                (opponent.wh40k_nickname or opponent.name) if opponent else ""
            ),
            "is_host": is_host,
        }

    @api.model
    def action_create_for_host(self, partner, roster, mission, points):
        points = str(points)
        if points not in ("1000", "2000"):
            raise UserError("Points must be 1000 or 2000.")
        if not roster or not roster.exists() or roster.partner_id.id != partner.id:
            raise UserError("Invalid host roster.")
        if mission and not mission.exists():
            raise UserError("Invalid mission.")
        return self.create(
            {
                "host_id": partner.id,
                "host_roster_id": roster.id,
                "mission_id": mission.id if mission else False,
                "points": points,
                "state": "draft",
            }
        )

    def to_publish_dict(self, base_url=None):
        self.ensure_one()
        expires_at = self.waiting_expires_at()
        return {
            "match_id": self.id,
            "state": self.state,
            "match_token": self.match_token,
            "join_url": self.get_join_url(base_url=base_url),
            "published_at": fields.Datetime.to_string(self.published_at)
            if self.published_at
            else None,
            "expires_at": fields.Datetime.to_string(expires_at) if expires_at else None,
            "waiting_seconds": self.WAITING_TIMEOUT_MINUTES * 60,
        }

    @api.model
    def find_by_token(self, match_token):
        # Token is the capability: guests are not yet in ACL domain, so search with
        # sudo after the controller authenticated a real user. Mutations still run
        # through action_accept_invite / action_join checks.
        match = self.sudo().search([("match_token", "=", match_token)], limit=1)
        if not match:
            raise UserError("Invalid match token.")
        if match.state == "waiting" and match.is_waiting_expired():
            match.action_cancel(reason="Waiting timeout expired")
            raise UserError("Waiting timeout expired. Match was cancelled.")
        return match

    def to_verify_dict(self):
        self.ensure_one()
        if self.state not in ("waiting", "selecting"):
            raise UserError(f"Match is not joinable (state={self.state}).")
        if self.guest_id and self.state == "waiting":
            raise UserError("A guest has already joined this match.")
        host_roster = self.host_roster_id
        # Host roster summary for invite card — sudo after token capability check.
        host_roster_sudo = host_roster.sudo() if host_roster else host_roster
        return {
            "match_id": self.id,
            "state": self.state,
            "points": self.points,
            "mission": {
                "id": self.mission_id.id,
                "name": self.mission_id.name,
            }
            if self.mission_id
            else None,
            "host": {
                "id": self.host_id.id,
                "nickname": self.host_id.wh40k_nickname or self.host_id.name,
            },
            "host_roster": host_roster_sudo.to_host_summary_dict() if host_roster_sudo else None,
        }

    def eligible_rosters_for(self, partner):
        self.ensure_one()
        limit = int(self.points)
        return self.env["wh40k.roster"].search(
            [
                ("partner_id", "=", partner.id),
                ("points_used", "<=", limit),
            ]
        )

    def to_eligible_rosters_dict(self, partner):
        self.ensure_one()
        rosters = self.eligible_rosters_for(partner)
        return {
            "match_id": self.id,
            "state": self.state,
            "points": self.points,
            "rosters": [r.to_eligible_dict() for r in rosters],
        }

    def to_state_dict(self, partner, base_url=None):
        self.ensure_one()
        if self.guest_id:
            self._assert_participant(partner)
        elif not self._partner_is_host(partner):
            raise AccessError("Not a participant of this match.")

        if self.state == "waiting" and self.is_waiting_expired():
            self.action_cancel(reason="Waiting timeout expired")

        unit_state = self.unit_state_dict()
        if not unit_state["host"] and not unit_state["guest"] and self.unit_state:
            # Fallback for rows not yet migrated.
            try:
                unit_state = json.loads(self.unit_state or "{}")
            except json.JSONDecodeError:
                unit_state = {"host": [], "guest": [], "undo": {}}

        expires_at = self.waiting_expires_at()
        return {
            "id": self.id,
            "state": self.state,
            "points": self.points,
            "match_token": self.match_token if self.state == "waiting" else None,
            "join_url": self.get_join_url(base_url=base_url)
            if self.state == "waiting"
            else None,
            "published_at": fields.Datetime.to_string(self.published_at)
            if self.published_at
            else None,
            "expires_at": fields.Datetime.to_string(expires_at) if expires_at else None,
            "write_date": fields.Datetime.to_string(self.write_date)
            if self.write_date
            else None,
            "cancel_reason": self.cancel_reason or "",
            "mission": {
                "id": self.mission_id.id,
                "name": self.mission_id.name,
                "description": self.mission_id.description or "",
            }
            if self.mission_id
            else None,
            "host": {
                "id": self.host_id.id,
                "nickname": self.host_id.wh40k_nickname or self.host_id.name,
            },
            "guest": {
                "id": self.guest_id.id,
                "nickname": self.guest_id.wh40k_nickname or self.guest_id.name,
            }
            if self.guest_id
            else None,
            "host_roster_id": self.host_roster_id.id,
            "guest_roster_id": self.guest_roster_id.id,
            "winner_id": self.winner_id.id if self.winner_id else None,
            "winner_nickname": (
                (self.winner_id.wh40k_nickname or self.winner_id.name)
                if self.winner_id
                else ""
            ),
            "unit_state": unit_state,
            "is_host": self.host_id.id == partner.id,
        }

    def to_surrender_result_dict(self, partner):
        self.ensure_one()
        winner = self.winner_id
        you_won = bool(winner and winner.id == partner.id)
        return {
            "state": self.state,
            "winner_id": winner.id if winner else None,
            "winner_nickname": (winner.wh40k_nickname or winner.name) if winner else "",
            "you_won": you_won,
            "you_surrendered": not you_won,
            "message": (
                "Victory! Opponent surrendered."
                if you_won
                else "Defeat. You surrendered."
            ),
        }

    def _db_write_date_string(self):
        """Read write_date from SQL so long-poll sees other transactions."""
        self.ensure_one()
        self.env.cr.execute(
            "SELECT write_date FROM wh40k_match WHERE id = %s",
            (self.id,),
        )
        row = self.env.cr.fetchone()
        if not row or not row[0]:
            return None
        return fields.Datetime.to_string(row[0])

    def wait_for_change(self, since_write_date=None, timeout_seconds=20):
        """Long-poll helper: return once write_date advances or timeout."""
        self.ensure_one()
        import time

        timeout_seconds = max(1, min(25, int(timeout_seconds or 20)))
        since = since_write_date or self._db_write_date_string()
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            current = self._db_write_date_string()
            if current and since and current != since:
                self.invalidate_recordset()
                return True, current
            time.sleep(0.75)
        current = self._db_write_date_string()
        self.invalidate_recordset()
        return False, current
