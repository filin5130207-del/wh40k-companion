/** @odoo-module **/

/** Pure helpers for Battle App store / wound tracking (unit-testable without OWL). */

export const API = "/wh40k/api";
export const UNDO_STACK_LIMIT = 20;

export function extractJoinToken(win) {
    const scope = win || (typeof window !== "undefined" ? window : null);
    if (!scope) {
        return "";
    }
    const hash = scope.location?.hash || "";
    const query = scope.location?.search || "";
    const path = scope.location?.pathname || "";
    const fromHash = hash.match(/wh40k_join=([^&]+)/);
    if (fromHash) {
        return decodeURIComponent(fromHash[1]);
    }
    const params = new URLSearchParams(query.startsWith("?") ? query.slice(1) : query);
    const fromQuery = params.get("wh40k_join") || params.get("join") || "";
    if (fromQuery) {
        return fromQuery;
    }
    const fromPath = path.match(/\/wh40k\/join\/([a-f0-9-]+)/i);
    if (fromPath) {
        return fromPath[1];
    }
    try {
        return scope.sessionStorage?.getItem("wh40k_join") || "";
    } catch (_e) {
        return "";
    }
}

export function rememberJoinToken(token, storage) {
    if (!token) {
        return;
    }
    const store =
        storage ||
        (typeof sessionStorage !== "undefined" ? sessionStorage : null);
    if (!store) {
        return;
    }
    try {
        store.setItem("wh40k_join", token);
    } catch (_e) {
        // ignore quota / private mode
    }
}

export function clearRememberedJoinToken(storage) {
    const store =
        storage ||
        (typeof sessionStorage !== "undefined" ? sessionStorage : null);
    if (!store) {
        return;
    }
    try {
        store.removeItem("wh40k_join");
    } catch (_e) {
        // ignore
    }
}

export function parseOdooDatetime(value) {
    if (!value) {
        return null;
    }
    const iso = String(value).includes("T")
        ? String(value)
        : `${String(value).replace(" ", "T")}Z`;
    const ms = Date.parse(iso);
    return Number.isNaN(ms) ? null : ms;
}

export function filterEligibleRosters(rosters, pointsLimit) {
    const limit = parseInt(pointsLimit, 10);
    if (!Number.isFinite(limit)) {
        return [];
    }
    return (rosters || []).filter((r) => (r.points_used || 0) <= limit);
}

export function snapshotUnit(unit) {
    return {
        models_remaining: unit.models_remaining,
        wounds_remaining: unit.wounds_remaining,
        destroyed: !!unit.destroyed,
    };
}

export function pushUndoEntry(undoMap, unitId, snapshot, limit = UNDO_STACK_LIMIT) {
    const key = String(unitId);
    const next = { ...(undoMap || {}) };
    const stack = [...(next[key] || []), snapshot];
    if (stack.length > limit) {
        stack.splice(0, stack.length - limit);
    }
    next[key] = stack;
    return next;
}

export function popUndoEntry(undoMap, unitId) {
    const key = String(unitId);
    const next = { ...(undoMap || {}) };
    const stack = [...(next[key] || [])];
    const prev = stack.pop();
    if (!prev) {
        return { undo: next, snapshot: null };
    }
    if (stack.length) {
        next[key] = stack;
    } else {
        delete next[key];
    }
    return { undo: next, snapshot: prev };
}

/**
 * Apply wounds/models delta in place (matches CompanionApp.adjustUnit math).
 * Returns true when the unit became destroyed by this change.
 */
export function applyUnitFieldDelta(unit, field, delta) {
    let destroyedNow = false;
    if (field === "wounds") {
        unit.wounds_remaining = Math.max(
            0,
            Math.min(unit.wounds, unit.wounds_remaining + delta)
        );
        if (unit.wounds_remaining === 0) {
            unit.models_remaining = 0;
            unit.destroyed = true;
            destroyedNow = true;
        }
    } else if (field === "models") {
        unit.models_remaining = Math.max(
            0,
            Math.min(unit.models, unit.models_remaining + delta)
        );
        if (unit.models_remaining === 0) {
            unit.wounds_remaining = 0;
            unit.destroyed = true;
            destroyedNow = true;
        }
    }
    return destroyedNow;
}

export function destroyUnitInPlace(unit) {
    unit.models_remaining = 0;
    unit.wounds_remaining = 0;
    unit.destroyed = true;
    return unit;
}

/** Wins over decisive games. A draw is not in the denominator. */
export function decisiveWinRate(wins, losses) {
    const won = Number(wins) || 0;
    const lost = Number(losses) || 0;
    const decisive = won + lost;
    if (decisive <= 0) {
        return 0;
    }
    return (won * 100) / decisive;
}

export function woundValue(value) {
    const text = String(value == null || value === "" ? "1" : value)
        .replace("+", "")
        .trim();
    const parsed = parseInt(text || "1", 10);
    if (!Number.isFinite(parsed) || parsed < 1) {
        return 1;
    }
    return parsed;
}

/**
 * One row per miniature already on the roster.
 * A model profile with quantity 1 is a single row. Quantity N expands to N rows.
 */
export function buildModelRows(profiles, unitName) {
    const rows = [];
    (profiles || []).forEach((profile) => {
        if (!profile) {
            return;
        }
        const qty = Math.max(1, Number(profile.quantity) || 1);
        const wounds = woundValue(profile.W);
        const id = profile.id;
        const base = profile.name || unitName || "Model";
        for (let index = 0; index < qty; index += 1) {
            rows.push({
                key: `${id}:${index}`,
                model_id: id,
                index,
                name: qty > 1 ? `${base} ${index + 1}` : base,
                models: 1,
                models_remaining: 1,
                wounds,
                wounds_remaining: wounds,
                destroyed: false,
                undo: [],
            });
        }
    });
    return rows;
}

export function ensureModelRows(unit) {
    if (unit && Array.isArray(unit.model_rows) && unit.model_rows.length) {
        return unit.model_rows;
    }
    const rows = buildModelRows(unit && unit.profiles, unit && unit.name);
    if (unit) {
        unit.model_rows = rows;
    }
    return rows;
}

export function rollupModelRows(rows) {
    const list = rows || [];
    const models = list.reduce((sum, row) => sum + (Number(row.models) || 0), 0);
    let modelsRemaining = list.reduce(
        (sum, row) => sum + (Number(row.models_remaining) || 0),
        0
    );
    const wounds = list.reduce((sum, row) => sum + (Number(row.wounds) || 0), 0);
    let woundsRemaining = list.reduce(
        (sum, row) => sum + (Number(row.wounds_remaining) || 0),
        0
    );
    const destroyed = modelsRemaining === 0 || woundsRemaining === 0;
    if (destroyed) {
        modelsRemaining = 0;
        woundsRemaining = 0;
        list.forEach((row) => {
            row.models_remaining = 0;
            row.wounds_remaining = 0;
            row.destroyed = true;
        });
    }
    return {
        models,
        models_remaining: modelsRemaining,
        wounds,
        wounds_remaining: woundsRemaining,
        destroyed,
    };
}

function cloneModelRows(rows) {
    return (rows || []).map((row) => ({
        ...row,
        undo: (row.undo || []).map((entry) => ({ ...entry })),
    }));
}

/**
 * +M / -M / +W / -W / destroy / undo on one miniature.
 * Squad remaining models and wounds become the sum of the rows.
 * Returns true when the miniature changed.
 */
export function applyModelOp(unit, modelKey, op, delta) {
    if (!unit) {
        return false;
    }
    const rows = cloneModelRows(ensureModelRows(unit));
    const row = rows.find((item) => item.key === modelKey);
    if (!row) {
        return false;
    }
    if (op === "undo") {
        const stack = row.undo || [];
        const prev = stack.pop();
        if (!prev) {
            return false;
        }
        row.undo = stack;
        row.models_remaining = prev.models_remaining;
        row.wounds_remaining = prev.wounds_remaining;
        row.destroyed = !!prev.destroyed;
    } else {
        if (row.destroyed) {
            return false;
        }
        const before = {
            models_remaining: row.models_remaining,
            wounds_remaining: row.wounds_remaining,
            destroyed: !!row.destroyed,
        };
        if (op === "destroy") {
            row.models_remaining = 0;
            row.wounds_remaining = 0;
            row.destroyed = true;
        } else if (op === "wounds" || op === "models") {
            applyUnitFieldDelta(row, op, delta);
        } else {
            return false;
        }
        if (
            row.models_remaining === before.models_remaining &&
            row.wounds_remaining === before.wounds_remaining &&
            !!row.destroyed === before.destroyed
        ) {
            return false;
        }
        const stack = row.undo || [];
        stack.push(before);
        if (stack.length > UNDO_STACK_LIMIT) {
            stack.splice(0, stack.length - UNDO_STACK_LIMIT);
        }
        row.undo = stack;
    }
    const totals = rollupModelRows(rows);
    unit.model_rows = rows;
    if (totals.models) {
        unit.models = totals.models;
    }
    unit.models_remaining = totals.models_remaining;
    if (totals.wounds) {
        unit.wounds = totals.wounds;
    }
    unit.wounds_remaining = totals.wounds_remaining;
    unit.destroyed = totals.destroyed;
    return true;
}

export function buildModelDelta(unit, modelKey, op, delta) {
    return {
        line_id: unit.line_id,
        unit_id: unit.unit_id,
        side: unit.side,
        model_key: modelKey,
        op,
        delta: delta || 0,
    };
}

/** One changed line for /match/unit_state. Not the full host/guest lists. */
export function buildWoundDelta(unit, undoMap) {
    const key = String(unit.unit_id);
    const stack = (undoMap || {})[key] || [];
    return {
        line_id: unit.line_id,
        unit_id: unit.unit_id,
        side: unit.side,
        models_remaining: unit.models_remaining,
        wounds_remaining: unit.wounds_remaining,
        destroyed: !!unit.destroyed,
        undo: stack,
    };
}

/**
 * Merge a server wound delta into local unit state.
 * Lines absent from the delta are left as they are (optimistic edits stay).
 */
export function applyWoundDelta(unitState, delta) {
    const source = unitState || { host: [], guest: [], undo: {} };
    const next = {
        host: (source.host || []).map((unit) => ({ ...unit })),
        guest: (source.guest || []).map((unit) => ({ ...unit })),
        undo: { ...(source.undo || {}) },
    };
    const undo = (delta && delta.undo) || {};
    Object.keys(undo).forEach((key) => {
        next.undo[String(key)] = undo[key];
    });
    (delta && delta.lines ? delta.lines : []).forEach((entry) => {
        const bucket = entry.side === "guest" ? "guest" : "host";
        const idx = next[bucket].findIndex(
            (unit) =>
                (entry.line_id && unit.line_id === entry.line_id) ||
                (entry.unit_id && unit.unit_id === entry.unit_id)
        );
        const cleaned = { ...entry };
        delete cleaned.undo;
        if (idx >= 0) {
            next[bucket][idx] = { ...next[bucket][idx], ...cleaned };
        } else {
            next[bucket].push(cleaned);
        }
    });
    return next;
}

/** Watch/POST revisions only move forward so a late poll cannot rewind. */
export function nextLinesRev(current, incoming) {
    const cur = Number(current);
    const inc = Number(incoming);
    const safeCur = Number.isFinite(cur) ? cur : 0;
    const safeInc = Number.isFinite(inc) ? inc : 0;
    return safeInc > safeCur ? safeInc : safeCur;
}

/** Finished or cancelled watch body: leave the game, same as a late poll. */
export function watchMatchGoesHome(data) {
    const match = data && data.match;
    if (!match) {
        return false;
    }
    return match.state === "finished" || match.state === "cancelled";
}

/** Odoo bus notification type written by ``wh40k.match._notify_match_changed``. */
export const MATCH_BUS_TYPE = "wh40k.match/updated";

/** Channel the PWA subscribes to: ``wh40k.match.<partner_id>``. */
export function matchBusChannel(partnerId) {
    return `wh40k.match.${partnerId}`;
}

/**
 * Same-origin Odoo gevent bus. ``version`` is the server worker version;
 * a mismatch makes Odoo close the socket.
 */
export function busWebsocketUrl(loc, version) {
    const scope = loc || (typeof location !== "undefined" ? location : null);
    const protocol = scope && scope.protocol === "https:" ? "wss:" : "ws:";
    const host = (scope && scope.host) || "localhost";
    const base = `${protocol}//${host}/websocket`;
    if (!version) {
        return base;
    }
    return `${base}?version=${encodeURIComponent(version)}`;
}

/** ``subscribe`` frame for the Odoo 20 bus websocket. */
export function busSubscribeFrame(partnerId, last = 0) {
    const lastId = Number.isInteger(last) ? last : 0;
    return {
        event_name: "subscribe",
        data: {
            channels: [matchBusChannel(partnerId)],
            last: lastId,
            check_outdated: false,
        },
    };
}

/**
 * Parse one websocket text frame.
 *
 * Odoo sends a JSON array of ``{id, message: {type, payload}}``. Internal
 * worker messages (``bus/last_id_reset``) are not match updates.
 */
export function parseBusFrame(data) {
    let parsed;
    try {
        parsed = typeof data === "string" ? JSON.parse(data) : data;
    } catch (_e) {
        return { notifications: [], lastIdReset: null };
    }
    if (!Array.isArray(parsed)) {
        return { notifications: [], lastIdReset: null };
    }
    const notifications = [];
    let lastIdReset = null;
    for (const item of parsed) {
        if (!item || typeof item !== "object") {
            continue;
        }
        if (item.internal) {
            if (item.type === "bus/last_id_reset" && Number.isInteger(item.payload)) {
                lastIdReset = item.payload;
            }
            continue;
        }
        const message = item.message;
        if (!message || message.type !== MATCH_BUS_TYPE) {
            continue;
        }
        const payload = message.payload;
        if (!payload || payload.match_id == null) {
            continue;
        }
        notifications.push({ id: item.id, payload });
    }
    return { notifications, lastIdReset };
}

/** Match payloads from one bus frame. Other bus types are ignored. */
export function parseBusNotifications(data) {
    return parseBusFrame(data).notifications.map((item) => item.payload);
}

/**
 * Long-poll ``/match/watch`` only while the bus socket is down.
 * A live socket delivers surrender, wounds, and finish on its own.
 */
export function shouldPollWatch(busState) {
    return !(busState && busState.busConnected);
}

/** The waiting screen may call a link public only when the server says so. */
export function joinLinkIsPublic(waiting) {
    return !!(waiting && waiting.join_url_public === true);
}

/** Datasheet columns shown on both army cards. Same keys for own and opponent. */
export const UNIT_PROFILE_FIELDS = ["M", "T", "Sv", "W", "LD", "OC", "InSv"];

export function emptyWaitingState() {
    return {
        match_id: null,
        join_url: "",
        join_url_public: false,
        match_token: "",
        published_at: null,
        expires_at: null,
        remaining_ms: 15 * 60 * 1000,
        write_date: null,
    };
}

export function emptyJoinState() {
    return {
        token: "",
        step: "token",
        verified: false,
        match_id: null,
        host_nickname: "",
        host_roster_name: "",
        host_roster_faction: "",
        host_roster_points: "",
        points: "",
        mission_name: "",
        rosters: [],
        roster_id: null,
    };
}

/** Profile keys present on a unit payload. Empty values still count as present. */
export function unitProfileKeys(unit) {
    const profiles = (unit && unit.profiles) || [];
    if (!profiles.length) {
        return [];
    }
    return UNIT_PROFILE_FIELDS.filter((key) =>
        Object.prototype.hasOwnProperty.call(profiles[0], key)
    );
}

function characteristicBits(profile) {
    return UNIT_PROFILE_FIELDS.map((key) => {
        const value = profile && profile[key];
        if (value == null || String(value).trim() === "") {
            return "";
        }
        return `${key} ${value}`;
    }).filter(Boolean);
}

function formatCharacteristicLine(name, bits) {
    if (name && bits.length) {
        return `${name}: ${bits.join(" · ")}`;
    }
    return bits.join(" · ") || name;
}

/** One readable line per model: ``T 4 · Sv 3+ · W 2`` and the other columns. */
export function unitCharacteristicLines(unit) {
    const profiles = (unit && unit.profiles) || [];
    return profiles
        .map((profile) => {
            const bits = characteristicBits(profile);
            const qty = Number(profile.quantity) > 1 ? ` ×${profile.quantity}` : "";
            const name = profile.name ? `${profile.name}${qty}` : "";
            return formatCharacteristicLine(name, bits);
        })
        .filter(Boolean);
}

function profileForModelRow(unit, row) {
    const profiles = (unit && unit.profiles) || [];
    if (!row || !profiles.length) {
        return null;
    }
    const id = row.model_id;
    if (id == null || id === false || id === "") {
        return null;
    }
    return profiles.find((profile) => String(profile.id) === String(id)) || null;
}

/**
 * Characteristics of one miniature from the Модели list.
 * Squad lines still list every profile. This line is only that row's profile.
 */
export function modelCharacteristicLine(unit, row) {
    const profile = profileForModelRow(unit, row);
    if (!profile) {
        return "";
    }
    const name = (row && row.name) || profile.name || "";
    return formatCharacteristicLine(name, characteristicBits(profile));
}

/**
 * What a squad is showing.
 * ``all`` is every model. A model key is that miniature only. ``""`` is closed.
 */
export function charScope(openChars, squadKey) {
    const value = openChars && openChars[squadKey];
    if (value === true || value === "all") {
        return "all";
    }
    if (typeof value === "string" && value) {
        return value;
    }
    return "";
}

/** Squad header toggles every model's characteristics. A second tap closes them. */
export function toggleSquadCharacteristics(openChars, squadKey) {
    const next = { ...(openChars || {}) };
    if (!squadKey) {
        return next;
    }
    if (charScope(next, squadKey) === "all") {
        delete next[squadKey];
    } else {
        next[squadKey] = "all";
    }
    return next;
}

/**
 * One miniature toggles only its characteristics.
 * Opening it replaces the squad-wide list.
 */
export function toggleModelCharacteristics(openChars, squadKey, modelKey) {
    const next = { ...(openChars || {}) };
    const key = modelKey == null ? "" : String(modelKey);
    if (!squadKey || !key) {
        return next;
    }
    if (charScope(next, squadKey) === key) {
        delete next[squadKey];
    } else {
        next[squadKey] = key;
    }
    return next;
}

/**
 * Datasheet body for a match unit.
 * A cached roster model wins when it already has characteristics or weapons.
 * Otherwise the match payload profiles fill the same columns.
 */
export function datasheetFromMatchUnit(unit, cached) {
    const cachedModels = cached && Array.isArray(cached.models) ? cached.models : [];
    const cachedHasStats = cachedModels.some(
        (model) =>
            model &&
            (model.T ||
                model.Sv ||
                model.W ||
                model.M ||
                model.LD ||
                model.OC ||
                model.InSv ||
                (model.weapons && model.weapons.length))
    );
    if (cachedHasStats) {
        return cached;
    }
    const profiles = (unit && unit.profiles) || [];
    if (!profiles.length) {
        if (cached && cached.name) {
            return cached;
        }
        return { name: (unit && unit.name) || "", models: [] };
    }
    return {
        name: (cached && cached.name) || (unit && unit.name) || "",
        models: profiles.map((profile, index) => {
            const cachedModel = cachedModels[index] || {};
            return {
                id: profile.id || cachedModel.id || index,
                name: profile.name || cachedModel.name || (unit && unit.name) || "",
                quantity: profile.quantity || cachedModel.quantity || 1,
                M: profile.M || "",
                T: profile.T || "",
                Sv: profile.Sv || "",
                W: profile.W || "",
                LD: profile.LD || "",
                OC: profile.OC || "",
                InSv: profile.InSv || "",
                weapons: cachedModel.weapons || [],
            };
        }),
    };
}

export function isWaitingTimeoutReason(reason) {
    return /timeout|таймаут/i.test(String(reason || ""));
}

/**
 * Verify / accept / join failed because the host cancelled or the wait ended.
 * A bad token is not this case: the guest stays on the token step.
 */
export function joinFailureLeavesScreen(message) {
    return /not joinable|not waiting for a guest|not open for joining|was cancelled|match cancelled|timeout expired|таймаут/i.test(
        String(message || "")
    );
}

/**
 * Host cancelled the QR / join wait.
 * Drop the status banner and leave that screen for home.
 * A waiting timeout is a different path and may keep its message.
 */
export function applyHostCancel(state) {
    const screen = state && state.screen;
    const leave = screen === "waiting" || screen === "join";
    return {
        screen: leave ? "home" : screen || "home",
        error: "",
        busy: false,
        waiting: emptyWaitingState(),
        join: emptyJoinState(),
    };
}

export function matchResultHeadline(result) {
    if (result && (result.is_draw || result.outcome === "draw")) {
        return "Ничья";
    }
    if (result && result.you_won) {
        return "Победа!";
    }
    if (result && result.you_surrendered) {
        return "Поражение";
    }
    return "Матч завершён";
}

/**
 * Guest join on the host's bus channel: leave the QR screen now.
 * Do not wait for ``/match/watch`` to finish its long-poll.
 */
export function busJoinShouldEnter(payload, waitingMatchId) {
    if (!payload || payload.lines_only) {
        return false;
    }
    if (payload.state !== "active") {
        return false;
    }
    if (waitingMatchId == null || payload.match_id == null) {
        return false;
    }
    return Number(payload.match_id) === Number(waitingMatchId);
}

export const NO_DECK_MESSAGE = "no deck for this detachment";

/** «Правила» / «Стратагемы» toggle. The active target returns to the unit list. */
export function togglePaneMode(current, target) {
    return current === target ? "units" : target;
}

export function paneHeading(mode) {
    if (mode === "rules") {
        return "Правила армии";
    }
    if (mode === "stratagems") {
        return "Стратагемы";
    }
    return "Юниты";
}

export function stratagemKey(strat) {
    if (!strat) {
        return "";
    }
    return `${strat.detachment || ""}::${strat.name || ""}`;
}

/** Tap opens one stratagem. Tapping that same row again closes it. */
export function toggleOpenStratagem(openKey, strat) {
    const key = stratagemKey(strat);
    return openKey === key ? null : key;
}

export function stratagemCpLabel(cp) {
    if (cp === null || cp === undefined || cp === "") {
        return "";
    }
    return `${cp} CP`;
}

export function stratagemBody(strat) {
    if (!strat) {
        return "";
    }
    const parts = [];
    if (strat.when) {
        parts.push(String(strat.when));
    }
    if (strat.target) {
        parts.push(String(strat.target));
    }
    if (strat.rules) {
        parts.push(String(strat.rules));
    }
    return parts.join("\n\n");
}

/**
 * Read-only deck for one roster, own or opponent.
 * Rows show name and CP. ``openKey`` reveals that stratagem's text.
 */
export function stratagemDeckView(roster, openKey) {
    const list = (roster && roster.stratagems) || [];
    const rows = list.map((strat) => {
        const key = stratagemKey(strat);
        const open = !!openKey && openKey === key;
        return {
            key,
            name: strat.name || "",
            cp: strat.cp,
            cpLabel: stratagemCpLabel(strat.cp),
            open,
            text: open ? stratagemBody(strat) : "",
        };
    });
    const message = rows.length
        ? ""
        : (roster && roster.stratagem_message) || NO_DECK_MESSAGE;
    return { rows, message, empty: rows.length === 0 };
}

export function createInitialState(initialJoinToken = "") {
    return {
        screen: "home",
        busy: false,
        error: "",
        needsNickname: false,
        player: {
            nickname: "",
            wins: 0,
            losses: 0,
            draws: 0,
            total_match: 0,
            win_rate: 0,
        },
        rosters: [],
        rosterDetail: null,
        rosterDetailPaneMode: "units",
        rosterDetailOpenStratagem: null,
        ownStratagems: [],
        oppStratagems: [],
        ownStratagemMessage: "",
        oppStratagemMessage: "",
        ownDetachmentName: "",
        oppDetachmentName: "",
        ownOpenStratagem: null,
        oppOpenStratagem: null,
        missions: [],
        importPreview: null,
        create: {
            points: "2000",
            mission_id: null,
            roster_id: null,
        },
        waiting: emptyWaitingState(),
        join: {
            ...emptyJoinState(),
            token: initialJoinToken,
            step: initialJoinToken ? "loading" : "token",
        },
        match: null,
        activeMatch: null,
        unitState: { host: [], guest: [], undo: {} },
        rules: [],
        ownRules: [],
        oppRules: [],
        ownPaneMode: "units",
        oppPaneMode: "units",
        gameSide: "own",
        datasheet: null,
        // Squad header stores "all". A miniature stores its model key. Absent is closed.
        openChars: {},
        openModels: {},
        showSurrenderModal: false,
        showDrawModal: false,
        result: {
            winner_nickname: "",
            you_won: false,
            you_surrendered: false,
            is_draw: false,
            message: "",
            show_on_home: false,
        },
        pendingRosterJson: null,
        renderError: "",
    };
}
