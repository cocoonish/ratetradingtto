"""What a bond of the trading list is worth on the two ASW curves the desk fits - the TLREF OIS curve (DİBS RV) and the
FX swap implied TRY curve (DİBS ASW, EK_FX): the yield and the clean price at which its ASW would sit on the curve
("adil getiri", "adil fiyat" on DİBS Trading, the bond's card and DİBS RV · Genel).

**OIS: DİBS RV's own columns.**  For every bond it has the present value of the cash flows on the OIS curve (``EG``),
the quarterly annuity on it (``EE``) and the dirty price at the value date carried to the OIS spot (``DI`` = ``DH`` ×
the funding factor ``DD``); its ASW is ``(PV − dirty @spot) / annuity × 100``.  The curve's fit is ``a + b·t + c·t²``
over the fixed coupon bonds (``CA3:CC3``; ``t`` the years from the OIS spot to maturity, ``FW``).

**FX swap: DİBS ASW's sheet on the FX swap implied TRY curve** - the ASW sheet with the OIS quotes it builds its curve
from swapped for the rates of EK_FX, each read by its own convention (TRYI 1–12M FX swap implied: one period, simple
ACT/360; TRYSAQ 2–10Y XCCY: annual ACT/360 par - as the desk's workbook reads them; 18M computed off the offshore XCCY
curve, ``aswfx.point_18m``) and given to the sheet as the par
quote of the sheet's own convention with the same discount factor at the tenor (``aswfx``; a tenor without a price keeps
its OIS quote: ``Service._asw_fx_calc``), the calculation behind DİBS ASW's "ASW FX" column and its FX swap chart.  The desk
chose this curve for every FX swap figure a trader reads (DİBS Trading, the card, Genel); DİBS RV's own FX columns
(``BF:BJ``, on the offshore ICAP curve) stay the workbook's, on the RV sheet only.  Per bond (its row found by ISIN):
``P`` the PV on the curve, ``Q`` the annuity, ``O`` the dirty price at the spot (``(L + N) × (1 + TLREF × days / 365)``),
``R`` its ASW, ``S`` the fitted curve's ASW at its ``J`` years (``AW3:AY3``, fitted by the sheet's own rule: its
"Eğri / grafik" column), ``T`` = R − S (+ cheap).  The signal is DİBS RV's: beyond its threshold (``P2``, "Eşik (bp)")
UCUZ / PAHALI.

**The fair value.**  At the curve's ASW the dirty price at the spot is ``PV − ASW_curve × annuity / 100``; back at the
value date it is that ÷ the funding factor, the clean price that − the accrued interest (DİBS RV ``CW``; DİBS ASW ``N``),
and the yield is the screen's BIST compound yield of that price, worked out as DİBS RV works out its own: a bill's
``(100 / dirty)^(365 / days) − 1`` (``DR`` days), a coupon bond's ``(1 + y/f)^f − 1`` with ``y`` the rate that discounts
its cash flows (``ID:JA`` at ``LV:MS`` coupon periods, ``f`` = ``CU`` a year) to the dirty price - on the FX side the
bond's own row of DİBS RV, at the same value date.  At the bond's own ASW the fair price is its price: what the fair
value tells is where the curve puts it.

A bill is in neither OIS fit (the curve is the fixed coupon bonds'): its fair value reads the curve at its own years and
says so; read further than a quarter of a year outside the years of the bonds fitted (as far as the ASW page draws the
curve) it is the curve stretched - shown soft.  A TLREF floater, an FRN and a CPI linker have no ASW curve to sit on:
no fair value, the reason given instead."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .xl.tokenizer import col_to_index, index_to_col
from .xl.values import serial_to_date

FIRST, LAST = 5, 54                      # the rows of the trading list (DİBS RV!A5:A54)
#: DİBS RV's OIS curve: the fit's a / b / c (row 3) and the count of its bonds, each row's "in the fit" flag and its
#: years, the present value and the annuity on the curve
CURVES: Dict[str, Dict[str, Any]] = {
    "ois": {"name": "OIS", "coef": ("CA", "CB", "CC"), "n": "BR", "flag": "FR", "t": "FS", "pv": "EG", "ann": "EE"},
}
#: DİBS ASW's sheet on the FX swap implied curve: its bond rows, the fit (row 3) and a bond's columns
FX_SHEET, FX_FIRST, FX_LAST = "ASW", 7, 56
FX: Dict[str, Any] = {"name": "FX swap", "coef": ("AW", "AX", "AY"), "n": "AN", "span": ("AZ", "BA"), "isin": "B", "t": "J",
                      "clean": "L", "valor": "M", "acc": "N", "dirty_spot": "O", "pv": "P", "ann": "Q", "asw": "R", "curve": "S",
                      "rich": "T", "state": "U"}
#: the curve's name wherever a page names it (the ASW page's own name of it)
FX_CURVE_TEXT = "FX swap ima eğrisi (TRYI 1–12A FX swap ima, 18A XCCY eğrisinden, TRYSAQ 2–10Y XCCY; fiyatı yoksa OIS)"
FLOWS = ("ID", "LV", 24)                 # a bond's cash flows, their times in coupon periods, how many at most
STRETCH = 0.25                           # years outside the bonds fitted that the curve is read as it is drawn
#: why a kind of bond has no fair value (DİBS RV's type: T, F, E)
NO_CURVE = {"T": "TLREF'e endeksli: ASW eğrileri sabit kuponlulara uydurulur, DM için uydurulmuş eğri yok - adil fiyat yok "
                 "(kâğıdın DM'i ASW / DM sütununda)",
            "F": "FRN: yalnız fiyatla izlenir, eğriye karşı hesap yok",
            "E": "TÜFE'ye endeksli: reel getiri, ASW yok"}


def _col(letters: str) -> int:
    return col_to_index(letters)


def isin_of(v: Any) -> str:
    return "".join(v.split()).upper() if isinstance(v, str) else ""


class FxCurve(object):
    """DİBS ASW's sheet on the FX swap implied TRY curve: its calculation (``calc``, the sheet ``si``), the row of each of
    its bonds (``rows``: ISIN -> row) and how many tenors had an FX swap price (``swapped``)."""

    __slots__ = ("calc", "si", "rows", "swapped")

    def __init__(self, calc, si: int, rows: Dict[str, int], swapped: int):
        self.calc, self.si, self.rows, self.swapped = calc, si, rows, swapped

    def get(self, r: int, col: str) -> Any:
        return self.calc.get(self.si, r, _col(col))


def fx_rows(calc, si: int) -> Dict[str, int]:
    """DİBS ASW's bonds: ISIN -> its row (the first, should one be there twice)."""
    out: Dict[str, int] = {}
    for r in range(FX_FIRST, FX_LAST + 1):
        code = isin_of(calc.get(si, r, _col(FX["isin"])))
        if code and code not in out:
            out[code] = r
    return out


def read_fits(calc, si: int, fx: Optional[FxCurve] = None) -> Dict[str, Dict[str, Any]]:
    """Each curve's fit: ``coef`` (a, b, c - None while it has too few bonds), ``n`` (its bonds) and ``span`` (the years
    of the bonds fitted, shortest and longest) - OIS as DİBS RV has it, FX swap as DİBS ASW has it on that curve (``fx``;
    none without it, ``why`` says so)."""
    c = CURVES["ois"]
    coef = [calc.get(si, 3, _col(x)) for x in c["coef"]]
    n = calc.get(si, 3, _col(c["n"]))
    ts = [calc.get(si, r, _col(c["t"])) for r in range(FIRST, LAST + 1) if calc.get(si, r, _col(c["flag"])) == 1.0]
    ts = [t for t in ts if type(t) is float]
    out = {"ois": {"coef": coef if all(type(x) is float for x in coef) else None, "n": int(n) if type(n) is float else 0,
                   "span": (min(ts), max(ts)) if ts else None}}
    out["fx"] = read_fx_fit(fx)
    return out


def read_fx_fit(fx: Optional[FxCurve]) -> Dict[str, Any]:
    """DİBS ASW's fit on the FX swap implied curve (``AW3:AY3``, its count ``AN3``, its years ``AZ3:BA3``)."""
    if fx is None:
        return {"coef": None, "n": 0, "span": None, "why": "EK_FX'te hiçbir vadenin fiyatı yok: %s kurulamadı" % FX_CURVE_TEXT}
    coef = [fx.get(3, x) for x in FX["coef"]]
    n = fx.get(3, FX["n"])
    lo, hi = (fx.get(3, x) for x in FX["span"])
    return {"coef": coef if all(type(x) is float for x in coef) else None, "n": int(n) if type(n) is float else 0,
            "span": (lo, hi) if type(lo) is float and type(hi) is float else None}


def curve_asw(coef: Sequence[float], t: float) -> float:
    """The fitted curve's ASW (bp) at ``t`` years."""
    a, b, c = coef
    return a + b * t + c * t ** 2


def signal(rich: Any, threshold: Any) -> str:
    """DİBS RV's signal of a cheap / rich figure (bp): UCUZ beyond its threshold, PAHALI below minus it, "–" between."""
    if type(rich) is not float:
        return ""
    th = threshold if type(threshold) is float else 0.0
    return "UCUZ" if rich > th else ("PAHALI" if rich < -th else "–")


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


def fair(calc, si: int, r: int, fits: Dict[str, Dict[str, Any]], fx: Optional[FxCurve] = None) -> Dict[str, Dict[str, Any]]:
    """The fair values of the bond on row ``r`` of DİBS RV, curve by curve (``ois``, ``fx``): ``asw`` (the curve's ASW at
    its ``t`` years), ``pv``, ``ann``, ``dd`` (the funding factor), ``acc`` (accrued), ``dirty_spot``, ``dirty`` (at its
    value date), ``price`` (clean), ``yield`` (BIST compound), ``bill`` (read off the curve, not in it), ``stretched``
    (outside the years fitted); or ``why`` there is none.  The FX side also has the bond's own ``own`` ASW, its ``rich``
    (+ cheap) and the curve's ASW ``curve`` as DİBS ASW has them (when it has them, whatever the fair value)."""
    def v(col: str) -> Any:
        return calc.get(si, r, _col(col))

    kind = v("D")
    return {"ois": _side(v, kind, CURVES["ois"], fits["ois"]), "fx": _fx_side(v, kind, fits["fx"], fx, isin_of(v("A")))}


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
        return {"why": "OIS eğrisinde kâğıdın bugünkü değeri yok"}
    if not all(type(x) is float for x in (t, dd, acc)) or dd <= 0:
        return {"why": "DİBS RV'de vade / fonlama çarpanı / işlemiş faiz yok"}
    return _at_curve(v, kind, curve_asw(fit["coef"], t), t, pv, ann, dd, acc, fit["span"])


def _fx_side(v: Callable[[str], Any], kind: Any, fit: Dict[str, Any], fx: Optional[FxCurve], isin: str) -> Dict[str, Any]:
    if kind in NO_CURVE:
        return {"why": NO_CURVE[kind]}
    if kind not in ("S", "B"):
        return {"why": "kâğıdın türü bilinmiyor (DİBS RV)"}
    if fx is None:
        return {"why": fit.get("why") or "EK_FX'te fiyat yok"}
    ar = fx.rows.get(isin)
    if ar is None:
        return {"why": "kâğıt DİBS ASW listesinde değil: FX swap ASW'si DİBS ASW'nin hesabıdır"}

    def w(key: str) -> Any:
        return fx.get(ar, FX[key])

    out: Dict[str, Any] = {k: x for k, x in (("own", w("asw")), ("rich", w("rich")), ("curve", w("curve"))) if type(x) is float}
    if "own" not in out:
        state = w("state")
        return dict(out, why="DİBS ASW kâğıdı hesaplamıyor" + (": %s" % state if isinstance(state, str) and state else ""))
    if fit["coef"] is None:
        return dict(out, why="FX swap ASW eğrisi uydurulamadı (DİBS ASW: en az 2 kâğıt gerekir; eğride %d kâğıt)" % fit["n"])
    if v("DG") is not True:
        state = v("BE")
        return dict(out, why="DİBS RV kâğıdı hesaplamıyor" + (": %s" % state if isinstance(state, str) and state else ""))
    t, pv, ann, spot, clean, acc = w("t"), w("pv"), w("ann"), w("dirty_spot"), w("clean"), w("acc")
    if not all(type(x) is float for x in (t, pv, ann, spot, clean, acc)) or ann <= 0 or clean + acc <= 0:
        return dict(out, why="DİBS ASW'de PV / annuity / fiyat yok")
    valor, own_valor = w("valor"), v("P")
    if valor != own_valor:
        def day(x: Any) -> str:
            return serial_to_date(x).strftime("%d.%m.%Y") if type(x) is float else "yok"
        return dict(out, why="DİBS ASW'nin valörü (%s) DİBS RV'ninkinden (%s) farklı: getiri hesaplanmadı" % (day(valor), day(own_valor)))
    asw = out["curve"] if "curve" in out else curve_asw(fit["coef"], t)
    got = _at_curve(v, kind, asw, t, pv, ann, spot / (clean + acc), acc, fit["span"])
    return dict(got, **out)


def _at_curve(v: Callable[[str], Any], kind: Any, asw: float, t: float, pv: float, ann: float, dd: float, acc: float,
              span: Optional[Tuple[float, float]]) -> Dict[str, Any]:
    """The bond at the curve's ASW: its dirty price at the spot, at the value date, the clean one and its yield."""
    dirty_spot = pv - asw * ann / 100.0
    dirty = dirty_spot / dd
    out = {"asw": asw, "t": t, "pv": pv, "ann": ann, "dd": dd, "acc": acc, "dirty_spot": dirty_spot, "dirty": dirty,
           "price": dirty - acc, "bill": kind == "B"}
    out["stretched"] = span is None or not (span[0] - STRETCH <= t <= span[1] + STRETCH)
    y = yield_of(v, kind, dirty)
    if y is None:
        return dict(out, why="bu fiyattan getiri bulunamadı")
    out["yield"] = y
    return out


def yield_of(v: Callable[[str], Any], kind: Any, dirty: float) -> Optional[float]:
    """The screen's BIST compound yield of a dirty price of the bond of a DİBS RV row (``v``: its columns), as the sheet
    works out its own: a bill's from its days, a coupon bond's from its cash flows."""
    if kind == "B":
        days = v("DR")
        return bill_yield(dirty, days) if type(days) is float else None
    freq = v("CU")
    flows = _flows(v)
    start = v("DX") if type(v("DX")) is float else 0.3
    simple = coupon_yield(dirty, flows, freq, start) if type(freq) is float else None
    return (1.0 + simple / freq) ** freq - 1.0 if simple is not None else None


def _flows(v: Callable[[str], Any]) -> List[Tuple[float, float]]:
    """A coupon bond's cash flows and their times in coupon periods, as DİBS RV lays them out (``ID:JA``, ``LV:MS``)."""
    cf0, x0, n = _col(FLOWS[0]), _col(FLOWS[1]), FLOWS[2]
    out = []
    for k in range(n):
        cf, x = v(index_to_col(cf0 + k)), v(index_to_col(x0 + k))
        if type(cf) is float and type(x) is float and cf != 0.0:
            out.append((cf, x))
    return out
