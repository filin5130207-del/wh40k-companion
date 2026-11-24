"""Text roster import for the official app and New Recruit exports.

The line rules follow ``roster-text-mock/parse.js``: labeled configuration
(New Recruit) and the headerless official-app paste. Names are resolved
against the rules catalogue. Army-rule bodies and stratagem when/target/effect
are kept on the import dict so the owner can read them, and
``rule_for_viewer`` drops that prose for anyone else.
"""

from __future__ import annotations

import re
from typing import Any

from ..catalogues.rules_catalogue import load_catalogue

BATTLE_SIZES = (
    "combat patrol",
    "incursion",
    "strike force",
    "onslaught",
    "strikeforce",
)
MISSIONS = (
    "disruption",
    "priority assets",
    "purge the foe",
    "reconnaissance",
    "recon",
    "take and hold",
)
BREADCRUMBS = ("chaos", "imperium", "space marines", "xenos", "adeptus astartes")

_CONFIG_RE = re.compile(
    r"^(battle size|detachment|force disposition|faction|list name)\b(?:\s*\[[^\]]*\])?\s*:\s*(.+)$",
    re.I,
)
_SECTION_MD_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_SECTION_COLON_RE = re.compile(r"^([A-Za-z][\w /&'-]*):\s*$")
_UNIT_HEADER_RE = re.compile(
    r"^(.+?)\s*(?:\(|\[)\s*([\d][\d,.'’\s]*)\s*(?:pts?|points?)\s*(?:\)|\])\s*$",
    re.I,
)
_BULLET_RE = re.compile(r"^([ \t]*)([•◦*])\s+(.+?)\s*$")
_CONT_RE = re.compile(r"^([ \t]+)(\d+\s*[x×]\s+\S.*)$")
_QTY_RE = re.compile(r"^(\d+)\s*[x×]\s+(.+)$", re.I)
_GLOSS_RE = re.compile(r"\[gloss:[^:\]]*:([^\]]+)\]")


def norm(value) -> str:
    text = str(value or "").lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"[^a-z0-9+]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def profile_norm(value) -> str:
    text = re.sub(r"\bw\s*/", "with ", str(value or ""), flags=re.I)
    return norm(text)


def readable(value) -> str:
    text = _GLOSS_RE.sub(r"\1", str(value or ""))
    return text.replace("**", "").strip()


def parse_pts(raw) -> int | None:
    digits = re.sub(r"[^\d]", "", str(raw or ""))
    return int(digits) if digits else None


def is_battle_size(name) -> bool:
    folded = norm(name)
    return any(folded == label or folded.startswith(label + " ") for label in BATTLE_SIZES)


def is_mission(name) -> bool:
    return norm(name) in MISSIONS


def strip_footer(text) -> str:
    kept = []
    for line in str(text or "").replace("\r\n", "\n").split("\n"):
        trimmed = line.strip()
        if trimmed and re.search(
            r"exported with app version|created with newrecruit|^\s*data version\b",
            trimmed,
            re.I,
        ):
            continue
        kept.append(line)
    return "\n".join(kept)


def split_detachment_line(line) -> list[str]:
    value = str(line or "").strip()
    value = re.sub(r"\s*[:：]\s*", ": ", value, count=1)
    keyed = re.match(r"^(?:detachment)\b(?:\s*\[[^\]]*\])?\s*:\s*(.+)$", value, re.I)
    if keyed:
        value = keyed.group(1).strip()
    value = re.sub(r"\s*\(\s*\d*\s*(?:detachment points?|dp)\s*\)\s*$", "", value, flags=re.I).strip()
    value = re.sub(r"\s*\[\s*\d+\s*(?:detachment points?|dp)\s*\]\s*$", "", value, flags=re.I).strip()
    parts = []
    for part in re.split(r"\s*,\s*and\s+|\s*,\s+|\s+and\s+", value, flags=re.I):
        cleaned = re.sub(
            r"\s*[\[\(]\s*\d+\s*(?:detachment points?|dp)\s*[\]\)]\s*$",
            "",
            part,
            flags=re.I,
        ).strip()
        if cleaned:
            parts.append(cleaned)
    return parts


def config_key(line):
    match = _CONFIG_RE.match(line)
    if not match:
        return None
    return {"key": match.group(1).lower(), "value": match.group(2).strip()}


def section_name(line):
    md = _SECTION_MD_RE.match(line)
    if md:
        return re.sub(r"\s*\(.*\)\s*$", "", md.group(1)).strip()
    if re.match(r"^[A-Z][A-Z0-9 /&-]{2,}$", line):
        return line.strip()
    colon = _SECTION_COLON_RE.match(line)
    if colon and not config_key(line):
        return colon.group(1).strip()
    return None


def unit_header(line):
    match = _UNIT_HEADER_RE.match(line)
    if not match:
        return None
    return {"name": match.group(1).strip(), "points": parse_pts(match.group(2))}


def bullet_of(line):
    match = _BULLET_RE.match(line)
    if not match:
        return None
    indent = match.group(1).replace("\t", "  ")
    return {"indent": len(indent), "text": match.group(3).strip(), "bullet": True}


def continuation_of(line):
    match = _CONT_RE.match(line)
    if not match:
        return None
    indent = match.group(1).replace("\t", "  ")
    return {"indent": len(indent), "text": match.group(2).strip(), "bullet": False}


def is_attachment_heading(line) -> bool:
    return bool(re.match(r"^attached units$", line, re.I) or re.match(r"^attached unit\s+\d+$", line, re.I))


def classify_item(text) -> dict:
    raw = re.sub(r"^\d+\s*[x×]\s+", "", text, flags=re.I).strip()
    if re.match(r"^warlord$", raw, re.I):
        return {"kind": "annotation", "label": "Warlord"}
    if re.match(r"^leader$", raw, re.I):
        return {"kind": "annotation", "label": "Leader"}
    attached = re.match(r"^attached\s+(?:as|to)\s*:\s*(.+)$", raw, re.I)
    if attached:
        direction = "to" if re.match(r"^\s*attached\s+to", raw, re.I) else "as"
        return {"kind": "annotation", "label": f"Attached {direction}: {attached.group(1).strip()}"}
    leading = re.match(r"^(?:leading|leader)\s*:\s*(.+)$", raw, re.I)
    if leading:
        return {"kind": "annotation", "label": f"Leading: {leading.group(1).strip()}"}
    enh = re.match(r"^(?:e|enhancements?)\s*:\s*(.+)$", raw, re.I)
    if enh:
        name = re.sub(r"\s*\(\+\s*[\d,]+\s*(?:pts?|points?)\s*\)\s*$", "", enh.group(1), flags=re.I).strip()
        return {"kind": "enhancement", "name": name}
    plain = re.sub(r"\s*\(\+\s*[\d,]+\s*(?:pts?|points?)\s*\)\s*$", "", raw, flags=re.I).strip()
    return {"kind": "gear", "name": plain}


def shape_items(bullets) -> list[dict]:
    items = []
    for index, bullet in enumerate(bullets):
        nxt = bullets[index + 1] if index + 1 < len(bullets) else None
        is_model = bool(nxt and nxt.get("bullet") and nxt.get("indent", 0) > bullet.get("indent", 0))
        item = classify_item(bullet["text"])
        item["raw"] = bullet["text"]
        item["indent"] = bullet.get("indent", 0)
        item["isModel"] = is_model and item["kind"] == "gear"
        items.append(item)
    return items


def _blank_parsed() -> dict:
    return {
        "name": "",
        "points": None,
        "limit": None,
        "faction": "",
        "battleSize": "",
        "mission": "",
        "detachmentNames": [],
        "units": [],
    }


def consume_units(lines, start) -> list[dict]:
    units = []
    current = None
    section = None

    def flush():
        nonlocal current
        if not current:
            return
        current["items"] = shape_items(current.pop("bullets"))
        units.append(current)
        current = None

    for raw_line in lines[start:]:
        line = raw_line.rstrip()
        trimmed = line.strip()
        if not trimmed:
            continue
        bullet = bullet_of(line)
        if bullet:
            if current:
                current["bullets"].append(bullet)
            continue
        cont = continuation_of(line)
        if cont and current:
            current["bullets"].append(cont)
            continue
        if is_attachment_heading(trimmed):
            flush()
            section = trimmed
            continue
        header = unit_header(trimmed)
        if header and not is_battle_size(header["name"]):
            flush()
            current = {
                "name": header["name"],
                "points": header["points"],
                "section": section,
                "bullets": [],
            }
            continue
        nxt = section_name(trimmed)
        if nxt:
            flush()
            section = nxt
            continue
        if current and not config_key(trimmed):
            current["bullets"].append({"indent": 99, "text": trimmed, "bullet": False})
    flush()
    return units


def parse_labeled(text) -> dict:
    lines = text.split("\n")
    parsed = _blank_parsed()
    start = len(lines)
    for index, raw_line in enumerate(lines):
        trimmed = raw_line.strip()
        if not trimmed or re.match(r"^\+{3,}$", trimmed) or re.match(r"^#\s+\+\+", trimmed):
            continue
        key = config_key(trimmed)
        if key:
            if key["key"] == "faction":
                parsed["faction"] = key["value"]
            elif key["key"] == "battle size":
                parsed["battleSize"] = key["value"]
            elif key["key"] == "force disposition":
                parsed["mission"] = key["value"]
            elif key["key"] == "detachment":
                parsed["detachmentNames"] = split_detachment_line(key["value"])
            elif key["key"] == "list name" and not parsed["name"]:
                parsed["name"] = key["value"]
            continue
        header = unit_header(trimmed)
        if header and is_battle_size(header["name"]):
            parsed["battleSize"] = trimmed
            parsed["limit"] = header["points"]
            continue
        sec = section_name(trimmed)
        if sec and norm(sec) == "configuration":
            continue
        if header and not parsed["name"]:
            parsed["name"] = header["name"]
            parsed["points"] = header["points"]
            continue
        if header or sec or bullet_of(raw_line):
            start = index
            break
        if not parsed["name"]:
            parsed["name"] = re.sub(r"^#+\s*", "", trimmed)
    parsed["units"] = consume_units(lines, start)
    if parsed["battleSize"] and parsed["limit"] is None:
        size = unit_header(parsed["battleSize"])
        parsed["limit"] = size["points"] if size else parse_pts(parsed["battleSize"])
    return parsed


def parse_headerless(text) -> dict:
    lines = text.split("\n")
    parsed = _blank_parsed()
    preamble = []
    consumed_title = False
    preamble_open = True
    section = None
    current = None
    units = []

    def flush():
        nonlocal current
        if not current:
            return
        current["items"] = shape_items(current.pop("bullets"))
        units.append(current)
        current = None

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        bullet = bullet_of(raw)
        if bullet:
            preamble_open = False
            if current:
                current["bullets"].append(bullet)
            continue
        cont = continuation_of(raw)
        if cont and current:
            current["bullets"].append(cont)
            continue
        header = unit_header(line)
        if header:
            if is_battle_size(header["name"]):
                parsed["battleSize"] = line
                parsed["limit"] = header["points"]
                continue
            if not consumed_title and not current and not units:
                consumed_title = True
                parsed["name"] = header["name"]
                parsed["points"] = header["points"]
                continue
            preamble_open = False
            flush()
            current = {
                "name": header["name"],
                "points": header["points"],
                "section": section,
                "bullets": [],
            }
            continue
        nxt = line if is_attachment_heading(line) else section_name(line)
        if nxt:
            preamble_open = False
            flush()
            section = nxt
            continue
        if not consumed_title and not current and not units:
            consumed_title = True
            parsed["name"] = line
        elif preamble_open and not current and not units:
            preamble.append(line)
        elif current:
            current["bullets"].append({"indent": 99, "text": line, "bullet": False})
    flush()
    parts = list(preamble)
    mission_at = next((i for i, part in enumerate(parts) if is_mission(part)), -1)
    if mission_at >= 0:
        parsed["mission"] = parts.pop(mission_at)
    if parts:
        faction = parts.pop(0)
        if norm(faction) in BREADCRUMBS and parts:
            faction = parts.pop(0)
        parsed["faction"] = faction
        names = []
        for part in parts:
            names.extend(split_detachment_line(part))
        parsed["detachmentNames"] = names
    parsed["units"] = units
    return parsed


def has_labeled_config(text) -> bool:
    return any(config_key(line.strip()) for line in text.split("\n"))


def parse_roster(text) -> dict:
    clean = strip_footer(text)
    return parse_labeled(clean) if has_labeled_config(clean) else parse_headerless(clean)


def weapon_key(name) -> dict:
    text = str(name or "")
    text = re.sub(r"[➤•◦*]", " ", text)
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = text.replace("’", "'").replace("‘", "'").lower()
    hunter = bool(re.search(r"\bhunter\b", text))
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"\bhunter\b", " ", text)
    text = re.sub(r"\b(vs|monster|vehicle)\b", " ", text)
    text = re.sub(r"[^a-z0-9+-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    bits = [bit.strip() for bit in text.split("-") if bit.strip()]
    return {"base": bits[0] if bits else "", "mode": " ".join(bits[1:]), "hunter": hunter}


def same_weapon(left, right) -> bool:
    return (
        left["base"] == right["base"]
        and left["mode"] == right["mode"]
        and left["hunter"] == right["hunter"]
        and len(left["base"]) > 0
    )


def match_by_name(rows, raw, name_of):
    wanted = norm(raw)
    for item in rows or []:
        if norm(name_of(item)) == wanted:
            return item
    return None


def match_faction(raw, index):
    if not raw:
        return None
    wanted = norm(raw)
    factions = index.get("factions") or []
    for faction in factions:
        if norm(faction.get("name")) == wanted or norm(faction.get("id")) == wanted:
            return faction
    tail = [
        faction
        for faction in factions
        if wanted.endswith(norm(faction.get("name"))) and len(norm(faction.get("name"))) > 3
    ]
    tail.sort(key=lambda faction: len(norm(faction.get("name"))), reverse=True)
    return tail[0] if tail else None


def match_detachment(raw, index):
    for faction in index.get("factions") or []:
        found = match_by_name(faction.get("detachments") or [], raw, lambda det: det.get("name"))
        if found:
            return {
                **found,
                "factionId": faction.get("id"),
                "factionName": faction.get("name"),
            }
    return None


def _faction_by_id(index, faction_id):
    for faction in index.get("factions") or []:
        if faction.get("id") == faction_id:
            return faction
    return None


def _add_units(pool, seen, units):
    for unit in units or []:
        key = f"{unit.get('source') or ''}:{unit.get('id') or unit.get('name')}"
        if key in seen:
            continue
        seen.add(key)
        pool.append(unit)


def _shared_units(index, faction):
    shared_ids = (faction or {}).get("sharedUnitIds") or []
    if not faction or not shared_ids:
        return []
    marines = _faction_by_id(index, "space-marines")
    by_id = {unit.get("id"): unit for unit in (marines or {}).get("units") or []}
    return [by_id[unit_id] for unit_id in shared_ids if unit_id in by_id]


def _add_faction_units(pool, seen, index, faction):
    if not faction:
        return
    _add_units(pool, seen, faction.get("units"))
    _add_units(pool, seen, _shared_units(index, faction))


def unit_pool(index, faction, detachments):
    pool = []
    seen = set()
    _add_faction_units(pool, seen, index, faction)
    for det in detachments or []:
        if not det.get("factionId") or (faction and det.get("factionId") == faction.get("id")):
            continue
        _add_faction_units(pool, seen, index, _faction_by_id(index, det.get("factionId")))
    return pool


def match_unit(name, pool, index):
    direct = match_by_name(pool, name, lambda row: row.get("name"))
    if direct:
        return direct
    wanted = norm(name)
    hits = []
    for faction in index.get("factions") or []:
        for unit in faction.get("units") or []:
            if norm(unit.get("name")) == wanted:
                hits.append(unit)
    return hits[0] if len(hits) == 1 else None


def match_gear(name, unit, enhancements) -> dict:
    key = weapon_key(name)
    if unit:
        hits = [weapon for weapon in unit.get("weapons") or [] if same_weapon(weapon_key(weapon.get("name")), key)]
        if len(hits) == 1:
            return {"status": "weapon", "weapon": hits[0]}
        if len(hits) > 1:
            return {"status": "modes", "weapons": hits}
        for ability_name in unit.get("abilityNames") or []:
            if norm(ability_name) == norm(name):
                return {"status": "ability", "name": ability_name}
    for row in enhancements or []:
        if norm(row.get("name")) == norm(name):
            return {
                "status": "enhancement",
                "enhancement": {
                    "name": row.get("name"),
                    "points": row.get("points"),
                    "detachmentId": row.get("detachmentId"),
                },
            }
    if unit and key["mode"] == "" and not key["hunter"] and key["base"]:
        family = [
            weapon
            for weapon in unit.get("weapons") or []
            if weapon_key(weapon.get("name"))["base"] == key["base"]
            and not weapon_key(weapon.get("name"))["hunter"]
        ]
        if len(family) > 1:
            return {"status": "modes", "weapons": family}
        if len(family) == 1:
            return {"status": "weapon", "weapon": family[0]}
    return {"status": "unmatched"}


def match_roster(parsed, index) -> dict:
    faction = match_faction(parsed.get("faction"), index)
    detachments = []
    for name in parsed.get("detachmentNames") or []:
        match = match_detachment(name, index)
        detachments.append(
            {
                "raw": name,
                "id": match.get("id") if match else None,
                "name": match.get("name") if match else None,
                "ruleName": match.get("ruleName") if match else None,
                "ruleBody": (match.get("ruleBody") or "") if match else "",
                "ruleFlavor": (match.get("ruleFlavor") or "") if match else "",
                "stratagems": (match.get("stratagems") or []) if match else [],
                "factionId": match.get("factionId") if match else None,
            }
        )
    pool = unit_pool(index, faction, detachments)
    enhancements = []
    matched_ids = {det["id"] for det in detachments if det.get("id")}
    for faction_row in index.get("factions") or []:
        for enh in faction_row.get("enhancements") or []:
            if enh.get("detachmentId") in matched_ids:
                enhancements.append(enh)
    units = []
    for unit in parsed.get("units") or []:
        datasheet = match_unit(unit.get("name"), pool, index)
        items = []
        for item in unit.get("items") or []:
            if item.get("kind") == "annotation" or item.get("isModel"):
                items.append({**item, "match": None})
                continue
            if item.get("kind") == "enhancement":
                found = next((enh for enh in enhancements if norm(enh.get("name")) == norm(item.get("name"))), None)
                items.append(
                    {
                        **item,
                        "match": (
                            {
                                "status": "enhancement",
                                "enhancement": {
                                    "name": found.get("name"),
                                    "points": found.get("points"),
                                    "detachmentId": found.get("detachmentId"),
                                },
                            }
                            if found
                            else {"status": "unmatched"}
                        ),
                    }
                )
                continue
            items.append({**item, "match": match_gear(item.get("name"), datasheet, enhancements)})
        units.append(
            {
                "name": unit.get("name"),
                "points": unit.get("points"),
                "section": unit.get("section") or "",
                "datasheetId": datasheet.get("id") if datasheet else None,
                "datasheetName": datasheet.get("name") if datasheet else None,
                "source": datasheet.get("source") if datasheet else None,
                "profiles": (datasheet.get("profiles") or []) if datasheet else [],
                "items": items,
            }
        )
    army = (faction or {}).get("armyRule") or None
    return {
        "meta": {
            "name": parsed.get("name") or "",
            "points": parsed.get("points"),
            "limit": parsed.get("limit"),
            "factionRaw": parsed.get("faction") or "",
            "factionId": faction.get("id") if faction else None,
            "factionName": faction.get("name") if faction else None,
            "armyRule": (
                {
                    "id": army.get("id"),
                    "name": army.get("name"),
                    "body": army.get("body") or "",
                    "flavor": army.get("flavor") or "",
                }
                if army
                else None
            ),
            "battleSize": parsed.get("battleSize") or "",
            "mission": parsed.get("mission") or "",
        },
        "detachments": detachments,
        "units": units,
    }


def _sig_tokens(value) -> list[str]:
    drop = {"with", "and", "the", "a", "w"}
    return [token for token in profile_norm(value).split() if token not in drop]


def _same_token(left, right) -> bool:
    if left == right:
        return True
    stem_left = left[:-1] if left.endswith("s") else left
    stem_right = right[:-1] if right.endswith("s") else right
    return len(stem_left) >= 4 and stem_left == stem_right


def _tokens_cover(needles, haystack) -> bool:
    return all(any(_same_token(needle, token) for token in haystack) for needle in needles)


def match_profile(name, profiles):
    """Pick the datasheet profile row for a model line."""
    if not profiles:
        return None
    wanted = profile_norm(name)
    exact = [profile for profile in profiles if profile_norm(profile.get("name")) == wanted]
    if len(exact) == 1:
        return exact[0]
    wanted_tokens = _sig_tokens(name)
    covered = []
    for profile in profiles:
        tokens = _sig_tokens(profile.get("name"))
        if tokens and _tokens_cover(tokens, wanted_tokens):
            covered.append((len(tokens), profile))
    if covered:
        covered.sort(key=lambda item: item[0], reverse=True)
        return covered[0][1]
    leading = []
    for profile in profiles:
        tokens = _sig_tokens(profile.get("name"))
        if tokens and any(_same_token(tokens[0], token) for token in wanted_tokens):
            overlap = sum(1 for token in tokens if any(_same_token(token, have) for have in wanted_tokens))
            leading.append((overlap, len(tokens), profile))
    if leading:
        leading.sort(key=lambda item: (-item[0], item[1]))
        return leading[0][2]
    if len(profiles) == 1:
        return profiles[0]
    return None


def split_qty(raw) -> tuple[int, str]:
    match = _QTY_RE.match(str(raw or "").strip())
    if not match:
        return 1, str(raw or "").strip()
    return int(match.group(1)), match.group(2).strip()


def _weapon_row(weapon) -> dict:
    kind = weapon.get("kind") or "ranged"
    skill = weapon.get("bs") if kind == "ranged" else weapon.get("ws")
    return {
        "name": weapon.get("name") or "Weapon",
        "weapon_type": "melee" if kind == "melee" else "ranged",
        "range": weapon.get("range") or "",
        "attacks": weapon.get("a") or "",
        "skill": skill or "",
        "strength": weapon.get("s") or "",
        "ap": weapon.get("ap") or "",
        "damage": weapon.get("d") or "",
        "keywords": ", ".join(tag for tag in (weapon.get("tags") or []) if isinstance(tag, str)),
    }


def _unmatched_weapon(name) -> dict:
    folded = norm(name)
    melee = any(word in folded for word in ("shield", "hammer", "sword", "axe", "fist", "blade", "claw"))
    return {
        "name": name or "Weapon",
        "weapon_type": "melee" if melee else "ranged",
        "range": "",
        "attacks": "",
        "skill": "",
        "strength": "",
        "ap": "",
        "damage": "",
        "keywords": "",
    }


def _add_gear(model, item):
    match = item.get("match") or {}
    status = match.get("status")
    if status == "weapon" and match.get("weapon"):
        model["weapons"].append(_weapon_row(match["weapon"]))
        return
    if status == "modes":
        for weapon in match.get("weapons") or []:
            model["weapons"].append(_weapon_row(weapon))
        return
    if status == "ability":
        model["abilities"].append({"name": match.get("name") or item.get("name") or "Ability", "description": ""})
        return
    model["weapons"].append(_unmatched_weapon(item.get("name") or item.get("raw")))


def _blank_model(name, quantity, profile) -> dict:
    return {
        "name": (profile or {}).get("name") or name or "Model",
        "quantity": quantity or 1,
        "movement": (profile or {}).get("m") or "",
        "toughness": (profile or {}).get("t") or "",
        "save": (profile or {}).get("sv") or "",
        "wounds": (profile or {}).get("w") or "",
        "leadership": (profile or {}).get("ld") or "",
        "objective_control": (profile or {}).get("oc") or "",
        "invuln_save": (profile or {}).get("inv") or "",
        "base": "",
        "weapons": [],
        "abilities": [],
    }


def models_from_unit(unit) -> list[dict]:
    profiles = unit.get("profiles") or []
    gear = [
        item
        for item in unit.get("items") or []
        if item.get("kind") not in ("annotation", "enhancement")
    ]
    models = []
    current = None
    loose = []

    def start(name, quantity):
        nonlocal current
        profile = match_profile(name, profiles)
        current = _blank_model(name, quantity, profile)
        models.append(current)
        return current

    for item in gear:
        _qty, bare = split_qty(item.get("raw") or item.get("name") or "")
        if item.get("isModel"):
            if match_profile(bare, profiles):
                start(bare, _qty)
            continue
        if current is None:
            loose.append(item)
            continue
        _add_gear(current, item)
    if not models:
        label = unit.get("datasheetName") or unit.get("name") or "Model"
        profile = match_profile(label, profiles) or (profiles[0] if len(profiles) == 1 else None)
        if profile is None and profiles:
            profile = profiles[0]
        current = _blank_model(label, 1, profile)
        for item in loose or gear:
            if not item.get("isModel"):
                _add_gear(current, item)
        models.append(current)
    elif loose:
        for item in loose:
            _add_gear(models[0], item)
    return models


def _unit_dict(unit) -> dict:
    abilities = []
    for item in unit.get("items") or []:
        if item.get("kind") == "annotation":
            abilities.append({"name": item.get("label") or item.get("raw") or "Note", "description": ""})
        elif item.get("kind") == "enhancement":
            match = item.get("match") or {}
            enh = (match.get("enhancement") or {}).get("name") if match.get("status") == "enhancement" else None
            abilities.append({"name": enh or item.get("name") or "Enhancement", "description": ""})
    models = models_from_unit(unit)
    total = sum(model.get("quantity") or 1 for model in models)
    return {
        "name": unit.get("datasheetName") or unit.get("name") or "Unit",
        "quantity": 1,
        "points": unit.get("points") or 0,
        "keywords": "",
        "abilities": abilities,
        "models": models,
        "_model_total": total,
    }


def to_import_dict(matched) -> dict:
    """Shape ``match_roster`` output for ``wh40k.roster.action_import_parsed``."""
    meta = matched.get("meta") or {}
    units = [_unit_dict(unit) for unit in matched.get("units") or []]
    for unit in units:
        unit.pop("_model_total", None)
    points_used = meta.get("points")
    if points_used is None:
        points_used = sum(unit.get("points") or 0 for unit in units)
    limit = meta.get("limit") or points_used or 2000
    army_rules = []
    army = meta.get("armyRule")
    if army and army.get("name"):
        army_rules.append(
            {
                "name": army["name"],
                "description": readable(army.get("body") or ""),
                "external_id": army.get("id") or "",
                "rule_scope": "army",
                "flavor": readable(army.get("flavor") or ""),
            }
        )
    sources = list(matched.get("detachments") or [])
    if not sources:
        sources = [{"raw": "Army", "name": None, "stratagems": []}]
    detachments = []
    for index, det in enumerate(sources):
        rules = []
        if det.get("ruleName"):
            rules.append(
                {
                    "name": det["ruleName"],
                    "description": readable(det.get("ruleBody") or ""),
                    "external_id": det.get("id") or "",
                    "rule_scope": "detachment",
                    "flavor": readable(det.get("ruleFlavor") or ""),
                }
            )
        for strat in det.get("stratagems") or []:
            rules.append(
                {
                    "name": strat.get("name") or "Stratagem",
                    "description": "",
                    "external_id": "",
                    "rule_scope": "stratagem",
                    "cp": strat.get("cp") or "",
                    "when": readable(strat.get("when") or ""),
                    "target": readable(strat.get("target") or ""),
                    "effect": readable(strat.get("effect") or ""),
                    "restrictions": readable(strat.get("restrictions") or ""),
                    "flavor": readable(strat.get("flavor") or ""),
                }
            )
        detachments.append(
            {
                "name": det.get("name") or det.get("raw") or "Detachment",
                "rules": rules,
                "units": units if index == 0 else [],
            }
        )
    faction_name = meta.get("factionName") or meta.get("factionRaw") or "Army"
    return {
        "name": meta.get("name") or "Imported Roster",
        "game_system": "Warhammer 40,000",
        "points_limit": int(limit or 2000),
        "points_used": int(points_used or 0),
        "forces": [
            {
                "name": faction_name,
                "catalogue_name": faction_name,
                "army_rules": army_rules,
                "detachments": detachments,
            }
        ],
    }


def unmatched_gear(matched) -> list[str]:
    rows = []
    for unit in matched.get("units") or []:
        if not unit.get("datasheetId"):
            rows.append(unit.get("name") or "Unit")
        for item in unit.get("items") or []:
            if item.get("kind") == "annotation" or item.get("isModel"):
                continue
            status = (item.get("match") or {}).get("status")
            if status == "unmatched":
                rows.append(f"{unit.get('name')} · {item.get('name') or item.get('raw')}")
    return rows


def preview_dict(matched) -> dict:
    meta = matched.get("meta") or {}
    return {
        "name": meta.get("name") or "",
        "faction": meta.get("factionName") or meta.get("factionRaw") or "",
        "game_system": "Warhammer 40,000",
        "points_used": meta.get("points") or 0,
        "points_limit": meta.get("limit") or 2000,
        "units": [unit.get("name") for unit in matched.get("units") or []],
        "unit_count": len(matched.get("units") or []),
        "detachments": [det.get("name") or det.get("raw") for det in matched.get("detachments") or []],
        "unmatched": unmatched_gear(matched),
        "format": "text",
    }


class RosterTextParser:
    """Parse an official-app or New Recruit text export and resolve it."""

    def __init__(self, text: str, catalogue: dict | None = None):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Roster text is empty")
        self.text = text
        self.catalogue = catalogue if catalogue is not None else load_catalogue()

    def matched(self) -> dict[str, Any]:
        return match_roster(parse_roster(self.text), self.catalogue)

    def preview(self) -> dict[str, Any]:
        return preview_dict(self.matched())

    def parse(self) -> dict[str, Any]:
        return to_import_dict(self.matched())
