"""Empty hand calculators show no errors (B7 of 28.11.2026, "Boş, sıfır ve yükleniyor ayrı okunsun" - ``extras.EMPTY_CALC_NAME``):
the Forward page's XARTRY customer gold forward (9× #VALUE!, "31.12.1899"), its bond carry (Bloomberg's yield and dirty price of
no ISIN - the file's cached values offline - and 2× #DIV/0!) and OIS · Nakit Akışı's summary (14× #DIV/0!).  Filled in, every
cell is the value its own formula gave before (the guards only open)."""
from __future__ import annotations

import pytest

from conftest import cell
from tto import extras as ex


def page(service, user, view_id):
    return {p["id"]: p for p in service.view(user, view_id)["panels"]}


def texts(p):
    return [c.get("t") or "" for row in (p.get("data") or {}).get("rows") or [] for c in row if isinstance(c, dict)]


def put(service, user, items):
    res = service.set_inputs(user, "tto", [{"ref": k, "value": v} for k, v in items.items()])
    assert res["errors"] == [], res["errors"]


def test_empty_calculators_read_blank(service):
    u = service.login("K8 boş hesap")["user"]
    fwd, tm = page(service, u, "forward"), page(service, u, "tmois")
    for p in (fwd["B21"], fwd["B24"], tm["B3"], tm["B4"]):
        bad = [t for t in texts(p) if t.startswith("#") or t == "31.12.1899"]
        assert bad == [], (p["id"], bad)
    # (the bond carry shows no yield, dirty price or coupon of no ISIN - offline the file's values stood there)
    assert [cell(service, "Forward!%s" % a, u) for a in ("V59", "V60", "V64", "V68", "V69", "W69", "W70")] == [""] * 7
    assert [cell(service, "TM_OIS!%s" % a, u) for a in ("B4", "D4", "F4", "H4", "J4", "B5", "J5", "B6", "D6", "F6", "H6", "J6")] == [""] * 12


def test_the_gold_forward_filled_in_is_its_formulas(service):
    u = service.login("K8 XARTRY")["user"]
    put(service, u, {"Forward!C61": "4100,5", "Forward!C63": "1414", "Forward!E61": "08.12.2026", "Forward!E67": "05.11.2026"})
    v = {a: cell(service, "Forward!%s" % a, u) for a in ("C61", "C63", "E59", "E61", "E63", "E64", "E67", "I2")}
    n = v["E61"] - v["I2"]
    e60 = v["C61"] / 31.26 * v["E59"]
    c62 = v["C61"] + v["C63"] / 100
    e62 = v["E59"] * (1 + v["E64"] / 360 * n) / (1 + v["E63"] / 360 * n)
    e65 = c62 * e62 / 31.26
    e66 = (e65 - e60) * 10000
    e68 = v["E61"] - v["E67"]
    e69 = e68 / n * e66
    want = {"E60": e60, "C62": c62, "C65": n, "E62": e62, "E65": e65, "E66": e66, "E68": e68, "E69": e69, "B71": v["E67"],
            "C71": v["E61"], "D71": e60, "E71": e69, "F71": e69 / 10000 + e60, "B73": v["E61"] - v["E67"]}
    assert {a: cell(service, "Forward!%s" % a, u) for a in want} == pytest.approx(want, rel=1e-12)


def test_the_bond_carry_with_an_isin_reads_bloomberg_as_before(service):
    """With an ISIN the cells read Bloomberg's answers (offline the file's) through their helpers beside the block; the
    request is made only with an ISIN."""
    u = service.login("K8 tahvil carry")["user"]
    put(service, u, {"Forward!V56": "TRB100227T13", "Forward!V57": "91,713", "Forward!V58": "05.11.2026",
                     "Forward!V62": "03.02.2027"})
    model = service.books["tto"].model
    for addr, helper in ex.CARRY_BBG:
        assert cell(service, "Forward!%s" % addr, u) == cell(service, "Forward!%s" % helper, u) == ex.recorded_value(model, "Forward", helper)
        assert "_xll.BDP(V56" in ex.formula_of(model, "Forward", helper) and "_xll" not in ex.formula_of(model, "Forward", addr)
    v59, v68, v63 = (cell(service, "Forward!%s" % a, u) for a in ("V59", "V68", "V63"))
    assert v63 == 90.0 and cell(service, "Forward!V69", u) == pytest.approx(v68 - v59) and \
        cell(service, "Forward!W69", u) == pytest.approx((v68 - v59) / 90)
    assert cell(service, "Forward!W70", u) == pytest.approx(cell(service, "Forward!V70", u) / 90)


def test_the_cash_flow_pricer_filled_in_is_its_formulas(service):
    from tto.xl.values import serial_to_date
    u = service.login("K8 nakit akışı")["user"]
    spot = cell(service, "OIS_MAIN!B2")
    day = lambda k: serial_to_date(spot + k).strftime("%d.%m.%Y")                            # noqa: E731
    put(service, u, {"TM_OIS!A10": day(0), "TM_OIS!B10": day(91), "TM_OIS!C10": "100000000",
                     "TM_OIS!A11": day(91), "TM_OIS!B11": day(182), "TM_OIS!C11": "100000000"})
    col = lambda c: [cell(service, "TM_OIS!%s%d" % (c, r), u) for r in range(10, 35)]          # noqa: E731
    s = lambda c: sum(x for x in col(c) if type(x) is float)                                  # noqa: E731
    b4 = s("H") / s("I")
    assert cell(service, "TM_OIS!B4", u) == pytest.approx(b4, rel=1e-12)
    assert cell(service, "TM_OIS!B5", u) == round(cell(service, "TM_OIS!B3", u) * (s("J") - s("H")))
    assert cell(service, "TM_OIS!D6", u) == round(s("I") * 0.0001)
    assert cell(service, "TM_OIS!F6", u) == pytest.approx(cell(service, "OIS_MAIN!F2") * cell(service, "OIS_MAIN!D2") / round(s("I") * 0.0001))
    j4 = cell(service, "TM_OIS!J4", u)
    assert type(j4) is float and cell(service, "TM_OIS!H6", u) == pytest.approx(round((b4 - j4) * 10000, 2), abs=1e-9)
    assert cell(service, "TM_OIS!J6", u) in ("–", "SABİT AL", "SABİT ÖDE")
    # a PV typed (two-way): the trade rate it gives, as before
    put(service, u, {"TM_OIS!B5": "-400000"})
    assert cell(service, "TM_OIS!B5", u) == -400000.0 and type(cell(service, "TM_OIS!D3", u)) is float
