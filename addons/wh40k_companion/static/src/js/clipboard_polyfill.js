/** @odoo-module **/

/**
 * Odoo 20 web_tour tour_helpers_clipboard does at module load:
 *   const originalClipboardWriteText = window.navigator.clipboard.writeText;
 * On insecure HTTP (phone LAN http://192.168.x.x) navigator.clipboard is
 * undefined -> TypeError and a blocking Oops! over Battle App / QR join.
 *
 * Runs early in web.assets_backend (listed before tour_resume_guard) so
 * navigator.clipboard exists before any lazy web_tour.interactive bundle
 * evaluates tour_helpers_clipboard.
 */
(function wh40kClipboardPolyfill() {
    try {
        if (typeof navigator === "undefined") {
            return;
        }
        const stubWrite = function () {
            return Promise.resolve();
        };
        const stubRead = function () {
            return Promise.resolve("");
        };
        if (!navigator.clipboard) {
            const clipboard = {
                writeText: stubWrite,
                readText: stubRead,
            };
            try {
                Object.defineProperty(navigator, "clipboard", {
                    configurable: true,
                    enumerable: true,
                    writable: true,
                    value: clipboard,
                });
            } catch (_e) {
                try {
                    navigator.clipboard = clipboard;
                } catch (_e2) {
                    // ignore
                }
            }
            return;
        }
        if (typeof navigator.clipboard.writeText !== "function") {
            try {
                navigator.clipboard.writeText = stubWrite;
            } catch (_e) {
                // ignore
            }
        }
        if (typeof navigator.clipboard.readText !== "function") {
            try {
                navigator.clipboard.readText = stubRead;
            } catch (_e) {
                // ignore
            }
        }
    } catch (_e) {
        // never block app boot
    }
})();
