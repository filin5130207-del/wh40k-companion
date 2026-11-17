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
            total_match: 0,
            win_rate: 0,
        },
        rosters: [],
        rosterDetail: null,
        rosterDetailPaneMode: "units",
        missions: [],
        importPreview: null,
        create: {
            points: "2000",
            mission_id: null,
            roster_id: null,
        },
        waiting: {
            match_id: null,
            join_url: "",
            join_url_public: false,
            match_token: "",
            published_at: null,
            expires_at: null,
            remaining_ms: 15 * 60 * 1000,
            write_date: null,
        },
        join: {
            token: initialJoinToken,
            step: initialJoinToken ? "loading" : "token",
            verified: false,
            host_nickname: "",
            host_roster_name: "",
            host_roster_faction: "",
            host_roster_points: "",
            points: "",
            mission_name: "",
            rosters: [],
            roster_id: null,
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
        showSurrenderModal: false,
        result: {
            winner_nickname: "",
            you_won: false,
            you_surrendered: false,
            message: "",
            show_on_home: false,
        },
        pendingRosterJson: null,
        renderError: "",
    };
}
