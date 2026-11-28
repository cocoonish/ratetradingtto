"""Günlük İşlemler's entry form, filled from elsewhere: saved templates ("Şablonlar") and rows pasted from Excel
("Excel'den yapıştır") - TOPLU FORWARD FİYATLAMA's rows too ("İşleme al": :func:`bulk_forward_paste`).

Nothing here prices or keeps a trade.  A template is the form's own spec - the shape ``ctx.openTrade`` fills the form
with (``blotter.js``: ``fillForm``) - checked so that it only ever holds what the form takes.  A pasted row becomes the
payload the form would send (``/api/blotter/forward``, ``/ois``, ``/bond``): the service prices it with the form's own
checks and keeps the rows that pass, all of them in one transaction (``Service.bulk_save``).
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Dict, List, Optional, Tuple

from . import blotter as bl
from .extras import BULK_EUR_PPD, BULK_SPREAD, BULK_USD_PPD
from .inputs import parse_amount


class EntryError(ValueError):
    pass


_TR_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u"})


def fold(text: Any) -> str:
    """Text compared without case, Turkish letters or punctuation: "Valör" is "valor", "DV01 ($)" "dv01",
    "Karşı taraf" "karsi taraf"."""
    s = str(text or "").casefold().replace("̇", "").translate(_TR_FOLD)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


# ---------------------------------------------------------------------------------------------- the form's words
FWD_DIRS = {"b": "B", "buy": "B", "al": "B", "alis": "B", "alim": "B", "bought": "B",
            "s": "S", "sell": "S", "sat": "S", "satis": "S", "sold": "S"}
#: an OIS side as the workbook's own list writes it (B pays the fixed rate, S receives it) or as the desk says it
OIS_SIDES_WORDS = {"pay": "PAY", "p": "PAY", "payer": "PAY", "paid": "PAY", "b": "PAY", "ode": "PAY",
                   "receive": "RECEIVE", "rec": "RECEIVE", "r": "RECEIVE", "receiver": "RECEIVE", "received": "RECEIVE",
                   "s": "RECEIVE"}
BASES = {"ret bid": "RET_BID", "ret mid": "RET_MID", "ret ask": "RET_ASK", "try": "TRY", "try faizi": "TRY", "faiz": "TRY",
         "try rate": "TRY", "fwd": "FWD", "forward": "FWD", "forward kur": "FWD", "kur": "FWD", "outright": "FWD",
         "sp": "SP", "swap puani": "SP", "puan": "SP", "swap points": "SP", "points": "SP"}
BASIS_LABEL = {"RET_BID": "RET bid", "RET_MID": "RET mid", "RET_ASK": "RET ask", "TRY": "TRY faizi", "FWD": "Forward kur",
               "SP": "Swap puanı"}
STRATEGIES = ("outright", "spread", "fly", "fra", "mpc", "mpcspread")
OIS_SIDES = {"outright": ("PAY", "RECEIVE"), "fra": ("PAY", "RECEIVE"), "mpc": ("PAY", "RECEIVE"),
             "spread": ("STEEPENER", "FLATTENER"), "fly": ("REC GÖVDE", "PAY GÖVDE"), "mpcspread": bl.MPC_SPREAD_SIDES}
OIS_LEGS = {"outright": 1, "spread": 2, "fly": 3}


def _word(text: Any, words: Dict[str, str], what: str) -> str:
    got = words.get(fold(text))
    if got is None:
        raise EntryError(what % (text,))
    return got


# ---------------------------------------------------------------------------------------------- templates
TEMPLATE_KINDS = ("fwd", "ois", "bond")
#: what of a form a template keeps as it was typed, and how long it may be
_SPEC_TEXT = {"fwd": {"amount": 30, "quote_amount": 30, "date": 30, "value": 30, "spot": 30, "code": 7, "cpt": 40, "note": 200},
              "ois": {"level": 30, "size": 30, "cpt": 40, "note": 200},
              "bond": {"instrument": 60, "amount": 30, "price": 30, "note": 200}}


def _amount_text(text: str, what: str) -> None:
    # (typed in the user's own number format: either reading will do - the form reads it again when it is filled)
    if not any((parse_amount(text, lang) or 0) > 0 for lang in ("tr", "en")):
        raise EntryError("%s anlaşılamadı: %r (örn. 10m ya da 10.000.000)" % (what, text))


def _int_list(v: Any, n: int, what: str) -> List[int]:
    if not isinstance(v, (list, tuple)) or len(v) != n or not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                                 and float(x) == int(x) for x in v):
        raise EntryError("%s anlaşılamadı" % what)
    return [int(x) for x in v]


def clean_spec(kind: str, spec: Any) -> Dict[str, Any]:
    """A template's spec as it is kept: the form's fields the user chose to keep ("any subset"), checked - the product
    (``kind``) and, of a forward, ``pair`` (USDTRY, EURTRY, GBPTRY ...), ``dir`` (B / S), ``amount`` *or*
    ``quote_amount`` (as typed: "10m"; the latter in the pair's second currency), ``date`` (a date or a tenor: "3M"),
    ``basis``, ``value`` (the rate / outright / points of that basis), ``spot``; of an OIS ``strategy``, ``side``,
    ``tenors`` (outright 1, spread 2, fly 3), ``months`` (FRA: start, end), ``mpc`` (start, end as places in the list
    of meetings - 0 the spot, k the k-th meeting: the template follows the meetings as they pass; a meeting spread's
    start, mid and end), ``level``, ``size``
    with ``sizeMode`` (dv01 / nominal); of a bond ``dir``, ``instrument``, ``amount``, ``price``; of each ``cpt`` and
    ``note``.  Anything else is left out; a template with nothing in it is refused."""
    if kind not in TEMPLATE_KINDS:
        raise EntryError("bilinmeyen ürün: %r" % (kind,))
    if not isinstance(spec, dict):
        raise EntryError("şablonun içeriği gerekli")
    out: Dict[str, Any] = {"kind": kind}
    for key, longest in _SPEC_TEXT[kind].items():
        v = spec.get(key)
        if v is None or isinstance(v, bool):
            continue
        if not isinstance(v, (str, int, float)):
            raise EntryError("%s anlaşılamadı" % key)
        v = str(v).strip()
        if len(v) > longest:
            raise EntryError("%s en fazla %d karakter olabilir" % (key, longest))
        if v:
            out[key] = v
    if kind in ("fwd", "bond") and spec.get("dir"):
        if spec["dir"] not in ("B", "S"):
            raise EntryError("yön B ya da S olmalı")
        out["dir"] = spec["dir"]
    if kind == "fwd":
        if spec.get("pair"):
            try:
                out["pair"] = bl.pair_of(spec["pair"])
            except bl.TradeError as exc:
                raise EntryError(str(exc))
        if spec.get("basis"):
            if spec["basis"] not in bl.FWD_BASES:
                raise EntryError("bilinmeyen fiyatlama: %r" % (spec["basis"],))
            out["basis"] = spec["basis"]
        if "amount" in out and "quote_amount" in out:
            raise EntryError("tutar ya dövizde ya karşı parada yazılır: ikisinden biri")
        for key, what in (("amount", "tutar"), ("quote_amount", "karşı tutar")):
            if key in out:
                _amount_text(out[key], what)
    elif kind == "ois":
        strategy = spec.get("strategy") or "outright"
        if strategy not in STRATEGIES:
            raise EntryError("bilinmeyen strateji: %r" % (strategy,))
        out["strategy"] = strategy
        if spec.get("side"):
            if spec["side"] not in OIS_SIDES[strategy]:
                raise EntryError("%s için yön %s olmalı" % (strategy, " ya da ".join(OIS_SIDES[strategy])))
            out["side"] = spec["side"]
        if spec.get("tenors") is not None and strategy in OIS_LEGS:
            tenors = spec["tenors"]
            if not isinstance(tenors, (list, tuple)) or len(tenors) != OIS_LEGS[strategy] or any(t not in bl.OIS_TENORS for t in tenors):
                raise EntryError("vadeler anlaşılamadı: %r" % (tenors,))
            out["tenors"] = list(tenors)
        if spec.get("months") is not None and strategy == "fra":
            m1, m2 = _int_list(spec["months"], 2, "FRA ayları")
            if m1 < 0 or m2 <= m1 or m1 % 3 or m2 % 3 or m2 > 120:
                raise EntryError("FRA ayları 3'ün katı olmalı (0 ≤ başlangıç < bitiş ≤ 120)")
            out["months"] = [m1, m2]
        if spec.get("mpc") is not None and strategy == "mpc":
            k1, k2 = _int_list(spec["mpc"], 2, "MPC toplantıları")
            if k1 < 0 or k2 <= k1:
                raise EntryError("MPC: bitiş başlangıçtan sonraki bir toplantı olmalı")
            out["mpc"] = [k1, k2]
        if spec.get("mpc") is not None and strategy == "mpcspread":
            k1, k2, k3 = _int_list(spec["mpc"], 3, "MPC toplantıları")
            if k1 < 0 or not k1 < k2 < k3:
                raise EntryError("MPC spread: toplantılar sırayla olmalı (başlangıç < orta < bitiş)")
            out["mpc"] = [k1, k2, k3]
        if "size" in out:
            mode = spec.get("sizeMode") or "dv01"
            if mode not in ("dv01", "nominal"):
                raise EntryError("büyüklük DV01 ya da nominal olmalı")
            _amount_text(out["size"], "büyüklük")
            out["sizeMode"] = mode
    else:
        if "amount" in out:
            _amount_text(out["amount"].lstrip("+-−"), "tutar")
    if len(out) == 1:
        raise EntryError("şablon boş: en az bir alan seçin")
    return out


# ---------------------------------------------------------------------------------------------- pasted rows
#: the fields a pasted column can be, per product, in the order the mapping offers them
FIELDS = {
    "fwd": [("pair", "Parite"), ("dir", "Yön"), ("amount", "Tutar (döviz)"), ("quote_amount", "Karşı tutar"),
            ("value_date", "Valör"), ("basis", "Fiyatlama"), ("try_rate", "TRY faizi"), ("forward", "Forward kur"),
            ("points", "Swap puanı"), ("spot", "Spot"), ("cpt", "Karşı taraf"), ("note", "Not")],
    "ois": [("side", "Yön"), ("tenor", "Vade"), ("start", "Başlangıç (MPC)"), ("end", "Bitiş (MPC)"), ("level", "Oran (%)"),
            ("dv01", "DV01 ($/bp)"), ("nominal", "Nominal (TL)"), ("cpt", "Karşı taraf"), ("note", "Not")],
    "bond": [("instrument", "Enstrüman"), ("dir", "Yön"), ("amount", "Tutar"), ("price", "Fiyat"), ("note", "Not")],
}
KIND_LABEL = {"fwd": "FX Forward", "ois": "OIS", "bond": "Tahvil"}
#: without a header row the columns are read in the order of the workbook's own lists on its "Günlük İşlemler" sheet
DEFAULT_ORDER = {"fwd": ["dir", "amount", "try_rate", "value_date"],                 # A:D   Yön · Tutar · Faiz · Valör
                 "ois": ["nominal", "dv01", "side", "level", "tenor", "cpt"],         # H:M   Nominal · DV01 USD · Yön · Faiz · Valör · CPT
                 "bond": ["instrument", "amount", "price"]}                           # Y:AA  Enstrüman · Tutar · Fiyat
#: what a header says, folded (:func:`fold`): the workbook's own captions, the dashboard's lists and the usual English
_HEADERS = {
    "fwd": {
        "pair": ("parite", "pair", "ccy", "ccy pair", "currency", "currency pair", "doviz", "para birimi", "cross"),
        "dir": ("yon", "side", "dir", "direction", "b s", "al sat", "alis satis", "buy sell", "yon b s"),
        "amount": ("tutar", "amount", "nominal", "notional", "miktar", "doviz tutari", "tutar doviz", "tutar dvz"),
        "quote_amount": ("karsi tutar", "counter amount", "quote amount", "contra amount", "karsi para tutari"),
        "value_date": ("valor", "valor tarihi", "value date", "vade tarihi", "vade", "tarih", "maturity", "settlement",
                       "settlement date", "date", "value"),
        "basis": ("fiyatlama", "pricing", "basis", "fiyat tipi", "fiyatlama tipi"),
        "try_rate": ("faiz", "try faizi", "try faiz", "try rate", "oran", "tl faizi"),
        "forward": ("forward", "fwd", "forward kur", "forward kuru", "kur", "outright", "fiyat", "price", "fwd rate",
                    "all in", "all in rate"),
        "points": ("swap puani", "puan", "swap points", "points", "pts", "swap", "fwd points", "forward points"),
        "spot": ("spot", "spot kur", "spot kuru", "spot rate"),
        "cpt": ("karsi taraf", "cpt", "counterparty", "cparty", "ctpy", "banka", "musteri", "taraf"),
        "note": ("not", "note", "notes", "aciklama", "comment", "yorum"),
    },
    "ois": {
        "side": ("yon", "side", "dir", "direction", "pay rec", "pay receive", "yon b s"),
        "tenor": ("vade", "tenor", "valor", "maturity", "enstruman", "instrument"),
        "start": ("baslangic", "start", "start date", "from", "baslangic tarihi", "baslangic mpc"),
        "end": ("bitis", "end", "end date", "to", "bitis tarihi", "bitis mpc"),
        "level": ("faiz", "oran", "rate", "level", "seviye", "fiyat", "price", "fixed rate", "oran yuzde"),
        "dv01": ("dv01", "dv01 usd", "dv01 bp", "risk", "dv01 usd bp", "bp degeri"),
        "nominal": ("nominal", "nominal tl", "notional", "tutar", "amount"),
        "cpt": ("karsi taraf", "cpt", "counterparty", "cparty", "ctpy", "banka", "taraf", "broker"),
        "note": ("not", "note", "notes", "aciklama", "comment", "yorum"),
    },
    "bond": {
        "instrument": ("enstruman", "isin", "kagit", "instrument", "bond", "tahvil", "menkul", "security"),
        "dir": ("yon", "side", "dir", "direction", "b s", "al sat", "alis satis", "buy sell"),
        "amount": ("tutar", "nominal", "amount", "miktar", "notional"),
        "price": ("fiyat", "price", "temiz fiyat", "clean price", "clean"),
        "note": ("not", "note", "notes", "aciklama", "comment", "yorum"),
    },
}
#: currencies a forward's amount column may name in its header ("USD tutarı", "Tutar (TL)", "EUR amount")
_CCYS = ("TRY", "USD", "EUR", "GBP", "CHF", "JPY", "CNH", "CNY", "RUB", "AUD", "CAD", "NZD", "SEK", "NOK", "DKK", "PLN",
         "HUF", "CZK", "ZAR", "AED", "SAR", "KWD", "QAR", "XAU", "ILS", "MXN", "BRL", "INR", "KRW", "SGD", "HKD")
_CCY_AMOUNT = re.compile(r"^(?:([a-z]{2,3}) )?(?:tutari|tutar|amount|nominal|notional|miktar)(?: ([a-z]{2,3}))?$")
_PRICES = (("TRY", "try_rate"), ("FWD", "forward"), ("SP", "points"))
PASTE_MAX_ROWS = 200
PASTE_MAX_CHARS = 200000


def header_field(kind: str, text: Any) -> Tuple[Optional[str], Optional[str]]:
    """The field a header names, and the currency it names: a forward's amount column may say its currency ("USD
    tutarı", "Tutar (TL)", "EUR amount", or just "TRY") - ``("amount", "USD")``, ``("quote_amount", "TRY")``; the
    pair of each row decides which side it is.  (None, None) when it is not a header of the product's."""
    f = fold(text)
    if not f:
        return None, None
    if kind == "fwd":
        m = _CCY_AMOUNT.match(f)
        code = (m.group(1) or m.group(2)) if m and bool(m.group(1)) != bool(m.group(2)) else (f if " " not in f else None)
        ccy = "TRY" if code in ("tl", "try") else (code or "").upper()
        if ccy in _CCYS:
            return ("quote_amount" if ccy == "TRY" else "amount"), ccy
    for key, words in _HEADERS[kind].items():
        if f in words:
            return key, None
    return None, None


def _rows(text: str) -> List[Tuple[int, List[str]]]:
    """The rows of a paste as Excel copies cells: tab-separated, a cell with a tab, a line break or a quote in quotes -
    each with the line of the paste it ends on; empty rows left out."""
    out = []
    reader = csv.reader(io.StringIO(text), delimiter="\t", quotechar='"', strict=False)
    for cells in reader:
        cells = [c.strip() for c in cells]
        if any(cells):
            out.append((reader.line_num, cells))
    return out


def read_paste(text: str, kind: str, mapping: Optional[List[Any]] = None, header: Optional[bool] = None) -> Dict[str, Any]:
    """Rows copied from Excel, read as trades of one product (``kind``: fwd / ois / bond) - not priced yet.

    The first row is a header when most of its cells name a field (:data:`_HEADERS`); ``header`` says it instead.  The
    columns are mapped from the header - without one in the order of the workbook's own lists (:data:`DEFAULT_ORDER`) -
    or as ``mapping`` says (a field or ``None`` per column).  A forward's amount column whose header names a currency is
    that currency's amount on each row (the pair decides which side).  Returns the columns (``i``, ``title``, ``field``,
    ``auto`` - what the header said -, ``ccy``), the rows (``n``: their line in the paste, ``cells``) and ``problems`` of
    the mapping (a field on two columns, a field the rows need missing) that fail every row."""
    if kind not in FIELDS:
        raise EntryError("bilinmeyen ürün: %r" % (kind,))
    if len(text) > PASTE_MAX_CHARS:
        raise EntryError("yapıştırılan metin çok uzun (en fazla %d karakter)" % PASTE_MAX_CHARS)
    rows = _rows(text)
    width = max((len(c) for _, c in rows), default=0)
    head = rows[0][1] + [""] * (width - len(rows[0][1])) if rows else []
    named = [header_field(kind, c) for c in head]
    filled = [c for c in head if c]
    found = bool(filled) and sum(1 for f, _ in named if f) * 2 >= len(filled) and any(f for f, _ in named)
    use_header = found if header is None else bool(header)
    columns: List[Dict[str, Any]] = []
    taken = set()
    for i in range(width):
        if use_header:
            field, ccy = named[i] if i < len(named) else (None, None)
            if field in taken:
                field = None                                   # a field twice: the first column has it
        else:
            order = DEFAULT_ORDER[kind]
            field, ccy = (order[i] if i < len(order) else None), None
        if field:
            taken.add(field)
        columns.append({"i": i, "title": head[i] if use_header else "", "field": field, "auto": field, "ccy": ccy})
    keys = [k for k, _ in FIELDS[kind]]
    if mapping is not None:
        if not isinstance(mapping, list):
            raise EntryError("sütun eşlemesi bir liste olmalı")
        for col in columns:
            if col["i"] < len(mapping):
                m = mapping[col["i"]]
                if m in (None, "", "-"):
                    col["field"] = None
                elif m in keys:
                    col["field"] = m
                else:
                    raise EntryError("bilinmeyen sütun: %r" % (m,))
            if col["field"] not in ("amount", "quote_amount"):
                col["ccy"] = None                               # (a currency only says which amount it is)
    labels = dict(FIELDS[kind])
    problems: List[str] = []
    seen: Dict[str, int] = {}
    for col in columns:
        f = col["field"]
        if f in seen:
            problems.append("%s iki sütunda (%d. ve %d.): birini \"—\" yapın" % (labels[f], seen[f] + 1, col["i"] + 1))
        elif f:
            seen[f] = col["i"]
    need = {"fwd": [("dir",), ("amount", "quote_amount"), ("value_date",), ("try_rate", "forward", "points", "basis")],
            "ois": [("side",), ("level",), ("tenor", "start")], "bond": [("instrument",), ("amount",), ("price",)]}[kind]
    missing = [" ya da ".join(labels[f] for f in alts) for alts in need if not any(f in seen for f in alts)]
    if rows and missing:
        problems.append("sütunu olmayan: %s" % ", ".join(missing))
    data = rows[1:] if use_header and rows else rows
    if len(data) > PASTE_MAX_ROWS:
        raise EntryError("bir yapıştırmada en fazla %d satır olabilir (%d satır var)" % (PASTE_MAX_ROWS, len(data)))
    return {"kind": kind, "fields": FIELDS[kind], "header": use_header, "header_found": found, "columns": columns,
            "head": head if use_header else None, "problems": problems,
            "rows": [{"n": n, "cells": cells + [""] * (width - len(cells))} for n, cells in data]}


def row_payload(kind: str, columns: List[Dict[str, Any]], cells: List[str]) -> Dict[str, Any]:
    """The payload the entry form would send for one pasted row (texts as typed: the service reads the numbers in the
    user's own format, as it reads the form's)."""
    vals: Dict[str, str] = {}
    ccys: Dict[str, str] = {}
    for col in columns:
        if col["field"] and col["i"] < len(cells) and cells[col["i"]]:
            vals[col["field"]] = cells[col["i"]]
            if col.get("ccy"):
                ccys[col["field"]] = col["ccy"]
    common = {"cpt": vals.get("cpt", "")[:40], "note": vals.get("note", "")[:200]}
    if kind == "fwd":
        return dict(common, **_fwd_row(vals, ccys))
    if kind == "ois":
        return dict(common, **_ois_row(vals))
    pl = {"instrument": vals.get("instrument", ""), "amount": vals.get("amount", ""), "price": vals.get("price", ""),
          "note": common["note"]}
    if "dir" in vals:
        pl["dir"] = _word(vals["dir"], FWD_DIRS, "yön anlaşılamadı: %r (B / S, Alış / Satış)")
    return pl


def _fwd_row(vals: Dict[str, str], ccys: Dict[str, str]) -> Dict[str, Any]:
    try:
        pair = bl.pair_of(vals.get("pair") or "USDTRY")
    except bl.TradeError as exc:
        raise EntryError(str(exc))
    if not vals.get("dir"):
        raise EntryError("yön yok (B / S, Alış / Satış)")
    if not vals.get("value_date"):
        raise EntryError("valör yok (gg.aa.yyyy ya da vade: 3M)")
    pl: Dict[str, Any] = {"pair": pair, "dir": _word(vals["dir"], FWD_DIRS, "yön anlaşılamadı: %r (B / S, Alış / Satış)"),
                          "value_date": vals["value_date"]}
    # the amounts: a column whose header names a currency is that currency's, whichever side of the pair it is
    for field in ("amount", "quote_amount"):
        if field not in vals:
            continue
        side, ccy = field, ccys.get(field)
        if ccy:
            if ccy == pair[:3]:
                side = "amount"
            elif ccy == pair[3:]:
                side = "quote_amount"
            else:
                raise EntryError("%s tutarı %s paritesinde yok" % (ccy, pair))
        if side in pl:
            raise EntryError("iki tutar sütunu da %s cinsinden" % (pair[:3] if side == "amount" else pair[3:]))
        pl[side] = vals[field]
    # the price: what "Fiyatlama" says, or the one price column that is filled
    if "basis" in vals:
        basis = _word(vals["basis"], BASES, "fiyatlama anlaşılamadı: %r (RET bid / mid / ask, TRY faizi, Forward kur, Swap puanı)")
        column = dict(_PRICES).get(basis)
        if column:
            if column not in vals:
                raise EntryError("fiyatlama %s ama %s yazılmamış" % (BASIS_LABEL[basis], dict(FIELDS["fwd"])[column]))
            pl["manual"] = vals[column]
    else:
        given = [(b, c) for b, c in _PRICES if c in vals]
        if not given:
            raise EntryError("fiyat yok: TRY faizi, forward kur ya da swap puanı gerekli (ya da Fiyatlama: RET mid)")
        if len(given) > 1:
            raise EntryError("birden çok fiyat (%s): hangisinin geçerli olduğunu Fiyatlama sütunu söylemeli"
                             % ", ".join(dict(FIELDS["fwd"])[c] for _, c in given))
        basis, column = given[0]
        pl["manual"] = vals[column]
    pl["basis"] = basis
    if "spot" in vals:
        pl["spot"] = vals["spot"]
    return pl


def _ois_row(vals: Dict[str, str]) -> Dict[str, Any]:
    if not vals.get("side"):
        raise EntryError("yön yok (PAY / RECEIVE)")
    pl: Dict[str, Any] = {"side": _word(vals["side"], OIS_SIDES_WORDS, "yön anlaşılamadı: %r (PAY / RECEIVE, B / S)"),
                          "level": vals.get("level", "")}
    if "start" in vals or "end" in vals:
        if "tenor" in vals:
            raise EntryError("hem vade hem başlangıç / bitiş yazılmış: MPC işlemi iki tarihle, vadeli işlem vadesiyle girilir")
        pl.update(strategy="mpc", start=vals.get("start", ""), end=vals.get("end", ""))
    else:
        tenor = "".join(vals.get("tenor", "").split()).upper()
        pl.update(strategy="outright", tenor="ON" if tenor == "O/N" else tenor)
    # a nominal is the trade's own size: its DV01 follows from it (a DV01 written beside it is not used)
    if "nominal" in vals:
        pl["nominal"] = vals["nominal"]
    elif "dv01" in vals:
        pl["dv01"] = vals["dv01"]
    return pl


# ---------------------------------------------------------------------------------------------- TOPLU FORWARD's rows
#: TOPLU FORWARD FİYATLAMA's rows as a paste ("İşleme al"; the desk, 24.11.2026: "3 ekle"): the columns the dialog reads
#: by their headers, and "Satır" - the table's row (1..100), which it does not read: after the save the browser empties
#: the Tutar of the rows kept by it, so that a second press cannot book them again
BULK_FWD_HEAD = ("Satır", "Parite", "Yön", "Tutar", "Valör", "TRY faizi", "Forward kur", "Karşı taraf", "Not")
BULK_FWD_NOTE = "TOPLU FORWARD"
#: where a row's TRY rate comes from, by the column of its typed value (the table is two-way: extras.BULK_TW_ID) - none
#: typed: RET mid; an ON karşılık % (M) or a Spread (bp) typed (26.11.2026): the Manuel TRY % it gives, booked as the
#: TRY rate; a P/gün typed: as its pair's puan
BULK_FWD_SOURCES = {None: "RET mid %", "L": "Manuel TRY %", BULK_SPREAD: "Spread (bp)", "M": "ON karşılık %",
                    "N": "USDTRY fwd", "O": "USDTRY puan", BULK_USD_PPD: "USDTRY P/gün", "P": "EURTRY fwd",
                    "Q": "EURTRY puan", BULK_EUR_PPD: "EURTRY P/gün"}
#: a row with nothing typed while the table's general spread is (extras.BULK_SPREAD_ALL): priced at RET mid + it
BULK_FWD_SPREAD_ALL = "RET mid % + genel spread"


def _plain(x: float, lang: str) -> str:
    """A rate or an outright to its last digit, in the user's format, ungrouped: read back, the same number."""
    s = repr(float(x))
    if "e" in s or "E" in s:
        s = ("%.15f" % x).rstrip("0").rstrip(".")
    return s if lang == "en" else s.replace(".", ",")


def _grouped(x: float, lang: str) -> str:
    """An amount in the user's format, grouped by thousands: 10.000.000 (Turkish) / 10,000,000 (English)."""
    s = "{:,.6f}".format(x).rstrip("0").rstrip(".")
    return s if lang == "en" else s.replace(",", "\0").replace(".", ",").replace("\0", ".")


def _number(v: Any) -> Optional[float]:
    return v if type(v) is float else None              # (a cell's number; "", an error or a text: none)


def _row_pair(row: Dict[str, Any]) -> str:
    return str(row.get("pair") or "").strip().upper() or "USDTRY"          # (Parite left blank: USDTRY)


def bulk_forward_price(row: Dict[str, Any]) -> Tuple[str, Optional[float], str]:
    """The price TOPLU FORWARD books a row at - what the row shows: ``(field, value, source)``.

    * a forward typed in the row's pair's own column (USDTRY fwd (elle) / EURTRY fwd (elle)): *Forward kur* = it;
    * else USDTRY whose USDTRY fwd, puan or P/gün is the row's typed value (the table is two-way): *Forward kur* = the
      row's USDTRY fwd - the one typed, or spot + the puan typed (P/gün typed · Gün) / 10000;
    * else USDTRY: *TRY faizi* = the rate the row priced with - its Manuel TRY %, typed or worked out from the EURTRY fwd /
      puan / P/gün, the ON karşılık % or the Spread (bp) typed, else RET mid % plus the table's general spread (blank:
      none) - the blotter's TRY-rate pricing is this very row's formula, the workbook's own bulk row ``Forward!N163``:
      the same forward; an ON or a spread is no booking price - the TRY rate it gives is;
    * else EURTRY: *Forward kur* = the row's EURTRY fwd.  (The blotter's EURTRY TRY-rate pricing takes the EUR rate as the
      middle of the interpolated EUR bid and ask, ``Forward!AD27``; the row takes Bloomberg's interpolated EUR MID: the
      same forward only while every MID is the exact middle of its bid and ask - the row's outright is booked instead.)

    The source says where the row's TRY rate comes from (``BULK_FWD_SOURCES``; nothing typed and a general spread:
    ``BULK_FWD_SPREAD_ALL``).  ``value`` None: the row has no such price (no valör, no curve): the dialog says why.
    ``row``: the table's cells - ``pair`` (V), ``manual`` (L), ``ret_mid`` (G), ``rate`` (the rate that prices the row,
    extras.BULK_RATE; a row without it: Manuel TRY %, else RET mid + ``spread_all``), ``spread_all`` (the general spread,
    bp), ``usd_fwd`` (N), ``eur_fwd`` (P), ``usd_typed`` (R), ``eur_typed`` (T) - and ``anchor``, the column of the row's
    typed value (BULK_FWD_SOURCES' keys; None: none - a row without it: L when its Manuel TRY % is a number)."""
    pair = _row_pair(row)
    typed = _number(row.get({"USDTRY": "usd_typed", "EURTRY": "eur_typed"}.get(pair, "")))
    if typed is not None:
        return "forward", typed, "elle forward"
    manual = _number(row.get("manual"))
    spread_all = _number(row.get("spread_all"))
    anchor = row["anchor"] if "anchor" in row else ("L" if manual is not None else None)
    source = BULK_FWD_SOURCES.get(anchor, BULK_FWD_SOURCES[None])
    if anchor is None and spread_all is not None:
        source = BULK_FWD_SPREAD_ALL
    if pair == "USDTRY":
        if anchor in ("N", "O", BULK_USD_PPD):
            return "forward", _number(row.get("usd_fwd")), source
        if "rate" in row:
            return "try_rate", _number(row.get("rate")), source
        ret_mid = _number(row.get("ret_mid"))
        if manual is None and ret_mid is not None and spread_all is not None:
            return "try_rate", ret_mid + spread_all / 100, source
        return "try_rate", manual if manual is not None else ret_mid, source
    return "forward", _number(row.get("eur_fwd")) if pair == "EURTRY" else None, source


def bulk_forward_paste(rows: List[Dict[str, Any]], lang: str = "tr") -> Dict[str, Any]:
    """TOPLU FORWARD FİYATLAMA's rows as Excel'den yapıştır reads them ("İşleme al"): an FX forward of every row with a
    Tutar - its Parite (blank: USDTRY), Yön, Tutar (the pair's first currency), Valör, the price it shows
    (:func:`bulk_forward_price`, to its last digit), Karşı taraf, and a note saying where it came from ("TOPLU FORWARD ·
    RET mid %").  A row without a Yön or a valör goes as it is: the preview says what is missing, it is never saved.  A
    row with a valör and no Tutar is left out and counted.

    ``rows``: the table's rows as the user sees them - ``n`` (1..100), ``date`` (B), ``dir``, ``amount``, ``cpt``,
    ``ref`` (its Tutar cell) and the price cells :func:`bulk_forward_price` reads.  Returns the text (``text``, in the
    user's number format ``lang``), ``taken`` / ``skipped``, what the dialog says of them (``said``), the column that
    names each line's row (``row_title``) and the Tutar cell of each row taken, by that name (``amounts``)."""
    from .xl.values import serial_to_date
    lines: List[List[str]] = []
    amounts: Dict[str, str] = {}
    skipped = 0
    for row in rows:
        day = _number(row.get("date"))
        day = day if day is not None and day > 0 else None
        amount = row.get("amount")
        if amount is None or (isinstance(amount, str) and not amount.strip()):
            if day is not None:
                skipped += 1                             # (a row priced and not to be booked; an empty one is no row)
            continue
        field, value, source = bulk_forward_price(row)
        price = "" if value is None else _plain(value, lang) + ("%" if field == "try_rate" else "")
        lines.append([str(row["n"]), _row_pair(row), str(row.get("dir") or "").strip(),
                      _grouped(amount, lang) if type(amount) is float else str(amount).strip(),
                      serial_to_date(day).strftime("%d.%m.%Y") if day is not None else "",
                      price if field == "try_rate" else "", price if field == "forward" else "",
                      str(row.get("cpt") or "").strip(), "%s · %s" % (BULK_FWD_NOTE, source)])
        amounts[str(row["n"])] = row["ref"]
    buf = io.StringIO()
    out = csv.writer(buf, delimiter="\t", quotechar='"', lineterminator="\n")
    for line in [list(BULK_FWD_HEAD)] + lines:
        out.writerow(line)
    if lines:
        said = ("TOPLU FORWARD FİYATLAMA'dan Tutar'ı yazılı %d satır%s. Fiyat satırın gösterdiği: USDTRY'de TRY faizi (Manuel "
                "TRY %%, boşsa RET mid %% - genel spread yazılıysa RET mid %% + genel spread -; USDTRY fwd, puanı ya da P/gün'ü "
                "yazılmışsa o forward), EURTRY'de EURTRY fwd, elle forward yazılmışsa o. Kaydedilen satırların Tutar'ı tabloda "
                "silinir."
                % (len(lines), " · Tutar'ı boş %d satır alınmadı" % skipped if skipped else ""))
    else:
        said = ("TOPLU FORWARD FİYATLAMA'da Tutar'ı yazılı satır yok%s: işleme almak için satıra Yön ve Tutar yazın"
                % (" (valörü olan %d satırın Tutar'ı boş)" % skipped if skipped else ""))
    return {"kind": "fwd", "text": buf.getvalue().rstrip("\n") if lines else "", "taken": len(lines), "skipped": skipped,
            "said": said, "row_title": BULK_FWD_HEAD[0], "amounts": amounts}
