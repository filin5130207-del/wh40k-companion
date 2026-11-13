import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """After ACL/group XML load: repair portal/nickname users to Player."""
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        env["res.users"]._wh40k_repair_player_access()
    except Exception:
        _logger.exception("WH40k 20.0.1.3.0 end-migrate player repair failed")