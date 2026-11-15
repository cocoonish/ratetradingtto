"""Spot / FX and FX vol: what the option market says about a currency pair, and where its vols stand.

**Quotes.**  Every tenor of a pair has five vol quotes on Bloomberg, in vol points (``tto.fxvol`` says what they
mean): ``<PAIR>V<tenor>`` (ATM), ``<PAIR>25R<tenor>`` / ``10R`` (risk reversals), ``<PAIR>25B<tenor>`` / ``10B``
(butterflies), each with a pricing source (``BGN`` by default, a shared setting) and the yellow key ``Curncy``:
``USDTRY25R3M BGN Curncy``.  The spot is ``<PAIR> Curncy``; forward points ``<ROOT><tenor> Curncy`` - the root is
the non-USD currency of a USD pair (``EUR1M``, ``JPY1M``, ``TRY1M``), the pair itself for a cross (``EURJPY1M``) -
in units of ``10^-FWD_SCALE`` (2 when the quote currency is the yen, 4 otherwise); a year is ``12M`` there, ``1Y``
in the vol tickers.  All of these were checked on the desk's terminal.

**Forwards.**  USDTRY is the TRY desk's own: the forward of each tenor is the one the Forward page prices with the
offshore curve (the ICAP implied TRY rates, ``EK_FWD``'s "TRY rates by tenor" table - its dates are the USDTRY spot
date plus the tenor on the desk's holiday calendar) and the USD OIS of the same days:
``F = spot·(1 + TRY·g/360)/(1 + USD·g/360)``, the very formula of the free forward list.  A TRY cross (EURTRY) is
the product of its USD legs: ``F = F(EURUSD)·F(USDTRY)``, so its TRY side is the offshore curve as well.  Any other
pair: Bloomberg's spot plus its forward points.  Delivery dates of those: the spot date (two week days on) plus the
tenor, the next week day.

**Time.**  ``T`` is the days from the spot date to delivery over 365 - the time from today to expiry, give or take
the two days of the spot lag at both ends.

**History.**  The vol monitor keeps daily closes (``PX_LAST``) in the dashboard's history table, the series named
``<ticker>|PX_LAST``: a year back on the first request, the last ten days after that, never more than once a day for
a series.  Levels and changes follow the workbook's own macro block (Masa, "MAKRO · risk göstergeleri"): week days
with the previous close filled in, the live value against the close 1 / 5 / 21 week days back (Δ1G / Δ1H / Δ1A),
the mean and z-score of the last 63 closes ("3A"), the z-score, percentile (share of closes at or below the live
value), minimum and maximum of the window (a year by default).
"""
from __future__ import annotations

import datetime as _dt
import math
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import fxvol as fv
from .history import add_months, filled
from .marketdata.base import INVALID_FIELD, INVALID_SECURITY, NOT_APPLICABLE, REQUESTING, bdp_key
from .xl.values import serial_to_date

TENORS = ("1W", "2W", "1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y")
#: weeks or months of each tenor
TENOR_SPEC = {"1W": (7, 0), "2W": (14, 0), "1M": (0, 1), "2M": (0, 2), "3M": (0, 3), "6M": (0, 6), "9M": (0, 9),
              "1Y": (0, 12), "18M": (0, 18), "2Y": (0, 24)}
#: the forward point tickers spell a year in months
POINT_TENOR = {"1Y": "12M"}
KINDS = ("ATM", "RR25", "BF25", "RR10", "BF10")
CODE = {"ATM": "V", "RR25": "25R", "BF25": "25B", "RR10": "10R", "BF10": "10B"}
KIND_LABEL = {"ATM": "ATM", "RR25": "25D RR", "BF25": "25D BF", "RR10": "10D RR", "BF10": "10D BF"}
DEFAULT_SOURCE = "BGN"
FIELD = "PX_LAST"
#: the vol monitor's own set per pair (kind, tenor): what is kept with its history for every pair
CORE = (("ATM", "1W"), ("ATM", "1M"), ("ATM", "3M"), ("ATM", "6M"), ("ATM", "1Y"), ("RR25", "1M"), ("RR25", "3M"),
        ("RR25", "1Y"), ("BF25", "1M"), ("BF25", "3M"), ("BF25", "1Y"), ("RR10", "1M"), ("BF10", "1M"))
#: skew: the risk reversal over the ATM vol of the same tenor (a ratio: "how many ATM vols the calls are over the
#: puts"), for the monitor's tenors whose both quotes it keeps: (name, risk reversal, tenor)
SKEWS = (("SKEW25", "RR25", "1M"), ("SKEW25", "RR25", "3M"), ("SKEW25", "RR25", "1Y"), ("SKEW10", "RR10", "1M"))
SKEW_OF = {"SKEW25": "RR25", "SKEW10": "RR10"}
SKEW_LABEL = {"SKEW25": "25D RR / ATM", "SKEW10": "10D RR / ATM"}
#: windows of the percentile / z-score / range (closes): ~3 months, ~6 months, a year
WINDOWS = (63, 126, 250)
LOOKBACK_DAYS = 366                      # the workbook's BDH: TODAY()-366 .. TODAY()-1
Z_FLAG = 1.5                             # the macro block's threshold (MASA!Q171)
EMPTY_RETRY = 6 * 3600.0                 # a series without history is not asked again sooner
YELLOW_KEYS = ("Curncy", "Index", "Comdty", "Govt", "Corp", "Equity", "Mtge", "Muni", "Pfd", "M-Mkt")
#: currencies whose pairs use forward deltas at every tenor (emerging markets)
EM = ("TRY", "ZAR", "MXN", "BRL", "RUB", "PLN", "HUF", "CZK", "CNH", "CNY", "INR", "IDR", "KRW", "TWD", "CLP", "COP",
      "ILS", "PHP", "THB", "SGD", "HKD", "KZT", "EGP", "NGN", "UAH", "RON")


class FxError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------- pairs
class Pair(object):
    """A currency pair and its conventions."""

    __slots__ = ("code", "group", "root", "premium", "spot_until", "decimals", "added")

    def __init__(self, code: str, group: str, premium: bool, spot_until: float, decimals: int, added: bool = False):
        self.code = code
        self.group = group
        base, quote = code[:3], code[3:]
        self.root = quote if base == "USD" else (base if quote == "USD" else code)
        self.premium = premium              # premium-adjusted deltas (the premium is paid in the base currency)
        self.spot_until = spot_until        # spot deltas up to this many years, forward deltas beyond
        self.decimals = decimals
        self.added = added                  # added by the desk (not one of the built-in pairs)

    @property
    def base(self) -> str:
        return self.code[:3]

    @property
    def quote(self) -> str:
        return self.code[3:]

    @property
    def scale(self) -> int:
        """Forward points are quoted in units of 10^-scale (the FWD_SCALE Bloomberg reports)."""
        return 2 if self.quote == "JPY" else 4

    def spot_delta(self, tenor: str) -> bool:
        weeks, months = TENOR_SPEC[tenor]
        years = months / 12.0 if months else weeks / 365.0
        return years <= self.spot_until + 1e-9

    def info(self) -> Dict[str, Any]:
        return {"code": self.code, "group": self.group, "premium": self.premium, "spot_until": self.spot_until,
                "decimals": self.decimals, "added": self.added, "convention": convention_text(self)}


def _pair(code: str, group: str, decimals: int) -> Pair:
    base, quote = code[:3], code[3:]
    em = base in EM or quote in EM
    return Pair(code, group, premium=quote != "USD", spot_until=0.0 if em else 1.0, decimals=decimals)


PAIRS: Tuple[Pair, ...] = (
    _pair("USDTRY", "TRY", 4), _pair("EURTRY", "TRY", 4),
    _pair("EURUSD", "G10", 5), _pair("USDJPY", "G10", 3), _pair("GBPUSD", "G10", 5), _pair("USDCHF", "G10", 5),
    _pair("AUDUSD", "G10", 5), _pair("USDCAD", "G10", 5), _pair("NZDUSD", "G10", 5), _pair("USDNOK", "G10", 4),
    _pair("USDSEK", "G10", 4),
    _pair("EURJPY", "Çapraz", 3), _pair("EURGBP", "Çapraz", 5), _pair("EURCHF", "Çapraz", 5), _pair("AUDJPY", "Çapraz", 3),
    _pair("GBPJPY", "Çapraz", 3),
)


def convention_text(p: Pair) -> str:
    delta = "primli delta" if p.premium else "primsiz delta"
    if p.spot_until <= 0:
        kind = "her vadede forward delta"
    else:
        kind = "1Y'ye kadar spot, sonrası forward delta"
    return "%s · %s · ATM = DNS" % (delta, kind)


def vol_ticker(pair: str, kind: str, tenor: str, source: str = DEFAULT_SOURCE) -> str:
    return "%s%s%s %sCurncy" % (pair, CODE[kind], tenor, (source + " ") if source else "")


def points_ticker(pair: Pair, tenor: str) -> str:
    return "%s%s Curncy" % (pair.root, POINT_TENOR.get(tenor, tenor))


def spot_ticker(pair: Pair) -> str:
    return "%s Curncy" % pair.code


def series_id(ticker: str) -> str:
    return "%s|%s" % (ticker, FIELD)


# ---------------------------------------------------------------------------------------------- dates
def week_day_on_or_after(d: _dt.date) -> _dt.date:
    while d.weekday() >= 5:
        d += _dt.timedelta(days=1)
    return d


def add_week_days(d: _dt.date, n: int) -> _dt.date:
    while n > 0:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def delivery(spot: _dt.date, tenor: str) -> _dt.date:
    weeks, months = TENOR_SPEC[tenor]
    return week_day_on_or_after(spot + _dt.timedelta(days=weeks) if weeks else add_months(spot, months))


def _lin(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    """Linear between the nodes, flat outside (the workbook's pattern)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            return ys[i] + (x - xs[i]) * (ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i])
    return ys[-1]


def _as_date(v: Any) -> Optional[_dt.date]:
    if type(v) is float and 20000 < v < 80000:
        return serial_to_date(v)
    if isinstance(v, str):
        m = re.match(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$", v)
        if m:
            try:
                return _dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------------------------------- statistics
def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _stdev(xs: Sequence[float]) -> Optional[float]:
    """The sample standard deviation (Excel's STDEV)."""
    n = len(xs)
    if n < 2:
        return None
    m = _mean(xs)
    v = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(v) if v > 0 else None


def closes_axis(today: _dt.date) -> List[_dt.date]:
    """The week days of the workbook's BDH: TODAY()-366 .. TODAY()-1."""
    end = today - _dt.timedelta(days=1)
    d = today - _dt.timedelta(days=LOOKBACK_DAYS)
    out = []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += _dt.timedelta(days=1)
    return out


def stats(points: Dict[str, float], live: Optional[float], today: _dt.date, window: int = 250) -> Dict[str, Any]:
    """Level and changes the way the workbook's macro block works them out (see the module text).  ``points``: the
    closes by ISO day; ``live``: the value now (the last close when there is none)."""
    axis = closes_axis(today)
    vals = filled(points, axis)
    # the BDH column: from the first day that has a close (Fill=P only fills after the first value)
    series = [v for v in vals if v is not None]
    last = live if live is not None else (series[-1] if series else None)
    out: Dict[str, Any] = {"last": last, "live": live is not None, "n": len(series), "day": max(points) if points else None}
    for name, back in (("d1", 1), ("w1", 5), ("m1", 21)):
        out[name] = (last - series[-back]) if (last is not None and len(series) >= back) else None
    if last is None or len(series) < 2:
        out.update({"avg3m": None, "z3m": None, "z": None, "pct": None, "min": None, "max": None, "window": 0})
        return out
    s3 = series[-63:]
    out["avg3m"] = _mean(s3)
    sd3 = _stdev(s3)
    out["z3m"] = (last - out["avg3m"]) / sd3 if sd3 else None
    win = series[-window:] if window and window < len(series) else series
    sd = _stdev(win)
    out["z"] = (last - _mean(win)) / sd if sd else None
    out["pct"] = sum(1 for x in win if x <= last) / len(win)
    out["min"], out["max"] = min(win), max(win)
    out["window"] = len(win)
    return out


def skew_closes(rr: Dict[str, float], atm: Dict[str, float]) -> Dict[str, float]:
    """The skew's closes: the risk reversal over the ATM vol on every day both closed (an ATM vol of zero is none)."""
    return {d: v / atm[d] for d, v in rr.items() if d in atm and atm[d] > 0}


def realized(closes: Sequence[Tuple[str, float]], n: int = 21) -> List[Tuple[str, Optional[float]]]:
    """Rolling realized vol (vol points, annualized with √252) of the daily log returns over ``n`` returns."""
    out: List[Tuple[str, Optional[float]]] = []
    rets: List[float] = []
    prev = None
    for day, v in closes:
        if prev is not None and prev > 0 and v > 0:
            rets.append(math.log(v / prev))
        prev = v
        if len(rets) >= n:
            sd = _stdev(rets[-n:])
            out.append((day, sd * math.sqrt(252.0) * 100.0 if sd is not None else None))
        else:
            out.append((day, None))
    return out


def nice_levels(lo: float, hi: float, center: float, count: int = 11) -> List[float]:
    """Round price levels covering ``lo`` .. ``hi`` (about ``count`` of them), one of them close to ``center``."""
    if not (hi > lo > 0):
        return []
    raw = (hi - lo) / max(count - 1, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10)), key=lambda s: abs(math.log(s / raw)))     # the round step nearest
    first = math.floor(lo / step) * step
    out = []
    x = first
    while x <= hi + 1e-12 and len(out) < 60:
        if x > 0:
            out.append(round(x, 10))
        x += step
    return out


# ---------------------------------------------------------------------------------------------- the desk
class Fx(object):
    """Quotes, forwards, smiles and history of the FX pages (one per service)."""

    def __init__(self, service):
        self.svc = service
        self.store = service.store
        self._lock = threading.RLock()
        self._smiles: Dict[Tuple, Tuple[Any, Dict[str, Any]]] = {}     # fitted smiles by their quotes
        self._likelies: Dict[Tuple, Dict[str, Any]] = {}                # their peaks and narrowest ranges, over F
        self._starts: Dict[Tuple[str, str, str], Any] = {}               # last parameters: warm starts
        self._pair_locks: Dict[str, threading.Lock] = {}
        self._hist_wait: List[List[str]] = []
        # series -> when it was last fetched: kept in the database, so that a restart the same day does not ask
        # Bloomberg for every series again (the daily data limit)
        kept = service.store.get("fx.hist.asked")
        self._hist_asked: Dict[str, float] = {k: float(v) for k, v in kept.items()} if isinstance(kept, dict) else {}
        self._hist_empty: Dict[str, float] = {}
        self._hist_kick = threading.Event()
        self._hist_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.hist_state: Dict[str, Any] = {"phase": "idle", "pending": 0, "fetched": 0, "last": None, "error": ""}
        self._memo: Dict[Tuple, Any] = {}                                 # reads of one market generation
        self._memo_gen = -1

    def _memoized(self, key: Tuple, fn):
        """``fn()`` once per market generation (the workbook's curve, a pair's forwards)."""
        gen = self.svc.gen
        with self._lock:
            if gen != self._memo_gen:
                self._memo, self._memo_gen = {}, gen
            if key in self._memo:
                return self._memo[key]
        val = fn()
        with self._lock:
            if gen == self._memo_gen:
                self._memo[key] = val
        return val

    # ================================================================== settings, pairs, user tickers
    def settings(self) -> Dict[str, Any]:
        s = self.store.get("fx.settings") or {}
        return {"source": s.get("source") if isinstance(s.get("source"), str) else DEFAULT_SOURCE}

    def set_settings(self, user: str, source: Any) -> Dict[str, Any]:
        src = re.sub(r"\s+", "", str(source or "")).upper()
        if src and not re.match(r"^[A-Z0-9]{2,8}$", src):
            raise FxError("fiyat kaynağı anlaşılamadı: %r (örn. BGN, CMPN)" % source)
        self.store.put("fx.settings", {"source": src or DEFAULT_SOURCE, "by": user, "at": _now()})
        with self._lock:
            self._smiles.clear()
            self._likelies.clear()
        return self.settings()

    def source(self) -> str:
        return self.settings()["source"]

    def user_tickers(self) -> List[Dict[str, Any]]:
        items = self.store.get("fx.tickers") or []
        return [t for t in items if isinstance(t, dict) and t.get("text")]

    def add_ticker(self, user: str, text: Any, label: Any = "") -> Dict[str, Any]:
        raw = " ".join(str(text or "").split())
        if not raw:
            raise FxError("ticker ya da parite yazın (örn. USDZAR, VIX Index)")
        code = raw.replace("/", "").upper()
        items = self.user_tickers()
        if re.match(r"^[A-Z]{6}$", code):
            if code[:3] == code[3:]:
                raise FxError("parite anlaşılamadı: %s" % raw)
            if any(p.code == code for p in PAIRS) or any(t["kind"] == "pair" and t["text"] == code for t in items):
                raise FxError("%s zaten listede" % code)
            item = {"kind": "pair", "text": code}
        else:
            parts = raw.split()
            key = next((k for k in YELLOW_KEYS if parts[-1].lower() == k.lower()), None)
            if len(parts) < 2 or key is None:
                raise FxError("ticker'ın sonunda sarı tuş olmalı (%s): %s" % (", ".join(YELLOW_KEYS[:4]), raw))
            ticker = " ".join(parts[:-1]).upper() + " " + key
            if any(t["kind"] == "ticker" and t["text"] == ticker for t in items):
                raise FxError("%s zaten listede" % ticker)
            item = {"kind": "ticker", "text": ticker}
        item.update({"id": uuid.uuid4().hex[:10], "label": str(label or "").strip()[:60], "by": user, "at": _now()})
        items.append(item)
        self.store.put("fx.tickers", items)
        return {"items": self.user_tickers(), "added": item}

    def remove_ticker(self, user: str, item_id: str) -> Dict[str, Any]:
        items = self.user_tickers()
        left = [t for t in items if t.get("id") != item_id]
        if len(left) == len(items):
            raise FxError("listede yok")
        self.store.put("fx.tickers", left)
        return {"items": left}

    def pairs(self) -> List[Pair]:
        out = list(PAIRS)
        for t in self.user_tickers():
            if t["kind"] == "pair":
                p = _pair(t["text"], "Eklenen", 4)
                p.added = True
                out.append(p)
        return out

    def pair(self, code: Any) -> Pair:
        c = str(code or "").replace("/", "").upper()
        for p in self.pairs():
            if p.code == c:
                return p
        raise FxError("parite bilinmiyor: %s" % code)

    # ================================================================== market values
    def value(self, ticker: str, field: str = FIELD) -> Tuple[Optional[float], str]:
        """The live value of a ticker (asking for it the first time) and, when there is none, why."""
        try:
            v = self.svc.provider.get_bdp(bdp_key(ticker, field))
        except Exception as exc:  # noqa: BLE001 - a provider that fails is no value
            return None, str(exc)[:80]
        if type(v) is float:
            return v, ""
        if v == REQUESTING:
            return None, "bekleniyor"
        if v in (INVALID_SECURITY, INVALID_FIELD, NOT_APPLICABLE):
            return None, "Bloomberg'de yok"
        return None, "veri yok"

    def overrides(self, user: Optional[str]) -> Dict[str, Any]:
        if not user:
            return {}
        v = self.store.get("fx.ov." + user)
        return v if isinstance(v, dict) else {}

    def set_override(self, user: str, pair: str, tenor: str, kind: str, value: Any) -> Dict[str, Any]:
        p = self.pair(pair)
        if tenor not in TENORS or kind not in KINDS + ("FWD",):
            raise FxError("vade ya da kota anlaşılamadı")
        ov = self.overrides(user)
        cell = ov.setdefault(p.code, {}).setdefault(tenor, {})
        if value is None or value == "":
            cell.pop(kind, None)
        else:
            try:
                x = float(value)
            except (TypeError, ValueError):
                raise FxError("sayı anlaşılamadı: %r" % (value,))
            if not math.isfinite(x) or (kind == "ATM" and x <= 0) or (kind == "FWD" and x <= 0):
                raise FxError("geçersiz değer: %r" % (value,))
            cell[kind] = x
        if not cell:
            ov[p.code].pop(tenor, None)
        if not ov.get(p.code):
            ov.pop(p.code, None)
        self.store.put("fx.ov." + user, ov)
        return {"overrides": ov.get(p.code, {})}

    def clear_overrides(self, user: str, pair: str) -> Dict[str, Any]:
        p = self.pair(pair)
        ov = self.overrides(user)
        ov.pop(p.code, None)
        self.store.put("fx.ov." + user, ov)
        return {"overrides": {}}

    # ================================================================== forwards
    def today(self) -> _dt.date:
        return self.svc.history.today()

    def _try_book(self, user: Optional[str]) -> Optional[Dict[str, Any]]:
        """USDTRY from the TRY workbook: the spot of the Forward page's USDTRY table, the offshore curve's simple zero
        rate at each tenor of ``EK_FWD``'s rates-by-tenor table, the USD OIS of as many days."""
        return self._memoized(("book", user), lambda: self._read_try_book(user))

    def _read_try_book(self, user: Optional[str]) -> Optional[Dict[str, Any]]:
        from . import extras as ex
        book = self.svc.books.get("tto")
        if book is None or ex.FWD_SHEET not in book.model.sheet_index or "Forward" not in book.model.sheet_index:
            return None

        def read() -> Optional[Dict[str, Any]]:
            calc = self.svc._calc(user, book)
            si_k, si_f = book.model.sheet_index[ex.FWD_SHEET], book.model.sheet_index["Forward"]

            def v(si: int, addr: str) -> Any:
                from .xl.model import COLS, parse_a1
                return calc.get(si, *divmod(parse_a1(addr), COLS))

            spot = v(si_k, "F%d" % (ex.FR_USD + 1))
            if type(spot) is not float or spot <= 0:
                return None
            usd = []
            for r in range(7, 27):
                d, m = v(si_f, "U%d" % r), v(si_f, "X%d" % r)
                if type(d) is float and type(m) is float:
                    usd.append((d, m))
            usd.sort()
            out: Dict[str, Any] = {"spot": spot, "tenors": {}, "spot_date": None}
            first = ex.FR_TENOR + 3                      # the title, the header and the value-date row above
            for i, (label, _, _) in enumerate(ex.FR_TENORS):
                r = first + i
                day, g, rate = _as_date(v(si_k, "B%d" % r)), v(si_k, "C%d" % r), v(si_k, "D%d" % r)
                if label not in TENOR_SPEC or day is None or type(g) is not float or g <= 0:
                    continue
                if out["spot_date"] is None:
                    out["spot_date"] = day - _dt.timedelta(days=int(round(g)))
                row = {"date": day, "days": g, "try": rate if type(rate) is float else None,
                       "usd": _lin(g, [u[0] for u in usd], [u[1] for u in usd]) if usd else None}
                if row["try"] is not None and row["usd"] is not None:
                    row["fwd"] = spot * (1 + row["try"] / 100.0 * g / 360.0) / (1 + row["usd"] / 100.0 * g / 360.0)
                out["tenors"][label] = row
            return out

        try:
            return self.svc.et.call(read)
        except Exception:  # noqa: BLE001 - a workbook that does not fit: Bloomberg's points instead
            return None

    def _points_curve(self, pair: Pair, spot_date: _dt.date, tenors: Sequence[str] = TENORS) -> Dict[str, Any]:
        """Spot and forward of each tenor from Bloomberg (spot + points / 10^FWD_SCALE)."""
        spot, why = self.value(spot_ticker(pair))
        out: Dict[str, Any] = {"spot": spot, "spot_why": why, "tenors": {}, "spot_date": spot_date, "source": "bbg"}
        for t in tenors:
            tk = points_ticker(pair, t)
            pts, pwhy = self.value(tk)
            scale, _ = self.value(tk, "FWD_SCALE")
            sc = int(scale) if scale is not None and 0 <= scale <= 8 else pair.scale
            day = delivery(spot_date, t)
            row: Dict[str, Any] = {"date": day, "days": float((day - spot_date).days), "points": pts, "scale": sc,
                                   "ticker": tk, "why": pwhy}
            if spot is not None and pts is not None:
                row["fwd"] = spot + pts / 10.0 ** sc
            out["tenors"][t] = row
        return out

    def curve(self, user: Optional[str], pair: Pair) -> Dict[str, Any]:
        """Spot, spot date and, per tenor, delivery date, days and forward (+ how it was made)."""
        return self._memoized(("curve", user, pair.code), lambda: self._curve(user, pair))

    def _curve(self, user: Optional[str], pair: Pair) -> Dict[str, Any]:
        today = self.today()
        spot_date = add_week_days(today, 2)
        if pair.code == "USDTRY":
            book = self._try_book(user)
            if book and book.get("tenors"):
                book["source"] = "offshore"
                book["spot_date"] = book["spot_date"] or spot_date
                return book
            return self._points_curve(pair, spot_date)
        if pair.quote == "TRY" and pair.base != "USD":
            leg = self.curve(user, self.pair_or_build(pair.base + "USD"))
            usd = self.curve(user, self.pair("USDTRY"))
            out: Dict[str, Any] = {"spot": None, "tenors": {}, "spot_date": usd["spot_date"], "source": "cross",
                                   "legs": [pair.base + "USD", "USDTRY"]}
            if leg.get("spot") and usd.get("spot"):
                out["spot"] = leg["spot"] * usd["spot"]
            for t in TENORS:
                a, b = leg["tenors"].get(t) or {}, usd["tenors"].get(t) or {}
                row = {"date": b.get("date") or a.get("date"), "days": b.get("days") or a.get("days")}
                if a.get("fwd") and b.get("fwd"):
                    row["fwd"] = a["fwd"] * b["fwd"]
                out["tenors"][t] = row
            return out
        return self._points_curve(pair, spot_date)

    def spot(self, user: Optional[str], pair: Pair) -> Tuple[Optional[float], str]:
        """The pair's spot as its page prices it: USDTRY the Forward page's (the TRY workbook's), a TRY cross the
        product of its USD legs, any other pair Bloomberg's - without asking for forward points."""
        if pair.code == "USDTRY":
            book = self._try_book(user)
            if book:
                return book["spot"], ""
        elif pair.quote == "TRY" and pair.base != "USD":
            a, why = self.spot(user, self.pair_or_build(pair.base + "USD"))
            b, why2 = self.spot(user, self.pair("USDTRY"))
            return (a * b if a and b else None), (why or why2)
        return self.value(spot_ticker(pair))

    def pair_or_build(self, code: str) -> Pair:
        try:
            return self.pair(code)
        except FxError:
            return _pair(code, "", 5)

    def _base_df(self, user: Optional[str], pair: Pair, tenor: str, row: Dict[str, Any], spot: Optional[float]) -> Tuple[float, str]:
        """The base currency's discount factor over the forward's days, for a spot delta: the USD OIS of the TRY
        workbook for a USD base, else the base's own USD pair's forward over spot times that (``F/S·DF_USD``).
        ``(1, reason)`` when it cannot be had: a forward delta then."""
        if not pair.spot_delta(tenor):
            return 1.0, ""
        g = row.get("days")
        usd = self._usd_rates(user)
        if not g or not usd:
            return 1.0, "faiz yok: forward delta"
        df_usd = 1.0 / (1.0 + _lin(g, usd[0], usd[1]) / 100.0 * g / 360.0)
        if pair.base == "USD":
            return df_usd, ""
        leg = pair if pair.quote == "USD" else self.pair_or_build(pair.base + "USD")
        c = self.curve(user, leg) if leg is not pair else None
        s = spot if leg is pair else (c or {}).get("spot")
        f = row.get("fwd") if leg is pair else ((c or {}).get("tenors", {}).get(tenor) or {}).get("fwd")
        if not s or not f:
            return 1.0, "faiz yok: forward delta"
        return f / s * df_usd, ""

    def _usd_rates(self, user: Optional[str]) -> Optional[Tuple[List[float], List[float]]]:
        book = self._try_book(user)
        if not book:
            return None
        rows = sorted((r["days"], r["usd"]) for r in book["tenors"].values() if r.get("usd") is not None)
        if not rows:
            return None
        return [r[0] for r in rows], [r[1] for r in rows]

    # ================================================================== a pair's surface
    def quotes(self, user: Optional[str], pair: Pair) -> Dict[str, Any]:
        """Every tenor's quotes (vol points), forward and dates - Bloomberg's, or the user's own where typed."""
        src = self.source()
        ov = self.overrides(user).get(pair.code, {})
        cur = self.curve(user, pair)
        rows = []
        for t in TENORS:
            c = cur["tenors"].get(t) or {}
            own = ov.get(t, {})
            row: Dict[str, Any] = {"tenor": t, "date": c.get("date").isoformat() if c.get("date") else None,
                                   "days": c.get("days"), "fwd": c.get("fwd"), "own": sorted(own)}
            if "FWD" in own:
                row["fwd"] = own["FWD"]
            if c.get("points") is not None:
                row["points"] = c["points"]
            for k in KINDS:
                tk = vol_ticker(pair.code, k, t, src)
                v, why = self.value(tk)
                row[k] = own.get(k, v)
                row[k + "_bbg"] = v
                row[k + "_why"] = "" if k in own else why
                row[k + "_ticker"] = tk
            rows.append(row)
        return {"pair": pair.code, "spot": cur.get("spot"), "spot_date": cur["spot_date"].isoformat() if cur.get("spot_date") else None,
                "forward_source": cur.get("source"), "legs": cur.get("legs"), "rows": rows, "source": src}

    def _smile(self, pair: Pair, tenor: str, model: str, q: fv.Quotes) -> Tuple[Any, Dict[str, Any]]:
        """The fitted smile of these quotes.  The forward is not part of the key: every condition of the fit (the
        deltas, the delta-neutral straddle, the market strangle's strikes) depends on strikes only through ``K/F``,
        so when only the forward moved - the spot ticked - the same smile holds in moneyness, exactly: it is moved
        to the new forward instead of being fitted again."""
        key = _smile_key(pair, tenor, model, q)
        with self._lock:
            hit = self._smiles.get(key)
            start = self._starts.get((pair.code, tenor, model))
        if hit is not None:
            return _moved(hit[0], hit[1], q.F)
        smile, info = fv.build_smile(q, model, start)
        with self._lock:
            if len(self._smiles) > 600:
                self._smiles.clear()
            self._smiles[key] = (smile, info)
            if info.get("start") is not None:
                self._starts[(pair.code, tenor, model)] = info["start"]
        return smile, info

    def _likely(self, pair: Pair, tenor: str, model: str, q: fv.Quotes, dist: Any) -> Dict[str, Any]:
        """The peak of a tenor's law and its narrowest ranges (``fxvol.likely``), kept with the smile's quotes: the
        shape is the same in K/F whatever the forward, so they are kept over the forward and a spot that ticked only
        scales them."""
        key = _smile_key(pair, tenor, model, q)
        with self._lock:
            unit = self._likelies.get(key)
        if unit is None:
            raw = fv.likely(dist)
            unit = {"mode": raw["mode"] / dist.F, "hdi": {p: [a / dist.F, b / dist.F] for p, (a, b) in raw["hdi"].items()}}
            with self._lock:
                if len(self._likelies) > 600:
                    self._likelies.clear()
                self._likelies[key] = unit
        return {"mode": unit["mode"] * dist.F, "hdi": {p: [a * dist.F, b * dist.F] for p, (a, b) in unit["hdi"].items()}}

    def surface(self, user: Optional[str], code: str, model: str = "svi", levels: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
        """The FX page: quotes, smile, distribution and the cloud of every tenor; with ``levels``, the probability
        matrix (automatic round levels when none are given)."""
        pair = self.pair(code)
        model = model if model in fv.MODELS else "svi"
        lock = self._pair_locks.setdefault(pair.code, threading.Lock())
        with lock:
            data = self.quotes(user, pair)
            spot = data["spot"]
            tenors = []
            for row in data["rows"]:
                tenors.append(self._tenor(user, pair, model, row, spot))
        out = dict(data)
        out["rows"] = tenors
        out["model"] = model
        out["pair_info"] = pair.info()
        out["quantiles"] = list(fv.QUANTILES)
        out["today"] = self.today().isoformat()
        out["levels"], out["matrix"] = self._matrix(tenors, spot, levels)
        # the spot's recent closes, for the chart's past
        today = self.today()
        hist = self.store.hist_many([series_id(spot_ticker(pair))], (today - _dt.timedelta(days=200)).isoformat(),
                                    (today - _dt.timedelta(days=1)).isoformat()).get(series_id(spot_ticker(pair))) or {}
        out["spot_history"] = sorted(hist.items())
        return out

    def _tenor(self, user: Optional[str], pair: Pair, model: str, row: Dict[str, Any], spot: Optional[float]) -> Dict[str, Any]:
        t = row["tenor"]
        out = dict(row)
        F, days, atm = row.get("fwd"), row.get("days"), row.get("ATM")
        if not F or not days or not atm:
            out["error"] = "forward yok" if not F else ("ATM vol yok" if not atm else "vade günü yok")
            return out
        df, df_note = self._base_df(user, pair, t, row, spot)
        T = days / 365.0
        pct = lambda k: row.get(k) / 100.0 if row.get(k) is not None else None   # noqa: E731
        q = fv.Quotes(F, T, atm / 100.0, pct("RR25"), pct("BF25"), pct("RR10"), pct("BF10"), premium=pair.premium, df=df)
        out.update({"T": T, "df": df, "delta": ("spot" if df != 1.0 else "forward"), "df_note": df_note,
                    "move_1sd": F * atm / 100.0 * math.sqrt(T)})   # ± one sigma from the ATM vol alone, around the same forward
        try:
            smile, info = self._smile(pair, t, model, q)
        except fv.MATH_ERRORS as exc:
            out["error"] = "smile kurulamadı: %s" % exc
            return out
        dist = fv.Distribution(smile)
        chk = dist.check()
        qs = fv.quantiles(dist)
        out["fit"] = {k: (v * 100.0 if v is not None else None) for k, v in info["fit"].items()}     # vol points
        out["points_smile"] = {k: ({"strike": v[0], "vol": v[1] * 100.0} if v else None) for k, v in info["points"].items()}
        out["model"] = info["model"]
        out["note"] = info.get("note") or ""
        out["curve"] = _curve_points(smile, dist, qs, info["points"])
        out["check"] = {"mass": chk["mass"], "mean_error": chk["mean_error"], "arbitrage": chk["arbitrage"]}
        out["q"] = {"%g" % p: v for p, v in qs.items()}
        out["params"] = info.get("svi") or ({"alpha": info["alpha"], "rho": info["rho"], "nu": info["nu"]} if "alpha" in info else None)
        if qs.get(0.84) is not None and qs.get(0.16) is not None:
            out["up_1s"] = qs[0.84] - F                       # one standard deviation up and down, the skew included
            out["down_1s"] = F - qs[0.16]
        try:                                                  # the likeliest level and the narrowest ranges
            out["likely"] = self._likely(pair, t, model, q, dist)
        except fv.MATH_ERRORS:
            out["likely"] = None
        out["_dist"] = dist
        return out

    def _matrix(self, tenors: List[Dict[str, Any]], spot: Optional[float], levels: Optional[Sequence[Any]]) -> Tuple[List[float], List[Dict[str, Any]]]:
        good = [t for t in tenors if t.get("_dist") is not None]
        lv: List[float] = []
        for x in levels or []:
            try:
                f = float(x)
            except (TypeError, ValueError):
                continue
            if f > 0 and math.isfinite(f):
                lv.append(f)
        lv = sorted(set(lv))
        if not lv and good:
            ref = next((t for t in good if t["tenor"] == "1Y"), good[-1])
            lo, hi = ref["q"].get("0.05"), ref["q"].get("0.95")
            if lo and hi:
                lv = nice_levels(lo, hi, spot or ref["fwd"])
        rows = []
        for t in tenors:
            d = t.pop("_dist", None)
            if d is None:
                rows.append({"tenor": t["tenor"], "above": None})
                continue
            above = []
            for L in lv:
                try:
                    above.append(min(1.0, max(0.0, d.above(L))))
                except fv.MATH_ERRORS:
                    above.append(None)
            rows.append({"tenor": t["tenor"], "above": above})
        return lv, rows

    # ================================================================== the board (Spot / FX page)
    def board(self, user: Optional[str]) -> Dict[str, Any]:
        src = self.source()
        today = self.today()
        rows = []
        spot_ids = [series_id(spot_ticker(p)) for p in self.pairs()]
        closes = self.store.hist_many(spot_ids, (today - _dt.timedelta(days=12)).isoformat(), (today - _dt.timedelta(days=1)).isoformat())
        for p in self.pairs():
            spot, why = self.spot(user, p)
            prev = closes.get(series_id(spot_ticker(p))) or {}
            last_close = prev[max(prev)] if prev else None
            row: Dict[str, Any] = {"pair": p.code, "group": p.group, "decimals": p.decimals, "spot": spot, "spot_why": why,
                                   "chg": (spot / last_close - 1.0) * 100.0 if spot and last_close else None}
            for kind, tenor in (("ATM", "1W"), ("ATM", "1M"), ("ATM", "3M"), ("ATM", "1Y"), ("RR25", "1M"), ("RR25", "3M"),
                                ("BF25", "1M"), ("RR10", "1M")):
                row["%s_%s" % (kind, tenor)] = self.value(vol_ticker(p.code, kind, tenor, src))[0]
            atm = row.get("ATM_1M")
            if spot and atm:
                row["breakeven"] = spot * atm / 100.0 / math.sqrt(252.0)
                row.update(self._one_month(user, p, spot) or {})
            rows.append(row)
        return {"rows": rows, "source": src, "today": today.isoformat()}

    def _one_month(self, user: Optional[str], pair: Pair, spot: float) -> Optional[Dict[str, float]]:
        """The 1M move one standard deviation either way from the ATM vol alone (forward × ATM × √T) and up and down
        with the skew included (the 84th and 16th percentiles of the spot one month on, around the forward): the
        forward and the smile as the Spot / FX page builds them."""
        src = self.source()
        vols = {k: self.value(vol_ticker(pair.code, k, "1M", src))[0] for k in KINDS}
        if not vols["ATM"]:
            return None
        if pair.code == "USDTRY" or (pair.quote == "TRY" and pair.base != "USD"):
            row = dict(self.curve(user, pair)["tenors"].get("1M") or {})          # the offshore curve / the USD legs
        else:                                                                    # Bloomberg's 1M points only
            row = self._points_curve(pair, add_week_days(self.today(), 2), ("1M",))["tenors"]["1M"]
        F, days = row.get("fwd"), row.get("days")
        if not F or not days:
            return None
        out = {"fwd_1m": F, "move_1m": F * vols["ATM"] / 100.0 * math.sqrt(days / 365.0)}   # the surface's 1M move_1sd
        df, _ = self._base_df(user, pair, "1M", row, spot)
        q = fv.Quotes(F, days / 365.0, vols["ATM"] / 100.0, *[(vols[k] / 100.0 if vols[k] is not None else None)
                                                             for k in ("RR25", "BF25", "RR10", "BF10")], premium=pair.premium, df=df)
        try:
            smile, _ = self._smile(pair, "1M", "svi", q)
            dist = fv.Distribution(smile)
            out.update({"up_1m": dist.quantile(0.84) - F, "down_1m": F - dist.quantile(0.16)})
        except fv.MATH_ERRORS:
            pass                                                                 # no smile: the ATM's move alone
        return out

    # ================================================================== the vol monitor
    def _series(self, tickers: Sequence[str], today: _dt.date) -> Dict[str, Dict[str, float]]:
        start = (today - _dt.timedelta(days=LOOKBACK_DAYS + 7)).isoformat()
        return self.store.hist_many([series_id(t) for t in tickers], start, (today - _dt.timedelta(days=1)).isoformat())

    def monitor(self, user: Optional[str], window: Any = 250) -> Dict[str, Any]:
        """Every pair's core vols: live level, changes, where they stand in the window; the desk's own tickers."""
        try:
            win = int(window)
        except (TypeError, ValueError):
            win = 250
        win = win if win in WINDOWS else 250
        src = self.source()
        today = self.today()
        pairs = self.pairs()
        tickers: List[str] = []
        layout: List[Tuple[Pair, str, str, str]] = []
        for p in pairs:
            for kind, tenor in CORE:
                tk = vol_ticker(p.code, kind, tenor, src)
                layout.append((p, kind, tenor, tk))
                tickers.append(tk)
            tickers.append(spot_ticker(p))
        own = [t for t in self.user_tickers() if t["kind"] == "ticker"]
        tickers += [t["text"] for t in own]
        self.want_history(tickers)
        data = self._series(tickers, today)
        cells: Dict[str, Dict[str, Any]] = {}
        for p, kind, tenor, tk in layout:
            live, why = self.value(tk)
            st = stats(data.get(series_id(tk)) or {}, live, today, win)
            st.update({"ticker": tk, "why": why})
            cells["%s|%s|%s" % (p.code, kind, tenor)] = st
        # the skews: the risk reversal over the ATM vol of the same tenor, its own closes from the two series
        for p in pairs:
            for name, rr_kind, tenor in SKEWS:
                rr_tk, atm_tk = vol_ticker(p.code, rr_kind, tenor, src), vol_ticker(p.code, "ATM", tenor, src)
                rr_live, atm_live = self.value(rr_tk)[0], self.value(atm_tk)[0]
                live = rr_live / atm_live if rr_live is not None and atm_live else None
                st = stats(skew_closes(data.get(series_id(rr_tk)) or {}, data.get(series_id(atm_tk)) or {}), live, today, win)
                st.update({"ticker": None, "of": [rr_tk, atm_tk], "why": "" if live is not None else "RR ya da ATM yok"})
                cells["%s|%s|%s" % (p.code, name, tenor)] = st
        rows = []
        for p in pairs:
            spot_tk = spot_ticker(p)
            closes = sorted((data.get(series_id(spot_tk)) or {}).items())
            rv = realized(closes)
            iv = cells.get("%s|ATM|1M" % p.code, {}).get("last")
            spot_now, _ = self.spot(user, p)
            atm_closes = sorted((data.get(series_id(vol_ticker(p.code, "ATM", "1M", src))) or {}).items())
            rows.append({"pair": p.code, "group": p.group, "decimals": p.decimals, "spot": spot_now, "spot_ticker": spot_tk,
                         "rv1m": rv[-1][1] if rv else None, "iv1m": iv,
                         "spark": [v for _, v in closes[-260:]][::5],               # the spot, a point a week
                         "spark_atm": [v for _, v in atm_closes[-260:]][::5]})      # ATM 1M, a point a week
        extra = []
        for t in own:
            live, why = self.value(t["text"])
            st = stats(data.get(series_id(t["text"])) or {}, live, today, win)
            st.update({"id": t["id"], "ticker": t["text"], "label": t.get("label") or t["text"], "why": why,
                       "by": t.get("by"), "spark": [v for _, v in sorted((data.get(series_id(t["text"])) or {}).items())[-260:]][::5]})
            extra.append(st)
        return {"pairs": [p.info() for p in pairs], "rows": rows, "cells": cells, "core": [list(c) for c in CORE],
                "skews": [list(s) for s in SKEWS], "skew_labels": SKEW_LABEL,
                "tenors": list(TENORS), "kinds": list(KINDS), "window": win, "windows": list(WINDOWS), "own": extra,
                "own_pairs": [t for t in self.user_tickers() if t["kind"] == "pair"], "source": src, "today": today.isoformat(),
                "history": self.history_status(), "z_flag": Z_FLAG}

    def pair_detail(self, user: Optional[str], code: str, tenor: str = "1M", model: str = "svi") -> Dict[str, Any]:
        """One pair in depth: the term structure and the skew now, a week and a month ago; the smile of a tenor then
        and now; the time series of its main vols and of the spot, and its realized vol."""
        pair = self.pair(code)
        tenor = tenor if tenor in TENORS else "1M"
        src = self.source()
        today = self.today()
        tickers = [vol_ticker(pair.code, k, t, src) for k in KINDS for t in TENORS] + [spot_ticker(pair)]
        self.want_history(tickers)
        data = self._series(tickers, today)
        axis = closes_axis(today)

        def back(tk: str, n: int) -> Optional[float]:
            vals = [v for v in filled(data.get(series_id(tk)) or {}, axis) if v is not None]
            return vals[-n] if len(vals) >= n else None

        structure: Dict[str, Any] = {}
        waiting = 0                          # quotes asked for the first time (the whole surface), still on their way
        now_why: Dict[str, str] = {}
        for k in KINDS:
            structure[k] = {"now": [], "w1": [], "m1": []}
            for t in TENORS:
                tk = vol_ticker(pair.code, k, t, src)
                v, why = self.value(tk)
                structure[k]["now"].append(v)
                waiting += why == "bekleniyor"
                if t == tenor:
                    now_why[k] = why
                structure[k]["w1"].append(back(tk, 5))
                structure[k]["m1"].append(back(tk, 21))
        # the smile of the tenor: now (as the FX page fits it), a week and a month ago from those days' closes.  Its
        # vols at its own delta strikes do not depend on the forward (every condition of the fit is in K/F, the deltas
        # are forward deltas here): a forward not there yet does not hold it back - the spot, or 1, stands in for it.
        smiles: Dict[str, Any] = {}
        smile_why = ""
        cur = self.curve(user, pair)
        row = cur["tenors"].get(tenor) or {}
        start = add_week_days(today, 2)
        days = row.get("days") or float((delivery(start, tenor) - start).days)
        F = row.get("fwd") or cur.get("spot") or 1.0
        for name, idx in (("now", None), ("w1", 5), ("m1", 21)):
            vals = {k: (structure[k]["now"] if idx is None else structure[k][name])[TENORS.index(tenor)] for k in KINDS}
            # a smile needs its skew: without the risk reversal and the fly of that day there is none to draw
            missing = [k for k in ("ATM", "RR25", "BF25") if vals[k] is None]
            if missing:
                smiles[name] = None
                if name == "now":
                    smile_why = " · ".join("%s %s %s" % (KIND_LABEL[k], tenor, "bekleniyor" if now_why.get(k) == "bekleniyor" else "yok")
                                           for k in missing)
                continue
            q = fv.Quotes(F, days / 365.0, vals["ATM"] / 100.0, *[(vals[k] / 100.0 if vals[k] is not None else None)
                                                                 for k in ("RR25", "BF25", "RR10", "BF10")],
                          premium=pair.premium, df=1.0)
            try:
                smile, info = self._smile(pair, tenor + ":" + name, model, q)
            except fv.MATH_ERRORS:
                smiles[name] = None
                if name == "now":
                    smile_why = "smile kurulamadı"
                continue
            pts = info["points"]
            smiles[name] = {k: (pts[k][1] * 100.0 if pts.get(k) else None) for k, _, _ in fv.PILLARS}
        series: Dict[str, Any] = {}
        for k, t in (("ATM", "1M"), ("ATM", "3M"), ("ATM", "1Y"), ("RR25", "1M"), ("RR25", "3M"), ("RR25", "1Y"), ("BF25", "1M"), ("RR10", "1M"),
                     ("BF10", "1M")):
            tk = vol_ticker(pair.code, k, t, src)
            series["%s %s" % (KIND_LABEL[k], t)] = sorted((data.get(series_id(tk)) or {}).items())
        spot_closes = sorted((data.get(series_id(spot_ticker(pair))) or {}).items())
        return {"pair": pair.code, "pair_info": pair.info(), "tenor": tenor, "tenors": list(TENORS), "kinds": list(KINDS),
                "structure": structure, "smiles": smiles, "smile_why": smile_why, "waiting": waiting, "series": series,
                "spot": spot_closes, "realized": realized(spot_closes), "history": self.history_status(), "today": today.isoformat()}

    def series(self, ticker: str = "", window: Any = 250, pair: Any = None, kind: Any = None, tenor: Any = None) -> Dict[str, Any]:
        """The daily closes of what a row or a cell shows, with the value now and where it stands: a ticker, or a pair's
        quote by kind and tenor - a skew (``SKEW25`` / ``SKEW10``) from the closes of its risk reversal and ATM vol."""
        try:
            win = int(window)
        except (TypeError, ValueError):
            win = 250
        today = self.today()
        if pair:
            p = self.pair(pair)
            k = str(kind or "").upper()
            t = str(tenor or "").upper()
            if t not in TENORS or (k not in KINDS and k not in SKEW_OF):
                raise FxError("vade ya da kota anlaşılamadı: %s %s" % (kind, tenor))
            src = self.source()
            if k in SKEW_OF:
                rr_tk, atm_tk = vol_ticker(p.code, SKEW_OF[k], t, src), vol_ticker(p.code, "ATM", t, src)
                self.want_history([rr_tk, atm_tk])
                data = self._series([rr_tk, atm_tk], today)
                pts = skew_closes(data.get(series_id(rr_tk)) or {}, data.get(series_id(atm_tk)) or {})
                rr_live, atm_live = self.value(rr_tk)[0], self.value(atm_tk)[0]
                live = rr_live / atm_live if rr_live is not None and atm_live else None
                return {"ticker": None, "of": [rr_tk, atm_tk], "label": "%s %s %s" % (p.code, SKEW_LABEL[k], t), "unit": "ratio",
                        "points": sorted(pts.items()), "live": live, "stats": stats(pts, live, today, win),
                        "from": closes_axis(today)[0].isoformat(), "today": today.isoformat(),
                        "why": "" if live is not None else "RR ya da ATM yok"}
            ticker = vol_ticker(p.code, k, t, src)
            label = "%s %s %s" % (p.code, KIND_LABEL[k], t)
        else:
            ticker = " ".join(str(ticker or "").split())
            if not ticker:
                raise FxError("ticker yok")
            label = ticker
        self.want_history([ticker])
        pts = self._series([ticker], today).get(series_id(ticker)) or {}
        live, why = self.value(ticker)
        return {"ticker": ticker, "label": label, "unit": "vol" if pair else "", "points": sorted(pts.items()), "live": live,
                "stats": stats(pts, live, today, win), "from": closes_axis(today)[0].isoformat(), "today": today.isoformat(), "why": why}

    def tenor_history(self, user: Optional[str], code: str, tenor: str) -> Dict[str, Any]:
        """One tenor of a pair through time: the closes of its five quotes and of its 25-delta skew (the Spot / FX page's
        surface, a row clicked).  The tenor's quotes are fetched once when first asked (a year back, then the last days)."""
        pair = self.pair(code)
        t = str(tenor or "").upper()
        if t not in TENORS:
            raise FxError("vade anlaşılamadı: %s" % tenor)
        src = self.source()
        today = self.today()
        tickers = {k: vol_ticker(pair.code, k, t, src) for k in KINDS}
        self.want_history(list(tickers.values()))
        data = self._series(list(tickers.values()), today)
        series = {k: sorted((data.get(series_id(tk)) or {}).items()) for k, tk in tickers.items()}
        skew = skew_closes(data.get(series_id(tickers["RR25"])) or {}, data.get(series_id(tickers["ATM"])) or {})
        live = {k: self.value(tk)[0] for k, tk in tickers.items()}
        return {"pair": pair.code, "tenor": t, "series": series, "skew": sorted(skew.items()), "labels": KIND_LABEL, "live": live,
                "skew_live": live["RR25"] / live["ATM"] if live["RR25"] is not None and live["ATM"] else None,
                "from": closes_axis(today)[0].isoformat(), "history": self.history_status(), "today": today.isoformat()}

    # ================================================================== history
    def history_status(self) -> Dict[str, Any]:
        st = dict(self.hist_state)
        st["auto"] = bool(getattr(self.svc.settings, "history", True))
        return st

    def want_history(self, tickers: Sequence[str], force: bool = False) -> None:
        """Have the daily closes of these tickers fetched in the background (when automatic fetching is on, or
        ``force``): a year back the first time, the last ten days after that, once a day at most."""
        if self.svc.mode != "live" and not force:
            return
        if not force and not getattr(self.svc.settings, "history", True):
            return
        now = time.time()
        with self._lock:
            todo = []
            for t in tickers:
                sid = series_id(t)
                if not force and now - self._hist_asked.get(sid, 0.0) < 20 * 3600.0:
                    continue
                if not force and now - self._hist_empty.get(sid, 0.0) < EMPTY_RETRY:
                    continue
                todo.append(t)
                self._hist_asked[sid] = now
            if not todo:
                return
            self.store.put("fx.hist.asked", {k: v for k, v in self._hist_asked.items() if now - v < 24 * 3600.0})
            self._hist_wait.append(todo)
            self.hist_state["pending"] = sum(len(x) for x in self._hist_wait)
            if self._hist_thread is None:
                self._hist_thread = threading.Thread(target=self._hist_loop, name="tto-fx-history", daemon=True)
                self._hist_thread.start()
        self._hist_kick.set()

    def sync_history(self, user: str, pair: Optional[str] = None) -> Dict[str, Any]:
        """"Tarihçeyi güncelle": the core set of every pair (and the full set of ``pair``), now."""
        src = self.source()
        tickers = [vol_ticker(p.code, k, t, src) for p in self.pairs() for k, t in CORE] + [spot_ticker(p) for p in self.pairs()]
        tickers += [t["text"] for t in self.user_tickers() if t["kind"] == "ticker"]
        if pair:
            p = self.pair(pair)
            tickers += [vol_ticker(p.code, k, t, src) for k in KINDS for t in TENORS]
        self.want_history(sorted(set(tickers)), force=True)
        return self.history_status()

    def _hist_loop(self) -> None:
        while not self._stop.is_set():
            self._hist_kick.wait(30.0)
            self._hist_kick.clear()
            while not self._stop.is_set():
                with self._lock:
                    if not self._hist_wait:
                        break
                    batch = self._hist_wait.pop(0)
                    self.hist_state["pending"] = sum(len(x) for x in self._hist_wait) + len(batch)
                try:
                    self._fetch(batch)
                except Exception as exc:  # noqa: BLE001 - the loop must survive anything
                    self.hist_state["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
                with self._lock:
                    self.hist_state["pending"] = sum(len(x) for x in self._hist_wait)

    def _fetch(self, tickers: Sequence[str]) -> int:
        today = self.today()
        bounds = self.store.hist_bounds()
        end = (today - _dt.timedelta(days=1)).strftime("%Y%m%d")
        first = today - _dt.timedelta(days=LOOKBACK_DAYS)
        full, tail = [], []
        for t in tickers:
            b = bounds.get(series_id(t))
            if b is None or b[0] > (first + _dt.timedelta(days=20)).isoformat() or b[1] < (today - _dt.timedelta(days=10)).isoformat():
                full.append(t)
            else:
                tail.append(t)
        self.hist_state["phase"] = "fetch"
        got = 0
        prov = self.svc.provider
        for group, start in ((full, first), (tail, today - _dt.timedelta(days=10))):
            for i in range(0, len(group), 50):
                if self._stop.is_set():
                    break
                chunk = group[i:i + 50]
                rows = prov.history([(t, FIELD) for t in chunk], start.strftime("%Y%m%d"), end, timeout=120.0)
                now = time.time()
                for t in chunk:
                    r = rows.get((t, FIELD))
                    if r:
                        got += self.store.hist_upsert(series_id(t), [(d, v) for d, v in r if d < today.isoformat()])
                    elif series_id(t) not in bounds:
                        with self._lock:
                            self._hist_empty[series_id(t)] = now
        self.hist_state.update({"phase": "idle", "fetched": self.hist_state.get("fetched", 0) + got,
                                "last": _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")})
        if got:
            self.svc.bump()
        return got

    def stop(self) -> None:
        self._stop.set()
        self._hist_kick.set()


# ---------------------------------------------------------------------------------------------- the terminal check
def check_fx(pair: str = "USDTRY", source: str = DEFAULT_SOURCE, host: str = "localhost", port: int = 8194,
             wait: float = 40.0, blpapi_module=None, out=print) -> int:
    """``python -m tto check-fx USDTRY``: ask the terminal once for every ticker of a pair's surface - the five vol
    quotes of every tenor, the forward points and their scale, the spot (one reference request, about seventy items)
    - and print which of them Bloomberg knows.  0: every ATM vol and the spot came back, 2: some did not, 1: no
    connection."""
    from .marketdata.bloomberg import BloombergProvider
    code = str(pair or "").replace("/", "").upper()
    if not re.match(r"^[A-Z]{6}$", code):
        out("Parite anlaşılamadı: %r (örn. USDTRY, EURUSD)" % pair)
        return 1
    p = next((x for x in PAIRS if x.code == code), None) or _pair(code, "", 4)
    prov = BloombergProvider(host, port, stream=False, blpapi_module=blpapi_module)
    try:
        prov.start()
    except ImportError as exc:
        out("blpapi yüklü değil (%s)" % exc)
        return 1
    except Exception as exc:  # noqa: BLE001
        out("Bağlantı kurulamadı: %s" % exc)
        return 1
    try:
        keys: Dict[Tuple[str, str], Tuple] = {}
        for t in TENORS:
            for k in KINDS:
                keys[(t, k)] = bdp_key(vol_ticker(code, k, t, source), FIELD)
            keys[(t, "FWD")] = bdp_key(points_ticker(p, t), FIELD)
            keys[(t, "SCALE")] = bdp_key(points_ticker(p, t), "FWD_SCALE")
        keys[("", "SPOT")] = bdp_key(spot_ticker(p), FIELD)
        for k in keys.values():
            prov._lookup(k, 0.0)
        t0 = time.time()
        while time.time() - t0 < wait and prov.busy():
            time.sleep(0.2)
        time.sleep(0.5)

        def shown(key: Tuple) -> str:
            v = prov._values.get(key, REQUESTING)
            if type(v) is float:
                return "%.4f" % v
            return {INVALID_SECURITY: "yok", INVALID_FIELD: "alan yok", NOT_APPLICABLE: "-", REQUESTING: "?"}.get(v, "boş")

        out("%s · vol kaynağı %s · ticker örnekleri: %s, %s, %s" % (code, source or "(yok)", vol_ticker(code, "ATM", "1M", source),
                                                                 vol_ticker(code, "RR25", "3M", source), points_ticker(p, "1Y")))
        out("%-5s" % "Vade" + "".join("%11s" % k for k in KINDS + ("FWD puan", "FWD_SCALE")))
        missing = 0
        for t in TENORS:
            cells = [shown(keys[(t, k)]) for k in KINDS + ("FWD", "SCALE")]
            if cells[0] in ("yok", "boş", "?"):
                missing += 1
            out("%-5s" % t + "".join("%11s" % c for c in cells))
        spot = shown(keys[("", "SPOT")])
        out("Spot %s: %s" % (spot_ticker(p), spot))
        st = prov.status()
        out("İstek: %d · veri isteği sayacı: %d%s" % (st["requests"], st["hits_today"], (" · " + st["error"]) if st["error"] else ""))
        return 0 if not missing and spot not in ("yok", "boş", "?") else 2
    finally:
        prov.stop()


def _smile_key(pair: Pair, tenor: str, model: str, q: fv.Quotes) -> Tuple:
    """What a fitted smile is kept by: its quotes, not its forward (see ``Fx._smile``)."""
    return (pair.code, tenor, model, round(q.T, 10), round(q.atm, 8), q.rr25 and round(q.rr25, 8),
            q.bf25 and round(q.bf25, 8), q.rr10 and round(q.rr10, 8), q.bf10 and round(q.bf10, 8), q.premium, round(q.df, 10))


def _moved(smile: Any, info: Dict[str, Any], F: float) -> Tuple[Any, Dict[str, Any]]:
    """A fitted smile carried to another forward, its shape in moneyness unchanged (strikes scale with F)."""
    if abs(F / smile.F - 1.0) < 1e-14:
        return smile, info
    r = F / smile.F
    if isinstance(smile, fv.SviSmile):
        moved: Any = fv.SviSmile(F, smile.T, smile.a, smile.b, smile.rho, smile.m, smile.s)
    elif isinstance(smile, fv.SabrSmile):
        moved = fv.SabrSmile(F, smile.T, smile.alpha, smile.rho, smile.nu)
    elif isinstance(smile, fv.VannaVolgaSmile):
        moved = fv.VannaVolgaSmile(F, smile.T, [smile.k1 * r, smile.k2 * r, smile.k3 * r], [smile.v1, smile.v2, smile.v3])
    else:
        moved = fv.FlatSmile(F, smile.T, smile.vol(smile.F))
    out = dict(info)
    out["points"] = {k: ((v[0] * r, v[1]) if v else None) for k, v in (info.get("points") or {}).items()}
    if info.get("pillars"):
        out["pillars"] = {k: (v[0] * r, v[1]) for k, v in info["pillars"].items()}
    return moved, out


def _curve_points(smile: Any, dist: Any, qs: Dict[float, Optional[float]], points: Dict[str, Any], n: int = 61) -> List[List[float]]:
    """The smile (vol points) and the density on a strike grid wide enough for the 1st to the 99th percentile and the
    10-delta strikes: ``[[strike, vol, density], ...]``."""
    ends = [v for v in (qs.get(0.01), qs.get(0.99)) if v] + [p[0] for p in points.values() if p]
    if len(ends) < 2:
        return []
    lo, hi = min(ends), max(ends)
    lo, hi = lo - 0.08 * (hi - lo), hi + 0.08 * (hi - lo)
    out = []
    for i in range(n):
        K = lo + (hi - lo) * i / (n - 1)
        if K <= 0:
            continue
        try:
            out.append([K, smile.vol(K) * 100.0, max(0.0, dist.density(K))])
        except fv.MATH_ERRORS:
            continue
    return out


def _now() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")
