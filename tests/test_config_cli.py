"""The dashboard never runs on the ports that other dashboards already use on the desk machine (5000, 5001)."""
import os
import subprocess
import sys

import pytest

from tto.config import DEFAULT_PORT, FORBIDDEN_PORTS, Settings, check_port

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_default_port_is_allowed():
    assert DEFAULT_PORT == 1057
    assert FORBIDDEN_PORTS == (5000, 5001)
    assert DEFAULT_PORT not in FORBIDDEN_PORTS
    assert Settings().port == 1057


@pytest.mark.parametrize("port", [5000, 5001, "5000"])
def test_reserved_ports_are_refused(port):
    with pytest.raises(ValueError):
        check_port(port)
    with pytest.raises(ValueError):
        Settings(port=port)


@pytest.mark.parametrize("port", [0, -1, 70000])
def test_invalid_ports(port):
    with pytest.raises(ValueError):
        check_port(port)


@pytest.mark.parametrize("port", [1054, 1055, 1056, 1057, 4999, 5002, 8080, 65535])
def test_other_ports_are_fine(port):
    assert check_port(port) == port


@pytest.mark.parametrize("port", ["5000", "5001"])
def test_command_line_refuses_reserved_ports(port):
    res = subprocess.run([sys.executable, "-m", "tto", "--port", port, "--mode", "replay"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 2
    assert "5000" in res.stderr and "5001" in res.stderr


def test_environment_port_is_checked_too():
    env = dict(os.environ, TTO_PORT="5001")
    res = subprocess.run([sys.executable, "-m", "tto", "--mode", "replay"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 2


def test_bloomberg_session_options_on_the_command_line():
    """Where the Bloomberg session runs and how it is tuned (see tto/marketdata/bbg_process.py)."""
    from tto.__main__ import build_parser, settings_from

    s = settings_from(build_parser().parse_args([]))
    assert s.bbg_isolate is True and s.bbg_interval is None and s.bbg_queue == 100000 and s.history_pace == 1.0
    s = settings_from(build_parser().parse_args(["--bbg-inprocess", "--bbg-interval", "2", "--bbg-queue", "50000"]))
    assert s.bbg_isolate is False and s.bbg_interval == 2.0 and s.bbg_queue == 50000
    s = settings_from(build_parser().parse_args(["run", "--bbg-interval", "0"]))
    assert s.bbg_isolate is True and s.bbg_interval == 0.0          # 0: every tick, also inside the dashboard
    assert Settings(bbg_interval=-3).bbg_interval == 0.0 and Settings(history_pace=-1).history_pace == 0.0
