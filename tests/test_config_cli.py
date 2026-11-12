"""The dashboard never runs on the ports reserved for the other desk dashboards (1055, 1056)."""
import os
import subprocess
import sys

import pytest

from tto.config import DEFAULT_PORT, FORBIDDEN_PORTS, Settings, check_port

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_default_port_is_allowed():
    assert DEFAULT_PORT == 1057
    assert DEFAULT_PORT not in FORBIDDEN_PORTS
    assert Settings().port == 1057


@pytest.mark.parametrize("port", [1055, 1056, "1055"])
def test_reserved_ports_are_refused(port):
    with pytest.raises(ValueError):
        check_port(port)
    with pytest.raises(ValueError):
        Settings(port=port)


@pytest.mark.parametrize("port", [0, -1, 70000])
def test_invalid_ports(port):
    with pytest.raises(ValueError):
        check_port(port)


@pytest.mark.parametrize("port", [1054, 1057, 8080, 65535])
def test_other_ports_are_fine(port):
    assert check_port(port) == port


@pytest.mark.parametrize("port", ["1055", "1056"])
def test_command_line_refuses_reserved_ports(port):
    res = subprocess.run([sys.executable, "-m", "tto", "--port", port, "--mode", "replay"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 2
    assert "1055" in res.stderr and "1056" in res.stderr


def test_environment_port_is_checked_too():
    env = dict(os.environ, TTO_PORT="1056")
    res = subprocess.run([sys.executable, "-m", "tto", "--mode", "replay"], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 2
