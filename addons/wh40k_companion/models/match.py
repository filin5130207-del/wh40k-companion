import json
import logging
import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..utils.public_url import is_loopback_base, is_private_base

_logger = logging.getLogger(__name__)


class Wh40kMatch(models.Model):
    _name = "wh40k.match"
    _description = "WH40k Match"
    _order = "create_date desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(compute="_compute_name", store=True)
    # Join-token lookup: btree on match_token (find_by_token).
    match_token = fields.Char(index=True, copy=False, readonly=True)
    # Dashboard / active-match lookup: btree on host and guest.
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
    # Terminal kind. Win and loss are the two sides of a finished match with a winner.
    result = fields.Selection(
        [
            ("win", "Win"),
            ("surrender", "Surrender"),
            ("loss", "Loss"),
            ("draw", "Draw"),
        ],
        string="Result",
        copy=False,
    )
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
    # System parameter. Public origin for QR and join links (no trailing slash).
    PUBLIC_BASE_PARAM = "wh40k.public_base_url"
    # Postgres NOTIFY channel. Surrender commits, then an in-flight watch wakes.
    NOTIFY_CHANNEL = "wh40k_match"

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

    def _notify_match_changed(self, lines_rev=None, lines_only=False):
        """Push a lightweight bus notification to host/guest when available.

        Line updates do not write the match row (that would bump write_date and
        force a full watch payload). ``lines_rev`` is the signal for those.
        """
        Bus = self.env["bus.bus"].sudo()
        for match in self:
            payload = {
                "match_id": match.id,
                "state": match.state,
                "write_date": fields.Datetime.to_string(match.write_date),
                "lines_only": bool(lines_only),
            }
            if lines_rev is not None:
                payload["lines_rev"] = int(lines_rev)
            for channel in match._bus_channels_for_partners():
                try:
                    Bus._sendone(channel, "wh40k.match/updated", payload)
                except Exception:  # noqa: BLE001 — bus must never break match writes
                    _logger.debug("WH40k bus notify skipped", exc_info=True)
            # bus.bus insert is not enough: the other request is blocked in
            # poll, not reading the table. NOTIFY wakes that poll on commit.
            match._pg_notify_watchers(payload)

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

    @api.model
    def resolve_join_base(self, base_url=None, request_host=None):
        """Origin for a join link, and whether it is safe to call public.

        ``wh40k.public_base_url`` wins. ``web.base.url`` is the public fallback
        only when it is not loopback or RFC1918. A remaining private origin is
        still returned so a same-LAN QR works, with ``is_public`` false.
        """
        if base_url:
            base = str(base_url).strip().rstrip("/")
            return {
                "base": base,
                "is_public": bool(base) and not is_private_base(base),
            }
        # Config parameters are global; sudo is intentional and read-only.
        icp = self.env["ir.config_parameter"].sudo()
        configured = (icp.get_str(self.PUBLIC_BASE_PARAM) or "").strip().rstrip("/")
        web_base = (icp.get_str("web.base.url") or "").strip().rstrip("/")
        request_host = (request_host or "").strip().rstrip("/")
        if configured:
            base = configured
        elif web_base and not is_private_base(web_base):
            base = web_base
        elif web_base and not is_loopback_base(web_base):
            base = web_base
        elif request_host and not is_loopback_base(request_host):
            base = request_host
        else:
            base = web_base or request_host
        return {
            "base": base,
            "is_public": bool(base) and not is_private_base(base),
        }

    def join_link_dict(self, base_url=None, request_host=None):
        self.ensure_one()
        resolved = self.resolve_join_base(base_url=base_url, request_host=request_host)
        base = resolved["base"]
        path = f"/wh40k/join/{self.match_token}"
        return {
            "join_url": f"{base}{path}" if base else path,
            "join_url_public": bool(resolved["is_public"]),
        }

    def get_join_url(self, base_url=None, request_host=None):
        self.ensure_one()
        return self.join_link_dict(base_url=base_url, request_host=request_host)["join_url"]

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
        line_model = self.env["wh40k.match.unit.line"]
        for unit in roster_rs.force_ids.mapped("detachment_ids.unit_ids"):
            slots = line_model._slots_from_unit(unit)
            models_count = sum(slot["models"] for slot in slots) or unit.quantity or 1
            wounds = sum(slot["wounds"] for slot in slots) or 1
            vals_list.append(
                {
                    "match_id": self.id,
                    "unit_id": unit.id,
                    "side": side,
                    "name": unit.name,
                    "models": models_count,
                    "models_remaining": models_count,
                    "wounds": wounds,
                    "wounds_remaining": wounds,
                    "destroyed": False,
                    "undo_stack": "[]",
                    "model_state": json.dumps(slots),
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

    def _own_side_key(self, partner):
        self.ensure_one()
        if partner and partner.id == self.host_id.id:
            return "host"
        if self.guest_id and partner and partner.id == self.guest_id.id:
            return "guest"
        raise UserError("Only match participants can update unit state.")

    @api.model
    def _payload_is_wound_delta(self, data):
        """A delta names lines. A legacy snapshot carries host/guest lists."""
        if not isinstance(data, dict):
            return False
        if "host" in data or "guest" in data:
            return False
        return (
            "lines" in data
            or "line_id" in data
            or "unit_id" in data
            or "model_key" in data
        )

    def _line_snapshot_changed(self, line, entry, stack):
        try:
            models_remaining = int(entry.get("models_remaining", line.models_remaining))
            wounds_remaining = int(entry.get("wounds_remaining", line.wounds_remaining))
        except (TypeError, ValueError):
            return True
        destroyed = bool(entry.get("destroyed", line.destroyed))
        if (
            models_remaining != line.models_remaining
            or wounds_remaining != line.wounds_remaining
            or destroyed != bool(line.destroyed)
        ):
            return True
        if isinstance(stack, list) and stack != line._undo_list():
            return True
        return False

    def _next_line_rev(self):
        self.ensure_one()
        self.env["wh40k.match.unit.line"].flush_model(["rev"])
        self.env.cr.execute(
            """
            SELECT COALESCE(MAX(rev), 0) + 1
              FROM wh40k_match_unit_line
             WHERE match_id = %s
            """,
            (self.id,),
        )
        return int(self.env.cr.fetchone()[0])

    def _lines_rev(self):
        _write_date, lines_rev = self._db_change_marker()
        return lines_rev

    def action_apply_wound_delta(self, delta, updating_partner=None):
        """Apply own-side line changes and return that delta only.

        Does not write the match row, so ``write_date`` stays a lifecycle
        signal and watch can skip the full roster/match payload.
        """
        self.ensure_one()
        if self.state != "active":
            raise UserError("Unit state can only be updated during an active match.")
        if isinstance(delta, str):
            delta = json.loads(delta)
        if not isinstance(delta, dict):
            raise UserError("Invalid wound delta.")

        partner = updating_partner or self.env.user.partner_id
        self._assert_participant(partner)
        own_key = self._own_side_key(partner)

        if isinstance(delta.get("lines"), list):
            entries = delta["lines"]
            undo_map = delta.get("undo") if isinstance(delta.get("undo"), dict) else {}
        elif delta.get("line_id") or delta.get("unit_id") or delta.get("model_key"):
            entries = [delta]
            if isinstance(delta.get("undo"), list):
                undo_map = {str(delta.get("unit_id")): delta["undo"]}
            elif isinstance(delta.get("undo"), dict):
                undo_map = delta["undo"]
            else:
                undo_map = {}
        else:
            raise UserError("Invalid wound delta.")

        model_entries = [
            entry for entry in entries if isinstance(entry, dict) and entry.get("model_key")
        ]
        # Squad-level deltas stay on the caller's side. A model action may
        # target either roster, but only a participant can send one.
        if model_entries:
            self._assert_participant(partner)
            tracked = self.env["wh40k.match.unit.line"].search(
                [("match_id", "=", self.id)]
            )
        else:
            # (match_id, side) — do not load the opponent's lines or any roster tree.
            tracked = self.env["wh40k.match.unit.line"].search(
                [("match_id", "=", self.id), ("side", "=", own_key)]
            )
        by_unit = {line.unit_id.id: line for line in tracked}
        by_id = {line.id: line for line in tracked}

        def _line_for(entry):
            line = None
            if entry.get("line_id"):
                try:
                    line = by_id.get(int(entry["line_id"]))
                except (TypeError, ValueError):
                    line = None
            if not line and entry.get("unit_id") is not None:
                try:
                    line = by_unit.get(int(entry["unit_id"]))
                except (TypeError, ValueError):
                    line = None
            return line

        pending = []
        model_pending = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get("model_key"):
                line = _line_for(entry)
                if line:
                    model_pending.append((line, entry))
                continue
            if entry.get("side") and entry["side"] != own_key:
                continue
            line = _line_for(entry)
            if not line:
                continue
            unit_key = str(line.unit_id.id)
            stack = undo_map.get(unit_key, undo_map.get(line.unit_id.id))
            if stack is None and isinstance(entry.get("undo"), list):
                stack = entry["undo"]
            if not isinstance(stack, list):
                stack = None
            if not self._line_snapshot_changed(line, entry, stack):
                continue
            pending.append((line, entry, stack))

        changed_entries = []
        changed_undo = {}
        if pending or model_pending:
            rev = self._next_line_rev()
            changed_ids = []
            for line, entry in model_pending:
                applied = line.adjust_model(
                    entry.get("model_key"),
                    entry.get("op"),
                    entry.get("delta") or 0,
                    rev=rev,
                )
                if applied:
                    changed_ids.append(line.id)
            for line, entry, stack in pending:
                line.action_apply_snapshot(entry, undo_stack=stack, rev=rev)
                changed_ids.append(line.id)
            if changed_ids:
                for line in self.env["wh40k.match.unit.line"].browse(changed_ids):
                    changed_entries.append(line.to_state_entry())
                    changed_undo[str(line.unit_id.id)] = line._undo_list()
                self._notify_match_changed(lines_rev=rev, lines_only=True)

        return {
            "lines_rev": self._lines_rev(),
            "write_date": self._db_write_date_string(),
            "delta": {"lines": changed_entries, "undo": changed_undo},
        }

    def action_update_unit_state(self, payload, updating_partner=None):
        """Persist live unit tracking. Legacy full lists become a wound delta."""
        self.ensure_one()
        if self.state != "active":
            raise UserError("Unit state can only be updated during an active match.")
        if isinstance(payload, str):
            data = json.loads(payload)
        else:
            data = payload or {}
        if not isinstance(data, dict):
            raise UserError("Invalid unit_state payload.")
        if self._payload_is_wound_delta(data):
            return self.action_apply_wound_delta(data, updating_partner=updating_partner)

        partner = updating_partner or self.env.user.partner_id
        own_key = self._own_side_key(partner)
        own_units = data.get(own_key)
        if not isinstance(own_units, list):
            raise UserError("Missing own-side unit list.")
        incoming_undo = data.get("undo") if isinstance(data.get("undo"), dict) else {}
        # Drop unchanged lines so a full client snapshot still writes a delta.
        lines = {
            line.unit_id.id: line
            for line in self.env["wh40k.match.unit.line"].search(
                [("match_id", "=", self.id), ("side", "=", own_key)]
            )
        }
        changed = []
        undo = {}
        for entry in own_units:
            if not isinstance(entry, dict) or entry.get("unit_id") is None:
                continue
            try:
                unit_id = int(entry["unit_id"])
            except (TypeError, ValueError):
                continue
            line = lines.get(unit_id)
            if not line:
                continue
            stack = incoming_undo.get(str(unit_id), incoming_undo.get(unit_id))
            if not isinstance(stack, list):
                stack = None
            if not self._line_snapshot_changed(line, entry, stack):
                continue
            changed.append(entry)
            if isinstance(stack, list):
                undo[str(unit_id)] = stack
        return self.action_apply_wound_delta(
            {"lines": changed, "undo": undo},
            updating_partner=partner,
        )

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
                "result": "surrender",
                "winner_id": winner.id,
                "finished_at": fields.Datetime.now(),
            }
        )
        # Players cannot write opponent partner stats; narrow sudo around counters only.
        winner.sudo().action_wh40k_record_result(won=True)
        loser.sudo().action_wh40k_record_result(won=False)
        return True

    def action_draw(self, partner):
        """Either participant records a draw for this match.

        Both players' draw counters move. A player cannot record a draw on
        someone else's match.
        """
        self.ensure_one()
        self._assert_participant(partner)
        if self.state != "active":
            raise UserError("Only active matches can be recorded as a draw.")
        if not self.guest_id or not self.host_id:
            raise UserError("Both players must be in the match to record a draw.")
        self.write(
            {
                "state": "finished",
                "result": "draw",
                "winner_id": False,
                "finished_at": fields.Datetime.now(),
            }
        )
        self.host_id.sudo().action_wh40k_record_result(outcome="draw")
        self.guest_id.sudo().action_wh40k_record_result(outcome="draw")
        return True

    # Datasheet columns the opponent card already shows. Own units use the same keys.
    UNIT_PROFILE_FIELDS = ("M", "T", "Sv", "W", "LD", "OC", "InSv")

    def _unit_profiles_by_id(self):
        """Characteristic rows for every line in this match.

        Opponent models sit outside the caller's roster rules. Call only after
        the participant check. The read is sudo; the check is not.
        """
        self.ensure_one()
        self.env.cr.execute(
            """
            SELECT DISTINCT unit_id
              FROM wh40k_match_unit_line
             WHERE match_id = %s
               AND unit_id IS NOT NULL
            """,
            (self.id,),
        )
        unit_ids = [row[0] for row in self.env.cr.fetchall()]
        grouped = {unit_id: [] for unit_id in unit_ids}
        if not unit_ids:
            return grouped
        units = self.env["wh40k.unit"].sudo().browse(unit_ids)
        units.mapped("model_ids")
        for unit in units:
            grouped[unit.id] = [
                {
                    "id": model.id,
                    "name": model.name or "",
                    "quantity": model.quantity or 1,
                    "M": model.movement or "",
                    "T": model.toughness or "",
                    "Sv": model.save or "",
                    "W": model.wounds or "",
                    "LD": model.leadership or "",
                    "OC": model.objective_control or "",
                    "InSv": model.invuln_save or "",
                }
                for model in unit.model_ids
            ]
        return grouped

    def _attach_unit_profiles(self, unit_state):
        """Copy the same characteristic fields onto host and guest lines."""
        profiles = self._unit_profiles_by_id()
        for side in ("host", "guest"):
            for entry in unit_state.get(side) or []:
                if not isinstance(entry, dict):
                    continue
                entry["profiles"] = list(profiles.get(entry.get("unit_id")) or [])
        return unit_state

    def you_result_for(self, partner):
        """This player's outcome: win, surrender, loss, or draw."""
        self.ensure_one()
        if self.result == "draw" or (
            self.state == "finished" and not self.winner_id and self.result == "draw"
        ):
            return "draw"
        if self.state != "finished" or not self.winner_id or not partner:
            return ""
        if self.winner_id.id == partner.id:
            return "win"
        if self.result == "surrender":
            return "surrender"
        return "loss"

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

    def to_publish_dict(self, base_url=None, request_host=None):
        self.ensure_one()
        expires_at = self.waiting_expires_at()
        link = self.join_link_dict(base_url=base_url, request_host=request_host)
        return {
            "match_id": self.id,
            "state": self.state,
            "match_token": self.match_token,
            "join_url": link["join_url"],
            "join_url_public": link["join_url_public"],
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

    def to_state_dict(self, partner, base_url=None, request_host=None):
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
        if not isinstance(unit_state, dict):
            unit_state = {"host": [], "guest": [], "undo": {}}
        self._attach_unit_profiles(unit_state)

        expires_at = self.waiting_expires_at()
        link = (
            self.join_link_dict(base_url=base_url, request_host=request_host)
            if self.state == "waiting"
            else None
        )
        # Both players see the same army, detachment, and stratagem text.
        # Read rosters with sudo: the opponent's rows are outside player ACL.
        shared = self.sudo()
        host_rules = (
            shared.host_roster_id.rules_payload() if shared.host_roster_id else []
        )
        guest_rules = (
            shared.guest_roster_id.rules_payload() if shared.guest_roster_id else []
        )
        return {
            "id": self.id,
            "state": self.state,
            "points": self.points,
            "match_token": self.match_token if self.state == "waiting" else None,
            "join_url": link["join_url"] if link else None,
            "join_url_public": link["join_url_public"] if link else False,
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
            "host_roster_id": shared.host_roster_id.id,
            "guest_roster_id": shared.guest_roster_id.id,
            "host_rules": host_rules,
            "guest_rules": guest_rules,
            "winner_id": self.winner_id.id if self.winner_id else None,
            "winner_nickname": (
                (self.winner_id.wh40k_nickname or self.winner_id.name)
                if self.winner_id
                else ""
            ),
            "result": self.result or "",
            "you_result": self.you_result_for(partner),
            "unit_state": unit_state,
            "lines_rev": self._lines_rev(),
            "is_host": self.host_id.id == partner.id,
        }

    def to_surrender_result_dict(self, partner):
        self.ensure_one()
        winner = self.winner_id
        you_won = bool(winner and winner.id == partner.id)
        return {
            "state": self.state,
            "result": self.result or "",
            "you_result": self.you_result_for(partner),
            "winner_id": winner.id if winner else None,
            "winner_nickname": (winner.wh40k_nickname or winner.name) if winner else "",
            "you_won": you_won,
            "you_surrendered": not you_won,
            "is_draw": False,
            "message": (
                "Victory! Opponent surrendered."
                if you_won
                else "Defeat. You surrendered."
            ),
        }

    def to_draw_result_dict(self, partner):
        self.ensure_one()
        self._assert_participant(partner)
        return {
            "state": self.state,
            "result": "draw",
            "you_result": "draw",
            "winner_id": None,
            "winner_nickname": "",
            "you_won": False,
            "you_surrendered": False,
            "is_draw": True,
            "message": "Draw.",
        }

    def _db_write_date_string(self):
        """Read write_date from SQL so long-poll sees other transactions."""
        write_date, _lines_rev = self._db_change_marker()
        return write_date

    def _pg_notify_watchers(self, payload):
        """Wake in-flight ``wait_for_change`` polls. Delivered on commit."""
        self.ensure_one()
        try:
            self.env.cr.execute(
                "SELECT pg_notify(%s, %s)",
                (
                    self.NOTIFY_CHANNEL,
                    json.dumps(
                        {
                            "match_id": self.id,
                            "state": payload.get("state"),
                            "lines_only": bool(payload.get("lines_only")),
                        }
                    ),
                ),
            )
        except Exception:  # noqa: BLE001 — notify must not break the match write
            _logger.debug("WH40k match NOTIFY skipped", exc_info=True)

    def _db_change_marker(self):
        """Match write_date (lifecycle) and max line rev (wound deltas)."""
        self.ensure_one()
        # Flush line rev only. Flushing match state/write_date from an in-flight
        # watch would write the cached pre-finish row back over the surrender.
        self.env["wh40k.match.unit.line"].flush_model(["rev"])
        self.env.cr.execute(
            """
            SELECT m.write_date,
                   COALESCE((
                       SELECT MAX(l.rev)
                         FROM wh40k_match_unit_line l
                        WHERE l.match_id = m.id
                   ), 0)
              FROM wh40k_match m
             WHERE m.id = %s
            """,
            (self.id,),
        )
        row = self.env.cr.fetchone()
        if not row:
            return None, 0
        write_date = fields.Datetime.to_string(row[0]) if row[0] else None
        return write_date, int(row[1] or 0)

    def _classify_change(self, since_write_date, since_rev):
        """``since_rev is None`` ignores line edits (legacy watch clients)."""
        write_date, lines_rev = self._db_change_marker()
        track_lines = since_rev is not None
        try:
            since_rev_i = int(since_rev) if track_lines else 0
        except (TypeError, ValueError):
            since_rev_i = 0
        lifecycle = bool(
            since_write_date and write_date and write_date != since_write_date
        )
        lines_changed = bool(track_lines and lines_rev != since_rev_i)
        return {
            "changed": lifecycle or lines_changed,
            "write_date": write_date,
            "lines_rev": lines_rev,
            "lines_only": bool(lines_changed and not lifecycle),
            "since_rev": since_rev_i,
        }

    def wound_delta_since(self, since_rev):
        """Lines with ``rev`` above ``since_rev``. No roster and no match header."""
        self.ensure_one()
        try:
            since_rev = int(since_rev or 0)
        except (TypeError, ValueError):
            since_rev = 0
        lines = self.env["wh40k.match.unit.line"].search(
            [("match_id", "=", self.id), ("rev", ">", since_rev)]
        )
        undo = {}
        entries = []
        for line in lines:
            entries.append(line.to_state_entry())
            undo[str(line.unit_id.id)] = line._undo_list()
        return {"lines": entries, "undo": undo}

    def _invalidate_tracked_lines(self):
        """Drop cached line fields so the next read sees the other transaction."""
        self.invalidate_recordset()
        self.env["wh40k.match.unit.line"].invalidate_model(
            [
                "models_remaining",
                "wounds_remaining",
                "destroyed",
                "undo_stack",
                "model_state",
                "rev",
                "write_date",
            ]
        )

    def _finish_row_from_sql(self, row):
        """``state``, ``winner_id``, ``result`` from a finish SELECT, or None."""
        if not row or row[0] not in ("finished", "cancelled"):
            return None
        return {
            "state": row[0],
            "winner_id": row[1],
            "result": row[2] or "",
        }

    def _read_finish_row(self):
        """State, winner, and result from this cursor, without flushing a cached row.

        ``result`` has to come from SQL. A long-poll that started before the
        finish still holds an empty ``result`` in the ORM cache.
        """
        self.ensure_one()
        self.env.cr.execute(
            "SELECT state, winner_id, result FROM wh40k_match WHERE id = %s",
            (self.id,),
        )
        return self._finish_row_from_sql(self.env.cr.fetchone())

    def _read_finish_committed(self):
        """Finish row other requests have committed.

        The extra cursor is rolled back and closed. It must not commit the
        watcher's transaction. Uncommitted test rows stay invisible here.
        """
        self.ensure_one()
        cr = None
        try:
            cr = self.env.registry.cursor()
            cr.execute(
                "SELECT state, winner_id, result FROM wh40k_match WHERE id = %s",
                (self.id,),
            )
            row = cr.fetchone()
            cr.rollback()
        except Exception:  # noqa: BLE001 — fall back to this cursor
            _logger.debug("WH40k watch committed-state read failed", exc_info=True)
            row = None
            if cr is not None:
                try:
                    cr.rollback()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            if cr is not None:
                try:
                    cr.close()
                except Exception:  # noqa: BLE001
                    pass
        return self._finish_row_from_sql(row)

    def _read_state_row(self):
        """State from this cursor, without flushing a cached match row."""
        self.ensure_one()
        self.env.cr.execute(
            "SELECT state FROM wh40k_match WHERE id = %s",
            (self.id,),
        )
        row = self.env.cr.fetchone()
        return row[0] if row else None

    def _read_state_committed(self):
        """State other requests have committed. Does not commit this one."""
        self.ensure_one()
        cr = None
        row = None
        try:
            cr = self.env.registry.cursor()
            cr.execute(
                "SELECT state FROM wh40k_match WHERE id = %s",
                (self.id,),
            )
            row = cr.fetchone()
            cr.rollback()
        except Exception:  # noqa: BLE001 — fall back to this cursor
            _logger.debug("WH40k watch committed-state read failed", exc_info=True)
            row = None
            if cr is not None:
                try:
                    cr.rollback()
                except Exception:  # noqa: BLE001
                    pass
        finally:
            if cr is not None:
                try:
                    cr.close()
                except Exception:  # noqa: BLE001
                    pass
        return row[0] if row else None

    def _nonterminal_lifecycle_info(self, since_write_date, since_rev, seen_state):
        """Join that ``write_date`` did not show. ``seen_state`` is pre-park.

        A guest join leaves ``waiting`` for ``active``. That must end the
        long-poll the same way a finish does, not burn the rest of the timeout.
        """
        if not seen_state:
            return None
        state = self._read_state_row()
        if not state or state == seen_state:
            state = self._read_state_committed() or state
        if not state or state == seen_state:
            return None
        if state in ("finished", "cancelled"):
            return self._terminal_watch_info(
                since_write_date, since_rev, include_committed=True
            )
        self._invalidate_tracked_lines()
        info = self._classify_change(since_write_date, since_rev)
        info["changed"] = True
        info["lines_only"] = False
        info["committed_state"] = state
        return info

    def _terminal_watch_info(self, since_write_date, since_rev, include_committed=False):
        """Lifecycle result when the match is already finished or cancelled.

        ``write_date`` is second-resolution, so a surrender in the same second
        does not change it. The state column is the signal. ``lines_only``
        stays false so the client gets the match and goes home.
        """
        seen = self._read_finish_row()
        if seen is None and include_committed:
            seen = self._read_finish_committed()
        if seen is None:
            return None
        self._invalidate_tracked_lines()
        info = self._classify_change(since_write_date, since_rev)
        info["changed"] = True
        info["lines_only"] = False
        info["terminal_state"] = seen["state"]
        info["terminal_winner_id"] = seen["winner_id"]
        info["terminal_result"] = seen.get("result") or ""
        return info

    def _raw_db_connection(self, cr):
        for attr in ("_cnx", "connection", "_obj"):
            conn = getattr(cr, attr, None)
            if conn is not None and hasattr(conn, "fileno"):
                return conn
        return None

    def _consume_notifies(self, conn):
        if hasattr(conn, "poll"):
            conn.poll()
        notifies_attr = getattr(conn, "notifies", None)
        if notifies_attr is None:
            return []
        if callable(notifies_attr):
            return list(notifies_attr())
        found = list(notifies_attr)
        try:
            notifies_attr.clear()
        except Exception:  # noqa: BLE001
            pass
        return found

    def _notify_is_ours(self, notifies):
        for notify in notifies:
            channel = getattr(notify, "channel", None)
            if channel and channel != self.NOTIFY_CHANNEL:
                continue
            payload = getattr(notify, "payload", None)
            try:
                data = json.loads(payload or "{}")
            except (TypeError, json.JSONDecodeError):
                return True
            try:
                if int(data.get("match_id") or 0) == self.id:
                    return True
            except (TypeError, ValueError):
                return True
        return False

    def _park_for_signal(self, timeout):
        """Block until this match is notified, or ``timeout`` elapses.

        Return True when a notification arrived or the row is already
        finished. LISTEN runs on a dedicated autocommit connection: on the
        request cursor it would stay invisible until that transaction
        commits, which is after the poll returns. A full-timeout sleep is
        not used. If LISTEN cannot be set up, recheck after a short slice.
        """
        self.ensure_one()
        timeout = max(0.0, float(timeout))
        if timeout <= 0:
            return False
        try:
            return bool(self._park_pg_notify(timeout))
        except Exception:  # noqa: BLE001 — sliced recheck, not the full budget
            _logger.debug("WH40k watch NOTIFY park failed", exc_info=True)
            import time

            time.sleep(min(0.25, timeout))
            return False

    def _park_pg_notify(self, timeout):
        import select

        cr = self.env.registry.cursor()
        conn = None
        raw = None
        try:
            conn = self._raw_db_connection(cr)
            if conn is None:
                raise RuntimeError("PostgreSQL connection has no fileno")
            try:
                cr.rollback()
            except Exception:  # noqa: BLE001
                pass
            if hasattr(conn, "autocommit"):
                conn.autocommit = True
            raw = conn.cursor()
            # Channel name is a module constant. LISTEN does not take binds.
            raw.execute("LISTEN wh40k_match")
            if not getattr(conn, "autocommit", False):
                conn.commit()
            self._consume_notifies(conn)
            # Finish or join may have committed in the gap before LISTEN.
            # Compare with this request's view: a join moves waiting → active
            # even when write_date stays in the same second.
            seen_state = self._read_state_row()
            raw.execute(
                "SELECT state FROM wh40k_match WHERE id = %s",
                (self.id,),
            )
            row = raw.fetchone()
            if row and row[0] in ("finished", "cancelled"):
                return True
            if row and seen_state and row[0] != seen_state:
                return True
            readable, _w, _x = select.select([conn], [], [], timeout)
            if not readable:
                return False
            return self._notify_is_ours(self._consume_notifies(conn)) or True
        finally:
            if raw is not None:
                try:
                    raw.execute("UNLISTEN *")
                    if conn is not None and not getattr(conn, "autocommit", False):
                        conn.commit()
                except Exception:  # noqa: BLE001
                    _logger.debug("WH40k UNLISTEN skipped", exc_info=True)
                try:
                    raw.close()
                except Exception:  # noqa: BLE001
                    pass
            if conn is not None and hasattr(conn, "autocommit"):
                try:
                    conn.autocommit = False
                except Exception:  # noqa: BLE001
                    pass
            try:
                cr.rollback()
            except Exception:  # noqa: BLE001
                pass
            try:
                cr.close()
            except Exception:  # noqa: BLE001
                pass

    def wait_for_change(self, since_write_date=None, timeout_seconds=20, since_rev=None):
        """Long-poll until the match changes.

        A finish or cancel returns as soon as the NOTIFY lands, including
        when ``write_date`` did not move. The wait is ``select`` on that
        channel, not a sleep of the whole poll budget.
        """
        self.ensure_one()
        import time

        timeout_seconds = max(1, min(25, int(timeout_seconds or 20)))
        baseline_wd, _baseline_rev = self._db_change_marker()
        since_wd = since_write_date or baseline_wd
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            terminal = self._terminal_watch_info(since_wd, since_rev)
            if terminal:
                return terminal
            classified = self._classify_change(since_wd, since_rev)
            if classified["changed"]:
                self._invalidate_tracked_lines()
                return classified
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            seen_state = self._read_state_row()
            if self._park_for_signal(remaining):
                terminal = self._terminal_watch_info(
                    since_wd, since_rev, include_committed=True
                )
                if terminal:
                    return terminal
                # Join wakes the same NOTIFY as surrender. Do not park again
                # until the long-poll budget just because the match is not finished.
                moved = self._nonterminal_lifecycle_info(
                    since_wd, since_rev, seen_state
                )
                if moved:
                    return moved
        terminal = self._terminal_watch_info(
            since_wd, since_rev, include_committed=True
        )
        if terminal:
            return terminal
        return self._classify_change(since_wd, since_rev)

    def watch_payload(
        self,
        partner,
        since_write_date=None,
        since_rev=None,
        timeout_seconds=20,
        base_url=None,
        request_host=None,
        wait=True,
    ):
        """Watch DTO. Line-only changes carry a wound delta, not ``match``.

        Finished and cancelled matches always include ``match`` so the client
        goes home, same as a poll that used to discover the finish at timeout.
        """
        self.ensure_one()
        if self.guest_id:
            self._assert_participant(partner)
        elif not self._partner_is_host(partner):
            raise AccessError("Not a participant of this match.")
        terminal = self._terminal_watch_info(since_write_date, since_rev)
        if terminal:
            info = terminal
        elif wait:
            info = self.wait_for_change(
                since_write_date=since_write_date,
                since_rev=since_rev,
                timeout_seconds=timeout_seconds,
            )
        else:
            info = self._classify_change(since_write_date, since_rev)
            self._invalidate_tracked_lines()
        payload = {
            "changed": bool(info["changed"]),
            "write_date": info["write_date"],
            "lines_rev": info["lines_rev"],
            "lines_only": bool(info["lines_only"]),
        }
        if not info["changed"]:
            return payload
        if info["lines_only"]:
            payload["delta"] = self.wound_delta_since(info["since_rev"])
            return payload
        self._invalidate_tracked_lines()
        payload["match"] = self.to_state_dict(
            partner, base_url=base_url, request_host=request_host
        )
        if info.get("terminal_state") in ("finished", "cancelled"):
            payload["match"]["state"] = info["terminal_state"]
            payload["lines_only"] = False
            # to_state_dict() may still be the pre-finish cache. Copy the
            # result the finish SQL just read. A draw has no winner.
            committed_result = info.get("terminal_result") or ""
            if committed_result:
                payload["match"]["result"] = committed_result
            if committed_result == "draw":
                payload["match"]["you_result"] = "draw"
                payload["match"]["winner_id"] = None
                payload["match"]["winner_nickname"] = ""
            else:
                winner_id = info.get("terminal_winner_id")
                if winner_id and not payload["match"].get("winner_id"):
                    payload["match"]["winner_id"] = winner_id
        elif info.get("committed_state"):
            payload["match"]["state"] = info["committed_state"]
            payload["lines_only"] = False
        return payload
