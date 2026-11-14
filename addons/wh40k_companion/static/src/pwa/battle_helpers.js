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
