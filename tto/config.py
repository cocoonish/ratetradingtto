"""Runtime settings."""
from __future__ import annotations

import os
from typing import Optional

#: ports that are already taken on the desk machine by other dashboards
FORBIDDEN_PORTS = (1055, 1056)
DEFAULT_PORT = 1057

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(object):
    def __init__(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT, data_dir: Optional[str] = None,
                 mode: str = "auto", bbg_host: str = "localhost", bbg_port: int = 8194,
                 tick_seconds: float = 2.0, locale: str = "tr", models_dir: Optional[str] = None,
                 bbg_stream: bool = True, bbg_bfx: str = "off", bbg_max_hits: int = 400000,
                 bbg_price_poll: float = 30.0):
        self.host = host
        self.port = check_port(port)
        self.data_dir = data_dir or os.environ.get("TTO_DATA_DIR") or os.path.join(ROOT, "data")
        self.mode = mode                    # auto | live | replay
        self.bbg_host = bbg_host
        self.bbg_port = int(bbg_port)
        self.tick_seconds = float(tick_seconds)
        self.locale = locale
        self.models_dir = models_dir or os.path.join(ROOT, "models")
        self.bbg_stream = bool(bbg_stream)      # real-time fields by subscription (False: poll them)
        self.bbg_bfx = bbg_bfx                  # "off" | "approx"  (BFXFORWARD has no API equivalent)
        self.bbg_max_hits = int(bbg_max_hits)   # daily cap on reference/historical data points (0 = no cap)
        self.bbg_price_poll = float(bbg_price_poll)

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "tto.db")


def check_port(port) -> int:
    port = int(port)
    if port in FORBIDDEN_PORTS:
        raise ValueError("port %d is reserved for the other desk dashboards (%s); choose another one, "
                         "e.g. %d" % (port, ", ".join(str(p) for p in FORBIDDEN_PORTS), DEFAULT_PORT))
    if not (1 <= port <= 65535):
        raise ValueError("invalid port %r" % (port,))
    return port
