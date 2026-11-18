"""Eğri noktaları (18.11.2026): the desk's list of the points each TRY curve is built from - Ayarlar → "Eğri noktaları".
The desk: "Bu enterpolasyon noktalarına Ayarlar'dan ekle / çıkar yapabilmeliyim, yanlarına da ne olduklarını not
alabilmeliyim. Ama PPK'lar her zaman olmalı. PPK tarihleri güncellenince o da güncellenmeli."

One list per curve - **OIS** and **Offshore** -, the desk's: everyone sees it, only administrators change it (it moves
everyone's curves), every change is logged.  A point is a tenor (1M, 18M, 2Y3M …) or a date; an instrument with its
convention (:mod:`tto.ppkcurve`: OIS, FX swap implied, XCCY); a source - the workbook's own quote (the default points), a
rate typed by the desk, a Bloomberg ticker (a new live subscription: its cost is said and confirmed before it is saved)
or **hesaplanan** (computed: where the curve is read - its par and zero rate by the point's convention, on the viewer's
interpolation setting -, never a point the curve is fitted to); a note; who added / changed it and when; on / off (off is
a soft removal: the row stays with its note, the curve interpolates across it).

* **The default list is today's points.**  OIS: OIS_MAIN's quoted tenors 1M … 10Y (Motor's quote copy A306:B321; 15M and
  21M are no quotes).  Offshore: the Forward sheet's TRYI 1W … 9M and TRYSAQ 1 … 10 rows as its curve reads them
  (AJ123:AN143), and "18M · XCCY · hesaplanan" (the desk: "18M hesaplanacak, gerçek kotasyon girilmeyecek" - EK_FX's 18M
  takes the curve's discount factor there).  On the default list every reader reads the workbook's own formulas.
* **PPK meetings are always in the list**: read-only rows of Motor's meeting table (the dashboard's PPK calendar) - PPK
  basamak steps there whatever else is in the list, and a calendar change moves them by itself.
* A curve whose list differs from the default is built on its points, both ways (:func:`tto.ppkcurve.list_curves`;
  tto/interp.py takes it into the workbook: Motor's node pars and the offshore curve's names on Bootstrap, the PPK
  cells on PPK basamak).  DİBS ASW keeps its own quotes (its own tickers, its curve's history day by day): it does not
  follow the list.
"""
from __future__ import annotations

import copy
import datetime as _dt
import math
import re
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import extras as ex
from . import ppkcurve as pk
from .service import ServiceError
from .store import now_iso
from .xl.model import COLS, parse_a1
from .xl.values import date_to_serial, serial_to_date

OIS, OFF = pk.OIS_KIND, "off"
CURVES = (OIS, OFF)
CURVE_TEXT = {OIS: "OIS", OFF: "Offshore"}
#: the instruments a curve takes
KINDS = {OIS: (pk.OIS_KIND,), OFF: (pk.FX_KIND, pk.XCCY_KIND)}
KIND_TEXT = {pk.OIS_KIND: "OIS", pk.FX_KIND: "FX swap ima", pk.XCCY_KIND: "XCCY"}
KIND_RULE = {pk.OIS_KIND: "3 aya kadar tek dönem basit ACT/365, sonra çeyreklik par ACT/365 (Motor'un ızgarası; ızgara dışı bir "
                          "vadede kuponlar vadeden geriye sayılır)",
             pk.FX_KIND: "tek dönem, basit ACT/360",
             pk.XCCY_KIND: "yıllık par ACT/360, kuponlar vadeden geriye sayılır - kısa dönem başta (18A = 6A + 12A)"}
SOURCE_TEXT = {pk.BOOK: "Çalışma kitabı", pk.TYPED: "Elle", pk.TICKER: "Bloomberg", pk.COMPUTED: "Hesaplanan"}
#: OIS's default points: Motor's quote copy (A306:B321 - months, rate) and the row of OIS_MAIN that copy reads
DEFAULT_OIS = ((1, 306, 9), (2, 307, 10), (3, 308, 11), (6, 309, 12), (9, 310, 13), (12, 311, 14), (18, 312, 16),
               (24, 313, 18), (36, 314, 19), (48, 315, 20), (60, 316, 21), (72, 317, 22), (84, 318, 23), (96, 319, 24),
               (108, 320, 25), (120, 321, 26))
#: the offshore curve's: the Forward sheet's TRYI rows (H label, G days, J mid %) and TRYSAQ rows (C label, K days, E mid %)
DEFAULT_TRYI = (("1W", 8), ("2W", 9), ("1M", 10), ("2M", 11), ("3M", 12), ("4M", 13), ("5M", 14), ("6M", 15), ("9M", 16))
DEFAULT_XCCY = tuple(("%dY" % n, pk.XCCY_ROWS[0] + n - 1) for n in range(1, 11))
#: ... and the 18M read off the curve (no quote is ever entered there)
COMPUTED_18M = "off:XCCY 18M"
COMPUTED_18M_NOTE = "1Y–2Y XCCY'den, 6M + 12M kupon, sondan"
#: what a list may hold: active points per curve, the note's length, the log kept
MAX_POINTS, NOTE_MAX, LOG_MAX = 40, 300, 1000
#: where the list and its log are kept (the store's key / value table)
KEY, LOG_KEY = "curvepoints.list", "curvepoints.log"
#: a Bloomberg ticker as the list takes it: the security and its yellow key
_YELLOW = {"CURNCY": "Curncy", "INDEX": "Index", "COMDTY": "Comdty", "GOVT": "Govt", "CORP": "Corp", "EQUITY": "Equity",
           "MTGE": "Mtge", "MUNI": "Muni", "PFD": "Pfd"}
_TICKER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./@&+\-]{0,40}$")
_TENOR = re.compile(r"^(\d{1,3})\s*([WHMAY])(?:\s*(\d{1,2})\s*([MA]))?$")


# ================================================================================================== a point's words
def tenor_text(months: Optional[int] = None, weeks: Optional[int] = None) -> str:
    """1W, 1M … 23M, 1Y, 2Y3M, 10Y - how the list names a tenor."""
    if weeks is not None:
        return "%dW" % weeks
    m = int(months or 0)
    if m % 12 == 0:
        return "%dY" % (m // 12)
    if m < 24:
        return "%dM" % m
    return "%dY%dM" % (m // 12, m % 12)


def parse_tenor(text: Any) -> Optional[Tuple[Optional[int], Optional[int]]]:
    """``(months, weeks)`` of a tenor typed as the desk types it (1W / 1H, 1M / 1A, 18M, 2Y, 2Y3M, 2Y 3A); None when it
    is none."""
    s = " ".join(str(text or "").upper().replace("İ", "I").split())
    m = _TENOR.match(s)
    if not m:
        return None
    n, unit, extra, _ = m.groups()
    n = int(n)
    if unit in "WH":
        return (None, n) if extra is None and 1 <= n <= 52 else None
    months = n * 12 if unit == "Y" else n
    if extra is not None:
        if unit != "Y":
            return None
        months += int(extra)
    return (months, None) if 1 <= months <= 360 else None


def parse_day(text: Any) -> Optional[_dt.date]:
    """A date typed as dd.mm.yyyy (or yyyy-mm-dd)."""
    s = str(text or "").strip()
    m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$", s) or None
    try:
        if m:
            return _dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
        if m:
            return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return None


def parse_rate(value: Any) -> Optional[float]:
    """A rate typed in percent ("41,25", "%41,25", 41.25) as a decimal."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
    else:
        s = str(value or "").replace("%", "").replace(" ", "").strip()
        if s.count(",") == 1 and "." in s:
            s = s.replace(".", "")
        s = s.replace(",", ".")
        try:
            v = float(s)
        except ValueError:
            return None
    if not math.isfinite(v) or not -50.0 <= v <= 500.0:
        return None
    return v / 100.0


def clean_ticker(text: Any) -> Optional[str]:
    """A Bloomberg ticker with its yellow key ("TRYSAQ1H ICPL Curncy"); None when it is not one."""
    parts = str(text or "").split()
    if len(parts) < 2:
        return None
    key = _YELLOW.get(parts[-1].upper())
    body = " ".join(parts[:-1])
    if key is None or not _TICKER.match(body):
        return None
    return "%s %s" % (body.upper(), key)


def pct(v: Optional[float]) -> str:
    return ("%.4f" % (v * 100.0)).replace(".", ",") + "%" if isinstance(v, float) and math.isfinite(v) else ""


# ================================================================================================== the default list
def default_rows() -> List[Dict[str, Any]]:
    """The list as the workbook has its curves: OIS_MAIN's quoted tenors, the Forward sheet's offshore rows, the computed
    18M - every one on, the desk's notes empty."""
    rows: List[Dict[str, Any]] = []
    for months, motor, main in DEFAULT_OIS:
        rows.append(_row("ois:%s" % pk.tenor_label(months), OIS, pk.OIS_KIND, tenor_text(months), pk.BOOK, default=True,
                         name=pk.tenor_label(months), book=motor, cell="OIS_MAIN!B%d" % main))
    for label, r in DEFAULT_TRYI:
        rows.append(_row("off:TRYI %s" % label, OFF, pk.FX_KIND, label, pk.BOOK, default=True, name="TRYI %s" % label, book=r,
                         cell="Forward!J%d" % r))
    for label, r in DEFAULT_XCCY:
        rows.append(_row("off:XCCY %s" % label, OFF, pk.XCCY_KIND, label, pk.BOOK, default=True, name="XCCY %s" % label, book=r,
                         cell="Forward!E%d" % r))
    rows.append(_row(COMPUTED_18M, OFF, pk.XCCY_KIND, "18M", pk.COMPUTED, default=True, name="XCCY 18M", note=COMPUTED_18M_NOTE))
    return rows


def _row(rid: str, curve: str, kind: str, tenor: Optional[str], source: str, default: bool = False, name: str = "",
         book: Optional[int] = None, cell: str = "", note: str = "", date: Optional[str] = None, rate: Optional[float] = None,
         ticker: Optional[str] = None) -> Dict[str, Any]:
    return {"id": rid, "curve": curve, "kind": kind, "tenor": tenor, "date": date, "source": source, "name": name or tenor or "",
            "book": book, "cell": cell, "rate": rate, "ticker": ticker, "slot": None, "note": note, "on": True,
            "default": default, "added_by": "", "added_at": "", "changed_by": "", "changed_at": "", "confirmed": None}


#: what a stored row of the default list keeps of its own (the rest is the code's: where it reads its quote)
_KEPT_OF_DEFAULT = ("note", "on", "changed_by", "changed_at")


def pillar(row: Dict[str, Any]) -> bool:
    """Whether the curve is built on the row: on, and not computed."""
    return bool(row.get("on")) and row.get("source") != pk.COMPUTED


def spec_of(row: Dict[str, Any]) -> pk.Spec:
    """The row as :mod:`tto.ppkcurve` builds a curve from it."""
    months = weeks = None
    if row.get("tenor"):
        parsed = parse_tenor(row["tenor"])
        if parsed:
            months, weeks = parsed
    date = None
    if row.get("date"):
        d = parse_day(row["date"])
        date = date_to_serial(d) if d else None
    cell = None
    if row.get("source") == pk.TICKER and row.get("slot") is not None:
        cell = (ex.INTERP_SHEET, ex.LIST_TICKER_FIRST + int(row["slot"]), parse_a1(ex.LIST_VALUE_COL + "1") % COLS)
    return pk.Spec(row["id"], row.get("name") or row.get("tenor") or "", row["kind"], row["source"], months, weeks, date,
                   row.get("book"), row.get("rate"), cell)


# ================================================================================================== the desk's list
class CurvePoints(object):
    """The desk's list of curve points: kept in the store, changed by administrators only, every change logged; what the
    curves are built from (:meth:`specs`) and what Ayarlar shows (:meth:`payload`)."""

    def __init__(self, svc: Any):
        self.svc = svc
        self._lock = threading.RLock()
        self.rev = 0
        self.seq = 0
        self.rows: List[Dict[str, Any]] = self._load()
        self._specs = self._make_specs(self.rows)

    # ------------------------------------------------------------------ kept
    def _load(self) -> List[Dict[str, Any]]:
        stored = self.svc.store.get(KEY)
        defaults = default_rows()
        if not isinstance(stored, dict) or not isinstance(stored.get("rows"), list):
            return defaults
        self.rev = int(stored.get("rev") or 0)
        self.seq = int(stored.get("seq") or 0)
        own = {d["id"]: d for d in defaults}
        rows: List[Dict[str, Any]] = []
        seen = set()
        for r in stored["rows"]:
            if not isinstance(r, dict) or r.get("id") in seen:
                continue
            base = own.get(r.get("id"))
            if base is not None:                       # a default row: where it reads its quote is the code's
                row = dict(base)
                row.update({k: r.get(k, row[k]) for k in _KEPT_OF_DEFAULT})
            elif r.get("curve") in CURVES and r.get("kind") in KINDS.get(r.get("curve"), ()) and \
                    r.get("source") in (pk.TYPED, pk.TICKER, pk.COMPUTED) and not str(r.get("id", "")).startswith(("ois:", "off:", "ppk:")):
                row = _row(str(r["id"]), r["curve"], r["kind"], r.get("tenor"), r["source"])
                row.update({k: r.get(k, row.get(k)) for k in row if k not in ("default", "book", "cell")})
            else:
                continue
            row["on"] = bool(row.get("on"))
            rows.append(row)
            seen.add(row["id"])
        rows += [d for d in defaults if d["id"] not in seen]          # (a default point the stored list did not know yet)
        return rows

    def _save(self) -> None:
        self.svc.store.put(KEY, {"version": 1, "rev": self.rev, "seq": self.seq, "rows": self.rows})

    def log(self, limit: int = 30) -> List[Dict[str, Any]]:
        """The latest changes, newest first."""
        entries = self.svc.store.get(LOG_KEY) or []
        return list(reversed(entries[-limit:])) if limit else list(reversed(entries))

    def _log(self, entries: List[Dict[str, Any]]) -> None:
        if not entries:
            return
        kept = (self.svc.store.get(LOG_KEY) or []) + entries
        self.svc.store.put(LOG_KEY, kept[-LOG_MAX:])

    # ------------------------------------------------------------------ what the curves are built from
    @staticmethod
    def _make_specs(rows: Sequence[Dict[str, Any]]) -> Dict[str, Optional[Tuple[pk.Spec, ...]]]:
        out: Dict[str, Optional[Tuple[pk.Spec, ...]]] = {}
        for curve in CURVES:
            out[curve] = tuple(spec_of(r) for r in rows if r["curve"] == curve and pillar(r)) if _differs(rows, curve) else None
        return out

    def specs(self) -> Dict[str, Optional[Tuple[pk.Spec, ...]]]:
        """``{"ois": points | None, "off": …}`` - the points a curve is built on when its list differs from the default
        (:func:`tto.ppkcurve.read`'s ``points``); None: the workbook's own (the default list)."""
        with self._lock:
            return dict(self._specs)

    def custom(self, curve: Optional[str] = None) -> bool:
        """Whether the list of ``curve`` (any curve: None) differs from the default."""
        with self._lock:
            return any(self._specs[c] is not None for c in ((curve,) if curve else CURVES))

    def tickers(self) -> Dict[int, str]:
        """The Bloomberg tickers of the points that read one (on), by their slot in EK_INTERP."""
        with self._lock:
            return {int(r["slot"]): r["ticker"] for r in self.rows
                    if r["source"] == pk.TICKER and r.get("on") and r.get("slot") is not None and r.get("ticker")}

    def differences(self, curve: str) -> List[str]:
        """How a curve's list differs from the default, in words ("2Y kapalı", "2Y3M (XCCY, elle) eklendi")."""
        with self._lock:
            return _differences(self.rows, curve)

    # ------------------------------------------------------------------ the cost of a ticker
    def ticker_cost(self) -> str:
        """What a new ticker point costs Bloomberg - said before it is saved."""
        s = self.svc.settings
        poll = max(float(getattr(s, "bbg_price_poll", 120.0) or 120.0), 1.0)
        worst = int(round(3 * 86400.0 / poll))
        text = ("1 canlı ticker, MID / BID / ASK - Bloomberg'e yeni bir abonelik. İlk değer bir referans isteğiyle gelir: 3 veri "
                "noktası (dashboard her açıldığında yeniden 3). Sonra canlı akış: akış Bloomberg'in günlük sınırına sayılmaz. "
                "Abonelik akmazsa alan başına en sık %d dakikada bir yeniden sorulur: en kötü günde ~%s veri noktası."
                % (max(int(round(poll / 60.0)), 1), format(worst, ",").replace(",", ".")))
        if self.svc.mode != "live":
            return text + " Şu an replay: Bloomberg'e istek gitmez; ticker'ın değeri yoksa nokta eğriye girmez."
        try:
            st = self.svc.provider.status() or {}
        except Exception:  # noqa: BLE001 - a status that cannot be read: no figure of today
            st = {}
        cap = int(getattr(s, "bbg_max_hits", 0) or 0)
        if isinstance(st.get("hits_today"), (int, float)):
            text += " Bugün şimdiye kadar %s veri noktası" % format(int(st["hits_today"]), ",").replace(",", ".")
            text += (" (dashboard'un günlük koruması %s)." % format(cap, ",").replace(",", ".")) if cap else "."
        return text

    # ------------------------------------------------------------------ changes (administrators)
    def change(self, user: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """An administrator's change of the list: ``action`` - ``add`` (``curve``, ``kind``, ``when`` (a tenor or a date),
        ``source`` (typed / ticker / calc), ``rate`` (%), ``ticker``, ``note``), ``off`` / ``on`` (``id``), ``note`` (``id``,
        ``note``), ``rate`` (``id``, ``rate``: a typed point's) or ``reset`` (back to the default: its points on, the
        others off - kept with their notes).  A ticker point (added, or switched on) needs ``confirm``: without it nothing
        is saved and the answer says what it costs (``needs_confirm``, ``cost``).  Every change is logged."""
        data = data if isinstance(data, dict) else {}
        action = str(data.get("action") or "").strip().lower()
        with self._lock:
            rows, rev, seq = copy.deepcopy(self.rows), self.rev, self.seq
        who = self._display(user)
        now = now_iso()
        fn = {"add": self._add, "off": self._switch, "on": self._switch, "note": self._note, "rate": self._rate,
              "reset": self._reset}.get(action)
        if fn is None:
            raise ServiceError("bilinmeyen işlem: %s" % (action or "(yok)"))
        res = fn(rows, data, action, user, who, now, seq)
        if res.get("needs_confirm"):
            return res
        rows, entries, seq = res["rows"], res["log"], res.get("seq", seq)
        self._check(rows)
        with self._lock:
            if self.rev != rev:
                raise ServiceError("liste bu arada değişti – sayfayı yenileyip tekrar deneyin", 409)
            self.rows, self.seq = rows, seq
            self.rev += 1
            self._specs = self._make_specs(rows)
            self._save()
            self._log(entries)
        self.svc.et.call(self.svc.interp.apply_list)
        self.svc.bump()
        return {"done": "; ".join(e["text"] for e in entries)}

    def _display(self, user: str) -> str:
        acc = self.svc.store.account(user) or {}
        return acc.get("display") or user

    def _find(self, rows: List[Dict[str, Any]], data: Dict[str, Any]) -> Dict[str, Any]:
        rid = str(data.get("id") or "")
        if rid.startswith("ppk:"):
            raise ServiceError("PPK toplantıları listeden çıkmaz: takvimden gelir (Ayarlar → PPK toplantı takvimi); PPK basamak "
                               "orada her zaman basamaklanır")
        row = next((r for r in rows if r["id"] == rid), None)
        if row is None:
            raise ServiceError("nokta bulunamadı: %s" % (rid or "(yok)"), 404)
        return row

    def _entry(self, user: str, who: str, now: str, action: str, row: Optional[Dict[str, Any]], text: str) -> Dict[str, Any]:
        return {"at": now, "by": user, "who": who, "action": action, "curve": row["curve"] if row else "",
                "id": row["id"] if row else "", "point": _label(row) if row else "", "text": text}

    def _add(self, rows, data, action, user, who, now, seq) -> Dict[str, Any]:
        curve = str(data.get("curve") or "").strip().lower()
        curve = {"ois": OIS, "off": OFF, "offshore": OFF}.get(curve, curve)
        if curve not in CURVES:
            raise ServiceError("eğri OIS ya da Offshore olmalı")
        kind = str(data.get("kind") or "").strip().lower()
        kind = {"fx swap": pk.FX_KIND, "fxswap": pk.FX_KIND, "fx swap ima": pk.FX_KIND}.get(kind, kind)
        if kind not in KINDS[curve]:
            raise ServiceError("%s eğrisinde tür şunlardan biri olmalı: %s" % (CURVE_TEXT[curve], ", ".join(KIND_TEXT[k] for k in KINDS[curve])))
        when = str(data.get("when") or "").strip()
        tenor = date = None
        parsed = parse_tenor(when)
        if parsed is not None:
            tenor = tenor_text(*parsed)
        else:
            d = parse_day(when)
            if d is None:
                raise ServiceError("vade anlaşılamadı: %s (1W, 18M, 2Y3M ya da gg.aa.yyyy)" % (when or "(boş)"))
            today = serial_to_date(self.svc.books["tto"].engine.clock.today())
            if not today < d <= today + _dt.timedelta(days=366 * 30):
                raise ServiceError("tarih bugünden sonra ve en çok 30 yıl ileride olmalı: %s" % when)
            date = d.isoformat()
        source = str(data.get("source") or "").strip().lower()
        source = {"elle": pk.TYPED, "typed": pk.TYPED, "bloomberg": pk.TICKER, "ticker": pk.TICKER, "hesaplanan": pk.COMPUTED,
                  "calc": pk.COMPUTED, "computed": pk.COMPUTED}.get(source, source)
        if source not in (pk.TYPED, pk.TICKER, pk.COMPUTED):
            raise ServiceError("kaynak elle, Bloomberg ya da hesaplanan olmalı (çalışma kitabının kotaları varsayılan noktalardır)")
        note = _note_of(data.get("note"))
        row = _row("", curve, kind, tenor, source, name=_name_of(curve, kind, tenor, date), date=date, note=note)
        if source == pk.TYPED:
            rate = parse_rate(data.get("rate"))
            if rate is None:
                raise ServiceError("oran anlaşılamadı: %s (yüzde, ör. 41,25)" % (data.get("rate") or "(boş)"))
            row["rate"] = rate
        if source == pk.TICKER:
            ticker = clean_ticker(data.get("ticker"))
            if ticker is None:
                raise ServiceError("Bloomberg ticker'ı anlaşılamadı: %s (ör. TRYSAQ1H ICPL Curncy)" % (data.get("ticker") or "(boş)"))
            row["ticker"] = ticker
            if not data.get("confirm"):
                return {"needs_confirm": True, "cost": self.ticker_cost(), "ticker": ticker}
            row["confirmed"] = {"by": user, "at": now, "cost": self.ticker_cost()}
        seq += 1
        row.update(id="p%d" % seq, added_by=user, added_at=now, changed_by=user, changed_at=now)
        rows.append(row)
        _slots(rows)
        text = "%s · %s eklendi (%s, %s%s)" % (CURVE_TEXT[curve], _label(row), KIND_TEXT[kind], _source_words(row),
                                                 (" · not: " + note) if note else "")
        return {"rows": rows, "log": [self._entry(user, who, now, "add", row, text)], "seq": seq}

    def _switch(self, rows, data, action, user, who, now, seq) -> Dict[str, Any]:
        row = self._find(rows, data)
        on = action == "on"
        if row["on"] == on:
            raise ServiceError("%s zaten %s" % (_label(row), "açık" if on else "kapalı"))
        if on and row["source"] == pk.TICKER:
            if not data.get("confirm"):
                return {"needs_confirm": True, "cost": self.ticker_cost(), "ticker": row.get("ticker")}
            row["confirmed"] = {"by": user, "at": now, "cost": self.ticker_cost()}
        row.update(on=on, changed_by=user, changed_at=now)
        _slots(rows)
        text = "%s · %s %s" % (CURVE_TEXT[row["curve"]], _label(row), "açıldı" if on else "kapatıldı (listede notuyla kalır)")
        return {"rows": rows, "log": [self._entry(user, who, now, action, row, text)]}

    def _note(self, rows, data, action, user, who, now, seq) -> Dict[str, Any]:
        row = self._find(rows, data)
        note = _note_of(data.get("note"))
        if note == row.get("note", ""):
            raise ServiceError("not aynı")
        before = row.get("note", "")
        row.update(note=note, changed_by=user, changed_at=now)
        text = "%s · %s notu: %s → %s" % (CURVE_TEXT[row["curve"]], _label(row), ("“%s”" % before) if before else "(boş)",
                                          ("“%s”" % note) if note else "(boş)")
        return {"rows": rows, "log": [self._entry(user, who, now, "note", row, text)]}

    def _rate(self, rows, data, action, user, who, now, seq) -> Dict[str, Any]:
        row = self._find(rows, data)
        if row["source"] != pk.TYPED:
            raise ServiceError("yalnız elle girilen bir noktanın oranı değiştirilir")
        rate = parse_rate(data.get("rate"))
        if rate is None:
            raise ServiceError("oran anlaşılamadı: %s (yüzde, ör. 41,25)" % (data.get("rate") or "(boş)"))
        before = row.get("rate")
        row.update(rate=rate, changed_by=user, changed_at=now)
        text = "%s · %s oranı %s → %s" % (CURVE_TEXT[row["curve"]], _label(row), pct(before), pct(rate))
        return {"rows": rows, "log": [self._entry(user, who, now, "rate", row, text)]}

    def _reset(self, rows, data, action, user, who, now, seq) -> Dict[str, Any]:
        changed = []
        for r in rows:
            want = bool(r["default"])
            if r["on"] != want:
                r.update(on=want, changed_by=user, changed_at=now)
                changed.append("%s %s %s" % (CURVE_TEXT[r["curve"]], _label(r), "açıldı" if want else "kapatıldı"))
        if not changed:
            raise ServiceError("liste zaten varsayılan")
        _slots(rows)
        text = "Varsayılana dönüldü: " + ", ".join(changed)
        return {"rows": rows, "log": [self._entry(user, who, now, "reset", None, text)]}

    def _check(self, rows: List[Dict[str, Any]]) -> None:
        """What a list must be before it is saved: at most :data:`MAX_POINTS` points a curve is built on, at most
        :data:`ex.LIST_TICKERS` tickers, and no two of a curve's points on one day (the calculation thread dates them)."""
        for curve in CURVES:
            n = sum(1 for r in rows if r["curve"] == curve and pillar(r))
            if n > MAX_POINTS:
                raise ServiceError("%s eğrisinde en çok %d açık nokta olabilir" % (CURVE_TEXT[curve], MAX_POINTS))
            if n < 1:
                raise ServiceError("%s eğrisinde en az bir nokta açık kalmalı" % CURVE_TEXT[curve])
        if sum(1 for r in rows if r["source"] == pk.TICKER and r["on"]) > ex.LIST_TICKERS:
            raise ServiceError("en çok %d Bloomberg ticker'lı nokta açık olabilir" % ex.LIST_TICKERS)
        clash = self.svc.et.call(self._same_day, rows)
        if clash:
            raise ServiceError(clash)

    def _same_day(self, rows: List[Dict[str, Any]]) -> str:
        """Two points a curve is built on that fall on one day ("": none) - dated on the desk's calculation."""
        book = self.svc.books.get("tto")
        if book is None:
            return ""
        calc = book.engine.shared
        idx = book.model.sheet_index

        def get(sheet: str, r: int, c: int) -> Any:
            return calc.get(idx[sheet], r, c)

        for curve in CURVES:
            mine = [r for r in rows if r["curve"] == curve and pillar(r)]
            seen: Dict[float, str] = {}
            for p in pk.resolve(get, [spec_of(r) for r in mine], curve):
                if p.end is None:
                    continue
                other = seen.get(p.end)
                if other is not None:
                    return "%s eğrisinde %s ile %s aynı güne düşüyor (%s): biri kapatılmalı" % (
                        CURVE_TEXT[curve], other, p.spec.name, _date_text(p.serial))
                seen[p.end] = p.spec.name
        return ""

    # ------------------------------------------------------------------ what Ayarlar shows
    def payload(self, user: Optional[str], admin: bool = False) -> Dict[str, Any]:
        """Ayarlar → Eğri noktaları: both curves' lists - each point with its source, its value now (a computed point's
        par, zero rate and discount factor on the viewer's interpolation setting), its note and who added / changed it;
        the PPK meetings among them (read only, from the calendar) - how each list differs from the default, the kinds and
        sources one may add, what a ticker costs and the log."""
        with self._lock:
            rows = copy.deepcopy(self.rows)
            rev = self.rev
        book = self.svc.books.get("tto")
        if book is None or not getattr(self.svc.interp, "available", False):
            return {"available": False}
        curves = self.svc.et.call(self._curves, user, book, rows)
        names = {u["name"]: u["display"] for u in self.svc.store.users()}       # (who added / changed: their names)
        for c in curves:
            for r in c["rows"]:
                for k in ("added_by", "changed_by"):
                    if r.get(k):
                        r[k] = names.get(r[k], r[k])
        mode = self.svc.interp.mode(user)
        return {"available": True, "can_edit": bool(admin), "rev": rev, "mode": mode,
                "mode_text": "PPK basamak" if mode == "ppk" else "Bootstrap (Murex)",
                # a list whose curve cannot be built: the workbook's own curve stands meanwhile (said in the page)
                "errors": self.svc.interp.list_errors() if any(_differs(rows, c) for c in CURVES) else [],
                "curves": curves, "custom": {c: _differs(rows, c) for c in CURVES},
                "kinds": [{"id": k, "label": KIND_TEXT[k], "rule": KIND_RULE[k], "curves": [c for c in CURVES if k in KINDS[c]]}
                          for k in (pk.OIS_KIND, pk.FX_KIND, pk.XCCY_KIND)],
                "sources": [{"id": s, "label": SOURCE_TEXT[s]} for s in (pk.TYPED, pk.TICKER, pk.COMPUTED)],
                "cost": self.ticker_cost(), "live": self.svc.mode == "live", "log": self.log(30)}

    def _curves(self, user: Optional[str], book: Any, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        calc = self.svc._calc(user, book)
        idx = book.model.sheet_index

        def get(sheet: str, r: int, c: int) -> Any:
            return calc.get(idx[sheet], r, c)

        from .interpchart import meetings
        out = []
        meets = meetings(get)
        cv = self.svc._try_curves(book, calc)               # (the user's curves: what Fiyatlama and EK_FX read too)
        mode = self.svc.interp.mode(user)
        for curve in CURVES:
            mine = [r for r in rows if r["curve"] == curve]
            where = pk.Dates(get, curve)
            res = pk.resolve(get, [spec_of(r) for r in mine], curve, where)
            read = reading_curve(cv, curve, mode)
            items = [_item(r, p, read) for r, p in zip(mine, res)]
            shift = 0.0
            if curve == OFF:
                ois_spot, fx_spot = pk._num(pk.to_num(get(*pk.OIS_SPOT))), where.spot
                shift = (fx_spot - ois_spot) if ois_spot is not None and fx_spot is not None else 0.0
            for day, name, date in meets:
                d = day - shift
                items.append({"id": "ppk:%s" % (name or day), "name": name or "PPK", "when": _date_text(date), "day": d,
                              "date": _date_text(where.spot + d) if where.spot is not None else "", "kind": "ppk",
                              "kind_text": "PPK toplantısı", "rule": "", "source": "ppk", "source_text": "takvimden",
                              "source_tip": "Motor'un toplantı tablosu (Ayarlar → PPK toplantı takvimi): takvim değişince kendiliğinden",
                              "value": None, "note": "PPK basamak burada basamaklanır", "note_tip": "TLREF kararın ertesi iş gününden (etkin gün) değişir",
                              "on": True, "default": True, "ppk": True, "computed": False, "pillar": False, "error": ""})
            items.sort(key=lambda x: (x["day"] if isinstance(x.get("day"), (int, float)) else 1e9, 0 if x.get("ppk") else 1))
            out.append({"id": curve, "title": CURVE_TEXT[curve], "custom": _differs(rows, curve),
                        "differs": _differences(rows, curve), "spot": _date_text(where.spot), "rows": items})
        return out


# ================================================================================================== helpers
def _differs(rows: Sequence[Dict[str, Any]], curve: str) -> bool:
    """A curve's list differs from the default when a default point is off or another point is on (a computed point is
    no point the curve is built on: it never makes a difference)."""
    for r in rows:
        if r["curve"] != curve or r["source"] == pk.COMPUTED:
            continue
        if r["default"] and not r["on"]:
            return True
        if not r["default"] and r["on"]:
            return True
    return False


def _differences(rows: Sequence[Dict[str, Any]], curve: str) -> List[str]:
    out = []
    for r in rows:
        if r["curve"] != curve or r["source"] == pk.COMPUTED:
            continue
        if r["default"] and not r["on"]:
            out.append("%s kapalı" % _label(r))
        elif not r["default"] and r["on"]:
            out.append("%s (%s, %s) eklendi" % (_label(r), KIND_TEXT[r["kind"]], _source_words(r)))
    return out


def _slots(rows: List[Dict[str, Any]]) -> None:
    """The EK_INTERP slots of the ticker points that are on (each keeps its own while on); an off one gives its up."""
    used = set()
    for r in rows:
        if r["source"] != pk.TICKER:
            continue
        if not r["on"]:
            r["slot"] = None
        elif r.get("slot") is not None:
            used.add(int(r["slot"]))
    for r in rows:
        if r["source"] == pk.TICKER and r["on"] and r.get("slot") is None:
            free = next((k for k in range(ex.LIST_TICKERS) if k not in used), None)
            if free is None:
                raise ServiceError("en çok %d Bloomberg ticker'lı nokta açık olabilir" % ex.LIST_TICKERS)
            r["slot"] = free
            used.add(free)


def _note_of(text: Any) -> str:
    note = " ".join(str(text or "").split())
    if len(note) > NOTE_MAX:
        raise ServiceError("not en fazla %d karakter olabilir" % NOTE_MAX)
    return note


def _name_of(curve: str, kind: str, tenor: Optional[str], date: Optional[str]) -> str:
    when = tenor or (_date_text(date_to_serial(parse_day(date))) if date else "")
    return when if kind == pk.OIS_KIND else "%s %s" % ("FX" if kind == pk.FX_KIND else "XCCY", when)


def _label(row: Dict[str, Any]) -> str:
    return row.get("name") or row.get("tenor") or row.get("date") or row.get("id") or ""


def _source_words(row: Dict[str, Any]) -> str:
    s = row["source"]
    if s == pk.TYPED:
        return "elle %s" % pct(row.get("rate"))
    if s == pk.TICKER:
        return "Bloomberg %s" % (row.get("ticker") or "")
    if s == pk.COMPUTED:
        return "hesaplanan"
    return "çalışma kitabı %s" % (row.get("cell") or "")


def _date_text(serial: Optional[float]) -> str:
    if not isinstance(serial, (int, float)) or not 20000 < serial < 80000:
        return ""
    return serial_to_date(serial).strftime("%d.%m.%Y")


def reading_curve(cv: Optional[Dict[str, Any]], curve: str, mode: str) -> Any:
    """The curve a computed point is read off on a user's interpolation setting (``cv``: their curves,
    ``Service._try_curves``): Bootstrap - Motor's (OIS) and the offshore curve as its names have it (the desk's list's
    when it differs); PPK basamak - ppkcurve's PPK curves (a PPK curve that cannot be made: Bootstrap).  The very curves
    Fiyatlama prices on and EK_FX's 18M is read off (``Service._asw_fx_18m``)."""
    if not cv:
        return None
    boot, ppk = ("boot", "ppk") if curve == OIS else ("off_boot", "off_ppk")
    if mode == "ppk" and cv.get(ppk) is not None:
        return cv[ppk]
    return cv.get(boot)


def computed(read: Any, p: pk.Resolved) -> Dict[str, Optional[float]]:
    """A computed point read off ``read`` (:func:`reading_curve`): the discount factor at its maturity, its par rate by
    its convention (its own schedule) and its zero rate (compounded once a year, ACT/365 - EK_FX's).  An XCCY of two
    coupons - the 18M: 6M then 12M - is ``aswfx.point_18m`` itself, the one function behind EK_FX's 18M; any other XCCY
    the same pieces (``aswfx.xccy_par``, ``aswfx.zero_rate``), an OIS or FX swap point its own swap (``ppkcurve.par``)."""
    from . import aswfx
    none = {"df": None, "par": None, "zero": None}
    if read is None or p.end is None or not p.pays:
        return none
    try:
        if p.spec.kind == pk.XCCY_KIND and len(p.pays) == 2:
            pt = aswfx.point_18m(read, p.pays[0], p.pays[1])
            return {"df": pt.df, "par": pt.par / 100.0, "zero": pt.zero / 100.0} if pt is not None else none
        dfs = [read.df(t) for t in p.pays]
        df = dfs[-1]
        par = aswfx.xccy_par(p.pays, dfs) if p.spec.kind == pk.XCCY_KIND else pk.par(read, p.pays, p.accruals)
        zero = aswfx.zero_rate(float(df), float(p.end))
    except (ArithmeticError, ValueError):
        return none
    if not (isinstance(df, float) and math.isfinite(df) and df > 0) or par is None or zero is None:
        return none
    return {"df": df, "par": par, "zero": zero / 100.0}


def _item(row: Dict[str, Any], p: pk.Resolved, read: Any) -> Dict[str, Any]:
    """A row of the list as Ayarlar shows it."""
    when = row.get("tenor") or (_date_text(date_to_serial(parse_day(row["date"]))) if row.get("date") else "")
    item = {"id": row["id"], "name": _label(row), "when": when, "day": p.end, "date": _date_text(p.serial), "kind": row["kind"],
            "kind_text": KIND_TEXT[row["kind"]], "rule": KIND_RULE[row["kind"]], "source": row["source"],
            "source_text": SOURCE_TEXT[row["source"]], "note": row.get("note") or "", "on": bool(row.get("on")),
            "default": bool(row.get("default")), "ppk": False, "computed": row["source"] == pk.COMPUTED, "pillar": pillar(row),
            "added_by": row.get("added_by") or "", "added_at": row.get("added_at") or "",
            "changed_by": row.get("changed_by") or "", "changed_at": row.get("changed_at") or "", "error": p.error,
            "value": p.rate, "zero": None, "df": None, "ticker": row.get("ticker"), "rate": row.get("rate")}
    s = row["source"]
    if s == pk.BOOK:
        item["source_tip"] = "Çalışma kitabının kotası: %s" % row.get("cell", "")
    elif s == pk.TYPED:
        item["source_tip"] = "Masanın girdiği oran: %s" % pct(row.get("rate"))
    elif s == pk.TICKER:
        conf = row.get("confirmed") or {}
        item["source_tip"] = "Bloomberg: %s (MID, yoksa BID/ASK ortası; yüzde)%s" % (
            row.get("ticker") or "", (" · maliyeti %s %s onayladı" % (conf.get("by", ""), conf.get("at", ""))) if conf else "")
        if not row.get("on"):
            item["error"] = ""                                  # (off: no subscription, nothing asked)
    else:
        item["source_tip"] = ("Eğriden okunur, eğriye bilgi eklemez: %s kuralıyla par, sıfır kupon faizi (yıllık bileşik ACT/365) "
                              "ve iskonto faktörü" % KIND_TEXT[row["kind"]])
        if row.get("on"):
            item.update(computed(read, p))
            item["value"] = item.pop("par")
    if p.pays and len(p.pays) > 1:
        item["schedule"] = " + ".join("%dg" % int(round(b - a)) for a, b in zip((0.0,) + tuple(p.pays[:-1]), p.pays))
    return item


__all__ = ["CurvePoints", "default_rows", "spec_of", "parse_tenor", "tenor_text", "computed", "reading_curve"]
