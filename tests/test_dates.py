"""Special days: the dashboard at a month end, at the year end, on a bayram and after a PPK meeting.

The desk's calendar is the workbook's holiday list (Motor!A361:A523): a value date the dashboard works out itself
follows it the way the workbook's own ``WORKDAY(EDATE(spot, n) - 1, 1, holidays)`` does.

A day other than the recorded one (Tuesday 03.11.2026, spot 04.11.2026) runs on a connected Bloomberg stand-in that
answers with the recorded values - each settle date its business-day lag on the desk's calendar from that day, as
WORKDAY(TODAY(), lag, holidays) counts - and on a clock at noon of that day."""
from __future__ import annotations

import datetime as dt
import re

import pytest

from conftest import cell
from tto.config import Settings
from tto.marketdata.bloomberg import NA_NA, NO_BFX, NO_RT
from tto.marketdata.replay import ReplayProvider
from tto.service import Service
from tto.xl.engine import Clock
from tto.xl.values import date_to_serial, serial_to_date

RECORDED = dt.date(2026, 11, 3)
USER = "tatil testi"


def as_date(v):
    if type(v) is float and 20000 < v < 80000:
        return serial_to_date(v)
    m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$", v) if isinstance(v, str) else None
    return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


class Calendar(object):
    """The desk's business days: no weekend, no day of the workbook's holiday list."""

    def __init__(self, svc):
        self.holidays = {as_date(cell(svc, "Motor!A%d" % r)) for r in range(361, 524)} - {None}

    def open(self, d):
        return d.weekday() < 5 and d not in self.holidays

    def add(self, d, n):
        while n > 0:
            d += dt.timedelta(days=1)
            n -= self.open(d)
        return d

    def between(self, a, b):
        return sum(self.open(a + dt.timedelta(days=k)) for k in range(1, (b - a).days + 1))


class StandIn(ReplayProvider):
    """A connected Bloomberg that answers at once with what it was given."""
    live = True

    def _get(self, key):
        v = self.snapshot.get(key)
        return NA_NA if v is None else v

    get_bdp = get_bdh = get_bds = _get

    def get_bfx(self, key):
        return NO_BFX

    def get_rt(self, key):
        return NO_RT


def on_day(service, data_dir, day):
    """The dashboard opened on ``day``: the recorded market with its settle dates moved to that day."""
    cal = Calendar(service)
    snapshot = {}
    for k, v in service.provider.snapshot.items():
        if k[0] == "BDP" and k[2] == "SETTLE_DT" and as_date(v):
            d = cal.add(day, cal.between(RECORDED, as_date(v)) or (not cal.open(day)))
            v = "%d.%d.%d" % (d.day, d.month, d.year) if isinstance(v, str) else float(date_to_serial(d))
        elif k[0] == "BDP" and k[2] == "DAYS_TO_MTY" and type(v) is float:
            v -= (day - RECORDED).days
        snapshot[k] = v
    today = float(date_to_serial(day))
    clock = Clock(today + 0.5)
    clock.today = lambda: today
    return Service(Settings(data_dir=str(data_dir), mode="replay", history=False), provider=StandIn(snapshot), clock=clock)


def day_of(svc, ref):
    return as_date(cell(svc, ref))


def tenor_day(svc, tenor):
    return serial_to_date(svc._tenor_date(tenor))


#: the workbook's own value dates of the month tenors: WORKDAY(EDATE(Forward!I2, n) - 1, 1, holidays)
WORKBOOK_TENORS = (("1M", "MASA!P94"), ("2M", "MASA!P95"), ("3M", "MASA!P96"), ("6M", "MASA!P97"), ("9M", "MASA!P98"),
                   ("1Y", "MASA!P99"), ("18M", "MASA!C171"))


def check_tenors(svc):
    cal = Calendar(svc)
    for tenor, ref in WORKBOOK_TENORS:
        assert tenor_day(svc, tenor) == day_of(svc, ref), tenor
    for tenor in ("1W", "2W", "3W", "6W", "18W", "28W", "1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y"):
        assert cal.open(tenor_day(svc, tenor)), tenor


def check_pages(svc):
    """Every page renders, and no cell of it failed in Python (a formula error is the workbook's own business)."""
    def failed(x):
        if isinstance(x, dict):
            return (x.get("k") == "e" and x.get("t") == "#ERR") or any(failed(v) for v in x.values())
        return isinstance(x, list) and any(failed(v) for v in x)
    for v in svc.views:
        assert not failed(svc.view(USER, v["id"])), v["id"]


# ---------------------------------------------------------------------------------------------- the recorded day
def test_tenor_value_dates_follow_the_desks_holidays(service):
    """Spot is Wednesday 04.11.2026: 18 weeks on is 10.03.2027 - Ramazan Bayramı (9-11 March) - so the forward settles
    on Friday 12.03; 28 weeks on is 19.05.2027, the last day of Kurban Bayramı and 19 Mayıs: Thursday 20.05."""
    assert tenor_day(service, "18W") == dt.date(2027, 3, 12)
    assert tenor_day(service, "28W") == dt.date(2027, 5, 20)
    assert service.quote_forward(USER, {"value_date": "18W", "basis": "RET_MID"})["value_date_iso"] == "2027-03-12"
    check_tenors(service)


# ---------------------------------------------------------------------------------------------- a month end
@pytest.fixture(scope="module")
def month_end(service, tmp_path_factory):
    """Monday 30.11.2026: spot is 01.12.2026, so one month on is 1 Ocak."""
    svc = on_day(service, tmp_path_factory.mktemp("ay-sonu"), dt.date(2026, 11, 30))
    yield svc
    svc.stop()


def test_one_month_from_the_first_of_december_skips_new_year(month_end):
    assert day_of(month_end, "OIS_MAIN!B2") == day_of(month_end, "Forward!I2") == dt.date(2026, 12, 1)
    assert tenor_day(month_end, "1M") == dt.date(2027, 1, 4)              # 1 Ocak is a Friday: the Monday after
    assert month_end.quote_forward(USER, {"value_date": "1M", "basis": "RET_MID"})["value_date_iso"] == "2027-01-04"
    check_tenors(month_end)


# ---------------------------------------------------------------------------------------------- the year end
@pytest.fixture(scope="module")
def year_end(service, tmp_path_factory):
    """Thursday 31.12.2026: 1 Ocak and the weekend follow - spot is Monday 04.01.2027; the PPK of 10.12.2026 is over."""
    svc = on_day(service, tmp_path_factory.mktemp("yil-sonu"), dt.date(2026, 12, 31))
    yield svc
    svc.stop()


def test_at_the_year_end_spot_is_after_new_year_and_the_weekend(year_end):
    assert day_of(year_end, "OIS_MAIN!B2") == day_of(year_end, "Forward!I2") == dt.date(2027, 1, 4)
    assert day_of(year_end, "DİBS RV!D2") == dt.date(2027, 1, 4)           # the bonds' T+1 is also after it
    check_tenors(year_end)


def test_the_meeting_of_december_leaves_the_list_once(year_end):
    h = year_end.history
    assert h.calendar()["passed_in_list"] == 1 and day_of(year_end, "OIS_MAIN!P10") == dt.date(2026, 12, 10)
    res = h.auto_roll()
    assert res["rolled"] == ["2026-12-10"] and res["first"] == "2027-01-21"
    assert day_of(year_end, "OIS_MAIN!P10") == dt.date(2027, 1, 21)        # MPC1 is the next meeting
    assert h.calendar()["passed_in_list"] == 0 and h.auto_roll() is None


def test_every_page_works_at_the_year_end(year_end):
    check_pages(year_end)


# ---------------------------------------------------------------------------------------------- a bayram
@pytest.fixture(scope="module")
def bayram(service, tmp_path_factory):
    """Wednesday 10.03.2027, the second day of Ramazan Bayramı: spot is Friday 12.03.2027."""
    svc = on_day(service, tmp_path_factory.mktemp("bayram"), dt.date(2027, 3, 10))
    yield svc
    svc.stop()


def test_on_a_bayram_spot_is_the_first_day_after_it(bayram):
    assert day_of(bayram, "OIS_MAIN!B2") == day_of(bayram, "Forward!I2") == dt.date(2027, 3, 12)
    assert day_of(bayram, "DİBS RV!D2") == dt.date(2027, 3, 12)
    assert tenor_day(bayram, "6W") == dt.date(2027, 4, 26)                 # six weeks on is 23 Nisan, a Friday
    check_tenors(bayram)


def test_every_page_works_on_a_bayram(bayram):
    check_pages(bayram)
