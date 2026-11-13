"""Charts: what is taken from the workbook's chart definitions and how values are handed to the browser.

The drawing itself (colours on screen, axes, smoothing, tooltips) is checked in the browser test.
"""
import os

import pytest

from helpers import mini_book
from tto.render import Renderer
from tto.views import load_views
from tto.xl import numfmt
from tto.xl.model import Model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TR = numfmt.get_locale("tr")


@pytest.fixture(scope="module")
def tto():
    return Model.load(os.path.join(ROOT, "models", "tto.json.gz"))


def charts_of(model, sheet):
    return model.sheet(sheet).charts


def colours(chart):
    return [s["color"] for s in chart["series"]]


# ---------------------------------------------------------------------------------------------- import
def test_all_fourteen_charts_are_imported_with_their_titles(tto):
    titles = {name: [c["title"] for c in charts_of(tto, name)] for name in ("MASA", "OIS_MAIN", "Forward")}
    assert [len(v) for v in titles.values()] == [6, 6, 2]
    assert titles["MASA"][0] == "Oranlar (360 basit)" and titles["Forward"][1] == "Rate Comparison"
    assert titles["OIS_MAIN"][0].startswith("TLREF patikası")
    assert sum(len(sh.charts) for sh in tto.sheets) == 14


def test_series_keep_the_colour_and_style_they_have_in_excel(tto):
    rates = charts_of(tto, "MASA")[0]
    # RET bid / ask: red and purple dashes, ICAP orange, OIS navy, VİOP green - all with markers
    assert colours(rates) == ["C0504D", "8064A2", "F79646", "1F497D", "9BBB59"]
    assert [bool(s.get("dash")) for s in rates["series"]] == [True, True, False, False, False]
    assert all(s.get("marker") for s in rates["series"]) and not any(s.get("smooth") for s in rates["series"])
    path = charts_of(tto, "OIS_MAIN")[0]
    assert colours(path) == ["4A7EBB", "BE4B48", "98B855", "7D5FA0"]
    assert all(s.get("smooth") for s in path["series"]) and not any(s.get("marker") for s in path["series"])
    # a series without a colour of its own takes the theme accent Excel would give it (blue, red, green, purple, aqua)
    assert colours(charts_of(tto, "Forward")[1]) == ["4F81BD", "C0504D", "9BBB59", "8064A2", "4BACC6"]
    bars = charts_of(tto, "OIS_MAIN")[1]
    assert bars["kind"] == "bar" and colours(bars) == ["4F81BD", "C0504D", "9BBB59", "8064A2"] and bars["gap_width"] == 150


def test_axes_follow_the_workbook(tto):
    masa, ois, fwd = charts_of(tto, "MASA"), charts_of(tto, "OIS_MAIN"), charts_of(tto, "Forward")
    assert masa[0]["ymin"] == 0.25 and "ymax" not in masa[0] and masa[0]["value_format"] == "0.0%"
    assert (masa[2]["ymin"], masa[2]["ymax"], masa[2]["major_unit"]) == (0.3, 0.42, 0.01)
    assert masa[4]["label_skip"] == 4 and "label_skip" not in masa[0]
    # the only date axis: the TLREF path, labelled by month
    assert [c["x_axis"] for c in ois] == ["date", "cat", "cat", "cat", "cat", "cat"]
    assert ois[0]["x_format"].replace("\\", "") == "mmm yy" and ois[0]["y_title"] == "TLREF"
    assert ois[2]["y_title"] == "Forward" and ois[3]["y_title"] == "Par oran"
    assert "ymin" not in fwd[0] and fwd[1]["ymin"] == 0.25          # the first one is on Excel's automatic axis
    # wide and short on the desk sheet, taller where Excel has them taller
    assert 0.3 < masa[0]["aspect"] < 0.37 and 0.7 < masa[2]["aspect"] < 0.77


def test_gaps_legend_and_bid_ask_boxes(tto):
    every = [c for sh in tto.sheets for c in sh.charts]
    assert all(c["blanks"] == "gap" for c in every)
    # "show #N/A as an empty cell" is set on the two Forward charts only
    assert [c["title"] for c in every if c["na_gap"]] == ["O/N Equivalent TRY Onshore - Offshore", "Rate Comparison"]
    band = charts_of(tto, "MASA")[3]
    assert [s["kind"] for s in band["series"]] == ["area", "area", "line", "line", "line"]
    assert [s.get("legend") for s in band["series"]] == [False, None, None, None, None]     # one legend key for the band
    assert band["series"][0]["alpha"] == 0.22 and band["series"][0]["noline"] and band["series"][0]["color"] == "C0504D"
    boxes = charts_of(tto, "MASA")[2]["updown"]
    assert (boxes["first"], boxes["last"], boxes["gap_width"]) == (0, 4, 120.0)            # RET bid ... RET ask
    assert boxes["up"] == {"color": "C0504D", "alpha": 0.28, "line": "C0504D", "line_alpha": 0.6}
    assert [c["title"] for c in every if c.get("updown")] == ["RET bid–ask ve piyasa (%, 360 basit)"]
    stacked = charts_of(tto, "OIS_MAIN")[5]
    assert all(s["stacked"] for s in stacked["series"]) and len(stacked["series"]) == 2


# ---------------------------------------------------------------------------------------------- values
def chart_of(cells, **chart):
    book = mini_book(cells)
    spec = {"title": "t", "kind": "line", "series": [{"name": "s", "cat": "S!A1:A6", "val": "S!B1:B6", "kind": "line"}]}
    spec.update(chart)
    return Renderer(book).chart(book.engine.shared, spec, TR)


VALUES = {"A1": "a", "A2": "b", "A3": "c", "A4": "d", "A5": "e", "A6": "f",
          "B1": 1.5, "B3": "=NA()", "B4": '=""', "B5": True, "B6": 2.5}          # B2 is empty


def test_values_are_plotted_the_way_excel_plots_them():
    # a number is a point, an empty cell a gap, #N/A is passed over by the line, text (even "") counts as zero
    assert chart_of(VALUES)["series"][0]["data"] == [1.5, None, "c", 0.0, 0.0, 2.5]
    # "show #N/A as empty": #N/A follows the rule for empty cells
    assert chart_of(VALUES, na_gap=True)["series"][0]["data"] == [1.5, None, None, 0.0, 0.0, 2.5]
    assert chart_of(VALUES, blanks="zero")["series"][0]["data"] == [1.5, 0.0, "c", 0.0, 0.0, 2.5]
    assert chart_of(VALUES, blanks="span")["series"][0]["data"] == [1.5, "c", "c", 0.0, 0.0, 2.5]
    assert chart_of(VALUES, blanks="zero", na_gap=True)["series"][0]["data"] == [1.5, 0.0, 0.0, 0.0, 0.0, 2.5]


def test_trailing_categories_without_label_and_value_are_dropped():
    out = chart_of({"A1": "a", "A2": "b", "B1": 1, "B2": 2})
    assert out["cats"] == ["a", "b"] and out["series"][0]["data"] == [1.0, 2.0]
    # a label keeps its category even when the value is missing
    out = chart_of({"A1": "a", "A2": "b", "A3": "c", "B1": 1})
    assert out["cats"] == ["a", "b", "c"] and out["series"][0]["data"] == [1.0, None, None]


def test_value_format_gives_unit_and_decimals():
    assert "unit" not in chart_of(VALUES) and "decimals" not in chart_of(VALUES)
    out = chart_of(VALUES, value_format="0.0%")
    assert out["unit"] == "pct" and out["decimals"] == 1
    assert chart_of(VALUES, value_format="0%")["decimals"] == 0
    out = chart_of(VALUES, value_format='#,##0.00;\\-#,##0.00;0.00')
    assert "unit" not in out and out["decimals"] == 2
    assert "decimals" not in chart_of(VALUES, value_format="General")


def test_series_style_and_axis_settings_reach_the_browser():
    spec = {"ymin": 0.1, "ymax": 0.5, "major_unit": 0.05, "label_skip": 2, "aspect": 0.4, "gap_width": 120.0, "y_title": "Oran",
            "auto": "fit", "updown": {"first": 0, "last": 0, "gap_width": 100.0, "up": {}, "down": {}},
            "series": [{"name": "s", "cat": "S!A1:A6", "val": "S!B1:B6", "kind": "line", "color": "C0504D", "dash": True,
                        "marker": True, "smooth": True, "alpha": 0.3, "legend": False}]}
    out = chart_of(VALUES, **spec)
    for key in ("ymin", "ymax", "major_unit", "label_skip", "aspect", "gap_width", "y_title", "auto", "updown"):
        assert out[key] == spec[key], key
    s = out["series"][0]
    assert (s["color"], s["dash"], s["marker"], s["smooth"], s["alpha"], s["legend"]) == ("C0504D", 1, 1, 1, 0.3, 0)
    plain = chart_of(VALUES)["series"][0]
    assert not any(k in plain for k in ("color", "dash", "marker", "smooth", "alpha", "legend"))


def test_a_date_axis_needs_real_increasing_dates():
    dates = {"A1": 46300, "A2": 46310, "A3": 46350, "B1": 1, "B2": 2, "B3": 3}
    spec = {"x_axis": "date", "x_format": "mmm\\ yy", "series": [{"name": "s", "cat": "S!A1:A3", "val": "S!B1:B3", "kind": "line"}]}
    out = chart_of(dates, **spec)
    assert out["x"] == {"type": "date", "values": [46300.0, 46310.0, 46350.0], "format": "mmm yy"}
    assert "x" not in chart_of(dates, series=spec["series"])                               # a category axis
    assert "x" not in chart_of(dict(dates, A2=46400), **spec)                              # not increasing
    assert "x" not in chart_of(dict(dates, A2="yok"), **spec)                              # not a date


def test_series_name_comes_from_its_cell():
    cells = dict(VALUES, D1="Seri adı")
    out = chart_of(cells, series=[{"name_ref": "S!D1", "name": None, "cat": "S!A1:A6", "val": "S!B1:B6", "kind": "line"}])
    assert out["series"][0]["name"] == "Seri adı"


# ---------------------------------------------------------------------------------------------- the pages
def test_every_chart_on_the_pages_is_drawable(service):
    seen = 0
    for view in load_views():
        for p in service.view(None, view["id"])["panels"]:
            if p["type"] != "chart":
                continue
            seen += 1
            d = p["data"]
            n = len(d["cats"])
            assert n > 1 and d["series"], (view["id"], p["id"])
            for s in d["series"]:
                assert len(s["data"]) == n
                assert all(type(v) is float or v is None or v == "c" for v in s["data"]), (view["id"], p["id"])
                assert any(type(v) is float for v in s["data"]), (view["id"], p["id"], s["name"])
                assert s["kind"] in ("line", "area", "bar")
                assert "color" not in s or (len(s["color"]) == 6 and int(s["color"], 16) >= 0)
            assert "slot" not in d["series"][0]
    assert seen == 16                                             # 14 from the workbook + 2 defined for the USD page


def test_tlref_path_is_on_a_date_axis_and_the_usd_charts_fit_their_data(service):
    ois = {p["id"]: p for p in service.view(None, "ois")["panels"] if p["type"] == "chart"}
    path = ois["chart0"]["data"]
    assert path["x"]["type"] == "date" and path["x"]["format"] == "mmm yy" and path["unit"] == "pct"
    xs = path["x"]["values"]
    assert len(xs) == len(path["cats"]) and all(a < b for a, b in zip(xs, xs[1:]))
    assert path["ymin"] == 0.25 and path["y_title"] == "TLREF"
    assert all(s["smooth"] == 1 for s in path["series"])
    usd = [p["data"] for p in service.view(None, "usd")["panels"] if p["type"] == "chart"]
    assert len(usd) == 2 and all(d["auto"] == "fit" for d in usd)
    masa = [p["data"] for p in service.view(None, "masa")["panels"] if p["type"] == "chart"]
    assert all("auto" not in d for d in masa)                     # workbook charts follow Excel's axis rule


def test_the_workbook_values_reach_the_chart_unchanged(service):
    from conftest import cell
    rates = next(p["data"] for p in service.view(None, "masa")["panels"] if p["type"] == "chart" and p["id"] == "chart0")
    assert [s["name"] for s in rates["series"]] == ["RET bid", "RET ask", "ICAP", "OIS zero", "VİOP"]
    for k, col in enumerate("GHIJK"):                            # MASA!AG6:AK16
        for i in range(11):
            v = cell(service, "MASA!A%s%d" % (col, 6 + i))
            got = rates["series"][k]["data"][i]
            if type(v) is float:
                assert got == v
            else:
                assert got == "c", (col, i, v)                   # #N/A: the line passes over the point
    viop = rates["series"][4]["data"]
    assert viop[0] == "c" and type(viop[4]) is float              # VİOP has no quote before 1M
    # the two Forward charts leave a gap instead
    fwd = [p["data"] for p in service.view(None, "forward")["panels"] if p["type"] == "chart"]
    assert all(v != "c" for d in fwd for s in d["series"] for v in s["data"])
    assert any(v is None for d in fwd for s in d["series"] for v in s["data"])
