from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


class Wh40kRoster(models.Model):
    _name = "wh40k.roster"
    _description = "WH40k Roster"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True)
    game_system = fields.Char()
    points_limit = fields.Integer(default=2000)
    points_used = fields.Integer(default=0)
    # External res.users id from the session service. Not a Many2one: that
    # registry does not exist in this database.
    owner_uid = fields.Integer(string="Owner user id", required=True, index=True)
    owner_name = fields.Char(string="Owner nickname")
    force_ids = fields.One2many("wh40k.force", "roster_id", string="Forces")
    unit_count = fields.Integer(compute="_compute_counts")
    weapon_count = fields.Integer(compute="_compute_counts")
    ability_count = fields.Integer(compute="_compute_counts")

    @api.depends(
        "force_ids.detachment_ids.unit_ids",
        "force_ids.detachment_ids.unit_ids.model_ids",
        "force_ids.detachment_ids.unit_ids.model_ids.weapon_ids",
        "force_ids.detachment_ids.unit_ids.ability_ids",
        "force_ids.detachment_ids.unit_ids.model_ids.ability_ids",
    )
    def _compute_counts(self):
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

    def _viewer_is_owner(self, owner_uid):
        """Detail is owner-only. Opponents read the match service's snapshot."""
        self.ensure_one()
        try:
            return int(owner_uid) == int(self.owner_uid)
        except (TypeError, ValueError):
            return False

    def check_detail_access(self, owner_uid):
        self.ensure_one()
        if not self._viewer_is_owner(owner_uid):
            raise AccessError("You cannot view this roster.")
        return True

    def to_detail_dict(self, owner_uid=None):
        """Full datasheet dump for the owner. Callers pass the token uid."""
        self.ensure_one()
        if owner_uid is not None:
            self.check_detail_access(owner_uid)
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
        return {
            "id": roster.id,
            "name": roster.name,
            "points_used": roster.points_used,
            "points_limit": roster.points_limit,
            "units": units,
            "rules": rules,
        }

    @api.model
    def _force_commands_from_parsed(self, parsed, owner_uid=None):
        """Build One2many create commands for forces from BattlescribeParser.parse()."""
        Rule = self.env["wh40k.rule"]
        owner_id = int(owner_uid or 0)
        force_cmds = []
        for force in parsed.get("forces") or []:
            army_rule_ids = []
            for rule in force.get("army_rules") or []:
                rec = Rule.create(
                    {
                        "name": rule["name"],
                        "description": rule.get("description"),
                        "external_id": rule.get("external_id"),
                        "owner_uid": owner_id,
                    }
                )
                army_rule_ids.append(rec.id)

            det_cmds = []
            for det in force.get("detachments") or []:
                det_rule_ids = []
                for rule in det.get("rules") or []:
                    rec = Rule.create(
                        {
                            "name": rule["name"],
                            "description": rule.get("description"),
                            "external_id": rule.get("external_id"),
                            "owner_uid": owner_id,
                        }
                    )
                    det_rule_ids.append(rec.id)

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

    def _iter_units(self):
        """Same order as ``to_detail_dict`` so snapshot keys line up with datasheets."""
        self.ensure_one()
        roster = self.sudo()
        for force in roster.force_ids:
            for detachment in force.detachment_ids:
                for unit in detachment.unit_ids:
                    yield unit

    def to_line_specs(self):
        """Stable per-roster unit keys for the match snapshot. Keys are positive."""
        self.ensure_one()
        specs = []
        key = 1
        for unit in self._iter_units():
            wounds = 0
            models_count = 0
            for model in unit.model_ids:
                qty = model.quantity or 1
                models_count += qty
                try:
                    wound = int(str(model.wounds or "1").replace("+", "").strip() or "1")
                except ValueError:
                    wound = 1
                wounds += wound * qty
            count = models_count or unit.quantity or 1
            specs.append(
                {
                    "unit_key": key,
                    "name": unit.name,
                    "models": count,
                    "wounds": wounds or 1,
                }
            )
            key += 1
        return specs

    def to_snapshot_dict(self, owner_uid):
        """Payload the match service stores. No live FK back to this registry."""
        self.ensure_one()
        self.check_detail_access(owner_uid)
        summary = self.to_host_summary_dict()
        specs = self.to_line_specs()
        detail = self.to_detail_dict(owner_uid)
        for spec, unit in zip(specs, detail.get("units") or []):
            unit["id"] = spec["unit_key"]
        return {
            "id": self.id,
            "name": self.name,
            "owner_uid": self.owner_uid,
            "owner_name": self.owner_name or "",
            "points_used": self.points_used,
            "points_limit": self.points_limit,
            "faction": summary.get("faction") or "",
            "line_specs": specs,
            "detail": detail,
        }

    @api.model
    def action_import_parsed(self, owner_uid, parsed, owner_name=None):
        """Create a roster from BattlescribeParser.parse() for an external user id."""
        if not owner_uid:
            raise UserError("Missing owner for roster import.")
        if not parsed or not parsed.get("name"):
            raise UserError("Invalid parsed roster payload.")
        force_cmds = self._force_commands_from_parsed(parsed, owner_uid=owner_uid)
        return self.create(
            {
                "name": parsed["name"],
                "game_system": parsed.get("game_system"),
                "points_limit": parsed.get("points_limit") or 2000,
                "points_used": parsed.get("points_used") or 0,
                "owner_uid": int(owner_uid),
                "owner_name": owner_name or "",
                "force_ids": force_cmds,
            }
        )
