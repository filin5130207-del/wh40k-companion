{
    "name": "WH40k Roster",
    "version": "20.0.1.0.0",
    "category": "Games",
    "summary": "Battlescribe/NewRecruit import and datasheets",
    "description": """
Roster service. Owns imported datasheets. The owner is ``owner_uid``, an
integer from the session service, not a res.users row in this database.
""",
    "author": "WH40k Companion",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.access.csv",
    ],
    "application": True,
    "installable": True,
}
