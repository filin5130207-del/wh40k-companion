{
    "name": "WH40k Battle Companion",
    "version": "20.0.1.13.0",
    "category": "Games",
    "summary": "Warhammer 40,000 roster import, matchmaking via QR, and in-game tracking",
    "description": """
WH40k Battle Companion
======================
Import NewRecruit/Battlescribe JSON rosters, manage player profiles,
create matches with QR join codes, and track wounds during games.
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
    ],
    "assets": {
        "web.assets_backend": [
            "wh40k_companion/static/src/css/companion.css",
            # Early module: polyfill navigator.clipboard
            # before web_tour.interactive evaluates tour_helpers_clipboard.
            "wh40k_companion/static/src/js/clipboard_polyfill.js",
            # Load before companion_app so TourPlugin.resumeTour is patched
            # before Battle App / QR join bootstraps.
            "wh40k_companion/static/src/js/tour_resume_guard.js",
            "wh40k_companion/static/src/js/companion_app.js",
            "wh40k_companion/static/src/xml/companion_templates.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
