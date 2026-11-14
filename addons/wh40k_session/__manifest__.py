{
    "name": "WH40k Session",
    "version": "20.0.1.0.0",
    "category": "Games",
    "summary": "Signup, login, Player/Manager groups, and the Battle App PWA",
    "description": """
Session service for WH40k Battle Companion.

This database owns res.users, the Player and Manager groups, nicknames, and
win/loss counters. It issues the bearer token the roster and match services
check. It does not store rosters or matches.

The PWA at /wh40k/app is the client of all three HTTP APIs.
""",
    "author": "WH40k Companion",
    "license": "LGPL-3",
    "depends": ["base", "web", "auth_signup"],
    "data": [
        "security/wh40k_security.xml",
        "security/ir.access.csv",
        "views/signup_templates.xml",
        "views/pwa_templates.xml",
        "views/menus.xml",
    ],
    "assets": {
        "wh40k_session.assets_public": [
            "wh40k_session/static/src/css/companion.css",
        ],
        "wh40k_session.assets_pwa": [
            ("include", "web._assets_helpers"),
            ("include", "web._assets_backend_helpers"),
            "web/static/src/scss/pre_variables.scss",
            "web/static/lib/bootstrap/scss/_variables.scss",
            "web/static/lib/bootstrap/scss/_variables-dark.scss",
            "web/static/lib/bootstrap/scss/_maps.scss",
            ("include", "web._assets_bootstrap_backend"),
            ("include", "web._assets_core"),
            ("remove", "web/static/src/**/*.dark.scss"),
            "wh40k_session/static/src/pwa/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
}
