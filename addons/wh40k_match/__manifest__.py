{
    "name": "WH40k Match",
    "version": "20.0.1.0.0",
    "category": "Games",
    "summary": "Match create, join token, wounds, undo, surrender, and watch",
    "description": """
Match service. Players are external user ids from the session service.
Army lists are snapshots copied from the roster service at create and join.
There is no Many2one to wh40k.roster or res.users.
""",
    "author": "WH40k Companion",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.access.csv",
        "data/mission_data.xml",
        "data/ir_cron_data.xml",
    ],
    "application": True,
    "installable": True,
}
