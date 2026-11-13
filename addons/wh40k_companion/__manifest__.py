{
    "name": "WH40k Battle Companion",
    "version": "20.0.1.18.0",
    "category": "Games",
    "summary": "Warhammer 40,000 roster import, matchmaking via QR, and in-game tracking",
    "description": """
WH40k Battle Companion
======================
Import NewRecruit/Battlescribe JSON rosters, manage player profiles,
create matches with QR join codes, and track wounds during games.

Battle App is a standalone PWA at /wh40k/app with JSON API under /wh40k/api/.

20.0.1.18.0 highlights:
- Roster file input keeps the Owl 3 signal ref (set/add/delete) on child screens.
- Prior 20.0.1.17.0: PWA CSS maps, Owl 3 useProps/proxy.
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
