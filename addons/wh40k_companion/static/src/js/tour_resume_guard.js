/** @odoo-module **/

/**
 * Odoo 20 TourPlugin.resumeTour lazy-loads web_tour.interactive, then
 * destructures TourInteractive from the module loader. On phones / flaky LAN
 * asset loads that module can stay undefined → UncaughtPromiseError and a
 * blocking "Oops!" over Battle App join (#wh40k_join=...).
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

function getLoadedModule(path) {
    try {
        return odoo.loader.modules.get(path);
    } catch (_e) {
        return undefined;
    }
}

patch(TourPlugin.prototype, {
    async resumeTour() {
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
        // QR deep-link / Battle App: never block join on a stale tour resume.
        const hash = window.location.hash || "";
        const path = window.location.pathname || "";
        if (hash.includes("wh40k_join") || path.includes("/wh40k/")) {
            clearTourQuietly();
        }
        return super.bootstrap(...arguments);
    },
});
