#!/usr/bin/env python3
"""Build the addon rules catalogue from wh-rules-data standard-r4-s1-e1.

The published archive is the whole snapshot. This script keeps the fields a
text roster needs: faction, army rule, detachments and stratagems, model
profiles, and weapon profiles. Unit ability text is dropped. Shared Space
Marine datasheets stay on space-marines; other books point at them with
sharedUnitIds.

Source archive (catalog.json sha256):
https://github.com/wh-rules/wh-rules-data/releases/download/standard-r4-s1-e1/standard-r4-s1-e1.zip
94764efc5883dd7748e9c205afaf8cb97a3e1399171c9bd1ab03c4e32e0e962b
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

BUNDLE = "standard-r4-s1-e1"
EXPECTED_SHA256 = "94764efc5883dd7748e9c205afaf8cb97a3e1399171c9bd1ab03c4e32e0e962b"
DEFAULT_OUT = (
    Path(__file__).resolve().parents[1]
    / "addons"
    / "wh40k_companion"
    / "data"
    / "rules_catalogue.json"
)
PROSE_UNIT_KEYS = {"body", "text", "when", "target", "effect", "description", "flavor"}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def english(path: Path) -> dict:
    data = load_json(path)
    top = next(iter(data))
    block = data[top]
    if "en" not in block:
        raise SystemExit(f"{path} has no English block")
    return block["en"]


def weapon(entry: dict, kind: str) -> dict:
    row = {
        "name": entry.get("name") or "",
        "kind": kind,
        "range": entry.get("range") or "",
        "a": entry.get("a") or "",
        "s": entry.get("s") or "",
        "ap": entry.get("ap") or "",
        "d": entry.get("d") or "",
        "tags": [tag for tag in (entry.get("tags") or []) if isinstance(tag, str)],
    }
    if kind == "ranged":
        row["bs"] = entry.get("bs") or ""
    else:
        row["ws"] = entry.get("ws") or ""
    return row


def model_profile(entry: dict) -> dict:
    return {
        "name": entry.get("name") or "",
        "m": entry.get("m") or "",
        "t": entry.get("t") or "",
        "sv": entry.get("sv") or "",
        "w": entry.get("w") or "",
        "ld": entry.get("ld") or "",
        "oc": entry.get("oc") or "",
        "inv": entry.get("inv") or "",
    }


def slim_unit(unit: dict, source: str) -> dict:
    weapons = [weapon(row, "ranged") for row in unit.get("ranged") or []]
    weapons += [weapon(row, "melee") for row in unit.get("melee") or []]
    slim = {
        "id": unit.get("id"),
        "name": unit.get("name") or "",
        "source": source,
        "profiles": [model_profile(row) for row in (unit.get("profiles") or [])],
        "weapons": weapons,
        "abilityNames": [
            ability.get("name")
            for ability in (unit.get("abilities") or [])
            if ability.get("name")
        ],
    }
    leaked = PROSE_UNIT_KEYS.intersection(slim)
    if leaked:
        raise SystemExit(f"unit prose {leaked} on {slim.get('id')}")
    return slim


def build(bundle_dir: Path) -> dict:
    catalog_path = bundle_dir / "catalog.json"
    if not catalog_path.is_file():
        # A unpacked release zip has no catalog.json; the manifest sits at the root.
        release = {
            "appDataVersion": None,
            "mfmVersion": None,
            "names": {},
        }
        manifest = bundle_dir / "manifest.json"
        if manifest.is_file():
            manifest_data = load_json(manifest)
            tag = manifest_data.get("tag")
            if tag and tag != BUNDLE:
                raise SystemExit(f"manifest tag {tag} is not {BUNDLE}")
            release["appDataVersion"] = manifest_data.get("appDataVersion")
            release["mfmVersion"] = manifest_data.get("mfmVersion")
            release["names"] = {"en": manifest_data.get("name") or ""}
    else:
        catalog = load_json(catalog_path)
        release = next(
            row
            for row in catalog["families"]["standard"]["releases"]
            if row["tag"] == BUNDLE
        )
    faction_dir = bundle_dir / "data" / "factions"
    sheet_dir = bundle_dir / "data" / "datasheets"
    if not faction_dir.is_dir():
        raise SystemExit(f"missing {faction_dir}")
    factions = []
    sheets = {}
    for path in sorted(sheet_dir.glob("*.json")):
        sheets[path.stem] = load_json(path)
    marine_ids = {unit.get("id") for unit in (sheets.get("space-marines") or {}).get("default") or []}
    for path in sorted(faction_dir.glob("*.json")):
        slug = path.stem
        faction = english(path)
        sheet = sheets.get(slug) or {}
        units_raw = sheet.get("default") or []
        shared_ids = list(sheet.get("sharedUnitIds") or [])
        missing = [unit_id for unit_id in shared_ids if unit_id not in marine_ids]
        if missing:
            raise SystemExit(f"{slug} sharedUnitIds missing from space-marines: {missing[:5]}")
        detachments = []
        enhancements = []
        for det in faction.get("detachments") or []:
            rule = det.get("rule") or {}
            stratagems = []
            for strat in det.get("stratagems") or []:
                stratagems.append(
                    {
                        "name": strat.get("name") or "",
                        "cp": strat.get("cp") or "",
                        "when": strat.get("when") or "",
                        "target": strat.get("target") or "",
                        "effect": strat.get("effect") or "",
                        "restrictions": strat.get("restrictions") or "",
                    }
                )
            detachments.append(
                {
                    "id": det.get("id"),
                    "name": det.get("name") or "",
                    "ruleName": rule.get("name") or "",
                    "ruleBody": rule.get("body") or "",
                    "stratagems": stratagems,
                }
            )
            for enh in det.get("enhancements") or []:
                enhancements.append(
                    {
                        "name": enh.get("name") or "",
                        "points": enh.get("points"),
                        "detachmentId": det.get("id"),
                    }
                )
        army = faction.get("armyRule") or {}
        factions.append(
            {
                "id": slug,
                "name": faction.get("name") or "",
                "armyRule": {
                    "id": army.get("id") or "",
                    "name": army.get("name") or "",
                    "body": army.get("body") or "",
                },
                "sharedUnitIds": shared_ids,
                "detachments": detachments,
                "enhancements": enhancements,
                "units": [slim_unit(unit, slug) for unit in units_raw],
            }
        )
    return {
        "bundle": BUNDLE,
        "appDataVersion": release.get("appDataVersion"),
        "mfmVersion": release.get("mfmVersion"),
        "bundleName": (release.get("names") or {}).get("en") or "GW app 2.8.1 · MFM 1.6",
        "archiveSha256": EXPECTED_SHA256,
        "factionCount": len(factions),
        "factions": factions,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle",
        type=Path,
        required=True,
        help="Unpacked standard-r4-s1-e1 directory, or the wh-rules-data repo root",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    catalogue = build(args.bundle)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(catalogue, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    units = sum(len(faction["units"]) for faction in catalogue["factions"])
    detachments = sum(len(faction["detachments"]) for faction in catalogue["factions"])
    print(
        f"wrote {args.out} factions={catalogue['factionCount']} "
        f"units={units} detachments={detachments} bytes={args.out.stat().st_size}"
    )


if __name__ == "__main__":
    main()
