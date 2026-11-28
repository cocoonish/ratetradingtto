"""Bugün: the morning screen - what wants attention, on one page (``GET /api/bugun``).  Each block says where the thing
is handled (the page links there) and says plainly when there is nothing.

* **RET** - loaded today or not (the header's yellow dot: the RET's last load is not of today's date), who loaded it
  and when; the fair value's tenors whose value differs from the published RET ("RET güncellemesi var":
  ``retfair.summary``, as last worked out).  The page opens the RET dialog on the fair value tab then, on the manual
  one when the RET was not loaded today.
* **Trades** - the open trades the user sees (the desk's and their own; another trader's own trades never), each with
  today's and the total P&L as of the last "MTM yenile" of its tab - nothing is valued here (MTM is on demand) -, and
  the ones near their target or stop: when the trades carry their ``levels`` (``/api/trades``: ``{target, stop, unit,
  to_target, to_stop, near}``); without them nothing is said of it.
* **Quant** - the AL / SAT lines that appeared since the previous close: the signal log's entries opened since the
  desk's close of the business day before the quant's day (a threshold crossed, a daily line's "YENİ") and the daily
  lines whose direction turned since that close (``new``) - best expectancy first (TRY at the line's own size), with
  the instrument, the side, the size, entry / target / stop and R/R - in the traded instrument's own level (an FX
  line's forward price; a level of the model's own - the FRA / PPK line's gap - as the instrument's, the FRA's rate,
  the gap beside it: ``note``).
* **DİBS** - the trading list's bonds whose RV signal turned: DİBS RV's Sinyal (OIS ASW, AC) and Sinyal FX (BI)
  against the desk's close record of them (:meth:`Bugun.look`: taken at the desk's close every business day - the
  sheet keeps no history of its signals; before the first record there is no comparison and the bonds signalling now
  are listed, "dünle kıyas yok"), and the zero-coupon curve's rich / cheap (the quant fit's NSS distance,
  ``dibsfv:<ISIN>``) beyond DİBS RV's threshold (P2) now and at the last close of its history.  The desk's
  calculation (the shared inputs) on both sides.
* **Girilmemiş işlemler** - the desk's trades said in Broker Chat today and not in Günlük İşlemler (the
  reconciliation's "Girilmedi", ``Service.broker_recon``).
* **Ajanda · takvim** - today's agenda items (the desk's and the user's own), the deadlines not met, today's / the
  next PPK and FOMC meetings (the meeting calendars), the TRY and USD holidays of today and of the next week day.

The desk, 28.11.2026 ("A - Yildizlilari yap. B - Hepsini yap. C - 2-3-4-5-8-10-12-13-16"), made it the morning meeting:

* **Kontrol** (A10, A8) - Masa's Kontrol strip's checks that are not "tamam" (MASA!B3:L3, their codes AY3:BH3 - the
  desk's calculation), each with its rule and the table it checks (:data:`KONTROL`), how many are; and when the user last
  pasted their DV01 position (``varrisk.paste_stamp``: red when not today).
* **PPK / FOMC günü** (C5) - on a TCMB or Fed meeting's day and the business day before it: the meeting's implied step
  now and against the last close (the PPK history), the survey, the scenarios' steps, the user's own position's risk of
  the decision (DV01 Risk's PPK karar riski: TL/bp, a 25 bp surprise); FOMC's from USD · FOMC (no history there).
* **Kapanıştan beri** (A11) - the largest moves since the previous close of OIS, offshore, offshore − OIS, the VİOP
  contracts and the bonds' ASW (Eğri Hareketi's points, ``Watch.moves``), the points that did not move today, the alarms
  that fired since the previous close; the page's "Referansı şimdi al" takes İzleme's and Eğri Hareketi's at once.
* **Masa notları** (A11) - the day's notes (``desk.notes:<day>``, shared), typed in place; the last earlier day's one
  click away.

No Bloomberg request; nothing valued, fitted or recomputed: the store, the quant result, the fair value RET's last
summary and a few cells of the desk's calculation (one trip to the calculation thread).  A block that cannot be read
says why; the others stand.
"""
from __future__ import annotations

import datetime as _dt
import math
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

#: the desk's close records of DİBS RV's signals, by day (the sheet keeps none): {day: {"at", "threshold", "bonds"}}
DIBS_KEY = "bugun.dibs"
DIBS_KEEP = 15                       # days of records kept
DIBS_SHEET = "DİBS RV"
SIGNALS = ("UCUZ", "PAHALI")
QUANT_TOP = 8                        # quant lines shown (the page says how many more there are)
LIST_MAX = 40                        # rows of a list at most (trades, chat lines, agenda items)
DEFAULT_CLOSE = _dt.time(17, 30)
RETRY = 600.0                        # s: a close record that failed is tried again after this long
#: a signal leg's action as the desk says the side
SIDES = {"Pay": "PAY", "Receive": "RECEIVE", "Buy": "AL", "Sell": "SAT", "Steepener": "STEEPENER",
         "Flattener": "FLATTENER", "Buy protection": "KORUMA AL", "Sell protection": "KORUMA SAT"}

#: Masa's Kontrol strip (MASA!B3:L3), chip by chip: (its column, its state code's column - 0 tamam, 1 uyarı, 2 hata, the
#: workbook's own AY3:BH3; AX3 the worst of them -, its name, the rule its code follows - read off the code's formula -,
#: the page and the table it checks, where that is).  The desk, 28.11.2026 (A10): "Kontrol nedenine götürsün" - each chip
#: links to its table, its rule in its tooltip; below 1500 px only those not "tamam" and "N tamam"; Bugün lists only those.
KONTROL = (
    ("B", "AX", "Genel", "Kontrollerin en kötüsü (MASA!AX3 = MAX(AY3:BH3)): hepsi tamamsa TAMAM, biri sarıysa UYARI, "
     "biri kırmızıysa HATA.", None, None, ""),
    ("C", "AY", "Spot", "Spot kaynağı (VIOP!AA8): Bloomberg (BBG) yeşil, elle spot (MANUEL) sarı, başka bir şey kırmızı.",
     "viop", "B6", "VİOP › Manuel spot"),
    ("D", "AZ", "OIS kota", "OIS kotaları (OIS_MAIN!B9:B26): 18 vadenin hepsinde kota varsa yeşil, biri eksikse kırmızı.",
     "ois", "B3", "OIS · PPK › OUTRIGHT"),
    ("E", "BA", "Çözücü", "Global çözücünün en büyük |model − kota| farkı (OIS_MAIN!W442:W457) toleransın (AU6) 2 katından "
     "küçükse yeşil, 5 katından küçükse sarı, üstü kırmızı.", "ois", "B22", "OIS · PPK › İMA PPK kontrolü"),
    ("F", "BB", "İma eğri − kota", "İma eğrinin kotalardan en büyük farkı (Motor!U325:U342) 3 bp'den küçükse yeşil, 5 bp'den "
     "küçükse sarı, üstü kırmızı.", "ois", "B22", "OIS · PPK › İMA PPK kontrolü"),
    ("G", "BC", "Geçmiş (BDH)", "VİOP geçmişinin (BDH, VIOP!K380:K509) son günü bir önceki iş günü ya da sonrasıysa yeşil, son "
     "3 iş günü içindeyse sarı, daha eskiyse kırmızı.", "settings", "history", "Ayarlar › Tarihçe"),
    ("H", "BD", "VİOP fiyat", "VİOP kontratlarının bid / ask'ı (VIOP!M99:X100, 12 kontrat): 24'ü de varsa yeşil, en az 12'si "
     "varsa sarı, daha azsa kırmızı.", "viop", "B14", "VİOP › Matris sürücü satırları"),
    ("I", "BE", "DİBS fit", "DİBS eğrisine oturan kâğıt sayısı (DİBS RV!AA5:AA54): en az 6 yeşil, 3–5 sarı, daha az kırmızı.",
     "dibs", "B3", "DİBS RV › göreli değer tablosu"),
    ("J", "BF", "XCCY DF", "XCCY iskonto faktörleri (Forward!G125:G134): hepsi sıfırdan büyük ve vadeyle azalıyorsa yeşil, "
     "değilse kırmızı.", "forward", "B28", "Forward › USDTRY Offshore Zero Rate"),
    ("K", "BG", "Olasılık", "Senaryo olasılıklarının toplamı (OIS_MAIN!Q6) %100 ise yeşil, değilse kırmızı.",
     "ois", "B2", "OIS · PPK › SENARYOLAR"),
    ("L", "BH", "TLREF", "TLREF (OIS_MAIN!J2) sıfırdan büyük bir sayıysa yeşil, değilse kırmızı.",
     "ois", "B1", "OIS · PPK › Parametreler"),
)
KONTROL_SHEET, KONTROL_ROW = "MASA", 3
KONTROL_STATES = {0: "tamam", 1: "uyarı", 2: "hata"}


def kontrol_target(page: Optional[str], panel: Optional[str]) -> str:
    """The address a chip leads to (``#/ois?p=B3``), or ``""``."""
    return "#/%s?p=%s" % (page, panel) if page and panel else ""


def kontrol_read(get: Callable[[str], Any]) -> List[Dict[str, Any]]:
    """Each chip of the strip as it reads now (``get(addr)``: a cell of MASA): its name, text, state code (``None``: one
    that cannot be read), rule, target."""
    out = []
    for col, code_col, name, rule, page, panel, where in KONTROL:
        text = get("%s%d" % (col, KONTROL_ROW))
        code = get("%s%d" % (code_col, KONTROL_ROW))
        code = int(code) if isinstance(code, float) and code in (0.0, 1.0, 2.0) else None
        out.append({"col": col, "name": name, "text": text if isinstance(text, str) else "", "code": code,
                    "state": KONTROL_STATES.get(code, "okunamadı"), "rule": rule, "href": kontrol_target(page, panel),
                    "where": where})
    return out


#: the meeting day's block (C5): the TCMB meetings' slots on OIS_MAIN (P10: MPC1), their implied step (R, bp), its band
#: (N), the scenarios' steps (U:W; names P3:P5, probabilities Q3:Q5); the survey's rows on Masa (Q157:Q159 dates, R the
#: survey's rate, U its step); DV01 Risk's PPK karar riski by meeting (C39:C62 dates, G TL/bp, J a 25 bp surprise);
#: USD · FOMC's table (B74:B83 dates; K İma O/N %, L the one before, O İma Δ, Q Fark WIRP, R:T the scenarios' steps -
#: their probabilities R72:T72 -, Z Piyasa − beklenen)
PPK_FIRST, PPK_LAST = 10, 89
SURVEY_ROWS = (157, 158, 159)
RISK_FIRST, RISK_LAST = 39, 62
FOMC_FIRST, FOMC_LAST = 74, 83
#: how far back the notes of an earlier day are looked for
NOTES_BACK = 10


def _num(v: Any) -> Optional[float]:
    """A finite number, or ``None``."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def _signal(v: Any) -> str:
    """DİBS RV's Sinyal cell as a state: "UCUZ", "PAHALI" or "" (none: "–", empty, an error)."""
    s = v.strip().upper() if isinstance(v, str) else ""
    return s if s in SIGNALS else ""


def zero_state(resid: Optional[float], threshold: Optional[float]) -> Optional[str]:
    """A bond's distance from the zero-coupon curve (bp, + cheap) as DİBS RV says a signal: beyond the threshold
    "UCUZ" / "PAHALI", else "" - ``None`` when either is not known."""
    if resid is None or threshold is None:
        return None
    return "UCUZ" if resid > threshold else ("PAHALI" if resid < -threshold else "")


def levels_of(v: Any) -> Optional[Dict[str, Any]]:
    """A trade's ``levels`` as ``/api/trades`` carries them (the Trades page's target / stop): its numbers, its unit and
    which one it is near - ``None`` when it carries none (or nothing of it can be read)."""
    if not isinstance(v, dict):
        return None
    near = v.get("near") if v.get("near") in ("target", "stop") else None
    out = {k: _num(v.get(k)) for k in ("target", "stop", "to_target", "to_stop")}
    out["unit"] = str(v.get("unit") or "")[:20]
    out["near"] = near
    if near is None and all(out[k] is None for k in ("target", "stop")):
        return None
    return out


class Bugun(object):
    """The page's data, read from what the service holds; the desk's close record of DİBS RV's signals."""

    def __init__(self, svc):
        self.svc = svc
        self.now: Callable[[], _dt.datetime] = _dt.datetime.now
        self._lock = threading.Lock()
        self._recorded: Optional[str] = None          # the day whose close record was taken (or found) last
        self._retry_after = 0.0                       # a record that failed is tried again after RETRY seconds

    # ------------------------------------------------------------------ the desk's days
    def close_time(self) -> _dt.time:
        """The desk's close (Trades' ``trades_close`` setting, 17:30)."""
        book = getattr(self.svc, "tradebook", None)
        try:
            return book.close_time() if book is not None else DEFAULT_CLOSE
        except Exception:  # noqa: BLE001
            return DEFAULT_CLOSE

    def business(self, day: _dt.date) -> bool:
        """A day the desk's market trades: a week day that is not one of its holidays."""
        if day.weekday() >= 5:
            return False
        ops = getattr(self.svc, "ops", None)
        if ops is None or not hasattr(ops, "market_day"):
            return True
        try:
            return bool(ops.market_day(day.isoformat()))
        except Exception:  # noqa: BLE001 - a week day then
            return True

    def previous_close(self, day: _dt.date) -> _dt.datetime:
        """The desk's close of the business day before ``day``."""
        d = day - _dt.timedelta(days=1)
        for _ in range(15):
            if self.business(d):
                break
            d -= _dt.timedelta(days=1)
        return _dt.datetime.combine(d, self.close_time())

    # ------------------------------------------------------------------ the page
    def view(self, user: Optional[str]) -> Dict[str, Any]:
        svc = self.svc
        user = svc.require_user(user)
        now = self.now()
        names = {u["name"]: u["display"] for u in svc.store.users()}
        try:
            eng: Dict[str, Any] = svc.et.call(self._read, user, now)
        except Exception as exc:  # noqa: BLE001 - the blocks that need it say so
            svc.ops.failure("Bugün · hesap tablosu", exc)
            eng = {"error": "okunamadı: %s" % (str(exc)[:200] or type(exc).__name__)}
        out: Dict[str, Any] = {"today": now.date().isoformat(), "time": now.strftime("%H:%M:%S"),
                               "close": self.close_time().strftime("%H:%M")}
        blocks: Tuple[Tuple[str, Callable[[], Dict[str, Any]]], ...] = (
            ("ret", lambda: self._ret(names, now)),
            ("kontrol", lambda: self._kontrol(user, eng, now)),
            ("trades", lambda: self._trades(user)),
            ("quant", self._quant),
            ("dibs", lambda: self._dibs(eng, now)),
            ("chat", lambda: self._chat(user)),
            ("agenda", lambda: self._agenda(user, eng, now)),
            ("meeting", lambda: self._meeting(eng, now)),
            ("moves", lambda: self._moves(user, eng, now)),
            ("notes", lambda: self._notes(names, now)))
        for name, fn in blocks:
            try:
                out[name] = fn()
            except Exception as exc:  # noqa: BLE001 - one block is not worth the page
                svc.ops.failure("Bugün · %s" % name, exc)
                out[name] = {"error": "okunamadı: %s" % (str(exc)[:200] or type(exc).__name__)}
        return out

    def _read(self, user: Optional[str] = None, now: Optional[_dt.datetime] = None) -> Dict[str, Any]:
        """Calculation thread, once a page: DİBS RV's signals (the desk's calculation), the meeting calendars, the TRY and
        USD holidays; Masa's Kontrol strip (the desk's calculation); a meeting of today or of the next business day as
        the user's calculation prices it; the moves since the close (Eğri Hareketi's points).  A part that cannot be read
        says why in its place (``{"error": ...}``)."""
        from . import meetings as mt
        svc = self.svc
        now = now or self.now()
        out: Dict[str, Any] = {"dibs": self._dibs_cells(), "tcmb": [], "fed": [], "holidays": {}}
        for key, cal in (("tcmb", mt.TCMB), ("fed", mt.FED)):
            b = svc.books.get(cal.book)
            if b is not None and cal.sheet in b.model.sheet_index:
                out[key] = sorted(d for d in mt.slot_dates(b, cal) if d)
        for ccy in ("TRY", "USD"):
            try:
                out["holidays"][ccy] = {x["date"]: x.get("name") or "" for x in svc._holiday_list(ccy)["items"]}
            except Exception:  # noqa: BLE001 - a currency without a list
                out["holidays"][ccy] = {}
        for key, fn in (("kontrol", self._kontrol_cells), ("meeting", lambda: self._meeting_cells(user, now)),
                        ("moves", lambda: self._moves_cells(user))):
            try:
                out[key] = fn()
            except Exception as exc:  # noqa: BLE001 - its block says so
                svc.ops.failure("Bugün · %s" % key, exc)
                out[key] = {"error": "okunamadı: %s" % (str(exc)[:200] or type(exc).__name__)}
        return out

    @staticmethod
    def _cell(calc, book, sheet: str, addr: str) -> Any:
        from .xl.model import COLS, parse_a1
        return calc.get(book.model.sheet_index[sheet], *divmod(parse_a1(addr), COLS))

    def _kontrol_cells(self) -> Optional[List[Dict[str, Any]]]:
        """Calculation thread: Masa's Kontrol strip in the desk's calculation (``None`` without the sheet)."""
        book = self.svc.books.get("tto")
        if book is None or KONTROL_SHEET not in book.model.sheet_index:
            return None
        calc = book.engine.shared
        return kontrol_read(lambda addr: self._cell(calc, book, KONTROL_SHEET, addr))

    def _next_business(self, day: _dt.date) -> _dt.date:
        d = day + _dt.timedelta(days=1)
        for _ in range(15):
            if self.business(d):
                break
            d += _dt.timedelta(days=1)
        return d

    def _meeting_cells(self, user: Optional[str], now: _dt.datetime) -> List[Dict[str, Any]]:
        """Calculation thread: the TCMB and Fed meetings of today or of the next business day (C5: the day before and
        the day of it), as the user's calculation prices them - the PPK's implied step, its band, the scenarios' steps,
        the survey, the user's position's risk of the decision; the FOMC's implied step (its share of a step), the
        difference to WIRP and to the expected step, the scenarios'."""
        from .xl.values import serial_to_date
        svc = self.svc
        today = now.date()
        when = {today.isoformat(): "today", self._next_business(today).isoformat(): "tomorrow"}
        out: List[Dict[str, Any]] = []

        def iso(v: Any) -> Optional[str]:
            return serial_to_date(v).isoformat() if isinstance(v, float) and v > 0 else None

        tto = svc.books.get("tto")
        if tto is not None and "OIS_MAIN" in tto.model.sheet_index:
            calc = svc._calc(user, tto) if user else tto.engine.shared

            def get(sheet: str, addr: str) -> Any:
                return self._cell(calc, tto, sheet, addr) if sheet in tto.model.sheet_index else None

            for r in range(PPK_FIRST, PPK_LAST + 1):
                day = iso(get("OIS_MAIN", "P%d" % r))
                if day not in when:
                    continue
                item: Dict[str, Any] = {"cal": "ppk", "name": "PPK", "date": day, "when": when[day], "slot": r - PPK_FIRST + 1,
                                        "implied": _num(get("OIS_MAIN", "R%d" % r)), "band": _num(get("OIS_MAIN", "N%d" % r))}
                scen = []
                for k, col in enumerate("XYZ"):
                    a, b = _num(get("OIS_MAIN", "%s%d" % (col, r - 1))), _num(get("OIS_MAIN", "%s%d" % (col, r)))
                    scen.append({"name": get("OIS_MAIN", "P%d" % (3 + k)) or "S%d" % (k + 1), "prob": _num(get("OIS_MAIN", "Q%d" % (3 + k))),
                                 "step": (b - a) * 10000.0 if a is not None and b is not None else None})
                item["scenarios"] = scen
                item["survey"] = None
                for sr in SURVEY_ROWS:
                    if iso(get("MASA", "Q%d" % sr)) == day:
                        item["survey"] = {"rate": _num(get("MASA", "R%d" % sr)), "step": _num(get("MASA", "U%d" % sr))}
                        break
                item["risk"] = None
                for rr in range(RISK_FIRST, RISK_LAST + 1):
                    if iso(get("DV01_RISK", "C%d" % rr)) == day:
                        item["risk"] = {"per_bp": _num(get("DV01_RISK", "G%d" % rr)), "pnl25": _num(get("DV01_RISK", "J%d" % rr))}
                        break
                out.append(item)
                break
        sofr = svc.books.get("sofr")
        if sofr is not None and "SOFR_FOMC" in sofr.model.sheet_index:
            calc = svc._calc(user, sofr) if user else sofr.engine.shared

            def fget(addr: str) -> Any:
                return self._cell(calc, sofr, "SOFR_FOMC", addr)

            for r in range(FOMC_FIRST, FOMC_LAST + 1):
                day = iso(fget("B%d" % r))
                if day not in when:
                    continue
                k_now, k_before = _num(fget("K%d" % r)), _num(fget("L%d" % r))
                out.append({"cal": "fomc", "name": "FOMC", "date": day, "when": when[day],
                            "implied": (k_now - k_before) * 100.0 if k_now is not None and k_before is not None else None,
                            "steps": _num(fget("N%d" % r)), "wirp": _num(fget("Q%d" % r)), "vs_expected": _num(fget("Z%d" % r)),
                            "scenarios": [{"name": name, "prob": _num(fget("%s72" % col)), "step": _num(fget("%s%d" % (col, r)))}
                                          for name, col in (("Baz", "R"), ("Şahin", "S"), ("Güvercin", "T"))]})
                break
        return out

    def _moves_cells(self, user: Optional[str]) -> Optional[Dict[str, Any]]:
        """Calculation thread: Eğri Hareketi's points against the previous close (``Watch.moves``)."""
        watch = getattr(self.svc, "watch", None)
        if watch is None:
            return None
        from .xl import numfmt
        return watch.moves(user or "", numfmt.get_locale(self.svc.settings.locale))

    def _dibs_cells(self) -> Optional[Dict[str, Any]]:
        """Calculation thread: each bond of the trading list (DİBS RV!A5:A54) with its Sinyal and Sinyal FX and their rich
        / cheap (AB, BH), and the threshold (P2) - in the desk's calculation; ``None`` without the sheet."""
        from . import rvfair
        from .xl.model import COLS, parse_a1
        book = self.svc.books.get("tto")
        if book is None or DIBS_SHEET not in book.model.sheet_index:
            return None
        si = book.model.sheet_index[DIBS_SHEET]
        calc = book.engine.shared

        def raw(c: str, r: int) -> Any:
            return calc.get(si, r, parse_a1("%s1" % c) % COLS)

        rows = []
        for r in range(rvfair.FIRST, rvfair.LAST + 1):
            code = rvfair.isin_of(raw("A", r))
            if not code:
                continue
            name = raw("C", r)
            rows.append({"isin": code, "name": name.strip() if isinstance(name, str) and not name.startswith("#") else "",
                         "ois": _signal(raw("AC", r)), "ois_v": _num(raw("AB", r)),
                         "fx": _signal(raw("BI", r)), "fx_v": _num(raw("BH", r))})
        return {"threshold": _num(raw("P", 2)), "rows": rows}

    # ------------------------------------------------------------------ RET
    def _ret(self, names: Dict[str, str], now: _dt.datetime) -> Dict[str, Any]:
        svc = self.svc
        if "tto" not in svc.books:
            return {"available": False}
        meta = svc.ret_meta() or {}
        at = str(meta.get("updated_at") or "") or None
        loaded = bool(at) and at[:10] == now.date().isoformat()
        fair = getattr(svc, "retfair", None)
        summary = fair.summary() if fair is not None else {}
        ups = [str(x) for x in summary.get("updates") or []]
        by = meta.get("updated_by")
        return {"available": True, "loaded": loaded, "at": at, "by": names.get(by, by) if by else None, "updates": ups,
                "checked": summary.get("at"), "tab": "fair" if ups else ("manual" if not loaded else None)}

    # ------------------------------------------------------------------ Trades
    def _trades(self, user: str) -> Dict[str, Any]:
        book = getattr(self.svc, "tradebook", None)
        if book is None:
            return {"available": False}
        tabs: Dict[str, Any] = {}
        rows: List[Dict[str, Any]] = []
        for scope in ("personal", "desk"):                  # (one's own first; nobody else's own ever: listing's rule)
            got = book.listing(user, scope)
            mtm = got.get("mtm") or None
            vals = (mtm or {}).get("values") or {}
            mine = [self._trade_row(it, scope, vals.get(str(it["id"])), mtm is not None) for it in got.get("open") or []]
            tabs[scope] = {"open": len(mine), "mtm_at": (mtm or {}).get("at"), "mtm_by": (mtm or {}).get("by_name"),
                           "stale": bool(mtm and mtm.get("stale")),
                           "day": self._sum(mine, "day"), "total": self._sum(mine, "total")}
            rows.extend(mine)
        near = [r for r in rows if r["levels"] and r["levels"]["near"]]
        near.sort(key=lambda r: (r["levels"]["near"] != "stop", r["id"]))      # (a stop first)
        return {"available": True, "tabs": tabs, "count": len(rows), "rows": rows[:LIST_MAX], "more": max(0, len(rows) - LIST_MAX),
                "near": near, "levels": any(r["levels"] for r in rows)}

    @staticmethod
    def _trade_row(it: Dict[str, Any], scope: str, v: Optional[Dict[str, Any]], valued: bool) -> Dict[str, Any]:
        per = (v or {}).get("periods") or {}

        def pnl(name: str, ccy: str) -> Optional[float]:
            return _num(((per.get(name) or {}).get("pnl") or {}).get(ccy))

        why = None
        if valued and v is None:
            why = "son MTM'den sonra girildi"
        elif v is not None and not v.get("ok"):
            why = v.get("why") or "değerlenemedi"
        elif v is not None and pnl("day", "try") is None:
            why = (per.get("day") or {}).get("why")
        return {"id": it["id"], "scope": scope, "text": it.get("text") or "", "product": it.get("product_text") or "",
                "who": it.get("created_by_name") if scope == "desk" else None, "trade_date": it.get("trade_date"),
                "day": pnl("day", "try"), "total": pnl("total", "try"), "day_usd": pnl("day", "usd"),
                "total_usd": pnl("total", "usd"), "why": why, "levels": levels_of(it.get("levels"))}

    @staticmethod
    def _sum(rows: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
        known = [r[key] for r in rows if r[key] is not None]
        return {"try": sum(known) if known else None, "missing": len(rows) - len(known)}

    # ------------------------------------------------------------------ quant
    def _quant(self) -> Dict[str, Any]:
        q = getattr(self.svc, "quant", None)
        if q is None:
            return {"available": False}
        v = q._view
        if v is None:
            return {"available": True, "ready": False,
                    "why": q.state.get("error") or "quant sonucu henüz yok (ilk hesap sürüyor)"}
        day = str(v.get("today") or self.svc.today_iso())
        since = self.previous_close(_dt.date.fromisoformat(day)).strftime("%Y-%m-%d %H:%M")
        live = {s["id"]: s for s in v.get("signals") or []}
        held = {s["id"]: s for s in v.get("gated") or []}
        seen: Dict[str, Optional[Dict[str, Any]]] = {}
        for e in q._log():
            if e.get("status") == "open" and "%s %s" % (e.get("day") or "", e.get("time") or "00:00") >= since:
                seen[e["sid"]] = e
        for s in live.values():                             # a daily line whose direction turned since the close ("YENİ")
            if s.get("new") and s["id"] not in seen:
                seen[s["id"]] = None
        lines = []
        for sid, e in seen.items():
            s = live.get(sid) or held.get(sid)
            if s is not None:
                lines.append(self._signal_line(s, e))
            elif e is not None:
                lines.append(self._log_line(e))
        lines.sort(key=lambda x: (x["exp_try"] is None, -(x["exp_try"] or 0.0), x["sid"]))
        return {"available": True, "ready": True, "day": day, "since": since, "at": v.get("at"), "count": len(lines),
                "lines": lines[:QUANT_TOP], "more": max(0, len(lines) - QUANT_TOP)}

    @staticmethod
    def _signal_line(s: Dict[str, Any], e: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """A live line as the desk reads it: the trade in its words, its side, size, entry / target / stop in the
        instrument's own price (FX: the forward of the holding; a level of the model's own: the traded instrument's -
        the FRA's rate -, the model's gap beside it in ``note``), R/R and the expected P&L."""
        from . import quantfam as qf
        px = s.get("px") or None
        quote = s.get("quote") or None
        mo = s.get("money") or {}
        info = s.get("info") or {}
        legs = s.get("legs") or []
        up = (s.get("direction") or 0) > 0
        if px is None and legs and legs[0].get("action"):
            side = SIDES.get(legs[0]["action"], str(legs[0]["action"]).upper())
        else:
            side = "AL" if up else "SAT"
        size = info.get("size") or None
        if size is None and px is not None and mo.get("base"):
            size = "1 mn %s" % mo["base"]
        if size is None and _num(mo.get("per_bp")) and _num(mo.get("dv01_usd")):
            size = "DV01 %s $" % qf._th(mo["dv01_usd"], 0)
        rr = _num(s.get("rr"))
        if rr is None and px is not None and _num(mo.get("target")) is not None and (_num(mo.get("stop")) or 0.0) < 0:
            rr = mo["target"] / -mo["stop"]
        try:
            exp_text = qf.exp_text(s)
        except Exception:  # noqa: BLE001 - the words are not worth the line
            exp_text = ""
        at = px if px is not None else (quote if quote is not None else s)
        return {"sid": s["id"], "family": s.get("family"), "model": info.get("model") or s.get("family_label") or "",
                "asset": s.get("asset") or "", "trade": s.get("line") or s.get("trade_tr") or s.get("expression") or "",
                "side": side, "up": up, "size": size, "entry": _num(at.get("entry")), "target": _num(at.get("target")),
                "stop": _num(at.get("stop")), "digits": int((px or quote or {}).get("digits") or s.get("digits") or 2),
                "unit": (px or quote or {}).get("label") or s.get("unit") or "", "rr": rr, "exp_try": _num(s.get("exp_try")),
                "note": qf.gaps_text(quote) if quote is not None else "",
                "exp_text": exp_text, "strength": s.get("strength") or "", "gated": s.get("gated") or "",
                "new": bool(s.get("new")), "day": (e or {}).get("day") or s.get("day"),
                "time": (e or {}).get("time") or s.get("time") or "", "page": s.get("page") or "quant", "listed": True}

    @staticmethod
    def _log_line(e: Dict[str, Any]) -> Dict[str, Any]:
        """A line written down since the close that is no longer in the list (its |z| fell back): as the log keeps it -
        a level of the model's own in the traded instrument's level it had then (``quote``), the gap beside it."""
        from . import quantfam as qf
        q = e.get("quote") if isinstance(e.get("quote"), dict) else None
        at = q if q is not None else {"entry": e.get("level"), "target": e.get("target"), "stop": e.get("stop"), "digits": e.get("digits")}
        lv, tg, st = _num(at.get("entry")), _num(at.get("target")), _num(at.get("stop"))
        rr = abs(tg - lv) / abs(st - lv) if lv is not None and tg is not None and st is not None and st != lv else None
        fam = qf.FAMILIES.get(e.get("family") or "")
        return {"sid": e["sid"], "family": e.get("family"), "model": e.get("family_label") or "", "asset": e.get("asset") or "",
                "trade": e.get("expression") or "", "side": "AL" if (e.get("dir") or 0) > 0 else "SAT", "up": (e.get("dir") or 0) > 0,
                "size": None, "entry": lv, "target": tg, "stop": st, "digits": int(at.get("digits") or 2),
                "unit": (q or {}).get("label") or e.get("unit") or "", "note": qf.gaps_text(q) if q is not None else "",
                "rr": rr, "exp_try": None, "exp_text": "", "strength": e.get("strength") or "", "gated": "", "new": bool(e.get("daily")),
                "day": e.get("day"), "time": e.get("time") or "", "page": fam[2] if fam else "quant", "listed": False}

    # ------------------------------------------------------------------ DİBS
    def closes(self) -> Dict[str, Dict[str, Any]]:
        v = self.svc.store.get(DIBS_KEY)
        return {k: x for k, x in v.items() if isinstance(x, dict)} if isinstance(v, dict) else {}

    def _zero(self) -> Tuple[Dict[str, Dict[str, Any]], str]:
        """The zero-coupon curve's rich / cheap of each bond (the quant fit's ``dibsfv`` monitors): now and at the last
        close of its history before the fit's day - and why there is none."""
        q = getattr(self.svc, "quant", None)
        fit = getattr(q, "_fit", None) if q is not None else None
        if not fit:
            return {}, "quant sonucu henüz yok"
        today = str(fit.get("today") or "")
        out: Dict[str, Dict[str, Any]] = {}
        for sid, m in (fit.get("mons") or {}).items():
            if not sid.startswith("dibsfv:"):
                continue
            prev = prev_day = None
            for d, x in zip(reversed(list(m.days or [])), reversed(list(m.values or []))):
                if str(d) < today and _num(x) is not None:
                    prev, prev_day = float(x), str(d)
                    break
            out[sid[7:]] = {"now": _num(getattr(m, "level", None)), "prev": prev, "prev_day": prev_day}
        return out, "" if out else "quant'ın DİBS adil değeri yok"

    def _dibs(self, eng: Dict[str, Any], now: _dt.datetime) -> Dict[str, Any]:
        if eng.get("error"):
            return {"error": eng["error"]}
        got = eng.get("dibs")
        if got is None:
            return {"available": False}
        today = now.date().isoformat()
        thr = got["threshold"]
        closes = self.closes()
        prev_day = max((d for d in closes if d < today), default=None)
        prev = (closes[prev_day].get("bonds") or {}) if prev_day else None
        zero, zero_why = self._zero()
        from . import bonds as bd
        rows = []
        for row in got["rows"]:
            isin = row["isin"]
            p = (prev or {}).get(isin) if prev is not None else None
            z = zero.get(isin) or {}
            known = bd.by_isin(isin)
            item = {"isin": isin, "label": bd.short_label(known) if known else (row["name"] or isin), "turned": []}
            for key in ("ois", "fx"):
                item[key] = {"now": row[key], "v": row[key + "_v"], "prev": p.get(key) if p is not None else None,
                             "prev_v": _num(p.get(key + "_v")) if p is not None else None, "known": p is not None}
                if p is not None and (p.get(key) or "") != row[key]:
                    item["turned"].append(key)
            zn, zp = zero_state(z.get("now"), thr), zero_state(z.get("prev"), thr)
            item["z"] = {"now": zn, "v": z.get("now"), "prev": zp, "prev_v": z.get("prev"), "known": zp is not None and zn is not None}
            if zp is not None and zn is not None and zp != zn:
                item["turned"].append("z")
            item["signal"] = any(item[k]["now"] in SIGNALS for k in ("ois", "fx", "z"))
            rows.append(item)
        z_prev = max((x["prev_day"] for x in zero.values() if x.get("prev_day")), default=None)
        turned = [r for r in rows if r["turned"]]
        # no record of the close: today's signals as they stand, "dünle kıyas yok"
        now_only = [r for r in rows if r["signal"] and not r["turned"]] if prev is None else []
        return {"available": True, "threshold": thr, "prev_day": prev_day, "z_prev_day": z_prev, "zero_why": zero_why,
                "compared": prev is not None, "count": len(rows), "turned": turned, "now": now_only,
                "first_record": None if closes else self.close_time().strftime("%H:%M")}

    def look(self, now: Optional[_dt.datetime] = None) -> Optional[Dict[str, Any]]:
        """One look of the desk's loop (tto/ops.py, every 15 s): the close record of DİBS RV's signals, once a business
        day at the desk's close (the first look after it that day) - the desk's calculation."""
        now = now or self.now()
        day = now.date()
        iso = day.isoformat()
        if now.time() < self.close_time() or self._recorded == iso or time.monotonic() < self._retry_after \
                or not self.business(day):
            return None
        with self._lock:
            closes = self.closes()
            if iso in closes:
                self._recorded = iso
                return None
            try:
                got = self.svc.et.call(self._dibs_cells)
            except Exception:
                self._retry_after = time.monotonic() + RETRY        # (said once by the loop; tried again later)
                raise
            if got is None:
                self._recorded = iso
                return None
            rec = {"at": now.strftime("%H:%M"), "threshold": got["threshold"],
                   "bonds": {r["isin"]: {k: r[k] for k in ("ois", "ois_v", "fx", "fx_v")} for r in got["rows"]}}
            closes[iso] = rec
            self.svc.store.put(DIBS_KEY, dict(sorted(closes.items())[-DIBS_KEEP:]))
            self._recorded = iso
            return rec

    # ------------------------------------------------------------------ the desk
    def _chat(self, user: str) -> Dict[str, Any]:
        rec = self.svc.broker_recon(user)
        miss = [x for x in rec.get("items") or [] if x.get("state") == "missing"]
        keep = ("product", "label", "price", "unit", "side", "party")
        return {"available": True, "date": rec.get("date"), "count": len(miss),
                "items": [{"id": x["id"], "time": str(x.get("time") or "")[:5], "source": x.get("source") or "",
                           "sender": x.get("sender") or "", "raw": x.get("raw") or "",
                           "q": {k: (x.get("q") or {}).get(k) for k in keep}} for x in miss[:LIST_MAX]],
                "more": max(0, len(miss) - LIST_MAX)}

    # ------------------------------------------------------------------ the morning meeting (28.11.2026)
    def _kontrol(self, user: str, eng: Dict[str, Any], now: _dt.datetime) -> Dict[str, Any]:
        """Masa's checks that are not "tamam" (A10: only those) and when the user last pasted their DV01 position (A8)."""
        from . import varrisk
        out: Dict[str, Any] = {"available": True, "dv01": varrisk.paste_stamp(self.svc.store, user, now.date().isoformat())}
        got = eng.get("kontrol") if not eng.get("error") else {"error": eng["error"]}
        if isinstance(got, dict) and got.get("error"):
            out["error_checks"] = got["error"]
            return out
        if got is None:
            out["checks"] = None
            return out
        chips = [c for c in got if c["col"] != "B"]
        out["checks"] = [c for c in chips if c["code"] != 0]
        out["ok"] = [c["name"] for c in chips if c["code"] == 0]
        out["overall"] = next((c for c in got if c["col"] == "B"), None)
        return out

    def _meeting(self, eng: Dict[str, Any], now: _dt.datetime) -> Dict[str, Any]:
        """A TCMB / Fed meeting today or on the next business day (C5) - the PPK's priced step against the last close of
        the PPK history (the solver's step of the latest day before today)."""
        if eng.get("error"):
            return {"error": eng["error"]}
        got = eng.get("meeting")
        if isinstance(got, dict) and got.get("error"):
            return {"error": got["error"]}
        items = [dict(x) for x in got or []]
        today = now.date().isoformat()
        for x in items:
            if x["cal"] != "ppk":
                continue
            x["prev"] = None
            start = (now.date() - _dt.timedelta(days=12)).isoformat()
            rows = [r for r in self.svc.store.mpc_values(start, (now.date() - _dt.timedelta(days=1)).isoformat(), [x["date"]])
                    if r.get("day", "") < today and _num(r.get("step")) is not None]
            if rows:
                last = max(rows, key=lambda r: r["day"])
                x["prev"] = {"day": last["day"], "step": float(last["step"])}
                if x.get("implied") is not None:
                    x["change"] = x["implied"] - float(last["step"])
        return {"available": True, "items": items}

    def _moves(self, user: str, eng: Dict[str, Any], now: _dt.datetime) -> Dict[str, Any]:
        """The moves since the previous close (A11) and the alarms that fired since then: the user's own and the desk's."""
        if eng.get("error"):
            return {"error": eng["error"]}
        got = eng.get("moves")
        if isinstance(got, dict) and got.get("error"):
            return {"error": got["error"]}
        out: Dict[str, Any] = dict(got or {}, available=got is not None)
        since = self.previous_close(now.date())
        out["since"] = since.strftime("%Y-%m-%d %H:%M")
        out["alarms"] = self._fired_since(user, since, now)
        return out

    def _fired_since(self, user: str, since: _dt.datetime, now: _dt.datetime) -> List[Dict[str, Any]]:
        """The alarms that fired from ``since`` (the previous close) to now: the user's own (``watch.fired:<day>``) and
        the desk's (``desk.alarmlog:<day>``), the latest first."""
        svc = self.svc
        watch, desk = getattr(svc, "watch", None), getattr(svc, "desk_alarms", None)
        out: List[Dict[str, Any]] = []
        day = since.date()
        while day <= now.date():
            iso = day.isoformat()
            stamp = since.strftime("%H:%M:%S") if day == since.date() else "00:00:00"
            for e in (watch.fired(iso) if watch is not None else []):
                if e.get("user") == user and str(e.get("time") or "") >= stamp:
                    out.append({"day": iso, "time": str(e.get("time") or "")[:5], "label": e.get("label") or "",
                                "text": e.get("condition") or "", "value": e.get("value_text") or "", "desk": False})
            for e in (desk.log(iso) if desk is not None else []):
                if e.get("kind") == "fired" and str(e.get("at") or "") >= stamp:
                    out.append({"day": iso, "time": str(e.get("at") or "")[:5], "label": e.get("label") or "",
                                "text": e.get("condition") or "", "value": e.get("value_text") or "", "desk": True})
            day += _dt.timedelta(days=1)
        out.sort(key=lambda x: (x["day"], x["time"]), reverse=True)
        return out[:LIST_MAX]

    def _notes(self, names: Dict[str, str], now: _dt.datetime) -> Dict[str, Any]:
        """The desk's notes of the day (A11: typed in place on Bugün) and the last earlier day's."""
        store = self.svc.store

        def read(day: _dt.date) -> Optional[Dict[str, Any]]:
            v = store.get("desk.notes:%s" % day.isoformat(), None)
            if not isinstance(v, dict) or not str(v.get("text") or "").strip():
                return None
            by = v.get("by")
            return {"day": day.isoformat(), "text": str(v.get("text") or ""), "by": names.get(by, by) if by else None,
                    "at": v.get("at")}

        today = now.date()
        prev = None
        for back in range(1, NOTES_BACK + 1):
            prev = read(today - _dt.timedelta(days=back))
            if prev is not None:
                break
        return {"available": True, "today": read(today) or {"day": today.isoformat(), "text": "", "by": None, "at": None},
                "prev": prev}

    def _agenda(self, user: str, eng: Dict[str, Any], now: _dt.datetime) -> Dict[str, Any]:
        svc = self.svc
        today = now.date()
        iso = today.isoformat()
        got = svc.desk.agenda(user)
        keep = ("day", "time", "text", "deadline", "shared", "done", "by", "repeat")
        items = [{k: it.get(k) for k in keep} for it in got.get("items") or [] if it.get("day") == iso]
        late = [{k: it.get(k) for k in keep} for it in got.get("items") or []
                if (it.get("day") or "") < iso and it.get("deadline") and not it.get("done")]
        out: Dict[str, Any] = {"available": True, "items": items[:LIST_MAX], "late": late[:LIST_MAX], "count": len(items)}
        if eng.get("error"):
            out["calendar_error"] = eng["error"]
            return out
        archive: List[str] = []
        hist = getattr(svc, "history", None)
        if hist is not None:
            try:
                archive = hist.archive()
            except Exception:  # noqa: BLE001 - the list alone
                archive = []
        meetings = {}
        for key, days in (("ppk", sorted(set(eng.get("tcmb") or []) | set(archive))), ("fomc", eng.get("fed") or [])):
            nxt = next((d for d in days if d > iso), None)
            meetings[key] = {"today": iso in days, "next": nxt,
                             "days": (_dt.date.fromisoformat(nxt) - today).days if nxt else None, "known": bool(days)}
        out["meetings"] = meetings
        nxt_day = today + _dt.timedelta(days=1)
        while nxt_day.weekday() >= 5:
            nxt_day += _dt.timedelta(days=1)
        hols = []
        for d, when in ((iso, "today"), (nxt_day.isoformat(), "next")):
            for ccy in ("TRY", "USD"):
                names = (eng.get("holidays") or {}).get(ccy) or {}
                if d in names:
                    hols.append({"day": d, "when": when, "ccy": ccy, "name": names[d]})
        out["holidays"] = hols
        return out
