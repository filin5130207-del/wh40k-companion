{
    "name": "WH40k Battle Companion",
    "version": "20.0.1.27.0",
    "category": "Games",
    "summary": "Warhammer 40,000 roster import, matchmaking via QR, and in-game tracking",
    "description": """
WH40k Battle Companion
======================
Import NewRecruit/Battlescribe JSON rosters, manage player profiles,
create matches with QR join codes, and track wounds during games.

Battle App is a standalone PWA at /wh40k/app with JSON API under /wh40k/api/.

20.0.1.27.0 highlights:
- Roster import stores the selected detachment name. Stratagem text stays in a static catalogue keyed by faction and detachment, and is not copied onto the roster.
- «Стратагемы» sits next to «Правила» on the player's roster and on the opponent's roster. The list shows name and CP. Tapping a row opens its text; tapping it again closes it. There is no used toggle and no CP spend.
- A detachment with no catalogue entry still imports. The list is empty and says "no deck for this detachment".
20.0.1.26.0 highlights:
- The Характеристики button is gone. Tapping a squad header opens every model's characteristics. Tapping one miniature inside Модели opens only that model's characteristics. A second tap closes them.
- Модели, the per-model +M -M +W -W / destroy / undo controls, and the squad M/W rollup stay. Stat lines stay hidden until a squad or a model is opened.
20.0.1.25.0 highlights:
- Win rate is wins divided by decisive games (wins + losses). Draws stay on the profile and do not move the rate. No decisive games shows 0%.
- Characteristic columns stay closed until the squad is opened. Each squad has a Models button that lists one row per miniature already on the roster.
- Either player can change a model on either roster: +M, -M, +W, -W, destroy, undo. Squad M and W are the sum of those rows.
20.0.1.24.0 highlights:
- Own army cards in an active match carry the same characteristic columns as the opponent (M, T, Sv, W, LD, OC, InSv).
- When the host cancels a QR / join wait, both players leave that screen and the status banner is cleared.
- Either player can record a draw. The match stores result ``draw`` and both players' draw counters move.
20.0.1.23.0 highlights:
- A guest join pushes wh40k.match/updated on wh40k.match.<host partner id> immediately. The host leaves the waiting screen from that socket and does not wait for the /match/watch long-poll. The long-poll still returns as soon as the join commits when the socket is down.
20.0.1.22.0 highlights:
- The Battle App subscribes to the Odoo bus channel wh40k.match.<partner_id> on /websocket. Surrender, wounds, and match finish update the other device from that socket. /wh40k/api/match/watch stays as the fallback when the socket fails, and a finish still wakes an in-flight watch.
- Join and QR links use the system parameter wh40k.public_base_url. web.base.url is used only when it is not a loopback or private address. A private link is labeled as LAN-only.
- Prior 20.0.1.21.0: a finished or cancelled match wakes an in-flight watch immediately. The client goes home from that payload.
- Prior 20.0.1.20.0: wound updates and line-only watch polls return a delta, not the full match.
- Roster unit/weapon/ability counts are stored. Import stays in the request and does not reload matches.
- Prior 20.0.1.19.0: join and app navigations are no longer served from the cached shell.
""",
    "author": "WH40k Companion",
    "license": "LGPL-3",
    "depends": ["base", "web", "web_tour", "mail", "auth_signup", "bus"],
    "data": [
        "security/wh40k_security.xml",
        "security/ir.access.csv",
        "data/mission_data.xml",
        "data/ir_cron_data.xml",
        "views/res_partner_views.xml",
        "views/roster_views.xml",
        "views/mission_views.xml",
        "views/match_views.xml",
        "views/companion_action.xml",
        "views/menus.xml",
        "views/signup_templates.xml",
        "views/pwa_templates.xml",
    ],
    "assets": {
        # Backend: only light polyfills; Battle App no longer mounts here.
        "web.assets_backend": [
            "wh40k_companion/static/src/js/clipboard_polyfill.js",
            "wh40k_companion/static/src/js/tour_resume_guard.js",
        ],
        # Public signup/landing/join pages.
        "wh40k_companion.assets_public": [
            "wh40k_companion/static/src/css/companion.css",
        ],
        # Standalone PWA. Mirror web.assets_backend / point_of_sale.base_app:
        # Bootstrap 5 defines $theme-colors-rgb in _maps.scss. Without it,
        # utilities.scss fails and Odoo serves the red "css error" footer.
        "wh40k_companion.assets_pwa": [
            ("include", "web._assets_helpers"),
            ("include", "web._assets_backend_helpers"),
            "web/static/src/scss/pre_variables.scss",
            "web/static/lib/bootstrap/scss/_variables.scss",
            "web/static/lib/bootstrap/scss/_variables-dark.scss",
            "web/static/lib/bootstrap/scss/_maps.scss",
            ("include", "web._assets_bootstrap_backend"),
            ("include", "web._assets_core"),
            ("remove", "web/static/src/**/*.dark.scss"),
            "wh40k_companion/static/src/pwa/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
