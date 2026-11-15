"""Daily history: closes, what was priced for every MPC meeting day by day, the end-of-day change matrix and
the meeting calendar (edits, and the roll after a meeting has passed)."""
import datetime as dt
import math
import time

import pytest

import fake_blpapi
from conftest import ANON, auth, make_service
from helpers import close
from tto import history
from tto.config import Settings
from tto.history import (DEFAULT_PAST_MEETINGS, DayProvider, History, add_months, align_meetings, curve_quotes, filled,
                         next_business_day, tenor_months, weekdays_ending)
from tto.marketdata.base import bdp_key
from tto.marketdata.bloomberg import BloombergProvider
from tto.marketdata.replay import ReplayProvider, _recorded_rows
from tto.quant import series_specs
from tto.service import Service, ServiceError
from tto.store import Store
from tto.xl.engine import Clock
from tto.xl.model import COLS, parse_a1
from tto.xl.values import XlArray, date_to_serial, serial_to_date

TODAY = "2026-11-03"                     # the day the workbook was saved
#: days of the recorded month the tests run the solver for: the references of the matrix (1 / 5 / 21 week days
#: before the last close) and the days around the meeting of 22 October
DAYS = ["2026-10-05", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-27", "2026-11-02", TODAY]


def D(text):
    return dt.date.fromisoformat(text)


# ====================================================================================== small pieces
def test_week_day_axis_and_previous_fill():
    axis = weekdays_ending(D("2026-11-03"), 7)
    assert [d.isoformat() for d in axis] == ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03"]
    assert weekdays_ending(D("2026-11-01"), 2)[-1] == D("2026-10-30")           # a Sunday: back to the Friday
    points = {"2026-10-26": 1.0, "2026-10-28": 2.0, "2026-11-03": 3.0}
    assert filled(points, axis) == [1.0, 1.0, 2.0, 2.0, 2.0, 2.0, 3.0]          # a holiday takes the previous close
    assert filled(points, axis, stale=2) == [1.0, 1.0, 2.0, 2.0, 2.0, None, 3.0]   # ... but a series that stopped does not go on
    assert filled({}, axis) == [None] * 7


def test_tenors_months_and_business_days():
    assert [tenor_months(t) for t in ("O/N", "T/N", "1W", "2W", "1M", "9M", "18M", "1Y", "10Y")] == \
        [0.01, 0.02, 0.25, 0.5, 1.0, 9.0, 18.0, 12.0, 120.0]
    assert tenor_months("spot") is None and tenor_months("") is None
    assert add_months(D("2026-11-30"), 3) == D("2027-02-28") and add_months(D("2027-01-31"), 13) == D("2028-02-29")
    assert add_months(D("2026-11-04"), 12) == D("2027-11-04")
    holidays = {D("2026-10-29")}
    assert next_business_day(D("2026-10-28"), holidays) == D("2026-10-30")       # over the Republic Day
    assert next_business_day(D("2026-10-30"), holidays) == D("2026-11-02")       # over the weekend


def test_meetings_are_matched_by_date_when_the_list_changes():
    old = ["2026-12-10", "2027-01-21", "2027-03-18", "2027-04-22"]
    # the roll: the meeting that passed leaves the list, everything else moves up
    assert align_meetings(old, old[1:]) == {0: None, 1: 0, 2: 1, 3: 2}
    # a corrected date is the same meeting
    assert align_meetings(old, ["2026-12-10", "2027-01-28", "2027-03-18", "2027-04-22"]) == {0: 0, 1: 1, 2: 2, 3: 3}
    assert align_meetings(old, ["2026-12-17", "2027-01-21", "2027-03-18", "2027-04-22"])[0] == 0
    # two neighbours corrected at once stay in order
    assert align_meetings(old, ["2026-12-10", "2027-01-14", "2027-03-25", "2027-04-22"]) == {0: 0, 1: 1, 2: 2, 3: 3}
    # a meeting put in between is a new one, the others keep their identity
    assert align_meetings(old, ["2026-12-10", "2027-01-21", "2027-02-11", "2027-03-18", "2027-04-22"]) == {0: 0, 1: 1, 2: 3, 3: 4}
    # a meeting taken out is gone - and a date far away is not "the same meeting moved"
    assert align_meetings(old, ["2026-12-10", "2027-03-18", "2027-04-22"]) == {0: 0, 1: None, 2: 1, 3: 2}
    assert align_meetings(old, ["2026-12-10", "2027-03-18", "2027-04-22", "2027-09-09"]) == {0: 0, 1: None, 2: 1, 3: 2}
    assert align_meetings(["2026-12-10"], ["2027-06-10"]) == {0: None}
    # roll and correction together
    assert align_meetings(old, ["2027-01-28", "2027-03-18", "2027-04-22", "2027-06-10"]) == {0: None, 1: 0, 2: 1, 3: 2}
    assert align_meetings([], ["2027-01-28"]) == {} and align_meetings(old, []) == {0: None, 1: None, 2: None, 3: None}
    # one meeting taken out and its neighbour corrected in the same edit: the date that moved least is the correction
    assert align_meetings(["2027-01-21", "2027-02-11", "2027-03-25", "2027-04-22"], ["2027-01-21", "2027-03-18", "2027-04-22"]) == \
        {0: 0, 1: None, 2: 1, 3: 2}
    assert align_meetings(["2027-01-21", "2027-03-18"], ["2027-01-21", "2027-02-11", "2027-03-25"]) == {0: 0, 1: 2}


# ====================================================================================== the quotes of a day
CURVE_DAYS = ["2026-10-%02d" % d for d in (19, 20, 21, 22, 23, 26, 27, 28)]
CURVE = {1.0: 36.4, 2.0: 36.6, 3.0: 36.9, 6.0: 36.4, 9.0: 36.0, 12.0: 35.5}


def curve(drift=0.10):
    """Six tenors that rise in parallel by ``drift`` a day: ``[(months, {day: close})]``."""
    return [(m, {d: v + drift * k for k, d in enumerate(CURVE_DAYS)}) for m, v in CURVE.items()]


def test_closes_that_belong_to_their_day_are_the_quotes():
    tenors = curve()
    values, marks = curve_quotes(tenors)
    assert marks == {} and values == [p for _, p in tenors]
    # a spike of the whole curve that comes back the next day is the market, not a wrong print
    jumpy = curve()
    for _, points in jumpy:
        points["2026-10-22"] += 0.60
    values, marks = curve_quotes(jumpy)
    assert marks == {} and values == [p for _, p in jumpy]
    # ... and so is a move of half the curve, or of two neighbouring tenors: a neighbour went along
    half = curve()
    for _, points in half[3:]:
        points["2026-10-22"] += 0.60
    assert curve_quotes(half)[1] == {}
    pair = curve()
    pair[2][1]["2026-10-22"] += 0.50
    pair[3][1]["2026-10-22"] += 0.50
    assert curve_quotes(pair)[1] == {}


def test_a_tenor_without_a_close_goes_on_by_what_its_neighbours_did():
    """A plain "previous value" fill leaves yesterday's level in a curve that has moved: on a tenor that
    closes every other day, in a market that moves 10 bp a day, that is a zigzag of 10 bp in the quote - and
    several times that in the meetings the solver hangs on it."""
    tenors = curve()
    true = dict(tenors[4][1])
    for d in CURVE_DAYS[1::2]:
        del tenors[4][1][d]                                               # the 9M closes every other day
    values, marks = curve_quotes(tenors)
    assert sorted(marks) == CURVE_DAYS[1::2] and all(m == {"carried": [4], "cleaned": []} for m in marks.values())
    assert all(values[4][d] == pytest.approx(true[d], abs=1e-12) for d in CURVE_DAYS)        # no zigzag
    plain = filled(tenors[4][1], [D(d) for d in CURVE_DAYS], 3)
    assert max(abs(v - true[d]) for v, d in zip(plain, CURVE_DAYS)) == pytest.approx(0.10)   # what carrying the level does
    # the neighbours are weighted by maturity: the 6M between a 3M that moved 20 bp and a 9M that moved 80 bp
    tenors = curve(0.0)
    del tenors[3][1]["2026-10-28"]
    tenors[2][1]["2026-10-28"] += 0.20
    tenors[4][1]["2026-10-28"] += 0.80
    values, marks = curve_quotes(tenors)
    assert values[3]["2026-10-28"] == pytest.approx(36.4 + 0.5 * 0.20 + 0.5 * 0.80)
    # the shortest tenor has one neighbour only; a tenor alone is carried as it is
    tenors = curve()
    del tenors[0][1]["2026-10-27"]
    assert curve_quotes(tenors)[0][0]["2026-10-27"] == pytest.approx(36.4 + 0.60)
    alone = [(3.0, {"2026-10-19": 36.9, "2026-10-21": 37.0})]
    values, marks = curve_quotes(alone + [(6.0, {"2026-10-20": 36.5})])
    assert values[0]["2026-10-20"] == 36.9 and marks["2026-10-20"]["carried"] == [0]
    # ... but not for ever: three trading days at most
    tenors = curve()
    for d in CURVE_DAYS[2:7]:
        del tenors[5][1][d]
    values, marks = curve_quotes(tenors)
    assert [d for d in CURVE_DAYS if d in values[5]] == CURVE_DAYS[:2] + CURVE_DAYS[2:5] + CURVE_DAYS[7:]
    assert "2026-10-26" not in values[5] and "2026-10-27" not in values[5]


def test_a_close_that_leaves_its_neighbours_and_comes_back_is_not_used():
    tenors = curve()
    true = [dict(p) for _, p in tenors]
    tenors[3][1]["2026-10-26"] += 0.45                                    # a wrong 6M print
    tenors[2][1]["2026-10-22"] = tenors[2][1]["2026-10-20"]               # a 3M quote that was not updated for two days
    tenors[2][1]["2026-10-21"] = tenors[2][1]["2026-10-20"]
    values, marks = curve_quotes(tenors)
    assert marks == {"2026-10-26": {"carried": [], "cleaned": [3]}}
    assert values[3]["2026-10-26"] == pytest.approx(true[3]["2026-10-26"])                   # where it belongs
    # the stale 3M is 10 and 20 bp behind and then catches up at once: below the 25 bp that count, left as it is
    assert values[2]["2026-10-22"] == tenors[2][1]["2026-10-22"]
    # a larger one of the same kind is caught: 30 bp behind for a day
    stale = curve(0.30)
    stale[2][1]["2026-10-22"] = stale[2][1]["2026-10-21"]
    values, marks = curve_quotes(stale)
    assert marks == {"2026-10-22": {"carried": [], "cleaned": [2]}}
    assert values[2]["2026-10-22"] == pytest.approx(36.9 + 0.30 * 3)
    # the neighbours of a wrong print are not thrown out with it (they left one side only)
    wrong = curve()
    wrong[2][1]["2026-10-23"] += 0.80
    values, marks = curve_quotes(wrong)
    assert marks == {"2026-10-23": {"carried": [], "cleaned": [2]}}
    # the very front is left alone (it does jump on its own), and so is the last day (it may yet stay there)
    front = curve()
    front[0][1]["2026-10-22"] += 0.60
    last = curve()
    last[3][1]["2026-10-28"] += 0.60
    assert curve_quotes(front)[1] == {} and curve_quotes(last)[1] == {}
    # a level that stays is a move, not a print
    moved = curve()
    for d in CURVE_DAYS[4:]:
        moved[3][1][d] += 0.50
    assert curve_quotes(moved)[1] == {}


def test_recorded_history_blocks_get_their_dates():
    opts = (("DATES", "H"), ("DAYS", "W"), ("FILL", "P"))
    key = ("BDH", "TYSO1 Curncy", "PX_LAST", "20261030", "20261103", opts)
    rows = _recorded_rows(key, XlArray([[35.6], [35.55], [35.52]]))
    assert rows == [("2026-10-30", 35.6), ("2026-11-02", 35.55), ("2026-11-03", 35.52)]      # week days from the start date
    dated = ("BDH", "USDTRY Curncy", "PX_LAST", "20261030", "20261103", (("DATES", "S"),))
    serial = float(date_to_serial(D("2026-11-02")))
    assert _recorded_rows(dated, XlArray([[serial, 49.9], [None, None]])) == [("2026-11-02", 49.9)]
    # a block whose dates cannot be told (trading days only, dates hidden) is not used
    assert _recorded_rows(("BDH", "X", "PX_LAST", "20261030", "20261103", (("DATES", "H"),)), XlArray([[1.0]])) == []
    prov = ReplayProvider({key: XlArray([[35.6], [35.55], [35.52]]), bdp_key("TYSO1 Curncy", "PX_LAST"): 35.52})
    prov.recorded_history[("BISTTREF Index", "PX_LAST")] = [("2026-10-30", 35.86), ("2026-11-02", 35.82)]
    prov.recorded_history[("TYSO1 Curncy", "PX_LAST")] = [("2026-11-02", 99.0), ("2026-10-29", 35.7)]
    got = prov.history([("TYSO1 Curncy", "px_last"), ("BISTTREF Index", "PX_LAST"), ("YOK Curncy", "PX_LAST")], "20261029", "20261102")
    assert got == {("TYSO1 Curncy", "PX_LAST"): [("2026-10-29", 35.7), ("2026-10-30", 35.6), ("2026-11-02", 35.55)],   # the workbook's own wins
                   ("BISTTREF Index", "PX_LAST"): [("2026-10-30", 35.86), ("2026-11-02", 35.82)]}


def test_the_day_provider_answers_with_the_closes_of_one_day():
    p = DayProvider("BISTTREF Index")
    p.quotes = {"TYSOA": 36.35}
    p.tlref = 35.8159
    p.spot_text = "4.11.2026"
    assert p.get_bdp(bdp_key("TYSOA GFOF Curncy", "MID")) == 36.35 and p.get_bdp(bdp_key("TYSOA Curncy", "PX_LAST")) == 36.35
    assert p.get_bdp(bdp_key("TYSO2 GFOF Curncy", "MID")) == "#N/A N/A"          # no close: the sheet's own fallback applies
    assert p.get_bdp(bdp_key("BISTTREF Index", "PX_LAST")) == 35.8159
    assert p.get_bdp(bdp_key("TRY Curncy", "SETTLE_DT")) == "4.11.2026" == p.get_bdp(bdp_key("USDTRY Curncy", "SETTLE_DT"))
    assert not p.unknown
    assert p.get_bdp(bdp_key("TYSOA Curncy", "DAYS_TO_MTY")) == "#N/A N/A" and p.unknown == {"TYSOA Curncy|DAYS_TO_MTY"}
    assert p.get_bdh(("BDH", "X", "PX_LAST", "1", "2", ())) == "#N/A N/A"


def test_calendar_dates_are_parsed_strictly():
    assert History.parse_dates(["10.12.2026", "2027-01-21", " 18/03/2027 ", "", None, 46499, "10.12.2026"]) == \
        ["2026-12-10", "2027-01-21", "2027-03-18", "2027-04-22"]
    for bad in ("32.01.2027", "yarın", "10.12.1999", 12):
        with pytest.raises(ValueError):
            History.parse_dates([bad])


# ====================================================================================== the store
def test_closes_are_stored_once(tmp_path):
    st = Store(str(tmp_path / "h.db"))
    assert st.hist_upsert("A|PX_LAST", [("2026-11-02", 1.5), ("2026-11-03", 1.6)]) == 2
    assert st.hist_upsert("A|PX_LAST", [("2026-11-02", 1.5), ("2026-11-03", 1.6)]) == 0          # nothing new
    assert st.hist_upsert("A|PX_LAST", [("2026-11-03", 1.7), ("2026-11-04", 1.8)]) == 2          # a restated close and a new day
    assert st.hist_upsert("B|PX_LAST", [("2026-11-03", 9.0)]) == 1 and st.hist_upsert("B|PX_LAST", []) == 0
    assert st.hist_series("A|PX_LAST") == [("2026-11-02", 1.5), ("2026-11-03", 1.7), ("2026-11-04", 1.8)]
    assert st.hist_series("A|PX_LAST", "2026-11-03", "2026-11-03") == [("2026-11-03", 1.7)]
    assert st.hist_many(["A|PX_LAST", "B|PX_LAST", "C|PX_LAST"], "2026-11-03") == \
        {"A|PX_LAST": {"2026-11-03": 1.7, "2026-11-04": 1.8}, "B|PX_LAST": {"2026-11-03": 9.0}, "C|PX_LAST": {}}
    assert st.hist_bounds() == {"A|PX_LAST": ("2026-11-02", "2026-11-04", 3), "B|PX_LAST": ("2026-11-03", "2026-11-03", 1)}
    st.hist_delete("B|PX_LAST")
    assert list(st.hist_bounds()) == ["A|PX_LAST"]
    st.close()
    again = Store(str(tmp_path / "h.db"))                    # it is on disk
    assert len(again.hist_series("A|PX_LAST")) == 3
    again.close()


def test_meeting_pricing_is_stored_per_day_and_meeting(tmp_path):
    st = Store(str(tmp_path / "m.db"))
    rows = [{"meeting": "2026-12-10", "step": -80.0, "level": 0.35, "cum": -80.0, "sigma": 6.0, "front": True},
            {"meeting": "2027-01-21", "step": -40.0, "level": 0.346, "cum": -120.0, "sigma": None, "front": False}]
    st.mpc_save("2026-11-02", "b1", {"spot": "2026-11-03", "tlref": 35.8, "quotes": 18, "status": "OK", "base": 0.358}, rows)
    st.mpc_save("2026-11-03", "b2", {"spot": "2026-11-04", "tlref": 35.8, "quotes": 18, "status": "OK", "decision": True}, rows[:1])
    st.mpc_save("2026-11-02", "b3", {"spot": "2026-11-03", "tlref": 35.9, "quotes": 17, "status": "Kota eksik"}, rows[1:])   # replaced as a whole
    days = st.mpc_days()
    assert list(days) == ["2026-11-02", "2026-11-03"] and days["2026-11-02"]["basis"] == "b3" and days["2026-11-02"]["quotes"] == 17
    assert days["2026-11-03"]["decision"] == 1 and days["2026-11-02"]["decision"] == 0
    assert [(r["day"], r["meeting"], r["front"]) for r in st.mpc_values()] == [("2026-11-02", "2027-01-21", 0), ("2026-11-03", "2026-12-10", 1)]
    assert st.mpc_values(meetings=["2026-12-10"])[0]["step"] == -80.0 and st.mpc_values(meetings=[]) == []
    assert st.mpc_values("2026-11-03", "2026-11-03")[0]["meeting"] == "2026-12-10"
    st.mpc_delete(["2026-11-02"])
    assert list(st.mpc_days()) == ["2026-11-03"] and len(st.mpc_values()) == 1
    st.mpc_delete()
    assert st.mpc_days() == {} and st.mpc_values() == []
    st.close()


def test_personal_inputs_and_saved_scenarios_move_with_their_cells(tmp_path):
    st = Store(str(tmp_path / "r.db"))
    for name in ("Ayşe", "Mehmet"):
        st.login(name)
    st.set_user_inputs("ayşe", "tto", {"OIS_MAIN!U10": -50.0, "OIS_MAIN!U11": -75.0, "OIS_MAIN!U12": None, "Forward!D2": 46400.0})
    st.set_user_inputs("mehmet", "tto", {"OIS_MAIN!U11": 25.0})
    st.set_user_inputs("ayşe", "sofr", {"OIS_MAIN!U11": 1.0})                     # another workbook: not touched
    st.save_scenario("ayşe", "baz", st.user_inputs("ayşe"))
    st.save_scenario("mehmet", "başka", {("tto", "Forward!D2"): 1.0})
    # the list moves up by one: row 10 is gone, 11 -> 10, 12 -> 11 (a chain: every move happens at once)
    res = st.remap_user_cells("tto", {"OIS_MAIN!U10": None, "OIS_MAIN!U11": "OIS_MAIN!U10", "OIS_MAIN!U12": "OIS_MAIN!U11"})
    assert res == {"moved": 3, "dropped": 1, "scenarios": 1}
    assert st.user_inputs("ayşe", "tto") == {("tto", "OIS_MAIN!U10"): -75.0, ("tto", "OIS_MAIN!U11"): None, ("tto", "Forward!D2"): 46400.0}
    assert st.user_inputs("mehmet", "tto") == {("tto", "OIS_MAIN!U10"): 25.0}
    assert st.user_inputs("ayşe", "sofr") == {("sofr", "OIS_MAIN!U11"): 1.0}
    assert st.load_scenario("ayşe", "baz") == {("tto", "OIS_MAIN!U10"): -75.0, ("tto", "OIS_MAIN!U11"): None, ("tto", "Forward!D2"): 46400.0,
                                              ("sofr", "OIS_MAIN!U11"): 1.0}
    assert st.load_scenario("mehmet", "başka") == {("tto", "Forward!D2"): 1.0}
    assert st.remap_user_cells("tto", {}) == {"moved": 0, "dropped": 0, "scenarios": 0}
    st.close()


# ====================================================================================== offline: what the workbook recorded
@pytest.fixture(scope="module")
def hsvc(tmp_path_factory):
    """A replay service whose history holds the recorded month, the solver run for :data:`DAYS`."""
    svc = make_service(tmp_path_factory.mktemp("hist"))
    res = svc.history.sync(only=DAYS)
    assert res["computed"] == len(DAYS), svc.history.state
    yield svc
    svc.stop()


def cells(svc, refs, user=None):
    """Raw values of cells of the TRY workbook."""
    book = svc.books["tto"]

    def run():
        calc = svc._calc(user, book)
        out = []
        for ref in refs:
            si, rc = book.cell(ref)
            out.append(calc.get(si, *divmod(rc, COLS)))
        return out

    return svc.et.call(run)


def test_the_series_come_from_the_workbook(hsvc):
    snap = hsvc.history.snapshot()
    assert snap["today"] == D(TODAY) and snap["spot"] == D("2026-11-04") and snap["src"] == "GFOF Curncy" and snap["backup"] == "Curncy"
    assert snap["sources"] == {"ois": ["GFOF"], "off": ["ICPL"], "xccy": ["ICPL"]}             # settings -> data sources
    by = {}
    for d in snap["defs"]:
        by.setdefault(d.group, []).append(d)
    assert [(d.label, d.ticker, d.field) for d in by["ref"]] == [("TLREF", "BISTTREF Index", "PX_LAST")]
    # the 16 quotes of the OIS page and the two stub quotes of the solver, on the source of MASA's history
    assert [d.label for d in by["ois"]] == ["1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y",
                                             "9Y", "10Y"]
    # GFOF first, as the OIS page itself prices; the ticker without a source (BGN, MASA's history) as the backup
    assert [d.ticker for d in by["ois"]][:4] == ["TYSO1Z GFOF Curncy", "TYSO2Z GFOF Curncy", "TYSOA GFOF Curncy", "TYSOB GFOF Curncy"]
    assert by["ois"][2].alts == ["TYSOA Curncy"] and by["ois"][2].root == "TYSOA" and by["ois"][-1].months == 120.0
    assert [d.label for d in by["off"]] == ["O/N", "T/N", "1W", "2W", "1M", "2M", "3M", "4M", "5M", "6M", "9M"]
    # offshore: ICAP's page first, the workbook's own BGN ticker as the backup (one without a source stays as it is)
    assert (by["off"][4].ticker, by["off"][4].alts) == ("TRYI1M ICPL Curncy", ["TRYI1M BGN Curncy"])
    assert (by["off"][7].ticker, by["off"][7].alts) == ("TRYI4M ICPL Curncy", ["TRYI4M Curncy"])
    assert [d.label for d in by["xccy"]] == ["%dY" % k for k in range(1, 11)]
    assert (by["xccy"][0].ticker, by["xccy"][0].alts) == ("TRYSAQ1 ICPL Curncy", ["TRYSAQ1 BGN Curncy"])
    bonds = by["dibs"]
    assert len(bonds) == 19 and all(d.info["isin"] in d.ticker for d in bonds)
    fixed = next(d for d in bonds if d.info["isin"] == "TRT150328T24")
    assert (fixed.ticker, fixed.alts, fixed.field, fixed.unit) == ("TRT150328T24 @ISL1 ISIN", ["TRT150328T24 ISIN"], "YLD_YTM_MID", "pct")
    assert fixed.info["maturity"] == "2028-03-15" and fixed.info["type"] == "S" and close(fixed.info["bist"], 0.39702755562957237, 1e-9)
    floater = next(d for d in bonds if d.info["isin"] == "TRT090130T12")
    assert (floater.field, floater.unit, floater.info["type"], floater.info["bist"]) == ("PX_LAST", "px", "T", None)   # price, not a yield
    assert len(snap["holidays"]) == 143 and snap["rows"][:2] == ["2026-12-10", "2027-01-21"] and snap["labels"][0] == "MPC1"
    assert len([r for r in snap["rows"] if r]) == 80
    # a ticker root changed on the OIS page changes the series (and the definitions follow the workbook at once)
    user = hsvc.login("Seri Deneme")["user"]
    hsvc.set_inputs(user, "tto", [{"ref": "OIS_MAIN!J9", "value": "TYSOX"}])
    try:
        assert [(d.ticker, d.alts) for d in hsvc.history.snapshot()["defs"] if d.label == "1M" and d.group == "ois"] == [
            ("TYSOX GFOF Curncy", ["TYSOX Curncy"])]
    finally:
        hsvc.reset_inputs(user, "tto", ["OIS_MAIN!J9"], shared=True)
    assert [d.ticker for d in hsvc.history.snapshot()["defs"] if d.label == "1M" and d.group == "ois"] == ["TYSOA GFOF Curncy"]


def test_offline_the_history_is_what_the_file_recorded(hsvc):
    st = hsvc.history.status()
    assert (st["series"], st["last_day"], st["mode"], st["phase"], st["error"]) == (14, TODAY, "replay", "idle", "")
    bounds = hsvc.store.hist_bounds()
    # (USDTRY, its swap points and USD OIS 3M are series of the quant package too - the VİOP sheet's BDH blocks have them)
    assert sorted(bounds) == ["BISTTREF Index|PX_LAST", "TRY12M Curncy|PX_LAST", "TRY1M Curncy|PX_LAST", "TRY3M Curncy|PX_LAST",
                              "TRY6M Curncy|PX_LAST", "TRYSAQ1 BGN Curncy|PX_LAST", "TYSO1 Curncy|PX_LAST", "TYSOA Curncy|PX_LAST",
                              "TYSOB Curncy|PX_LAST", "TYSOC Curncy|PX_LAST", "TYSOF Curncy|PX_LAST", "TYSOI Curncy|PX_LAST",
                              "USDTRY Curncy|PX_LAST", "USSOC Curncy|PX_LAST"]
    one_month = dict(hsvc.store.hist_series("TYSOA Curncy|PX_LAST"))
    assert len(one_month) == 22 and one_month["2026-10-05"] == 37.15 and one_month[TODAY] == 36.35      # the BDH block of the file
    assert one_month[TODAY] == hsvc.provider.snapshot[bdp_key("TYSOA Curncy", "PX_LAST")]                 # its last row is today's quote
    tlref = dict(hsvc.store.hist_series("BISTTREF Index|PX_LAST"))
    assert tlref["2026-10-22"] == 36.8769 and tlref["2026-10-23"] == 35.8498 and "2026-10-29" not in tlref   # a holiday has no fixing
    assert max(tlref) == "2026-11-02" and close(tlref["2026-11-02"] / 100.0, cells(hsvc, ["OIS_MAIN!J2"])[0], 1e-12)   # = TLREF on the OIS page
    assert min(tlref) >= "2025-10-29"                                                                      # one year back, not more
    cov = hsvc.history.coverage()["series"]
    assert {(s["ticker"], s["n"]) for s in cov if s["label"] == "1M" and s["group"] == "ois"} == {("TYSOA Curncy", 22), ("TYSOA GFOF Curncy", 0)}
    assert sum(1 for s in cov if s["group"] == "dibs" and s["n"]) == 0                                    # the file has no bond history
    # a second pass finds nothing new and computes nothing again
    assert hsvc.history.sync(only=DAYS) == {"fetched": 0, "computed": 0, "rev": hsvc.history.rev}


def test_history_of_today_is_the_ois_page(tmp_path):
    """The solver of the history, fed with the quotes the OIS page shows, gives the OIS page - cell by cell."""
    svc = make_service(tmp_path)
    try:
        h = svc.history
        h._fetch()
        snap = h.snapshot()
        row_of = {root: r for r, root in snap["roots"].items() if root}
        live = dict(zip(row_of, cells(svc, ["OIS_MAIN!B%d" % row_of[root] for root in row_of])))
        live[snap["stub"]["1W"]], live[snap["stub"]["2W"]] = cells(svc, ["OIS_MAIN!AU13", "OIS_MAIN!AU14"])
        assert len(live) == 18 and all(isinstance(v, float) for v in live.values())
        for root, q in live.items():                         # today's close of every tenor := the quote on the page
            svc.store.hist_upsert("%s Curncy|PX_LAST" % root, [(TODAY, round(q * 100.0, 10))])
        assert h._compute(only=[TODAY]) == 1
        meta = svc.store.mpc_days()[TODAY]
        assert (meta["status"], meta["quotes"], meta["spot"], meta["decision"], meta["note"]) == ("OK", 18, "2026-11-04", 0, "")
        assert close(meta["base"], cells(svc, ["OIS_MAIN!J2"])[0], 1e-12)
        got = {r["meeting"]: r for r in svc.store.mpc_values(TODAY, TODAY)}
        want = {}
        rows = list(range(10, 90))
        sheet = cells(svc, ["OIS_MAIN!%s%d" % (c, r) for r in rows for c in "PRSTN"])
        for k in range(len(rows)):
            p, step, level, cum, sigma = sheet[5 * k:5 * k + 5]
            if isinstance(step, float) and isinstance(level, float):
                want[serial_to_date(p).isoformat()] = (step, level, cum, sigma)
        assert len(want) >= 75 and set(got) == set(want)
        for meeting, (step, level, cum, sigma) in want.items():
            g = got[meeting]
            assert close(g["step"], step, 1e-9) and close(g["level"], level, 1e-12) and close(g["cum"], cum, 1e-9), meeting
            assert close(g["sigma"], sigma, 1e-9), meeting
        assert [m for m, g in got.items() if g["front"]] == ["2026-12-10"]
        # ... and the page of the history shows exactly that as the last point
        page = h.mpc()
        first = next(m for m in page["meetings"] if m["date"] == "2026-12-10")
        assert first["label"] == "MPC1" and not first["passed"] and close(first["last"]["step"], want["2026-12-10"][0], 1e-9)
        assert page["series"]["2026-12-10"]["level"][-1] == got["2026-12-10"]["level"] and page["days"] == [TODAY]
    finally:
        svc.stop()


def test_meeting_pricing_day_by_day(hsvc):
    days = hsvc.store.mpc_days()
    assert sorted(days) == DAYS
    assert {d["status"] for d in days.values()} == {"Kota eksik: 10 vade (BDP)"}       # the file recorded six tenors, up to 1Y
    assert {d["quotes"] for d in days.values()} == {6}
    assert days["2026-10-21"]["spot"] == "2026-10-22" and days["2026-10-27"]["spot"] == "2026-10-28"
    assert days["2026-11-02"]["tlref"] == 35.8159 and days[TODAY]["tlref"] == 35.8159      # today: the last fixing published
    rows = {}
    for r in hsvc.store.mpc_values():
        rows.setdefault(r["day"], {})[r["meeting"]] = r
    # ---- the meeting of 22 October: priced until the day before, then held
    oct_ = "2026-10-22"
    assert [d for d in DAYS if oct_ in rows[d]] == ["2026-10-05", "2026-10-20", "2026-10-21"]
    assert all(rows[d][oct_]["front"] == 1 for d in ("2026-10-05", "2026-10-20", "2026-10-21"))
    last = rows["2026-10-21"][oct_]
    assert -130 < last["step"] < -60                                   # a cut of about 100 bp was priced the day before
    assert close(last["step"], (last["level"] - 0.368509) * 10000, 1e-9)   # the first meeting is measured from that day's TLREF
    # ---- every meeting the quotes reach (1Y) and none beyond
    for d in DAYS:
        meetings = sorted(rows[d])
        horizon = add_months(D(days[d]["spot"]), 12)
        assert meetings and all(D(days[d]["spot"]) <= D(m) <= horizon for m in meetings), d
        assert sum(r["front"] for r in rows[d].values()) == 1 and rows[d][meetings[0]]["front"] == 1
        for m in meetings[1:]:                                           # later meetings: level = previous level + step
            prev = rows[d][meetings[meetings.index(m) - 1]]
            assert close(rows[d][m]["level"], prev["level"] + rows[d][m]["step"] / 10000.0, 1e-9), (d, m)
    assert "2027-10-21" in rows[TODAY] and "2027-10-21" not in rows["2026-10-05"]       # it came within reach of the 1Y quote later
    # ---- the day of the meeting itself: the close prices the decision, that day's TLREF fixing does not yet
    dec = "2026-12-10"
    on = rows[oct_][dec]
    assert days[oct_]["decision"] == 1 and on["front"] == 1 and oct_ not in rows[oct_]
    assert [d for d in DAYS if days[d]["decision"]] == [oct_]
    raw = (on["level"] - 0.368769) * 10000                               # measured from the old fixing it would carry the cut as well
    assert raw < on["step"] - 60 and close(on["step"], (on["level"] - days[oct_]["base"]) * 10000, 1e-6)
    assert 0.353 < days[oct_]["base"] < 0.365                            # the level the solver puts after the decision (~36 -> ~35.8)
    assert abs(on["step"] - rows["2026-10-23"][dec]["step"]) < 25         # no jump into the next day
    assert all(close(r["cum"], round((r["level"] - days[oct_]["base"]) * 10000, 2), 1e-9) for r in rows[oct_].values())
    for d in DAYS:
        if d != oct_:
            assert close(days[d]["base"], days[d]["tlref"] / 100.0, 1e-12)


def test_meeting_pricing_time_series(hsvc):
    page = hsvc.history.mpc()
    assert page["days"] == DAYS and page["today"] == TODAY and page["spot"] == "2026-11-04" and not page["live"]
    assert page["partial"] == len(DAYS) and page["status"] == ["Kota eksik: 10 vade (BDP)"] and page["decision_days"] == ["2026-10-22"]
    dates = [m["date"] for m in page["meetings"]]
    assert dates[0] == "2026-10-22" and dates[1:3] == ["2026-12-10", "2027-01-21"] and dates == sorted(dates)
    held, nxt = page["meetings"][0], page["meetings"][1]
    # the meeting that was held: its series ends the day before, with what TLREF did afterwards
    assert held["passed"] and held["where"] == "archive" and (held["first_day"], held["last_day"], held["n"]) == ("2026-10-05", "2026-10-21", 3)
    assert close(held["realized"], (35.8498 - 36.8769) * 100, 1e-9) and close(held["priced"], held["last"]["step"], 1e-12)
    assert close(held["surprise"], held["realized"] - held["priced"], 1e-9) and abs(held["surprise"]) < 40
    series = page["series"]["2026-10-22"]["step"]
    assert [v is not None for v in series] == [True, True, True, False, False, False, False, False]
    # the next meeting: a point on every day, changes against 1 / 5 / 21 week days earlier
    assert not nxt["passed"] and (nxt["label"], nxt["where"], nxt["n"], nxt["last_day"]) == ("MPC1", "list", len(DAYS), TODAY)
    steps = page["series"]["2026-12-10"]["step"]
    assert all(isinstance(v, float) for v in steps) and close(nxt["last"]["step"], steps[-1], 1e-12)
    assert close(nxt["d1"], steps[-1] - steps[-2], 1e-9)               # 02.11
    assert close(nxt["w1"], steps[-1] - steps[5], 1e-9)                # 27.10 = 5 week days before
    assert close(nxt["m1"], steps[-1] - steps[0], 1e-9)                # 05.10 = 21 week days before
    assert nxt["min"] == min(steps) and nxt["max"] == max(steps)
    levels = page["series"]["2026-12-10"]["level"]
    assert all(0.33 < v < 0.37 for v in levels)
    assert page["tlref"] == [36.8231, 36.8228, 36.8509, 36.8769, 35.8498, 35.8705, 35.8159, 35.8159] and page["quotes"] == [6] * 8
    assert hsvc.history.mpc(days=20)["days"] == DAYS[1:]                # a shorter window: from 14.10
    assert len(hsvc.history.mpc(upcoming=2)["meetings"]) == 3


def test_days_are_judged_by_the_workbooks_own_status(hsvc):
    flag = history.day_flag
    assert flag({"status": "OK"}) == "" and flag({"status": "OK", "control": 0.6, "tolerance": 5.0}) == ""
    assert flag({"status": "Kota eksik: 10 vade (BDP)", "control": 2.6, "tolerance": 5.0}) == "missing"
    assert flag({"status": "Kota/takvim tutarsız – kontrolü incele"}) == "inconsistent"        # a day of an earlier version
    assert flag({"status": "Kota eksik: 1 vade (BDP)", "control": 9.0, "tolerance": 5.0}) == "inconsistent"
    assert flag({"status": "HATA", "note": "ZeroDivisionError"}) == "error" and flag({}) == ""
    # what the recorded days say: six tenors only, but the solver matches them (the sheet tolerates 5 x 1 bp)
    days = hsvc.store.mpc_days()
    assert {flag(d) for d in days.values()} == {"missing"}
    assert all(d["tolerance"] == 5.0 and 0 <= d["control"] < 5.0 and d["carried"] >= 0 for d in days.values())
    st = hsvc.history.status()
    assert st["mpc_partial"] == len(DAYS) and st["mpc_missing"] == len(DAYS) and st["mpc_unreliable"] == 0
    page = hsvc.history.mpc()
    assert page["flags"] == ["missing"] * len(DAYS) and page["flagged"] == {}
    assert [(i["kind"], i["count"], i["status"]) for i in page["issues"]] == [("missing", len(DAYS), "Kota eksik: 10 vade (BDP)")]
    assert page["control"] == [days[d]["control"] for d in DAYS] and page["carried"] == [days[d]["carried"] for d in DAYS]


def test_a_day_the_solver_cannot_fit_is_reported_and_kept_out_of_the_series(tmp_path):
    """On the desk the page said "8 günde eksik OIS kotası var (Kota/takvim tutarsız – kontrolü incele; OK)".
    Nothing was missing on those days: the workbook's own check had failed - the solver could not match the
    quotes, which is what one stale close does to it.  Such a day stays in the database and in the daily
    table, but its steps are not drawn, do not set the range of a meeting and are not what a change is
    measured against."""
    svc = make_service(tmp_path)
    try:
        st, h = svc.store, svc.history
        meeting = "2026-12-10"

        def day(date, status, step, **more):
            meta = {"spot": "2026-11-04", "tlref": 35.8, "quotes": 16, "status": status, "base": 0.358}
            meta.update(more)
            st.mpc_save(date, "b-" + date, meta, [{"meeting": meeting, "step": step, "level": 0.358 + step / 10000.0,
                                                   "cum": step, "sigma": 5.0, "front": True}])

        day("2026-10-29", "OK", -80.0, control=0.4, tolerance=5.0, carried=0)
        day("2026-10-30", "Kota/takvim tutarsız – kontrolü incele", -480.0, control=37.5, tolerance=5.0, carried=2)
        day("2026-11-02", "OK", -82.0)                                       # computed by an earlier version: no control
        day("2026-11-03", "Kota eksik: 2 vade (BDP)", -85.0, control=1.1, tolerance=5.0, carried=0)
        page = h.mpc()
        assert page["days"] == ["2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03"]
        assert page["flags"] == ["", "inconsistent", "", "missing"]
        assert page["control"] == [0.4, 37.5, None, 1.1] and page["carried"] == [0, 2, None, 0]
        assert page["series"][meeting]["step"] == [-80.0, None, -82.0, -85.0]             # the spike is not drawn
        m = next(x for x in page["meetings"] if x["date"] == meeting)
        assert (m["min"], m["max"], m["n"]) == (-85.0, -80.0, 3)                         # ... and is not the range
        assert m["last"]["step"] == -85.0 and m["d1"] == pytest.approx(-3.0)
        assert page["flagged"] == {"2026-10-30": {meeting: {"step": -480.0, "level": pytest.approx(0.31), "cum": -480.0}}}
        assert page["issues"] == [
            {"kind": "inconsistent", "count": 1, "days": ["2026-10-30"], "status": "Kota/takvim tutarsız – kontrolü incele", "control": 37.5},
            {"kind": "missing", "count": 1, "days": ["2026-11-03"], "status": "Kota eksik: 2 vade (BDP)", "control": 1.1}]
        assert page["partial"] == 2
        state = h.status()
        assert (state["mpc_partial"], state["mpc_missing"], state["mpc_unreliable"]) == (2, 1, 1)
        # a change is measured against the last day the solver stands behind: 02.11 against 29.10, not 30.10
        day("2026-11-03", "Kota/takvim tutarsız – kontrolü incele", -300.0, control=11.0, tolerance=5.0)
        m = next(x for x in h.mpc()["meetings"] if x["date"] == meeting)
        assert m["last"]["step"] == -82.0 and m["last_day"] == "2026-11-02" and m["d1"] == pytest.approx(-2.0)
        # the end-of-day matrix reads the meetings the same way: on the day that does not count the last good
        # close is carried (as a close is over a holiday), and 02.11 is measured against 29.10, not 30.10
        block = h.matrix("2026-11-03")["mpc"]
        assert block[0]["meeting"] == meeting and block[0]["step"]["last"] == -82.0 and block[0]["step"]["d1"] == 0.0
        block = h.matrix("2026-11-02")["mpc"]
        assert block[0]["step"]["last"] == -82.0 and block[0]["step"]["d1"] == pytest.approx(-2.0)
        # a day whose status only says that tenors are missing, but whose check failed all the same
        day("2026-11-03", "Kota eksik: 1 vade (BDP)", -300.0, control=9.0, tolerance=5.0)
        assert h.mpc()["flags"][-1] == "inconsistent"
    finally:
        svc.stop()


def test_a_stale_close_is_what_the_solver_calls_inconsistent(tmp_path):
    """The workbook's own curve of 03.11.2026 (16 tenors, live) through the history's machine: the status is
    "OK" and the model is within a basis point of the quotes.  With one close 40 bp off - a quote that was not
    updated that day - the sheet says "Kota/takvim tutarsız" and the steps move by hundreds of basis points."""
    svc = make_service(tmp_path)
    try:
        h = svc.history
        snap = h.snapshot()
        quotes = {}
        for d in snap["defs"]:
            v = svc.provider.snapshot.get(bdp_key("%s GFOF Curncy" % d.root, "MID")) if d.group == "ois" else None
            if isinstance(v, float):
                quotes[d.root] = v
        assert len(quotes) == 16
        shared = h._plan(snap)[1]
        today = D(TODAY)
        calendar = [D(x) for x in h.meetings(snap)]

        def solve(q):
            p = {"day": today, "spot": next_business_day(today, set()), "tlref": 35.8159, "quotes": q,
                 "meetings": [m for m in calendar if m >= today][:80], "horizon": add_months(today, 24)}
            return h._het_call(h._solve, p, shared)

        good = solve(quotes)
        assert good["status"] == "OK" and good["tolerance"] == 5.0 and good["control"] < 1.0
        assert history.day_flag(good) == ""
        stale = dict(quotes, TYSOC=quotes["TYSOC"] + 0.40)                   # the 3M close, 40 bp too high
        bad = solve(stale)
        assert bad["status"].startswith("Kota/takvim tutarsız") and bad["control"] > bad["tolerance"]
        assert history.day_flag(bad) == "inconsistent"
        a = {r["meeting"]: r["step"] for r in good["rows"]}
        b = {r["meeting"]: r["step"] for r in bad["rows"]}
        assert max(abs(a[m] - b[m]) for m in list(a)[:4]) > 60               # the near meetings are thrown about
    finally:
        svc.stop()


def test_a_wrong_close_does_not_reach_the_solver(tmp_path):
    """The recorded month with one 3M close 40 bp too high: fed as it is, the nearest meetings jump by a
    hundred basis points for that one day - while the workbook's status still says all is well, the model
    being within its tolerance.  The close is told by its neighbours (2M and 6M did not go along, and it was
    back the next day), is not used, and the day comes out in line with the days around it."""
    svc = make_service(tmp_path)
    try:
        h, st = svc.history, svc.store
        h._fetch()
        series, day = "TYSOC Curncy|PX_LAST", "2026-10-27"
        closes = dict(st.hist_series(series))
        before = h._plan(h.snapshot())[0]
        assert all(p["carried"] == 0 and p["cleaned"] == "" for p in before)             # the recording is clean
        st.hist_upsert(series, [(day, closes[day] + 0.40)])
        plan, shared = h._plan(h.snapshot())
        p = next(x for x in plan if x["day"] == D(day))
        assert p["cleaned"] == "TYSOC" and p["carried"] == 1
        assert abs(p["quotes"]["TYSOC"] - closes[day]) < 0.12                            # near what it really was (7.5 bp off)
        assert p["basis"] != next(x for x in before if x["day"] == D(day))["basis"]      # the day is computed again
        others = [x for x in plan if x["day"] != D(day)]
        assert all(x["cleaned"] == "" and x["carried"] == 0 for x in others)
        assert [x["basis"] for x in others] == [x["basis"] for x in before if x["day"] != D(day)]   # ... and only that day

        def front(result):
            return next(r["step"] for r in result["rows"] if r["front"])

        raw = h._het_call(h._solve, dict(p, quotes=dict(p["quotes"], TYSOC=closes[day] + 0.40)), shared)
        fixed = h._het_call(h._solve, p, shared)
        around = [front(h._het_call(h._solve, x, shared)) for x in plan if _iso_day(x["day"]) in ("2026-10-26", "2026-10-28")]
        assert len(around) == 2
        assert history.day_flag(raw) != "inconsistent"                                   # the sheet's own check does not see it
        assert abs(front(raw) - sum(around) / 2) > 80                                    # what the wrong close does
        assert abs(front(fixed) - sum(around) / 2) < 25                                  # ... and the day without it
        # stored with the day, and shown on the page
        assert h._compute(only=[day]) == 1
        meta = st.mpc_days()[day]
        assert meta["cleaned"] == "TYSOC" and meta["carried"] == 1
        page = h.mpc()
        assert page["cleaned"][page["days"].index(day)] == "TYSOC" and page["carried"][page["days"].index(day)] == 1
    finally:
        svc.stop()


def _iso_day(d):
    return d.isoformat()


def test_a_database_of_the_previous_version_keeps_its_days(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE mpc_days (day TEXT PRIMARY KEY, basis TEXT NOT NULL, spot TEXT, tlref REAL, base REAL, "
               "decision INTEGER NOT NULL DEFAULT 0, quotes INTEGER, status TEXT, note TEXT, computed_at TEXT NOT NULL)")
    db.execute("INSERT INTO mpc_days VALUES ('2026-11-03', 'b', '2026-11-04', 35.8, 0.358, 0, 16, "
               "'Kota/takvim tutarsız – kontrolü incele', '', '2026-11-13 14:24:00')")
    db.commit()
    db.close()
    st = Store(path)
    old = st.mpc_days()["2026-11-03"]
    assert old["basis"] == "b" and old["control"] is None and old["tolerance"] is None and old["carried"] is None
    assert history.day_flag(old) == "inconsistent"                           # told by its status text
    st.mpc_save("2026-11-04", "b2", {"status": "OK", "quotes": 16, "control": 0.4, "tolerance": 5.0, "carried": 1}, [])
    new = st.mpc_days()["2026-11-04"]
    assert (new["control"], new["tolerance"], new["carried"]) == (0.4, 5.0, 1)
    st.close()
    assert sorted(Store(path).mpc_days()) == ["2026-11-03", "2026-11-04"]    # opening it again adds nothing twice


def test_end_of_day_matrix(hsvc):
    m = hsvc.history.matrix()
    assert m["asof"] == TODAY and m["ref"] == {"d1": "2026-11-02", "w1": "2026-10-27", "m1": "2026-10-05"}
    assert m["days"][0] == TODAY and m["days"][1] == "2026-11-02" and not m["live"] and not m["decision_day"]
    assert m["source"] == {"ois": "GFOF → Excel (Curncy)", "off": "ICPL → Excel (BGN)", "xccy": "ICPL → Excel (BGN)", "dibs_field": "YLD_YTM_MID"}
    recorded = hsvc.provider.history([("TYSOA Curncy", "PX_LAST"), ("TRYSAQ1 BGN Curncy", "PX_LAST")], "20261001", "20261103")
    curve = {r["tenor"]: r for r in m["curve"]}
    assert list(curve) == ["O/N", "T/N", "1W", "2W", "1M", "2M", "3M", "4M", "5M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "4Y", "5Y", "6Y", "7Y",
                            "8Y", "9Y", "10Y"]
    one = dict(recorded[("TYSOA Curncy", "PX_LAST")])
    e = curve["1M"]["ois"]
    assert e["last"] == one[TODAY] == 36.35 and e["ticker"] == "TYSOA Curncy" and e["day"] == TODAY and e["unit"] == "pct"
    assert close(e["d1"], (one[TODAY] - one["2026-11-02"]) * 100, 1e-9) and e["d1_from"] == one["2026-11-02"]
    assert close(e["w1"], (one[TODAY] - one["2026-10-27"]) * 100, 1e-9) and close(e["m1"], (one[TODAY] - one["2026-10-05"]) * 100, 1e-9)
    assert close(e["m1"], -80.0, 1e-9)                                  # 37.15 -> 36.35 over the month of the cut
    assert curve["1M"]["off"] is None and curve["18M"]["ois"] is None    # nothing recorded for these
    x = dict(recorded[("TRYSAQ1 BGN Curncy", "PX_LAST")])
    assert curve["1Y"]["off"]["kind"] == "xccy" and curve["1Y"]["off"]["last"] == x[TODAY] == 39.35
    assert close(curve["1Y"]["off"]["m1"], (39.35 - 38.8) * 100, 1e-9) and curve["1Y"]["ois"]["last"] == 35.52
    t = m["tlref"]
    assert (t["last"], t["day"], t["d1"]) == (35.8159, "2026-11-02", 0.0)   # today's fixing is not out: yesterday's stands
    assert close(t["m1"], (35.8159 - 36.8231) * 100, 1e-9) and close(t["w1"], (35.8159 - 35.8705) * 100, 1e-9)
    # ---- the meetings: last pricing and its changes, from the days the solver ran for
    rows = {r["day"]: r for r in hsvc.store.mpc_values(meetings=["2026-12-10"])}
    first = m["mpc"][0]
    assert first["meeting"] == "2026-12-10" and first["front"] and [x["meeting"] for x in m["mpc"]] == sorted(x["meeting"] for x in m["mpc"])
    assert close(first["step"]["last"], rows[TODAY]["step"], 1e-12) and close(first["step"]["d1"], rows[TODAY]["step"] - rows["2026-11-02"]["step"], 1e-9)
    assert close(first["step"]["w1"], rows[TODAY]["step"] - rows["2026-10-27"]["step"], 1e-9)
    assert close(first["step"]["m1"], rows[TODAY]["step"] - rows["2026-10-05"]["step"], 1e-9)
    assert close(first["level"]["m1"], (rows[TODAY]["level"] - rows["2026-10-05"]["level"]) * 10000, 1e-9)       # a level moves in bp
    assert close(first["cum"]["last"], rows[TODAY]["cum"], 1e-12)
    assert m["mpc"][-1]["step"]["m1"] is None                           # 21.10.2027 was out of reach a month ago
    # ---- bonds: the list of DİBS RV by maturity; no history offline, the workbook's own yield for the level
    bonds = m["bonds"]
    assert len(bonds) == 19 and [b["maturity"] or "9999" for b in bonds] == sorted(b["maturity"] or "9999" for b in bonds)
    assert all(b["last"] is None and b["d1"] is None for b in bonds) and sum(1 for b in bonds if b["bist"]) >= 14
    assert {b["unit"] for b in bonds if b["type"] == "T"} == {"px"} and {b["field"] for b in bonds if b["type"] == "S"} == {"YLD_YTM_MID"}

    # ---- another day, a weekend, a day without data, nonsense
    past = hsvc.history.matrix("2026-10-23")
    assert past["asof"] == "2026-10-23" and past["ref"]["d1"] == "2026-10-22" and past["mpc"][0]["meeting"] == "2026-12-10"
    assert close(past["tlref"]["d1"], (35.8498 - 36.8769) * 100, 1e-9)           # the cut arrived in the fixing
    assert close(past["curve"][4]["ois"]["last"], one["2026-10-23"], 1e-12) and past["curve"][4]["ois"]["m1"] is None
    assert close(past["mpc"][0]["step"]["d1"], rows["2026-10-23"]["step"] - rows["2026-10-22"]["step"], 1e-9)
    assert hsvc.history.matrix("2026-10-22")["decision_day"] is True
    assert hsvc.history.matrix("2026-10-25")["asof"] == "2026-10-23"             # a Sunday: the Friday before
    empty = hsvc.history.matrix("2025-06-02")
    assert empty["tlref"] is None and empty["mpc"] == [] and all(r["ois"] is None for r in empty["curve"])
    with pytest.raises(ServiceError):
        hsvc.history.matrix("dün")


def test_history_settings(hsvc):
    h = hsvc.history
    assert h.settings() == {"dibs_field": "YLD_YTM_MID", "lookback_days": 370}
    try:
        assert h.set_settings({"dibs_field": " yld cnv mid "})["dibs_field"] == "YLD_CNV_MID"
        assert {d.field for d in h.snapshot()["defs"] if d.group == "dibs" and d.unit == "pct"} == {"YLD_CNV_MID"}
        assert h.set_settings({"lookback_days": "120"}) == {"dibs_field": "YLD_CNV_MID", "lookback_days": 120}
        for bad in ({"dibs_field": "YLD;DROP"}, {"dibs_field": ""}, {"lookback_days": 5}, {"lookback_days": "çok"}):
            with pytest.raises(ValueError):
                h.set_settings(bad)
        assert h.settings() == {"dibs_field": "YLD_CNV_MID", "lookback_days": 120}
    finally:
        h.set_settings(dict(dibs_field="YLD_YTM_MID", lookback_days=370))
        h._kick.clear()


# ====================================================================================== the calendar
def steps_by_meeting(svc, user=None):
    """{meeting date: (U, V, W)} - the scenario steps typed per meeting, as the user sees them."""
    rows = list(range(10, 90))
    vals = cells(svc, ["OIS_MAIN!%s%d" % (c, r) for r in rows for c in "PUVW"], user)
    out = {}
    for k in range(len(rows)):
        p = vals[4 * k]
        if isinstance(p, float):
            out[serial_to_date(p).isoformat()] = tuple(vals[4 * k + 1:4 * k + 4])
    return out


def test_calendar_lists_the_meetings_held_and_ahead(hsvc):
    cal = hsvc.history.calendar()
    assert (cal["today"], cal["spot"], cal["next"], cal["slots"], cal["passed_in_list"]) == (TODAY, "2026-11-04", "2026-12-10", 80, 0)
    dates = [m["date"] for m in cal["meetings"]]
    assert dates == sorted(dates) and len(dates) == 95
    assert dates[:15] == list(DEFAULT_PAST_MEETINGS) and all(m["where"] == "archive" and m["passed"] for m in cal["meetings"][:15])
    first = cal["meetings"][15]
    assert first == {"date": "2026-12-10", "row": 10, "label": "MPC1", "passed": False, "where": "list"}
    assert cal["meetings"][-1]["row"] == 89 and cal["meetings"][-1]["label"] == "MPC80"
    assert hsvc.history.meetings() == dates


def test_calendar_edits_keep_what_was_typed_with_its_meeting(tmp_path):
    svc = make_service(tmp_path)
    try:
        h = svc.history
        ayse = svc.login("Ayşe Takvim")["user"]
        veli = svc.login("Veli Takvim")["user"]
        svc.set_inputs(ayse, "tto", [{"ref": "OIS_MAIN!U11", "value": "-75"}, {"ref": "OIS_MAIN!V12", "value": "-125"},
                                     {"ref": "OIS_MAIN!W12", "value": ""}, {"ref": "OIS_MAIN!U40", "value": "10"}])
        svc.save_scenario(ayse, "takvim öncesi")
        start = h.meetings()
        base = {None: steps_by_meeting(svc), ayse: steps_by_meeting(svc, ayse), veli: steps_by_meeting(svc, veli)}
        assert base[ayse]["2027-01-21"][0] == -75.0 and base[ayse]["2027-03-18"][1:] == (-125.0, None)
        assert base[None]["2027-03-18"] == (None, None, None) and base[veli] == base[None]      # nobody starts with a step

        def check(now, moved=()):
            """Every meeting that is still there has the steps it had; ``moved``: (old date, new date)."""
            renamed = dict(moved)
            for who in (None, ayse, veli):
                got = steps_by_meeting(svc, who)
                for meeting, typed in base[who].items():
                    target = renamed.get(meeting, meeting)
                    if target in now:
                        assert got[target] == typed, (who, meeting)

        # ---- 1. the actual date of a meeting becomes known: one row changes, nothing moves
        new = [d if d != "2027-03-18" else "2027-03-25" for d in start]
        res = h.set_calendar(ayse, new)
        assert (res["meetings"], res["archive"], res["rolled"], res["moved"], res["dropped"], res["changed"]) == (80, 15, [], 0, 0, 0)
        assert cells(svc, ["OIS_MAIN!P12"]) == [float(date_to_serial(D("2027-03-25")))]
        assert h.meetings() == new
        check(set(new), moved=[("2027-03-18", "2027-03-25")])
        assert svc.store.shared_meta("tto", ["OIS_MAIN!P12"])["updated_by"] == ayse

        # ---- 2. an extra meeting is put in between: the later meetings move down a row, their steps with them
        extra = sorted(new[:-1] + ["2027-02-11"])               # 80 slots: the last one makes room
        res = h.set_calendar(veli, ["11.02.2027"] + [d for d in new[:-1]])
        assert res["meetings"] == 80 and res["changed"] == 78 and res["moved"] == 3 and res["dropped"] == 0 and res["scenarios"] == 1
        assert h.meetings() == extra
        assert cells(svc, ["OIS_MAIN!P11", "OIS_MAIN!P12", "OIS_MAIN!P13"]) == [float(date_to_serial(D(d))) for d in
                                                                              ("2027-01-21", "2027-02-11", "2027-03-25")]
        check(set(extra), moved=[("2027-03-18", "2027-03-25")])
        for who in (None, ayse, veli):
            assert steps_by_meeting(svc, who)["2027-02-11"] == (None, None, None)       # a new meeting: nothing typed for it
        assert svc.store.user_inputs(ayse, "tto")[("tto", "OIS_MAIN!V13")] == -125.0    # her March step went from row 12 to 13
        assert ("tto", "OIS_MAIN!U11") in svc.store.user_inputs(ayse, "tto")           # January stayed in row 11
        assert svc.load_scenario(ayse, "takvim öncesi")["cells"] == 4
        check(set(extra), moved=[("2027-03-18", "2027-03-25")])                         # the saved scenario moved as well

        # ---- 3. back to the original list: everything is where it was, nothing is left behind
        res = h.set_calendar(ayse, start)
        assert res["meetings"] == 80 and h.meetings() == start
        for who in (None, ayse, veli):
            got = steps_by_meeting(svc, who)
            last = start[-1]
            assert {k: v for k, v in got.items() if k != last} == {k: v for k, v in base[who].items() if k != last}, who
        leftovers = [k for k in svc.store.shared_inputs("tto") if k[1].startswith("OIS_MAIN!") and k[1][9] in "UVW"]
        assert leftovers == []                                   # the file's own steps are the file's again
        assert svc.store.user_inputs(ayse, "tto") == {("tto", "OIS_MAIN!U11"): -75.0, ("tto", "OIS_MAIN!V12"): -125.0,
                                                      ("tto", "OIS_MAIN!W12"): None, ("tto", "OIS_MAIN!U40"): 10.0}

        # ---- what is refused
        with pytest.raises(ServiceError) as exc:
            h.set_calendar(ayse, start + ["2037-01-15"])
        assert "en fazla 80" in str(exc.value)
        with pytest.raises(ServiceError):
            h.set_calendar(ayse, ["2025-01-23"])                 # no meeting ahead
        with pytest.raises(ServiceError) as exc:
            h.set_calendar(ayse, start[:-1] + ["31.02.2027"])
        assert "anlaşılamadı" in str(exc.value)
        with pytest.raises(ServiceError) as exc:
            h.set_calendar("kimse", start)
        assert exc.value.status == 401
        assert h.meetings() == start

        # ---- a meeting of the past can be added to (or taken out of) the archive
        res = h.set_calendar(ayse, [d for d in start if d != "2025-01-23"] + ["2024-12-26"])
        assert res["archive"] == 15 and h.meetings()[0] == "2024-12-26" and "2025-01-23" not in h.meetings()
        again = Service(Settings(data_dir=str(tmp_path), mode="replay", history=False))        # it survives a restart
        try:
            assert again.history.meetings()[0] == "2024-12-26"
        finally:
            again.stop()
    finally:
        svc.stop()


def test_announced_dates_correct_the_calendar(hsvc):
    """Pasting the central bank's dates: each corrects the meeting ahead nearest to it (at most 45 days away, in
    order); the meetings not announced yet and the past stay; nothing is saved by looking."""
    h = hsvc.history
    cal = h.calendar()
    cur = [m["date"] for m in cal["meetings"]]
    assert cal["history_days"] == len(hsvc.store.mpc_days())
    res = h.preview_calendar(cur, ["14.01.2027", "2027-03-11", "22.04.2027", "23.10.2026"], "correct")
    assert res["corrected"] == [["2027-01-21", "2027-01-14"], ["2027-03-18", "2027-03-11"]]
    assert (res["added"], res["removed"], res["unchanged"], res["skipped"], res["spot"]) == ([], [], 1, ["2026-10-23"], "2026-11-04")
    assert len(res["dates"]) == len(cur) and res["dates"] == sorted(res["dates"])
    assert res["dates"][:15] == cur[:15]                                                    # the meetings held: as they were
    assert [d for d in res["dates"] if d >= "2028"] == [d for d in cur if d >= "2028"]     # the years not announced yet stay
    assert h.calendar()["meetings"] == cal["meetings"]                                      # looking saves nothing
    res = h.preview_calendar(cur, ["2026-12-10"], "correct")
    assert (res["corrected"], res["added"], res["unchanged"], res["dates"]) == ([], [], 1, cur)
    # a date with no meeting within 45 days is a new meeting; the workbook's 80 rows must have room for it
    with pytest.raises(ServiceError) as exc:
        h.preview_calendar(cur, ["2027-01-21", "2027-02-11", "2027-03-18"], "correct")
    text = str(exc.value)
    assert "en fazla 80" in text and "81 olur" in text and "11.02.2027" in text and cur[-1][8:] + "." + cur[-1][5:7] in text
    shorter = cur[:-1]
    res = h.preview_calendar(shorter, ["2027-01-21", "2027-02-11", "2027-03-18"], "correct")
    assert (res["corrected"], res["added"], res["unchanged"], len(res["dates"])) == ([], ["2027-02-11"], 2, len(cur))
    # the other two ways: add what is missing, or replace every meeting ahead
    res = h.preview_calendar(shorter, ["2027-02-11", "21.01.2027"], "merge")
    assert (res["added"], res["unchanged"], res["corrected"]) == (["2027-02-11"], 1, [])
    res = h.preview_calendar(cur, ["2026-12-10", "2027-01-14"], "future")
    assert res["dates"] == cur[:15] + ["2026-12-10", "2027-01-14"]
    assert (len(res["removed"]), res["added"], res["unchanged"]) == (79, ["2027-01-14"], 1)
    for args in ((cur, [], "correct"), (cur, ["31.02.2027"], "correct"), (cur, ["2027-01-14"], "yanlış")):
        with pytest.raises(ServiceError):
            h.preview_calendar(*args)


def test_announced_dates_carry_the_steps_typed_for_their_meetings(tmp_path):
    svc = make_service(tmp_path)
    try:
        h = svc.history
        ayse = svc.login("Ayşe Takvim")["user"]
        svc.set_inputs(ayse, "tto", [{"ref": "OIS_MAIN!U11", "value": "-75"}, {"ref": "OIS_MAIN!V12", "value": "-125"}])
        before = {None: steps_by_meeting(svc), ayse: steps_by_meeting(svc, ayse)}
        res = h.preview_calendar(h.meetings(), ["14.01.2027", "11.03.2027", "22.04.2027"], "correct")
        saved = h.set_calendar(ayse, res["dates"])
        assert (saved["meetings"], saved["moved"], saved["changed"], saved["dropped"]) == (80, 0, 0, 0)  # rows stay, dates change
        assert h.meetings() == res["dates"]
        for who in (None, ayse):
            after = steps_by_meeting(svc, who)
            assert after["2027-01-14"] == before[who]["2027-01-21"] and after["2027-03-11"] == before[who]["2027-03-18"]
            assert after["2027-04-22"] == before[who]["2027-04-22"]
        assert before[ayse]["2027-01-21"][0] == -75.0 and steps_by_meeting(svc, ayse)["2027-01-14"][0] == -75.0
    finally:
        svc.stop()


def panel_errors(svc, view_id, user=None):
    """(panels that failed, the cells of the page that show an error)."""
    page = svc.view(user, view_id)
    bad = set()
    for p in page["panels"]:
        data = p.get("data") if p["type"] in ("table", "notes") else None
        for i, row in enumerate((data or {}).get("rows", [])):
            for j, c in enumerate(row):
                if c.get("k") == "e":
                    bad.add("%s!%s%d" % (data.get("sheet") or page["sheet"], data["c"][j], data["r"][i]))
    return [p["id"] for p in page["panels"] if p.get("error")], bad


def test_a_meeting_that_passed_leaves_the_list_by_itself(tmp_path):
    """MPC1 is always the next meeting: when one has passed (its date is before the OIS spot), the running
    dashboard rolls the list itself - at start and when the day turns - and what was typed moves with its meeting."""
    import time as _time
    svc = make_service(tmp_path)
    try:
        h = svc.history
        book = svc.books["tto"]
        user = svc.login("Otomatik Deneme")["user"]
        svc.set_inputs(user, "tto", [{"ref": "OIS_MAIN!U11", "value": "-75"}])               # her step for 21.01.2027
        assert h.auto_roll() is None and svc.store.get("mpc.autoroll") is None              # nothing has passed yet

        def move_spot():                                                                     # Bloomberg's settle date, then
            book.declare("OIS_MAIN!W2", scope="shared", group="test-spot")
            book.engine.set_inputs({book.cell("OIS_MAIN!W2"): "14.12.2026"})
        svc.et.call(move_spot)
        svc.bump()
        cal = h.calendar()
        assert (cal["spot"], cal["passed_in_list"], cal["meetings"][15]["label"]) == ("2026-12-14", 1, "MPC1")
        svc.start()                                                                          # the dashboard starts: it rolls
        for _ in range(100):
            if not h.calendar()["passed_in_list"]:
                break
            _time.sleep(0.2)
        cal = h.calendar()
        assert (cal["next"], cal["passed_in_list"], cal["autoroll_error"]) == ("2027-01-21", 0, "")
        assert cal["meetings"][15]["where"] == "archive" and cal["meetings"][15]["date"] == "2026-12-10"
        assert cal["meetings"][16] == {"date": "2027-01-21", "row": 10, "label": "MPC1", "passed": False, "where": "list"}
        assert cal["autoroll"]["rolled"] == ["2026-12-10"] and cal["autoroll"]["first"] == "2027-01-21"
        assert svc.store.user_inputs(user, "tto") == {("tto", "OIS_MAIN!U10"): -75.0}      # her step went with its meeting
        assert svc.store.shared_meta("tto", ["OIS_MAIN!P10"])["updated_by"] == h.AUTO_USER
        assert h.auto_roll() is None                                                         # once is enough
    finally:
        svc.stop()


def test_the_roll_follows_the_spot_within_the_day(tmp_path, monkeypatch):
    """Bloomberg's settle date (the OIS spot) moves some time after midnight, not at the turn of the day: the running
    dashboard looks again every few minutes, so a meeting that passed leaves the list on its day."""
    monkeypatch.setattr(Service, "ROLL_CHECK_SECONDS", 0.5)
    svc = make_service(tmp_path)
    try:
        h = svc.history
        book = svc.books["tto"]
        svc.start()
        time.sleep(1.5)                                                                     # the look at start: nothing
        assert (h.calendar()["next"], h.calendar()["passed_in_list"]) == ("2026-12-10", 0)

        def move_spot():
            book.declare("OIS_MAIN!W2", scope="shared", group="test-spot")
            book.engine.set_inputs({book.cell("OIS_MAIN!W2"): "11.12.2026"})
        svc.et.call(move_spot)
        svc.bump()
        assert h.calendar()["passed_in_list"] == 1                                          # passed, still listed
        for _ in range(100):
            if not h.calendar()["passed_in_list"]:
                break
            time.sleep(0.2)
        cal = h.calendar()
        assert (cal["next"], cal["passed_in_list"], cal["autoroll"]["rolled"]) == ("2027-01-21", 0, ["2026-12-10"])
    finally:
        svc.stop()


def test_a_meeting_date_typed_on_the_ois_page_goes_through_the_calendar(tmp_path):
    """A date typed over a meeting on the OIS page changes the list the way the calendar does: the steps typed per
    meeting stay with their meeting.  The file's dates are not put back over the list (they are those of the day
    the file was saved: the steps would no longer be their meetings')."""
    from conftest import cell
    svc = make_service(tmp_path)
    try:
        user = svc.login("Takvim Deneme")["user"]

        def p(r):
            return serial_to_date(cell(svc, "OIS_MAIN!P%d" % r)).isoformat()
        assert [p(r) for r in (10, 11, 12, 13)] == ["2026-12-10", "2027-01-21", "2027-03-18", "2027-04-22"]
        svc.set_inputs(user, "tto", [{"ref": "OIS_MAIN!U11", "value": "-75"}, {"ref": "OIS_MAIN!U12", "value": "-125"}])
        # 21.01.2027 moves a week: its step goes with it
        res = svc.set_inputs(user, "tto", [{"ref": "OIS_MAIN!P11", "value": "28.01.2027"}])
        assert res["errors"] == [] and res["calendar"]["dropped"] == 0 and p(11) == "2027-01-28"
        mine = svc.store.user_inputs(user, "tto")
        assert mine[("tto", "OIS_MAIN!U11")] == -75.0 and mine[("tto", "OIS_MAIN!U12")] == -125.0
        # 18.03.2027 leaves the list: the meetings below move up, each with its own step - 18.03's goes with it
        svc.set_inputs(user, "tto", [{"ref": "OIS_MAIN!P12", "value": ""}])
        assert [p(r) for r in (11, 12)] == ["2027-01-28", "2027-04-22"]
        mine = svc.store.user_inputs(user, "tto")
        assert mine[("tto", "OIS_MAIN!U11")] == -75.0 and ("tto", "OIS_MAIN!U12") not in mine
        res = svc.set_inputs(user, "tto", [{"ref": "OIS_MAIN!P13", "value": "yarın"}])
        assert res["applied"] == 0 and "anlaşılamadı" in res["errors"][0]
        with pytest.raises(ServiceError) as exc:
            svc.reset_inputs(user, "tto", ["OIS_MAIN!P10:P12"], shared=True)
        assert "Toplantı takvimi" in str(exc.value) and p(12) == "2027-04-22"
    finally:
        svc.stop()


def test_after_a_meeting_has_passed_and_after_the_roll(tmp_path):
    """The first meeting of the list passes: the pages go on with the next one; the roll takes the passed
    meeting out of the list and nothing that belongs to a meeting changes."""
    svc = make_service(tmp_path)
    try:
        h = svc.history
        book = svc.books["tto"]
        user = svc.login("Roll Deneme")["user"]
        other = svc.login("Diğer Roll")["user"]
        pages = ("ois", "dv01", "carry", "motor")              # the pages that are built on the list of meetings
        usual = {v: panel_errors(svc, v) for v in pages}
        assert usual["ois"] == ([], set())
        h.sync(only=["2026-11-02", TODAY])
        plan_before = [(p["day"], p["basis"]) for p in h._plan(h.snapshot())[0]]
        assert len(plan_before) == 21

        # ---- the OIS spot moves beyond the meeting of 10.12.2026 (what Bloomberg's settle date will say then)
        def move_spot():
            book.declare("OIS_MAIN!W2", scope="shared", group="test-spot")
            book.engine.set_inputs({book.cell("OIS_MAIN!W2"): "14.12.2026"})
        svc.et.call(move_spot)
        svc.bump()
        # a date typed into the page before (the "two dates" calculator starts on 30.11.2026) is now behind the
        # spot: that block shows #N/A until a new date is typed - as it does in Excel - and nothing else does
        stale = panel_errors(svc, "ois")
        assert stale[0] == [] and stale[1] == {"OIS_MAIN!%s%d" % (c, r) for c in "BCDF" for r in range(125, 130)}

        def new_dates():
            book.engine.set_inputs({book.cell("OIS_MAIN!B122"): float(date_to_serial(D("2026-12-14"))),
                                    book.cell("OIS_MAIN!B123"): float(date_to_serial(D("2027-03-15")))})
        svc.et.call(new_dates)
        svc.bump()
        assert cells(svc, ["OIS_MAIN!B2"]) == [float(date_to_serial(D("2026-12-14")))]
        q10, r10, s10, q11, r11, s11, status = cells(svc, ["OIS_MAIN!Q10", "OIS_MAIN!R10", "OIS_MAIN!S10", "OIS_MAIN!Q11", "OIS_MAIN!R11",
                                                         "OIS_MAIN!S11", "OIS_MAIN!AU12"])
        assert (q10, r10, s10) == ("geçti", "geçti", "") and status == "OK"
        tlref = cells(svc, ["OIS_MAIN!J2"])[0]
        assert isinstance(r11, float) and close(r11, (s11 - tlref) * 10000, 1e-9)       # the next meeting is the first one now
        for v, (errors, bad) in usual.items():                   # the pages go on: no panel fails, no new error cells
            now = panel_errors(svc, v)
            assert now[0] == [] and now[1] <= bad, (v, sorted(now[1] - bad)[:10])
        cal = h.calendar()
        assert (cal["spot"], cal["next"], cal["passed_in_list"]) == ("2026-12-14", "2027-01-21", 1)
        assert cal["meetings"][15] == {"date": "2026-12-10", "row": 10, "label": "MPC1", "passed": True, "where": "list"}

        # ---- scenario steps of a user and a saved scenario
        svc.set_inputs(user, "tto", [{"ref": "OIS_MAIN!U11", "value": "-75"}, {"ref": "OIS_MAIN!U12", "value": "-125"},
                                     {"ref": "OIS_MAIN!V11", "value": ""}, {"ref": "OIS_MAIN!W40", "value": "25"}])
        svc.save_scenario(user, "roll öncesi")

        def by_meeting(who):
            """{meeting ahead: (implied bps, implied level, TLREF S1, S2, S3, step S1, S2, S3)}"""
            rows = list(range(10, 90))
            vals = cells(svc, ["OIS_MAIN!%s%d" % (c, r) for r in rows for c in "PQRSXYZUVW"], who)
            out = {}
            for k in range(len(rows)):
                p, q = vals[10 * k], vals[10 * k + 1]
                if isinstance(p, float) and q != "geçti":
                    out[serial_to_date(p).isoformat()] = tuple(vals[10 * k + 2:10 * k + 10])
            return out

        before = {who: by_meeting(who) for who in (None, user, other)}
        assert len(before[None]) == 79 and before[user]["2027-01-21"][5] == -75.0 and before[user] != before[other]

        # ---- the roll
        res = h.roll_calendar(user)
        assert res["rolled"] == ["2026-12-10"] and (res["meetings"], res["archive"], res["first"]) == (79, 16, "2027-01-21")
        assert (res["moved"], res["dropped"], res["scenarios"]) == (4, 0, 1)
        cal = h.calendar()
        assert (cal["next"], cal["passed_in_list"]) == ("2027-01-21", 0)
        assert cal["meetings"][15] == {"date": "2026-12-10", "row": None, "label": "", "passed": True, "where": "archive"}
        assert cal["meetings"][16] == {"date": "2027-01-21", "row": 10, "label": "MPC1", "passed": False, "where": "list"}
        assert cells(svc, ["OIS_MAIN!P10", "OIS_MAIN!P88", "OIS_MAIN!P89", "OIS_MAIN!Q10"])[:3] == \
            [float(date_to_serial(D("2027-01-21"))), float(date_to_serial(D("2036-10-19"))), None]
        # what was priced for, and typed for, every meeting ahead is exactly what it was - for everybody
        for who in (None, user, other):
            assert by_meeting(who) == before[who], who
        assert svc.store.user_inputs(user, "tto") == {("tto", "OIS_MAIN!U10"): -75.0, ("tto", "OIS_MAIN!U11"): -125.0,
                                                      ("tto", "OIS_MAIN!V10"): None, ("tto", "OIS_MAIN!W39"): 25.0}
        # a scenario saved before the roll still means the same meetings
        svc.reset_inputs(user, "tto")
        assert by_meeting(user) == before[None]
        svc.load_scenario(user, "roll öncesi")
        assert by_meeting(user) == before[user]
        for v, (errors, bad) in usual.items():
            now = panel_errors(svc, v)
            assert now[0] == [] and now[1] <= bad, (v, sorted(now[1] - bad)[:10])

        # ---- the history: series belong to the date of their meeting, the roll changes nothing in them
        assert [(p["day"], p["basis"]) for p in h._plan(h.snapshot())[0]] == plan_before
        assert h.sync(only=["2026-11-02", TODAY])["computed"] == 0
        page = h.mpc()
        dec = next(m for m in page["meetings"] if m["date"] == "2026-12-10")
        assert dec["passed"] and dec["where"] == "archive" and dec["n"] == 2 and dec["last_day"] == TODAY
        assert next(m for m in page["meetings"] if m["date"] == "2027-01-21")["label"] == "MPC1"
        # rolling again finds nothing to do; a second roll is harmless
        again = h.roll_calendar(other)
        assert again["rolled"] == [] and again["moved"] == 0 and by_meeting(user) == before[user]
        # and it is all there after a restart
        svc2 = Service(Settings(data_dir=str(tmp_path), mode="replay", history=False))
        try:
            assert svc2.history.calendar()["meetings"][16]["row"] == 10
            assert steps_by_meeting(svc2, user)["2027-01-21"][0] == -75.0
            assert steps_by_meeting(svc2)["2027-03-18"] == (None, None, None)              # the file brings no step of its own
        finally:
            svc2.stop()
    finally:
        svc.stop()


# ====================================================================================== live: Bloomberg history
def _weekdays(first, last):
    d = first
    while d <= last:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


def _fake_history(svc, snap):
    """A year of closes for every series the workbook asks for (made up, the same on every run).

    The OIS curve is the one the workbook was saved with, moved up and down in parallel over time - so that
    it is a curve the solver can fit, and today's close is the quote of the OIS page."""
    start, today = D("2025-10-20"), D(TODAY)
    holidays = {D("2026-01-01"), D("2026-10-29")}
    days = [d for d in _weekdays(start, today) if d not in holidays]
    hist = {}
    sheet = svc.books["tto"].model.sheets[svc.books["tto"].model.sheet_index["OIS_MAIN"]]
    saved = {root: sheet.cached[parse_a1("B%d" % r)] * 100.0 for r, root in snap["roots"].items() if root}
    saved[snap["stub"]["1W"]] = sheet.cached[parse_a1("AU13")] * 100.0
    saved[snap["stub"]["2W"]] = sheet.cached[parse_a1("AU14")] * 100.0

    def drift(d):
        back = (today - d).days
        return 0.004 * back + 0.05 * math.sin(back / 9.0)

    def curve(level, months, seed):
        return [(d, round(level - 0.25 * math.log(1.0 + months) + drift(d) + 0.02 * math.sin((d - start).days / 7.0 + seed), 4)) for d in days]

    for k, d in enumerate(snap["defs"]):
        if d.group == "Quant":
            continue                                                        # the quant package's own series: none here
        if d.group == "ref":
            # the fixing of the workbook's day; one point higher until the meeting of 22 October; today's is not out yet
            hist[(d.ticker, d.field)] = [(x, 36.8159 if x <= D("2026-10-22") else 35.8159) for x in days if x < today]
        # the curves have history on the workbook's own tickers only (the backups): GFOF / ICPL give none here, so
        # each series is read from its backup as it is
        elif d.group == "ois":
            hist[(d.alts[-1], d.field)] = [(x, round(saved[d.root] + drift(x), 4)) for x in days]
        elif d.group in ("off", "xccy"):
            hist[(d.alts[-1], d.field)] = curve(42.0, d.months, k)
        elif d.info["isin"] == "TRT150328T24":
            hist[(d.alts[0], d.field)] = curve(41.0, 16, k)                 # only the ticker without a source has history
        elif d.info["isin"] != "TRT081128T15":                               # ... and one bond has none at all
            hist[(d.ticker, d.field)] = curve(41.5, 24 + k, k)
    return hist, days


def test_live_the_history_comes_from_bloomberg(tmp_path):
    server = fake_blpapi.Server()
    provider = BloombergProvider(blpapi_module=fake_blpapi.module(server))
    provider.start()
    today = float(date_to_serial(D(TODAY)))
    clock = Clock(today + 0.5)
    clock.today = lambda: today
    svc = Service(Settings(data_dir=str(tmp_path), mode="live", history=False), provider=provider, clock=clock)
    try:
        h = svc.history
        snap = h.snapshot()
        quant = len(series_specs())                                          # the quant package's own series (two years back)
        assert svc.mode == "live" and snap["today"] == D(TODAY) and len(snap["defs"]) == 59 + quant
        hist, days = _fake_history(svc, snap)
        server.history.update(hist)

        def asked():
            return [r for r in server.requests if r["op"] == "HistoricalDataRequest"]

        # ---- the first pass: a year of everything, a handful of requests (the quant series: two years, five a pass)
        res = h.sync(only=[TODAY])
        first = [r for r in asked() if r["options"]["startDate"] != "20241024"]
        assert len(asked()) - len(first) == 1 and len(asked()[-1]["securities"]) == History.BACKFILL_PER_SYNC
        tickers = {s for r in first for s in r["securities"]}
        # (the bonds go out the way the API names them: the sheet's "TRT150328T24 @ISL1 ISIN" is Excel's spelling)
        assert {"TYSOA Curncy", "TYSOA GFOF Curncy", "BISTTREF Index", "TRYI1M BGN Curncy", "TRYSAQ5 BGN Curncy",
                "/isin/TRT150328T24@ISL1", "/isin/TRT150328T24"} <= tickers
        assert not [t for t in tickers if t.endswith(" ISIN")]
        assert {"TRYI1M ICPL Curncy", "TRYSAQ5 ICPL Curncy"} <= tickers                                  # the main sources too
        assert len(tickers) == 117 and len(first) <= 5                       # 50 securities per request, one field each
        assert {r["options"]["startDate"] for r in first} == {"20251029"} and {r["options"]["endDate"] for r in first} == {"20261103"}
        assert all("nonTradingDayFillOption" not in r["options"] for r in first)          # trading days only, nothing filled in
        assert {tuple(r["fields"]) for r in first} == {("PX_LAST",), ("YLD_YTM_MID",)}
        stored = svc.store.hist_bounds()
        in_window = [d for d in days if d >= D("2025-10-29")]
        assert stored["TYSOA Curncy|PX_LAST"] == (in_window[0].isoformat(), TODAY, len(in_window))
        assert res["fetched"] == sum(b[2] for b in stored.values()) and len(stored) == 58
        assert "TYSOA GFOF Curncy|PX_LAST" not in stored and "TRT150328T24 @ISL1 ISIN|YLD_YTM_MID" not in stored
        assert stored["BISTTREF Index|PX_LAST"][1] == "2026-11-02"

        # ---- the matrix: every block has levels and changes, by the 1 / 5 / 21 week day rule
        m = h.matrix()
        assert m["asof"] == TODAY and m["live"] and m["ref"] == {"d1": "2026-11-02", "w1": "2026-10-27", "m1": "2026-10-05"}
        curve = {r["tenor"]: r for r in m["curve"]}
        for tenor, side, ticker in (("1M", "ois", "TYSOA Curncy"), ("10Y", "ois", "TYSO10 Curncy"), ("1W", "off", "TRYI1W BGN Curncy"),
                                    ("5Y", "off", "TRYSAQ5 BGN Curncy")):
            series = dict((d.isoformat(), v) for d, v in hist[(ticker, "PX_LAST")])
            e = curve[tenor][side]
            assert e["ticker"] == ticker and e["last"] == series[TODAY]
            assert close(e["d1"], (series[TODAY] - series["2026-11-02"]) * 100, 1e-9)
            assert close(e["w1"], (series[TODAY] - series["2026-10-27"]) * 100, 1e-9)
            assert close(e["m1"], (series[TODAY] - series["2026-10-05"]) * 100, 1e-9)
        assert all(r["ois"] for r in m["curve"] if r["months"] >= 1 and r["tenor"] not in ("4M", "5M"))
        assert all(r["off"] for r in m["curve"] if r["tenor"] != "18M")
        assert (m["tlref"]["last"], m["tlref"]["d1"], m["tlref"]["w1"]) == (35.8159, 0.0, 0.0) and close(m["tlref"]["m1"], -100.0, 1e-9)
        bonds = {b["isin"]: b for b in m["bonds"]}
        assert bonds["TRT150328T24"]["ticker"] == "TRT150328T24 ISIN" and bonds["TRT150328T24"]["last"] is not None   # the fallback ticker
        assert bonds["TRT081128T15"]["last"] is None and sum(1 for b in bonds.values() if b["last"] is not None) == 18
        # a week day without any close (the holiday) takes the close before it
        hol = h.matrix("2026-10-30")
        assert hol["ref"]["d1"] == "2026-10-29" and close(hol["curve"][4]["ois"]["d1_from"], dict((d.isoformat(), v) for d, v in
                                                                                                hist[("TYSOA Curncy", "PX_LAST")])["2026-10-28"], 1e-12)

        # ---- the solver ran for today with all 18 quotes
        assert res["computed"] == 1
        meta = svc.store.mpc_days()[TODAY]
        assert (meta["status"], meta["quotes"], meta["spot"], meta["tlref"]) == ("OK", 18, "2026-11-04", 35.8159)
        rows = svc.store.mpc_values(TODAY, TODAY)
        assert len(rows) >= 75 and rows[0]["meeting"] == "2026-12-10" and rows[0]["front"] == 1
        assert all(0.10 < r["level"] < 0.60 for r in rows) and -200 < rows[0]["step"] < 0
        # the holidays of the past are read off the fixings: 29.10 was no business day, so 28.10 settles on 30.10
        plan = {p["day"].isoformat(): p for p in h._plan(h.snapshot())[0]}
        assert "2026-10-29" not in plan and "2026-01-01" not in plan and plan["2026-10-28"]["spot"] == D("2026-10-30")
        assert plan["2026-10-21"]["meetings"][0] == D("2026-10-22") and len(plan) == len(in_window)

        # ---- the next pass asks for the new days only - from each series' last close on, that close again (and the
        #      next five quant series); series without any history are left alone for the rest of the day
        n = len(asked())
        res = h.sync(only=[TODAY])
        later = [r for r in asked()[n:] if r["options"]["startDate"] != "20241024"]
        assert res == {"fetched": 0, "computed": 0, "rev": h.rev} and len(asked()[n:]) - len(later) == 1
        assert {r["options"]["startDate"] for r in later} == {"20261031", "20261030"} and len(later) <= 3      # (TLREF: 2 Nov)
        assert not ({"TYSOA GFOF Curncy", "TRT150328T24 @ISL1 ISIN"} & {s for r in later for s in r["securities"]})

        # ---- a close moves (today's last price): one row is stored, today is solved again
        sec = ("TYSO1 Curncy", "PX_LAST")
        server.history[sec] = server.history[sec][:-1] + [(D(TODAY), server.history[sec][-1][1] - 0.25)]
        before = svc.store.mpc_values(TODAY, TODAY)[0]["step"]
        res = h.sync(only=[TODAY])
        assert (res["fetched"], res["computed"]) == (1, 1)
        assert svc.store.mpc_values(TODAY, TODAY)[0]["step"] != before
        assert h.matrix()["curve"][11]["ois"]["last"] == server.history[sec][-1][1]

        # ---- asking for an update by hand tries the series without history again
        n = len(asked())
        h._empty.clear()
        h.sync(only=[TODAY])
        assert "TYSOA GFOF Curncy" in {s for r in asked()[n:] for s in r["securities"]}
        st = h.status()
        assert st["mode"] == "live" and st["mpc_days"] == 1 and st["mpc_partial"] == 0 and st["error"] == ""
        # Bloomberg's hits (security × field per request) of the four passes, part by part instead of one round number:
        # the workbook's own reference data, every pair asked once - however many fields the workbook uses (the bid /
        # ask sizes added some) -, and what the history asked: exactly what its rules say
        hist_hits = sum(len(r["securities"]) for r in asked())
        refs = [(s, f, r["overrides"]) for r in server.requests if r["op"] != "HistoricalDataRequest" for s in r["securities"] for f in r["fields"]]
        print("hits: %d = %d reference + %d history" % (provider.status()["hits_today"], len(refs), hist_hits))
        assert provider.status()["hits_today"] == server.hits() == len(refs) + hist_hits and len(refs) == len(set(refs))
        q, with_data, without = History.BACKFILL_PER_SYNC, len(svc.store.hist_bounds()), 117 - 58
        # first pass: every series of the workbook in full and five quant ones; then the last days of the 58 with
        # history and five more quant series, twice; by hand: the last days again, the 59 workbook series without
        # history again and five more quant series (those never asked go first)
        assert with_data == 58 and hist_hits == (117 + q) + 2 * (with_data + q) + (with_data + without + q)
    finally:
        svc.stop()


def test_bloomberg_history_requests_that_time_out_are_picked_up_later():
    server = fake_blpapi.Server()
    server.history[("AAA Curncy", "PX_LAST")] = [(D("2026-11-02"), 1.0), (D("2026-11-03"), 2.0)]
    server.silent = True                                                   # the terminal does not answer
    p = BloombergProvider(blpapi_module=fake_blpapi.module(server), request_timeout=0.4)
    p.start()
    try:
        t0 = time.time()
        assert p.history([("AAA Curncy", "PX_LAST")], "20261101", "20261103", timeout=0.3) == {}
        assert time.time() - t0 < 2.0
        server.silent = False                                              # ... and comes back: the request is sent again
        got = p.history([("AAA Curncy", "PX_LAST"), ("YOK Curncy", "PX_LAST")], "20261101", "20261103", timeout=10.0)
        assert got == {("AAA Curncy", "PX_LAST"): [("2026-11-02", 1.0), ("2026-11-03", 2.0)]}      # no history: left out
        assert p.history([("AAA Curncy", "PX_LAST")], "20261103", "20261103", timeout=10.0) == {("AAA Curncy", "PX_LAST"): [("2026-11-03", 2.0)]}
        assert not p.busy() and p.drain_changes() == []                    # nothing of it reaches the workbook
        assert not [k for k in p._values if k[0] == "BDH"]
    finally:
        p.stop()


# ====================================================================================== HTTP
@pytest.fixture(scope="module")
def client(hsvc):
    from starlette.testclient import TestClient

    from tto.server import create_app
    _svc[:] = [hsvc]
    with TestClient(create_app(hsvc), headers=auth(hsvc, "Tarihçe Okuyucu")) as c:
        yield c


_svc = []


def hdr(user):
    return auth(_svc[0], user)


def test_history_api(client, hsvc, monkeypatch):
    user = hsvc.login("Tarihçe API")["user"]
    pages = {p["id"]: p for p in client.get("/api/nav").json()["pages"]}
    assert pages["eod"]["group"] == "Masa" and pages["mpc"]["group"] == "TRY Faiz" and pages["settings"]["group"] == "Araçlar"
    for path in ("/static/js/pages/history.js",):
        assert client.get(path).status_code == 200
    st = client.get("/api/history/status").json()
    assert st["phase"] == "idle" and st["mpc_days"] == len(DAYS) and st["running"] is False and st["auto"] is False
    m = client.get("/api/history/matrix").json()
    assert m["asof"] == TODAY and len(m["curve"]) == 22 and len(m["bonds"]) == 19 and m["mpc"][0]["meeting"] == "2026-12-10"
    assert client.get("/api/history/matrix", params={"asof": "2026-10-23"}).json()["asof"] == "2026-10-23"
    assert client.get("/api/history/matrix", params={"asof": "x"}).status_code == 400
    page = client.get("/api/history/mpc", params={"n": 3}).json()
    assert page["days"] == DAYS and len(page["meetings"]) == 4
    assert client.get("/api/history/mpc", params={"days": "çok"}).status_code == 400
    # 59 series of the workbook, 58 of them with a backup ticker; and the quant package's own (no backups)
    assert len(client.get("/api/history/series").json()["series"]) == 117 + len(series_specs())
    cal = client.get("/api/calendar").json()
    assert cal["next"] == "2026-12-10" and len(cal["meetings"]) == 95
    dates = [x["date"] for x in cal["meetings"]]
    assert client.post("/api/calendar", json={"dates": dates}, headers=ANON).status_code == 401                      # who is asking?
    assert client.post("/api/calendar", json={"dates": "x"}, headers=hdr(user)).status_code == 400
    assert client.post("/api/calendar", json={"dates": dates + ["yarın"]}, headers=hdr(user)).status_code == 400
    res = client.post("/api/calendar", json={"dates": dates}, headers=hdr(user))                        # unchanged: nothing moves
    assert res.status_code == 200 and (res.json()["meetings"], res.json()["moved"], res.json()["rolled"]) == (80, 0, [])
    # a pasted column, before it is saved: what it would do to the list being edited
    prev = client.post("/api/calendar/preview", json={"current": dates, "dates": ["14.01.2027"], "mode": "correct"})
    assert prev.status_code == 200 and prev.json()["corrected"] == [["2027-01-21", "2027-01-14"]] and len(prev.json()["dates"]) == 95
    assert client.post("/api/calendar/preview", json={"current": dates, "dates": "x"}).status_code == 400
    assert client.post("/api/calendar/preview", json={"current": dates, "dates": ["14.01.2027"], "mode": "x"}).status_code == 400
    assert client.post("/api/history/settings", json={"dibs_field": "x"}, headers=ANON).status_code == 401
    assert client.post("/api/history/settings", json={"lookback_days": 3}, headers=hdr(user)).status_code == 400
    ok = client.post("/api/history/settings", json={"dibs_field": "yld_ytm_mid", "lookback_days": 370}, headers=hdr(user))
    assert ok.json() == {"dibs_field": "YLD_YTM_MID", "lookback_days": 370}
    # "update now" runs in the background: the call returns at once
    calls = []
    monkeypatch.setattr(hsvc.history, "sync", lambda **kw: calls.append(kw) or {"fetched": 0, "computed": 0, "rev": hsvc.history.rev})
    assert client.post("/api/history/sync", json={}, headers=ANON).status_code == 401
    res = client.post("/api/history/sync", json={"recompute": True}, headers=hdr(user))
    assert res.status_code == 200 and res.json()["running"] is True
    for _ in range(100):
        if calls:
            break
        time.sleep(0.05)
    assert calls and calls[0] == {"recompute": True}
