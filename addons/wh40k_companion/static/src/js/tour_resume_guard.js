/** @odoo-module **/

/**
 * Odoo 20 TourPlugin.resumeTour lazy-loads web_tour.interactive, then
 * destructures TourInteractive from the module loader. On phones / flaky LAN
 * asset loads that module can stay undefined -> UncaughtPromiseError and a
 * blocking "Oops!" over Battle App join (#wh40k_join=...).
 *
 * Separately, web_tour/tour_helpers/tour_helpers_clipboard reads
 * navigator.clipboard.writeText at module evaluate time. On insecure HTTP LAN
 * (http://192.168.x.x) clipboard is missing -> TypeError while loading that
 * module. clipboard_polyfill.js runs first; ensureClipboard() below is a
 * second line of defense right before loadBundle("web_tour.interactive").
 *
 * Guard resumeTour: if the interactive (or automatic) module is missing after
 * loadBundle, clear tour localStorage and continue. Battle App does not need
 * onboarding tours for QR join / match play.
 */

import { patch } from "@web/core/utils/patch";
import { loadBundle } from "@web/core/assets";
import { TourPlugin } from "@web_tour/tour_plugin";
import { tourState } from "@web_tour/tour_state";

function clearTourQuietly() {
    try {
        tourState.clear();
    } catch (_e) {
        // ignore
    }
}

function ensureClipboard() {
    try {
        if (typeof navigator === "undefined") {
            return;
        }
        const stubWrite = () => Promise.resolve();
        const stubRead = () => Promise.resolve("");
        if (!navigator.clipboard) {
            const clipboard = { writeText: stubWrite, readText: stubRead };
            try {
                Object.defineProperty(navigator, "clipboard", {
                    configurable: true,
                    enumerable: true,
                    writable: true,
                    value: clipboard,
                });
            } catch (_e) {
                navigator.clipboard = clipboard;
            }
            return;
        }
        if (typeof navigator.clipboard.writeText !== "function") {
            navigator.clipboard.writeText = stubWrite;
        }
        if (typeof navigator.clipboard.readText !== "function") {
            navigator.clipboard.readText = stubRead;
        }
    } catch (_e) {
        // ignore
    }
}

function isBattleAppContext() {
    const hash = window.location.hash || "";
    const path = window.location.pathname || "";
    const search = window.location.search || "";
    return (
        hash.includes("wh40k_join") ||
        search.includes("wh40k_join") ||
        path.includes("/wh40k/") ||
        // client action hash often looks like #action=...&... without join token
        // once sessionStorage already holds the token after /wh40k/join redirect
        (() => {
            try {
                return !!sessionStorage.getItem("wh40k_join");
            } catch (_e) {
                return false;
            }
        })()
    );
}

function getLoadedModule(path) {
    try {
        return odoo.loader.modules.get(path);
    } catch (_e) {
        return undefined;
    }
}

// Ensure clipboard exists as soon as this module evaluates (backend boot),
// before any later resumeTour -> loadBundle("web_tour.interactive").
ensureClipboard();

patch(TourPlugin.prototype, {
    async resumeTour() {
        // Battle App / QR join: never pull interactive tour helpers (clipboard).
        if (isBattleAppContext()) {
            clearTourQuietly();
            return;
        }

        ensureClipboard();

        const tourName = tourState.getCurrentTour();
        const tourConfig = tourState.getCurrentConfig() || {};
        let tour;
        try {
            tour = await this.getTour(tourName, tourConfig);
        } catch (error) {
            console.warn("WH40k: tour lookup failed; clearing tour state", error);
            clearTourQuietly();
            return;
        }
        if (!tour || !tour.steps || !tour.steps.length) {
            clearTourQuietly();
            return;
        }

        try {
            tour.steps.forEach((step) => this.validateStep(step));
        } catch (error) {
            console.warn("WH40k: tour step validation failed; clearing", error);
            clearTourQuietly();
            return;
        }

        if (tourConfig.mode === "auto") {
            try {
                ensureClipboard();
                if (!getLoadedModule("@web_tour/tour_automatic/tour_automatic")) {
                    await loadBundle("web_tour.automatic", { css: false });
                }
                const mod = getLoadedModule("@web_tour/tour_automatic/tour_automatic");
                if (!mod || !mod.TourAutomatic) {
                    console.warn("WH40k: TourAutomatic unavailable; skipping resume");
                    clearTourQuietly();
                    return;
                }
                new mod.TourAutomatic(tour).start();
            } catch (error) {
                console.warn("WH40k: automatic tour resume failed; clearing", error);
                clearTourQuietly();
            }
            return;
        }

        try {
            ensureClipboard();
            await loadBundle("web_tour.interactive");
            const mod = getLoadedModule("@web_tour/tour_interactive/tour_interactive");
            if (!mod || !mod.TourInteractive) {
                console.warn("WH40k: TourInteractive unavailable; skipping resume");
                clearTourQuietly();
                return;
            }
            new mod.TourInteractive(tour, {
                orm: this.orm,
                effect: this.effect,
                overlay: this.overlay,
                onChainNextTour: (nextTour) =>
                    this.startTour(nextTour.name, {
                        mode: "manual",
                        redirect: false,
                        rainbowManMessage: nextTour.rainbowManMessage,
                    }),
            }).start(this.env);
        } catch (error) {
            console.warn("WH40k: interactive tour resume failed; clearing", error);
            clearTourQuietly();
        }
    },

    async bootstrap() {
        ensureClipboard();
        // QR deep-link / Battle App: never block join on a stale tour resume.
        if (isBattleAppContext()) {
            clearTourQuietly();
        }
        return super.bootstrap(...arguments);
    },
});
