{
    "name": "WH40k Battle Companion",
    "version": "20.0.1.0.0",
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
    "depends": ["base", "web", "mail"],
    "data": [
        "security/ir.access.csv",
        "data/mission_data.xml",
        "data/ir_cron_data.xml",
        "views/res_partner_views.xml",
        "views/roster_views.xml",
        "views/mission_views.xml",
        "views/match_views.xml",
        "views/companion_action.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "wh40k_companion/static/src/css/companion.css",
            "wh40k_companion/static/src/js/companion_app.js",
            "wh40k_companion/static/src/xml/companion_templates.xml",
        ],
    },
    "application": True,
    "installable": True,
}
