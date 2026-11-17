"""A scenario loaded and an input written at the same time: they are applied in the order they were sent.

The browser sends an input as it is typed; the engine applies it in its queue of writes.  A scenario loaded right
after (before that write's turn came) once replaced the stored inputs at once, outside the queue - and the write still
waiting landed over the loaded scenario (the typed value came back).  The load now waits in the same queue.
"""
from __future__ import annotations

import threading
import time

from conftest import cell, make_service
from tto.service import EngineThread


def _until(cond, seconds=10.0):
    end = time.time() + seconds
    while not cond():
        assert time.time() < end, "timed out"
        time.sleep(0.01)


def test_a_write_waiting_in_the_queue_does_not_land_over_a_loaded_scenario(tmp_path):
    svc = make_service(tmp_path)
    try:
        u = svc.login("Sıra Deneme")["user"]
        assert svc.set_inputs(u, "tto", [{"ref": "Forward!D2", "value": "15.12.2026"}])["errors"] == []
        assert cell(svc, "Forward!D2", u) == 46371.0                       # 15.12.2026
        svc.save_scenario(u, "sıra")
        # the engine busy (a page being made, say): what is sent now waits in its queue
        gate = threading.Event()
        blocker = svc.et.submit_at(EngineThread.WRITE, gate.wait, 30)
        _until(lambda: svc.et.busy_for() > 0)
        typed = threading.Thread(target=svc.set_inputs, args=(u, "tto", [{"ref": "Forward!D2", "value": "01.03.2027"}]))
        typed.start()
        _until(lambda: svc.et.queued() >= 1)                               # the typed date waits
        loaded = threading.Thread(target=svc.load_scenario, args=(u, "sıra"))
        loaded.start()
        _until(lambda: svc.et.queued() >= 2)                               # the load waits behind it
        assert svc.store.user_inputs(u)[("tto", "Forward!D2")] == 46371.0   # (nothing applied out of turn)
        gate.set()
        typed.join(30)
        loaded.join(30)
        blocker.result(30)
        # the write came first, the load after it: the scenario's date stands, in the store and on the page
        assert svc.store.user_inputs(u)[("tto", "Forward!D2")] == 46371.0
        assert cell(svc, "Forward!D2", u) == 46371.0
        # ... and a write sent after the load is applied after it
        assert svc.set_inputs(u, "tto", [{"ref": "Forward!D2", "value": "16.12.2026"}])["errors"] == []
        assert cell(svc, "Forward!D2", u) == 46372.0
    finally:
        svc.stop()
