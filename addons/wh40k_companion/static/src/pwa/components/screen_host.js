/** @odoo-module **/

import { Component } from "@odoo/owl";

/**
 * Thin screen host: templates keep calling methods on `this.app`.
 * Props validation keeps the root→screen contract explicit.
 */
function makeScreen(templateName) {
    return class extends Component {
        static template = templateName;
        static props = {
            app: { type: Object },
        };

        setup() {
            this.app = this.props.app;
        }

        get state() {
            return this.props.app.state;
        }
    };
}

// Forward common template handlers via prototype getters on each call site
// by exposing the app controller methods through `this`.
function withAppMethods(Base) {
    return class extends Base {
        setup() {
            super.setup();
            const app = this.props.app;
            const proto = Object.getPrototypeOf(app);
            const names = new Set([
                ...Object.getOwnPropertyNames(proto),
                ...Object.keys(app),
            ]);
            for (const name of names) {
                if (name === "constructor" || name.startsWith("_") || name === "props") {
                    continue;
                }
                const value = app[name];
                if (typeof value === "function") {
                    this[name] = value.bind(app);
                }
            }
            // Getters used by templates (ownUnits, qrImageUrl, …)
            for (const name of names) {
                const desc = Object.getOwnPropertyDescriptor(proto, name);
                if (desc && desc.get && !Object.prototype.hasOwnProperty.call(this, name)) {
                    Object.defineProperty(this, name, {
                        get: () => app[name],
                        configurable: true,
                    });
                }
            }
        }
    };
}

export const NicknameGate = withAppMethods(makeScreen("wh40k_companion.NicknameGate"));
export const HomeScreen = withAppMethods(makeScreen("wh40k_companion.HomeScreen"));
export const RostersScreen = withAppMethods(makeScreen("wh40k_companion.RostersScreen"));
export const RosterDetailScreen = withAppMethods(
    makeScreen("wh40k_companion.RosterDetailScreen")
);
export const ImportPreview = withAppMethods(makeScreen("wh40k_companion.ImportPreview"));
export const CreateMatch = withAppMethods(makeScreen("wh40k_companion.CreateMatch"));
export const WaitingScreen = withAppMethods(makeScreen("wh40k_companion.WaitingScreen"));
export const JoinScreen = withAppMethods(makeScreen("wh40k_companion.JoinScreen"));
export const GameScreen = withAppMethods(makeScreen("wh40k_companion.GameScreen"));
export const MatchResultScreen = withAppMethods(
    makeScreen("wh40k_companion.MatchResultScreen")
);
