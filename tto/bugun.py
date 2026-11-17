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
  the instrument, the side, the size, entry / target / stop and R/R.
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
            eng: Dict[str, Any] = svc.et.call(self._read)
        except Exception as exc:  # noqa: BLE001 - the blocks that need it say so
            svc.ops.failure("Bugün · hesap tablosu", exc)
            eng = {"error": "okunamadı: %s" % (str(exc)[:200] or type(exc).__name__)}
        out: Dict[str, Any] = {"today": now.date().isoformat(), "time": now.strftime("%H:%M:%S"),
                               "close": self.close_time().strftime("%H:%M")}
        blocks: Tuple[Tuple[str, Callable[[], Dict[str, Any]]], ...] = (
            ("ret", lambda: self._ret(names, now)),
            ("trades", lambda: self._trades(user)),
            ("quant", self._quant),
            ("dibs", lambda: self._dibs(eng, now)),
            ("chat", lambda: self._chat(user)),
            ("agenda", lambda: self._agenda(user, eng, now)))
        for name, fn in blocks:
            try:
                out[name] = fn()
            except Exception as exc:  # noqa: BLE001 - one block is not worth the page
                svc.ops.failure("Bugün · %s" % name, exc)
                out[name] = {"error": "okunamadı: %s" % (str(exc)[:200] or type(exc).__name__)}
        return out

    def _read(self) -> Dict[str, Any]:
        """Calculation thread, once a page: DİBS RV's signals (the desk's calculation), the meeting calendars, the TRY and
        USD holidays."""
        from . import meetings as mt
        svc = self.svc
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
        return out

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
        instrument's own price (FX: the forward of the holding), R/R and the expected P&L."""
        from . import quantfam as qf
        px = s.get("px") or None
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
        at = px if px is not None else s
        return {"sid": s["id"], "family": s.get("family"), "model": info.get("model") or s.get("family_label") or "",
                "asset": s.get("asset") or "", "trade": s.get("line") or s.get("trade_tr") or s.get("expression") or "",
                "side": side, "up": up, "size": size, "entry": _num(at.get("entry")), "target": _num(at.get("target")),
                "stop": _num(at.get("stop")), "digits": int((px or {}).get("digits") or s.get("digits") or 2),
                "unit": (px or {}).get("label") or s.get("unit") or "", "rr": rr, "exp_try": _num(s.get("exp_try")),
                "exp_text": exp_text, "strength": s.get("strength") or "", "gated": s.get("gated") or "",
                "new": bool(s.get("new")), "day": (e or {}).get("day") or s.get("day"),
                "time": (e or {}).get("time") or s.get("time") or "", "page": s.get("page") or "quant", "listed": True}

    @staticmethod
    def _log_line(e: Dict[str, Any]) -> Dict[str, Any]:
        """A line written down since the close that is no longer in the list (its |z| fell back): as the log keeps it."""
        from . import quantfam as qf
        lv, tg, st = _num(e.get("level")), _num(e.get("target")), _num(e.get("stop"))
        rr = abs(tg - lv) / abs(st - lv) if lv is not None and tg is not None and st is not None and st != lv else None
        fam = qf.FAMILIES.get(e.get("family") or "")
        return {"sid": e["sid"], "family": e.get("family"), "model": e.get("family_label") or "", "asset": e.get("asset") or "",
                "trade": e.get("expression") or "", "side": "AL" if (e.get("dir") or 0) > 0 else "SAT", "up": (e.get("dir") or 0) > 0,
                "size": None, "entry": lv, "target": tg, "stop": st, "digits": int(e.get("digits") or 2), "unit": e.get("unit") or "",
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
