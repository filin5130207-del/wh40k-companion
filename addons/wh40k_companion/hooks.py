import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Grant Player group + Battle App home action after install."""
    try:
        env["res.users"]._wh40k_repair_player_access()
    except Exception:
        _logger.exception("WH40k post_init player access repair failed")