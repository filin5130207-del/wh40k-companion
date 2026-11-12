"""Shared fixtures for wh40k_companion TransactionCase / HttpCase tests."""

import json
from pathlib import Path

from odoo.addons.wh40k_companion.parsers.battlescribe_parser import BattlescribeParser


def sample_roster_path():
    return Path(__file__).resolve().parents[1] / "testdata" / "aufychi.json"


def load_sample_roster_json():
    return json.loads(sample_roster_path().read_text(encoding="utf-8"))


def minimal_roster_json(
    name="Tiny Army",
    points=100,
    unit_name="Boyz",
    wounds_text="1",
    wounds_fallback=None,
    with_nested_weapon=True,
    empty_forces=False,
):
    """Build a compact NewRecruit-like payload for parser/import tests."""
    if empty_forces:
        return {
            "roster": {
                "name": name,
                "gameSystemName": "Warhammer 40,000 10th Edition",
                "costs": [{"name": "pts", "value": 0}],
                "forces": [],
            }
        }

    wound_char = {"name": "W"}
    if wounds_text is not None:
        wound_char["$text"] = wounds_text
    if wounds_fallback is not None:
        wound_char["value"] = wounds_fallback

    nested = []
    if with_nested_weapon:
        nested.append(
            {
                "name": "Slugga",
                "type": "upgrade",
                "profiles": [
                    {
                        "typeName": "Ranged Weapons",
                        "name": "Slugga",
                        "characteristics": [
                            {"name": "Range", "$text": '12"'},
                            {"name": "A", "$text": "1"},
                            {"name": "BS", "$text": "5+"},
                            {"name": "S", "$text": "4"},
                            {"name": "AP", "$text": "0"},
                            {"name": "D", "$text": "1"},
                            {"name": "Keywords", "$text": "Pistol"},
                        ],
                    }
                ],
            }
        )

    return {
        "roster": {
            "name": name,
            "gameSystemName": "Warhammer 40,000 10th Edition",
            "costs": [{"name": "pts", "value": points}],
            "costLimits": [{"name": "pts", "value": 2000}],
            "forces": [
                {
                    "name": "Army Roster",
                    "catalogueName": "Orks",
                    "rules": [
                        {
                            "name": "Waaagh!",
                            "description": "Fight harder",
                            "id": "rule-1",
                        }
                    ],
                    "selections": [
                        {
                            "name": "Detachment",
                            "type": "upgrade",
                            "selections": [
                                {
                                    "name": "Waaaagh! Tribe",
                                    "type": "upgrade",
                                    "rules": [
                                        {
                                            "name": "Tribe Rule",
                                            "description": "More Dakka",
                                            "id": "det-rule-1",
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "name": unit_name,
                            "type": "unit",
                            "number": 1,
                            "costs": [{"name": "pts", "value": points}],
                            "categories": [{"name": "Infantry"}, {"name": "Battleline"}],
                            "profiles": [
                                {
                                    "typeName": "Unit",
                                    "name": unit_name,
                                    "characteristics": [
                                        {"name": "M", "value": '6"'},
                                        {"name": "T", "$text": "5"},
                                        {"name": "Sv", "$text": "5+"},
                                        wound_char,
                                        {"name": "LD", "$text": "7+"},
                                        {"name": "OC", "$text": "2"},
                                    ],
                                },
                                {
                                    "typeName": "Abilities",
                                    "name": "Mob Rule",
                                    "characteristics": [
                                        {
                                            "name": "Description",
                                            "$text": "Stay in the fight",
                                        }
                                    ],
                                },
                            ],
                            "selections": nested,
                        },
                    ],
                }
            ],
        }
    }


class Wh40kPlayerMixin:
    """Create Player/Manager users and thin host/guest rosters."""

    @classmethod
    def _create_wh40k_user(cls, login, name, groups, password=None):
        Users = cls.env["res.users"].with_context(no_reset_password=True)
        vals = {
            "name": name,
            "login": login,
            "email": login,
            "group_ids": [(6, 0, [g.id for g in groups])],
        }
        if password:
            vals["password"] = password
        return Users.create(vals)

    @classmethod
    def _setup_wh40k_players(cls, password=None, prefix=None):
        """Create Player/Manager users with unique logins per test class."""
        player = cls.env.ref("wh40k_companion.group_player")
        manager = cls.env.ref("wh40k_companion.group_manager")
        cls.group_player = player
        cls.group_manager = manager
        # Short unique tag so login + nickname stay unique across test classes.
        tag = prefix or (
            cls.__name__.replace("TestWh40k", "t")
            .replace("Test", "t")
            .lower()[:24]
        )
        cls.user_a = cls._create_wh40k_user(
            f"{tag}_a@example.com", f"{tag} A", [player], password=password
        )
        cls.user_b = cls._create_wh40k_user(
            f"{tag}_b@example.com", f"{tag} B", [player], password=password
        )
        cls.user_stranger = cls._create_wh40k_user(
            f"{tag}_s@example.com",
            f"{tag} Stranger",
            [player],
            password=password,
        )
        cls.user_manager = cls._create_wh40k_user(
            f"{tag}_m@example.com",
            f"{tag} Manager",
            [manager],
            password=password,
        )
        # Nicknames must be globally unique (partner constraint, max practical length).
        cls.user_a.partner_id.wh40k_nickname = f"{tag}_A"
        cls.user_b.partner_id.wh40k_nickname = f"{tag}_B"
        cls.user_stranger.partner_id.wh40k_nickname = f"{tag}_S"
        cls.user_manager.partner_id.wh40k_nickname = f"{tag}_M"
        cls.mission = cls.env["wh40k.mission"].create(
            {"name": f"{tag} Mission", "sequence": 50}
        )

    def _make_tiny_roster(self, user, name="Tiny", points_used=100, points_limit=2000):
        roster = (
            self.env["wh40k.roster"]
            .with_user(user)
            .create(
                {
                    "name": name,
                    "partner_id": user.partner_id.id,
                    "points_used": points_used,
                    "points_limit": points_limit,
                }
            )
        )
        force = (
            self.env["wh40k.force"]
            .with_user(user)
            .create({"name": f"{name} Force", "roster_id": roster.id})
        )
        det = (
            self.env["wh40k.detachment"]
            .with_user(user)
            .create({"name": f"{name} Det", "force_id": force.id})
        )
        unit = (
            self.env["wh40k.unit"]
            .with_user(user)
            .create({"name": f"{name} Unit", "detachment_id": det.id, "quantity": 1})
        )
        self.env["wh40k.model"].with_user(user).create(
            {
                "name": f"{name} Model",
                "unit_id": unit.id,
                "quantity": 2,
                "wounds": "2",
            }
        )
        return roster

    def _import_minimal(self, user, **kwargs):
        data = minimal_roster_json(**kwargs)
        parsed = BattlescribeParser(data).parse()
        return (
            self.env["wh40k.roster"]
            .with_user(user)
            .action_import_parsed(user.partner_id, parsed)
        )

    def _publish_match(self, host_user, host_roster, points="2000"):
        match = (
            self.env["wh40k.match"]
            .with_user(host_user)
            .action_create_for_host(
                host_user.partner_id, host_roster, self.mission, points
            )
        )
        match.with_user(host_user).action_publish()
        return match

    def _activate_match(self, host_user, guest_user, host_roster, guest_roster, points="2000"):
        match = self._publish_match(host_user, host_roster, points=points)
        match.with_user(guest_user).action_accept_invite(guest_user.partner_id)
        match.with_user(guest_user).action_join(guest_user.partner_id, guest_roster)
        return match
