"""The stand-in for ``blpapi`` as an importable module: what a helper process (or ``TTO_BLPAPI_MODULE``)
imports in place of the real package.  The pretend terminal behind it is described by the environment
variable ``TTO_FAKE_BBG`` (JSON), which a spawned process inherits:

    {"securities": 200,            # TEST0000 Curncy ... with BID / ASK, plus USDTRY Curncy
     "invalid": 100,               # NONE0000 Curncy ...: securities Bloomberg does not know
     "workbook": true,             # ... or: answer what the workbooks recorded (everything they ask for)
     "missing_maturities": true,   # ... and no "TYB<n>D BFX. Curncy" maturity but the ones they recorded
     "history": true,              # ... and the daily closes the replay mode has (the history layer then has
                                   #     a few weeks of meeting pricing to compute: a minute of solid work)
     "idle_maturities": [1, 2, 9], # ... BIST swap maturities that exist but are not quoted: size 0 and an old
                                   #     price, the same on both sides (what the desk's terminal answers)
     "bad_close": ["TYSOC Curncy", "2026-10-27", 0.4],   # ... one close of the history that is off
     "viop_history": 90,           # ... and so many week days of made-up closes (up to yesterday) of the spot,
                                   #     the twelve VİOP contracts and the OIS tenors the VİOP sheet's history asks for
     "release_gil": true,          # accessors let go of the interpreter lock (see fake_blpapi.py)
     "queue_limit": 10000,         # undelivered events a session holds
     "tick_rate": 2000,            # ticks per second pushed by a background thread (0: none)
     "fail_start": true,           # the terminal is not there
     "hang_start": 30,             # ... or does not answer for so many seconds
     "silent": true,               # requests are never answered (time-outs)
     "crash_once": "/path/marker", # the process dies on the request for CRASH Curncy, once (the marker file)
     "crash_always": true,         # ... or every time
     "hang_once": "/path/marker",  # the helper stops talking on the request for HANG Curncy - alive, but its loop
     "hang_always": true,          #     blocks for good (a call that never returns) - once, or every time
     "stats": "/path/file.json"}   # written twice a second: ticks pushed / dropped, subscriptions, process id
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import threading
import time

import fake_blpapi

CONFIG = json.loads(os.environ.get("TTO_FAKE_BBG") or "{}")


def _server() -> "fake_blpapi.Server":
    if CONFIG.get("workbook"):
        srv = _workbook_server()
    else:
        srv = fake_blpapi.Server()
    n = int(CONFIG.get("securities", 0))
    for i in range(n):
        sec = "TEST%04d Curncy" % i
        for field, value in (("BID", 10.0 + i), ("ASK", 10.5 + i), ("BID_SIZE", 100.0), ("ASK_SIZE", 200.0)):
            srv.ref[(sec, field, ())] = value
            srv.rt[(sec, field)] = value
    for i in range(int(CONFIG.get("invalid", 0))):
        srv.invalid.add("NONE%04d Curncy" % i)
    if not CONFIG.get("workbook"):
        srv.ref[("USDTRY Curncy", "BID", ())] = 49.997
        srv.ref[("USDTRY Curncy", "ASK", ())] = 49.9975
        srv.ref[("USDTRY Curncy", "PX_LAST", ())] = 49.9973
        srv.ref[("TRY Curncy", "SETTLE_DT", ())] = _dt.date(2026, 11, 4)
        srv.rt[("USDTRY Curncy", "BID")] = 49.997
        srv.history[("USDTRY Curncy", "PX_LAST")] = [(_dt.date(2026, 10, 29), 49.90), (_dt.date(2026, 10, 30), 49.93),
                                                      (_dt.date(2026, 11, 2), 49.95), (_dt.date(2026, 11, 3), 49.99)]
    srv.fail_start = bool(CONFIG.get("fail_start"))
    srv.silent = bool(CONFIG.get("silent"))
    srv.queue_limit = int(CONFIG.get("queue_limit", 0))
    srv.release_gil = bool(CONFIG.get("release_gil"))
    return srv


def _workbook_server() -> "fake_blpapi.Server":
    """Everything the four workbooks recorded at their last calculation (exactly what the replay mode
    answers with)."""
    import tempfile

    from helpers import server_from_snapshot
    from tto.config import Settings
    from tto.service import Service

    closes = {}
    viop = None
    with tempfile.TemporaryDirectory() as folder:
        svc = Service(Settings(data_dir=folder, mode="replay", history=False))
        try:
            snapshot = dict(svc.provider.snapshot)
            if CONFIG.get("viop_history"):
                from conftest import cell
                viop = {"spot": cell(svc, "VIOP!S340"), "last": cell(svc, "VIOP!L511"),
                        "contracts": [(cell(svc, "VIOP!%s1" % a), cell(svc, "VIOP!%s9" % b))
                                      for a, b in zip("LMNOPQRSTUVW", "MNOPQRSTUVWX")]}
            if CONFIG.get("history"):
                items = [(t, d.field) for d in svc.history.snapshot()["defs"] for t in [d.ticker] + d.alts]
                closes = svc.provider.history(items, "20250101", "20991231")
        finally:
            svc.stop()
            svc.store.close()               # Windows does not remove a folder that holds an open database file
    extra = {}
    for days in CONFIG.get("idle_maturities", []):
        for source in (0, 1):
            sec = "TYB%dD BFX%d Curncy" % (days, source)
            for field, value in (("BID", 434.0 * days), ("ASK", 434.0 * days), ("BID_SIZE", 0.0), ("ASK_SIZE", 0.0)):
                extra[("BDP", sec, field, ())] = value
    snapshot.update(extra)
    srv = server_from_snapshot({k: v for k, v in snapshot.items() if k[0] not in ("BFX", "RT")})
    for (sec, field), rows in closes.items():
        srv.history[(sec, field)] = [(_dt.date.fromisoformat(day), value) for day, value in rows]
    if viop:
        srv.history.update(viop_history(viop, int(CONFIG["viop_history"]), _dt.date.today()))
    if CONFIG.get("bad_close"):
        sec, day, add = CONFIG["bad_close"]
        srv.history[(sec, "PX_LAST")] = [(d, v + add if d.isoformat() == day else v) for d, v in srv.history.get((sec, "PX_LAST"), [])]
    if CONFIG.get("missing_maturities"):
        # the BIST swap sheet asks for every maturity from 1 to 400 days on two sources; only a handful exist
        srv.invalid = _Missing({k[1] for k in snapshot if k[0] == "BDP"})
    return srv


def viop_history(viop, n: int, today: "_dt.date"):
    """Made-up daily closes for the VİOP sheet's history block: ``n`` week days up to yesterday.  The spot
    drifts up to its last level, each contract is priced at an implied TRY rate that rises with its expiry and
    wanders a little from day to day, the OIS and USD OIS tenors move slowly.  Stand-in data for the pretend
    terminal - nothing of it is a real quote."""
    import math

    days = []
    d = today - _dt.timedelta(days=1)
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= _dt.timedelta(days=1)
    days.reverse()
    out = {}
    last = viop["last"] if type(viop["last"]) is float else 50.0
    spot = {d: last * math.exp(-0.0011 * (len(days) - 1 - i)) for i, d in enumerate(days)}
    out[(viop["spot"], "PX_LAST")] = [(d, spot[d]) for d in days]
    for name, level, drift in (("TYSOA", 36.6, 0.004), ("TYSOB", 36.9, 0.005), ("TYSOC", 37.1, 0.006), ("TYSOF", 37.5, 0.007),
                               ("TYSOI", 37.4, 0.006), ("TYSO1", 36.9, 0.004), ("USSOA", 3.90, 0.0), ("USSOC", 3.95, 0.0005),
                               ("USSOF", 4.05, 0.0008), ("USSO1", 4.20, 0.001)):
        out[(name + " Curncy", "PX_LAST")] = [(d, level + drift * i + 0.06 * math.sin(i / 5.0 + len(name))) for i, d in enumerate(days)]
    base = _dt.date(1899, 12, 30)
    for k, (ticker, expiry) in enumerate(viop["contracts"]):
        if not isinstance(ticker, str) or type(expiry) is not float:
            continue
        rows = []
        for i, d in enumerate(days):
            g = expiry - ((d - base).days + 1)
            if g <= 0:
                continue
            rate = 0.335 + 0.0035 * k + 0.00012 * i + 0.004 * math.sin(i / 7.0 + k)
            rows.append((d, spot[d] * (1 + rate * g / 360) / (1 + 0.04 * g / 360)))
        out[(ticker, "PX_LAST")] = rows
    return out


class _Missing(set):
    """Securities Bloomberg does not know: every BIST swap maturity that is not in ``known``."""

    def __init__(self, known):
        super(_Missing, self).__init__()
        self.known = set(known)

    def __contains__(self, sec):
        if set.__contains__(self, sec):
            return True
        return isinstance(sec, str) and sec.startswith("TYB") and " BFX" in sec and sec not in self.known


server = _server()


class Session(fake_blpapi.Session):
    def __init__(self, options=None):
        super(Session, self).__init__(options, server)

    def start(self):
        if CONFIG.get("hang_start"):
            time.sleep(float(CONFIG["hang_start"]))
        return super(Session, self).start()

    def sendRequest(self, request, correlationId=None, **kwargs):
        marker = CONFIG.get("crash_once")
        asked = list(request.data.get("securities", [])) + [request.data.get("security")]   # (a bar request names one)
        if "CRASH Curncy" in asked:
            if CONFIG.get("crash_always"):
                os._exit(3)                      # the helper process dies without a word
            if marker and not os.path.exists(marker):
                with open(marker, "w") as fh:
                    fh.write("crashed")
                os._exit(3)
        hang = CONFIG.get("hang_once")
        if "HANG Curncy" in asked and (CONFIG.get("hang_always") or (hang and not os.path.exists(hang))):
            if hang:
                with open(hang, "w") as fh:
                    fh.write("hung")
            _freeze()
        return super(Session, self).sendRequest(request, correlationId=correlationId, **kwargs)


def _freeze() -> None:
    """The helper goes silent without dying: the loop that sends its batches to the dashboard blocks for good
    from its next batch on (as in a call that never returns); the process and its threads stay alive."""
    import sys
    mod = sys.modules.get("tto.marketdata.bbg_process")
    if mod is not None:
        mod._send_values = lambda *args, **kwargs: time.sleep(3600)


def _market() -> None:
    """Background ticks: every subscribed security in turn, ``tick_rate`` a second; and the statistics file."""
    rate = float(CONFIG.get("tick_rate", 0))
    stats = CONFIG.get("stats")
    pushed = 0
    t0 = time.time()
    last_stats = 0.0
    while True:
        now = time.time()
        if rate > 0:
            due = int((now - t0) * rate) - pushed
            for s in list(server.sessions):
                subs = list(s.subs)
                if not subs:
                    continue
                for j in range(min(due, 5000)):
                    n = pushed + j
                    sec = subs[n % len(subs)]
                    values = {}
                    for f in s.subs[sec][0]:                 # the security's own level, moved a hair
                        base = server.rt.get((sec, f))
                        if isinstance(base, float):
                            values[f] = base * (1.0 + 1e-6 * (n % 11))
                    s.push_tick(sec, values or {"MKTDATA_EVENT_TYPE": "QUOTE"})
                break
            pushed += max(0, min(due, 5000))
        if stats and now - last_stats >= 0.5:
            last_stats = now
            try:
                with open(stats + ".tmp", "w") as fh:
                    json.dump({"pushed": pushed, "dropped": server.dropped, "pid": os.getpid(),
                               "subscriptions": sum(len(s.subs) for s in server.sessions),
                               "asked": len(server.subscriptions),                     # subscribe + resubscribe calls
                               "topics": len({t for t, _ in server.subscriptions}),    # securities ever asked for
                               "queued": sum(s.events.qsize() for s in server.sessions)}, fh)
                os.replace(stats + ".tmp", stats)
            except OSError:
                pass
        time.sleep(0.005)


if CONFIG.get("tick_rate") or CONFIG.get("stats"):
    threading.Thread(target=_market, name="fake-market", daemon=True).start()

Name = fake_blpapi.Name
CorrelationId = fake_blpapi.CorrelationId
SessionOptions = fake_blpapi.SessionOptions
Event = fake_blpapi.Event
SubscriptionList = fake_blpapi.SubscriptionList
