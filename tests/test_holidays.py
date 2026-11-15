"""TRY, USD and EUR holiday lists, and FX value dates on the holidays of both currencies of the pair.

TRY is the workbook's own list (Motor!A361:B523; DİBS ASW keeps a copy).  USD (the Federal Reserve's holidays: the days
New York does not settle FX) and EUR (TARGET2's closing days) are lists of the dashboard's own on ``EK_TATIL``, from
their rules for 2020-2040 to start with, edited by the desk.  USDTRY spot is a business day of both TRY and USD after
today, EURTRY spot two days that are business days of both TRY and EUR; their tenors roll to the next day both are open.
Money market, bond, VİOP and OIS dates stay on the TRY list alone.

The days are known ones: Thanksgiving (26.11.2026), Good Friday and Easter Monday (03.04 and 06.04.2026), 4 July 2026 on
a Saturday, Veterans Day (11.11.2026), Cumhuriyet Bayramı (29.10.2026).  The service runs on the workbook's recorded
market on a clock set to the day of each check."""
from __future__ import annotations

import datetime as dt
import types

import pytest

from conftest import auth, cell, make_service
from tto import extras as ex
from tto import fx
from tto.config import Settings
from tto.service import EngineThread, Service, ServiceError
from tto.xl.engine import Clock
from tto.xl.values import date_to_serial, serial_to_date

D = dt.date
RECORDED = D(2026, 11, 3)


def day_of(svc, ref):
    v = cell(svc, ref)
    return serial_to_date(v) if type(v) is float else v


def on(svc, day):
    """The dashboard on ``day`` (at noon): TODAY() and everything that follows it computed again."""
    svc.books["tto"].engine.clock.fixed = float(date_to_serial(day)) + 0.5
    svc.et.call_at(EngineThread.WRITE, lambda: [b.engine.clock_tick() for b in svc.books.values()])
    svc.bump()


def tenor(svc, text, pair="USDTRY"):
    v = svc.et.call(svc._tenor_date, text, pair)
    return serial_to_date(v) if v is not None else None


@pytest.fixture(scope="module")
def desk(tmp_path_factory):
    """A service on the recorded market whose clock the tests move (``on``)."""
    svc = Service(Settings(data_dir=str(tmp_path_factory.mktemp("tatil")), mode="replay", history=False),
                  clock=Clock(float(date_to_serial(RECORDED)) + 0.5))
    yield svc
    svc.stop()


# ---------------------------------------------------------------------------------------------- the rules
def test_the_usd_list_is_the_feds_holidays():
    usd = dict(ex.usd_holidays(2020, 2040))
    assert len(usd) == 212 and all(d.weekday() < 5 for d in usd)                      # no weekend day
    days2026 = sorted(d for d in usd if d.year == 2026)
    assert days2026 == [D(2026, 1, 1), D(2026, 1, 19), D(2026, 2, 16), D(2026, 5, 25), D(2026, 6, 19), D(2026, 9, 7),
                        D(2026, 10, 12), D(2026, 11, 11), D(2026, 11, 26), D(2026, 12, 25)]
    assert usd[D(2026, 11, 26)] == "Thanksgiving" and usd[D(2026, 11, 11)] == "Veterans Day"
    assert D(2026, 4, 3) not in usd                                          # Good Friday: New York settles
    assert D(2026, 7, 3) not in usd and D(2026, 7, 4) not in usd             # 4 July on a Saturday: Friday stays open
    assert usd[D(2027, 7, 5)] == "Independence Day (gözlenen)"               # ... on a Sunday: the Monday after is closed
    assert usd[D(2022, 12, 26)] == "Noel (gözlenen)" and usd[D(2023, 1, 2)] == "Yılbaşı (gözlenen)"
    assert D(2021, 12, 31) not in usd                                        # 1 Ocak 2022 was a Saturday
    assert usd[D(2022, 6, 20)] == "Juneteenth (gözlenen)" and not any(d.month == 6 and d.day in (18, 19) for d in usd if d.year == 2021)
    assert ex.usd_holidays(2026, 2026) == sorted(ex.usd_holidays(2026, 2026))   # in date order


def test_the_eur_list_is_target2s_closing_days():
    eur = dict(ex.eur_holidays(2020, 2040))
    assert len(eur) == 98 and all(d.weekday() < 5 for d in eur)
    assert sorted(d for d in eur if d.year == 2026) == [D(2026, 1, 1), D(2026, 4, 3), D(2026, 4, 6), D(2026, 5, 1), D(2026, 12, 25)]
    assert eur[D(2026, 4, 3)] == "Good Friday" and eur[D(2026, 4, 6)] == "Easter Monday"     # (26.12.2026 is a Saturday)
    assert sorted(d for d in eur if d.year == 2027) == [D(2027, 1, 1), D(2027, 3, 26), D(2027, 3, 29)]   # 1 May, 25-26 Dec: weekend
    assert [ex.easter(y) for y in (2024, 2025, 2026, 2027, 2038)] == [D(2024, 3, 31), D(2025, 4, 20), D(2026, 4, 5), D(2027, 3, 28),
                                                                      D(2038, 4, 25)]


def test_which_pairs_have_a_joint_calendar():
    assert ex.pair_calendar("USDTRY") == ("USD", "TRY") and ex.pair_calendar("eurtry") == ("EUR", "TRY")
    assert ex.pair_calendar("EURUSD") == ("EUR", "USD")
    assert ex.pair_calendar("GBPTRY") == () == ex.pair_calendar("USDJPY") == ex.pair_calendar("TRYTRY")
    # a file the holiday sheet does not fit: the TRY list, as before
    assert ex.fx_holidays(types.SimpleNamespace(sheet_index={}), "USDTRY") == ex.TRY_HOLIDAYS == "Motor!$A$361:$A$523"


# ---------------------------------------------------------------------------------------------- the sheet
def test_the_holiday_sheet_holds_both_lists_and_the_spot_dates_read_them(desk):
    svc = desk
    on(svc, RECORDED)
    assert svc.books["tto"].left_out == []
    first = ex.HOL_FIRST
    usd, eur = ex.usd_holidays(*ex.HOL_YEARS), ex.eur_holidays(*ex.HOL_YEARS)
    assert [day_of(svc, "EK_TATIL!B%d" % (first + k)) for k in range(len(usd))] == [d for d, _ in usd]
    assert [cell(svc, "EK_TATIL!A%d" % (first + k)) for k in range(3)] == ["Yılbaşı", "Martin Luther King Day", "Presidents' Day"]
    assert [day_of(svc, "EK_TATIL!D%d" % (first + k)) for k in range(len(eur))] == [d for d, _ in eur]
    assert cell(svc, "EK_TATIL!B%d" % (first + len(usd))) is None and cell(svc, "EK_TATIL!D%d" % (first + len(eur))) is None
    # the copy of the TRY list between them: 29.10.2026 first, a 0 for an empty row
    assert day_of(svc, "EK_TATIL!C%d" % first) == D(2026, 10, 29) == day_of(svc, "Motor!A361")
    assert cell(svc, "EK_TATIL!C%d" % (first + 162)) == 0.0 and cell(svc, "EK_TATIL!C%d" % (first + 163)) is None
    # the spot dates are the dashboard's own; Bloomberg's (a date as text offline) stands beside each
    assert day_of(svc, "Forward!I2") == D(2026, 11, 4) and cell(svc, "Forward!J2") == "4.11.2026"
    assert day_of(svc, "Forward!K2") == D(2026, 11, 5) and cell(svc, "Forward!L2") == "5.11.2026"
    page = svc.view(None, "forward")
    strip = next(p for p in page["panels"] if p["id"] == "B1")
    assert strip["data"]["c"] == ["C", "D", "F", "G", "I", "J", "K", "L"]
    assert [c["t"] for c in strip["data"]["rows"][0]] == ["", "Valör tarihi", "USDTRY spot", "EURTRY spot", "USDTRY spot valörü",
                                                          "Bloomberg valörü", "EURTRY spot valörü", "Bloomberg valörü"]
    assert [c["t"] for c in strip["data"]["rows"][1]][4:] == ["04.11.2026", "4.11.2026", "05.11.2026", "5.11.2026"]
    hol = svc.holidays()
    assert hol["ccys"] == ["TRY", "USD", "EUR"] and hol["tr"] == hol["lists"]["TRY"]["items"] and len(hol["tr"]) == 152
    assert [(len(hol["lists"][c]["items"]), hol["lists"][c]["slots"], hol["lists"][c]["books"]) for c in ("USD", "EUR")] == \
        [(212, ex.HOL_ROWS, ["tto"]), (98, ex.HOL_ROWS, ["tto"])]
    assert {"date": "2026-11-26", "name": "Thanksgiving"} in hol["lists"]["USD"]["items"]
    assert {"date": "2026-04-06", "name": "Easter Monday"} in hol["lists"]["EUR"]["items"]
    assert hol["us"][:2] == ["2026-01-01", "2026-01-19"]                     # SIFMA (the USD workbook's), as before


# ---------------------------------------------------------------------------------------------- spot dates
@pytest.mark.parametrize("trade, spot", [
    (D(2026, 11, 24), D(2026, 11, 25)),
    (D(2026, 11, 25), D(2026, 11, 27)),          # T+1 is Thanksgiving: a TRY business day, no USD settlement
    (D(2026, 10, 28), D(2026, 10, 30)),          # 29.10 Cumhuriyet Bayramı
    (D(2026, 4, 2), D(2026, 4, 3)),              # Good Friday: USDTRY settles
    (D(2026, 7, 2), D(2026, 7, 3)),              # 4 July is a Saturday: the Fed is open on Friday 03.07
    (D(2026, 11, 10), D(2026, 11, 12)),          # Veterans Day
    (D(2026, 12, 31), D(2027, 1, 4)),            # 1 Ocak and the weekend
])
def test_usdtry_spot_is_the_next_business_day_of_both_try_and_usd(desk, trade, spot):
    on(desk, trade)
    assert day_of(desk, "Forward!I2") == spot
    assert desk.fx.spot_date(desk.fx.pair("USDTRY")) == spot              # the FX page counts the same way


@pytest.mark.parametrize("trade, spot", [
    (D(2026, 4, 1), D(2026, 4, 7)),              # Good Friday and Easter Monday: TARGET2 is closed
    (D(2026, 11, 24), D(2026, 11, 26)),          # Thanksgiving does not matter for EURTRY
    (D(2026, 10, 27), D(2026, 10, 30)),          # 29.10 Cumhuriyet Bayramı
    (D(2026, 12, 23), D(2026, 12, 28)),          # Noel (26.12 is a Saturday)
])
def test_eurtry_spot_is_two_business_days_of_both_try_and_eur(desk, trade, spot):
    on(desk, trade)
    assert day_of(desk, "Forward!K2") == spot
    assert desk.fx.spot_date(desk.fx.pair("EURTRY")) == spot


def test_the_money_market_and_bond_dates_stay_on_the_try_list(desk):
    """The bonds' T+1 value date and the TRY OIS spot (Bloomberg's, recorded) do not move for a US holiday."""
    on(desk, D(2026, 11, 25))
    assert day_of(desk, "Forward!I2") == D(2026, 11, 27)
    assert day_of(desk, "DİBS RV!D2") == D(2026, 11, 26)                   # WORKDAY(TODAY(),1,Motor!A361:A523)
    assert day_of(desk, "OIS_MAIN!B2") == D(2026, 11, 4)                   # (recorded: Bloomberg's, unchanged)


# ---------------------------------------------------------------------------------------------- tenors
def test_usdtry_tenors_roll_over_a_usd_holiday(desk):
    """Spot Monday 26.10.2026: one month on is Thanksgiving - every USDTRY date of the workbook and of the dashboard
    takes Friday 27.11; a pair without a joint calendar keeps the TRY list (26.11)."""
    on(desk, D(2026, 10, 23))
    assert day_of(desk, "Forward!I2") == D(2026, 10, 26)
    thanksgiving_after = D(2026, 11, 27)
    for ref in ("MASA!P94", "EK_FWD!B5", "Forward!B200", "EK_FWD!B%d" % (ex.FR_TENOR + 3 + 2)):     # (the tenor table's 1M row)
        assert day_of(desk, ref) == thanksgiving_after, ref
    assert cell(desk, "EK_FWD!A%d" % (ex.FR_TENOR + 3 + 2)) == "1M"
    assert tenor(desk, "1M") == thanksgiving_after
    assert desk.quote_forward("Tatil Fiyat", {"value_date": "1M", "basis": "RET_MID"})["value_date_iso"] == "2026-11-27"
    assert tenor(desk, "1M", "GBPTRY") == D(2026, 11, 26)
    assert desk.fx.curve(None, desk.fx.pair("USDTRY"))["tenors"]["1M"]["date"] == thanksgiving_after
    assert day_of(desk, "MASA!C171") == D(2028, 4, 26) and tenor(desk, "18M") == D(2028, 4, 26)


def test_eurtry_tenors_roll_over_target2_holidays_and_usdtry_settles_on_good_friday(desk):
    """Monday 02.03.2026: USDTRY spot 03.03 - one month on is Good Friday, a USD settlement day; EURTRY spot 04.03 -
    one month on is a Saturday, and the Monday after Easter Monday: 07.04."""
    on(desk, D(2026, 3, 2))
    assert day_of(desk, "Forward!I2") == D(2026, 3, 3) and day_of(desk, "Forward!K2") == D(2026, 3, 4)
    assert tenor(desk, "1M") == D(2026, 4, 3) == day_of(desk, "MASA!P94") == day_of(desk, "EK_FWD!B5")
    assert tenor(desk, "1M", "EURTRY") == D(2026, 4, 7) == day_of(desk, "EK_FWD!B%d" % ex.FWD_EUR_ROWS[0])
    assert tenor(desk, "1M", "eur") == D(2026, 4, 7)                          # the pair as typed into the blotter
    cross = desk.fx.curve(None, desk.fx.pair("EURTRY"))
    assert cross["spot_date"] == D(2026, 3, 4) and cross["tenors"]["1M"]["date"] == D(2026, 4, 7)
    assert cross["tenors"]["1M"]["days"] == 34.0
    on(desk, D(2026, 2, 27))                                                  # Friday: EURTRY spot 03.03, 1M is Good Friday
    assert tenor(desk, "1M", "EURTRY") == D(2026, 4, 7) and tenor(desk, "1M", "EURUSD") == D(2026, 4, 7)


def test_the_fx_page_dates_eurusd_on_both_calendars_and_other_pairs_on_week_days(desk):
    on(desk, D(2026, 4, 1))
    eurusd, usdjpy = desk.fx.pair("EURUSD"), desk.fx.pair("USDJPY")
    assert desk.fx.spot_date(eurusd) == D(2026, 4, 7)                         # Good Friday and Easter Monday skipped
    assert desk.fx.spot_date(usdjpy) == D(2026, 4, 3)                         # (no holiday list: two week days, as before)
    on(desk, D(2026, 11, 24))
    assert desk.fx.spot_date(eurusd) == D(2026, 11, 27)                       # Thanksgiving skipped
    assert desk.fx.spot_date(usdjpy) == D(2026, 11, 26)
    assert desk.fx.curve(None, eurusd)["tenors"]["1W"]["date"] == D(2026, 12, 4)
    assert fx.delivery(D(2026, 10, 26), "1M", desk.holiday_dates(("USD", "TRY"))) == D(2026, 11, 27)
    assert fx.delivery(D(2026, 10, 26), "1M") == D(2026, 11, 26)


# ---------------------------------------------------------------------------------------------- editing
def test_each_list_is_edited_apart_and_the_value_dates_follow_for_everybody(tmp_path, monkeypatch):
    """A day added to the USD list moves USDTRY - and nothing else; one added to the EUR list moves EURTRY.  Writes go
    to the calculation thread first in line, the shared pages are made again, a restart keeps the lists, and over HTTP
    any signed-in user edits one list at a time (the TRY list when none is named, as before)."""
    from starlette.testclient import TestClient
    from tto.server import create_app
    svc = make_service(tmp_path)
    try:
        u = svc.login("Tatil Düzenleyen")["user"]
        hol = svc.holidays()
        usd = hol["lists"]["USD"]["items"]
        assert day_of(svc, "Forward!I2") == D(2026, 11, 4) and day_of(svc, "Forward!K2") == D(2026, 11, 5)
        strip = lambda page: next(p for p in page["panels"] if p["id"] == "B1")["data"]["rows"][1]     # noqa: E731
        assert strip(svc.view(None, "forward"))[4]["t"] == "04.11.2026"        # the page is kept for everybody now
        priorities = []
        call_at = svc.et.call_at

        def spy(priority, fn, *args, **kw):
            priorities.append((priority, getattr(fn, "__name__", "")))
            return call_at(priority, fn, *args, **kw)

        monkeypatch.setattr(svc.et, "call_at", spy)
        res = svc.set_holidays(u, usd + [{"date": "04.11.2026", "name": "Deneme tatili"}], "usd")
        monkeypatch.setattr(svc.et, "call_at", call_at)
        assert (EngineThread.WRITE, "_set_holidays") in priorities
        assert res["ccy"] == "USD" and res["saved"] == 213 and len(res["lists"]["USD"]["items"]) == 213
        assert {"date": "2026-11-04", "name": "Deneme tatili"} in res["lists"]["USD"]["items"]
        assert day_of(svc, "Forward!I2") == D(2026, 11, 5)                    # USDTRY moved ...
        assert day_of(svc, "Forward!K2") == D(2026, 11, 5)                    # ... EURTRY did not
        assert day_of(svc, "DİBS RV!D2") == D(2026, 11, 4)                    # ... nor the bonds' T+1 (TRY)
        assert res["lists"]["TRY"] == hol["lists"]["TRY"] and res["lists"]["EUR"] == hol["lists"]["EUR"]
        assert strip(svc.view(None, "forward"))[4]["t"] == "05.11.2026"       # the kept page followed
        assert strip(svc.view(svc.login("Başka Kullanıcı")["user"], "forward"))[4]["t"] == "05.11.2026"
        res = svc.set_holidays(u, hol["lists"]["EUR"]["items"] + [{"date": "2026-11-05", "name": "AB deneme"}], "EUR")
        assert day_of(svc, "Forward!K2") == D(2026, 11, 6) and day_of(svc, "Forward!I2") == D(2026, 11, 5)
        assert svc.store.shared_inputs("tto")[("tto", "EK_TATIL!D%d" % (ex.HOL_FIRST + 98))] is not None
        with pytest.raises(ServiceError):
            svc.set_holidays(u, usd, "GBP")
        with pytest.raises(ServiceError):
            svc.set_holidays(u, usd + [{"date": "31.02.2027"}], "USD")
        with pytest.raises(ServiceError):                                     # more days than the list has rows
            svc.set_holidays(u, ["%02d.%02d.2045" % (d, m) for m in range(1, 13) for d in range(1, 23)], "EUR")
        # a day added to the TRY list: the desk's market days (read once a day otherwise) follow at once
        svc.ops.market_day("2026-11-04")
        assert "2026-11-04" not in svc.et.call(svc.watch.holidays)
        svc.set_holidays(u, hol["tr"] + [{"date": "04.11.2026", "name": "Deneme"}])
        assert "2026-11-04" in svc.et.call(svc.watch.holidays) and "2026-11-04" not in svc.ops._days
        svc.set_holidays(u, hol["tr"])
        assert "2026-11-04" not in svc.et.call(svc.watch.holidays)
    finally:
        svc.stop()
    again = make_service(tmp_path)
    try:
        lists = again.holidays()["lists"]
        assert {"date": "2026-11-04", "name": "Deneme tatili"} in lists["USD"]["items"] and len(lists["EUR"]["items"]) == 99
        assert day_of(again, "Forward!I2") == D(2026, 11, 5) and day_of(again, "Forward!K2") == D(2026, 11, 6)
        with TestClient(create_app(again)) as client:                        # (its shutdown stops the service)
            hdr = auth(again, "Tatil Okuyan")                                  # not an administrator: everybody edits
            got = client.get("/api/holidays", headers=hdr).json()
            assert got["lists"]["USD"]["items"] == lists["USD"]["items"] and got["ccys"] == ["TRY", "USD", "EUR"]
            back = client.post("/api/holidays", json={"ccy": "USD", "items": usd}, headers=hdr)
            assert back.status_code == 200 and back.json()["lists"]["USD"]["items"] == usd
            back = client.post("/api/holidays", json={"ccy": "EUR", "items": hol["lists"]["EUR"]["items"]}, headers=hdr)
            assert back.status_code == 200 and back.json()["ccy"] == "EUR"
            old = client.post("/api/holidays", json={"items": hol["tr"]}, headers=hdr)            # an older caller: TRY
            assert old.status_code == 200 and old.json()["ccy"] == "TRY" and old.json()["tr"] == hol["tr"]
            assert client.post("/api/holidays", json={"ccy": "GBP", "items": usd}, headers=hdr).status_code == 400
            assert client.post("/api/holidays", json={"ccy": "USD", "items": "x"}, headers=hdr).status_code == 400
            assert day_of(again, "Forward!I2") == D(2026, 11, 4) and day_of(again, "Forward!K2") == D(2026, 11, 5)
            # the lists of the sheet again: nothing stored for them
            assert not any(ref.startswith("EK_TATIL!") for _, ref in again.store.shared_inputs("tto"))
    finally:
        again.stop()
