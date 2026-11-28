"""Kotasyon defteri - the quotes given to clients, and how many of them were done (28.11.2026).

The desk (28.11.2026), of the forward card on Fiyatlama: "Fiyatladiktan sonra bunu done diye gunluk islemlere
alabilmeliyim veya done olmadiysa da hit ratiosunu takip edebilmeliyim"; and of the list of new features, C2 - "Kotasyon
defteri, 'Done' işleme çevirir" (the desk's "C - 2-3-4-5-8-10-12-13-16").

* **What is logged.** Every quote copied for a client: a table's "Kotasyon kopyala" (one row or the whole table:
  ``Service.client_quote`` logs it, so a table that opts in to it later is logged with no code of its own) and Fiyatlama's
  forward card.  A record: the day, who, when, the product ("FX forward", "TRY OIS" …), the instrument as the quote's
  heading names it, the pair, the side, the levels (bid / ask / mid, what they are and how they read), where it came from
  (``source``: "Kotasyon kopyala", "Fiyatlama · forward kartı"), the page, the amount, the value date, the client (typed
  by the trader, optional) and the text sent.  Nothing is priced here: the levels are what the quote said.
* **Its status**: ``open`` when given, then ``done`` (the client dealt - the trade goes into Günlük İşlemler, ``trade_id``
  once it is there) or ``not_done``; any of them can be set again (a mistake undone).  The whole desk's log: everyone
  sees every quote, with who gave it.
* **The hit ratio**: done / (done + not done) - a quote still open counts in neither -, by client and by product over a
  period (``hit``).

The store keeps the records (``Store.add_quote_log`` …, table ``quote_log``); the service's endpoints are ``POST
/api/quote-log`` (a quote), ``POST /api/quote-log/{id}`` (its status, trade, client), ``GET /api/quote-log?from=&to=``
(the quotes and the hit ratio).  The browser's component is ``tto/static/js/quotelog.js`` (``mountQuoteLog``).
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import quotes as qt
from .inputs import parse_amount, parse_date
from .xl.values import serial_to_date

STATUSES = ("open", "done", "not_done")
STATUS_TEXT = {"open": "Açık", "done": "Done", "not_done": "Done değil"}
#: a client not named: one group of the hit ratio
NO_CLIENT = "(müşteri yazılmadı)"
#: the longest period asked for at once (days)
MAX_DAYS = 400
#: the lengths a record keeps
LIMITS = {"product": 40, "instrument": 120, "pair": 20, "side": 20, "source": 60, "client": 60, "page": 40, "panel": 20,
          "note": 200, "unit": 20, "text": 4000, "kind": 20}
#: the levels a quote may give, in the order a table's quote is read for its record (the first one it has)
LEVEL_FIELDS = (("outright", "kur"), ("try", "%"), ("points", "puan"))


class QuoteLogError(ValueError):
    """What the log says of a request it cannot take (Turkish)."""


def _text(v: Any, key: str) -> str:
    return " ".join(str(v if v is not None else "").split())[:LIMITS[key]]


def _number(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v and abs(v) != float("inf") else None
    if isinstance(v, str) and v.strip():
        x = parse_amount(v.strip())
        return float(x) if x is not None else None
    return None


def _day(v: Any) -> Optional[str]:
    """A date as the record keeps it (ISO): an Excel serial, an ISO day or a day typed (31.12.2026)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 20000 < v < 80000:
        return serial_to_date(float(v)).isoformat()
    if isinstance(v, str) and v.strip():
        s = v.strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return s
        x = parse_date(s)
        return serial_to_date(x).isoformat() if x is not None else None
    return None


def levels_of(raw: Any) -> Dict[str, Any]:
    """The levels of a quote as kept: ``{bid, ask, mid, unit, kind, text}`` (numbers or ``None``)."""
    src = raw if isinstance(raw, dict) else {}
    out: Dict[str, Any] = {k: _number(src.get(k)) for k in ("bid", "ask", "mid")}
    if out["mid"] is None and out["bid"] is not None and out["ask"] is not None:
        out["mid"] = (out["bid"] + out["ask"]) / 2.0
    for k in ("unit", "kind", "text"):
        if src.get(k) not in (None, ""):
            out[k] = _text(src[k], k)
    return out


def clean_new(payload: Any) -> Tuple[Dict[str, Any], str]:
    """A quote to log as the browser sends it (``POST /api/quote-log``): ``(record, status)``.  ``product`` and
    ``instrument`` are required; ``status`` "open" unless "done" / "not_done" is said (a quote dealt on the spot)."""
    if not isinstance(payload, dict):
        raise QuoteLogError("kota okunamadı")
    rec: Dict[str, Any] = {}
    for key in ("product", "instrument", "pair", "side", "source", "client", "page", "panel", "note", "text"):
        if payload.get(key) not in (None, ""):
            rec[key] = _text(payload[key], key) if key != "text" else str(payload[key])[:LIMITS["text"]]
    if not rec.get("product"):
        raise QuoteLogError("ürün yazılmalı (FX forward, TRY OIS …)")
    if not rec.get("instrument"):
        raise QuoteLogError("enstrüman yazılmalı")
    rec.setdefault("source", "elle")
    rec["levels"] = levels_of(payload.get("levels"))
    size = _number(payload.get("size"))
    if size is not None:
        rec["size"] = size
    day = _day(payload.get("value_date"))
    if day is not None:
        rec["value_date"] = day
    status = str(payload.get("status") or "open")
    if status not in STATUSES:
        raise QuoteLogError("durum open, done ya da not_done olmalı")
    trade = payload.get("trade_id")
    if trade is not None:
        rec["trade_id"] = _trade_id(trade)
    return rec, status


def _trade_id(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise QuoteLogError("işlem numarası okunamadı: %r" % (v,))
    if n <= 0 or isinstance(v, bool):
        raise QuoteLogError("işlem numarası okunamadı: %r" % (v,))
    return n


def clean_update(payload: Any) -> Tuple[Optional[str], Dict[str, Any]]:
    """What ``POST /api/quote-log/{id}`` changes: ``(status or None, fields)`` - the status ("done" / "not_done" /
    "open"), the trade it became (``trade_id``; ``null`` takes it out) and the client."""
    if not isinstance(payload, dict):
        raise QuoteLogError("istek okunamadı")
    status = payload.get("status")
    if status is not None and status not in STATUSES:
        raise QuoteLogError("durum open, done ya da not_done olmalı")
    fields: Dict[str, Any] = {}
    if "trade_id" in payload:
        fields["trade_id"] = None if payload["trade_id"] in (None, "") else _trade_id(payload["trade_id"])
    if "client" in payload:
        fields["client"] = _text(payload["client"], "client") or None
    if "note" in payload:
        fields["note"] = _text(payload["note"], "note") or None
    if status is None and not fields:
        raise QuoteLogError("değişecek bir şey yok (durum, işlem no ya da müşteri)")
    return status, fields


def period(frm: Any, to: Any, today: str) -> Tuple[str, str]:
    """The days asked for (ISO, both included): ``from`` … ``to``, each a day typed or ISO; none: today; one: that day
    alone.  At most :data:`MAX_DAYS` days."""
    first = _day(frm) if frm not in (None, "") else None
    last = _day(to) if to not in (None, "") else None
    if frm not in (None, "") and first is None:
        raise QuoteLogError("başlangıç günü okunamadı: %r" % (frm,))
    if to not in (None, "") and last is None:
        raise QuoteLogError("bitiş günü okunamadı: %r" % (to,))
    first = first or last or today
    last = last or (today if frm not in (None, "") else first)
    if last < first:
        first, last = last, first
    span = (_dt.date.fromisoformat(last) - _dt.date.fromisoformat(first)).days
    if span > MAX_DAYS:
        raise QuoteLogError("en çok %d günlük dönem sorulabilir" % MAX_DAYS)
    return first, last


# ---------------------------------------------------------------------------------------------- the hit ratio
def _count(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    n = {s: 0 for s in STATUSES}
    unbooked = 0
    for q in rows:
        n[q.get("status") if q.get("status") in STATUSES else "open"] += 1
        if q.get("status") == "done" and not q.get("trade_id"):
            unbooked += 1
    decided = n["done"] + n["not_done"]
    return {"quotes": len(rows), "done": n["done"], "not_done": n["not_done"], "open": n["open"],
            "ratio": (n["done"] / float(decided)) if decided else None, "unbooked": unbooked}


def hit(quotes: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The hit ratio - done / (done + not done) - by client, by product and for all: per group its quotes, done, not
    done, still open, the ratio (``None`` while nothing is decided) and the done ones not booked yet (no trade number)."""
    def by(key: Callable[[Dict[str, Any]], str]) -> List[Dict[str, Any]]:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for q in quotes:
            groups.setdefault(key(q), []).append(q)
        out = [dict(_count(rows), key=k) for k, rows in groups.items()]
        out.sort(key=lambda g: (-g["quotes"], g["key"]))
        return out

    return {"by_client": by(lambda q: q.get("client") or NO_CLIENT), "by_product": by(lambda q: q.get("product") or "?"),
            "all": _count(quotes)}


# ---------------------------------------------------------------------------------------------- a table's quote
#: "Sheet!A1" -> (the cell's value, its number format): what Service.client_quote reads with
Reader = Callable[[str], Tuple[Any, str]]


def _sources(f: Dict[str, Any]) -> List[Any]:
    return list(f["src"]) if isinstance(f["src"], list) else [f["src"]]


def _read(read: Reader, src: Any, sheet: str, row: Optional[int]) -> Tuple[Any, str]:
    ref = qt.ref_of(src, sheet, row)
    return read(ref) if ref else (None, "General")


def from_table(spec: Dict[str, Any], read: Reader, sheet: str, row: Optional[int], part: Optional[int], text: str,
               where: Dict[str, str]) -> Dict[str, Any]:
    """The record of a table's "Kotasyon kopyala" (``spec``: its ``client_quote``; ``row`` / ``part`` as the copy was
    asked; ``text``: what was copied; ``where``: the page / panel and their titles).  One quote - a row, a part, a table
    that is one quote - gives its levels (the first of outright, TRY rate, points it has: bid / ask, or one value), its
    pair, side, value date and amount; a whole table (or both parts) is one record without levels - its text says what
    was sent."""
    heading = (text or "").split("\n", 1)[0]
    instrument = heading.split(" · ")[0].strip() or where.get("panel_title") or where.get("panel") or "kota"
    rec: Dict[str, Any] = {"instrument": instrument, "source": "Kotasyon kopyala", "page": where.get("page", ""),
                           "panel": where.get("panel", ""), "text": text}
    one: Optional[Dict[str, Any]] = None
    if spec.get("parts"):
        if part is not None:
            one = qt.parts(spec)[part]
    elif qt.table_rows(spec) is None or row is not None:
        one = spec
    pair_spec = (one or spec).get("pair")
    pair = ""
    if isinstance(pair_spec, str):
        pair = pair_spec
    elif isinstance(pair_spec, dict) and (row is not None or not qt.is_column(pair_spec.get("src"))):
        v, _ = _read(read, pair_spec.get("src"), sheet, row)
        pair = v.strip().upper() if isinstance(v, str) else ""
    if pair:
        rec["pair"] = pair[:LIMITS["pair"]]
    named = spec.get("product") or (one or {}).get("product")
    if named:
        rec["product"] = _text(named, "product")
    elif "VİOP" in pair.upper() or "VIOP" in pair.upper():
        rec["product"] = "VİOP"
    elif pair:
        rec["product"] = "FX forward"
    else:
        rec["product"] = _text(spec.get("title") or where.get("panel_title") or "kota", "product")
    if one is None:
        rec["levels"] = levels_of(None)
        rec["lines"] = max(0, len([x for x in (text or "").split("\n") if x.strip()]) - 1)
        return rec
    lv: Dict[str, Any] = levels_of(None)
    for key, unit in LEVEL_FIELDS:
        f = qt.field(one, key)
        if not f:
            continue
        got = [_read(read, s, sheet, row) for s in _sources(f)]
        nums = [v if type(v) is float and v == v else None for v, _ in got]
        if not any(x is not None for x in nums):
            continue
        shown = [qt.number_text(v, fmt, "tr") for v, fmt in got]
        if len(nums) == 2:
            lv = levels_of({"bid": nums[0], "ask": nums[1], "unit": unit, "kind": key, "text": " / ".join(t or "–" for t in shown)})
        else:
            lv = levels_of({"mid": nums[0], "unit": unit, "kind": key, "text": shown[0]})
        break
    rec["levels"] = lv
    for key, dest in (("end", "value_date"), ("side", "side"), ("amount", "size")):
        f = qt.field(one, key)
        if not f:
            continue
        v, _ = _read(read, _sources(f)[0], sheet, row)
        if dest == "value_date":
            day = _day(v)
            if day:
                rec[dest] = day
        elif dest == "side":
            if isinstance(v, str) and v.strip():
                rec[dest] = _text(v, "side")
        elif type(v) is float and v == v:
            rec[dest] = v
    return rec
