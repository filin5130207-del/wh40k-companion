/** @odoo-module **/

import { reactive } from "@odoo/owl";

export const API = "/wh40k/api";

export function extractJoinToken() {
    const hash = window.location.hash || "";
    const query = window.location.search || "";
    const path = window.location.pathname || "";
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
        return sessionStorage.getItem("wh40k_join") || "";
    } catch (_e) {
        return "";
    }
}

export function rememberJoinToken(token) {
    if (!token) {
        return;
    }
    try {
        sessionStorage.setItem("wh40k_join", token);
    } catch (_e) {
        // ignore quota / private mode
    }
}

export function clearRememberedJoinToken() {
    try {
        sessionStorage.removeItem("wh40k_join");
    } catch (_e) {
        // ignore
    }
}

export function parseOdooDatetime(value) {
    if (!value) {
        return null;
    }
    const iso = String(value).includes("T") ? String(value) : `${String(value).replace(" ", "T")}Z`;
    const ms = Date.parse(iso);
    return Number.isNaN(ms) ? null : ms;
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

/**
 * Reactive battle store. Mutations should go through named actions on the
 * CompanionApp controller so OWL re-renders stay predictable.
 */
export function createBattleStore(initialJoinToken = "") {
    return reactive(createInitialState(initialJoinToken));
}
