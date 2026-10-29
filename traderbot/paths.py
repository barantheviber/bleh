"""Where TraderBot keeps its files.

Windows: %APPDATA%\\TraderBot, macOS: ~/Library/Application Support/TraderBot,
elsewhere: ~/.local/share/TraderBot. TRADERBOT_HOME overrides all of them
(the tests and the self-test use a temporary folder).
"""

import os
import sys

APP = "TraderBot"


def app_dir():
    base = os.environ.get("TRADERBOT_HOME")
    if not base:
        if sys.platform.startswith("win"):
            base = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP)
        elif sys.platform == "darwin":
            base = os.path.expanduser("~/Library/Application Support/" + APP)
        else:
            base = os.path.join(os.environ.get("XDG_DATA_HOME") or
                                os.path.expanduser("~/.local/share"), APP)
    os.makedirs(base, exist_ok=True)
    return base


def path(*parts):
    p = os.path.join(app_dir(), *parts)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return p


def resource(*parts):
    """A file shipped with the app (research report, icons): next to the
    package when running from source, under _MEIPASS in the frozen exe."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)
