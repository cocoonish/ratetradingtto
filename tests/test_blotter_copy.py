"""Günlük İşlemler: "Benzerini gir" and "Ters işlem" (the desk, 23.11.2026: "one click fills the entry form from that
trade, either as a new trade or with the side reversed, for repeats and unwinds").  What the form is filled with, product
by product (``blotter.copy_specs``, on every trade listed where the form is open): the trade's terms as a new trade, or
the offsetting trade - the other side, the same size and end; a start that has passed is today's spot, a day gone by's
TRY OIS a broken date to its own maturity, priced as Fiyatlama prices one (the short period first).  Nothing is stored
until the trader saves; a trade that has run off has no offset (said why)."""
from __future__ import annotations

import datetime as dt

import pytest

from conftest import cell
from tto import blotter as bl
from tto import pricing as pr
from tto.xl.values import date_to_serial, serial_to_date

ROW = ("id", "kind", "package", "trade_date", "created_by", "created_at", "updated_by", "updated_at", "edits", "copy")


@pytest.fixture(scope="module")
def desk(module_service):
    svc = module_service
    return svc, svc.login("Kopya A")["user"]


def calendar(svc):
    """Today's OIS spot and the TRY holidays, as Fiyatlama reads them."""
    book = svc.books["tto"]
    idx = book.model.sheet_index
    return pr.read(lambda sheet, r, c: book.engine.shared.get(idx[sheet], r, c))


def days_ago(n):
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


def before_spot(mk, n):
    """The day ``n`` days before the market's OIS spot (the workbook's TODAY() + 1 business day)."""
    return (serial_to_date(mk.ois_spot) - dt.timedelta(days=n)).isoformat()


def serial(iso):
    return float(date_to_serial(dt.date.fromisoformat(iso)))


def stored(svc, tid):
    return {k: v for k, v in svc.store.trade(tid).items() if k not in ROW}


def copies(svc, user, tid, since):
    """``copy`` of a trade as the page gets it: listed over a period up to today (where the form is open)."""
    data = svc.blotter(user, since, None, svc.today_iso())
    assert data["can_enter"]
    return next(t for t in data["trades"] if t["id"] == tid)["copy"]


def back_dated(svc, user, day, tid):
    """A trade of today's kept again as one of ``day``'s (its record as it is)."""
    legs = svc.store.trade_legs(tid)
    recs = [{k: v for k, v in lg.items() if k not in ROW} for lg in legs]
    if len(recs) == 1:
        return [svc.store.add_trade(day, legs[0]["kind"], recs[0], user)]
    return svc.store.add_trades(day, legs[0]["kind"], recs, user, "old" + str(tid))


# ---------------------------------------------------------------------------------------------- the broken date itself
def test_a_broken_date_ois_is_priced_as_fiyatlama_prices_it(desk):
    """A leg to a date of its own: Fiyatlama's TRY OIS (spot to that date, quarterly back from it, the short period
    first) on Bootstrap - its mid is the page's, its annuity sizes the nominal by OIS_MAIN's rule."""
    svc, a = desk
    mk = calendar(svc)
    hol = mk.holidays["TRY"]
    end = pr.roll(pr.edate(mk.ois_spot, 10) + 9.0, hol)            # 10M and some days: a broken date
    name = bl.date_tenor(end)
    q = svc.quote_ois(a, {"strategy": "outright", "side": "PAY", "tenor": name, "level": "36,00", "dv01": "2000"})
    page = svc.pricing(a, {"asset": "ois", "start": "", "end": name, "side": "PAY", "size_kind": "dv01", "size": "2000", "price": ""})
    lg = q["legs"][0]
    assert lg["tenor"] == name and lg["role"] == "outright"
    assert q["info"]["market"] == pytest.approx(page["mid"]["boot"], abs=1e-12)
    assert lg["annuity"] == pytest.approx(page["annuity"]["boot"], abs=1e-12)
    usdtry = cell(svc, "OIS_MAIN!D2")
    lot = cell(svc, "OIS_MAIN!H2")
    assert lg["nominal"] == bl._round_half_away(2000.0 * usdtry / (lg["annuity"] * 1e-4) / lot) * lot
    assert lg["dv01"] == pytest.approx(lg["nominal"] * lg["annuity"] * 1e-4 / usdtry)
    # the schedule: quarterly back from the end, the short period first
    deal = pr.swap_deal(pr.OIS, ("spot", 0.0), ("d", end), mk)
    assert len(deal.legs) == 4 and deal.legs[0].days < deal.legs[1].days
    # a date on a holiday or a weekend ends on the next business day; a date before the spot is refused
    sat = mk.ois_spot + 300.0
    while int(sat) % 7 != 0:                                       # (serial % 7: 0 is a Saturday)
        sat += 1.0
    q2 = svc.quote_ois(a, {"strategy": "outright", "side": "PAY", "tenor": bl.date_tenor(sat), "level": "36"})
    assert q2["legs"][0]["tenor"] == bl.date_tenor(pr.roll(sat, hol))
    with pytest.raises(Exception, match="kırık vade"):
        svc.quote_ois(a, {"strategy": "outright", "side": "PAY", "tenor": bl.date_tenor(mk.ois_spot - 3.0), "level": "36"})


def test_a_spread_and_a_fra_between_broken_dates(desk):
    """A spread of two dated legs reads each leg's mid; a FRA between two dates is the two spot swaps to its dates on one
    nominal (its forward annuity), its mid Fiyatlama's FRA of those dates; from Spot, the swap to its end alone."""
    svc, a = desk
    mk = calendar(svc)
    hol = mk.holidays["TRY"]
    d1 = pr.roll(pr.edate(mk.ois_spot, 11) + 5.0, hol)
    d2 = pr.roll(pr.edate(d1, 12), hol)
    n1, n2 = bl.date_tenor(d1), bl.date_tenor(d2)
    par = lambda n: svc.pricing(a, {"asset": "ois", "start": "", "end": n})["mid"]["boot"]       # noqa: E731
    sp = svc.quote_ois(a, {"strategy": "spread", "side": "STEEPENER", "short": n1, "long": n2, "level": "10", "nominal": "100m"})
    assert [lg["tenor"] for lg in sp["legs"]] == [n1, n2]
    assert sp["info"]["market"] == pytest.approx((par(n2) - par(n1)) * 1e4, abs=1e-9)
    with pytest.raises(Exception, match="kısa vade uzun vadeden önce olmalı"):
        svc.quote_ois(a, {"strategy": "spread", "side": "STEEPENER", "short": n2, "long": n1, "level": "10"})
    fra = svc.quote_ois(a, {"strategy": "fra", "side": "PAY", "start_months": n1, "end_months": n2, "level": "35", "nominal": "200m"})
    start, end = fra["legs"]
    assert (start["role"], start["tenor"], start["dir"], end["role"], end["tenor"], end["dir"]) == ("start", n1, "S", "end", n2, "B")
    assert start["nominal"] == end["nominal"] == 200e6
    page = svc.pricing(a, {"asset": "fra", "start": n1, "end": n2})
    assert fra["info"]["market"] == pytest.approx(page["mid"]["boot"], abs=0.2e-4)      # (the same schedule but a rolled day)
    assert fra["label"] == "PAY FRA %s→%s @ 35,0000%%" % (n1, n2)
    one = svc.quote_ois(a, {"strategy": "fra", "side": "RECEIVE", "start_months": 0, "end_months": n2, "level": "35", "nominal": "200m"})
    assert [(lg["role"], lg["tenor"], lg["dir"]) for lg in one["legs"]] == [("end", n2, "S")]
    assert one["info"]["market"] == pytest.approx(par(n2), abs=1e-12)


# ---------------------------------------------------------------------------------------------- today's trades
def test_todays_trades_copy_as_entered(desk):
    """A trade of today: "Benzerini gir" its terms, no price (the form prices it on today's market); "Ters işlem" the
    other side, the same size and end."""
    svc, a = desk
    f = svc.add_forward(a, {"dir": "B", "quote_amount": "500m", "value_date": "3M", "basis": "SP", "manual": "17.400",
                            "cpt": "GARANTİ", "note": "müşteri"})
    c = copies(svc, a, f["id"], svc.today_iso())
    assert c["benzer"]["spec"] == {"kind": "fwd", "pair": "USDTRY", "dir": "B", "basis": "SP", "value": "", "spot": "",
                                   "cpt": "GARANTİ", "note": "müşteri", "quote_amount": 500e6,
                                   "date": bl.date_tenor(f["value_date"])}
    # the offset: the dollars of the trade (typed in TRY, worked out from its forward) - the position closes exactly
    assert c["ters"]["spec"] == {"kind": "fwd", "pair": "USDTRY", "dir": "S", "basis": "SP", "value": "", "spot": "", "cpt": "GARANTİ",
                                 "note": "müşteri", "amount": f["amount"], "date": bl.date_tenor(f["value_date"])}
    assert "karşı parada girilmişti" in c["ters"]["how"] and f["typed"] == "quote"
    o = svc.add_ois(a, {"strategy": "fly", "side": "REC GÖVDE", "wing1": "1Y", "body": "2Y", "wing2": "3Y", "level": "5",
                        "nominal": "100m", "cpt": "AKB"})
    c = copies(svc, a, o["ids"][0], svc.today_iso())
    want = {"kind": "ois", "strategy": "fly", "side": "REC GÖVDE", "level": "", "cpt": "AKB", "note": "", "sizeMode": "nominal",
            "size": 100e6, "tenors": ["1Y", "2Y", "3Y"]}
    assert c["benzer"]["spec"] == want and c["ters"]["spec"] == dict(want, side="PAY GÖVDE")
    s = svc.add_ois(a, {"strategy": "spread", "side": "FLATTENER", "short": "1Y", "long": "5Y", "level": "-20", "dv01": "3000"})
    c = copies(svc, a, s["ids"][0], svc.today_iso())
    assert (c["ters"]["spec"]["side"], c["ters"]["spec"]["sizeMode"], c["ters"]["spec"]["size"], c["ters"]["spec"]["tenors"]) == \
        ("STEEPENER", "dv01", 3000.0, ["1Y", "5Y"])
    r = svc.add_ois(a, {"strategy": "fra", "side": "RECEIVE", "start_months": "12", "end_months": "15", "level": "34", "nominal": "250m"})
    c = copies(svc, a, r["ids"][0], svc.today_iso())
    assert (c["ters"]["spec"]["side"], c["ters"]["spec"]["months"], c["ters"]["spec"]["size"]) == ("PAY", [12, 15], 250e6)
    b = svc.add_bond(a, {"instrument": "TRT130629T14", "dir": "B", "amount": "50m", "price": "98,25", "note": "x"})
    c = copies(svc, a, b["id"], svc.today_iso())
    assert c["benzer"]["spec"] == {"kind": "bond", "dir": "B", "instrument": "TRT130629T14", "amount": 50e6, "price": "", "note": "x"}
    assert c["ters"]["spec"] == dict(c["benzer"]["spec"], dir="S")
    # a package's copy is on its first leg listed alone
    listed = svc.blotter(a)["trades"]
    assert sum(1 for t in listed if t.get("package") == svc.store.trade(o["ids"][0])["package"] and "copy" in t) == 1


def test_a_day_gone_bys_trades_from_todays_spot(desk):
    """A day gone by's trade: its start has passed - "Benzerini gir" the same tenor from today's spot, "Ters işlem" the
    offset to its own end: a TRY OIS a broken date to its maturity (each leg of a package), a FRA still to start between
    its own dates, a FRA started a spot swap to its end, a forward its value date, a meeting swap from today's spot."""
    svc, a = desk
    mk = calendar(svc)
    hol, spot = mk.holidays["TRY"], mk.ois_spot
    day = days_ago(40)
    own_spot = pr.roll(serial(day) + 1.0, hol)                      # WORKDAY(day, 1, TRY): that day's OIS spot
    o = svc.add_ois(a, {"strategy": "outright", "side": "PAY", "tenor": "1Y", "level": "38", "nominal": "150m", "cpt": "İŞ", "note": "eski"})
    [old] = back_dated(svc, a, day, o["ids"][0])
    before = stored(svc, old)
    c = copies(svc, a, old, day)
    maturity = pr.tenor_date(own_spot, 12, hol)
    assert c["ters"]["spec"] == {"kind": "ois", "strategy": "outright", "side": "RECEIVE", "level": "", "cpt": "İŞ", "note": "eski",
                                 "sizeMode": "nominal", "size": 150e6, "tenors": [bl.date_tenor(maturity)]}
    assert "kırık vade" in c["ters"]["how"] and bl.date_tenor(spot) in c["ters"]["how"]
    assert c["benzer"]["spec"]["tenors"] == ["1Y"] and c["benzer"]["spec"]["side"] == "PAY"
    # saved: a broken-date RECEIVE to the same maturity, the same nominal - the old trade as it was
    q = svc.add_ois(a, {"strategy": "outright", "side": "RECEIVE", "tenor": c["ters"]["spec"]["tenors"][0], "level": "37,5",
                        "nominal": "150m"})
    new = svc.store.trade(q["ids"][0])
    assert (new["tenor"], new["dir"], new["nominal"], new["rate"]) == (bl.date_tenor(maturity), "S", 150e6, 0.375)
    assert stored(svc, old) == before
    # the workbook's sheet: the leg between the two main tenors around its end, by days (as a meeting swap from the spot)
    rows = [r for r in range(bl.OIS_ROWS[0], bl.OIS_ROWS[1] + 1) if cell(svc, "Günlük İşlemler!J%d" % r) == "S"
            and cell(svc, "Günlük İşlemler!K%d" % r) == pytest.approx(0.375)]
    nodes = [bl.tenor_end(cell(svc, "OIS_MAIN!B2"), x) for x in bl.SUMMARY_TENORS]
    want = [(bl.SUMMARY_TENORS[i], w) for i, w in bl.split_weights(maturity, nodes)]
    assert [(cell(svc, "Günlük İşlemler!L%d" % r), cell(svc, "Günlük İşlemler!I%d" % r) / new["dv01"]) for r in rows] == \
        [(t, pytest.approx(w)) for t, w in want]
    assert {x["key"] for x in svc.blotter(a)["cost"]["ois"]} >= {bl.date_tenor(maturity)}
    # a spread of that day: both legs to their own maturities; a forward: the same value date, its tenor again
    s = svc.add_ois(a, {"strategy": "spread", "side": "STEEPENER", "short": "1Y", "long": "2Y", "level": "15", "nominal": "80m"})
    olds = back_dated(svc, a, day, s["ids"][0])
    c = copies(svc, a, olds[0], day)
    assert c["ters"]["spec"]["tenors"] == [bl.date_tenor(pr.tenor_date(own_spot, 12, hol)), bl.date_tenor(pr.tenor_date(own_spot, 24, hol))]
    assert (c["ters"]["spec"]["side"], c["ters"]["spec"]["size"]) == ("FLATTENER", 80e6)
    assert c["benzer"]["spec"]["tenors"] == ["1Y", "2Y"]
    # a FRA still to start: between its own two dates; one started: from today's spot to its end
    r = svc.add_ois(a, {"strategy": "fra", "side": "PAY", "start_months": "6", "end_months": "9", "level": "35", "nominal": "300m"})
    [f_old, _] = back_dated(svc, a, day, r["ids"][0])
    c = copies(svc, a, f_old, day)
    assert c["ters"]["spec"]["months"] == [bl.date_tenor(pr.tenor_date(own_spot, 6, hol)), bl.date_tenor(pr.tenor_date(own_spot, 9, hol))]
    assert (c["ters"]["spec"]["side"], c["ters"]["spec"]["size"]) == ("RECEIVE", 300e6) and c["benzer"]["spec"]["months"] == [6, 9]
    # (run off or started against the market's day - the workbook's OIS spot: in replay the file's, not the clock's)
    gone, started = before_spot(mk, 130), before_spot(mk, 100)
    r = svc.add_ois(a, {"strategy": "fra", "side": "PAY", "start_months": "0", "end_months": "3", "level": "35", "nominal": "300m"})
    [f_spot] = back_dated(svc, a, gone, r["ids"][0])
    c = copies(svc, a, f_spot, gone)
    assert c["ters"] == {"why": "vadesi geldi (%s): kapatılacak swap kalmadı" % bl.date_tenor(pr.tenor_date(pr.roll(serial(gone) + 1, hol), 3, hol))}
    assert c["benzer"]["spec"]["months"] == [0, 3]                  # (the same FRA again from today's spot)
    r = svc.add_ois(a, {"strategy": "fra", "side": "PAY", "start_months": "3", "end_months": "6", "level": "35", "nominal": "300m"})
    [f_on, _] = back_dated(svc, a, started, r["ids"][0])
    c = copies(svc, a, f_on, started)
    e = pr.tenor_date(pr.roll(serial(started) + 1, hol), 6, hol)
    assert c["ters"]["spec"]["months"] == [0, bl.date_tenor(e)] and "kırık vade" in c["ters"]["how"]


def test_a_day_gone_bys_forward_and_meeting_swap(desk):
    svc, a = desk
    mk = calendar(svc)
    day = days_ago(20)
    f = svc.add_forward(a, {"dir": "S", "amount": "7m", "value_date": "6M", "basis": "RET_MID", "cpt": "X"})
    [old] = back_dated(svc, a, day, f["id"])
    # (kept as entered 20 days ago: its value date 6 months from that day's spot)
    from tto.history import add_months
    spot_then = mk.fx_spot - 20.0
    vd = float(date_to_serial(add_months(serial_to_date(spot_then), 6)))
    svc.store.update_trades([(old, dict(stored(svc, old), value_date=vd, days=vd - spot_then))], a)
    c = copies(svc, a, old, day)
    assert (c["benzer"]["spec"]["date"], c["benzer"]["spec"]["dir"], c["benzer"]["spec"]["amount"]) == ("6M", "S", 7e6)
    assert (c["ters"]["spec"]["date"], c["ters"]["spec"]["dir"], c["ters"]["spec"]["amount"]) == (bl.date_tenor(vd), "B", 7e6)
    # its value date come: no offset, said why
    svc.store.update_trades([(old, dict(stored(svc, old), value_date=mk.fx_spot - 1.0, days=150.0))], a)
    c = copies(svc, a, old, day)
    assert c["ters"] == {"why": "valörü geldi (%s): kapatılacak forward kalmadı" % bl.date_tenor(mk.fx_spot - 1.0)}
    assert c["benzer"]["spec"]["date"] == bl.date_tenor(mk.fx_spot + 150.0)       # (no whole tenor: the same days on)
    # a meeting swap: its own dates while its start is to come; started, from today's spot to its end; ended, none
    m = svc.ois_market(a)["mpc"]
    d1, d2 = m["dates"][0]["date"], m["dates"][1]["date"]
    q = svc.add_ois(a, {"strategy": "mpc", "side": "PAY", "start": d1, "end": d2, "level": "38", "nominal": "100m"})
    [mo] = back_dated(svc, a, day, q["ids"][0])
    assert copies(svc, a, mo, day)["ters"]["spec"]["start"] == d1
    svc.store.update_trades([(mo, dict(stored(svc, mo), mpc={"start": mk.ois_spot - 10.0, "end": d2, "days": d2 - mk.ois_spot + 10.0}))], a)
    c = copies(svc, a, mo, day)
    assert (c["ters"]["spec"]["start"], c["ters"]["spec"]["end"], c["ters"]["spec"]["side"]) == (mk.ois_spot, d2, "RECEIVE")
    assert (c["benzer"]["spec"]["start"], c["benzer"]["spec"]["side"]) == (mk.ois_spot, "PAY")
    svc.store.update_trades([(mo, dict(stored(svc, mo), mpc={"start": mk.ois_spot - 40.0, "end": mk.ois_spot - 5.0, "days": 35.0}))], a)
    c = copies(svc, a, mo, day)
    assert c == {"benzer": {"why": "dönemi bitti (%s)" % bl.date_tenor(mk.ois_spot - 5.0)},
                 "ters": {"why": "dönemi bitti (%s)" % bl.date_tenor(mk.ois_spot - 5.0)}}


def test_no_copy_where_the_form_is_closed_and_nothing_stored(desk):
    """A day gone by on its own (the form closed): no ``copy``; listing it never writes a trade."""
    svc, a = desk
    day = days_ago(3)
    o = svc.add_ois(a, {"strategy": "outright", "side": "PAY", "tenor": "2Y", "level": "36", "nominal": "50m"})
    [old] = back_dated(svc, a, day, o["ids"][0])
    data = svc.blotter(a, day)
    assert not data["can_enter"] and all("copy" not in t for t in data["trades"])
    assert "copy" not in svc.store.trade(old)
    copies(svc, a, old, day)
    assert "copy" not in svc.store.trade(old)


def test_the_tenor_of_a_forward():
    spot = float(date_to_serial(dt.date(2026, 11, 4)))
    vd = float(date_to_serial(dt.date(2027, 2, 4)))
    assert bl.fwd_tenor({"value_date": vd, "days": vd - spot}) == "3M"
    assert bl.fwd_tenor({"value_date": vd + 3.0, "days": vd + 3.0 - spot}) == "3M"           # (rolled over a weekend)
    assert bl.fwd_tenor({"value_date": vd + 9.0, "days": vd + 9.0 - spot}) is None
    assert bl.fwd_tenor({"value_date": spot + 14.0, "days": 14.0}) == "2W"
    assert bl.date_tenor(vd) == "04.02.2027" and bl.tenor_date_of("04.02.2027") == vd and bl.tenor_date_of("1Y") is None
