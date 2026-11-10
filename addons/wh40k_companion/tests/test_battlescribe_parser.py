import json
from pathlib import Path

from odoo.tests.common import TransactionCase

from odoo.addons.wh40k_companion.parsers.battlescribe_parser import BattlescribeParser


class TestBattlescribeParser(TransactionCase):
    def test_parse_aufychi_sample(self):
        sample = Path(__file__).resolve().parents[1] / "testdata" / "aufychi.json"
        data = json.loads(sample.read_text(encoding="utf-8"))
        parser = BattlescribeParser(data)
        summary = parser.summary()
        self.assertGreater(summary["units"], 0)
        self.assertGreater(summary["models"], 0)
        self.assertGreater(summary["weapons"], 0)
        self.assertGreater(summary["abilities"], 0)
        self.assertGreater(summary["points_used"], 0)

    def test_import_route_creates_records(self):
        sample = Path(__file__).resolve().parents[1] / "testdata" / "aufychi.json"
        data = json.loads(sample.read_text(encoding="utf-8"))
        parser = BattlescribeParser(data)
        parsed = parser.parse()
        partner = self.env.user.partner_id
        Rule = self.env["wh40k.rule"]
        force_cmds = []
        for force in parsed["forces"]:
            army_rule_ids = [
                Rule.create(
                    {
                        "name": r["name"],
                        "description": r.get("description"),
                    }
                ).id
                for r in force.get("army_rules") or []
            ]
            det_cmds = []
            for det in force.get("detachments") or []:
                det_rule_ids = [
                    Rule.create(
                        {
                            "name": r["name"],
                            "description": r.get("description"),
                        }
                    ).id
                    for r in det.get("rules") or []
                ]
                unit_cmds = []
                for unit in det.get("units") or []:
                    model_cmds = []
                    for model in unit.get("models") or []:
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
                                    "weapon_ids": [
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
                                    ],
                                    "ability_ids": [
                                        (
                                            0,
                                            0,
                                            {
                                                "name": a["name"],
                                                "description": a.get("description"),
                                            },
                                        )
                                        for a in model.get("abilities") or []
                                    ],
                                },
                            )
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
                                "model_ids": model_cmds,
                                "ability_ids": [
                                    (
                                        0,
                                        0,
                                        {
                                            "name": a["name"],
                                            "description": a.get("description"),
                                        },
                                    )
                                    for a in unit.get("abilities") or []
                                ],
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
        roster = self.env["wh40k.roster"].create(
            {
                "name": parsed["name"],
                "game_system": parsed.get("game_system"),
                "points_limit": parsed.get("points_limit") or 2000,
                "points_used": parsed.get("points_used") or 0,
                "partner_id": partner.id,
                "force_ids": force_cmds,
            }
        )
        self.assertTrue(roster.id)
        self.assertGreater(roster.unit_count, 0)
        self.assertGreater(roster.weapon_count, 0)
        self.assertGreater(roster.ability_count, 0)
        self.assertGreater(roster.points_used, 0)
