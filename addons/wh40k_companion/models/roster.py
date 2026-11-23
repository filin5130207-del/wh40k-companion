from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.wh40k_companion.catalogues.stratagems import (
    resolve_stratagem_deck,
    stratagem_fields_for_viewer,
)


class Wh40kRoster(models.Model):
    _name = "wh40k.roster"
    _description = "WH40k Roster"
    _order = "create_date desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, tracking=True)
    game_system = fields.Char()
    points_limit = fields.Integer(default=2000)
    points_used = fields.Integer(default=0)
    partner_id = fields.Many2one(
        "res.partner",
        string="Owner",
        required=True,
        default=lambda self: self.env.user.partner_id,
        index=True,  # dashboard roster list filters on owner
        ondelete="cascade",
    )
    force_ids = fields.One2many("wh40k.force", "roster_id", string="Forces")
    # Selected detachment names from the roster file, one per line. Stratagem
    # text is not copied here; the deck is resolved from the static catalogue.
    detachment_name = fields.Text(string="Detachment")
    # Stored so list/dashboard reads the columns. Depends stay on the tree so a
    # weapon/unit edit recomputes only the affected rosters, not every match.
    unit_count = fields.Integer(compute="_compute_counts", store=True)
    weapon_count = fields.Integer(compute="_compute_counts", store=True)
    ability_count = fields.Integer(compute="_compute_counts", store=True)

    @api.depends(
        "force_ids.detachment_ids.unit_ids",
        "force_ids.detachment_ids.unit_ids.model_ids",
        "force_ids.detachment_ids.unit_ids.model_ids.weapon_ids",
        "force_ids.detachment_ids.unit_ids.ability_ids",
        "force_ids.detachment_ids.unit_ids.model_ids.ability_ids",
    )
    def _compute_counts(self):
        """Recompute only ``self`` when the tree changes.

        Dashboard and roster list read the stored columns and do not call
        this method. The depends paths are the unit/model/weapon/ability
        lines, not match state, so a wound update does not recompute counts.
        """
        for roster in self:
            units = roster.force_ids.mapped("detachment_ids.unit_ids")
            models_rs = units.mapped("model_ids")
            roster.unit_count = len(units)
            roster.weapon_count = len(models_rs.mapped("weapon_ids"))
            roster.ability_count = len(units.mapped("ability_ids")) + len(
                models_rs.mapped("ability_ids")
            )

    def to_list_dict(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "game_system": self.game_system,
            "points_limit": self.points_limit,
            "points_used": self.points_used,
            "unit_count": self.unit_count,
        }

    def to_eligible_dict(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "points_used": self.points_used,
            "points_limit": self.points_limit,
        }

    def to_host_summary_dict(self):
        self.ensure_one()
        faction = ""
        if self.force_ids:
            force = self.force_ids[:1]
            faction = force.catalogue_name or force.name or self.game_system or ""
        else:
            faction = self.game_system or ""
        return {
            "id": self.id,
            "name": self.name,
            "points_used": self.points_used,
            "faction": faction,
        }

    def _viewer_may_see_detail(self, partner):
        """Owner always; opponent only in selecting/active match with this roster."""
        self.ensure_one()
        if not partner:
            return False
        if self.partner_id.id == partner.id:
            return True
        Match = self.env["wh40k.match"]
        return bool(
            Match.search(
                [
                    ("state", "in", ("selecting", "active")),
                    "|",
                    ("host_roster_id", "=", self.id),
                    ("guest_roster_id", "=", self.id),
                    "|",
                    ("host_id", "=", partner.id),
                    ("guest_id", "=", partner.id),
                ],
                limit=1,
            )
        )

    def check_detail_access(self, partner):
        self.ensure_one()
        if not self._viewer_may_see_detail(partner):
            raise AccessError("You cannot view this roster.")
        return True

    def to_detail_dict(self, partner=None):
        """Full datasheet dump for PWA. Enforces owner/participant access."""
        self.ensure_one()
        partner = partner or self.env.user.partner_id
        self.check_detail_access(partner)
        viewer_owns_roster = self.partner_id.id == partner.id
        # Opponent may lack ACL on foreign roster rows; serialize after explicit check.
        roster = self
        if not viewer_owns_roster:
            roster = self.sudo()
        units = []
        rules = []
        for force in roster.force_ids:
            for rule in force.army_rule_ids:
                rules.append(
                    {
                        "name": rule.name,
                        "description": rule.description or "",
                        "scope": "army",
                    }
                )
            for det in force.detachment_ids:
                for rule in det.detachment_rule_ids:
                    rules.append(
                        {
                            "name": rule.name,
                            "description": rule.description or "",
                            "scope": "detachment",
                        }
                    )
                for unit in det.unit_ids:
                    models_payload = []
                    for model in unit.model_ids:
                        models_payload.append(
                            {
                                "id": model.id,
                                "name": model.name,
                                "quantity": model.quantity,
                                "M": model.movement,
                                "T": model.toughness,
                                "Sv": model.save,
                                "W": model.wounds,
                                "LD": model.leadership,
                                "OC": model.objective_control,
                                "InSv": model.invuln_save,
                                "Base": model.base,
                                "weapons": [
                                    {
                                        "name": w.name,
                                        "weapon_type": w.weapon_type,
                                        "range": w.range,
                                        "A": w.attacks,
                                        "skill": w.skill,
                                        "S": w.strength,
                                        "AP": w.ap,
                                        "D": w.damage,
                                        "keywords": w.keywords,
                                    }
                                    for w in model.weapon_ids
                                ],
                                "abilities": [
                                    {
                                        "name": a.name,
                                        "description": a.description or "",
                                    }
                                    for a in model.ability_ids
                                ],
                            }
                        )
                    units.append(
                        {
                            "id": unit.id,
                            "name": unit.name,
                            "points": unit.points,
                            "keywords": unit.keywords,
                            "quantity": unit.quantity,
                            "abilities": [
                                {
                                    "name": a.name,
                                    "description": a.description or "",
                                }
                                for a in unit.ability_ids
                            ],
                            "models": models_payload,
                        }
                    )
        payload = {
            "id": roster.id,
            "name": roster.name,
            "points_used": roster.points_used,
            "points_limit": roster.points_limit,
            "detachment_name": roster.detachment_name or "",
            "units": units,
            "rules": rules,
        }
        # The match screen loads this dict for both rosters. Only the owner
        # receives a stratagem deck; the opponent's payload omits it entirely.
        if viewer_owns_roster:
            deck = resolve_stratagem_deck(roster._detachment_catalogue_pairs())
            payload.update(stratagem_fields_for_viewer(deck, True))
        return payload

    def _detachment_catalogue_pairs(self):
        """``(catalogue name, detachment name)`` for each selected detachment.

        Names come from ``detachment_name`` (the import binding). The catalogue
        is the force that owns a detachment row with that name. Stratagem
        bodies are not read from those rows.
        """
        self.ensure_one()
        names = [
            line.strip()
            for line in (self.detachment_name or "").splitlines()
            if line.strip()
        ]
        if not names:
            return []
        name_to_catalogue = {}
        for force in self.force_ids:
            catalogue = (force.catalogue_name or "").strip()
            for det in force.detachment_ids:
                det_name = (det.name or "").strip()
                if det_name and det_name not in name_to_catalogue:
                    name_to_catalogue[det_name] = catalogue
        first_catalogue = ""
        if self.force_ids:
            first_catalogue = (self.force_ids[:1].catalogue_name or "").strip()
        return [(name_to_catalogue.get(name, first_catalogue), name) for name in names]

    @api.model
    def _create_owned_rules(self, rules, owner_id):
        """Batch-insert rules inside the current request. Does not touch matches."""
        rules = rules or []
        if not rules:
            return []
        created = self.env["wh40k.rule"].create(
            [
                {
                    "name": rule["name"],
                    "description": rule.get("description"),
                    "external_id": rule.get("external_id"),
                    "owner_partner_id": owner_id,
                }
                for rule in rules
            ]
        )
        return created.ids

    @api.model
    def _force_commands_from_parsed(self, parsed, owner_partner=None):
        """Build One2many create commands for forces from BattlescribeParser.parse()."""
        owner_id = owner_partner.id if owner_partner else self.env.user.partner_id.id
        force_cmds = []
        for force in parsed.get("forces") or []:
            army_rule_ids = self._create_owned_rules(force.get("army_rules"), owner_id)

            det_cmds = []
            for det in force.get("detachments") or []:
                det_rule_ids = self._create_owned_rules(det.get("rules"), owner_id)

                unit_cmds = []
                for unit in det.get("units") or []:
                    model_cmds = []
                    for model in unit.get("models") or []:
                        weapon_cmds = [
                            (
                                0,
                                0,
                                {
                                    "name": w["name"],
                                    "weapon_type": w["weapon_type"],
                                    "range": w.get("range"),
                                    "attacks": w.get("attacks"),
                                    "skill": w.get("skill"),
                                    "strength": w.get("strength"),
                                    "ap": w.get("ap"),
                                    "damage": w.get("damage"),
                                    "keywords": w.get("keywords"),
                                },
                            )
                            for w in model.get("weapons") or []
                        ]
                        model_ability_cmds = [
                            (
                                0,
                                0,
                                {
                                    "name": a["name"],
                                    "description": a.get("description"),
                                },
                            )
                            for a in model.get("abilities") or []
                        ]
                        model_cmds.append(
                            (
                                0,
                                0,
                                {
                                    "name": model["name"],
                                    "quantity": model.get("quantity") or 1,
                                    "movement": model.get("movement"),
                                    "toughness": model.get("toughness"),
                                    "save": model.get("save"),
                                    "wounds": model.get("wounds"),
                                    "leadership": model.get("leadership"),
                                    "objective_control": model.get("objective_control"),
                                    "invuln_save": model.get("invuln_save"),
                                    "base": model.get("base"),
                                    "weapon_ids": weapon_cmds,
                                    "ability_ids": model_ability_cmds,
                                },
                            )
                        )
                    unit_ability_cmds = [
                        (
                            0,
                            0,
                            {
                                "name": a["name"],
                                "description": a.get("description"),
                            },
                        )
                        for a in unit.get("abilities") or []
                    ]
                    models_total = sum(
                        (m.get("quantity") or 1) for m in unit.get("models") or []
                    )
                    unit_cmds.append(
                        (
                            0,
                            0,
                            {
                                "name": unit["name"],
                                "quantity": unit.get("quantity") or 1,
                                "points": unit.get("points") or 0,
                                "keywords": unit.get("keywords"),
                                "current_models": models_total
                                or unit.get("quantity")
                                or 1,
                                "model_ids": model_cmds,
                                "ability_ids": unit_ability_cmds,
                            },
                        )
                    )

                det_cmds.append(
                    (
                        0,
                        0,
                        {
                            "name": det["name"],
                            "detachment_rule_ids": [(6, 0, det_rule_ids)],
                            "unit_ids": unit_cmds,
                        },
                    )
                )

            force_cmds.append(
                (
                    0,
                    0,
                    {
                        "name": force["name"],
                        "catalogue_name": force.get("catalogue_name"),
                        "army_rule_ids": [(6, 0, army_rule_ids)],
                        "detachment_ids": det_cmds,
                    },
                )
            )
        return force_cmds

    @api.model
    def action_import_parsed(self, partner, parsed):
        """Create a roster from BattlescribeParser.parse() in this request.

        Import stays on the caller's cursor (no cron, no second transaction).
        Mail tracking is off so follower/message writes do not flush the env,
        and this method never searches or invalidates ``wh40k.match``.
        """
        if not partner:
            raise UserError("Missing partner for roster import.")
        if not parsed or not parsed.get("name"):
            raise UserError("Invalid parsed roster payload.")
        roster_model = self.with_context(
            tracking_disable=True,
            mail_notrack=True,
            mail_create_nosubscribe=True,
            mail_create_nolog=True,
        )
        force_cmds = roster_model._force_commands_from_parsed(
            parsed, owner_partner=partner
        )
        detachment_names = [
            name.strip()
            for name in (parsed.get("detachment_names") or [])
            if (name or "").strip()
        ]
        return roster_model.create(
            {
                "name": parsed["name"],
                "game_system": parsed.get("game_system"),
                "points_limit": parsed.get("points_limit") or 2000,
                "points_used": parsed.get("points_used") or 0,
                "partner_id": partner.id,
                "detachment_name": "\n".join(detachment_names),
                "force_ids": force_cmds,
            }
        )
