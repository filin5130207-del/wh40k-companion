/** @odoo-module **/

import { Component, proxy, signal, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

const API = "/wh40k/api";

function extractJoinToken() {
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

function rememberJoinToken(token) {
    if (!token) {
        return;
    }
    try {
        sessionStorage.setItem("wh40k_join", token);
    } catch (_e) {
        // ignore quota / private mode
    }
}

function clearRememberedJoinToken() {
    try {
        sessionStorage.removeItem("wh40k_join");
    } catch (_e) {
        // ignore
    }
}

function parseOdooDatetime(value) {
    if (!value) {
        return null;
    }
    // Odoo JSON datetimes are UTC "YYYY-MM-DD HH:MM:SS"
    const iso = String(value).includes("T") ? String(value) : `${String(value).replace(" ", "T")}Z`;
    const ms = Date.parse(iso);
    return Number.isNaN(ms) ? null : ms;
}

export class Wh40kCompanionApp extends Component {
    static template = "wh40k_companion.CompanionApp";
    static props = {};
    rosterFile = signal.ref();

    setup() {
        const initialJoinToken = extractJoinToken();
        if (initialJoinToken) {
            rememberJoinToken(initialJoinToken);
        }
        this.state = proxy({
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
            rosterDetail: null, // full roster from /wh40k/roster/<id>/detail
            rosterDetailPaneMode: "units", // units | rules
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
            },
            join: {
                token: initialJoinToken,
                step: initialJoinToken ? "loading" : "token", // loading | token | invite | selecting
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
            activeMatch: null, // dashboard summary when an active match exists
            unitState: { host: [], guest: [], undo: {} },
            rules: [],
            ownRules: [],
            oppRules: [],
            ownPaneMode: "units", // units | rules
            oppPaneMode: "units",
            gameSide: "own", // own | opponent — only one side visible
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
        });
        this._poll = null;
        this._countdown = null;
        this._finishingMatch = false;
        this._waitingTimeoutHandled = false;

        onWillStart(async () => {
            await this.loadDashboard();
            await this.loadMissions();
            if (this.state.needsNickname) {
                this.state.screen = "nickname";
            } else if (this.state.join.token) {
                this.state.screen = "join";
                this.state.join.step = "loading";
                await this.verifyToken();
            }
        });

        onMounted(() => {
            // Waiting room + active game both poll through the same ticker.
            this._poll = setInterval(() => this.pollMatchLifecycle(), 5000);
            this._countdown = setInterval(() => this.tickCountdown(), 1000);
        });

        onWillUnmount(() => {
            if (this._poll) {
                clearInterval(this._poll);
            }
            if (this._countdown) {
                clearInterval(this._countdown);
            }
        });
    }

    get eligibleHostRosters() {
        const limit = parseInt(this.state.create.points, 10);
        return (this.state.rosters || []).filter((r) => r.points_used <= limit);
    }

    get showBottomNav() {
        // Keep sticky nav visible during the active match (game) so players can
        // leave without surrendering and still find their way back via resume.
        return [
            "home",
            "dashboard",
            "rosters",
            "roster_detail",
            "create_match",
            "join",
            "import_preview",
            "game",
            "result",
        ].includes(this.state.screen);
    }

    get activeMatchSummary() {
        const am = this.state.activeMatch;
        if (!am) {
            return "";
        }
        const parts = [];
        if (am.opponent_nickname) {
            parts.push(`vs ${am.opponent_nickname}`);
        }
        if (am.mission_name) {
            parts.push(am.mission_name);
        }
        if (am.points) {
            parts.push(`${am.points} pts`);
        }
        return parts.join(" · ") || "Матч ещё идёт";
    }

    get qrImageUrl() {
        const url = this.state.waiting.join_url || "";
        if (!url) {
            return "";
        }
        // Same-origin proxy — browsers on locked-down networks often block QR CDNs.
        return `/wh40k/qr.png?size=260&data=${encodeURIComponent(url)}`;
    }

    get countdownLabel() {
        const ms = Math.max(0, this.state.waiting.remaining_ms || 0);
        const totalSec = Math.floor(ms / 1000);
        const mm = String(Math.floor(totalSec / 60)).padStart(2, "0");
        const ss = String(totalSec % 60).padStart(2, "0");
        return `${mm}:${ss}`;
    }

    static UNDO_STACK_LIMIT = 20;

    get ownSideKey() {
        if (!this.state.match) {
            return "host";
        }
        return this.state.match.is_host ? "host" : "guest";
    }

    get oppSideKey() {
        return this.ownSideKey === "host" ? "guest" : "host";
    }

    get ownUnits() {
        if (!this.state.match) {
            return [];
        }
        return this.state.unitState[this.ownSideKey] || [];
    }

    get oppUnits() {
        if (!this.state.match) {
            return [];
        }
        return this.state.unitState[this.oppSideKey] || [];
    }

    get ownSideLabel() {
        if (!this.state.match) {
            return "Your army";
        }
        return this.state.match.is_host
            ? this.state.match.host?.nickname || "Host"
            : this.state.match.guest?.nickname || "Guest";
    }

    get oppSideLabel() {
        if (!this.state.match) {
            return "Opponent";
        }
        return this.state.match.is_host
            ? this.state.match.guest?.nickname || "Guest"
            : this.state.match.host?.nickname || "Host";
    }

    get ownRules() {
        return this.state.ownRules || [];
    }

    get oppRules() {
        return this.state.oppRules || [];
    }

    get rosterDetailUnits() {
        return (this.state.rosterDetail && this.state.rosterDetail.units) || [];
    }

    get rosterDetailRules() {
        return (this.state.rosterDetail && this.state.rosterDetail.rules) || [];
    }

    rosterUnitLabel(unit) {
        const pts = unit.points != null ? `${unit.points} pts` : "";
        const qty = unit.quantity != null ? `×${unit.quantity}` : "";
        const models = (unit.models || []).reduce((n, m) => n + (m.quantity || 0), 0);
        const modelBit = models ? `${models} models` : "";
        return [pts, qty, modelBit].filter(Boolean).join(" · ") || "Даташит";
    }

    unitStatusLabel(unit) {
        return (
            "Models " +
            unit.models_remaining +
            "/" +
            unit.models +
            " | Wounds " +
            unit.wounds_remaining +
            "/" +
            unit.wounds
        );
    }

    weaponLabel(w) {
        return (
            " | " +
            (w.weapon_type || "-") +
            " | R " +
            (w.range || "-") +
            " | A " +
            (w.A || "-") +
            " | " +
            (w.skill || "-") +
            " | S " +
            (w.S || "-") +
            " | AP " +
            (w.AP || "-") +
            " | D " +
            (w.D || "-")
        );
    }

    missionName() {
        return (this.state.match && this.state.match.mission && this.state.match.mission.name) || "";
    }

    setScreen(screen) {
        this.state.error = "";
        const next = screen === "dashboard" ? "home" : screen;
        this.state.screen = next;
        if (next !== "roster_detail" && next !== "game") {
            this.state.datasheet = null;
        }
        if (next !== "roster_detail") {
            this.state.rosterDetailPaneMode = "units";
        }
    }

    async openRosterDetail(rosterId) {
        if (!rosterId) {
            return;
        }
        try {
            this.state.busy = true;
            this.state.datasheet = null;
            this.state.rosterDetailPaneMode = "units";
            const data = await this.rpc(`${API}/roster/${rosterId}/detail`);
            const roster = data.roster || null;
            this.state.rosterDetail = roster;
            this._rosterCache = this._rosterCache || {};
            if (roster && roster.id) {
                this._rosterCache[roster.id] = roster;
            }
            this.state.busy = false;
            this.setScreen("roster_detail");
        } catch (e) {
            this.setError(e.message || "Не удалось открыть ростер.");
        }
    }

    closeRosterDetail() {
        this.state.datasheet = null;
        this.state.rosterDetailPaneMode = "units";
        this.setScreen("rosters");
    }

    toggleRosterDetailPaneMode() {
        this.state.rosterDetailPaneMode =
            this.state.rosterDetailPaneMode === "rules" ? "units" : "rules";
    }

    openManualJoin() {
        this.state.error = "";
        if (!this.state.join.verified) {
            this.state.join.step = "token";
        }
        this.state.screen = "join";
    }

    setError(err) {
        this.state.error = err || "Unexpected error";
        this.state.busy = false;
    }

    async rpc(route, params = {}) {
        this.state.error = "";
        const result = await rpc(route, params);
        if (result && result.ok === false) {
            throw new Error(result.error || "Request failed");
        }
        return result;
    }

    async loadDashboard() {
        const data = await this.rpc(`${API}/player/dashboard`);
        this.state.player = data.player;
        this.state.rosters = data.rosters || [];
        this.state.needsNickname = !(data.player && data.player.has_nickname);
        this.state.activeMatch = data.active_match || null;
        const pending = (data.pending_join_token || "").trim();
        if (pending && !this.state.join.token) {
            this.state.join.token = pending;
            rememberJoinToken(pending);
        } else if (pending && pending === this.state.join.token) {
            rememberJoinToken(pending);
        }
    }

    async refreshActiveMatch() {
        try {
            const data = await this.rpc(`${API}/match/active`);
            this.state.activeMatch = data.active_match || null;
        } catch (_e) {
            // non-fatal; banner simply stays as-is
        }
    }

    async resumeActiveMatch() {
        const matchId =
            (this.state.activeMatch && this.state.activeMatch.id) ||
            (this.state.match && this.state.match.id);
        if (!matchId) {
            this.setError("Нет активного матча для возврата.");
            return;
        }
        try {
            this.state.busy = true;
            await this.enterGame(matchId);
            this.state.busy = false;
        } catch (e) {
            this.state.busy = false;
            this.state.activeMatch = null;
            this.setError(e.message || "Не удалось вернуться в матч.");
        }
    }

    async loadMissions() {
        const data = await this.rpc(`${API}/missions`);
        this.state.missions = data.missions || [];
        if (!this.state.create.mission_id && this.state.missions.length) {
            this.state.create.mission_id = this.state.missions[0].id;
        }
    }

    onNicknameChange(ev) {
        this.state.player.nickname = ev.target.value;
    }

    async saveNickname() {
        try {
            this.state.busy = true;
            await this.rpc(`${API}/player/nickname`, { nickname: this.state.player.nickname });
            await this.loadDashboard();
            this.state.needsNickname = false;
            this.state.busy = false;
            if (this.state.join.token) {
                this.state.screen = "join";
                this.state.join.step = "loading";
                await this.verifyToken();
            } else {
                this.setScreen("home");
            }
        } catch (e) {
            this.setError(e.message);
        }
    }

    onRosterFile(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) {
            this.state.pendingRosterJson = null;
            this.state.importPreview = null;
            return;
        }
        const reader = new FileReader();
        reader.onload = async () => {
            try {
                this.state.pendingRosterJson = JSON.parse(reader.result);
                this.state.busy = true;
                const data = await this.rpc(`${API}/roster/preview`, {
                    roster_json: this.state.pendingRosterJson,
                });
                this.state.importPreview = data.preview;
                this.state.busy = false;
                this.setScreen("import_preview");
            } catch (e) {
                this.setError(e.message || "Invalid JSON file.");
                this.state.pendingRosterJson = null;
                this.state.importPreview = null;
            }
        };
        reader.readAsText(file);
    }

    cancelImportPreview() {
        this.state.pendingRosterJson = null;
        this.state.importPreview = null;
        const fileInput = this.rosterFile();
        if (fileInput) {
            fileInput.value = "";
        }
        this.setScreen("rosters");
    }

    async confirmImportRoster() {
        if (!this.state.pendingRosterJson) {
            this.setError("Choose a roster JSON file first.");
            return;
        }
        try {
            this.state.busy = true;
            await this.rpc(`${API}/roster/import`, {
                roster_json: this.state.pendingRosterJson,
            });
            await this.loadDashboard();
            this.state.busy = false;
            this.state.pendingRosterJson = null;
            this.state.importPreview = null;
            const fileInput = this.rosterFile();
            if (fileInput) {
                fileInput.value = "";
            }
            this.setScreen("rosters");
        } catch (e) {
            this.setError(e.message);
        }
    }

    onPointsChange(ev) {
        this.state.create.points = ev.target.value;
        this.state.create.roster_id = null;
    }

    selectMission(id) {
        this.state.create.mission_id = id;
    }

    selectHostRoster(id) {
        this.state.create.roster_id = id;
    }

    async createAndPublish() {
        if (!this.state.create.mission_id || !this.state.create.roster_id) {
            this.setError("Select a mission and a roster.");
            return;
        }
        try {
            this.state.busy = true;
            const created = await this.rpc(`${API}/match/create`, {
                roster_id: this.state.create.roster_id,
                mission_id: this.state.create.mission_id,
                points: this.state.create.points,
            });
            const published = await this.rpc(`${API}/match/publish`, {
                match_id: created.match_id,
            });
            this.state.waiting = {
                match_id: published.match_id,
                join_url: published.join_url,
                match_token: published.match_token,
                published_at: published.published_at,
                expires_at: published.expires_at,
                remaining_ms: (published.waiting_seconds || 900) * 1000,
            };
            this._waitingTimeoutHandled = false;
            this.tickCountdown();
            this.state.busy = false;
            this.setScreen("waiting");
        } catch (e) {
            this.setError(e.message);
        }
    }

    clearWaitingState() {
        this.state.waiting = {
            match_id: null,
            join_url: "",
            match_token: "",
            published_at: null,
            expires_at: null,
            remaining_ms: 15 * 60 * 1000,
        };
    }

    /**
     * 15min waiting timer expired (or server cancelled for timeout):
     * cancel server-side if still waiting, then land on home dashboard.
     */
    async leaveWaitingAfterTimeout(message) {
        if (this._waitingTimeoutHandled) {
            return;
        }
        this._waitingTimeoutHandled = true;
        const matchId = this.state.waiting.match_id;
        try {
            if (matchId) {
                await this.rpc(`${API}/match/cancel`, {
                    match_id: matchId,
                    reason: "Таймаут ожидания противника",
                });
            }
        } catch (_e) {
            // Already cancelled by cron / concurrent poll — still go home.
        }
        this.clearWaitingState();
        try {
            await this.loadDashboard();
        } catch (_e) {
            // still navigate home
        }
        this.setScreen("home");
        this.state.error =
            message || "Время ожидания истекло. Матч отменён.";
        this.state.busy = false;
    }

    tickCountdown() {
        if (this.state.screen !== "waiting") {
            return;
        }
        const expiresMs = parseOdooDatetime(this.state.waiting.expires_at);
        if (expiresMs) {
            this.state.waiting.remaining_ms = Math.max(0, expiresMs - Date.now());
        } else if (this.state.waiting.remaining_ms > 0) {
            this.state.waiting.remaining_ms = Math.max(0, this.state.waiting.remaining_ms - 1000);
        }
        if (this.state.waiting.remaining_ms <= 0 && this.state.waiting.match_id) {
            // Do not leave the host stuck on the waiting/QR screen.
            this.leaveWaitingAfterTimeout(
                "Время ожидания истекло. Матч отменён."
            );
        }
    }

    async pollMatchLifecycle() {
        if (this.state.screen === "waiting" && this.state.waiting.match_id) {
            await this.pollWaiting();
            return;
        }
        if (this.state.screen === "game" && this.state.match && this.state.match.id) {
            await this.pollActiveMatch();
        }
    }

    async pollWaiting() {
        if (this.state.screen !== "waiting" || !this.state.waiting.match_id) {
            return;
        }
        try {
            const data = await this.rpc(`${API}/match/state`, {
                match_id: this.state.waiting.match_id,
            });
            if (data.match.expires_at) {
                this.state.waiting.expires_at = data.match.expires_at;
            }
            if (data.match.state === "active") {
                await this.enterGame(data.match.id);
            } else if (data.match.state === "cancelled") {
                const reason = data.match.cancel_reason || "Матч отменён.";
                const isTimeout = reason.includes("Таймаут");
                if (isTimeout) {
                    await this.leaveWaitingAfterTimeout(
                        "Время ожидания истекло. Матч отменён."
                    );
                } else {
                    this.clearWaitingState();
                    this.setScreen("home");
                    this.state.error = reason;
                    try {
                        await this.loadDashboard();
                    } catch (_e) {
                        // ignore
                    }
                }
            } else if (
                data.match.state === "waiting" &&
                this.state.waiting.remaining_ms <= 0
            ) {
                await this.leaveWaitingAfterTimeout(
                    "Время ожидания истекло. Матч отменён."
                );
            }
        } catch (e) {
            // keep polling
        }
    }

    async pollActiveMatch() {
        if (this._finishingMatch || !this.state.match || !this.state.match.id) {
            return;
        }
        try {
            const data = await this.rpc(`${API}/match/state`, {
                match_id: this.state.match.id,
            });
            const match = data.match || {};
            if (match.state === "finished") {
                await this.goHomeAfterMatchEnd({
                    winner_id: match.winner_id,
                    winner_nickname: match.winner_nickname || "",
                    host: match.host,
                    guest: match.guest,
                    is_host: !!match.is_host,
                    you_surrendered: false,
                });
            } else if (match.state === "cancelled") {
                this.state.activeMatch = null;
                this.state.match = null;
                this.setError(match.cancel_reason || "Матч отменён.");
                this.setScreen("home");
            }
        } catch (_e) {
            // keep polling
        }
    }

    dismissMatchResultBanner() {
        this.state.result = {
            ...this.state.result,
            show_on_home: false,
            message: "",
        };
    }

    /**
     * Both players leave the game/result screens and land on the home
     * dashboard (with bottom nav). Optional banner summarizes the outcome.
     */
    async goHomeAfterMatchEnd({
        winner_id = null,
        winner_nickname = "",
        host = null,
        guest = null,
        is_host = false,
        you_won = null,
        you_surrendered = false,
        message = "",
    } = {}) {
        if (this._finishingMatch) {
            return;
        }
        this._finishingMatch = true;
        try {
            let resolvedWinnerNick = (winner_nickname || "").trim();
            if (!resolvedWinnerNick && winner_id) {
                if (host && host.id === winner_id) {
                    resolvedWinnerNick = host.nickname || "";
                } else if (guest && guest.id === winner_id) {
                    resolvedWinnerNick = guest.nickname || "";
                }
            }
            let resolvedYouWon = you_won;
            if (resolvedYouWon == null && winner_id && host && guest) {
                const myId = is_host ? host.id : guest.id;
                resolvedYouWon = myId === winner_id;
            }
            resolvedYouWon = !!resolvedYouWon;
            const resolvedMessage =
                message ||
                (you_surrendered
                    ? "Поражение. Вы сдались."
                    : resolvedYouWon
                      ? "Победа! Противник сдался."
                      : "Матч завершён.");
            this.state.result = {
                winner_nickname: resolvedWinnerNick,
                you_won: resolvedYouWon,
                you_surrendered: !!you_surrendered,
                message: resolvedMessage,
                show_on_home: true,
            };
            this.state.showSurrenderModal = false;
            this.state.activeMatch = null;
            this.state.match = null;
            this.state.datasheet = null;
            try {
                await this.loadDashboard();
            } catch (_e) {
                // still navigate home even if dashboard refresh fails
            }
            this.state.busy = false;
            this.setScreen("home");
        } finally {
            this._finishingMatch = false;
        }
    }

    async refreshMatch() {
        await this.pollMatchLifecycle();
    }

    async cancelWaiting() {
        if (!this.state.waiting.match_id) {
            this.clearWaitingState();
            this.setScreen("home");
            return;
        }
        try {
            await this.rpc(`${API}/match/cancel`, {
                match_id: this.state.waiting.match_id,
            });
            this.clearWaitingState();
            this._waitingTimeoutHandled = true;
            try {
                await this.loadDashboard();
            } catch (_e) {
                // ignore
            }
            this.setScreen("home");
        } catch (e) {
            this.setError(e.message);
        }
    }

    onJoinTokenChange(ev) {
        let value = (ev.target.value || "").trim();
        const urlMatch = value.match(/wh40k\/join\/([a-f0-9-]+)/i);
        if (urlMatch) {
            value = urlMatch[1];
        }
        const hashMatch = value.match(/wh40k_join=([^&]+)/);
        if (hashMatch) {
            value = decodeURIComponent(hashMatch[1]);
        }
        this.state.join.token = value;
        rememberJoinToken(value);
    }

    async verifyToken() {
        if (!this.state.join.token) {
            this.setError("Enter a match token.");
            this.state.join.step = "token";
            return;
        }
        try {
            this.state.busy = true;
            if (this.state.screen === "join" && this.state.join.step !== "invite") {
                this.state.join.step = "loading";
            }
            const verified = await this.rpc(`${API}/match/verify`, {
                match_token: this.state.join.token,
            });
            this.state.join.verified = true;
            this.state.join.step = "invite";
            this.state.join.host_nickname = verified.host?.nickname || "Host";
            this.state.join.points = verified.points;
            this.state.join.mission_name = verified.mission?.name || "";
            this.state.join.host_roster_name = verified.host_roster?.name || "";
            this.state.join.host_roster_faction = verified.host_roster?.faction || "";
            this.state.join.host_roster_points = verified.host_roster?.points_used || "";
            this.state.join.rosters = [];
            this.state.join.roster_id = null;
            clearRememberedJoinToken();
            this.state.busy = false;
        } catch (e) {
            this.state.join.step = "token";
            this.setError(e.message);
        }
    }

    async acceptInvite() {
        try {
            this.state.busy = true;
            const accepted = await this.rpc(`${API}/match/accept`, {
                match_token: this.state.join.token,
            });
            this.state.join.step = "selecting";
            this.state.join.rosters = accepted.rosters || [];
            this.state.join.roster_id = this.state.join.rosters[0]?.id || null;
            this.state.busy = false;
        } catch (e) {
            this.setError(e.message);
        }
    }

    declineInvite() {
        clearRememberedJoinToken();
        this.state.join = {
            token: "",
            step: "token",
            verified: false,
            host_nickname: "",
            host_roster_name: "",
            host_roster_faction: "",
            host_roster_points: "",
            points: "",
            mission_name: "",
            rosters: [],
            roster_id: null,
        };
        this.setScreen("home");
    }

    selectGuestRoster(id) {
        this.state.join.roster_id = id;
    }

    async joinMatch() {
        if (!this.state.join.roster_id) {
            this.setError("Select a roster to join with.");
            return;
        }
        try {
            this.state.busy = true;
            const joined = await this.rpc(`${API}/match/join`, {
                match_token: this.state.join.token,
                roster_id: this.state.join.roster_id,
            });
            this.state.busy = false;
            await this.enterGame(joined.match_id);
        } catch (e) {
            this.setError(e.message);
        }
    }

    async enterGame(matchId) {
        const data = await this.rpc(`${API}/match/state`, { match_id: matchId });
        if (data.match.state !== "active") {
            this.state.activeMatch = null;
            throw new Error(
                data.match.state === "finished"
                    ? "Матч уже завершён."
                    : data.match.state === "cancelled"
                      ? "Матч отменён."
                      : "Матч сейчас недоступен."
            );
        }
        this.state.match = data.match;
        this.state.activeMatch = {
            id: data.match.id,
            state: data.match.state,
            points: data.match.points,
            mission_name: (data.match.mission && data.match.mission.name) || "",
            opponent_nickname: data.match.is_host
                ? data.match.guest?.nickname || ""
                : data.match.host?.nickname || "",
            is_host: !!data.match.is_host,
        };
        const us = data.match.unit_state || {};
        this.state.unitState = {
            host: us.host || [],
            guest: us.guest || [],
            undo: us.undo || {},
        };
        this.state.ownPaneMode = "units";
        this.state.oppPaneMode = "units";
        this.state.gameSide = "own";
        this._swipeStartX = null;
        this._swipeStartY = null;
        this.state.ownRules = [];
        this.state.oppRules = [];
        this.state.rules = [];
        const ownRosterId = data.match.is_host
            ? data.match.host_roster_id
            : data.match.guest_roster_id;
        const oppRosterId = data.match.is_host
            ? data.match.guest_roster_id
            : data.match.host_roster_id;
        this._rosterCache = this._rosterCache || {};
        if (ownRosterId) {
            const detail = await this.rpc(`${API}/roster/${ownRosterId}/detail`);
            this._rosterCache[ownRosterId] = detail.roster;
            this.state.ownRules = detail.roster?.rules || [];
            this.state.rules = this.state.ownRules;
        }
        if (oppRosterId) {
            const other = await this.rpc(`${API}/roster/${oppRosterId}/detail`);
            this._rosterCache[oppRosterId] = other.roster;
            this.state.oppRules = other.roster?.rules || [];
        }
        this.setScreen("game");
    }

    setGameSide(side) {
        this.state.gameSide = side === "opponent" ? "opponent" : "own";
    }

    onGameSwipeStart(ev) {
        const t = ev.touches && ev.touches[0];
        if (!t) {
            return;
        }
        this._swipeStartX = t.clientX;
        this._swipeStartY = t.clientY;
    }

    onGameSwipeEnd(ev) {
        if (this._swipeStartX == null) {
            return;
        }
        const t = ev.changedTouches && ev.changedTouches[0];
        const startX = this._swipeStartX;
        const startY = this._swipeStartY;
        this._swipeStartX = null;
        this._swipeStartY = null;
        if (!t) {
            return;
        }
        const dx = t.clientX - startX;
        const dy = t.clientY - startY;
        // Require a clear horizontal swipe (ignore mostly-vertical scrolls).
        if (Math.abs(dx) < 56 || Math.abs(dx) <= Math.abs(dy) * 1.15) {
            return;
        }
        if (dx < 0) {
            this.setGameSide("opponent");
        } else {
            this.setGameSide("own");
        }
    }

    onGameSwipeCancel() {
        this._swipeStartX = null;
        this._swipeStartY = null;
    }

    toggleOwnPaneMode() {
        this.state.ownPaneMode = this.state.ownPaneMode === "rules" ? "units" : "rules";
    }

    toggleOppPaneMode() {
        this.state.oppPaneMode = this.state.oppPaneMode === "rules" ? "units" : "rules";
    }

    _undoKey(unit) {
        return String(unit.unit_id);
    }

    _snapshotUnit(unit) {
        return {
            models_remaining: unit.models_remaining,
            wounds_remaining: unit.wounds_remaining,
            destroyed: !!unit.destroyed,
        };
    }

    _cloneUnitState() {
        return {
            host: [...(this.state.unitState.host || [])],
            guest: [...(this.state.unitState.guest || [])],
            undo: { ...(this.state.unitState.undo || {}) },
        };
    }

    _pushUndo(unit) {
        const key = this._undoKey(unit);
        const undo = { ...(this.state.unitState.undo || {}) };
        const stack = [...(undo[key] || [])];
        stack.push(this._snapshotUnit(unit));
        if (stack.length > Wh40kCompanionApp.UNDO_STACK_LIMIT) {
            stack.splice(0, stack.length - Wh40kCompanionApp.UNDO_STACK_LIMIT);
        }
        undo[key] = stack;
        this.state.unitState = {
            host: [...(this.state.unitState.host || [])],
            guest: [...(this.state.unitState.guest || [])],
            undo,
        };
    }

    canUndo(unit) {
        if (!unit || !this.isOwnUnit(unit)) {
            return false;
        }
        const stack = (this.state.unitState.undo || {})[this._undoKey(unit)] || [];
        return stack.length > 0;
    }

    isOwnUnit(unit) {
        if (!unit || !this.state.match) {
            return false;
        }
        return unit.side === this.ownSideKey;
    }

    findUnitDetail(unit) {
        const cache = this._rosterCache || {};
        for (const roster of Object.values(cache)) {
            const found = (roster.units || []).find((u) => u.id === unit.unit_id);
            if (found) {
                return found;
            }
        }
        return { name: unit.name, models: [] };
    }

    openDatasheet(unit) {
        // Roster-detail units already carry models/weapons; match units need cache lookup.
        if (unit && Array.isArray(unit.models)) {
            this.state.datasheet = unit;
            return;
        }
        this.state.datasheet = this.findUnitDetail(unit);
    }

    closeDatasheet() {
        this.state.datasheet = null;
    }

    vibrate() {
        try {
            if (window.navigator && typeof window.navigator.vibrate === "function") {
                window.navigator.vibrate(40);
            }
        } catch (e) {
            // ignore
        }
    }

    async persistUnitState() {
        await this.rpc(`${API}/match/unit_state`, {
            match_id: this.state.match.id,
            unit_state: {
                host: this.state.unitState.host || [],
                guest: this.state.unitState.guest || [],
                undo: this.state.unitState.undo || {},
            },
        });
    }

    async adjustUnit(unit, field, delta) {
        if (!this.isOwnUnit(unit) || unit.destroyed) {
            return;
        }
        this._pushUndo(unit);
        if (field === "wounds") {
            unit.wounds_remaining = Math.max(0, Math.min(unit.wounds, unit.wounds_remaining + delta));
            if (unit.wounds_remaining === 0) {
                unit.models_remaining = 0;
                unit.destroyed = true;
                this.vibrate();
            }
        } else if (field === "models") {
            unit.models_remaining = Math.max(0, Math.min(unit.models, unit.models_remaining + delta));
            if (unit.models_remaining === 0) {
                unit.wounds_remaining = 0;
                unit.destroyed = true;
                this.vibrate();
            }
        }
        this.state.unitState = this._cloneUnitState();
        try {
            await this.persistUnitState();
        } catch (e) {
            this.setError(e.message);
        }
    }

    async destroyUnit(unit) {
        if (!this.isOwnUnit(unit) || unit.destroyed) {
            return;
        }
        this._pushUndo(unit);
        unit.models_remaining = 0;
        unit.wounds_remaining = 0;
        unit.destroyed = true;
        this.vibrate();
        this.state.unitState = this._cloneUnitState();
        try {
            await this.persistUnitState();
        } catch (e) {
            this.setError(e.message);
        }
    }

    async undoUnit(unit) {
        if (!this.canUndo(unit)) {
            return;
        }
        const key = this._undoKey(unit);
        const undo = { ...(this.state.unitState.undo || {}) };
        const stack = [...(undo[key] || [])];
        const prev = stack.pop();
        if (!prev) {
            return;
        }
        if (stack.length) {
            undo[key] = stack;
        } else {
            delete undo[key];
        }
        unit.models_remaining = prev.models_remaining;
        unit.wounds_remaining = prev.wounds_remaining;
        unit.destroyed = !!prev.destroyed;
        this.state.unitState = {
            host: [...(this.state.unitState.host || [])],
            guest: [...(this.state.unitState.guest || [])],
            undo,
        };
        try {
            await this.persistUnitState();
        } catch (e) {
            this.setError(e.message);
        }
    }

    openSurrenderModal() {
        this.state.showSurrenderModal = true;
    }

    closeSurrenderModal() {
        this.state.showSurrenderModal = false;
    }

    async confirmSurrender() {
        try {
            this.state.busy = true;
            this.state.showSurrenderModal = false;
            const result = await this.rpc(`${API}/match/surrender`, {
                match_id: this.state.match.id,
            });
            await this.goHomeAfterMatchEnd({
                winner_id: result.winner_id,
                winner_nickname: result.winner_nickname || "",
                you_won: !!result.you_won,
                you_surrendered: !!result.you_surrendered,
                message: result.message || "",
            });
        } catch (e) {
            this.setError(e.message);
        }
    }
}

