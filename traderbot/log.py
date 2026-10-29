"""Logging to a rotating file in the app folder, plus any extra handler the UI adds."""

import logging
import logging.handlers

from . import paths

FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def setup(level=logging.INFO):
    root = logging.getLogger()
    if any(getattr(h, "_traderbot", False) for h in root.handlers):
        return root
    root.setLevel(level)
    fh = logging.handlers.RotatingFileHandler(paths.path("logs", "traderbot.log"),
                                              maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(logging.Formatter(FORMAT))
    fh._traderbot = True
    root.addHandler(fh)
    return root
