"""The Bloomberg session in a helper process (tto/marketdata/bbg_process.py).

Why it exists is measured here too: a reader thread that shares its process with a computing thread reads
ticks hundreds of times slower (every call into blpapi lets go of the interpreter lock and waits to get it
back), which is how the desk's first live run ended in "Slow consumer: event queue is full, events are
being dropped".  The stand-in for blpapi behaves the same way (``release_gil``) and has the same limited
event queue (``queue_limit``).
"""
import json
import multiprocessing
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

import fake_blpapi
from tto.config import FORBIDDEN_PORTS, Settings
from tto.marketdata import bbg_process
from tto.marketdata.base import INVALID_SECURITY, REQUESTING, bdp_key
from tto.marketdata.bbg_process import IsolatedBloombergProvider, IsolationError
from tto.marketdata.bloomberg import NA_NA, NO_BFX, BloombergProvider
from tto.service import Service
from tto.xl.values import XlArray

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GIL = getattr(sys, "_is_gil_enabled", lambda: True)()


def wait_for(cond, timeout=15.0, step=0.02):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return bool(cond())


def alive(pid: int) -> bool:
    """Is the process still running (a zombie nobody has collected counts as gone)?"""
    if os.name == "nt":
        # not os.kill(pid, 0): on Windows signal 0 is CTRL_C_EVENT, a console event that "succeeds" whatever the
        # process - and without a console Python goes on to TerminateProcess, ending the process it was to look at
        import _winapi
        try:
            handle = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, pid)
        except OSError:
            return False                                # no such process any more
        try:
            return _winapi.WaitForSingleObject(handle, 0) == _winapi.WAIT_TIMEOUT
        finally:
            _winapi.CloseHandle(handle)
    try:
        with open("/proc/%d/stat" % pid) as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def helpers():
    return [p for p in multiprocessing.active_children() if p.name == "tto-bloomberg"]


@pytest.fixture()
def fake(monkeypatch, tmp_path):
    """Describe the pretend terminal of the helper: ``fake(securities=50, tick_rate=100)`` -> stats reader."""
    stats = str(tmp_path / "stats.json")

    def configure(**config):
        config.setdefault("stats", stats)
        monkeypatch.setenv("TTO_FAKE_BBG", json.dumps(config))

        def read():
            try:
                with open(stats) as fh:
                    return json.load(fh)
            except (OSError, ValueError):
                return {}
        return read

    return configure


@pytest.fixture()
def isolated():
    made = []

    def make(**kw):
        kw.setdefault("blpapi_name", "fake_blpapi_live")
        kw.setdefault("reconnect_wait", 0.2)
        p = IsolatedBloombergProvider(**kw)
        made.append(p)
        return p

    yield make
    for p in made:
        p.stop()
    assert wait_for(lambda: not helpers(), 10), "a helper process was left behind"


def settle(p, timeout=20.0):
    assert wait_for(lambda: not p.busy(), timeout)
    time.sleep(0.25)                                    # the last batch of values is on its way
    assert not p.busy()


def spin(stop):
    x = 0
    while not stop.is_set():
        for i in range(5000):
            x = (x * 31 + i) % 1000003


# ====================================================================================== the ordinary life
def test_values_cross_the_process_boundary_like_in_process(fake, isolated):
    stats = fake(securities=3, invalid=2)
    p = isolated(bfx="approx")
    p.start()
    bid, ask, last = (bdp_key("USDTRY Curncy", f) for f in ("BID", "ASK", "PX_LAST"))
    assert p.get_bdp(bid) == REQUESTING and p.busy()            # what Excel shows while it waits
    for k in (ask, last, bdp_key("TRY Curncy", "SETTLE_DT"), bdp_key("NONE0000 Curncy", "BID"), bdp_key("YOK Curncy", "PX_LAST")):
        p.get_bdp(k)
    settle(p)
    assert (p.get_bdp(bid), p.get_bdp(ask), p.get_bdp(last)) == (49.997, 49.9975, 49.9973)
    assert p.get_bdp(bdp_key("TRY Curncy", "SETTLE_DT")) == "4.11.2026"
    assert p.get_bdp(bdp_key("NONE0000 Curncy", "BID")) == INVALID_SECURITY
    assert p.get_bdp(bdp_key("YOK Curncy", "PX_LAST")) == NA_NA
    assert sorted(p.drain_changes()) == sorted([bid, ask, last, bdp_key("TRY Curncy", "SETTLE_DT"),
                                                bdp_key("NONE0000 Curncy", "BID"), bdp_key("YOK Curncy", "PX_LAST")])
    assert p.drain_changes() == []
    st = p.status()
    assert st["mode"] == "live" and st["isolated"] and st["connected"] and st["worker"] == "running" and st["restarts"] == 0
    assert st["hits_today"] == 6 and st["pending"] == 0 and st["streaming"] and st["items"] == 6
    assert wait_for(lambda: p.status()["subscriptions"] == 2)   # USDTRY and YOK; the unknown security is not asked for
    assert p.status()["subscriptions_invalid"] == 1
    assert wait_for(lambda: stats().get("topics") == 2)
    # history: a BDH cell of the workbook, and the blocking call of the daily history
    opts = (("DATES", "S"), ("DAYS", "W"), ("FILL", "P"))
    bdh = ("BDH", "USDTRY Curncy", "PX_LAST", "20261029", "20261103", opts)
    assert p.get_bdh(bdh) == REQUESTING
    settle(p)
    got = p.get_bdh(bdh)
    assert type(got) is XlArray and got.rows == [[46324.0, 49.90], [46325.0, 49.93], [46328.0, 49.95], [46329.0, 49.99]]
    rows = p.history([("USDTRY Curncy", "PX_LAST"), ("YOK Curncy", "PX_LAST")], "20261001", "20261103", timeout=10)
    assert rows == {("USDTRY Curncy", "PX_LAST"): [("2026-10-29", 49.90), ("2026-10-30", 49.93), ("2026-11-02", 49.95),
                                                   ("2026-11-03", 49.99)]}
    # BFXFORWARD has no API equivalent; the approximation works on values the helper fetched
    assert p.get_bfx(("BFX", "USDTRY", "20261204", "MID")) in (REQUESTING, NO_BFX)
    settle(p)
    assert p.get_bfx(("BFX", "USDTRY", "20261204", "MID")) == NO_BFX        # the pretend terminal has no curve


def test_ticks_reach_the_engine_as_the_latest_value(fake, isolated):
    stats = fake(securities=20, tick_rate=400)
    p = isolated()
    p.start()
    keys = [bdp_key("TEST%04d Curncy" % i, f) for i in range(20) for f in ("BID", "ASK")]
    for k in keys:
        p.get_bdp(k)
    settle(p)
    p.drain_changes()
    first = {k: p.get_bdp(k) for k in keys}
    assert wait_for(lambda: len(set(p.drain_changes())) >= 30, timeout=10)      # ticks arrive without being asked for
    assert any(p.get_bdp(k) != first[k] for k in keys)
    st = p.status()
    assert st["ticks"] > 100 and st["hits_today"] == 40                           # streaming costs no data points
    assert wait_for(lambda: stats().get("pushed", 0) > 400)
    assert stats()["dropped"] == 0


def test_stop_ends_the_helper(fake, isolated):
    stats = fake(securities=1)
    p = isolated()
    p.start()
    assert wait_for(lambda: stats().get("pid"))
    pid = stats()["pid"]
    assert alive(pid) and pid != os.getpid() and len(helpers()) == 1
    p.get_bdp(bdp_key("USDTRY Curncy", "BID"))
    settle(p)
    p.stop()
    assert wait_for(lambda: not alive(pid), 10)
    assert not p.status()["connected"]
    assert p.get_bdp(bdp_key("USDTRY Curncy", "BID")) == 49.997                   # what was known stays readable
    p.stop()                                                                      # twice is harmless


# ====================================================================================== when things go wrong
def test_a_missing_blpapi_is_noticed_without_starting_a_process(isolated):
    p = isolated(blpapi_name="blpapi_that_is_not_installed")
    t0 = time.time()
    with pytest.raises(ImportError):
        p.start()
    assert time.time() - t0 < 1.0 and not helpers()


def test_a_blpapi_that_cannot_be_loaded_is_reported_as_such(isolated):
    """Installed, but its import fails in the helper (the C++ library is missing): the same ImportError the
    dashboard gets in-process, so "auto" mode falls back to the saved data."""
    p = isolated(blpapi_name="fake_blpapi_broken")
    with pytest.raises(ImportError) as err:
        p.start()
    assert "DLL load failed" in str(err.value)
    assert wait_for(lambda: not helpers(), 10)


def test_an_unreachable_terminal_is_reported_as_in_process(fake, isolated):
    fake(fail_start=True)
    p = isolated()
    with pytest.raises(RuntimeError) as err:
        p.start()
    assert not isinstance(err.value, IsolationError) and "Bloomberg oturumu açılamadı" in str(err.value)
    assert wait_for(lambda: not helpers(), 10)


def test_a_helper_that_does_not_answer_is_given_up(fake, isolated):
    fake(hang_start=60)
    p = isolated(start_timeout=1.5)
    t0 = time.time()
    with pytest.raises(IsolationError):
        p.start()
    assert time.time() - t0 < 10
    assert wait_for(lambda: not helpers(), 10)                  # and it is not left running


def test_a_helper_that_dies_is_started_again_and_asked_for_everything(fake, isolated, tmp_path):
    stats = fake(securities=5, crash_once=str(tmp_path / "crashed"))
    p = isolated()
    p.start()
    keys = [bdp_key("TEST%04d Curncy" % i, "BID") for i in range(5)]
    for k in keys:
        p.get_bdp(k)
    settle(p)
    assert [p.get_bdp(k) for k in keys] == [10.0, 11.0, 12.0, 13.0, 14.0]
    assert wait_for(lambda: stats().get("pid"))
    first = stats()["pid"]
    p.drain_changes()
    p.get_bdp(bdp_key("CRASH Curncy", "PX_LAST"))                # the helper dies on this request
    assert wait_for(lambda: p.status()["restarts"] == 1, 20)
    assert wait_for(lambda: p.status()["connected"] and p.status()["worker"] == "running", 10)
    settle(p)
    assert wait_for(lambda: stats().get("pid") not in (None, first))
    assert not alive(first)
    assert [p.get_bdp(k) for k in keys] == [10.0, 11.0, 12.0, 13.0, 14.0]       # nothing was lost meanwhile
    assert p.get_bdp(bdp_key("CRASH Curncy", "PX_LAST")) == NA_NA                # ... and the request was repeated
    assert wait_for(lambda: p.status()["subscriptions"] == 6)                    # the new helper subscribed again
    new = bdp_key("TEST0000 Curncy", "ASK")
    p.get_bdp(new)
    settle(p)
    assert p.get_bdp(new) == 10.5
    # the daily count of data points goes on where the first helper stopped: 5 before, then 5 + 1 + 1 again
    assert p.status()["hits_today"] >= 12


def test_a_helper_that_keeps_dying_is_not_restarted_for_ever(fake, isolated, monkeypatch):
    """Every new helper asks Bloomberg for everything again.  One that dies again and again would use up the
    terminal's daily data limit that way, so after a few quick deaths in a row the dashboard stops trying
    and says so."""
    monkeypatch.setattr(bbg_process, "MAX_QUICK_DEATHS", 2)
    fake(securities=2, crash_always=True)
    p = isolated(reconnect_wait=0.1)
    p.start()
    keys = [bdp_key("TEST%04d Curncy" % i, "BID") for i in range(2)]
    for k in keys:
        p.get_bdp(k)
    settle(p)
    p.get_bdp(bdp_key("CRASH Curncy", "PX_LAST"))                # dies on it, and again after the restart
    assert wait_for(lambda: p.status()["worker"] == "stopped", 30)
    st = p.status()
    assert st["restarts"] == 1 and not st["connected"] and "art arda 2 kez" in st["error"]
    assert not p.busy()                                           # nothing the engine should wait for
    assert [p.get_bdp(k) for k in keys] == [10.0, 11.0]          # the last values stay readable
    time.sleep(1.0)
    assert not helpers() and p.status()["restarts"] == 1          # and it stays that way


def test_a_value_that_cannot_cross_the_pipe_does_not_hold_up_the_rest():
    sent = []

    def send(obj):
        import pickle
        pickle.dumps(obj)                                         # what Connection.send does first
        sent.append(obj)

    batch = [(("BDP", "A", "X", ()), 1.5), (("BDP", "B", "X", ()), threading.Lock()), (("BDP", "C", "X", ()), "txt")]
    bbg_process._send_values(send, batch, 3, {"pending": 0})
    assert sent == [("values", [(("BDP", "A", "X", ()), 1.5), (("BDP", "B", "X", ()), NA_NA),
                                (("BDP", "C", "X", ()), "txt")], 3, {"pending": 0})]


def test_the_helper_ends_when_the_dashboard_dies(tmp_path):
    """A dashboard that is killed (no clean-up at all) must not leave a process holding a Bloomberg session."""
    stats = str(tmp_path / "stats.json")
    script = (
        "import json, os, sys, time\n"
        "sys.path[:0] = [%r, %r]\n"
        "from tto.marketdata.bbg_process import IsolatedBloombergProvider\n"
        "if __name__ == '__main__':\n"
        "    p = IsolatedBloombergProvider(blpapi_name='fake_blpapi_live')\n"
        "    p.start()\n"
        "    for _ in range(200):\n"
        "        if os.path.exists(%r):\n"
        "            break\n"
        "        time.sleep(0.05)\n"
        "    print(json.load(open(%r))['pid'], flush=True)\n"
        "    os._exit(0)\n" % (ROOT, HERE, stats, stats))
    path = tmp_path / "dies.py"
    path.write_text(script)
    env = dict(os.environ, TTO_FAKE_BBG=json.dumps({"securities": 1, "stats": stats}))
    out = subprocess.run([sys.executable, str(path)], env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    pid = int(out.stdout.strip().splitlines()[-1])
    assert wait_for(lambda: not alive(pid), 15), "the helper outlived the dashboard"


# ====================================================================================== the reason for all this
@pytest.mark.skipif(not GIL, reason="needs the interpreter lock")
def test_a_reader_next_to_a_computing_thread_falls_behind_and_the_helper_does_not(fake, isolated):
    """The measurement behind the design.  2 000 ticks a second, an event queue of blpapi's own default
    length (10 000), and a dashboard that computes all the time:

    * inside the dashboard's process the reader gets through a few per cent of them and the queue overflows;
    * in the helper process every tick is read and nothing is dropped.
    """
    stop = threading.Event()
    threads = [threading.Thread(target=spin, args=(stop,), daemon=True) for _ in range(2)]
    try:
        # ---- in the dashboard's own process
        server = fake_blpapi.Server()
        server.release_gil = True
        server.queue_limit = 10000
        for i in range(50):
            for f, v in (("BID", 10.0 + i), ("ASK", 10.5 + i)):
                server.ref[("TEST%04d Curncy" % i, f, ())] = v
        inproc = BloombergProvider(blpapi_module=fake_blpapi.module(server))
        inproc.start()
        try:
            for i in range(50):
                for f in ("BID", "ASK"):
                    inproc.get_bdp(bdp_key("TEST%04d Curncy" % i, f))
            assert wait_for(lambda: inproc.status()["subscriptions"] == 50)
            for t in threads:
                t.start()
            before = inproc.status()["ticks"]
            t0 = time.time()
            pushed = 0
            while time.time() - t0 < 3.0:                        # 2 000 ticks a second for three seconds
                due = int((time.time() - t0) * 2000) - pushed
                for j in range(due):
                    server.tick("TEST%04d Curncy" % ((pushed + j) % 50), {"BID": 20.0 + pushed + j})
                pushed += due
                time.sleep(0.01)
            read_inproc = inproc.status()["ticks"] - before
        finally:
            inproc.stop()
            server.release_gil = False
        assert pushed > 5000
        assert read_inproc < 0.25 * pushed, "the reader kept up in-process: %d of %d" % (read_inproc, pushed)

        # ---- in the helper process, under the same load
        stats = fake(securities=50, release_gil=True, queue_limit=10000, tick_rate=2000)
        p = isolated()
        p.start()
        keys = [bdp_key("TEST%04d Curncy" % i, f) for i in range(50) for f in ("BID", "ASK")]
        for k in keys:
            p.get_bdp(k)
        assert wait_for(lambda: p.status()["subscriptions"] == 50, 30)
        a, t0 = p.status()["ticks"], time.time()
        time.sleep(3.0)
        b, seconds = p.status()["ticks"], time.time() - t0
        assert b - a > 0.7 * 2000 * (seconds - 1.0), "the helper read only %d ticks in %.1f s" % (b - a, seconds)
        st, fk = p.status(), stats()
        assert fk["dropped"] == 0 and fk["queued"] < 2500
        assert not st["slow"] and st["slow_warnings"] == 0 and st["events_dropped"] == 0
        assert len(set(p.drain_changes())) >= 50                 # ... and the values arrive in the dashboard
    finally:
        stop.set()
        fake_blpapi.Server().release_gil = False


# ====================================================================================== in the dashboard
def test_the_dashboard_uses_the_helper_and_falls_back_when_it_cannot(fake, tmp_path, monkeypatch):
    fake(securities=1)
    monkeypatch.setenv("TTO_BLPAPI_MODULE", "fake_blpapi_live")
    svc = Service(Settings(data_dir=str(tmp_path / "a"), mode="live", history=False))
    try:
        assert svc.mode == "live" and isinstance(svc.provider, IsolatedBloombergProvider) and svc.mode_note == ""
        assert svc.provider.interval == 0.0 and svc.provider.queue_size == 100000
        st = svc.status()["provider"]
        assert st["isolated"] and st["connected"] and st["worker"] == "running"
        assert len(helpers()) == 1
        assert svc.describe() == "Veri: Bloomberg canlı · oturum ayrı bir yardımcı süreçte"
    finally:
        svc.stop()
    assert wait_for(lambda: not helpers(), 10)

    # the helper cannot be started: the session runs inside the dashboard, tuned for it
    def refuse(self):
        raise IsolationError("yardımcı süreç başlatılamadı: denied")

    before = sys.getswitchinterval()
    monkeypatch.setattr(IsolatedBloombergProvider, "_spawn", refuse)
    try:
        svc = Service(Settings(data_dir=str(tmp_path / "b"), mode="live", history=False))
        try:
            assert svc.mode == "live" and type(svc.provider) is BloombergProvider
            assert "yardımcı süreç" in svc.mode_note
            assert svc.provider.interval == 1.0                  # ticks conflated: one a second per subscription
            assert svc.status()["provider"]["isolated"] is False
            assert sys.getswitchinterval() <= 0.001 + 1e-9       # the reader thread is favoured
            assert "kendi sürecinde" in svc.describe() and "başlatılamadı" in svc.describe()
        finally:
            svc.stop()
        svc = Service(Settings(data_dir=str(tmp_path / "c"), mode="live", history=False, bbg_isolate=False,
                               bbg_interval=0.0, bbg_queue=5000))
        try:
            assert type(svc.provider) is BloombergProvider and svc.mode_note == ""
            assert svc.provider.interval == 0.0 and svc.provider.queue_size == 5000
        finally:
            svc.stop()
    finally:
        sys.setswitchinterval(before)
    assert not helpers()


def _free_port():
    for _ in range(50):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        if port not in FORBIDDEN_PORTS:
            return port
    raise RuntimeError("no free port")


_SESSIONS = {}                                          # port -> the headers of the first administrator's session


def _status(port):
    from helpers import first_admin
    url = "http://127.0.0.1:%d" % port
    if port not in _SESSIONS:
        _SESSIONS[port] = first_admin(url)              # every /api request but the sign-in needs a session
    with urllib.request.urlopen(urllib.request.Request(url + "/api/status", headers=_SESSIONS[port]), timeout=10) as r:
        return json.load(r)


@pytest.mark.skipif(not GIL, reason="needs the interpreter lock")
def test_python_m_tto_live_keeps_up_with_a_busy_market(tmp_path):
    """The desk's first live run, as closely as it can be staged without a terminal: ``python -m tto --mode
    live`` with the four workbooks, a terminal that answers what they recorded, 1 500 ticks a second, an
    event queue of blpapi's default length and accessors that let go of the interpreter lock.  Nothing may be
    dropped, unknown securities are not subscribed to, and stopping the dashboard ends the helper."""
    stats = str(tmp_path / "stats.json")
    port = _free_port()
    env = dict(os.environ, TTO_BLPAPI_MODULE="fake_blpapi_live", PYTHONPATH=os.pathsep.join([HERE, ROOT]),
               TTO_FAKE_BBG=json.dumps({"workbook": True, "missing_maturities": True, "release_gil": True,
                                        "queue_limit": 10000, "tick_rate": 1500, "stats": stats}))
    log = open(str(tmp_path / "server.log"), "w")
    proc = subprocess.Popen([sys.executable, "-m", "tto", "--mode", "live", "--port", str(port), "--host", "127.0.0.1",
                             "--data-dir", str(tmp_path / "data"), "--no-history", "--tick", "1"],
                            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        def up():
            try:
                return _status(port)["mode"] == "live"
            except Exception:  # noqa: BLE001
                assert proc.poll() is None, "the dashboard ended: see %s" % log.name
                return False
        assert wait_for(up, 240, 0.5), open(log.name).read()[-2000:]
        # the first calculation of everything: wait until nothing is outstanding any more
        quiet = {"since": None}

        def warm():
            st = _status(port)["provider"]
            if st["pending"] == 0 and st["subscriptions"] > 150:
                quiet["since"] = quiet["since"] or time.time()
                return time.time() - quiet["since"] > 3.0
            quiet["since"] = None
            return False
        assert wait_for(warm, 300, 0.5), _status(port)["provider"]
        a = _status(port)["provider"]
        time.sleep(4.0)
        b = _status(port)["provider"]
        with open(stats) as fh:
            fk = json.load(fh)
        assert b["isolated"] and b["connected"] and b["worker"] == "running" and b["restarts"] == 0
        assert b["ticks"] - a["ticks"] > 0.6 * 1500 * 3.0, (a["ticks"], b["ticks"])      # the helper keeps reading
        assert fk["dropped"] == 0 and fk["queued"] < 5000, fk
        assert not b["slow"] and b["slow_warnings"] == 0 and b["events_dropped"] == 0 and b["messages_lost"] == 0
        assert b["subscriptions_invalid"] > 700                    # the maturities that do not exist ...
        assert fk["topics"] == b["subscriptions"] + b["subscriptions_failed"]     # ... were never subscribed to
        assert b["subscriptions"] > 150 and b["hits_today"] < 12000 and not b["limit_reached"]
        print("\nlive run: %s" % {k: b[k] for k in ("subscriptions", "subscriptions_invalid", "subscriptions_failed",
                                                     "hits_today", "ticks", "items", "requests")}, fk)
        helper = fk["pid"]
        assert alive(helper) and helper != proc.pid
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=60)
        assert wait_for(lambda: not alive(helper), 15), "the helper outlived the dashboard"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=30)
        log.close()
