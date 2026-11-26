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
    assert.deepEqual(state.openWeapons, {});
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

check("buildWoundDelta is one line, not both armies", () => {
    const unit = {
        line_id: 4,
        unit_id: 9,
        side: "host",
        models_remaining: 2,
        wounds_remaining: 1,
        destroyed: false,
    };
    const delta = mod.buildWoundDelta(unit, { "9": [{ wounds_remaining: 2 }] });
    assert.equal(delta.line_id, 4);
    assert.equal(delta.wounds_remaining, 1);
    assert.equal(delta.undo.length, 1);
    assert.equal(delta.host, undefined);
    assert.equal(delta.guest, undefined);
});

check("applyWoundDelta merges one line and keeps the other", () => {
    const state = {
        host: [
            { line_id: 1, unit_id: 10, side: "host", wounds_remaining: 3, destroyed: false },
        ],
        guest: [
            { line_id: 2, unit_id: 11, side: "guest", wounds_remaining: 5, destroyed: false },
        ],
        undo: {},
    };
    const next = mod.applyWoundDelta(state, {
        lines: [
            { line_id: 2, unit_id: 11, side: "guest", wounds_remaining: 4, destroyed: false },
        ],
        undo: { "11": [{ wounds_remaining: 5 }] },
    });
    assert.equal(next.host[0].wounds_remaining, 3);
    assert.equal(next.guest[0].wounds_remaining, 4);
    assert.equal(next.undo["11"].length, 1);
    assert.notEqual(next.guest[0], state.guest[0]);
});

check("watchMatchGoesHome is the finished or cancelled match", () => {
    assert.equal(mod.watchMatchGoesHome({ match: { state: "finished" } }), true);
    assert.equal(mod.watchMatchGoesHome({ match: { state: "cancelled" } }), true);
    assert.equal(
        mod.watchMatchGoesHome({
            lines_only: true,
            delta: { lines: [{}] },
            match: { state: "finished" },
        }),
        true
    );
    assert.equal(mod.watchMatchGoesHome({ lines_only: true, delta: { lines: [] } }), false);
    assert.equal(mod.watchMatchGoesHome({ match: { state: "active" } }), false);
    assert.equal(mod.watchMatchGoesHome(null), false);
});

check("bus frame keeps match updates and ignores other types", () => {
    const raw = JSON.stringify([
        {
            id: 3,
            message: {
                type: "wh40k.match/updated",
                payload: { match_id: 9, state: "finished", lines_only: false },
            },
        },
        { id: 4, message: { type: "mail.record/insert", payload: { id: 1 } } },
        { internal: true, type: "bus/last_id_reset", payload: 8 },
    ]);
    const frame = mod.parseBusFrame(raw);
    assert.equal(frame.lastIdReset, 8);
    assert.equal(frame.notifications.length, 1);
    const payloads = mod.parseBusNotifications(raw);
    assert.equal(payloads.length, 1);
    assert.equal(payloads[0].match_id, 9);
    assert.equal(payloads[0].state, "finished");
    assert.equal(mod.parseBusNotifications("not-json").length, 0);
    assert.equal(mod.parseBusNotifications({}).length, 0);
});

check("subscribe frame targets wh40k.match.<partner> on this origin", () => {
    const frame = mod.busSubscribeFrame(42, 7);
    assert.equal(frame.event_name, "subscribe");
    assert.deepEqual(frame.data.channels, ["wh40k.match.42"]);
    assert.equal(frame.data.last, 7);
    assert.equal(frame.data.check_outdated, false);
    const url = mod.busWebsocketUrl(
        { protocol: "https:", host: "example.com" },
        "saas-19.5-1"
    );
    assert.equal(url, "wss://example.com/websocket?version=saas-19.5-1");
});

check("watch is the fallback when the bus socket is down", () => {
    assert.equal(mod.shouldPollWatch({ busConnected: false }), true);
    assert.equal(mod.shouldPollWatch({ busConnected: true }), false);
    assert.equal(mod.shouldPollWatch(undefined), true);
    assert.equal(mod.shouldPollWatch({}), true);
});

check("an active bus join leaves the waiting screen without a long-poll", () => {
    assert.equal(
        mod.busJoinShouldEnter(
            { match_id: 4, state: "active", lines_only: false },
            4
        ),
        true
    );
    assert.equal(
        mod.busJoinShouldEnter(
            { match_id: 4, state: "selecting", lines_only: false },
            4
        ),
        false
    );
    assert.equal(
        mod.busJoinShouldEnter(
            { match_id: 4, state: "active", lines_only: true },
            4
        ),
        false
    );
    assert.equal(
        mod.busJoinShouldEnter(
            { match_id: 9, state: "active", lines_only: false },
            4
        ),
        false
    );
    assert.equal(mod.busJoinShouldEnter(null, 4), false);
});

check("own unit characteristics use the same fields as the opponent", () => {
    const own = {
        name: "Intercessors",
        profiles: [
            {
                name: "Intercessor",
                quantity: 5,
                M: '6"',
                T: "4",
                Sv: "3+",
                W: "2",
                LD: "6+",
                OC: "2",
                InSv: "",
            },
        ],
    };
    const opponent = {
        name: "Boyz",
        profiles: [
            {
                name: "Boy",
                quantity: 10,
                M: '6"',
                T: "5",
                Sv: "5+",
                W: "1",
                LD: "7+",
                OC: "2",
                InSv: "6+",
            },
        ],
    };
    assert.deepEqual(mod.unitProfileKeys(own), mod.unitProfileKeys(opponent));
    for (const key of ["M", "T", "Sv", "W", "LD", "OC", "InSv"]) {
        assert.ok(mod.unitProfileKeys(own).includes(key));
        assert.ok(mod.unitProfileKeys(opponent).includes(key));
    }
    const ownLine = mod.unitCharacteristicLines(own)[0];
    const oppLine = mod.unitCharacteristicLines(opponent)[0];
    for (const key of ["T", "Sv", "W"]) {
        assert.match(ownLine, new RegExp(`${key} `));
        assert.match(oppLine, new RegExp(`${key} `));
    }
    assert.match(oppLine, /InSv /);
    assert.equal(ownLine.includes("InSv "), false);
    const sheet = mod.datasheetFromMatchUnit(own, { name: own.name, models: [] });
    assert.equal(sheet.models[0].T, "4");
    assert.equal(sheet.models[0].Sv, "3+");
    assert.equal(sheet.models[0].W, "2");
});

check("squad header opens every model and a miniature opens only itself", () => {
    const state = mod.createInitialState();
    assert.deepEqual(state.openChars, {});
    assert.equal(mod.charScope(state.openChars, "4"), "");

    const unit = {
        name: "Boyz",
        line_id: 4,
        profiles: [
            {
                id: 7,
                name: "Boy",
                quantity: 2,
                M: '6"',
                T: "5",
                Sv: "5+",
                W: "2",
                LD: "7+",
                OC: "2",
                InSv: "6+",
            },
            {
                id: 8,
                name: "Nob",
                quantity: 1,
                M: '6"',
                T: "6",
                Sv: "4+",
                W: "3",
                LD: "6+",
                OC: "1",
                InSv: "",
            },
        ],
    };
    const squadLines = mod.unitCharacteristicLines(unit);
    assert.equal(squadLines.length, 2);
    assert.match(squadLines[0], /^Boy ×2: /);
    assert.match(squadLines[1], /^Nob: /);
    assert.match(squadLines[0], /T 5/);
    assert.match(squadLines[1], /T 6/);

    const rows = mod.buildModelRows(unit.profiles, unit.name);
    assert.equal(rows.length, 3);
    const boy = rows[0];
    const nob = rows[2];
    const boyLine = mod.modelCharacteristicLine(unit, boy);
    const nobLine = mod.modelCharacteristicLine(unit, nob);
    assert.match(boyLine, /^Boy 1: /);
    assert.match(boyLine, /T 5/);
    assert.equal(boyLine.includes("Nob"), false);
    assert.equal(boyLine.includes("×"), false);
    assert.match(nobLine, /^Nob: /);
    assert.match(nobLine, /T 6/);
    assert.equal(nobLine.includes("Boy"), false);
    assert.equal(mod.modelCharacteristicLine(unit, { key: "missing", model_id: 99, name: "Other" }), "");

    let open = mod.toggleSquadCharacteristics(state.openChars, "4");
    assert.equal(mod.charScope(open, "4"), "all");
    assert.equal(mod.charScope(open, "9"), "");
    open = mod.toggleModelCharacteristics(open, "4", boy.key);
    assert.equal(mod.charScope(open, "4"), boy.key);
    assert.equal(mod.charScope(open, "4") === "all", false);
    open = mod.toggleSquadCharacteristics(open, "4");
    assert.equal(mod.charScope(open, "4"), "all");
    open = mod.toggleSquadCharacteristics(open, "4");
    assert.equal(mod.charScope(open, "4"), "");
    open = mod.toggleModelCharacteristics(open, "4", nob.key);
    open = mod.toggleModelCharacteristics(open, "4", nob.key);
    assert.equal(mod.charScope(open, "4"), "");
    const other = mod.toggleModelCharacteristics(open, "9", boy.key);
    assert.equal(mod.charScope(other, "9"), boy.key);
    assert.equal(mod.charScope(other, "4"), "");
    assert.equal(mod.charScope({ 4: true }, "4"), "all");
});

check("chosen weapons keep stored stats and an empty shield stays a row", () => {
    const bolt = mod.weaponStatCells({
        name: "Bolt rifle",
        range: '24"',
        A: "2",
        skill: "3+",
        S: "4",
        AP: "-1",
        D: "1",
    });
    assert.equal(bolt.name, "Bolt rifle");
    assert.equal(bolt.range, '24"');
    assert.equal(bolt.attacks, "2");
    assert.equal(bolt.skill, "3+");
    assert.equal(bolt.strength, "4");
    assert.equal(bolt.ap, "-1");
    assert.equal(bolt.damage, "1");

    const shield = mod.weaponStatCells({
        name: "Storm Shield",
        weapon_type: "melee",
        range: false,
        A: false,
        skill: "",
        S: false,
        AP: "",
        D: false,
    });
    assert.equal(shield.name, "Storm Shield");
    for (const key of ["range", "attacks", "skill", "strength", "ap", "damage"]) {
        assert.equal(shield[key], "");
    }

    const models = [
        {
            id: 1,
            name: "Wolf Guard Terminator",
            weapons: [
                { name: "Storm bolter", range: '24"', A: "2", skill: "3+", S: "4", AP: "0", D: "1" },
                { name: "Storm Shield", range: "", A: "", skill: "", S: "", AP: "", D: "" },
            ],
        },
        {
            id: 2,
            name: "Wolf Guard Terminator Pack Leader",
            weapons: [{ name: "Thunder hammer", range: "Melee", A: "3", skill: "3+", S: "8", AP: "-2", D: "2" }],
        },
    ];
    const rows = mod.weaponRowsFromModels(models, true);
    assert.equal(rows.length, 3);
    assert.equal(rows[0].model, "Wolf Guard Terminator");
    assert.equal(rows[1].name, "Storm Shield");
    assert.equal(rows[1].model, "");
    assert.equal(rows[1].attacks, "");
    assert.equal(rows[1].damage, "");
    assert.equal(rows[2].model, "Wolf Guard Terminator Pack Leader");
    assert.equal(rows[2].attacks, "3");
    const shared = mod.weaponRowsFromModels(models, false);
    assert.equal(shared.length, 3);
    assert.equal(shared[1].name, "Storm Shield");
    assert.equal(shared[1].range, "");
    assert.equal(shared[1].attacks, "");
    assert.equal(shared[1].damage, "");
    const single = mod.weaponRowsFromModels([models[0]], true);
    assert.equal(single[0].model, "");
    assert.equal(single[1].name, "Storm Shield");
});

check("the squad card has no characteristics button", () => {
    const xml = readFileSync(join(here, "../src/pwa/companion_templates.xml"), "utf8");
    const start = xml.indexOf('t-name="wh40k_companion.SquadCard"');
    const end = xml.indexOf('t-name="wh40k_companion.GameScreen"');
    const card = xml.slice(start, end);
    assert.equal(card.includes("Характеристики"), false);
    assert.equal(card.includes("toggleChars"), false);
    assert.match(card, /toggleSquadChars\(unit\)/);
    assert.match(card, /toggleModelChars\(unit, row\)/);
    assert.match(card, />\s*Модели\s*</);
    assert.match(card, />\+M</);
    assert.match(card, />−M</);
    assert.match(card, />\+W</);
    assert.match(card, />−W</);
    assert.match(card, />Уничтожить</);
    assert.match(card, />Отменить</);
    assert.equal(card.includes("openDatasheet"), false);
    assert.match(card, /class="wh40k-muted wh40k-unit-chars"/);
    assert.equal(card.includes("wh40k-roster-char"), false);
    assert.equal(card.includes("isOwnUnit"), false);
    assert.match(card, /toggleWeapons\(unit\)/);
    assert.match(card, />\s*Оружие\s*</);
    assert.match(card, /t-if="this\.weaponsOpen\(unit\)"/);
    assert.equal(/isOwnUnit\(unit\) and this\.weaponsOpen\(unit\)/.test(card), false);
    assert.match(card, /matchWeaponRows\(unit\)/);
    assert.match(card, /t-call="wh40k_companion\.WeaponLines"/);
    const weaponButton = card.indexOf("Оружие");
    const weaponOpen = card.indexOf('t-if="this.weaponsOpen(unit)"');
    assert.ok(weaponButton !== -1 && weaponOpen > weaponButton);
    const app = readFileSync(join(here, "../src/pwa/companion_app.js"), "utf8");
    const fnStart = app.indexOf("matchWeaponRows(unit)");
    const fnEnd = app.indexOf("missionName()", fnStart);
    const fn = app.slice(fnStart, fnEnd);
    assert.equal(fn.includes("isOwnUnit"), false);
    assert.match(fn, /weaponRowsFromModels\(cached\)/);
    assert.match(fn, /weaponRowsFromModels\(profiles\)/);
});

check("roster datasheet colors stay off the match screen", () => {
    const xml = readFileSync(join(here, "../src/pwa/companion_templates.xml"), "utf8");
    const rosterStart = xml.indexOf('t-name="wh40k_companion.RosterDetailScreen"');
    const rosterEnd = xml.indexOf('t-name="wh40k_companion.ImportPreview"');
    const roster = xml.slice(rosterStart, rosterEnd);
    assert.match(roster, /wh40k_companion\.RosterDatasheetModal/);
    assert.equal(roster.includes('t-call="wh40k_companion.DatasheetModal"'), false);
    assert.match(roster, /toggleWeapons\(unit\)/);
    assert.match(roster, /weaponsOpen\(unit\)/);
    assert.match(roster, />\s*Оружие\s*</);
    assert.match(roster, /rosterWeaponRows\(unit\)/);
    assert.match(roster, /t-call="wh40k_companion\.WeaponLines"/);
    const rosterWeapons = roster.indexOf("rosterWeaponRows(unit)");
    const rosterGate = roster.lastIndexOf("weaponsOpen(unit)", rosterWeapons);
    assert.ok(rosterGate !== -1 && rosterGate < rosterWeapons);

    const linesStart = xml.indexOf('t-name="wh40k_companion.WeaponLines"');
    const linesEnd = xml.indexOf('t-name="wh40k_companion.RosterDatasheetModal"');
    const lines = xml.slice(linesStart, linesEnd);
    for (const label of ["Range", "A", "Skill", "S", "AP", "D"]) {
        assert.ok(lines.includes(label));
    }
    assert.match(lines, /weapon\.range/);
    assert.match(lines, /weapon\.attacks/);
    assert.match(lines, /weapon\.skill/);
    assert.match(lines, /weapon\.strength/);
    assert.match(lines, /weapon\.ap/);
    assert.match(lines, /weapon\.damage/);

    const gameStart = xml.indexOf('t-name="wh40k_companion.GameScreen"');
    const gameEnd = xml.indexOf('t-name="wh40k_companion.MatchResultScreen"');
    const game = xml.slice(gameStart, gameEnd);
    assert.match(
        game,
        /Кнопка «Оружие» показывает выбранное оружие отряда на вашем ростере и у противника/
    );
    assert.match(game, /t-call="wh40k_companion\.DatasheetModal"/);
    assert.equal(game.includes("RosterDatasheetModal"), false);
    assert.equal(game.includes("wh40k-roster-char"), false);

    const sheetStart = xml.indexOf('t-name="wh40k_companion.DatasheetModal"');
    const rosterSheetStart = xml.indexOf('t-name="wh40k_companion.RosterDatasheetModal"');
    const matchSheet = xml.slice(sheetStart, rosterSheetStart);
    assert.equal(matchSheet.includes("wh40k-roster-char"), false);
    const rosterSheet = xml.slice(rosterSheetStart);
    assert.match(rosterSheet, /wh40k-roster-char-label/);
    assert.match(rosterSheet, /wh40k-roster-char-value/);

    const css = readFileSync(join(here, "../src/pwa/companion.css"), "utf8");
    assert.match(
        css,
        /\.wh40k-roster-datasheet th\.wh40k-roster-char-label\s*\{[^}]*color:\s*var\(--wh40k-muted\)/
    );
    assert.match(
        css,
        /\.wh40k-roster-datasheet td\.wh40k-roster-char-value\s*\{[^}]*color:\s*#fff/
    );
    assert.equal(css.includes("wh40k-char-value"), false);
});

check("host cancel clears the waiting and join status", () => {
    const waiting = mod.createInitialState();
    waiting.screen = "waiting";
    waiting.error = "Cancelled by host";
    waiting.waiting.match_id = 9;
    waiting.waiting.join_url = "http://lan/wh40k/join/abc";
    const host = mod.applyHostCancel(waiting);
    assert.equal(host.screen, "home");
    assert.equal(host.error, "");
    assert.equal(host.waiting.match_id, null);
    assert.equal(host.waiting.join_url, "");

    const joining = mod.createInitialState();
    joining.screen = "join";
    joining.error = "Match is not joinable (state=cancelled).";
    joining.join.step = "invite";
    joining.join.token = "abc";
    joining.join.match_id = 9;
    joining.join.verified = true;
    const guest = mod.applyHostCancel(joining);
    assert.equal(guest.screen, "home");
    assert.equal(guest.error, "");
    assert.equal(guest.join.step, "token");
    assert.equal(guest.join.token, "");
    assert.equal(guest.join.match_id, null);
    assert.equal(guest.join.verified, false);

    assert.equal(
        mod.joinFailureLeavesScreen("Match is not joinable (state=cancelled)."),
        true
    );
    assert.equal(
        mod.joinFailureLeavesScreen("This match is not waiting for a guest."),
        true
    );
    assert.equal(mod.joinFailureLeavesScreen("Invalid match token."), false);
    assert.equal(mod.isWaitingTimeoutReason("Waiting timeout expired"), true);
    assert.equal(mod.isWaitingTimeoutReason("Cancelled by host"), false);
});

check("win rate ignores draws and is zero without decisive games", () => {
    assert.equal(mod.decisiveWinRate(2, 2), 50);
    assert.equal(mod.decisiveWinRate(1, 0), 100);
    assert.equal(mod.decisiveWinRate(3, 1), 75);
    assert.equal(mod.decisiveWinRate(0, 0), 0);
    assert.equal(mod.decisiveWinRate(0, 4), 0);
});

check("wounding or destroying one miniature rolls up to the squad", () => {
    const single = mod.buildModelRows(
        [{ id: 1, name: "Warboss", quantity: 1, W: "6" }],
        "Warboss"
    );
    assert.equal(single.length, 1);
    assert.equal(single[0].name, "Warboss");

    const unit = {
        name: "Boyz",
        line_id: 4,
        unit_id: 9,
        side: "guest",
        models: 2,
        models_remaining: 2,
        wounds: 4,
        wounds_remaining: 4,
        destroyed: false,
        profiles: [{ id: 7, name: "Boy", quantity: 2, W: "2" }],
    };
    const rows = mod.buildModelRows(unit.profiles, unit.name);
    assert.equal(rows.length, 2);
    assert.equal(rows[0].name, "Boy 1");
    assert.equal(rows[1].name, "Boy 2");
    unit.model_rows = rows;

    assert.equal(mod.applyModelOp(unit, rows[0].key, "wounds", -1), true);
    assert.equal(unit.models_remaining, 2);
    assert.equal(unit.wounds_remaining, 3);
    assert.equal(unit.destroyed, false);
    assert.equal(unit.model_rows[0].wounds_remaining, 1);
    assert.equal(unit.model_rows[1].wounds_remaining, 2);

    assert.equal(mod.applyModelOp(unit, rows[0].key, "destroy", 0), true);
    assert.equal(unit.models_remaining, 1);
    assert.equal(unit.wounds_remaining, 2);
    assert.equal(unit.model_rows[0].destroyed, true);
    assert.equal(unit.model_rows[0].models_remaining, 0);
    assert.equal(unit.model_rows[0].wounds_remaining, 0);
    assert.equal(unit.model_rows[1].models_remaining, 1);

    assert.equal(mod.applyModelOp(unit, rows[0].key, "undo", 0), true);
    assert.equal(unit.models_remaining, 2);
    assert.equal(unit.wounds_remaining, 3);
    assert.equal(unit.model_rows[0].destroyed, false);
    assert.equal(unit.model_rows[0].wounds_remaining, 1);
    assert.equal(unit.model_rows[0].models_remaining, 1);

    assert.equal(mod.applyModelOp(unit, rows[0].key, "models", -1), true);
    assert.equal(unit.models_remaining, 1);
    assert.equal(unit.wounds_remaining, 2);
    assert.equal(mod.applyModelOp(unit, rows[1].key, "destroy", 0), true);
    assert.equal(unit.models_remaining, 0);
    assert.equal(unit.wounds_remaining, 0);
    assert.equal(unit.destroyed, true);
    assert.equal(mod.applyModelOp(unit, rows[1].key, "undo", 0), true);
    assert.equal(unit.destroyed, false);
    assert.equal(unit.models_remaining, 1);
    assert.equal(unit.wounds_remaining, 2);
    const delta = mod.buildModelDelta(unit, rows[0].key, "undo", 0);
    assert.equal(delta.model_key, rows[0].key);
    assert.equal(delta.op, "undo");
    assert.equal(delta.side, "guest");
    assert.equal(delta.line_id, 4);
    assert.equal(delta.unit_id, 9);
});

check("a draw is its own result headline", () => {
    assert.equal(mod.matchResultHeadline({ is_draw: true, you_won: false }), "Ничья");
    assert.equal(mod.matchResultHeadline({ you_won: true }), "Победа!");
    assert.equal(
        mod.matchResultHeadline({ you_won: false, you_surrendered: true }),
        "Поражение"
    );
    assert.equal(mod.matchResultHeadline({ you_won: false }), "Матч завершён");
});

check("a join link is public only when the server says so", () => {
    const state = mod.createInitialState();
    assert.equal(state.waiting.join_url_public, false);
    assert.equal(mod.joinLinkIsPublic(state.waiting), false);
    assert.equal(mod.joinLinkIsPublic({ join_url_public: false }), false);
    assert.equal(mod.joinLinkIsPublic({ join_url: "http://192.168.0.163:8069/wh40k/join/x" }), false);
    assert.equal(mod.joinLinkIsPublic({ join_url_public: true }), true);
    assert.equal(mod.joinLinkIsPublic(null), false);
});

check("nextLinesRev only moves forward", () => {
    assert.equal(mod.nextLinesRev(2, 1), 2);
    assert.equal(mod.nextLinesRev(2, 4), 4);
    assert.equal(mod.nextLinesRev(undefined, 1), 1);
});

check("owner roster rename and delete stay on that list", () => {
    const state = mod.createInitialState();
    assert.equal(state.rosterRenameId, null);
    assert.equal(state.rosterRenameName, "");
    assert.equal(mod.cleanRosterName("  Ауфичи  "), "Ауфичи");
    assert.equal(mod.cleanRosterName("   "), "");
    assert.equal(mod.cleanRosterName(null), "");

    const rosters = [
        { id: 1, name: "Старое", points_used: 100 },
        { id: 2, name: "Чужой", points_used: 50 },
    ];
    const renamed = mod.renameRosterInList(rosters, 1, "  Новое имя  ");
    assert.equal(renamed[0].name, "Новое имя");
    assert.equal(renamed[1].name, "Чужой");
    assert.equal(rosters[0].name, "Старое");
    assert.equal(mod.renameRosterInList(rosters, 1, "   ")[0].name, "Старое");

    const left = mod.removeRosterFromList(renamed, "1");
    assert.deepEqual(left.map((row) => row.id), [2]);
    assert.equal(mod.removeRosterFromList(left, 9).length, 1);
    assert.equal(
        mod.rosterDeletePrompt("Ауфичи"),
        "Удалить ростер «Ауфичи»? Это нельзя отменить."
    );
    assert.match(mod.rosterDeletePrompt("  "), /этот ростер/);
    assert.equal(
        mod.rosterActionError(
            new Error("This roster is used in a match and cannot be deleted."),
            "Не удалось удалить ростер."
        ),
        "Этот ростер участвует в матче, удалить его нельзя."
    );
    assert.equal(
        mod.rosterActionError(new Error("Only the roster owner can change it.")),
        "Только владелец может изменить этот ростер."
    );
    assert.equal(
        mod.rosterActionError(new Error(""), "Не удалось удалить ростер."),
        "Не удалось удалить ростер."
    );

    const xml = readFileSync(join(here, "../src/pwa/companion_templates.xml"), "utf8");
    const start = xml.indexOf('t-name="wh40k_companion.RostersScreen"');
    const end = xml.indexOf('t-name="wh40k_companion.RosterDetailScreen"');
    const screen = xml.slice(start, end);
    assert.match(screen, /Переименовать/);
    assert.match(screen, /Удалить/);
    assert.match(screen, /Сохранить/);
    assert.match(screen, /Отмена/);
    assert.match(screen, /this\.deleteRoster\(roster\)/);
    assert.match(screen, /this\.saveRosterRename\(roster\.id\)/);
    assert.match(screen, /this\.openRosterDetail\(roster\.id\)/);
    const css = readFileSync(join(here, "../src/pwa/companion.css"), "utf8");
    assert.match(css, /\.wh40k-roster-actions/);
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
