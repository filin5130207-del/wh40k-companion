/**
 * Resolve text rosters against the standard-r4-s1-e1 catalogue.
 *
 * Run:
 *   node addons/wh40k_companion/static/tests/test_rules_catalogue.mjs
 */
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const addon = join(here, "../..");
const src = readFileSync(join(here, "../src/pwa/rules_catalogue.js"), "utf8").replace(
    /\/\*\*\s*@odoo-module\s*\*\*\/\s*/,
    ""
);
const dir = mkdtempSync(join(tmpdir(), "wh40k-rules-"));
const out = join(dir, "rules_catalogue.mjs");
writeFileSync(out, src);
const mod = await import(pathToFileURL(out).href);
const catalogue = JSON.parse(
    readFileSync(join(addon, "data/rules_catalogue.json"), "utf8")
);

const PROSE = ["body", "ruleBody", "when", "target", "effect"];

function walkKeys(value, found) {
    if (Array.isArray(value)) {
        for (const item of value) walkKeys(item, found);
        return;
    }
    if (!value || typeof value !== "object") return;
    for (const [key, item] of Object.entries(value)) {
        if (PROSE.includes(key)) found.add(key);
        walkKeys(item, found);
    }
}

function proseKeys(value) {
    const found = new Set();
    walkKeys(value, found);
    return found;
}

function statusOf(result, unitName, gearName) {
    const unit = result.units.find((row) => row.name === unitName);
    if (!unit) return "missing-unit";
    const hit = unit.items.find(
        (item) => item.kind === "gear" && item.name.toLowerCase() === gearName.toLowerCase()
    );
    if (!hit || !hit.match) return "missing";
    return hit.match.status + (hit.match.weapon ? ":" + hit.match.weapon.name : "");
}

function run(file) {
    const text = readFileSync(join(addon, "testdata/text_rosters", file), "utf8");
    return mod.matchRoster(mod.parseRoster(text), catalogue);
}

let failed = 0;
function check(name, fn) {
    try {
        fn();
        console.log(`ok - ${name}`);
    } catch (err) {
        failed += 1;
        console.error(`FAIL - ${name}`);
        console.error(err);
    }
}

check("catalogue covers every faction in the snapshot", () => {
    assert.equal(catalogue.bundle, "standard-r4-s1-e1");
    assert.equal(catalogue.factionCount, 30);
    assert.equal(catalogue.factions.length, 30);
    const ids = new Set(catalogue.factions.map((faction) => faction.id));
    for (const id of ["space-wolves", "orks", "necrons", "tyranids", "tau-empire", "aeldari"]) {
        assert.ok(ids.has(id), id);
    }
    for (const faction of catalogue.factions) {
        assert.ok(faction.armyRule.name, faction.id);
        assert.ok(faction.armyRule.body && faction.armyRule.body.length > 20, faction.id);
        for (const det of faction.detachments) {
            assert.ok(det.ruleBody, `${faction.id}/${det.id} rule`);
            assert.ok(Array.isArray(det.stratagems), `${faction.id}/${det.id} stratagems`);
            for (const strat of det.stratagems) {
                for (const key of ["name", "cp", "when", "target", "effect", "restrictions"]) {
                    assert.equal(typeof strat[key], "string", `${strat.name} ${key}`);
                }
            }
        }
        for (const unit of faction.units) {
            assert.ok(unit.profiles.length, unit.id);
            for (const profile of unit.profiles) {
                for (const key of ["m", "t", "sv", "w", "ld", "oc", "inv"]) {
                    assert.equal(typeof profile[key], "string", `${unit.id} ${key}`);
                }
            }
            for (const weapon of unit.weapons) {
                for (const key of ["name", "range", "a", "s", "ap", "d"]) {
                    assert.equal(typeof weapon[key], "string", `${unit.id} ${weapon.name} ${key}`);
                }
                assert.ok(Array.isArray(weapon.tags), unit.id);
                if (weapon.kind === "ranged") assert.equal(typeof weapon.bs, "string");
                if (weapon.kind === "melee") assert.equal(typeof weapon.ws, "string");
            }
        }
    }
});

check("shared copy keeps rule prose and stats", () => {
    const ownerKeys = proseKeys(catalogue);
    for (const key of PROSE) assert.ok(ownerKeys.has(key), key);
    const wolves = catalogue.factions.find((faction) => faction.id === "space-wolves");
    assert.equal(wolves.armyRule.name, "Combat Doctrines");
    assert.ok(wolves.armyRule.body.length > 20);
    const det = wolves.detachments[0];
    assert.ok(det.ruleName);
    assert.ok(det.ruleBody.length > 20);
    assert.ok(det.stratagems[0].name);
    assert.ok(det.stratagems[0].cp);
    assert.ok(det.stratagems[0].when);
    assert.ok(det.stratagems[0].target);
    assert.ok(det.stratagems[0].effect);
    assert.equal(typeof det.stratagems[0].restrictions, "string");
    const unit = wolves.units[0];
    assert.ok(unit.profiles[0].t);
    assert.ok(unit.weapons.length === 0 || unit.weapons[0].name);
});

check("space wolves paste still resolves, including shared and deathwatch units", () => {
    const gg = run("gg.txt");
    assert.equal(gg.meta.factionId, "space-wolves");
    assert.equal(gg.meta.armyRule.name, "Combat Doctrines");
    assert.ok(gg.meta.armyRule.body.length > 40);
    assert.deepEqual(
        gg.detachments.map((det) => det.id),
        ["assault-brethren", "deathwatch-support", "terminator-storm-force"]
    );
    assert.ok(gg.detachments.every((det) => det.ruleBody && det.stratagems.length > 0));
    assert.ok(gg.units.every((unit) => unit.datasheetId && unit.profiles.length));
    assert.equal(statusOf(gg, "Logan Grimnar", "Storm Bolter"), "weapon:Storm Bolter");
    assert.equal(statusOf(gg, "Logan Grimnar", "Axe Morkai"), "modes");
    assert.ok(statusOf(gg, "Logan Grimnar", "Tyrnak and Fenrir").startsWith("weapon:"));
    assert.equal(
        gg.units.find((unit) => unit.name === "Logan Grimnar").profiles[0].inv,
        "4+"
    );
    const terminators = gg.units.find((unit) => unit.name === "Terminator Squad");
    assert.equal(terminators.source, "space-marines");
    const deathwatch = gg.units.find((unit) => unit.name === "Deathwatch Terminator Squad");
    assert.equal(deathwatch.source, "deathwatch");
    assert.ok(gg.meta.armyRule.body.length > 40);
    assert.ok(gg.detachments[0].ruleBody.length > 20);
    const strat = gg.detachments[0].stratagems[0];
    assert.ok(strat.name);
    assert.equal(strat.cp.length > 0, true);
    assert.ok(strat.when);
    assert.ok(strat.target);
    assert.ok(strat.effect);
});

check("new recruit space wolves text resolves the same books", () => {
    const auf = run("aufsky-drift.txt");
    assert.equal(auf.meta.factionId, "space-wolves");
    assert.equal(auf.meta.name, "Ауфский дрифт");
    assert.deepEqual(
        auf.detachments.map((det) => det.id),
        ["saga-of-the-beastslayer", "assault-brethren", "stormlance-task-force"]
    );
    assert.ok(auf.units.every((unit) => unit.datasheetId && unit.profiles.length));
    assert.equal(statusOf(auf, "Logan Grimnar", "Storm bolter"), "weapon:Storm Bolter");
});

function stormShields(result) {
    const rows = [];
    for (const unit of result.units) {
        for (const item of unit.items) {
            if (item.kind !== "gear" || item.isModel) continue;
            if (!/storm shield/i.test(item.name || "")) continue;
            rows.push(`${unit.name}:${item.match && item.match.status}`);
        }
    }
    return rows;
}

check("storm shield stays an unmatched weapon on both lists", () => {
    const gg = run("gg.txt");
    const auf = run("aufsky-drift.txt");
    const ggShields = stormShields(gg);
    const aufShields = stormShields(auf);
    assert.ok(ggShields.length >= 1, ggShields.join(","));
    assert.ok(aufShields.length >= 1, aufShields.join(","));
    assert.ok(ggShields.every((row) => row.endsWith(":unmatched")), ggShields.join(","));
    assert.ok(aufShields.every((row) => row.endsWith(":unmatched")), aufShields.join(","));
    assert.ok(gg.units.every((unit) => unit.datasheetId));
    assert.ok(auf.units.every((unit) => unit.datasheetId));
    assert.ok(gg.detachments.every((det) => det.id));
    assert.ok(auf.detachments.every((det) => det.id));
});

check("a non-space-wolves list resolves against its own book", () => {
    const orks = catalogue.factions.find((faction) => faction.id === "orks");
    const det = orks.detachments[0];
    const unit = orks.units.find((row) => row.weapons.length > 0);
    const weapon = unit.weapons[0];
    const text = [
        `${unit.name} list (1000 Points)`,
        "",
        "Faction: Orks",
        "Battle Size: Incursion (1000 Point limit)",
        `Detachment: ${det.name}`,
        "Force Disposition: Take and Hold",
        "",
        "## Character",
        "",
        `${unit.name} (100 pts)`,
        `  • 1x ${weapon.name}`,
        "",
    ].join("\n");
    const result = mod.matchRoster(mod.parseRoster(text), catalogue);
    assert.equal(result.meta.factionId, "orks");
    assert.equal(result.meta.armyRule.name, orks.armyRule.name);
    assert.ok(result.meta.armyRule.body.length > 20);
    assert.equal(result.detachments[0].id, det.id);
    assert.ok(result.detachments[0].ruleBody);
    assert.ok(result.detachments[0].stratagems.length > 0);
    assert.equal(result.units[0].datasheetId, unit.id);
    assert.equal(result.units[0].source, "orks");
    assert.equal(result.units[0].profiles[0].m, unit.profiles[0].m);
    const gear = result.units[0].items.find((item) => item.kind === "gear");
    assert.notEqual(gear.match.status, "unmatched");
});

check("same datasheet name stays on the roster faction", () => {
    const templars = catalogue.factions.find((faction) => faction.id === "black-templars");
    const own = templars.units.find((unit) => unit.name === "Gladiator Lancer");
    const marines = catalogue.factions.find((faction) => faction.id === "space-marines");
    const shared = marines.units.find((unit) => unit.name === "Gladiator Lancer");
    assert.ok(own && shared && own.id === shared.id);
    const det = templars.detachments[0];
    const text = [
        "Crusade (2000 Points)",
        "",
        "Faction: Black Templars",
        `Detachment: ${det.name}`,
        "",
        "## Other",
        "",
        "Gladiator Lancer (160 pts)",
        "  • 1x Lancer laser destroyer",
        "",
    ].join("\n");
    const result = mod.matchRoster(mod.parseRoster(text), catalogue);
    assert.equal(result.meta.factionId, "black-templars");
    assert.equal(result.meta.armyRule.name, templars.armyRule.name);
    assert.equal(result.detachments[0].id, det.id);
    assert.equal(result.units[0].source, "black-templars");
    assert.equal(result.units[0].datasheetId, own.id);
});

rmSync(dir, { recursive: true, force: true });
if (failed) {
    process.exit(1);
}
