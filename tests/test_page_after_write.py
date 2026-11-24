"""A page asked for while a write is being applied shows that write (``Service._wrote``).

A write is applied on the calculation thread; its writer tells the pages of the new generation afterwards, from the
request's own thread (``bump``, after the trading list's followers).  A page the browser asks for in between - the
refresh the previous write's answer started - was made from the written values but under the generation from before:
the browser had that generation, so it took the page for unchanged, and every later answer too (what they made was the
same).  The browser test's DİBS RV row move failed so (24.11.2026): the bond's ISIN blanked on its row, the server moved
its manual clean price to the bond's other row, yet the page kept the price on the old row; the ISIN typed back there
was what the page showed, so nothing was sent, and the next Delete took the bond - and its price - off the list.  Every
WRITE job now moves the generation on the calculation thread before the next job reads it.
"""
from __future__ import annotations

import threading
import time

import pytest

from conftest import cell, make_service
from tto.service import EngineThread

LIST = "DİBS RV!A5:A54"


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    """A service of its own: the trading list (the desk's) changes here."""
    s = make_service(tmp_path_factory.mktemp("data"))
    yield s
    s.stop()


def until(cond, seconds=30.0):
    end = time.time() + seconds
    while not cond():
        assert time.time() < end, "timed out"
        time.sleep(0.005)


def rows(s, user, isin):
    """The bond's row and the list's next empty row."""
    lst = s._list_values(user, "tto", LIST)
    return lst.index(isin) + 5, 5 + max(k for k, v in enumerate(lst) if v) + 1


def shown(answer, ref):
    """A cell's text in a page's answer (None: no panel of the answer has it)."""
    sheet, addr = ref.split("!")
    col, row = addr.rstrip("0123456789"), int(addr[len(addr.rstrip("0123456789")):])
    for p in answer.get("panels", []):
        d = p.get("data") or {}
        if d.get("sheet") == sheet and row in (d.get("r") or []) and col in (d.get("c") or []):
            return d["rows"][d["r"].index(row)][d["c"].index(col)].get("t")
    return None


class Browser(object):
    """DİBS RV as the browser keeps it: the cells it last drew, the generation it has them of (view.js refresh)."""

    def __init__(self, s, user):
        self.s, self.user = s, user
        first = s.view(user, "dibs")
        self.ids = [p["id"] for p in first["panels"]]
        self.gen, self.kind = first["gen"], first["as"]
        self.cells = {}
        self.took(first)

    def took(self, answer):
        """An answer drawn: its panels' cells (an unchanged answer draws nothing), the generation it is of."""
        for p in answer.get("panels", []):
            d = p.get("data") or {}
            for i, r in enumerate(d.get("r") or []):
                for j, c in enumerate(d.get("c") or []):
                    self.cells["%s!%s%d" % (d.get("sheet"), c, r)] = d["rows"][i][j].get("t")
        self.gen, self.kind = max(self.gen, answer["gen"]), answer.get("as", self.kind)
        return answer

    def ask(self):
        """What a refresh sends (since its generation, the page's panels) - a future, answered on the calculation thread."""
        return self.s.view_future(self.user, "dibs", False, None, self.gen, self.ids, None, self.kind)

    def refresh(self):
        return self.took(self.ask().result(60))

    def __getitem__(self, ref):
        return self.cells.get(ref)


def test_a_page_asked_for_between_a_write_and_its_news_shows_the_write(svc, monkeypatch):
    """The browser test's row move: a manual clean price on the bond's row, the ISIN typed into the next empty row, the
    old row's ISIN blanked - and the page asks for itself after the write was applied, before the pages are told."""
    s = svc
    u = s.login("Yazı Sonrası Sayfa")["user"]
    s.store.update_account(u, role="admin")                 # (as the browser test's: a page of their own)
    frm, to = rows(s, u, "TRT081128T15")
    page = Browser(s, u)
    assert s.set_inputs(u, "tto", [{"ref": "DİBS RV!N%d" % frm, "value": "98,5"}])["errors"] == []
    page.refresh()
    assert s.set_inputs(u, "tto", [{"ref": "DİBS RV!A%d" % to, "value": "TRT081128T15"}])["errors"] == []
    page.refresh()
    assert (page["DİBS RV!N%d" % frm], page["DİBS RV!A%d" % to]) == ("98,500", "TRT081128T15")
    assert page.ask().result(60).get("unchanged")         # (current: the browser has this generation's page)
    # the write's own thread held after the calculation thread applied it (here: before the trading list's followers
    # - in the browser it is the threads' turns that decide); the page asks in between
    applied, go = threading.Event(), threading.Event()
    follow = s._follow_trading

    def held(user, res):
        applied.set()
        assert go.wait(30)
        return follow(user, res)
    monkeypatch.setattr(s, "_follow_trading", held)
    out = {}
    writer = threading.Thread(target=lambda: out.update(
        res=s.set_inputs(u, "tto", [{"ref": "DİBS RV!A%d" % frm, "value": ""}])))
    writer.start()
    try:
        assert applied.wait(30)
        between = page.refresh()
    finally:
        go.set()
        writer.join(30)
    assert "TRT081128T15 satır %d → %d" % (frm, to) in out["res"]["row_values"]["text"]
    told = page.refresh()                                   # told of the write's generation, the page asks again
    # the page shows the move - the old row empty, the price on the bond's new row - as a page opened afresh does
    refs = ["DİBS RV!%s" % c for c in ("A%d" % frm, "N%d" % frm, "A%d" % to, "N%d" % to)]
    assert [page[r] for r in refs] == ["", "", "TRT081128T15", "98,500"]
    assert [shown(s.view(u, "dibs"), r) for r in refs] == [page[r] for r in refs]
    # ... from the page made in between: of the write's own generation, it brought the move (nothing came after it)
    assert not between.get("unchanged") and shown(between, "DİBS RV!N%d" % to) == "98,500" and told.get("unchanged")


def test_a_bond_moved_away_and_back_quickly_keeps_its_price(svc):
    """There and back as fast as the browser sends it: the old row's ISIN blanked, typed back, the new row's blanked - each
    sent before the one before is answered, while the calculation thread is busy (a page being made), the page asking
    in between.  The writes are applied in the order sent; the price is back on the bond's row, on the server and on
    the page."""
    s = svc
    u = s.login("Gidip Gelen Fiyat")["user"]
    code = next(c for c in s._list_values(u, "tto", LIST) if c and c != "TRT081128T15")
    frm, to = rows(s, u, code)
    assert s.set_inputs(u, "tto", [{"ref": "DİBS RV!N%d" % frm, "value": "97,25"}])["errors"] == []
    assert s.set_inputs(u, "tto", [{"ref": "DİBS RV!A%d" % to, "value": code}])["errors"] == []
    page = Browser(s, u)
    s.bump()                                                # (a new generation - the market - before the page asks)
    gate = threading.Event()
    busy = s.et.submit_at(EngineThread.VIEW, gate.wait, 30)
    until(lambda: s.et.busy_for() > 0)
    got, threads, asked = {}, [], [page.ask()]              # (the page's refresh waits in the queue with the writes)
    try:
        for k, (ref, value) in enumerate((("A%d" % frm, ""), ("A%d" % frm, code), ("A%d" % to, ""))):
            n = s.et.queued()
            t = threading.Thread(target=lambda k=k, ref=ref, value=value: got.__setitem__(
                k, s.set_inputs(u, "tto", [{"ref": "DİBS RV!" + ref, "value": value}])))
            t.start()
            threads.append(t)
            until(lambda: s.et.queued() > n)                # (queued before the next is sent)
        asked.append(page.ask())
    finally:
        gate.set()
    for t in threads:
        t.join(60)
    busy.result(30)
    for fut in asked:
        page.took(fut.result(60))
    # applied in the order sent - the results say so: there (its price with it) first; the last one, the other row
    # blanked, takes the price back only after the ISIN was typed back on the bond's row (else the bond would have left
    # the list, its price with it)
    told = [(got[k].get("row_values") or {}).get("text") or "" for k in range(3)]
    assert "%s satır %d → %d" % (code, frm, to) in told[0], told
    assert "%s satır %d → %d" % (code, to, frm) in told[2] and "listeden çıktı" not in told[2], told
    assert all(not got[k]["errors"] for k in range(3))
    assert cell(s, "DİBS RV!N%d" % frm, u) == 97.25 and s._list_values(u, "tto", LIST)[frm - 5] == code
    assert s._list_values(u, "tto", LIST)[to - 5] == "" and cell(s, "DİBS RV!N%d" % to, u) == ""
    # the page, following the generations as the browser does, shows it so
    s.bump()
    page.refresh()
    assert (page["DİBS RV!A%d" % frm], page["DİBS RV!N%d" % frm], page["DİBS RV!A%d" % to], page["DİBS RV!N%d" % to]) \
        == (code, "97,250", "", "")
