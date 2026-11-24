/** @odoo-module **/

import { Component, signal, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import {
    API,
    extractJoinToken,
    rememberJoinToken,
    clearRememberedJoinToken,
    parseOdooDatetime,
    createBattleStore,
    filterEligibleRosters,
    snapshotUnit,
    pushUndoEntry,
    popUndoEntry,
    applyUnitFieldDelta,
    destroyUnitInPlace,
    decisiveWinRate,
    buildModelRows,
    applyModelOp,
    buildModelDelta,
    buildWoundDelta,
    applyWoundDelta,
    nextLinesRev,
    watchMatchGoesHome,
    shouldPollWatch,
    joinLinkIsPublic,
    busJoinShouldEnter,
    emptyJoinState,
    unitCharacteristicLines as linesForProfiles,
    modelCharacteristicLine as lineForModel,
    charScope,
    toggleSquadCharacteristics,
    toggleModelCharacteristics,
    datasheetFromMatchUnit,
    isWaitingTimeoutReason,
    joinFailureLeavesScreen,
    applyHostCancel,
    matchResultHeadline,
    UNDO_STACK_LIMIT,
} from "./battle_store";
import { createMatchBus } from "./bus_client";
import { matchRoster, parseRoster } from "./rules_catalogue";
import { Wh40kErrorBoundary } from "./error_boundary";
import {
    NicknameGate,
    HomeScreen,
    RostersScreen,
    RosterDetailScreen,
    ImportPreview,
    CreateMatch,
    WaitingScreen,
    JoinScreen,
    GameScreen,
    MatchResultScreen,
} from "./components/screen_host";

export class Wh40kCompanionApp extends Component {
    static template = "wh40k_companion.CompanionApp";
    static components = {
        Wh40kErrorBoundary,
        NicknameGate,
        HomeScreen,
        RostersScreen,
        RosterDetailScreen,
        ImportPreview,
        CreateMatch,
        WaitingScreen,
        JoinScreen,
        GameScreen,
        MatchResultScreen,
    };
    rosterFile = signal.ref();

    setup() {
        const initialJoinToken = extractJoinToken();
        if (initialJoinToken) {
            rememberJoinToken(initialJoinToken);
        }
        this.state = createBattleStore(initialJoinToken);
        this._watchLoop = false;
        this._countdown = null;
        this._finishingMatch = false;
        this._waitingTimeoutHandled = false;
        this._bus = null;
        this._busConnected = false;
        this._busRefreshing = false;
        this._busPending = null;
        this._enteringMatchId = null;
        this._joinProbeAt = 0;
        this._joinProbeBusy = false;

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
            this._watchLoop = true;
            this.startMatchBus();
            this.runWatchLoop();
            this._countdown = setInterval(() => this.tickCountdown(), 1000);
        });

        onWillUnmount(() => {
            this._watchLoop = false;
            if (this._bus) {
                this._bus.stop();
                this._bus = null;
            }
            this._busConnected = false;
            if (this._countdown) {
                clearInterval(this._countdown);
            }
        });
    }

    recoverFromRenderError() {
        this.state.renderError = "";
        this.state.error = "";
        this.setScreen("home");
    }

    get eligibleHostRosters() {
        return filterEligibleRosters(this.state.rosters, this.state.create.points);
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

    get joinLinkIsPublic() {
        return joinLinkIsPublic(this.state.waiting);
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

    static UNDO_STACK_LIMIT = UNDO_STACK_LIMIT;

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
            "Модели " +
            unit.models_remaining +
            "/" +
            unit.models +
            " · Раны " +
            unit.wounds_remaining +
            "/" +
            unit.wounds
        );
    }

    winRateLabel() {
        const player = this.state.player || {};
        return decisiveWinRate(player.wins, player.losses).toFixed(0) + "%";
    }

    squadKey(unit) {
        return String((unit && (unit.line_id || unit.unit_id)) || "");
    }

    charsOpen(unit) {
        return charScope(this.state.openChars, this.squadKey(unit)) === "all";
    }

    modelCharsOpen(unit, row) {
        const key = row && row.key != null ? String(row.key) : "";
        return !!key && charScope(this.state.openChars, this.squadKey(unit)) === key;
    }

    modelsOpen(unit) {
        return !!(this.state.openModels && this.state.openModels[this.squadKey(unit)]);
    }

    toggleSquadChars(unit) {
        this.state.openChars = toggleSquadCharacteristics(
            this.state.openChars,
            this.squadKey(unit)
        );
    }

    toggleModelChars(unit, row) {
        this.state.openChars = toggleModelCharacteristics(
            this.state.openChars,
            this.squadKey(unit),
            row && row.key
        );
    }

    toggleModels(unit) {
        const key = this.squadKey(unit);
        const openModels = { ...(this.state.openModels || {}) };
        openModels[key] = !openModels[key];
        this.state.openModels = openModels;
    }

    modelRows(unit) {
        if (unit && Array.isArray(unit.model_rows) && unit.model_rows.length) {
            return unit.model_rows;
        }
        return buildModelRows(unit && unit.profiles, unit && unit.name);
    }

    modelStatusLabel(row) {
        return (
            "M " +
            row.models_remaining +
            "/" +
            row.models +
            " · W " +
            row.wounds_remaining +
            "/" +
            row.wounds
        );
    }

    canUndoModel(row) {
        return !!(row && row.undo && row.undo.length);
    }

    rosterProfiles(unit) {
        if (!unit || unit.unit_id == null) {
            return [];
        }
        const detail = this.findUnitDetail(unit);
        if (!detail || !Array.isArray(detail.models) || !detail.models.length) {
            return [];
        }
        return detail.models.map((model) => ({
            id: model.id,
            name: model.name,
            quantity: model.quantity,
            M: model.M,
            T: model.T,
            Sv: model.Sv,
            W: model.W,
            LD: model.LD,
            OC: model.OC,
            InSv: model.InSv,
        }));
    }

    unitCharacteristicLines(unit) {
        const fromPayload = linesForProfiles(unit);
        if (fromPayload.length) {
            return fromPayload;
        }
        return linesForProfiles({ profiles: this.rosterProfiles(unit) });
    }

    modelCharacteristicLine(unit, row) {
        const fromPayload = lineForModel(unit, row);
        if (fromPayload) {
            return fromPayload;
        }
        return lineForModel({ profiles: this.rosterProfiles(unit) }, row);
    }

    resultHeadline() {
        return matchResultHeadline(this.state.result);
    }

    get resultBannerClass() {
        if (this.state.result && this.state.result.is_draw) {
            return "wh40k-result-draw";
        }
        if (this.state.result && this.state.result.you_won) {
            return "wh40k-result-win";
        }
        return "wh40k-result-loss";
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
        // The catalogue is the owner's rules reference. It is not copied onto
        // match state, which is what the opponent receives.
        if (next === "rosters" || next === "roster_detail") {
            this.ensureRulesCatalogue();
        }
    }

    ensureRulesCatalogue() {
        if (this._rulesCatalogue) {
            return Promise.resolve(this._rulesCatalogue);
        }
        if (this._rulesCataloguePromise) {
            return this._rulesCataloguePromise;
        }
        this._rulesCataloguePromise = this.rpc(`${API}/rules/catalogue`)
            .then((data) => {
                this._rulesCatalogue = data.catalogue || null;
                return this._rulesCatalogue;
            })
            .catch((error) => {
                this._rulesCataloguePromise = null;
                this._rulesCatalogueError = error;
                return null;
            });
        return this._rulesCataloguePromise;
    }

    async resolveTextRoster(text) {
        const catalogue = await this.ensureRulesCatalogue();
        if (!catalogue) {
            throw new Error("Rules catalogue is not loaded.");
        }
        return matchRoster(parseRoster(text), catalogue);
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
                join_url_public: published.join_url_public === true,
                match_token: published.match_token,
                published_at: published.published_at,
                expires_at: published.expires_at,
                remaining_ms: (published.waiting_seconds || 900) * 1000,
                write_date: published.write_date || null,
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
        const next = applyHostCancel({ screen: "home" });
        this.state.waiting = next.waiting;
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
                    reason: "Waiting timeout expired",
                });
            }
        } catch (_e) {
            // Already cancelled by cron / concurrent poll — still go home.
        }
        this.clearWaitingState();
        this.state.join = emptyJoinState();
        clearRememberedJoinToken();
        try {
            await this.loadDashboard();
        } catch (_e) {
            // still navigate home
        }
        this.setScreen("home");
        this.state.error =
            message || "Waiting time expired. Match cancelled.";
        this.state.busy = false;
    }

    /**
     * Host cancelled the QR / join wait. Clear the status and leave that screen.
     * Unlike the timeout path, the banner must not stay on the next screen.
     */
    async leaveAfterHostCancel() {
        const next = applyHostCancel({ screen: this.state.screen });
        this._waitingTimeoutHandled = true;
        this.state.waiting = next.waiting;
        this.state.join = next.join;
        this.state.busy = false;
        this.state.error = "";
        clearRememberedJoinToken();
        this.setScreen(next.screen);
        this.state.error = "";
        try {
            await this.loadDashboard();
        } catch (_e) {
            // home is already showing
        }
        this.state.error = "";
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
                "Waiting time expired. Match cancelled."
            );
        }
    }

    startMatchBus() {
        const partnerId = this.state.player && this.state.player.id;
        if (!partnerId) {
            this._busConnected = false;
            return;
        }
        const shell = typeof window !== "undefined" ? window.odoo || {} : {};
        this._bus = createMatchBus({
            partnerId,
            lastId: shell.wh40k_bus_last_id,
            version: shell.wh40k_bus_version || "",
            onConnection: (connected) => {
                this._busConnected = connected;
            },
            onNotification: (payload) => {
                this.onMatchBusNotification(payload);
            },
        });
    }

    _busTargetsOpenMatch(payload) {
        if (!payload || payload.match_id == null) {
            return false;
        }
        const matchId = payload.match_id;
        if (this.state.screen === "waiting" && this.state.waiting.match_id === matchId) {
            return true;
        }
        if (
            this.state.screen === "join" &&
            this.state.join.match_id != null &&
            Number(this.state.join.match_id) === Number(matchId)
        ) {
            return true;
        }
        return !!(
            this.state.screen === "game" &&
            this.state.match &&
            this.state.match.id === matchId
        );
    }

    async onMatchBusNotification(payload) {
        if (!this._busTargetsOpenMatch(payload)) {
            return;
        }
        // Keep the latest payload. A join must not be dropped behind a refresh.
        this._busPending = payload;
        if (this._busRefreshing) {
            return;
        }
        this._busRefreshing = true;
        try {
            while (this._busPending && this._watchLoop) {
                const next = this._busPending;
                this._busPending = null;
                if (
                    this.state.screen === "waiting" &&
                    busJoinShouldEnter(next, this.state.waiting.match_id)
                ) {
                    // /match/state, not the long-poll. The row is already committed.
                    try {
                        await this.enterGame(next.match_id);
                        continue;
                    } catch (_enter) {
                        // State route missed the row. Short watch is the fallback.
                    }
                }
                if (!this._busTargetsOpenMatch(next)) {
                    continue;
                }
                await this.pollMatchLifecycle(1);
            }
        } catch (_e) {
            // The watch loop retries if the socket drops.
        } finally {
            this._busRefreshing = false;
        }
    }

    async runWatchLoop() {
        while (this._watchLoop) {
            this.maybeProbeJoinCancel();
            // The socket is the live path. Watch stays for a failed or dropped bus.
            if (!shouldPollWatch({ busConnected: this._busConnected })) {
                await new Promise((r) => setTimeout(r, 500));
                continue;
            }
            try {
                await this.pollMatchLifecycle();
            } catch (_e) {
                // keep loop alive
            }
            // When not watching a match, idle briefly.
            if (
                !(
                    (this.state.screen === "waiting" && this.state.waiting.match_id) ||
                    (this.state.screen === "game" && this.state.match && this.state.match.id)
                )
            ) {
                await new Promise((r) => setTimeout(r, 1500));
            }
        }
    }

    async pollMatchLifecycle(timeout) {
        if (this.state.screen === "waiting" && this.state.waiting.match_id) {
            await this.watchMatch(
                this.state.waiting.match_id,
                this.state.waiting.write_date,
                (match) => this.applyWaitingWatch(match),
                timeout
            );
            return;
        }
        if (this.state.screen === "game" && this.state.match && this.state.match.id) {
            await this.watchMatch(
                this.state.match.id,
                this.state.match.write_date,
                (match) => this.applyActiveWatch(match),
                timeout
            );
            return;
        }
        if (
            this.state.screen === "join" &&
            this.state.join.step === "selecting" &&
            this.state.join.match_id
        ) {
            const matchId = this.state.join.match_id;
            await this.watchMatch(
                matchId,
                null,
                (match) => this.applyJoinWatch(match, matchId),
                timeout
            );
        }
    }

    maybeProbeJoinCancel() {
        if (this._joinProbeBusy) {
            return;
        }
        if (this.state.screen !== "join") {
            return;
        }
        const step = this.state.join.step;
        if (step !== "invite" && step !== "selecting") {
            return;
        }
        if (!this.state.join.token && !this.state.join.match_id) {
            return;
        }
        const now = Date.now();
        if (this._joinProbeAt && now - this._joinProbeAt < 4000) {
            return;
        }
        this._joinProbeAt = now;
        this._joinProbeBusy = true;
        this.probeJoinCancel().finally(() => {
            this._joinProbeBusy = false;
        });
    }

    async probeJoinCancel() {
        const token = this.state.join.token;
        if (!token || this.state.screen !== "join") {
            return;
        }
        try {
            await this.rpc(`${API}/match/verify`, { match_token: token });
        } catch (e) {
            if (this.state.screen !== "join" || this.state.join.token !== token) {
                return;
            }
            await this.leaveJoinIfMatchClosed(e && e.message);
        }
    }

    async leaveJoinIfMatchClosed(message) {
        if (isWaitingTimeoutReason(message)) {
            await this.leaveWaitingAfterTimeout("Waiting time expired. Match cancelled.");
            return true;
        }
        if (joinFailureLeavesScreen(message)) {
            await this.leaveAfterHostCancel();
            return true;
        }
        return false;
    }

    async applyJoinWatch(match, matchId) {
        if (
            this.state.screen !== "join" ||
            Number(this.state.join.match_id) !== Number(matchId)
        ) {
            return;
        }
        if (!match) {
            return;
        }
        if (match.state === "active") {
            await this.enterGame(match.id || matchId);
            return;
        }
        if (match.state === "cancelled") {
            if (isWaitingTimeoutReason(match.cancel_reason)) {
                await this.leaveWaitingAfterTimeout(
                    "Waiting time expired. Match cancelled."
                );
                return;
            }
            await this.leaveAfterHostCancel();
        }
    }

    async watchMatch(matchId, since, onPayload, timeout) {
        try {
            const params = {
                match_id: matchId,
                since: since || null,
                timeout: timeout || 20,
            };
            // since_rev asks for a line delta. Omit it on the waiting screen.
            if (this.state.match && this.state.match.id === matchId) {
                params.since_rev = this.state.match.lines_rev || 0;
            }
            const data = await this.rpc(`${API}/match/watch`, params);
            if (data.write_date) {
                if (this.state.screen === "waiting" && this.state.waiting.match_id === matchId) {
                    this.state.waiting.write_date = data.write_date;
                }
                if (this.state.match && this.state.match.id === matchId) {
                    this.state.match.write_date = data.write_date;
                }
            }
            if (
                data.lines_rev != null &&
                this.state.match &&
                this.state.match.id === matchId
            ) {
                this.state.match.lines_rev = nextLinesRev(
                    this.state.match.lines_rev,
                    data.lines_rev
                );
            }
            // A finish must go home even if the body also carries a line delta.
            if (watchMatchGoesHome(data)) {
                await onPayload(data.match);
                return;
            }
            if (data.lines_only && data.delta) {
                this.state.unitState = applyWoundDelta(this.state.unitState, data.delta);
                return;
            }
            if (data.match) {
                if (data.match.lines_rev != null && this.state.match && this.state.match.id === matchId) {
                    this.state.match.lines_rev = nextLinesRev(
                        this.state.match.lines_rev,
                        data.match.lines_rev
                    );
                }
                await onPayload(data.match);
            }
        } catch (_e) {
            await new Promise((r) => setTimeout(r, 2000));
        }
    }

    async applyWaitingWatch(match) {
        if (match.expires_at) {
            this.state.waiting.expires_at = match.expires_at;
        }
        if (match.state === "active") {
            await this.enterGame(match.id);
        } else if (match.state === "cancelled") {
            const reason = match.cancel_reason || "";
            if (isWaitingTimeoutReason(reason)) {
                await this.leaveWaitingAfterTimeout("Waiting time expired. Match cancelled.");
            } else {
                await this.leaveAfterHostCancel();
            }
        } else if (match.state === "waiting" && this.state.waiting.remaining_ms <= 0) {
            await this.leaveWaitingAfterTimeout("Waiting time expired. Match cancelled.");
        }
    }

    async applyActiveWatch(match) {
        if (this._finishingMatch) {
            return;
        }
        if (match.unit_state) {
            this.state.unitState = {
                host: match.unit_state.host || [],
                guest: match.unit_state.guest || [],
                undo: match.unit_state.undo || {},
            };
        }
        if (match.state === "finished") {
            const isDraw = match.result === "draw" || match.you_result === "draw";
            await this.goHomeAfterMatchEnd({
                winner_id: match.winner_id,
                winner_nickname: match.winner_nickname || "",
                host: match.host,
                guest: match.guest,
                is_host: !!match.is_host,
                you_surrendered: false,
                is_draw: isDraw,
                message: isDraw ? "Ничья." : "",
            });
        } else if (match.state === "cancelled") {
            this.state.activeMatch = null;
            this.state.match = null;
            this.setError(match.cancel_reason || "Match cancelled.");
            this.setScreen("home");
        }
    }

    dismissMatchResultBanner() {
        this.state.result = {
            ...this.state.result,
            show_on_home: false,
            is_draw: false,
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
        is_draw = false,
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
            const resolvedDraw = !!is_draw;
            if (resolvedDraw) {
                resolvedYouWon = false;
            }
            const resolvedMessage =
                message ||
                (resolvedDraw
                    ? "Ничья."
                    : you_surrendered
                      ? "Поражение. Вы сдались."
                      : resolvedYouWon
                        ? "Победа! Противник сдался."
                        : "Матч завершён.");
            this.state.result = {
                winner_nickname: resolvedDraw ? "" : resolvedWinnerNick,
                you_won: resolvedYouWon,
                you_surrendered: resolvedDraw ? false : !!you_surrendered,
                is_draw: resolvedDraw,
                message: resolvedMessage,
                show_on_home: true,
            };
            this.state.showSurrenderModal = false;
            this.state.showDrawModal = false;
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
            await this.leaveAfterHostCancel();
            return;
        }
        try {
            await this.rpc(`${API}/match/cancel`, {
                match_id: this.state.waiting.match_id,
            });
            await this.leaveAfterHostCancel();
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
            this.state.join.match_id = verified.match_id || null;
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
            if (await this.leaveJoinIfMatchClosed(e.message)) {
                return;
            }
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
            this.state.join.match_id = accepted.match_id || this.state.join.match_id;
            this.state.join.rosters = accepted.rosters || [];
            this.state.join.roster_id = this.state.join.rosters[0]?.id || null;
            this.state.busy = false;
        } catch (e) {
            if (await this.leaveJoinIfMatchClosed(e.message)) {
                return;
            }
            this.setError(e.message);
        }
    }

    declineInvite() {
        clearRememberedJoinToken();
        this.state.join = emptyJoinState();
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
            if (await this.leaveJoinIfMatchClosed(e.message)) {
                return;
            }
            this.setError(e.message);
        }
    }

    async enterGame(matchId) {
        if (this._enteringMatchId === matchId) {
            return;
        }
        if (
            this.state.screen === "game" &&
            this.state.match &&
            this.state.match.id === matchId
        ) {
            return;
        }
        this._enteringMatchId = matchId;
        try {
            await this._loadGame(matchId);
        } finally {
            if (this._enteringMatchId === matchId) {
                this._enteringMatchId = null;
            }
        }
    }

    async _loadGame(matchId) {
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
        return snapshotUnit(unit);
    }

    _cloneUnitState() {
        return {
            host: [...(this.state.unitState.host || [])],
            guest: [...(this.state.unitState.guest || [])],
            undo: { ...(this.state.unitState.undo || {}) },
        };
    }

    _pushUndo(unit) {
        const undo = pushUndoEntry(
            this.state.unitState.undo || {},
            unit.unit_id,
            snapshotUnit(unit),
            Wh40kCompanionApp.UNDO_STACK_LIMIT
        );
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
        this.state.datasheet = datasheetFromMatchUnit(unit, this.findUnitDetail(unit));
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

    async persistModelOp(unit, modelKey, op, delta) {
        const payload = buildModelDelta(unit, modelKey, op, delta);
        const data = await this.rpc(`${API}/match/unit_state`, {
            match_id: this.state.match.id,
            unit_delta: payload,
        });
        if (data && data.delta) {
            this.state.unitState = applyWoundDelta(this.state.unitState, data.delta);
        }
        if (data && data.lines_rev != null && this.state.match) {
            this.state.match.lines_rev = nextLinesRev(
                this.state.match.lines_rev,
                data.lines_rev
            );
        }
    }

    async _changeModel(unit, row, op, delta) {
        if (!unit || !row || !this.state.match) {
            return;
        }
        if (op !== "undo" && (row.destroyed || unit.destroyed)) {
            return;
        }
        const changed = applyModelOp(unit, row.key, op, delta);
        if (!changed) {
            return;
        }
        const nextRow = (unit.model_rows || []).find((item) => item.key === row.key);
        if ((nextRow && nextRow.destroyed) || unit.destroyed) {
            this.vibrate();
        }
        this.state.unitState = this._cloneUnitState();
        try {
            await this.persistModelOp(unit, row.key, op, delta);
        } catch (e) {
            this.setError(e.message);
        }
    }

    adjustModel(unit, row, field, delta) {
        return this._changeModel(unit, row, field, delta);
    }

    destroyModel(unit, row) {
        return this._changeModel(unit, row, "destroy", 0);
    }

    undoModel(unit, row) {
        if (!this.canUndoModel(row)) {
            return;
        }
        return this._changeModel(unit, row, "undo", 0);
    }

    async persistWoundDelta(unit) {
        const delta = buildWoundDelta(unit, this.state.unitState.undo);
        const data = await this.rpc(`${API}/match/unit_state`, {
            match_id: this.state.match.id,
            unit_delta: delta,
        });
        if (data && data.delta) {
            this.state.unitState = applyWoundDelta(this.state.unitState, data.delta);
        }
        if (data && data.lines_rev != null && this.state.match) {
            this.state.match.lines_rev = nextLinesRev(
                this.state.match.lines_rev,
                data.lines_rev
            );
        }
    }

    async adjustUnit(unit, field, delta) {
        if (!this.isOwnUnit(unit) || unit.destroyed) {
            return;
        }
        this._pushUndo(unit);
        if (applyUnitFieldDelta(unit, field, delta)) {
            this.vibrate();
        }
        this.state.unitState = this._cloneUnitState();
        try {
            await this.persistWoundDelta(unit);
        } catch (e) {
            this.setError(e.message);
        }
    }

    async destroyUnit(unit) {
        if (!this.isOwnUnit(unit) || unit.destroyed) {
            return;
        }
        this._pushUndo(unit);
        destroyUnitInPlace(unit);
        this.vibrate();
        this.state.unitState = this._cloneUnitState();
        try {
            await this.persistWoundDelta(unit);
        } catch (e) {
            this.setError(e.message);
        }
    }

    async undoUnit(unit) {
        if (!this.canUndo(unit)) {
            return;
        }
        const { undo, snapshot: prev } = popUndoEntry(
            this.state.unitState.undo || {},
            unit.unit_id
        );
        if (!prev) {
            return;
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
            await this.persistWoundDelta(unit);
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

    openDrawModal() {
        this.state.showDrawModal = true;
    }

    closeDrawModal() {
        this.state.showDrawModal = false;
    }

    async confirmDraw() {
        try {
            this.state.busy = true;
            this.state.showDrawModal = false;
            await this.rpc(`${API}/match/draw`, {
                match_id: this.state.match.id,
            });
            await this.goHomeAfterMatchEnd({
                is_draw: true,
                you_won: false,
                you_surrendered: false,
                winner_id: null,
                winner_nickname: "",
                message: "Ничья.",
            });
        } catch (e) {
            this.setError(e.message);
        }
    }
}

