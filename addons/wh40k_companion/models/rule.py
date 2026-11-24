from odoo import fields, models


class Wh40kRule(models.Model):
    _name = "wh40k.rule"
    _description = "WH40k Army / Detachment Rule"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    description = fields.Text(translate=True)
    external_id = fields.Char(index=True)
    rule_scope = fields.Selection(
        [
            ("army", "Army"),
            ("detachment", "Detachment"),
            ("stratagem", "Stratagem"),
        ],
        string="Scope",
    )
    cp = fields.Char(string="CP")
    when_text = fields.Text(string="When")
    target_text = fields.Text(string="Target")
    effect_text = fields.Text(string="Effect")
    restrictions = fields.Text()
    flavor = fields.Text()
    owner_partner_id = fields.Many2one(
        "res.partner",
        string="Owner",
        index=True,
        ondelete="cascade",
        help="Roster owner; used for record ACL.",
    )
    force_ids = fields.Many2many(
        "wh40k.force",
        "wh40k_force_army_rule_rel",
        "rule_id",
        "force_id",
        string="Forces",
    )
    detachment_ids = fields.Many2many(
        "wh40k.detachment",
        "wh40k_detachment_rule_rel",
        "rule_id",
        "detachment_id",
        string="Detachments",
    )
