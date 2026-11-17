"""What a bond of the trading list is worth on the ASW curves DİBS RV fits - the TLREF OIS curve and the FX swap implied
TRY curve: the yield and the clean price at which its ASW would sit on the curve ("adil getiri", "adil fiyat" on DİBS
Trading and the bond's card).

DİBS RV's own columns do the work.  For every bond it has the present value of the cash flows on each curve (``EG`` on
the OIS curve, ``WX`` on the FX swap curve), the quarterly annuity on it (``EE``, ``WY``) and the dirty price at the value
date carried to the OIS spot (``DI`` = ``DH`` × the funding factor ``DD``); its ASW is ``(PV − dirty @spot) / annuity ×
100``.  Each curve's fit is ``a + b·t + c·t²`` over the fixed coupon bonds (``CA3:CC3``, ``XO3:XQ3``; ``t`` the years from
the OIS spot to maturity, ``FW``).  At the curve's ASW the dirty price at the spot is ``PV − ASW_curve × annuity / 100``;
back at the value date it is that ÷ the funding factor, the clean price that − the accrued interest (``CW``), and the
yield is the screen's BIST compound yield of that price, worked out as the sheet works out its own: a bill's
``(100 / dirty)^(365 / days) − 1`` (``DR`` days), a coupon bond's ``(1 + y/f)^f − 1`` with ``y`` the rate that discounts
its cash flows (``ID:JA`` at ``LV:MS`` coupon periods, ``f`` = ``CU`` a year) to the dirty price.  At the bond's own ASW
the fair price is its price: what the fair value tells is where the curve puts it.

A bill is in neither fit (the curves are the fixed coupon bonds'): its fair value reads the curve at its own years and
says so; read further than a quarter of a year outside the years of the bonds fitted (as far as the ASW page draws the
curve) it is the curve stretched - shown soft.  A TLREF floater, an FRN and a CPI linker have no ASW curve to sit on:
no fair value, the reason given instead."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .xl.tokenizer import col_to_index, index_to_col

FIRST, LAST = 5, 54                      # the rows of the trading list (DİBS RV!A5:A54)
#: the two curves: the fit's a / b / c (row 3) and the count of its bonds, each row's "in the fit" flag and its years,
#: the present value and the annuity on the curve
CURVES: Dict[str, Dict[str, Any]] = {
    "ois": {"name": "OIS", "coef": ("CA", "CB", "CC"), "n": "BR", "flag": "FR", "t": "FS", "pv": "EG", "ann": "EE"},
    "fx": {"name": "FX swap", "coef": ("XO", "XP", "XQ"), "n": "XF", "flag": "XA", "t": "XB", "pv": "WX", "ann": "WY"},
}
FLOWS = ("ID", "LV", 24)                 # a bond's cash flows, their times in coupon periods, how many at most
STRETCH = 0.25                           # years outside the bonds fitted that the curve is read as it is drawn
#: why a kind of bond has no fair value (DİBS RV's type: T, F, E)
NO_CURVE = {"T": "TLREF'e endeksli: ASW eğrileri sabit kuponlulara uydurulur, DM için uydurulmuş eğri yok - adil fiyat yok "
                 "(kâğıdın DM'i ASW / DM sütununda)",
            "F": "FRN: yalnız fiyatla izlenir, eğriye karşı hesap yok",
            "E": "TÜFE'ye endeksli: reel getiri, ASW yok"}


def _col(letters: str) -> int:
    return col_to_index(letters)


def read_fits(calc, si: int) -> Dict[str, Dict[str, Any]]:
    """Each curve's fit as DİBS RV has it: ``coef`` (a, b, c - None while it has too few bonds), ``n`` (its bonds) and
    ``span`` (the years of the bonds fitted, shortest and longest)."""
    out: Dict[str, Dict[str, Any]] = {}
    for side, c in CURVES.items():
        coef = [calc.get(si, 3, _col(x)) for x in c["coef"]]
        n = calc.get(si, 3, _col(c["n"]))
        ts = [calc.get(si, r, _col(c["t"])) for r in range(FIRST, LAST + 1) if calc.get(si, r, _col(c["flag"])) == 1.0]
        ts = [t for t in ts if type(t) is float]
        out[side] = {"coef": coef if all(type(x) is float for x in coef) else None, "n": int(n) if type(n) is float else 0,
                     "span": (min(ts), max(ts)) if ts else None}
    return out


def curve_asw(coef: Sequence[float], t: float) -> float:
    """The fitted curve's ASW (bp) at ``t`` years."""
    a, b, c = coef
    return a + b * t + c * t ** 2


def bill_yield(dirty: float, days: float) -> Optional[float]:
    """A bill's (or zero's) BIST compound yield at a price: ``(100 / P)^(365 / days) − 1``."""
    if dirty <= 0 or days <= 0:
        return None
    return (100.0 / dirty) ** (365.0 / days) - 1.0


def coupon_yield(dirty: float, flows: Sequence[Tuple[float, float]], freq: float, start: float) -> Optional[float]:
    """The BIST simple yield of a coupon bond at a dirty price: the ``y`` at which ``Σ CF · (1 + y/f)^(−periods)`` is the
    price (Newton's method from ``start``, to the last digit)."""
    if dirty <= 0 or freq <= 0 or not flows:
        return None
    y = start
    for _ in range(100):
        g = 1.0 + y / freq
        if g <= 0:
            return None
        pv = sum(cf * g ** -x for cf, x in flows)
        slope = sum(-x * cf * g ** (-x - 1.0) / freq for cf, x in flows)
        if slope == 0:
            return None
        step = (pv - dirty) / slope
        y -= step
        if abs(step) < 1e-14:
            return y
    return y if abs(step) < 1e-9 else None


def fair(calc, si: int, r: int, fits: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The fair values of the bond on row ``r`` of DİBS RV, curve by curve (``ois``, ``fx``): ``asw`` (the curve's ASW at
    its ``t`` years), ``pv``, ``ann``, ``dd`` (the funding factor), ``acc`` (accrued), ``dirty_spot``, ``dirty`` (at its
    value date), ``price`` (clean), ``yield`` (BIST compound), ``bill`` (read off the curve, not in it), ``stretched``
    (outside the years fitted); or ``why`` there is none."""
    def v(col: str) -> Any:
        return calc.get(si, r, _col(col))

    kind = v("D")
    out: Dict[str, Dict[str, Any]] = {}
    for side, c in CURVES.items():
        out[side] = _side(v, kind, c, fits[side])
    return out


def _side(v: Callable[[str], Any], kind: Any, c: Dict[str, Any], fit: Dict[str, Any]) -> Dict[str, Any]:
    if kind in NO_CURVE:
        return {"why": NO_CURVE[kind]}
    if kind not in ("S", "B"):
        return {"why": "kâğıdın türü bilinmiyor (DİBS RV)"}
    if v("DG") is not True:
        state = v("BE")
        return {"why": "DİBS RV kâğıdı hesaplamıyor" + (": %s" % state if isinstance(state, str) and state else "")}
    if fit["coef"] is None:
        return {"why": "%s ASW eğrisi uydurulamadı (DİBS RV: en az 2 sabit kuponlu kâğıt gerekir; eğride %d kâğıt)" % (c["name"], fit["n"])}
    t, pv, ann, dd, acc = v("FW"), v(c["pv"]), v(c["ann"]), v("DD"), v("CW")
    if type(pv) is not float or type(ann) is not float or ann <= 0:
        return {"why": "%s eğrisi bu vadeye uzanmıyor: kâğıdın bu eğrideki bugünkü değeri yok" % c["name"]
                if c["name"] != "OIS" else "OIS eğrisinde kâğıdın bugünkü değeri yok"}
    if not all(type(x) is float for x in (t, dd, acc)) or dd <= 0:
        return {"why": "DİBS RV'de vade / fonlama çarpanı / işlemiş faiz yok"}
    asw = curve_asw(fit["coef"], t)
    dirty_spot = pv - asw * ann / 100.0
    dirty = dirty_spot / dd
    out = {"asw": asw, "t": t, "pv": pv, "ann": ann, "dd": dd, "acc": acc, "dirty_spot": dirty_spot, "dirty": dirty,
           "price": dirty - acc, "bill": kind == "B"}
    span = fit["span"]
    out["stretched"] = span is None or not (span[0] - STRETCH <= t <= span[1] + STRETCH)
    if kind == "B":
        days = v("DR")
        y = bill_yield(dirty, days) if type(days) is float else None
    else:
        freq = v("CU")
        flows = _flows(v)
        start = v("DX") if type(v("DX")) is float else 0.3
        simple = coupon_yield(dirty, flows, freq, start) if type(freq) is float else None
        y = (1.0 + simple / freq) ** freq - 1.0 if simple is not None else None
    if y is None:
        return dict(out, why="bu fiyattan getiri bulunamadı")
    out["yield"] = y
    return out


def _flows(v: Callable[[str], Any]) -> List[Tuple[float, float]]:
    """A coupon bond's cash flows and their times in coupon periods, as DİBS RV lays them out (``ID:JA``, ``LV:MS``)."""
    cf0, x0, n = _col(FLOWS[0]), _col(FLOWS[1]), FLOWS[2]
    out = []
    for k in range(n):
        cf, x = v(index_to_col(cf0 + k)), v(index_to_col(x0 + k))
        if type(cf) is float and type(x) is float and cf != 0.0:
            out.append((cf, x))
    return out
