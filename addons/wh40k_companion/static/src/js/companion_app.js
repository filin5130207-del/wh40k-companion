/** @odoo-module **/

import { Component, proxy, signal, onWillStart, onMounted, onWillUnmount, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { standardActionServiceProps } from "@web/webclient/actions/action_plugin";

function extractJoinToken() {
    const hash = window.location.hash || "";
    const query = window.location.search || "";
    const fromHash = hash.match(/wh40k_join=([^&]+)/);
    if (fromHash) {
        return decodeURIComponent(fromHash[1]);
    }
    const params = new URLSearchParams(query);
    return params.get("wh40k_join") || "";
}

export class Wh40kCompanionApp extends Component {
    static template = "wh40k_companion.CompanionApp";
    props = useProps({
        ...standardActionServiceProps,
    });
    rosterFile = signal.ref();

    setup() {
        this.state = proxy({
            screen: "dashboard",
            busy: false,
            error: "",
            player: {
                nickname: "",
                wins: 0,
                losses: 0,
                total_match: 0,
                win_rate: 0,
            },
            rosters: [],
            missions: [],
            create: {
                points: "2000",
                mission_id: null,
                roster_id: null,
            },
            waiting: {
                match_id: null,
                join_url: "",
                match_token: "",
            },
            join: {
                token: extractJoinToken(),
                verified: false,
                host_nickname: "",
                points: "",
                mission_name: "",
                rosters: [],
                roster_id: null,
            },
            match: null,
            unitState: { host: [], guest: [] },
            rules: [],
            datasheet: null,
            result: {
                winner_nickname: "",
            },
            pendingRosterJson: null,
        });
        this._poll = null;

        onWillStart(async () => {
            await this.loadDashboard();
            await this.loadMissions();
            if (this.state.join.token) {
                this.state.screen = "join";
            }
        });

        onMounted(() => {
            this._poll = setInterval(() => this.pollWaiting(), 5000);
        });

        onWillUnmount(() => {
            if (this._poll) {
                clearInterval(this._poll);
            }
        });
    }

    get eligibleHostRosters() {
        const limit = parseInt(this.state.create.points, 10);
        return (this.state.rosters || []).filter((r) => r.points_used <= limit);
    }

    get qrImageUrl() {
        const url = this.state.waiting.join_url || "";
        return `https://api.qrserver.com/v1/create-qr-code/?size=260x260&data=${encodeURIComponent(url)}`;
    }

    get ownUnits() {
        if (!this.state.match) {
            return [];
        }
        const side = this.state.match.is_host ? "host" : "guest";
        return (this.state.unitState[side] || []);
    }

    get oppUnits() {
        if (!this.state.match) {
            return [];
        }
        const side = this.state.match.is_host ? "guest" : "host";
        return (this.state.unitState[side] || []);
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

    setScreen(screen) {
        this.state.error = "";
        this.state.screen = screen;
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
        const data = await this.rpc("/wh40k/player/dashboard");
        this.state.player = data.player;
        this.state.rosters = data.rosters || [];
    }

    async loadMissions() {
        const data = await this.rpc("/wh40k/missions");
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
            await this.rpc("/wh40k/player/nickname", { nickname: this.state.player.nickname });
            await this.loadDashboard();
            this.state.busy = false;
        } catch (e) {
            this.setError(e.message);
        }
    }

    onRosterFile(ev) {
        const file = ev.target.files && ev.target.files[0];
        if (!file) {
            this.state.pendingRosterJson = null;
            return;
        }
        const reader = new FileReader();
        reader.onload = () => {
            try {
                this.state.pendingRosterJson = JSON.parse(reader.result);
            } catch (e) {
                this.setError("Invalid JSON file.");
                this.state.pendingRosterJson = null;
            }
        };
        reader.readAsText(file);
    }

    async importRoster() {
        if (!this.state.pendingRosterJson) {
            this.setError("Choose a roster JSON file first.");
            return;
        }
        try {
            this.state.busy = true;
            await this.rpc("/wh40k/roster/import", {
                roster_json: this.state.pendingRosterJson,
            });
            await this.loadDashboard();
            this.state.busy = false;
            this.state.pendingRosterJson = null;
            const fileInput = this.rosterFile();
            if (fileInput) {
                fileInput.value = "";
            }
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
            const created = await this.rpc("/wh40k/match/create", {
                roster_id: this.state.create.roster_id,
                mission_id: this.state.create.mission_id,
                points: this.state.create.points,
            });
            const published = await this.rpc("/wh40k/match/publish", {
                match_id: created.match_id,
            });
            this.state.waiting = {
                match_id: published.match_id,
                join_url: published.join_url,
                match_token: published.match_token,
            };
            this.state.busy = false;
            this.setScreen("waiting");
        } catch (e) {
            this.setError(e.message);
        }
    }

    async pollWaiting() {
        if (this.state.screen !== "waiting" || !this.state.waiting.match_id) {
            return;
        }
        try {
            const data = await this.rpc("/wh40k/match/state", {
                match_id: this.state.waiting.match_id,
            });
            if (data.match.state === "active") {
                await this.enterGame(data.match.id);
            } else if (data.match.state === "cancelled") {
                this.setError("Match was cancelled (stale waiting timeout or host cancel).");
                this.setScreen("dashboard");
            }
        } catch (e) {
            // keep polling; surface soft errors only
        }
    }

    async refreshMatch() {
        await this.pollWaiting();
    }

    async cancelWaiting() {
        if (!this.state.waiting.match_id) {
            this.setScreen("dashboard");
            return;
        }
        try {
            await this.rpc("/wh40k/match/cancel", { match_id: this.state.waiting.match_id });
            this.setScreen("dashboard");
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
    }

    async verifyToken() {
        if (!this.state.join.token) {
            this.setError("Enter a match token.");
            return;
        }
        try {
            this.state.busy = true;
            const verified = await this.rpc("/wh40k/match/verify", {
                match_token: this.state.join.token,
            });
            const eligible = await this.rpc("/wh40k/match/eligible_rosters", {
                match_token: this.state.join.token,
            });
            this.state.join.verified = true;
            this.state.join.host_nickname = verified.host?.nickname || "Host";
            this.state.join.points = verified.points;
            this.state.join.mission_name = verified.mission?.name || "";
            this.state.join.rosters = eligible.rosters || [];
            this.state.join.roster_id = this.state.join.rosters[0]?.id || null;
            this.state.busy = false;
        } catch (e) {
            this.setError(e.message);
        }
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
            const joined = await this.rpc("/wh40k/match/join", {
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
        const data = await this.rpc("/wh40k/match/state", { match_id: matchId });
        this.state.match = data.match;
        this.state.unitState = data.match.unit_state || { host: [], guest: [] };
        const rosterId = data.match.is_host
            ? data.match.host_roster_id
            : data.match.guest_roster_id;
        if (rosterId) {
            const detail = await this.rpc(`/wh40k/roster/${rosterId}/detail`);
            this.state.rules = detail.roster?.rules || [];
            this._rosterCache = this._rosterCache || {};
            this._rosterCache[rosterId] = detail.roster;
            // Also cache opponent roster for datasheets
            const otherId = data.match.is_host
                ? data.match.guest_roster_id
                : data.match.host_roster_id;
            if (otherId) {
                const other = await this.rpc(`/wh40k/roster/${otherId}/detail`);
                this._rosterCache[otherId] = other.roster;
            }
        }
        this.setScreen("game");
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
        await this.rpc("/wh40k/match/unit_state", {
            match_id: this.state.match.id,
            unit_state: {
                host: this.state.unitState.host || [],
                guest: this.state.unitState.guest || [],
            },
        });
    }

    async adjustUnit(unit, field, delta) {
        if (unit.destroyed) {
            return;
        }
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
        // trigger reactivity
        this.state.unitState = {
            host: [...(this.state.unitState.host || [])],
            guest: [...(this.state.unitState.guest || [])],
        };
        try {
            await this.persistUnitState();
        } catch (e) {
            this.setError(e.message);
        }
    }

    async destroyUnit(unit) {
        unit.models_remaining = 0;
        unit.wounds_remaining = 0;
        unit.destroyed = true;
        this.vibrate();
        this.state.unitState = {
            host: [...(this.state.unitState.host || [])],
            guest: [...(this.state.unitState.guest || [])],
        };
        try {
            await this.persistUnitState();
        } catch (e) {
            this.setError(e.message);
        }
    }

    async confirmSurrender() {
        if (!window.confirm("Surrender this match? This cannot be undone.")) {
            return;
        }
        try {
            this.state.busy = true;
            const result = await this.rpc("/wh40k/match/surrender", {
                match_id: this.state.match.id,
            });
            this.state.result.winner_nickname = result.winner_nickname;
            this.state.busy = false;
            await this.loadDashboard();
            this.setScreen("result");
        } catch (e) {
            this.setError(e.message);
        }
    }
}

registry.category("actions").add("wh40k_companion_app", Wh40kCompanionApp);
