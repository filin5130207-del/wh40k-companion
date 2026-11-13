"""NewRecruit / Battlescribe roster JSON parser.

Characteristic values are read from ``$text`` (not ``value``).
"""

from __future__ import annotations

import json
from typing import Any


UNIT_TYPE_NAMES = {"Unit"}
MELEE_TYPE_NAMES = {"Melee Weapons"}
RANGED_TYPE_NAMES = {"Ranged Weapons"}
ABILITY_TYPE_NAMES = {"Abilities"}


def _char_map(profile: dict) -> dict[str, str]:
    result = {}
    for char in profile.get("characteristics") or []:
        name = char.get("name")
        if not name:
            continue
        # Prefer $text; fall back only when $text is absent/empty
        text = char.get("$text")
        if text is None or text == "":
            text = char.get("value")
        result[name] = "" if text is None else str(text)
    return result


def _pts(costs: list | None) -> int:
    total = 0
    for cost in costs or []:
        if cost.get("name") == "pts":
            try:
                total += int(float(cost.get("value") or 0))
            except (TypeError, ValueError):
                pass
    return total


def _keywords(categories: list | None) -> str:
    names = []
    for cat in categories or []:
        name = cat.get("name")
        if name:
            names.append(name)
    return ", ".join(names)


def _walk_selections(selections: list | None):
    for sel in selections or []:
        yield sel
        yield from _walk_selections(sel.get("selections"))


class BattlescribeParser:
    """Parse a NewRecruit/Battlescribe roster JSON into nested dicts ready for ORM create."""

    def __init__(self, data: dict | str | bytes):
        if isinstance(data, (str, bytes)):
            data = json.loads(data)
        if not isinstance(data, dict):
            raise ValueError("Roster JSON must be an object")
        self.raw = data
        self.roster_node = data.get("roster", data)

    def parse(self) -> dict[str, Any]:
        node = self.roster_node
        costs = node.get("costs") or []
        limits = node.get("costLimits") or []
        points_used = _pts(costs)
        points_limit = _pts(limits) or points_used or 2000

        forces = []
        for force in node.get("forces") or []:
            forces.append(self._parse_force(force))

        return {
            "name": node.get("name") or "Imported Roster",
            "game_system": node.get("gameSystemName") or "",
            "points_limit": points_limit,
            "points_used": points_used,
            "forces": forces,
        }

    def summary(self) -> dict[str, int]:
        parsed = self.parse()
        units = 0
        models = 0
        weapons = 0
        abilities = 0
        for force in parsed["forces"]:
            for det in force["detachments"]:
                for unit in det["units"]:
                    units += 1
                    abilities += len(unit.get("abilities") or [])
                    for model in unit.get("models") or []:
                        models += 1
                        weapons += len(model.get("weapons") or [])
                        abilities += len(model.get("abilities") or [])
        return {
            "units": units,
            "models": models,
            "weapons": weapons,
            "abilities": abilities,
            "points_used": parsed["points_used"],
            "points_limit": parsed["points_limit"],
        }

    def preview(self) -> dict[str, Any]:
        """Lightweight preview payload for import confirmation UI."""
        parsed = self.parse()
        unit_names: list[str] = []
        factions: list[str] = []
        for force in parsed["forces"]:
            catalogue = (force.get("catalogue_name") or "").strip()
            force_name = (force.get("name") or "").strip()
            faction = catalogue or force_name
            if faction and faction not in factions:
                factions.append(faction)
            for det in force.get("detachments") or []:
                for unit in det.get("units") or []:
                    name = (unit.get("name") or "").strip()
                    if name and name not in unit_names:
                        unit_names.append(name)
        return {
            "name": parsed["name"],
            "faction": ", ".join(factions) if factions else (parsed.get("game_system") or "Unknown"),
            "game_system": parsed.get("game_system") or "",
            "points_used": parsed["points_used"],
            "points_limit": parsed["points_limit"],
            "units": unit_names,
            "unit_count": len(unit_names),
        }

    def _parse_force(self, force: dict) -> dict:
        army_rules = []
        for rule in force.get("rules") or []:
            army_rules.append(
                {
                    "name": rule.get("name") or "Rule",
                    "description": rule.get("description") or "",
                    "external_id": rule.get("id"),
                }
            )

        detachments = self._extract_detachments(force)
        # Fallback: if no detachment found, put all units under a default detachment
        if not detachments:
            detachments = [
                {
                    "name": "Army",
                    "rules": [],
                    "units": self._extract_units_from_selections(force.get("selections") or []),
                }
            ]

        return {
            "name": force.get("name") or "Force",
            "catalogue_name": force.get("catalogueName") or "",
            "army_rules": army_rules,
            "detachments": detachments,
        }

    def _extract_detachments(self, force: dict) -> list[dict]:
        """Find Detachment configuration upgrades and attach army units to them.

        NewRecruit often lists multiple detachment options under a Configuration
        selection named ``Detachment``. The first selected named detachment is
        treated as primary; units live as siblings under the force selections.
        """
        detachments_meta: list[dict] = []
        unit_selections: list[dict] = []

        for sel in force.get("selections") or []:
            name = (sel.get("name") or "").strip()
            sel_type = sel.get("type")
            if name.lower() == "detachment" or (
                sel_type == "upgrade" and "detachment" in name.lower()
            ):
                for child in sel.get("selections") or []:
                    rules = []
                    for rule in child.get("rules") or []:
                        rules.append(
                            {
                                "name": rule.get("name") or child.get("name") or "Rule",
                                "description": rule.get("description") or "",
                                "external_id": rule.get("id"),
                            }
                        )
                    # Ability profiles on detachment also count as rules text
                    for profile in child.get("profiles") or []:
                        if profile.get("typeName") in ABILITY_TYPE_NAMES:
                            chars = _char_map(profile)
                            rules.append(
                                {
                                    "name": profile.get("name") or child.get("name"),
                                    "description": chars.get("Description", ""),
                                    "external_id": profile.get("id"),
                                }
                            )
                    detachments_meta.append(
                        {
                            "name": child.get("name") or "Detachment",
                            "rules": rules,
                            "units": [],
                        }
                    )
            elif sel_type in ("unit", "model"):
                unit_selections.append(sel)
            else:
                # Nested units elsewhere (rare)
                for nested in _walk_selections(sel.get("selections")):
                    if nested.get("type") in ("unit", "model") and nested is not sel:
                        # Only collect top-level unit/model under this upgrade tree
                        # if parent itself is not unit/model (already handled)
                        pass

        units = [self._parse_unit(u) for u in unit_selections]
        if not detachments_meta:
            return []
        # Attach all units to the first detachment (primary choice)
        detachments_meta[0]["units"] = units
        # Keep additional detachment options as rule-only entries (user may have
        # multiple selected options in the JSON)
        return detachments_meta

    def _extract_units_from_selections(self, selections: list) -> list[dict]:
        units = []
        for sel in selections:
            if sel.get("type") in ("unit", "model"):
                units.append(self._parse_unit(sel))
        return units

    def _parse_unit(self, selection: dict) -> dict:
        unit_abilities = []
        unit_stats_profiles = []
        for profile in selection.get("profiles") or []:
            type_name = profile.get("typeName") or ""
            if type_name in ABILITY_TYPE_NAMES:
                chars = _char_map(profile)
                unit_abilities.append(
                    {
                        "name": profile.get("name") or "Ability",
                        "description": chars.get("Description", ""),
                    }
                )
            elif type_name in UNIT_TYPE_NAMES:
                unit_stats_profiles.append(profile)

        models = []
        # Direct model-type selection (characters / vehicles often type=model)
        if selection.get("type") == "model":
            models.append(
                self._parse_model(
                    selection,
                    fallback_profiles=unit_stats_profiles,
                    include_nested_weapons=True,
                )
            )
        else:
            child_models = [
                s for s in (selection.get("selections") or []) if s.get("type") == "model"
            ]
            if child_models:
                for child in child_models:
                    models.append(self._parse_model(child, fallback_profiles=unit_stats_profiles))
            else:
                # Unit without nested models: treat selection itself as the model line
                models.append(
                    self._parse_model(
                        selection,
                        fallback_profiles=unit_stats_profiles,
                        include_nested_weapons=True,
                    )
                )

        # Unit-level upgrades may also contribute abilities
        for child in selection.get("selections") or []:
            if child.get("type") == "model":
                continue
            for profile in child.get("profiles") or []:
                if profile.get("typeName") in ABILITY_TYPE_NAMES:
                    chars = _char_map(profile)
                    unit_abilities.append(
                        {
                            "name": profile.get("name") or child.get("name") or "Ability",
                            "description": chars.get("Description", ""),
                        }
                    )

        quantity = int(selection.get("number") or 1)
        points = _pts(selection.get("costs"))
        # Sometimes pts are only on nested model lines
        if not points:
            for child in selection.get("selections") or []:
                points += _pts(child.get("costs"))

        return {
            "name": selection.get("name") or "Unit",
            "quantity": quantity,
            "points": points,
            "keywords": _keywords(selection.get("categories")),
            "abilities": unit_abilities,
            "models": models,
        }

    def _parse_model(
        self,
        selection: dict,
        fallback_profiles: list | None = None,
        include_nested_weapons: bool = True,
    ) -> dict:
        stats = {
            "movement": "",
            "toughness": "",
            "save": "",
            "wounds": "",
            "leadership": "",
            "objective_control": "",
            "invuln_save": "",
            "base": "",
        }
        abilities = []
        weapons = []

        profiles = list(selection.get("profiles") or [])
        if fallback_profiles and not any(
            (p.get("typeName") in UNIT_TYPE_NAMES) for p in profiles
        ):
            profiles = list(fallback_profiles) + profiles

        for profile in profiles:
            type_name = profile.get("typeName") or ""
            chars = _char_map(profile)
            if type_name in UNIT_TYPE_NAMES:
                stats.update(
                    {
                        "movement": chars.get("M", ""),
                        "toughness": chars.get("T", ""),
                        "save": chars.get("Sv", ""),
                        "wounds": chars.get("W", ""),
                        "leadership": chars.get("LD", ""),
                        "objective_control": chars.get("OC", ""),
                        "invuln_save": chars.get("InSv", ""),
                        "base": chars.get("Base", ""),
                    }
                )
            elif type_name in ABILITY_TYPE_NAMES:
                abilities.append(
                    {
                        "name": profile.get("name") or "Ability",
                        "description": chars.get("Description", ""),
                    }
                )
            elif type_name in MELEE_TYPE_NAMES or type_name in RANGED_TYPE_NAMES:
                weapons.append(self._weapon_from_profile(profile, type_name))

        if include_nested_weapons:
            for child in selection.get("selections") or []:
                for profile in child.get("profiles") or []:
                    type_name = profile.get("typeName") or ""
                    if type_name in MELEE_TYPE_NAMES or type_name in RANGED_TYPE_NAMES:
                        weapons.append(self._weapon_from_profile(profile, type_name))
                    elif type_name in ABILITY_TYPE_NAMES:
                        chars = _char_map(profile)
                        abilities.append(
                            {
                                "name": profile.get("name") or child.get("name") or "Ability",
                                "description": chars.get("Description", ""),
                            }
                        )

        return {
            "name": selection.get("name") or "Model",
            "quantity": int(selection.get("number") or 1),
            **stats,
            "weapons": weapons,
            "abilities": abilities,
        }

    def _weapon_from_profile(self, profile: dict, type_name: str) -> dict:
        chars = _char_map(profile)
        weapon_type = "melee" if type_name in MELEE_TYPE_NAMES else "ranged"
        skill = chars.get("WS") if weapon_type == "melee" else chars.get("BS")
        name = profile.get("name") or "Weapon"
        # Strip Battlescribe arrow prefix
        if name.startswith("➤ "):
            name = name[2:].strip()
        return {
            "name": name,
            "weapon_type": weapon_type,
            "range": chars.get("Range", ""),
            "attacks": chars.get("A", ""),
            "skill": skill or "",
            "strength": chars.get("S", ""),
            "ap": chars.get("AP", ""),
            "damage": chars.get("D", ""),
            "keywords": chars.get("Keywords", ""),
        }
