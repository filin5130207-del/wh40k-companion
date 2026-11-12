/**
 * Node unit tests for pure Battle App helpers (no Odoo / OWL required).
 *
 * Run:
 *   node addons/wh40k_companion/static/tests/test_battle_helpers.mjs
 */
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const helpersPath = join(here, "../src/pwa/battle_helpers.js");
const src = readFileSync(helpersPath, "utf8").replace(
    /\/\*\*\s*@odoo-module\s*\*\*\/\s*/,
    ""
);
const dir = mkdtempSync(join(tmpdir(), "wh40k-helpers-"));
const out = join(dir, "battle_helpers.mjs");
writeFileSync(out, src);
const mod = await import(pathToFileURL(out).href);

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

check("parseOdooDatetime accepts space-separated UTC", () => {
    const ms = mod.parseOdooDatetime("2024-01-02 03:04:05");
    assert.equal(typeof ms, "number");
    assert.ok(ms > 0);
});

check("parseOdooDatetime rejects garbage", () => {
    assert.equal(mod.parseOdooDatetime(""), null);
    assert.equal(mod.parseOdooDatetime("not-a-date"), null);
});

check("extractJoinToken from query / path / storage", () => {
    const fakeWin = {
        location: {
            hash: "",
            search: "?wh40k_join=abc-123",
            pathname: "/wh40k/app",
        },
        sessionStorage: {
            getItem: () => "",
        },
    };
    assert.equal(mod.extractJoinToken(fakeWin), "abc-123");
    fakeWin.location.search = "";
    fakeWin.location.pathname = "/wh40k/join/deadbeef-cafe-babe-0000-111122223333";
    assert.equal(
        mod.extractJoinToken(fakeWin),
        "deadbeef-cafe-babe-0000-111122223333"
    );
    fakeWin.location.pathname = "/wh40k/app";
    fakeWin.sessionStorage.getItem = () => "from-session";
    assert.equal(mod.extractJoinToken(fakeWin), "from-session");
});

check("createInitialState seeds join token", () => {
    const state = mod.createInitialState("tok-1");
    assert.equal(state.join.token, "tok-1");
    assert.equal(state.join.step, "loading");
    assert.equal(state.screen, "home");
    assert.deepEqual(state.unitState, { host: [], guest: [], undo: {} });
});

check("filterEligibleRosters by points", () => {
    const rosters = [
        { id: 1, points_used: 500 },
        { id: 2, points_used: 2000 },
        { id: 3, points_used: 1001 },
    ];
    assert.deepEqual(
        mod.filterEligibleRosters(rosters, "1000").map((r) => r.id),
        [1]
    );
});

check("wound delta destroys at zero", () => {
    const unit = {
        unit_id: 7,
        wounds: 3,
        wounds_remaining: 1,
        models: 2,
        models_remaining: 2,
        destroyed: false,
    };
    const destroyed = mod.applyUnitFieldDelta(unit, "wounds", -1);
    assert.equal(destroyed, true);
    assert.equal(unit.destroyed, true);
    assert.equal(unit.models_remaining, 0);
});

check("undo stack push/pop", () => {
    const unit = {
        unit_id: 9,
        wounds: 2,
        wounds_remaining: 2,
        models: 1,
        models_remaining: 1,
        destroyed: false,
    };
    let undo = {};
    undo = mod.pushUndoEntry(undo, unit.unit_id, mod.snapshotUnit(unit), 2);
    mod.applyUnitFieldDelta(unit, "wounds", -1);
    undo = mod.pushUndoEntry(undo, unit.unit_id, mod.snapshotUnit(unit), 2);
    assert.equal(undo["9"].length, 2);
    const popped = mod.popUndoEntry(undo, 9);
    assert.equal(popped.snapshot.wounds_remaining, 1);
    assert.equal(popped.undo["9"].length, 1);
});

check("destroyUnitInPlace", () => {
    const unit = {
        models_remaining: 3,
        wounds_remaining: 5,
        destroyed: false,
    };
    mod.destroyUnitInPlace(unit);
    assert.equal(unit.destroyed, true);
    assert.equal(unit.models_remaining, 0);
    assert.equal(unit.wounds_remaining, 0);
});

check("rememberJoinToken / clear", () => {
    const mem = new Map();
    const storage = {
        setItem: (k, v) => mem.set(k, v),
        getItem: (k) => mem.get(k),
        removeItem: (k) => mem.delete(k),
    };
    mod.rememberJoinToken("xyz", storage);
    assert.equal(mem.get("wh40k_join"), "xyz");
    mod.clearRememberedJoinToken(storage);
    assert.equal(mem.has("wh40k_join"), false);
});

rmSync(dir, { recursive: true, force: true });

if (failed) {
    console.error(`\n${failed} failing test(s)`);
    process.exit(1);
}
console.log("\nAll battle_helpers tests passed.");
