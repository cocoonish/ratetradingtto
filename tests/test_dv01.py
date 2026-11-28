"""DV01: the risk sheet opens without a position; the VİOP matrix shows each DV01 in its own currency.

DV01 Risk, the desk's decisions of 28.11.2026 ("A - Yildizlilari yap. B - Hepsini yap. C - 2-3-4-5-8-10-12-13-16"; to
"Pozisyon (C6:C25) varsayılanı Onshore mu, Onshore + TLREF mi?": "Onshore + tlref"): the Pozisyon tab's bucket DV01s
default to the paste area's Onshore + TLREF, a typed value wins (A8); when the position was pasted, red when not today
(A8: the pinned Parametreler, Bugün); "Hedge'i işle" - the hedge recommender's rows as Günlük İşlemler's OIS paste - and
its prices right-clicked (A3); the page's one-line summary, pinned (B13)."""
from __future__ import annotations

import datetime as _dt

import pytest

from conftest import cell, make_service
from tto import extras as ex
from tto import tradehint as th
from tto import varrisk as vr
from tto.xl.model import COLS, a1, parse_range


def test_the_dv01_risk_sheet_opens_without_a_position(service):
    """The file keeps the desk's positions of the day it was saved: the sheet opens without one instead - the paste area
    empty (where to paste), the bucket DV01s at zero (their default: the paste's Onshore + TLREF) - and what a user types
    or pastes is theirs."""
    r1, c1, r2, c2 = parse_range("X33:Y52")
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            assert cell(service, "DV01_RISK!%s" % a1(r * COLS + c)) is None, (r, c)
    for r in range(6, 26):
        assert cell(service, "DV01_RISK!C%d" % r) == 0.0, r
    u = service.login("DV01 Pozisyon")["user"]
    try:
        service.set_inputs(u, "tto", [{"ref": "DV01_RISK!C11", "value": "176474"}])
        assert cell(service, "DV01_RISK!C11", u) == 176474.0 and cell(service, "DV01_RISK!C11") == 0.0
    finally:
        service.reset_inputs(u, "tto")
    assert cell(service, "DV01_RISK!C11", u) == 0.0


def test_the_viop_matrix_shows_each_dv01_in_its_own_currency(service):
    """Per 1 mn USD: the TRY rate's bp in TL and in USD (at the contract's price, the forward of its maturity),
    the USD rate's bp in USD - the workbook showed it in TL."""
    assert [cell(service, "VIOP!K%d" % r) for r in (107, 108, 109)] == ["DV01 TRY (TL)", "DV01 TRY (USD)", "DV01 USD (USD)"]
    for col in ex.VIOP_DV01_COLS:
        days, bid, ask, usd = (cell(service, "VIOP!%s%d" % (col, r)) for r in (98, 99, 100, 101))
        mid = (bid + ask) / 2
        try_tl, try_usd, usd_usd = (cell(service, "VIOP!%s%d" % (col, r)) for r in (107, 108, 109))
        assert try_tl > 0 > usd_usd and try_usd == pytest.approx(try_tl / mid), col
        assert usd_usd == pytest.approx(-100 * (days / 360) / (1 + usd * days / 360)), col
        # the USD bp as the workbook had it (in TL, at the contract's price) is the same figure at that price
        assert usd_usd * mid == pytest.approx(-100 * mid * (days / 360) / (1 + usd * days / 360)), col
    panel = next(p for p in service.view(None, "viop", True)["panels"] if p["id"] == "B14")
    assert panel["range"] == "K97:X109" and panel["data"]["r"][-1] == 109


# ---------------------------------------------------------------------------------------------- A8: Pozisyon's default
@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    s = make_service(tmp_path_factory.mktemp("dv01"))
    yield s
    s.stop()


def _paste(s, user, col, values):
    s.set_inputs(user, "tto", [{"ref": "DV01_RISK!%s%d" % (col, ex.VAR_FIRST + i), "value": str(v)} for i, v in enumerate(values)])


ONSHORE = [10000.0 * (i + 1) for i in range(20)]
TLREF = [-3000.0 * (i + 2) for i in range(20)]


def test_pozisyon_defaults_to_onshore_plus_tlref_a_typed_value_wins(svc):
    """C6:C25 = Z33:Z52 = X + Y, bucket for bucket (the same 20 buckets: ON ↔ O/N …); a value typed into C stands, the
    others keep following the paste; Delete takes it back; another user's paste is theirs alone; nothing flows the other
    way - the Onshore + OIS VaR book reads the paste, never C."""
    u, v = svc.login("A8 Pozisyon")["user"], svc.login("A8 Başkası")["user"]
    assert [cell(svc, "DV01_RISK!B%d" % r) for r in range(6, 26)] == ex.dv01_bucket_labels()
    assert [cell(svc, "DV01_RISK!W%d" % r) for r in range(33, 53)] == list(ex.VAR_BUCKETS)
    _paste(svc, u, "X", ONSHORE)
    _paste(svc, u, "Y", TLREF)
    for i in range(20):
        assert cell(svc, "DV01_RISK!C%d" % (6 + i), u) == pytest.approx(ONSHORE[i] + TLREF[i]), i
    assert cell(svc, "DV01_RISK!C26", u) == pytest.approx(sum(ONSHORE) + sum(TLREF))     # (Toplam, × C3 = 1)
    assert cell(svc, "DV01_RISK!C6", v) == 0.0 and cell(svc, "DV01_RISK!C6") == 0.0       # (theirs alone)
    svc.set_inputs(u, "tto", [{"ref": "DV01_RISK!C11", "value": "176474"}])
    assert cell(svc, "DV01_RISK!C11", u) == 176474.0 and cell(svc, "DV01_RISK!C12", u) == pytest.approx(ONSHORE[6] + TLREF[6])
    assert cell(svc, "DV01_RISK!Z38", u) == pytest.approx(ONSHORE[5] + TLREF[5])          # (the paste is not changed by C)
    svc.reset_inputs(u, "tto", ["DV01_RISK!C11"])
    assert cell(svc, "DV01_RISK!C11", u) == pytest.approx(ONSHORE[5] + TLREF[5])
    # the how-to above Özet says so; the workbook's own words are gone only where the addition put its own
    assert "Onshore + TLREF" in cell(svc, "DV01_RISK!B2") and cell(svc, "DV01_RISK!B2") == ex.DV01_HOWTO
    svc.reset_inputs(u, "tto")


def test_the_default_needs_the_workbooks_buckets(tmp_path):
    """A workbook whose bucket table does not line up with the paste area keeps C as it is (the addition left out)."""
    import os
    from tto.books import remove_sheets
    from tto.xl.model import Model, parse_a1
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    model = Model.load(os.path.join(root, "models", "tto.json.gz"))
    remove_sheets("tto", model)
    model.sheet("DV01_RISK").consts[parse_a1("B10")] = "4W"
    left = ex.apply("tto", model)
    assert any(x.startswith(ex.DV01_DEFAULT_NAME + ":") for x in left), left
    assert parse_a1("C6") not in model.sheet("DV01_RISK").fml


# ---------------------------------------------------------------------------------------------- A8: when it was pasted
def test_when_the_position_was_pasted_red_when_not_today(svc):
    """The pinned Parametreler's last cell says when the user last wrote their position (the paste area's Onshore / TLREF
    and Offshore, or C typed over): "yapıştırıldı 28.11 09:12" from ``user_inputs.updated_at``, red when not today;
    "yapıştırma yok" before any; Bugün's Kontrol says the same."""
    u = svc.login("A8 Saat")["user"]
    svc.reset_inputs(u, "tto")

    def last(user):
        page = svc.view(user, "dv01")
        data = next(p for p in page["panels"] if p["id"] == "B2")["data"]
        assert data["c"][-1] == "Yapıştırma" and data["added"] == 1
        return data["rows"][0][-1]

    none = last(u)
    assert none["t"] == "yapıştırma yok" and none.get("c") == "mute" and vr.paste_stamp(svc.store, u, "2026-11-28")["at"] is None
    _paste(svc, u, "AA", [5000.0] * 20)
    now = _dt.datetime.now()
    got = last(u)
    assert got["t"] == "yapıştırıldı %s" % now.strftime("%d.%m %H:%M") or got["t"].startswith("yapıştırıldı %s" % now.strftime("%d.%m"))
    assert "c" not in got
    k = svc.bugun.view(u)["kontrol"]["dv01"]
    assert k["today"] and k["text"] == got["t"]
    # yesterday's paste (the stamp the store keeps): red, on Bugün "bugün değil"
    with svc.store._lock:
        svc.store._db.execute("UPDATE user_inputs SET updated_at=? WHERE user=? AND book='tto'", ("2026-11-27 17:45:10", u))
    svc.bump()                                             # (a page is read again at the next generation: the day turns so)
    got = last(u)
    assert got["t"] == "yapıştırıldı 27.11 17:45" and got["c"] == "neg"
    k = svc.bugun.view(u)["kontrol"]["dv01"]
    assert not k["today"] and k["at"] == "2026-11-27 17:45:10"
    # a typed bucket DV01 counts too; another user's paste does not
    svc.set_inputs(u, "tto", [{"ref": "DV01_RISK!C7", "value": "1000"}])
    assert "c" not in last(u)
    other = svc.login("A8 Saat Başkası")["user"]
    assert vr.paste_stamp(svc.store, other, now.date().isoformat())["at"] is None
    svc.reset_inputs(u, "tto")
    assert last(u)["t"] == "yapıştırma yok"


# ---------------------------------------------------------------------------------------------- A3: Hedge'i işle
def _row(name, start, end, side, nominal, rate=0.355, dv01=-12345.0, active=1.0, f=0.0, g=365.0):
    return {"name": name, "active": active, "start": start, "end": end, "f": f, "g": g, "rate": rate, "dv01": dv01,
            "side": side, "nominal": nominal}


def test_the_hedge_as_an_ois_paste():
    """An active instrument with a side and a rounded nominal is a line - a spot start by its tenor, a forward start (an
    FRA of the recommender) as an OIS between its two dates from the spot -, at the curve's rate (per cent, the user's
    number format), its nominal without sign, a note naming it; the others are left out (inactive, "–") or said (no
    nominal)."""
    spot = 46330.0                                         # 04.11.2026
    rows = [_row("OIS 1M", 0.0, 1.0, "RECEIVE", -2.5e8, rate=0.3637), _row("OIS 2M", 0.0, 2.0, "PAY", 1e8, active=0.0),
            _row("OIS 18M", 0.0, 18.0, "PAY", 3.75e8, rate=0.35585), _row("OIS 9M", 0.0, 9.0, "–", 0.0),
            _row("FRA 3x6", 3.0, 6.0, "PAY", 1.2e9, rate=0.3412, f=92.0, g=181.0), _row("OIS 3Y", 0.0, 36.0, "RECEIVE", 0.0),
            _row("OIS 1Y", 0.0, 12.0, "RECEIVE", 5e7, active="1")]
    got = vr.hedge_paste(rows, spot, "tr")
    lines = [x.split("\t") for x in got["text"].split("\n")]
    assert lines[0] == list(vr.HEDGE_HEAD) and got["kind"] == "ois" and got["taken"] == 4 and got["skipped"] == ["OIS 3Y"]
    assert lines[1][:6] == ["RECEIVE", "1M", "", "", "36,3700", "250.000.000"]
    assert lines[2][:6] == ["PAY", "18M", "", "", "35,5850", "375.000.000"]
    assert lines[3][:6] == ["PAY", "", "04.02.2027", "04.05.2027", "34,1200", "1.200.000.000"]
    assert "FRA 3x6" in lines[3][6] and "iki tarih arası" in lines[3][6] and "DV01 -12.345 TL/bp" in lines[1][6]
    assert lines[4][:2] == ["RECEIVE", "1Y"]
    assert "OIS 3Y" in got["said"]
    en = vr.hedge_paste(rows[:1], spot, "en")["text"].split("\n")[1].split("\t")
    assert en[4:6] == ["36.3700", "250,000,000"]
    empty = vr.hedge_paste([_row("OIS 1M", 0.0, 1.0, "–", 0.0)], spot)
    assert empty["taken"] == 0 and empty["text"] == "" and "işlenecek satır yok" in empty["said"]


def test_hedge_islem_reads_the_users_recommender_and_the_dialog_takes_it(svc):
    """The service reads the user's own recommender (their position, their instruments) and the paste dialog's preview
    takes every line: outrights by tenor, an FRA as a two-date OIS."""
    u = svc.login("A3 Hedge")["user"]
    _paste(svc, u, "X", ONSHORE)
    _paste(svc, u, "Y", TLREF)
    svc.set_inputs(u, "tto", [{"ref": "DV01_RISK!C101", "value": "1"}])       # FRA 3x6 on as well
    got = svc.dv01_hedge(u)
    assert got["kind"] == "ois" and got["taken"] >= 2
    lines = [x.split("\t") for x in got["text"].split("\n")[1:]]
    tenors = [x[1] for x in lines if x[1]]
    assert "1Y" in tenors and all(t in ("1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "5Y", "10Y") for t in tenors)
    for line in lines:
        assert line[0] in ("PAY", "RECEIVE") and line[5].replace(".", "").isdigit()
    fra = [x for x in lines if not x[1]]
    assert fra and fra[0][2] and fra[0][3]
    prev = svc.bulk_preview(u, "ois", got["text"])
    assert prev["valid"] == len(lines) and not prev["invalid"], [r.get("error") for r in prev["rows"]]
    # nothing active: said why, no text
    svc.set_inputs(u, "tto", [{"ref": "DV01_RISK!C%d" % r, "value": "0"} for r in range(ex.HEDGE_FIRST, ex.HEDGE_LAST + 1)])
    none = svc.dv01_hedge(u)
    assert none["taken"] == 0 and none["text"] == ""
    svc.reset_inputs(u, "tto")


def test_the_recommenders_prices_take_a_right_click(svc):
    """The table's "İşlem gir" (its ``trade`` hint): a spot-start instrument's rate is an OIS outright of its tenor (the
    helper column the hint reads), a forward start says it is no OIS tenor; the page sends the header's action."""
    u = svc.login("A3 İşlem gir")["user"]
    page = svc.view(u, "dv01")
    b14 = next(p for p in page["panels"] if p["id"] == "B14")
    assert b14["action"] == "hedge-islem" and b14["data"]["trade"] == {"view": "dv01", "panel": "B14", "cells": {"J": ""},
                                                                      "first": ex.HEDGE_FIRST, "last": ex.HEDGE_LAST}
    view = svc.view_index["dv01"]
    assert th.check(next(p for p in view["panels"] if p["id"] == "B14")["trade"]) == []
    assert [cell(svc, "DV01_RISK!%s%d" % (ex.HEDGE_TENOR_COL, r), u) for r in range(88, 99)] == \
        ["1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "5Y", "10Y"]
    got = svc.trade_prefill(u, {"view": "dv01", "panel": "B14", "row": 93, "col": "J", "text": "35,55%"})["spec"]
    assert got["kind"] == "ois" and got["strategy"] == "outright" and got["tenors"] == ["1Y"] and got["level"] == "35,55%"
    with pytest.raises(Exception) as err:
        svc.trade_prefill(u, {"view": "dv01", "panel": "B14", "row": 101, "col": "J", "text": "34,12%"})
    assert "OIS vadesi değil" in str(err.value)


# ---------------------------------------------------------------------------------------------- B13: the summary line
def test_the_pinned_summary_line(svc):
    """Beside the parameters on every tab: par DV01, TLREF yolu, VaR Onshore + OIS and Offshore, hedge sonrası Σ|risk|,
    açıklanamayan P&L - each the cell its own tab shows."""
    u = svc.login("B13 Özet")["user"]
    _paste(svc, u, "X", ONSHORE)
    svc.set_inputs(u, "tto", [{"ref": "DV01_RISK!C140", "value": "-2,5m"}])
    page = svc.view(u, "dv01")
    assert page["pinned"] == ["B2", "S1"]
    data = next(p for p in page["panels"] if p["id"] == "S1")["data"]
    heads = [c.get("t") for c in data["rows"][0]]
    assert heads == [c[0] for c in ex.DV01_SUMMARY_CELLS]
    for k, src in enumerate(("C29", "C30", "Y59", "Y56", "D108", "C142")):
        assert cell(svc, "DV01_RISK!%s148" % "BCDEFG"[k], u) == cell(svc, "DV01_RISK!%s" % src, u), src
    assert cell(svc, "DV01_RISK!E148", u) == "pozisyon yok"                     # (no offshore paste)
    assert cell(svc, "DV01_RISK!B148", u) == pytest.approx(sum(ONSHORE))
    svc.reset_inputs(u, "tto")
