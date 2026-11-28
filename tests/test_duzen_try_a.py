"""The desk's layout review on Masa, OIS · PPK, USD · FOMC, Fiyatlama and Swaption (27.11.2026: "Hepsini yap"): the tabs as
the desk's own shortcuts name them, the main table first, the inputs beside (above) their tables, empty rows folded, a
helper column hidden until it is asked for (one click back), the looks that differed from page to page made one - and no
value, formula or input changed.  (How the browser lays a column of stacked panels out, ``"limit"`` and ``"freeze"`` are
the layout mechanism's own tests; the pages' pictures are the browser test's.)"""
import json
import os
import re

import pytest

from conftest import cell
from tto import extras as ex
from tto.render import fill_tone, tone
from tto.service import Service
from tto.views import load_views
from tto.xl.model import Model
from tto.xl.tokenizer import col_to_index, index_to_col

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = {"masa": "10_masa.json", "ois": "20_ois.json", "usd": "80_usd.json"}


def raw(view_id):
    """A page definition as written (a tab's column of stacked panels is an array there)."""
    with open(os.path.join(ROOT, "tto", "views", FILES[view_id]), encoding="utf-8") as fh:
        return json.load(fh)


def flat(ids):
    return [x for p in ids for x in (p if isinstance(p, list) else [p])]


def tabs(view):
    return {s["id"]: s for s in view["sections"]}


def panels(view):
    return {p["id"]: p for p in view["panels"]}


def at(data, col, row):
    """A cell of a page's table by its column letter and sheet row (None when the table does not show it)."""
    if col not in data["c"] or row not in data["r"]:
        return None
    return data["rows"][data["r"].index(row)][data["c"].index(col)]


def page(service, user, view_id):
    return {p["id"]: p for p in service.view(user, view_id)["panels"]}


# ============================================================================== Masa
def test_masa_tabs_the_date_to_date_tools_together_makro_in_sinyaller():
    v = raw("masa")
    t, p = tabs(v), panels(v)
    assert list(t) == ["over", "fwd", "tarih", "rates", "viop", "sig"]
    assert [s["title"] for s in v["sections"]] == ["Genel bakış", "Forward fiyatlama", "Tarih arası", "Faiz · PPK", "VİOP", "Sinyaller"]
    # Genel bakış: no manual spot - the strip's "Spot kaynağı ✎" writes the same two cells, the VİOP page shows them; the charts
    # side by side (three rates' charts, then RET BANDINA GÖRE PİYASA with its bp chart)
    assert t["over"]["panels"] == ["B2", "B3", "B4", "chart0", "chart1", "chart2", "B8", "chart3"]
    assert p["SPOT"]["hidden"] and p["SPOT"]["borrowed"] and (p["SPOT"]["sheet"], p["SPOT"]["range"]) == ("VIOP", "Z8:AA11")
    # one dates row: TARİH ARASI FORWARD beside TARİH ARASI FAİZ, whose first row it reads; the strip that repeated that row
    # is a helper - a temporary copy of the forward still shows it above itself, its own dates
    assert t["tarih"]["panels"] == ["B9", "B10", "TAFS", "TAF"] and t["fwd"]["panels"] == ["EKS", "EKSE", "B22"]
    assert p["B10D"]["hidden"] and p["B10D"]["range"] == "B60:N60" and p["B10"]["copy_with"] == ["B10D"] and p["B10"]["copyable"]
    assert p["B9"]["range"] == "B59:N70"                                                 # (row 60: the dates, in TARİH ARASI FAİZ)
    # the strips of inputs above their tables: a column each
    assert t["viop"]["panels"] == ["B15", ["B16D", "B16"], ["B17D", "B17"]]
    assert t["sig"]["panels"] == [["B18D", "B18"], ["B19D", "B19"], ["B23D", "B23"], "B20"]
    # every table shown is in a tab, once in it
    shown = {pid for pid, x in p.items() if not x.get("hidden")}
    assert set(flat(x for s in v["sections"] for x in s["panels"])) == shown
    assert all(len(flat(s["panels"])) == len(set(flat(s["panels"]))) for s in v["sections"])


def test_masa_tables_fold_their_empty_rows_and_keep_the_inputs_first():
    p = panels(raw("masa"))
    # the forward summaries' free ("serbest") rows past the first empty one; the panels as wide as their matrix
    assert p["EKS"]["grow"] == {"key": "B", "first": 5, "extra": 1, "last": 14} and not p["EKS"].get("wide")
    assert p["EKSE"]["grow"] == {"key": "B", "first": 104, "extra": 1, "last": 113} and not p["EKSE"].get("wide")
    # the VİOP targets' inputs: the rows past the first empty one (TARGET itself shows one row a target: Excel hides the rest)
    assert p["B17D"]["grow"] == {"key": "L", "first": 331, "extra": 1, "last": 338} and "grow" not in p["B17"]
    # TOPLU TARİH ARASI FAİZ: Başlangıç, Bitiş, Spread, Gün, then Kote % and what it reads, then the curves - its input column
    # was 450 px out of view on a 1920 screen
    taf = p["TAF"]
    assert taf["cols"][:7] == ["B", "C", "D", "E", "N", "O", "P"] and sorted(taf["cols"]) == sorted("BCDEFGHIJKLMNOP")
    assert taf["freeze"] == 2 and taf["grow"] == {"key": "B", "first": 5, "extra": 1, "last": 104}
    # the identifier column in view when a wide table scrolls sideways
    assert {pid: x["freeze"] for pid, x in p.items() if x.get("freeze")} == {"B9": 1, "TAFS": 1, "TAF": 2, "B10": 1, "B21": 1, "B22": 1}


def test_the_folded_rows_hold_nothing_the_desk_reads(service):
    """A row a "grow" folds away is one whose key cell is empty: such a row prices nothing (its label, rank number or the
    general spreads it would use aside) - on the page as the desk has it (replay, a user of the test's own)."""
    u = service.login("Düzen satırlar")["user"]
    allowed = {("masa", "EKS"): "ADE", ("masa", "EKSE"): "ADE", ("masa", "B17D"): "", ("ois", "B9"): "A", ("ois", "B10"): "A", ("ois", "B11"): "A", ("usd", "top"): "F", ("usd", "spr"): "F",
               ("usd", "fly"): "F"}
    folded = 0
    for (vid, pid), extra in allowed.items():
        spec = panels(raw(vid))[pid]["grow"]
        data = page(service, u, vid)[pid]["data"]
        filled = [r for r in data["r"] if spec["first"] <= r <= spec["last"] and (at(data, spec["key"], r) or {}).get("t", "").strip()]
        for r in data["r"]:
            if not spec["first"] <= r <= spec["last"] or (filled and r <= max(filled)):
                continue
            # past the last filled row: nothing but the allowed columns (the panel's own appended columns are empty too)
            texts = {c: (x.get("t") or "").strip() for c, x in zip(data["c"], data["rows"][data["r"].index(r)])}
            assert not {c: t for c, t in texts.items() if t and c not in extra}, (vid, pid, r)
            folded += 1
    assert folded >= 10                               # (FLY's, FRA's, USD FLY's, the free rows', the targets' empty rows)


# ============================================================================== OIS · PPK
def test_ois_tabs_quotes_beside_outright_and_ppk_ima_in_two():
    v = raw("ois")
    t, p = tabs(v), panels(v)
    assert list(t) == ["quotes", "mpc", "mpcis", "best", "all"]
    # Kotalar: OUTRIGHT first, beside it one column - SENARYOLAR, the stub (the one-table Hesaplayıcılar tab's); the solver's
    # settings beside İMA PPK in MPC ima (28.11.2026, B12: they ran ~350 px below OUTRIGHT)
    assert t["quotes"]["panels"] == ["B3", ["B2", "B18"], "chart3", "chart4", "B5"]
    # PPK ima in two, by the names the desk's own shortcuts use
    assert (t["mpc"]["title"], t["mpcis"]["title"]) == ("MPC ima", "MPC işlem")
    assert t["mpc"]["panels"] == ["B4", "chart0", "chart1", "B6", "B7", ["B22", "B8"]]
    assert t["mpcis"]["panels"] == ["B13", "PPK1", "B14", "B15", "PPK2", "B16"]
    # IMPLIED RATES opens on its first 24 meetings (all of them one click away), the best lists fold their empty ranks
    assert p["B4"]["limit"] == {"rows": 24}
    for pid, first, last in (("B9", 30, 44), ("B10", 48, 62), ("B11", 66, 80)):
        assert p[pid]["grow"] == {"key": "B", "first": first, "extra": 1, "last": last} and p[pid]["ranked"]
    assert p["B11"]["freeze"] == 2
    # what TLREF's normalization builds on stays: the parameters pinned and open, the panels by their ids
    assert v["pinned"] == ["B1"] and not p["B1"].get("collapsed") and not p["B1"].get("hidden")
    assert {"B1", "B6", "PPK1", "PPK2", "PPKY"} <= set(p) and not p["B6"].get("hidden") and p["PPKY"]["hidden"]
    shown = {pid for pid, x in p.items() if not x.get("hidden")}
    assert set(flat(x for s in v["sections"] for x in s["panels"])) | set(v["pinned"]) == shown


def test_the_desks_shortcuts_open_the_tabs_named_after_them(service):
    links = {link["label"]: link for link in service.view(None, "masa")["links"]}
    ois, masa = service.view(None, "ois"), service.view(None, "masa")

    def tab_of(view, pid):
        return next(s["title"] for s in view["sections"] if pid in flat(s["panels"]))

    assert links["MPC ima"]["page"] == "ois" and tab_of(ois, links["MPC ima"]["panel"]) == "MPC ima"
    assert links["MPC işlem"]["page"] == "ois" and tab_of(ois, links["MPC işlem"]["panel"]) == "MPC işlem"
    assert tab_of(ois, links["Outright"]["panel"]) == "Kotalar" and tab_of(ois, links["En iyi RV"]["panel"]) == "En iyi işlemler"
    assert tab_of(masa, links["Makro"]["panel"]) == "Sinyaller" and tab_of(masa, links["RV geçmiş"]["panel"]) == "Sinyaller"
    assert tab_of(masa, links["Kırık vade"]["panel"]) == "Forward fiyatlama" and tab_of(masa, links["PPK anket"]["panel"]) == "Faiz · PPK"
    # the menu's table search: a stacked panel's tab is its tab
    tables = {t["id"]: t["tab"] for t in next(x for x in service.nav() if x["id"] == "ois")["tables"]}
    assert tables["B18"] == tables["B2"] == "Kotalar" and tables["B8"] == "MPC ima" and tables["B13"] == "MPC işlem"


# ============================================================================== USD · FOMC
def test_usd_tabs_main_table_first_and_the_fomc_inputs_in_view():
    v = raw("usd")
    t, p = tabs(v), panels(v)
    assert t["top"]["panels"] == ["top", "spr", "fly", "inp", "chk"] and p["cap"]["hidden"]      # (its caption: the page's title)
    # (28.11.2026, B11: the scenario view a table of its own beside the chart - test_duzen_try_fx.py)
    assert t["fomc"]["panels"] == ["fomc", "fomc-sc", "fomc-chart", "inp"] and t["curve"]["panels"] == ["crv", "inp", "curve-chart"]
    assert t["trades"]["panels"] == ["t1", "t2", "t3", "t4", "t5", "inp"]
    cols = p["fomc"]["cols"]
    # "PENCERE OIS → FOMC ADIMI" (AA:AE: the market's window rate, then the four two-way inputs) right after İma O/N % (K)
    assert cols[cols.index("K") + 1:cols.index("K") + 6] == ["AA", "AB", "AC", "AD", "AE"]
    assert sorted(set(cols) | set(p["fomc-sc"]["cols"]), key=col_to_index) == [index_to_col(c) for c in range(1, col_to_index("AE") + 1)]
    assert p["fomc"]["freeze"] == 2 and cols[:2] == ["A", "B"]
    for pid, first, last in (("top", 5, 14), ("spr", 20, 29), ("fly", 34, 43)):
        assert p[pid]["grow"] == {"key": "H", "first": first, "extra": 1, "last": last}


def test_usd_hides_only_helper_columns_and_one_click_brings_them_back(service):
    u = service.login("Düzen USD")["user"]
    by = page(service, u, "usd")
    fomc, crv = by["fomc"]["data"], by["crv"]["data"]
    assert fomc["c"] == panels(raw("usd"))["fomc"]["cols"]
    assert all((at(fomc, c, 74) or {}).get("i") == "u" for c in ("AB", "AC", "AD", "AE"))      # (still the user's inputs)
    hidden = Service.DEFAULT_HIDDEN_COLUMNS
    assert [at(fomc, c, 73)["t"] for c in hidden["v/usd/fomc"]] == ["Başl. gün", "Bitiş gün", "ln DF başl.", "ln DF bitiş"]
    assert [at(crv, c, 47)["t"] for c in hidden["v/usd/crv"]] == ["Kullan", "Ay", "Hafta", "ln DF", "SOFR ticker", "FF ticker"]
    # every other column shown: the rates, steps, quotes and errors the desk reads
    assert at(fomc, "K", 73)["t"] == "İma O/N %" and "K" not in hidden["v/usd/fomc"] and "H" not in hidden["v/usd/fomc"]
    assert service.columns(u)["defaults"]["v/usd/fomc"] == list(hidden["v/usd/fomc"])
    service.set_columns(u, "v/usd/fomc", [])                                     # "Sütunlar → Tümünü göster": kept as such
    assert service.columns(u)["tables"]["v/usd/fomc"] == [] and "v/usd/fomc" not in service.columns(u)["defaults"]


# ============================================================================== the looks
def test_the_forward_matrix_legend_is_the_desk_summarys_note(service):
    assert str(cell(service, "EK_FWD!" + ex.FWD_LEGEND)).startswith("Eğriler: S1 = ") and cell(service, "EK_FWD!K2") is None
    assert str(cell(service, "EK_FWD!L101")).startswith("eğri ve 'Tümü'") and cell(service, "EK_FWD!K101") is None
    by = page(service, None, "masa")
    eks = by["EKS"]
    assert not (at(eks["data"], "K", 2) or {}).get("t") and "Eğriler: S1 = " in eks["note"]
    assert not (at(by["EKSE"]["data"], "K", 101) or {}).get("t")
    # the Forward page's matrix still says it, in its row 2 (right of Fwd ask)
    fwd = page(service, None, "forward")["EKF1"]["data"]
    assert (at(fwd, "L", 2) or {}).get("t", "").startswith("Eğriler: S1 = ")


def test_a_direction_on_the_try_lists_reads_as_on_the_usd_page(service):
    u = service.login("Düzen YÖN")["user"]
    want = {}
    for condition, look in ex.LOOK_YON_RULES:
        key = re.search(r'"([A-Z]+)"', condition).group(1)
        want[key] = (tone(look["color"]), fill_tone(look["fill"]), 1)

    def kind(text):
        return text[:3] if text[:3] in ("REC", "PAY") else (text if text in ("FLATTENER", "STEEPENER") else None)

    def look(c):
        return (c.get("c"), c.get("f"), c.get("b"))

    seen = set()
    for vid, pages in (("ois", page(service, u, "ois")), ("masa", page(service, u, "masa"))):
        sheet = {"ois": "OIS_MAIN", "masa": "MASA"}[vid]
        for s, _, rng in ex.LOOK_YON:
            if s != sheet:
                continue
            col = re.match(r"[A-Z]+", rng).group(0)
            r1, r2 = (int(x) for x in re.findall(r"\d+", rng))
            data = next(p["data"] for p in pages.values() if p.get("data") and "r" in p["data"] and col in p["data"]["c"]
                        and r1 in p["data"]["r"] and r2 in p["data"]["r"])
            for r in range(r1, r2 + 1):
                c = at(data, col, r)
                k = kind((c or {}).get("t", "").strip())
                if k is None:
                    assert not c or look(c) not in want.values(), (sheet, col, r)          # ("–", a caption: as they were)
                    continue
                assert look(c) == want[k], (sheet, col, r, c)
                seen.add(k)
    assert {"REC", "PAY", "STEEPENER"} <= seen
    # the USD page's own, for the same words: the same look
    usd = page(service, u, "usd")
    rec = next(c for c in (at(usd["top"]["data"], "I", r) for r in range(5, 15)) if c and c["t"].startswith("REC"))
    assert look(rec) == want["REC"]


def test_the_solvers_figures_read_with_one_decimal_their_values_whole(service):
    b8 = page(service, None, "ois")["B8"]["data"]
    for _, _, addr in ex.LOOK_SOLVER:
        c = at(b8, re.match(r"[A-Z]+", addr).group(0), int(re.search(r"\d+", addr).group(0)))
        assert re.fullmatch(r"-?\d+,\d", c["t"]) and c["v"] == cell(service, "OIS_MAIN!" + addr), (addr, c)


def test_the_ret_ask_is_one_colour_in_every_chart_of_the_desk_page(service):
    charts = {p["id"]: p["data"] for p in page(service, None, "masa").values() if p["type"] == "chart"}
    ask = {k: [s["color"] for s in charts[k]["series"] if s["name"].startswith("RET ask")] for k in ("chart0", "chart1", "chart2")}
    bid = {k: [s["color"] for s in charts[k]["series"] if s["name"].startswith("RET bid")] for k in ("chart0", "chart1", "chart2")}
    assert all(len(x) == 1 for x in ask.values()) and len({x[0] for x in ask.values()}) == 1, ask
    assert len({x[0] for x in bid.values()}) == 1 and bid["chart0"] != ask["chart0"], bid


def test_the_looks_change_no_value_formula_or_input(monkeypatch):
    """The workbook with the looks and without them: the same constants and formulas on every sheet they touch."""
    path = os.path.join(ROOT, "models", "tto.json.gz")
    with_looks = Model.load(path)
    assert ex.apply("tto", with_looks) == []
    monkeypatch.setitem(ex._BUILDERS, "tto", tuple(b for b in ex._BUILDERS["tto"] if b[0] != ex.LOOK_NAME))
    without = Model.load(path)
    assert ex.apply("tto", without) == []
    for name in ("OIS_MAIN", "MASA"):
        a, b = with_looks.sheet(name), without.sheet(name)
        assert a.consts == b.consts and a.fml == b.fml and a.arr == b.arr, name
        assert len(a.cf) == len(b.cf) + (len(ex.LOOK_YON_RULES)), name
    assert with_looks.templates == without.templates


# ============================================================================== the pages' definitions
def test_a_tab_may_hold_a_column_of_stacked_panels():
    """In a page definition a tab's panel may be an array of ids - one column of panels stacked one under another; the
    dashboard reads the ids in their order (tests/test_views.py: every tab names real panels)."""
    views = {v["id"]: v for v in load_views()}
    assert flat(tabs(views["masa"])["viop"]["panels"]) == ["B15", "B16D", "B16", "B17D", "B17"]
    assert flat(tabs(views["ois"])["quotes"]["panels"]) == ["B3", "B2", "B18", "chart3", "chart4", "B5"]
    assert flat(tabs(views["ois"])["mpc"]["panels"])[-2:] == ["B22", "B8"]      # (the solver's settings under İMA PPK: B12)
    assert flat(tabs(views["masa"])["sig"]["panels"]) == ["B18D", "B18", "B19D", "B19", "B23D", "B23", "B20"]


@pytest.mark.parametrize("name", ["pricing.js", "swaption.js"])
def test_fiyatlama_and_swaption_say_a_try_rate_with_two_decimals(name):
    """The desk's rule of 25.11.2026 for the pricing tables' TRY rates (two decimals), on Fiyatlama and Swaption too (the
    browser test reads the tiles, buckets and the bulk table); an FX outright keeps four, a USD / EUR rate its own."""
    with open(os.path.join(ROOT, "tto", "static", "js", "pages", name), encoding="utf-8") as fh:
        src = fh.read()
    assert "pct(v, 4)" not in src and "pct(r.quote, 4)" not in src and "pct(n.level, 4)" not in src
