{
    "name": "WH40k Battle Companion",
    "version": "20.0.1.14.0",
    "category": "Games",
    "summary": "Warhammer 40,000 roster import, matchmaking via QR, and in-game tracking",
    "description": """
WH40k Battle Companion
======================
Import NewRecruit/Battlescribe JSON rosters, manage player profiles,
create matches with QR join codes, and track wounds during games.

Battle App is a standalone PWA at /wh40k/app with JSON API under /wh40k/api/.
""",
    "author": "WH40k Companion",
    "license": "LGPL-3",
    "depends": ["base", "web", "web_tour", "mail", "auth_signup"],
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
        # Standalone PWA (Odoo howto: standalone Owl application).
        "wh40k_companion.assets_pwa": [
            ("include", "web._assets_helpers"),
            "web/static/src/scss/pre_variables.scss",
            "web/static/lib/bootstrap/scss/_variables.scss",
            ("include", "web._assets_bootstrap"),
            ("include", "web._assets_core"),
            "wh40k_companion/static/src/pwa/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
