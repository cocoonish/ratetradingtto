"""Günlük İşlemler (daily blotter): pricing helpers for trade entry and the position / cost summary.

Everything that is a market calculation is read from the workbook itself (the Forward sheet's own cells
with the value date typed into ``Forward!D2`` / the bulk-pricing row, the OIS annuities of ``Motor``), so
the numbers are the ones Excel shows.  What is new here is only bookkeeping: turning a spread / fly / FRA
into its legs and the cost ("maliyet") of the net position.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from .xl.engine import Calc
from .xl.errors import XlError
from .xl.model import COLS, parse_a1
from .xl.values import serial_to_date

SHEET = "Günlük İşlemler"
FWD_ROWS = (3, 200)        # A:D
OIS_ROWS = (3, 250)        # H:M  (the tenor summary reads to row 200, the counterparty pivot to row 250)
BOND_ROWS = (3, 250)       # Y:AA
OIS_TENORS = ["ON", "1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y", "15M", "18M", "21M", "2Y", "3Y", "4Y", "5Y",
              "6Y", "7Y", "8Y", "9Y", "10Y"]
TENOR_MONTHS = {"1M": 1, "2M": 2, "3M": 3, "6M": 6, "9M": 9, "1Y": 12, "15M": 15, "18M": 18, "21M": 21, "2Y": 24,
                "3Y": 36, "4Y": 48, "5Y": 60, "6Y": 72, "7Y": 84, "8Y": 96, "9Y": 108, "10Y": 120}
# OIS_MAIN outright table: tenor label -> row (A9:A26); Motor row = 316 + that row
OIS_ROW = {"1M": 9, "2M": 10, "3M": 11, "6M": 12, "9M": 13, "1Y": 14, "15M": 15, "18M": 16, "21M": 17, "2Y": 18,
           "3Y": 19, "4Y": 20, "5Y": 21, "6Y": 22, "7Y": 23, "8Y": 24, "9Y": 25, "10Y": 26}
FWD_BASES = ("RET_BID", "RET_MID", "RET_ASK", "TRY", "FWD")


class TradeError(ValueError):
    pass


def _num(v: Any, what: str) -> float:
    if type(v) is float and v == v:
        return v
    raise TradeError("%s hesaplanamadı (%r)" % (what, v.code if type(v) is XlError else v))


def month_label(m: int) -> str:
    if m >= 12 and m % 12 == 0:
        return "%dY" % (m // 12)
    return "%dM" % m


# ---------------------------------------------------------------------------------------------- FX forward
def price_forward(book, base_overlay: Dict[Tuple[int, int], Any], value_date: float, basis: str,
                  manual: Optional[float] = None) -> Dict[str, Any]:
    """Price a USDTRY forward for ``value_date`` exactly as the Forward sheet does.

    ``basis``  RET_BID / RET_MID / RET_ASK -> the 'RET' row of the USDTRY outright table (Forward!D33:F33)
               TRY  -> ``manual`` is a TRY simple ACT/360 rate (fraction); bulk-pricing formula (Forward!N)
               FWD  -> ``manual`` is the forward outright; the implied TRY rate is backed out
    """
    if basis not in FWD_BASES:
        raise TradeError("bilinmeyen fiyatlama tipi: %r" % basis)
    eng = book.engine
    cell = book.cell
    overlay = dict(base_overlay)
    d2 = cell("Forward!D2")
    b_row = cell("Forward!B163")
    l_row = cell("Forward!L163")
    overlay[d2] = float(value_date)
    overlay[b_row] = float(value_date)
    overlay[l_row] = (manual * 100.0) if (basis == "TRY" and manual is not None) else None
    calc = Calc(eng, eng.shared, overlay)

    def v(ref: str) -> Any:
        si, rc = cell(ref)
        r, c = divmod(rc, COLS)
        return calc.get(si, r, c)

    days = _num(v("Forward!U27"), "gün sayısı")
    if days <= 0:
        raise TradeError("valör spot tarihinden sonra olmalı")
    spot = _num(v("Forward!F2"), "spot")
    usd_bid, usd_mid, usd_ask = v("Forward!W27"), v("Forward!X27"), v("Forward!Y27")
    ret_bid, ret_ask = v("Forward!W48"), v("Forward!X48")
    df_try, df_usd = v("Forward!O37"), v("Forward!O42")        # 'Forward DV01' block: TRY OIS and USD OIS discount factors
    table = {}
    for name, row in (("ICAP", 30), ("OIS", 31), ("VIOP", 32), ("RET", 33)):
        table[name] = {"bid": v("Forward!D%d" % row), "mid": v("Forward!E%d" % row), "ask": v("Forward!F%d" % row)}
    out: Dict[str, Any] = {
        "value_date": float(value_date), "days": days, "spot": spot, "basis": basis,
        "usd_bid": usd_bid, "usd_mid": usd_mid, "usd_ask": usd_ask, "ret_bid": ret_bid, "ret_ask": ret_ask,
        "ret_mid": (ret_bid + ret_ask) / 2.0 if type(ret_bid) is float and type(ret_ask) is float else None,
        "table": {k: {s: (x if type(x) is float else None) for s, x in d.items()} for k, d in table.items()},
    }
    if basis == "RET_BID":
        fwd = _num(table["RET"]["bid"], "RET bid forward")
        rate = _num(ret_bid, "RET bid")
        usd = usd_ask
    elif basis == "RET_ASK":
        fwd = _num(table["RET"]["ask"], "RET ask forward")
        rate = _num(ret_ask, "RET ask")
        usd = usd_bid
    elif basis == "RET_MID":
        fwd = _num(table["RET"]["mid"], "RET mid forward")
        usd = usd_mid
        rate = (_num(ret_bid, "RET bid") + _num(ret_ask, "RET ask")) / 2.0      # the sheet's 'RET MID'
    elif basis == "TRY":
        if manual is None:
            raise TradeError("TRY faizi girilmedi")
        fwd = _num(v("Forward!N163"), "forward")
        rate = float(manual)
        usd = _num(v("Forward!J163"), "USD faiz") / 100.0        # the USD mid the bulk row itself uses
    else:
        if manual is None or manual <= 0:
            raise TradeError("forward kur girilmedi")
        fwd = float(manual)
        usd = _num(v("Forward!J163"), "USD faiz") / 100.0        # same convention as the TRY-rate pricing
        rate = ((fwd / spot) * (1.0 + usd * days / 360.0) - 1.0) * 360.0 / days
    out.update({
        "forward": fwd, "try_rate": rate, "usd_rate": usd if type(usd) is float else None,
        "points": (fwd - spot) * 10000.0, "daily_points": (fwd - spot) * 10000.0 / days,
        "on_equiv": 360.0 * ((1.0 + rate * days / 360.0) ** (1.0 / days) - 1.0) if rate > -1 else None,
        "df_try": df_try if type(df_try) is float else None, "df_usd": df_usd if type(df_usd) is float else None,
    })
    # per 1 mn USD bought, so that the form can show the risk before an amount is typed
    out["dv01_1m"] = forward_dv01("B", 1e6, fwd, days, spot, out["df_try"], out["df_usd"], rate, out["usd_rate"])
    return out


def forward_dv01(direction: str, amount: float, forward: float, days: float, spot: Optional[float],
                 df_try: Optional[float] = None, df_usd: Optional[float] = None, try_rate: Optional[float] = None,
                 usd_rate: Optional[float] = None) -> Dict[str, Optional[float]]:
    """DV01 of an FX forward as the Forward sheet's 'Forward DV01' block has it (Forward!N31:P49).

    ``tl``   TL for +1 bp on the TRY rate  = ±amount·forward·T·DF_TRY/10000   (+ for a purchase of USD)
    ``usd``  the same in USD at spot                                           (the sheet's TRY_USD_DV01)
    ``usd_leg``  USD for +1 bp on the USD rate = ∓amount·T·DF_USD/10000

    T = days/360.  Without the sheet's discount factors (a trade stored before they were kept) the trade's
    own simple rates stand in for them.
    """
    try:
        t = float(days) / 360.0
        sign = 1.0 if direction == "B" else -1.0
        if type(df_try) is not float and type(try_rate) is float:
            df_try = 1.0 / (1.0 + try_rate * t)
        if type(df_usd) is not float and type(usd_rate) is float:
            df_usd = 1.0 / (1.0 + usd_rate * t)
        tl = sign * float(amount) * float(forward) * t * df_try / 10000.0 if type(df_try) is float else None
        usd_leg = -sign * float(amount) * t * df_usd / 10000.0 if type(df_usd) is float else None
    except (TypeError, ValueError, ZeroDivisionError):
        return {"tl": None, "usd": None, "usd_leg": None}
    usd = tl / spot if tl is not None and type(spot) is float and spot > 0 else None
    return {"tl": tl, "usd": usd, "usd_leg": usd_leg}


def forward_trade(book, overlay, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate + price a forward trade as typed in the entry form; returns the record to store."""
    direction = str(payload.get("dir", "")).upper()
    if direction not in ("B", "S"):
        raise TradeError("yön B (alış) ya da S (satış) olmalı")
    amount = payload.get("amount")
    if type(amount) is not float or amount <= 0:
        raise TradeError("tutar pozitif bir sayı olmalı")
    vd = payload.get("value_date")
    if type(vd) is not float:
        raise TradeError("valör tarihi gerekli")
    basis = str(payload.get("basis", "RET_MID")).upper()
    manual = payload.get("manual")
    p = price_forward(book, overlay, vd, basis, manual if type(manual) is float else None)
    rec = {
        "dir": direction, "amount": amount, "value_date": vd, "basis": basis,
        "manual": manual if type(manual) is float else None,
        "days": p["days"], "spot": p["spot"], "usd_rate": p["usd_rate"], "try_rate": p["try_rate"],
        "forward": p["forward"], "points": p["points"], "tl": amount * p["forward"],
        "df_try": p.get("df_try"), "df_usd": p.get("df_usd"),
        "cpt": str(payload.get("cpt") or "").strip()[:40], "note": str(payload.get("note") or "").strip()[:200],
    }
    risk = forward_dv01(direction, amount, p["forward"], p["days"], p["spot"], p.get("df_try"), p.get("df_usd"),
                        p["try_rate"], p["usd_rate"])
    rec.update({"dv01_tl": risk["tl"], "dv01": risk["usd"], "usd_dv01": risk["usd_leg"]})
    return rec


# ---------------------------------------------------------------------------------------------- OIS
class OisMarket(object):
    """Par rates and annuities of the TRY OIS curve, read from OIS_MAIN / Motor through the engine."""

    def __init__(self, book, calc):
        self.book = book
        self.calc = calc
        self._fn_cache: Dict[str, Any] = {}

    def value(self, ref: str) -> Any:
        si, rc = self.book.cell(ref)
        r, c = divmod(rc, COLS)
        return self.calc.get(si, r, c)

    def formula(self, text: str) -> Any:
        """Evaluate an ad-hoc Excel formula against the workbook."""
        from .render import calc_value
        from .xl.tokenizer import to_template
        fn = self._fn_cache.get(text)
        if fn is None:
            fn = self.book.engine.compiler.compile_expression(to_template(text, 1, 1), False)
            self._fn_cache[text] = fn
        return calc_value(self.calc, fn, 0, 1, 1)

    @property
    def usdtry(self) -> float:
        return _num(self.value("OIS_MAIN!D2"), "USDTRY")

    @property
    def lot(self) -> float:
        v = self.value("OIS_MAIN!H2")
        return v if type(v) is float and v > 0 else 1.0

    @property
    def default_dv01(self) -> float:
        v = self.value("OIS_MAIN!F2")
        return v if type(v) is float and v > 0 else 1000.0

    def par(self, tenor: str) -> Optional[float]:
        row = OIS_ROW.get(tenor)
        if row is not None:
            v = self.value("OIS_MAIN!B%d" % row)
            return v if type(v) is float else None
        if tenor == "1W":
            v = self.value("OIS_MAIN!AU13")
            return v if type(v) is float else None
        if tenor == "2W":
            v = self.value("OIS_MAIN!AU14")
            return v if type(v) is float else None
        if tenor == "ON":
            v = self.value("OIS_MAIN!J2")
            return v if type(v) is float else None
        return None

    def annuity(self, tenor: str) -> float:
        """PV of 1 bp-year of fixed leg per unit nominal (Motor!I for quoted tenors)."""
        row = OIS_ROW.get(tenor)
        if row is not None:
            return _num(self.value("Motor!I%d" % (316 + row)), "annuity " + tenor)
        days = {"ON": 1.0, "1W": 7.0, "2W": 14.0}.get(tenor)
        if days is None:
            raise TradeError("bilinmeyen vade: %r" % tenor)
        r = self.par(tenor) or 0.0
        return (days / 365.0) / (1.0 + r * days / 365.0)

    def annuity_months(self, months: int) -> float:
        """Annuity of the spot swap to ``months`` on Motor's quarterly grid (OIS_MAIN columns O / P)."""
        if months <= 0:
            return 0.0
        return _num(self.formula("SUMPRODUCT((Motor!$A$139:$A$178*3<=%d)*Motor!$D$139:$D$178*Motor!$O$139:$O$178)"
                                 % months), "annuity %dM" % months)

    def df_months(self, months: int) -> float:
        if months <= 0:
            return 1.0
        return _num(self.formula("INDEX(Motor!$O$139:$O$178,%d)" % (months // 3)), "DF %dM" % months)

    def nominal(self, dv01_usd: float, annuity: float, weight: float = 1.0) -> float:
        """OIS_MAIN sizing rule: ROUND(w*DV01*USDTRY/(A*0.0001)/lot,0)*lot."""
        lot = self.lot
        raw = weight * dv01_usd * self.usdtry / (annuity * 0.0001)
        return _round_half_away(raw / lot) * lot

    def dv01_usd(self, nominal: float, annuity: float) -> float:
        return nominal * annuity * 0.0001 / self.usdtry


def _round_half_away(x: float) -> float:
    f = float("%.15g" % abs(x))
    r = math.floor(f + 0.5)
    return -r if x < 0 else r


def ois_legs(mkt: OisMarket, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Expand an OIS trade (outright / spread / fly / FRA) into the outright legs booked in the blotter.

    Conventions (same as OIS_MAIN): RECEIVE = receive fixed; spread = long − short in bp, FLATTENER =
    receive the long leg / pay the short leg; fly = 2·body − wings in bp, "REC GÖVDE" = receive the body;
    FRA start→end is traded as the two spot swaps with one nominal sized on the forward annuity.
    Size is given per leg as DV01 in USD (fly wings carry half) or as TL nominal.
    """
    strategy = str(payload.get("strategy", "outright")).lower()
    side = str(payload.get("side", "")).upper()
    level = payload.get("level")
    dv01 = payload.get("dv01")
    nominal_in = payload.get("nominal")
    cpt = str(payload.get("cpt") or "").strip()[:40]
    if type(level) is not float:
        raise TradeError("seviye (faiz ya da bp) gerekli")
    if type(dv01) is not float or dv01 <= 0:
        if type(nominal_in) is float and nominal_in > 0:
            dv01 = None
        else:
            dv01 = mkt.default_dv01
    legs: List[Dict[str, Any]] = []
    comma = str(payload.get("_lang") or "tr") != "en"

    def fmt(x: float, digits: int) -> str:
        text = "%.*f" % (digits, x)
        return text.replace(".", ",") if comma else text

    def leg(tenor: str, receive: bool, rate: float, weight: float, role: str, annuity: Optional[float] = None,
            nominal: Optional[float] = None):
        a = annuity if annuity is not None else mkt.annuity(tenor)
        if nominal is None:
            if dv01 is not None:
                nominal = mkt.nominal(dv01, a, weight)
            else:
                nominal = float(nominal_in) * weight
        legs.append({"tenor": tenor, "dir": "S" if receive else "B", "rate": rate, "nominal": nominal,
                     "dv01": mkt.dv01_usd(nominal, a), "role": role, "cpt": cpt, "annuity": a})

    def tenor_of(key: str) -> str:
        t = str(payload.get(key) or "").upper().strip()
        if t not in OIS_TENORS:
            raise TradeError("geçersiz vade: %r" % t)
        return t

    def market(t: str) -> float:
        p = mkt.par(t)
        if p is None:
            raise TradeError("%s için piyasa kotası yok" % t)
        return p

    label = ""
    if strategy == "outright":
        if side not in ("PAY", "RECEIVE"):
            raise TradeError("yön PAY ya da RECEIVE olmalı")
        t = tenor_of("tenor")
        leg(t, side == "RECEIVE", level, 1.0, "outright")
        label = "%s %s @ %s%%" % (side, t, fmt(level * 100.0, 4))
        mid = mkt.par(t)
        info = {"market": mid, "cost_bp": None if mid is None else
                ((mid - level) if side == "RECEIVE" else (level - mid)) * 10000.0}
    elif strategy == "spread":
        if side not in ("FLATTENER", "STEEPENER"):
            raise TradeError("yön FLATTENER ya da STEEPENER olmalı")
        ts, tl = tenor_of("short"), tenor_of("long")
        if OIS_TENORS.index(ts) >= OIS_TENORS.index(tl):
            raise TradeError("kısa vade uzun vadeden önce olmalı")
        rs = payload.get("short_rate")
        rs = rs if type(rs) is float else market(ts)
        rl = rs + level / 10000.0
        flat = side == "FLATTENER"
        leg(ts, not flat, rs, 1.0, "short")
        leg(tl, flat, rl, 1.0, "long")
        label = "%s %s/%s @ %s bp" % (side, ts, tl, fmt(level, 2))
        mkt_level = (market(tl) - market(ts)) * 10000.0
        info = {"market": mkt_level, "cost_bp": (mkt_level - level) if flat else (level - mkt_level)}
    elif strategy == "fly":
        if side not in ("REC GÖVDE", "PAY GÖVDE", "REC GOVDE", "PAY GOVDE"):
            raise TradeError("yön REC GÖVDE ya da PAY GÖVDE olmalı")
        t1, tb, t2 = tenor_of("wing1"), tenor_of("body"), tenor_of("wing2")
        if not (OIS_TENORS.index(t1) < OIS_TENORS.index(tb) < OIS_TENORS.index(t2)):
            raise TradeError("vadeler kanat < gövde < kanat sırasında olmalı")
        r1 = payload.get("wing1_rate")
        r1 = r1 if type(r1) is float else market(t1)
        r2 = payload.get("wing2_rate")
        r2 = r2 if type(r2) is float else market(t2)
        rb = (level / 10000.0 + r1 + r2) / 2.0
        rec_body = side.startswith("REC")
        leg(t1, not rec_body, r1, 0.5, "wing1")
        leg(tb, rec_body, rb, 1.0, "body")
        leg(t2, not rec_body, r2, 0.5, "wing2")
        label = "%s %s/%s/%s @ %s bp" % ("REC GÖVDE" if rec_body else "PAY GÖVDE", t1, tb, t2, fmt(level, 2))
        mkt_level = (2.0 * market(tb) - market(t1) - market(t2)) * 10000.0
        info = {"market": mkt_level, "cost_bp": (mkt_level - level) if rec_body else (level - mkt_level)}
    elif strategy == "fra":
        if side not in ("PAY", "RECEIVE"):
            raise TradeError("yön PAY ya da RECEIVE olmalı")
        m1, m2 = payload.get("start_months"), payload.get("end_months")
        if type(m1) is not float or type(m2) is not float:
            raise TradeError("başlangıç ve bitiş (ay) gerekli")
        m1, m2 = int(m1), int(m2)
        if m1 < 0 or m2 <= m1 or m1 % 3 or m2 % 3 or m2 > 120:
            raise TradeError("FRA ayları 3'ün katı olmalı (0 ≤ başlangıç < bitiş ≤ 120)")
        a1, a2 = mkt.annuity_months(m1), mkt.annuity_months(m2)
        fwd_annuity = a2 - a1
        if fwd_annuity <= 0:
            raise TradeError("forward annuity hesaplanamadı")
        if dv01 is not None:
            nominal = mkt.nominal(dv01, fwd_annuity, 1.0)
        else:
            nominal = float(nominal_in)
        end_par = (1.0 - mkt.df_months(m2)) / a2
        rec = side == "RECEIVE"
        if m1 == 0:
            leg(month_label(m2), rec, level, 1.0, "end", annuity=a2, nominal=nominal)
            mkt_level = end_par
        else:
            start_par = (1.0 - mkt.df_months(m1)) / a1
            q = payload.get("start_rate")
            q = q if type(q) is float else start_par
            # achieved FRA = (R·A2 − Q·A1)/(A2 − A1)  =>  R = (FRA·(A2 − A1) + Q·A1)/A2
            r_end = (level * fwd_annuity + q * a1) / a2
            leg(month_label(m1), not rec, q, 1.0, "start", annuity=a1, nominal=nominal)
            leg(month_label(m2), rec, r_end, 1.0, "end", annuity=a2, nominal=nominal)
            mkt_level = (end_par * a2 - start_par * a1) / fwd_annuity
        label = "%s FRA %s→%s @ %s%%" % (side, "Spot" if m1 == 0 else month_label(m1), month_label(m2), fmt(level * 100.0, 4))
        info = {"market": mkt_level, "cost_bp": ((mkt_level - level) if rec else (level - mkt_level)) * 10000.0}
    else:
        raise TradeError("bilinmeyen strateji: %r" % strategy)
    # cost versus market mid in money terms: the bp given away on the leg that carries the price
    if strategy == "fra":
        risk_dv01 = abs(legs[-1]["dv01"] - (legs[0]["dv01"] if len(legs) > 1 else 0.0))
    elif strategy == "fly":
        risk_dv01 = legs[1]["dv01"] / 2.0          # the body rate moves by half the fly level
    else:
        risk_dv01 = legs[-1]["dv01"]
    cost_bp = info.get("cost_bp")
    info["cost_usd"] = None if cost_bp is None else cost_bp * risk_dv01
    info["cost_tl"] = None if cost_bp is None else cost_bp * risk_dv01 * mkt.usdtry
    # + = pays fixed (gains when rates rise), as the blotter sheet's "Net" column: pay − receive
    net = sum(lg["dv01"] if lg["dir"] == "B" else -lg["dv01"] for lg in legs)
    return {"strategy": strategy, "side": side, "level": level, "label": label, "legs": legs, "info": info,
            "usdtry": mkt.usdtry, "dv01": {"net": net, "gross": sum(lg["dv01"] for lg in legs)}}


# ---------------------------------------------------------------------------------------------- bonds
BOND_SHEET = "DİBS RV"
BOND_ROWS_RV = (5, 54)
_BOND_COLUMNS = {"isin": "ISIN", "name": "Ad", "maturity": "Vade", "clean": "Kullanılan temiz", "mod_dur": "Mod. süre",
                 "dv01_mn": "DV01 TL / 1mn"}


def bond_info(book, calc, instrument: str) -> Optional[Dict[str, Any]]:
    """What the DİBS RV table knows about a bond typed into the blotter (by ISIN): name, maturity, the clean
    price in use, modified duration and DV01 in TL per 1 mn nominal.  ``None`` when the bond is not listed."""
    key = "".join(str(instrument or "").upper().split())
    if not key or BOND_SHEET not in book.model.sheet_index:
        return None
    si = book.model.sheet_index[BOND_SHEET]
    sh = book.model.sheets[si]
    cols: Dict[str, int] = {}
    for c in range(1, sh.max_col + 1):
        text = sh.consts.get(4 * COLS + c)
        if isinstance(text, str):
            for name, label in _BOND_COLUMNS.items():
                if name not in cols and text.strip().startswith(label):
                    cols[name] = c
    if "isin" not in cols or "dv01_mn" not in cols:
        return None
    for r in range(BOND_ROWS_RV[0], BOND_ROWS_RV[1] + 1):
        isin = calc.get(si, r, cols["isin"])
        if not isinstance(isin, str) or not isin.strip():
            continue
        code = "".join(isin.upper().split())
        if code == key or (len(key) >= 6 and (key in code or code in key)):
            out: Dict[str, Any] = {"isin": isin.strip(), "row": r}
            for name in ("name", "maturity", "clean", "mod_dur", "dv01_mn"):
                v = calc.get(si, r, cols[name]) if name in cols else None
                out[name] = v if type(v) in (float, str) else None
            return out
    return None


def bond_dv01(amount: float, info: Optional[Dict[str, Any]], usdtry: Optional[float]) -> Dict[str, Optional[float]]:
    """DV01 of a bond trade for +1 bp of yield: a purchase loses, so it is negative (TL, and USD at spot)."""
    per_mn = info.get("dv01_mn") if info else None
    if type(per_mn) is not float:
        return {"tl": None, "usd": None}
    tl = -float(amount) / 1e6 * per_mn
    return {"tl": tl, "usd": tl / usdtry if type(usdtry) is float and usdtry > 0 else None}


# ---------------------------------------------------------------------------------------------- risk of the day
def risk_summary(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """DV01 of the listed trades in USD for +1 bp on TRY rates: USD bought forward and fixed paid are positive,
    USD sold forward, fixed received and bonds bought are negative.  Trades without a DV01 (a bond the DİBS
    table does not list) are counted in ``unknown``."""
    out: Dict[str, Any] = {"fwd": 0.0, "fwd_tl": 0.0, "ois": 0.0, "ois_gross": 0.0, "bond": 0.0, "bond_tl": 0.0, "unknown": 0}
    for t in trades:
        k = t.get("kind")
        if k == "fwd":
            if type(t.get("dv01")) is float:
                out["fwd"] += t["dv01"]
                out["fwd_tl"] += t.get("dv01_tl") or 0.0
            else:
                out["unknown"] += 1
        elif k == "ois":
            d = t.get("dv01")
            if type(d) is float:
                out["ois"] += d if t.get("dir") == "B" else -d
                out["ois_gross"] += d
        elif k == "bond":
            if type(t.get("dv01")) is float:
                out["bond"] += t["dv01"]
                out["bond_tl"] += t.get("dv01_tl") or 0.0
            else:
                out["unknown"] += 1
    out["total"] = out["fwd"] + out["ois"] + out["bond"]
    return out


# ---------------------------------------------------------------------------------------------- cost of position
def position_cost(buys: List[Tuple[float, float]], sells: List[Tuple[float, float]]) -> Dict[str, Any]:
    """'Maliyet' as on the Calculators sheet: break-even level of the net position.

    ``buys`` / ``sells`` are (size, level) pairs.  Net = ΣA_buy − ΣA_sell, cost = (A₁R₁ − A₂R₂)/(A₁ − A₂),
    realised = min(A₁, A₂)·(R₂ − R₁).
    """
    a1 = sum(a for a, _ in buys)
    a2 = sum(a for a, _ in sells)
    r1 = sum(a * r for a, r in buys) / a1 if a1 else None
    r2 = sum(a * r for a, r in sells) / a2 if a2 else None
    net = a1 - a2
    cost = None
    if a1 and a2:
        if net != 0:
            cost = (a1 * r1 - a2 * r2) / net
    elif a1:
        cost = r1
    elif a2:
        cost = r2
    realised = min(a1, a2) * (r2 - r1) if (a1 and a2) else 0.0
    return {"buy": a1, "buy_avg": r1, "sell": a2, "sell_avg": r2, "net": net, "cost": cost, "realised": realised}


def summarise(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Position and cost per forward value date bucket, OIS tenor and bond instrument."""
    fwd: Dict[float, Dict[str, List[Tuple[float, float]]]] = {}
    ois: Dict[str, Dict[str, List[Tuple[float, float]]]] = {}
    bonds: Dict[str, Dict[str, List[Tuple[float, float]]]] = {}
    for t in trades:
        k = t.get("kind")
        if k == "fwd":
            d = fwd.setdefault(t["value_date"], {"B": [], "S": []})
            d[t["dir"]].append((t["amount"], t["forward"]))
        elif k == "ois":
            d = ois.setdefault(t["tenor"], {"B": [], "S": []})
            d[t["dir"]].append((t["dv01"], t["rate"]))
        elif k == "bond":
            d = bonds.setdefault(t["instrument"], {"B": [], "S": []})
            if t["amount"] >= 0:
                d["B"].append((t["amount"], t["price"]))
            else:
                d["S"].append((-t["amount"], t["price"]))
    out: Dict[str, Any] = {"fwd": [], "ois": [], "bond": []}
    for vd in sorted(fwd):
        pc = position_cost(fwd[vd]["B"], fwd[vd]["S"])
        pc["key"] = vd
        # forwards: realised P&L in TL = matched USD × (sell forward − buy forward)
        out["fwd"].append(pc)
    order = {t: i for i, t in enumerate(OIS_TENORS)}
    for tenor in sorted(ois, key=lambda x: order.get(x, 999)):
        # pay = "B" (buy the rate), receive = "S"; realised in USD = matched DV01 × (receive − pay) in bp
        pc = position_cost(ois[tenor]["B"], ois[tenor]["S"])
        pc["key"] = tenor
        pc["realised"] = pc["realised"] * 10000.0
        out["ois"].append(pc)
    for inst in sorted(bonds):
        pc = position_cost(bonds[inst]["B"], bonds[inst]["S"])
        pc["key"] = inst
        pc["realised"] = pc["realised"] / 100.0
        out["bond"].append(pc)
    return out


def overnight_equivalent(rate: Any, days: Any) -> Optional[float]:
    """O/N equivalent (360) of a forward trade's TRY rate, as column F of the blotter sheet computes it:
    ``360*((1+rate*days/365)^(1/days)-1)``."""
    try:
        r, d = float(rate), float(days)
    except (TypeError, ValueError):
        return None
    if d <= 0 or 1.0 + r * d / 365.0 <= 0:
        return None
    return 360.0 * ((1.0 + r * d / 365.0) ** (1.0 / d) - 1.0)


# ---------------------------------------------------------------------------------------------- sheet sync
def sheet_values(book, trades: List[Dict[str, Any]]) -> Dict[Tuple[int, int], Any]:
    """Cell values of the three input lists of the 'Günlük İşlemler' sheet for the given trades."""
    si = book.model.sheet_index[SHEET]
    vals: Dict[Tuple[int, int], Any] = {}

    def put(col: str, row: int, v: Any):
        vals[(si, parse_a1("%s%d" % (col, row)))] = v

    for r in range(FWD_ROWS[0], FWD_ROWS[1] + 1):
        for col in "ABCD":
            put(col, r, None)
    for r in range(OIS_ROWS[0], OIS_ROWS[1] + 1):
        for col in "HIJKLM":
            put(col, r, None)
    for r in range(BOND_ROWS[0], BOND_ROWS[1] + 1):
        for col in ("Y", "Z", "AA"):
            put(col, r, None)
    rf, ro, rb = FWD_ROWS[0], OIS_ROWS[0], BOND_ROWS[0]
    for t in trades:
        k = t.get("kind")
        if k == "fwd" and rf <= FWD_ROWS[1]:
            put("A", rf, t["dir"])
            put("B", rf, float(t["amount"]))
            put("C", rf, float(t["try_rate"]))
            put("D", rf, float(t["value_date"]))
            rf += 1
        elif k == "ois" and ro <= OIS_ROWS[1]:
            put("H", ro, float(t["nominal"]) if t.get("nominal") else None)
            put("I", ro, float(t["dv01"]))
            put("J", ro, t["dir"])
            put("K", ro, float(t["rate"]))
            put("L", ro, t["tenor"])
            put("M", ro, t.get("cpt") or None)
            ro += 1
        elif k == "bond" and rb <= BOND_ROWS[1]:
            put("Y", rb, t["instrument"])
            put("Z", rb, float(t["amount"]))
            put("AA", rb, float(t["price"]))
            rb += 1
    return vals


def input_ranges() -> List[str]:
    return ["%s!A%d:D%d" % (SHEET, FWD_ROWS[0], FWD_ROWS[1]), "%s!H%d:M%d" % (SHEET, OIS_ROWS[0], OIS_ROWS[1]),
            "%s!Y%d:AA%d" % (SHEET, BOND_ROWS[0], BOND_ROWS[1])]
