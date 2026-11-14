import sys
from pathlib import Path


def _ensure_wh40k_token():
    here = Path(__file__).resolve()
    for candidate in (here.parents[2] / "services", Path("/opt/wh40k")):
        if (candidate / "wh40k_token" / "__init__.py").is_file():
            entry = str(candidate)
            if entry not in sys.path:
                sys.path.insert(0, entry)
            return


_ensure_wh40k_token()

from . import models  # noqa: E402
from . import controllers  # noqa: E402
