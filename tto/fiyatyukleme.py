"""Kâğıt Fiyat Yükleme (bond price upload): the desk's daily tool to make bid / ask prices for a list of Turkish
government bonds and save them as a txt file to upload elsewhere - the desk's request of 20.11.2026:

    "Bir de kağıt fiyat yükleme sekmesi açmamız gerekli. Bu sekmede BBG/İhale olarak iki seçim olacak. Her sabah ihale
    fiyatları yükleyeceğim, buna göre belirttiğim yield spreadine göre fiyatları alıp t0 yieldına spreadleri koyarak
    fiyatları belirleyecek. [...] Zero coupon kağıtlar yield ile, diğerleri fiyat ile yazılacak, ve hangisi yazıldıysa
    diğerleri 0 yazılacak. [...] Eğer bbg olarak seçim yaparsam, bbg last trade'i mid alacak. Eğer son trade bugün
    değilse, son ihale fiyatından itibaren curve'deki genel harekete göre fiyat basacak."

(the whole text and the four answers: docs/desk-decisions.md, "Kâğıt fiyat yükleme").

**The list** is each user's (``KEY_LIST``): a bond stays until its owner takes it off; each row its own two spreads or
the defaults.  A bond not in the desk's catalog comes in by the desk's own route (``Service.bond_list_add``: Bloomberg's
facts once per new ISIN); without Bloomberg (replay) it cannot.

**Spreads** ("İki tarafa da ayrı ayrı"): a yield-quoted bond (fixed coupon, bill, zero coupon) bid yield = t0 + bid bp,
ask yield = t0 − ask bp; a price-quoted one (TLREF floater, FRN, TÜFE linker: "price spread") bid price = t0 − bid,
ask price = t0 + ask.  Negatives are allowed (skew).

**t0** is today's own value date (the paste day; the next TRY business day when today is not one).  Every yield here is
BIST's simple yield, the auction sheet's and DİBS RV's (``extras._tto_auction``): a bill's or zero coupon's
(100/P − 1)·365/days, a fixed coupon bond's the rate that discounts its coupons at (1 + y/f) per period - quantcurve's
``Bond`` (coupons every round(364/f) days back from the maturity) and its accrued interest (``quantcurve.accrued``).

**İhale**: the morning's auction text (``parse``): "<dd/mm/yy(yy)>[zc| TLREF| cpi].t1|.t2  <value>"; a bill's or zero's
value is its simple yield, the others' a clean price; .t1 / .t2 value T+1 / T+2 from the paste day (TRY business days).
Each line is matched to a bond by its maturity and tag (``candidates``) - or by what the desk named it once
(``KEY_LABELS``, desk-wide, for ever).  A bond's .t1 line is used, its .t2 only without one.  t0: a yield-quoted bond's
yield at the line's value date, the same yield at t0 gives the t0 price; a price-quoted bond's clean price is its t0 as it
is.  Every day's lines are kept per ISIN (``KEY_AUCTIONS``): BBG mode's "last auction price".

**BBG**: mid = Bloomberg's last trade.  A bond of DİBS RV's trading list: the sheet's own LAST_PRICE / LAST_TRADE_DATE
(``AS`` / ``I``: already asked for, no new cost); any other: one reference request of LAST_PRICE and LAST_TRADE_DATE
(2 hits a bond, only on Hesapla, kept ``CACHE_SECONDS``: :meth:`~tto.marketdata.base.Provider.reference`).  A last
trade of today is the mid (a coupon bond's a clean price, a bill's a price turned into its simple yield - or a yield,
``bill_last``).  Otherwise the newest of the last trade and the last auction kept, moved with the bond curve since its
day's close (``move``): its simple yield + (the Nelson-Siegel fit of the trading list's yields now − the same fit on
that day's close, both at the bond's cash flows from t0); without that fit the TRY OIS Bootstrap zero rate's change at
the bond's maturity, said on the row.  An auction kept on the trade's day or later is the reference ("son trade bugün
değilse, son ihale fiyatından itibaren"); a trade newer than any auction kept is (the desk, 20.11.2026: "dün işlem
olmasına rağmen son işlem dün diyor ve göstermiyor" - before the market opens, yesterday's last trade plus the night's
move).  A price-quoted bond keeps that reference's price; neither a trade nor an auction: no price, the row says why.

**Eurobonds** (the same night: "Eklenecek listede eurobondlar da olacak. Bunlar direkt bbgden fiyatlanacak. Bunlarda last
trade yok direkt midden ve spreadden gideceğiz" - "Eurobondlar da yield spreadi"): a USD / EUR Turkish sovereign comes onto
the list by its ISIN, its facts (description, currency, coupon, frequency, day count, maturity, coupon dates, settlement
lag: ``EURO_FACTS``) asked of Bloomberg once and kept here (``KEY_EURO``; never in the DİBS catalog).  Whatever the switch
says it is priced from Bloomberg's mid: PX_MID (else the middle of PX_BID / PX_ASK, said) and YLD_YTM_MID; bid yield = mid
+ bid bp, ask yield = mid − ask bp (its own default pair); each side's clean price by the street convention (``Street``:
Excel's PRICE / YIELD, 30/360 or ACT/ACT by DAY_CNT_DES) anchored to Bloomberg - the convention's price + (PX_MID − its
price at the mid yield), so the mid is Bloomberg's to the digit and the anchor (shown, flagged beyond 0,05) moves the sides
by the convention's curvature only.  In the txt: clean prices, yields 0.

**Sabit fiyat** (the desk, 20.11.2026: "Bir de sabit fiyat kısmı açmalıyız, bazı kağıtları direkt bu şekilde yüklenecek diye
girip bırakabilmeliyim"): a bond's bid and ask in the unit the txt writes it in (a bill's / zero's simple yields, any
other's clean prices), typed (``set_fixed``) or pasted from Excel ("Sabitlemeyi de tablo olarak atacağım excelden
kopyalayıp [...]": ``parse_fixed`` - the ISIN, the first number after it, the next within ±10 % of it), kept with the
user's list until changed or taken off.  Only the ISIN and the two figures are needed (``fixed_record``: the catalog's
record, a Eurobond's facts if held, else what a Turkish ISIN says - its maturity, "TRB…" a bill, "TRT…F…" an
FX-denominated DİBS).  On Hesapla, in either mode, it is a row as it is (``_fixed_row``: its other unit for information
only), never computed and never asked of Bloomberg; in the list too, the fixed figures win.  An edit of its cells is that
Hesapla's alone.

**Kaydet** (``txt``): one line a bond, ``ISIN,pricebid,priceask,yieldbid,yieldask``: bills and zero coupons with their
simple yields (%), the prices 0; the rest with clean prices, the yields 0 - three decimals, a dot, CRLF, ASCII
(``dibs_fiyat_YYYYMMDD.txt``); each user's saves of the day kept (``KEY_SAVED``) for a second download."""
from __future__ import annotations

import calendar
import datetime as _dt
import math
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import bonds as bd
from . import kagitfiyat as kf
from . import quantcurve as qc

PAGE_ID = "fiyat-yukleme"
PAGE = {"id": PAGE_ID, "title": "Kâğıt Fiyat Yükleme", "group": "Tahvil", "book": "tto", "sheet": None, "custom": True}
AFTER = "kagit-fiyat"                      # the menu entry it follows (Kâğıt Fiyatlama)

MODES = ("ihale", "bbg")
MODE_TEXT = {"ihale": "İhale", "bbg": "BBG"}
#: a Eurobond (a USD / EUR Turkish sovereign, "XS…", "US900123…"): the desk's addition of 20.11.2026 - priced from
#: Bloomberg's mid whatever the switch says, its spreads in yield bp ("Eurobondlar da yield spreadi")
EURO = "euro"
#: the defaults until a user sets theirs: DİBS quoted in yield in bp of the simple yield, price-quoted ones in price points,
#: Eurobonds in bp of Bloomberg's yield (their own pair: much tighter than DİBS)
DEFAULTS: Dict[str, float] = {"yield_bid": 5.0, "yield_ask": 5.0, "price_bid": 0.05, "price_ask": 0.05, "euro_bid": 2.0, "euro_ask": 2.0}
#: a spread's bounds (either way: a negative one skews the quote)
LIMITS = {"bp": 500.0, "price": 10.0}
#: the kinds quoted in yield (their spreads in bp) and those written with their yields in the txt
YIELD_KINDS = ("fixed", "bill", "zero")
WRITE_YIELD = ("bill", "zero")
#: the kinds in the order the page lists them (as Tüm Kâğıtlar groups them; Eurobonds last)
ORDER = ("bill", "zero", "fixed", "float", "frn", "cpi", EURO)
#: the store's keys (kv): a user's list and settings, a user's saved files, the desk's labels, the desk's auction values,
#: the Eurobonds' facts (desk-wide: asked of Bloomberg once an ISIN)
KEY_LIST, KEY_SAVED = "fiyatyukleme.list:%s", "fiyatyukleme.saved:%s"
KEY_LABELS, KEY_AUCTIONS, KEY_EURO = "fiyatyukleme.labels", "fiyatyukleme.auctions", "fiyatyukleme.eurobonds"
#: a Eurobond's facts (once an ISIN), its mid (2 hits a bond a Hesapla) and the sides asked only when the mid is empty
EURO_FACTS = ("NAME", "SECURITY_DES", "CRNCY", "CPN", "CPN_TYP", "CPN_FREQ", "DAY_CNT_DES", "MATURITY", "FIRST_CPN_DT",
              "PENULTIMATE_CPN_DT", "INT_ACC_DT", "DAYS_TO_SETTLE")
EURO_MID = ("PX_MID", "YLD_YTM_MID")
EURO_SIDES = ("PX_BID", "PX_ASK")
EURO_LAG = 2                               # business days to settle when Bloomberg does not say (DAYS_TO_SETTLE)
ANCHOR_WARN = 0.05                         # price points: the street convention this far from Bloomberg's mid is flagged
LIST_MAX = 200                             # bonds on a user's list
TEXT_MAX = 100000                          # characters of a pasted auction text
AUCTIONS_KEPT = 30                         # auction values kept per bond (the latest)
SAVED_DAYS, SAVED_PER_DAY = 10, 10         # a user's saved files kept: days, files a day
#: BBG mode: the fields of a bond off the trading list (2 hits a bond a Hesapla), how long an answer is used again
BBG_FIELDS = ("LAST_PRICE", "LAST_TRADE_DATE")
CACHE_SECONDS = 300.0
BBG_WAIT = 15.0                            # seconds Hesapla waits for Bloomberg's answer
NEAR_DAYS = 45                             # an unrecognised line's candidates: bonds maturing within this many days
#: a bill's last trade read as a price while the yield it gives is in this range (a decimal), else as a yield (%)
SANE_YIELD = (-0.05, 1.0)
#: the tags of an auction line (case folded) and the kind each stands for; no tag: the fixed coupon bond, else the bill
TAGS = {"zc": "zc", "tlref": "tlref", "cpi": "cpi", "tüfe": "cpi", "tufe": "cpi", "frn": "frn"}
TAG_KINDS = {"zc": ("bill", "zero"), "tlref": ("float",), "cpi": ("cpi",), "frn": ("frn",)}
TAG_TEXT = {"": "sabit kuponlu (yoksa bono / kuponsuz)", "zc": "kuponsuz / bono", "tlref": "TLREF'e endeksli", "cpi": "TÜFE'ye endeksli",
            "frn": "FRN"}
BP = 1e4

_DATE_START = re.compile(r"^\s*\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{2,4}")
_LINE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\s*([^\W\d_]+)?\s*\.\s*t(\d)\s+(\S+)\s*$", re.IGNORECASE)
_TN = re.compile(r"\s*\.\s*t\d\s*(\S+\s*)?$", re.IGNORECASE)          # a line's ".t1  31.500" (or a label's ".t1")


class FiyatError(ValueError):
    """A request the page cannot answer: the reason, in Turkish (the service's 400)."""


def menu(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The nav's pages with Kâğıt Fiyat Yükleme right after Kâğıt Fiyatlama in the Tahvil menu (where that is)."""
    at = next((i + 1 for i, p in enumerate(pages) if p["id"] == AFTER), None)
    if at is None:
        return pages
    return pages[:at] + [dict(PAGE)] + pages[at:]


# ---------------------------------------------------------------------------------------------- numbers, days
def num(v: Any) -> Optional[float]:
    """A number as the page or a pasted text writes it ("31.500", "31,5", "−0,05"); None for anything else."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    s = str(v or "").strip().replace("−", "-").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def _serial(d: _dt.date) -> float:
    from .xl.values import date_to_serial
    return float(date_to_serial(d))


def workday(day: _dt.date, n: int, hol: frozenset) -> _dt.date:
    """``WORKDAY(day, n, TRY)``: the n-th TRY business day after ``day`` (``hol``: the holidays as dates) -
    kagitfiyat's, on serials."""
    return kf.workday(day, n, frozenset(_serial(d) for d in hol))


def t0_of(today: _dt.date, hol: frozenset) -> _dt.date:
    """Today's own value date: today, or the next TRY business day when today is none."""
    return today if today.weekday() < 5 and today not in hol else workday(today, 1, hol)


def date_said(v: Any) -> Optional[_dt.date]:
    """A date as Bloomberg / the sheet gives it: a serial, "3.11.2026" (with a time after it or not), "2026-11-03"."""
    from .xl.values import serial_to_date
    if type(v) is float and 20000 < v < 80000:
        return serial_to_date(v)
    if isinstance(v, (_dt.datetime,)):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    s = str(v or "").strip().split(" ")[0]
    for pat, order in ((r"^(\d{4})-(\d{1,2})-(\d{1,2})$", "ymd"), (r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", "dmy")):
        m = re.match(pat, s)
        if m:
            a, b, c = (int(x) for x in m.groups())
            y, mo, d = (a, b, c) if order == "ymd" else (c, b, a)
            try:
                return _dt.date(y, mo, d)
            except ValueError:
                return None
    return None


def tr_day(d: Optional[_dt.date]) -> str:
    return d.strftime("%d.%m.%Y") if d else ""


def _n(v: float, digits: int = 3) -> str:
    return ("%.*f" % (digits, v)).replace(".", ",")


def _bp(v: float) -> str:
    r = int(round(v))
    return ("+%d" % r) if r >= 0 else ("−%d" % -r)


# ---------------------------------------------------------------------------------------------- the auction text
def label_key(day: _dt.date, tag: str) -> str:
    """The label of an auction line without its .t1 / .t2, written one way ("10/02/2027 zc", "13/01/2027 tlref",
    "06/01/2027"): what the desk's naming of a line is kept under (dd/mm/yy and dd/mm/yyyy alike)."""
    return day.strftime("%d/%m/%Y") + (" " + tag if tag else "")


def parse(text: str) -> Dict[str, List[Dict[str, Any]]]:
    """The auction lines of a pasted text: ``{"lines": [...], "ignored": [{"n", "text"}]}``.  A line is
    ``{"n", "text", "label", "key", "date", "tag", "tn", "value"}`` (``tag`` case folded - "zc", "tlref", "cpi", "frn",
    "" or one it does not know; ``tn`` 1 or 2) - or, for one that starts with a date but cannot be read, ``{"n", "text",
    "why"}``.  Every other line ("Auction prices:", "** Min 50 mio, …") is ignored."""
    out: Dict[str, List[Dict[str, Any]]] = {"lines": [], "ignored": []}
    for i, raw in enumerate(str(text or "").splitlines()):
        line = raw.strip()
        if not line:
            continue
        m = _LINE.match(line)
        if m is None:
            if _DATE_START.match(line):
                out["lines"].append({"n": i + 1, "text": line, "why": "satır okunamadı (beklenen: gg/aa/yyyy[etiket].t1 değer)"})
            else:
                out["ignored"].append({"n": i + 1, "text": line})
            continue
        dd, mm, yy, tag, tn, value = m.groups()
        year = int(yy) + (2000 if len(yy) == 2 else 0)
        try:
            day = _dt.date(year, int(mm), int(dd))
        except ValueError:
            out["lines"].append({"n": i + 1, "text": line, "why": "tarih geçersiz: %s/%s/%s" % (dd, mm, yy)})
            continue
        tag = (tag or "").casefold()
        tag = TAGS.get(tag, tag)
        label = _TN.sub("", line[:m.end(5)])                            # (the text before ".t1")
        rec: Dict[str, Any] = {"n": i + 1, "text": line, "label": label, "key": label_key(day, tag), "date": day.isoformat(),
                               "tag": tag, "tn": int(tn)}
        v = num(value)
        if tn not in ("1", "2"):
            rec["why"] = "valör .t%s bilinmiyor (yalnız .t1 / .t2)" % tn
        elif v is None or v <= 0:
            rec["why"] = "değer okunamadı: %s" % value
        else:
            rec["value"] = v
        out["lines"].append(rec)
    return out


def candidates(day: str, tag: str, pool: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The bonds an auction line can mean: maturing on ``day`` (ISO), of the tag's kind - no tag: the fixed coupon bond,
    or the bill / zero coupon when no fixed coupon bond matures that day ("zc" marks a zero coupon where a coupon bond
    has the same maturity)."""
    hit = [b for b in pool if b.get("maturity") == day and b.get("kind")]
    if not tag:
        fixed = [b for b in hit if b["kind"] == "fixed"]
        return fixed or [b for b in hit if b["kind"] in ("bill", "zero")]
    kinds = TAG_KINDS.get(tag)
    return [b for b in hit if b["kind"] in kinds] if kinds else []


def near(day: str, pool: Sequence[Dict[str, Any]], days: int = NEAR_DAYS, most: int = 12) -> List[Dict[str, Any]]:
    """The bonds maturing within ``days`` of ``day``, nearest first: what an unrecognised line is picked from."""
    d0 = _dt.date.fromisoformat(day)
    out = []
    for b in pool:
        if not b.get("maturity"):
            continue
        gap = abs((_dt.date.fromisoformat(b["maturity"]) - d0).days)
        if gap <= days:
            out.append((gap, ORDER.index(b["kind"]) if b.get("kind") in ORDER else 9, b))
    out.sort(key=lambda x: (x[0], x[1], x[2]["isin"]))
    return [brief(b) for _, _, b in out[:most]]


def brief(b: Dict[str, Any]) -> Dict[str, Any]:
    """A bond as a page lists it: ISIN, the desk's short name, Bloomberg's description, kind, maturity (a Eurobond: its
    currency too)."""
    if b.get("kind") == EURO:
        mat = _dt.date.fromisoformat(b["maturity"]).strftime("%d.%m.%y") if b.get("maturity") else ""
        return {"isin": b["isin"], "label": ("%s %s" % (mat, b.get("ccy") or "")).strip(), "name": b.get("name") or "", "kind": EURO,
                "kind_text": "Eurobond", "ccy": b.get("ccy") or "", "maturity": b.get("maturity")}
    if b.get("fixed_only"):
        # a fixed price's bond the dashboard does not know (an FX-denominated DİBS: not in the catalog by the desk's rule)
        mat = _dt.date.fromisoformat(b["maturity"]).strftime("%d.%m.%y") if b.get("maturity") else ""
        tail = {FX_DIBS_KIND: " Döviz", "bill": " Bono"}.get(b.get("kind") or "", "")
        return {"isin": b["isin"], "label": (mat + tail).strip() or b["isin"], "name": b.get("name") or "", "kind": b.get("kind"),
                "kind_text": {FX_DIBS_KIND: FX_DIBS_TEXT, "bill": "Bono"}.get(b.get("kind") or "", ""), "ccy": "",
                "maturity": b.get("maturity")}
    return {"isin": b["isin"], "label": bd.short_label(b), "name": b.get("name") or "", "kind": b.get("kind"),
            "kind_text": bd.KINDS.get(b.get("kind") or "", "tür bekleniyor"), "ccy": "TRY", "maturity": b.get("maturity")}


def row_order(r: Dict[str, Any]) -> Tuple[int, str, str]:
    """The page's order of bonds: by kind (``ORDER``), then maturity."""
    return (ORDER.index(r["kind"]) if r.get("kind") in ORDER else 9, r.get("maturity") or "9999", r.get("isin") or "")


# ---------------------------------------------------------------------------------------------- fixed prices pasted from Excel
#: a cell that looks like an ISIN; a Turkish FX-denominated DİBS ("TRT191127F19": TR, the type letter, DDMMYY, F, 2 digits)
_ISIN_CELL = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
_FX_DIBS = re.compile(r"^TR[A-Z]\d{6}F\d\d$")
#: the offer is the next number within this share of the bid (a yield column - 4.74 -, a stock - 42,000 - are not)
OFFER_REACH = 0.10
FX_DIBS_KIND, FX_DIBS_TEXT = "fxdibs", "Döviz DİBS"


def cell_num(text: Any) -> Optional[float]:
    """A pasted cell as a number: a dot or a Turkish comma as the decimal mark, and with both the last one is it
    ("99.483", "99,483", "1.234,5", "42,000.5"); a "%" dropped; anything else None."""
    t = str(text or "").strip().replace(" ", "").replace(" ", "").replace("−", "-").rstrip("%")
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif t.count(",") == 1:
        t = t.replace(",", ".")
    elif t.count(",") > 1 or t.count(".") > 1:
        t = t.replace(",", "").replace(".", "") if t.count(",") > 1 else t.replace(".", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def parse_fixed(text: str, unit_of) -> Dict[str, List[Dict[str, Any]]]:
    """Fixed prices pasted from Excel (the desk, 20.11.2026: "Sabitlemeyi de tablo olarak atacağım excelden kopyalayıp
    [...] Burada bid ve offer'ı ve ISIN'i kopyalayacağım"), one bond a line: the cells as Excel copies them (tabs; else
    runs of spaces), the ISIN the first cell that looks like one, the bid the first number after it, the offer the next
    number within ``OFFER_REACH`` of the bid - so the sheet's lower block (ISIN | Bid | | Offer) and its upper one (ISIN |
    Bid | Bid Yield | Offer | T1 Yield | Stok) read alike.  ``{"rows": [{"n", "text", "isin", "bid", "ask"}], "bad": [{"n",
    "text", "why"}], "ignored": [...]}`` - a line with neither an ISIN nor a number (a header, "USD") is ignored; ``unit_of``
    (ISIN -> "yield" | "price") says which way an offer would be on the wrong side of its bid."""
    out: Dict[str, List[Dict[str, Any]]] = {"rows": [], "bad": [], "ignored": []}
    for i, raw in enumerate(str(text or "").splitlines()):
        if not raw.strip():
            continue
        cells = raw.split("\t") if "\t" in raw else re.split(r" {2,}", raw.strip())
        if len(cells) == 1:
            cells = raw.split()
        cells = [c.strip() for c in cells]
        line = " | ".join(c for c in cells if c)
        at = next((j for j, c in enumerate(cells) if _ISIN_CELL.match(c.upper())), None)
        if at is None:
            if any(cell_num(c) is not None for c in cells):
                out["bad"].append({"n": i + 1, "text": line, "why": "ISIN yok"})
            else:
                out["ignored"].append({"n": i + 1, "text": line})
            continue
        isin = cells[at].upper()
        if not bd.isin_valid(isin):
            out["bad"].append({"n": i + 1, "text": line, "why": "ISIN'in kontrol hanesi tutmuyor: %s" % isin})
            continue
        nums = [v for v in (cell_num(c) for c in cells[at + 1:]) if v is not None]
        if not nums:
            out["bad"].append({"n": i + 1, "text": line, "why": "bid yok (ISIN'den sonra sayı yok)"})
            continue
        bid = nums[0]
        ask = next((v for v in nums[1:] if abs(v - bid) <= OFFER_REACH * abs(bid)), None)
        if ask is None:
            out["bad"].append({"n": i + 1, "text": line, "why": "offer yok: bid'in ±%%%d'u içinde ikinci sayı yok" % int(OFFER_REACH * 100)})
            continue
        in_yield = unit_of(isin) == "yield"
        if (ask > bid) if in_yield else (ask < bid):
            out["bad"].append({"n": i + 1, "text": line, "why": "offer getirisi bid'inkinden büyük" if in_yield else "offer bid'den küçük"})
            continue
        out["rows"].append({"n": i + 1, "text": line, "isin": isin, "bid": bid, "ask": ask})
    return out


def match(lines: List[Dict[str, Any]], labels: Dict[str, Dict[str, Any]], pool: Sequence[Dict[str, Any]]) -> None:
    """Each readable line's bond, in place: what the desk named its label (``labels``, first), else its maturity and tag
    (``candidates``) - ``isin`` and ``how``; a line that matches none, or more than one, gets ``why`` and the bonds near
    its date to pick from (``near``).  Then a bond's .t1 line is the one used (``used``), its .t2 only without one."""
    by_isin = {b["isin"]: b for b in pool}
    for ln in lines:
        if ln.get("why"):
            continue
        named = labels.get(ln["key"])
        if named and named.get("isin"):
            b = by_isin.get(named["isin"])
            if b is None:
                ln["why"] = "tanıtılan ISIN kâğıt kataloğunda yok: %s" % named["isin"]
            else:
                ln.update(isin=b["isin"], how="tanıtıldı (%s)" % (named.get("by") or "masa"))
        elif ln["tag"] and ln["tag"] not in TAG_KINDS:
            ln["why"] = "etiket bilinmiyor: %s (zc, TLREF, cpi)" % ln["tag"]
        else:
            got = candidates(ln["date"], ln["tag"], pool)
            when = _dt.date.fromisoformat(ln["date"]).strftime("%d.%m.%Y")
            if len(got) == 1:
                ln.update(isin=got[0]["isin"], how="vade + etiket")
            elif not got:
                ln["why"] = "%s vadeli %s kâğıt yok" % (when, TAG_TEXT.get(ln["tag"], ln["tag"]))
            else:
                ln["why"] = "%s vadeli birden çok kâğıt: %s" % (when, ", ".join("%s (%s)" % (b["isin"], bd.KINDS.get(b["kind"], b["kind"]))
                                                                             for b in got))
        if ln.get("isin"):
            b = by_isin[ln["isin"]]
            ln.update(name=b.get("name") or "", short=bd.short_label(b), kind=b.get("kind"))
            if not b.get("kind"):
                ln["why"] = "türü Bloomberg'den bekleniyor: değeri okunamaz"
    for ln in lines:
        if ln.get("isin") and not ln.get("why"):
            ln["used"] = False
    for isin in {ln["isin"] for ln in lines if ln.get("isin") and not ln.get("why")}:
        mine = [ln for ln in lines if ln.get("isin") == isin and not ln.get("why")]
        best = next((ln for ln in mine if ln["tn"] == 1), mine[0])
        best["used"] = True
        for ln in mine:
            if ln is not best:
                ln["unused"] = ("aynı kâğıdın .t1 satırı kullanıldı (satır %d)" % best["n"] if best["tn"] == 1 and ln["tn"] == 2
                                else "aynı kâğıdın satır %d'i kullanıldı" % best["n"])
    for ln in lines:
        if ln.get("why") and "date" in ln:
            ln["near"] = near(ln["date"], pool)


# ---------------------------------------------------------------------------------------------- price <-> yield (BIST)
def quoted_in_yield(kind: Optional[str]) -> bool:
    """A DİBS quoted in yield (BIST's simple yield): fixed coupon, bill, zero."""
    return kind in YIELD_KINDS


def quoted_of(kind: Optional[str]) -> str:
    """What a row's spreads move: "yield" (a DİBS quoted in yield, a Eurobond) or "price" (TLREF, FRN, TÜFE)."""
    return "yield" if kind in YIELD_KINDS or kind == EURO else "price"


def bond_of(rec: Dict[str, Any]) -> Optional[qc.Bond]:
    """The bond as quantcurve prices it (BIST): a bill or zero coupon from its days, a fixed coupon bond from its coupons
    (semi-annual); None for a price-quoted bond or one whose coupon is not known."""
    kind = rec.get("kind")
    if kind not in YIELD_KINDS or not rec.get("maturity"):
        return None
    mat = _dt.date.fromisoformat(rec["maturity"])
    if kind == "fixed":
        cpn = rec.get("coupon")
        if not isinstance(cpn, (int, float)) or not cpn > 0:
            return None
        return qc.Bond(rec["isin"], rec.get("name") or "", "fixed", mat, float(cpn), 2)
    return qc.Bond(rec["isin"], rec.get("name") or "", "bill", mat)


def yield_of(bond: qc.Bond, clean: float, value: _dt.date) -> Optional[float]:
    """BIST's simple yield (decimal) of a clean price at a value date: a bill's (100/P − 1)·365/days; a coupon bond's
    from its dirty price (+ the accrued interest of that date)."""
    if value >= bond.maturity or not clean > 0:
        return None
    if bond.kind == "bill":
        return (100.0 / clean - 1.0) * qc.YEAR / (bond.maturity - value).days
    y = bond.yield_of(clean + qc.accrued(bond, value), value, "simple", bond.coupon / 100.0 or 0.3)
    return y if y is not None and math.isfinite(y) else None


def price_of(bond: qc.Bond, y: float, value: _dt.date) -> Optional[float]:
    """The clean price at BIST's simple yield ``y`` (decimal) at a value date."""
    if value >= bond.maturity or y <= -0.99:
        return None
    p = bond.price(y, value, "simple")[0] - qc.accrued(bond, value)
    return p if math.isfinite(p) else None


def model_yield(bond: qc.Bond, nss: qc.Nss, value: _dt.date) -> Optional[float]:
    """The bond's simple yield on a curve: its cash flows after ``value`` discounted on it (times from ``value``)."""
    flows, _ = bond.flows(value)
    if not flows:
        return None
    pm = sum(cf * nss.df((d - value).days / qc.YEAR) for d, cf in flows)
    return bond.yield_of(pm, value, "simple", nss.zero(max((bond.maturity - value).days / qc.YEAR, 0.01)))


def simple_of_compound(bond: qc.Bond, yc: float, value: _dt.date) -> Optional[float]:
    """A compound (once a year) yield as the bond's simple one at a value date - kagitfiyat's ``Pricer.simple``."""
    days = float((bond.maturity - value).days)
    return kf.Pricer(bond.kind, value, days, bond.freq, [], 0.0, bond).simple(yc)


def bill_last(v: float, days: float, ref: Optional[float] = None) -> Tuple[Optional[float], str]:
    """A bill's (or zero coupon's) last trade as its simple yield (decimal), and how it was read: Bloomberg quotes TRY
    bills in price (DİBS RV!AS: 92,147 for a 99-day bill), so a price - unless the yield it gives is out of reach
    (``SANE_YIELD``) and the figure itself is a yield's (% - 31,4 for that bill would give 806 %); where both readings
    are in reach, the one nearer ``ref`` (the bill's yield on the sheet or the curve), else the price."""
    as_price = (100.0 / v - 1.0) * qc.YEAR / days if v > 0 and days > 0 else None
    as_yield = v / 100.0

    def sane(y: Optional[float]) -> bool:
        return y is not None and SANE_YIELD[0] <= y <= SANE_YIELD[1]

    if sane(as_price) and sane(as_yield) and ref is not None:
        if abs(as_yield - ref) < abs(as_price - ref):
            return as_yield, "getiri olarak okundu (%s; fiyat sayılsa getirisi %%%s olurdu)" % (_n(v, 3), _n(as_price * 100.0, 2))
        return as_price, "fiyat"
    if sane(as_price):
        return as_price, "fiyat"
    if sane(as_yield):
        return as_yield, "getiri olarak okundu (%s; fiyat sayılsa getirisi %%%s olurdu)" % (
            _n(v, 3), _n(as_price * 100.0, 0) if as_price is not None else "?")
    return None, "son işlem okunamadı: %s" % _n(v, 3)


def quote(kind: str, bond: Optional[qc.Bond], t0: _dt.date, t0_yield: Optional[float], t0_price: Optional[float],
          bid: float, ask: float) -> Dict[str, Optional[float]]:
    """The two sides at t0 from the spreads: a yield-quoted bond's bid yield = t0 + bid bp, ask yield = t0 − ask bp, each
    side's clean price at it; a price-quoted one's bid price = t0 − bid, ask price = t0 + ask (no yields).  Yields in %
    (simple), prices clean."""
    if quoted_in_yield(kind):
        if t0_yield is None or bond is None:
            return {"bid_yield": None, "ask_yield": None, "bid_price": None, "ask_price": None}
        by, ay = t0_yield + bid / BP, t0_yield - ask / BP
        return {"bid_yield": by * 100.0, "ask_yield": ay * 100.0, "bid_price": price_of(bond, by, t0), "ask_price": price_of(bond, ay, t0)}
    if t0_price is None:
        return {"bid_yield": None, "ask_yield": None, "bid_price": None, "ask_price": None}
    return {"bid_yield": None, "ask_yield": None, "bid_price": t0_price - bid, "ask_price": t0_price + ask}


# ---------------------------------------------------------------------------------------------- Eurobonds: the street convention
def edate(d: _dt.date, months: int) -> _dt.date:
    """``EDATE``: the same day ``months`` on, the month's last day where that month is shorter."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return _dt.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def basis_of(text: Any, ccy: str) -> Tuple[str, str]:
    """The day count of Bloomberg's ``DAY_CNT_DES``: "act" (ACT/ACT, ICMA), "30e" (ISMA's 30E/360), "30u" (30/360 US, the
    bond basis) - and how it was read; not said: a USD bond 30/360, any other ACT/ACT."""
    t = _said(text).upper()
    if "ACT/ACT" in t or "ACTUAL/ACTUAL" in t:
        return "act", t
    if "ISMA-30" in t or "30E" in t or "EURO" in t:
        return "30e", t
    if "30/360" in t:
        return "30u", t
    return ("30u", "30/360 (DAY_CNT_DES yok: USD'nin)") if ccy == "USD" else ("act", "ACT/ACT (DAY_CNT_DES yok)")


class Street(object):
    """A fixed-coupon Eurobond by the street convention (Excel's PRICE / YIELD, the SIA's): coupons of c/f every 12/f
    months back from the maturity (``EDATE``), the accrued interest c/f × A/E, the dirty price Σ CF / (1 + y/f)^(k + DSC/E)
    - in the last coupon period simple interest, (100 + c/f) / (1 + DSC/E · y/f).  30/360 (US or ISMA's): E = 360/f, DSC
    = E − A; ACT/ACT: the period's actual days and the days left.  A short first coupon (the settlement before ``first``,
    the accrual from ``start``) is that much smaller.  Clean prices per 100; yields decimal, compounded f times a year.
    There is no such bond in the workbook's own sheets (YP DIBS asks Bloomberg's YAS): the prices are anchored to
    Bloomberg's mid (``anchored``)."""

    __slots__ = ("mat", "c", "f", "basis", "step", "first", "start")

    def __init__(self, maturity: _dt.date, coupon: float, freq: int, basis: str, first: Optional[_dt.date] = None,
                 start: Optional[_dt.date] = None):
        self.mat, self.c = maturity, float(coupon or 0.0) / 100.0
        self.f = int(freq) if freq in (1, 2, 4, 12) else 2
        self.basis, self.step = basis, 12 // (int(freq) if freq in (1, 2, 4, 12) else 2)
        self.first, self.start = first, start

    def days(self, d1: _dt.date, d2: _dt.date) -> float:
        """The day count from ``d1`` to ``d2``."""
        if self.basis == "act":
            return float((d2 - d1).days)
        a, b = d1.day, d2.day
        if self.basis == "30e":
            a, b = min(a, 30), min(b, 30)
        else:                                            # 30/360 US: the end of February and the 31st
            feb1 = d1.month == 2 and a == calendar.monthrange(d1.year, 2)[1]
            feb2 = d2.month == 2 and b == calendar.monthrange(d2.year, 2)[1]
            if feb1 and feb2:
                b = 30
            if feb1:
                a = 30
            if b == 31 and a >= 30:
                b = 30
            if a == 31:
                a = 30
        return float(360 * (d2.year - d1.year) + 30 * (d2.month - d1.month) + (b - a))

    def at(self, s: _dt.date) -> Optional[Tuple[float, float, float, int, float, float]]:
        """At a settlement date: (E, A, DSC, the coupons left, a coupon, the next coupon) - None on or after the maturity."""
        if s >= self.mat:
            return None
        k = 0
        while edate(self.mat, -(k + 1) * self.step) > s:
            k += 1
        nxt, prv = edate(self.mat, -k * self.step), edate(self.mat, -(k + 1) * self.step)
        e = 360.0 / self.f if self.basis != "act" else float((nxt - prv).days)
        cpn = 100.0 * self.c / self.f
        a = self.days(prv, s)
        dsc = e - a if self.basis != "act" else float((nxt - s).days)
        first = cpn
        if self.first is not None and self.start is not None and s < self.first == nxt and prv < self.start < nxt:
            first = cpn * self.days(self.start, nxt) / e  # a short first coupon, accrued from the accrual start
            a = self.days(self.start, s)
        return e, a, dsc, k + 1, cpn, first

    def dirty(self, y: float, s: _dt.date) -> Optional[float]:
        got = self.at(s)
        if got is None or y <= -self.f:
            return None
        e, _, dsc, n, cpn, first = got
        w = dsc / e
        if n == 1:
            return (100.0 + first) / (1.0 + w * y / self.f)
        g = 1.0 + y / self.f
        return first / g ** w + sum(cpn / g ** (k + w) for k in range(1, n)) + 100.0 / g ** (n - 1 + w)

    def accrued(self, s: _dt.date) -> float:
        """c/f × A/E (in a short first period A runs from the accrual start)."""
        got = self.at(s)
        if got is None:
            return 0.0
        e, a, _, _, cpn, _ = got
        return cpn * a / e

    def clean(self, y: float, s: _dt.date) -> Optional[float]:
        d = self.dirty(y, s)
        return d - self.accrued(s) if d is not None else None

    def yield_of(self, clean: float, s: _dt.date, guess: Optional[float] = None) -> Optional[float]:
        """The yield of a clean price (Newton, to the last digit)."""
        y = guess if guess is not None else max(self.c, 0.01)
        for _ in range(60):
            p, up, dn = self.clean(y, s), self.clean(y + 1e-6, s), self.clean(y - 1e-6, s)
            if p is None or up is None or dn is None or up == dn:
                return None
            step = (p - clean) / ((up - dn) / 2e-6)
            y -= step
            if abs(step) < 1e-13:
                return y
        p = self.clean(y, s)
        return y if p is not None and abs(p - clean) < 1e-9 else None


def street_of(rec: Dict[str, Any]) -> Street:
    """A Eurobond's record (its Bloomberg facts) as a ``Street`` bond."""
    def day(k: str) -> Optional[_dt.date]:
        return _dt.date.fromisoformat(rec[k]) if rec.get(k) else None
    return Street(day("maturity"), rec.get("coupon") or 0.0, int(rec.get("freq") or 2), rec.get("basis") or "30u", day("first_cpn"),
                  day("acc_start"))


def anchored(bond: Street, s: _dt.date, mid_price: float, mid_yield: float) -> Optional[float]:
    """Bloomberg's mid against the street convention: PX_MID − the convention's price at Bloomberg's mid yield.  A price
    is then the convention's + this (the mid reproduces Bloomberg's exactly; a convention that differs moves the sides by
    its curvature only)."""
    p = bond.clean(mid_yield, s)
    return mid_price - p if p is not None else None


def _said(v: Any) -> str:
    """What Bloomberg answered as text ("" for none: an error, "#N/A ...", nothing)."""
    if isinstance(v, str):
        s = v.strip()
        return "" if s.startswith("#") else s
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return repr(v)
    return ""


def euro_record(isin: str, facts: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """A Eurobond's record from Bloomberg's facts (``EURO_FACTS``): ``(record, "")`` or ``(None, why)`` - Bloomberg does
    not know it, a TL bond (DİBS: the catalog's), a floater, no maturity, no coupon."""
    typ = _said(facts.get("CPN_TYP")).upper()
    raw = facts.get("CRNCY")
    ccy = _said(raw).upper()
    if not ccy:
        bad = str(raw or "") + str(facts.get("CPN_TYP") or "")
        return None, ("Bloomberg bu ISIN'i tanımıyor" if "INVALID SECURITY" in bad.upper() else "Bloomberg kâğıdın bilgilerini vermedi")
    if ccy == "TRY":
        return None, "TL kâğıt: Eurobond değil (DİBS kataloğunda yok)"
    if any(w in typ for w in ("FLOAT", "VARIABLE", "FRN")):
        return None, "değişken kuponlu: yalnız sabit kuponlu Eurobond fiyatlanır"
    mat = date_said(facts.get("MATURITY"))
    if mat is None:
        return None, "vadesi yok (süresiz kâğıt fiyatlanmaz)"
    cpn = facts.get("CPN")
    if not isinstance(cpn, (int, float)) or isinstance(cpn, bool) or cpn < 0:
        return None, "kuponu bilinmiyor"
    freq = facts.get("CPN_FREQ")
    freq = int(freq) if isinstance(freq, (int, float)) and not isinstance(freq, bool) and int(freq) in (1, 2, 4, 12) else 2
    basis, how = basis_of(facts.get("DAY_CNT_DES"), ccy)
    lag = facts.get("DAYS_TO_SETTLE")
    lag = int(lag) if isinstance(lag, (int, float)) and not isinstance(lag, bool) and 0 <= lag <= 10 else None

    def iso(k: str) -> Optional[str]:
        d = date_said(facts.get(k))
        return d.isoformat() if d else None

    return {"isin": isin, "kind": EURO, "name": _said(facts.get("SECURITY_DES")) or _said(facts.get("NAME")) or isin,
            "issuer": _said(facts.get("NAME")), "ccy": ccy, "coupon": float(cpn), "freq": freq, "basis": basis, "basis_text": how,
            "maturity": mat.isoformat(), "first_cpn": iso("FIRST_CPN_DT"), "penult_cpn": iso("PENULTIMATE_CPN_DT"),
            "acc_start": iso("INT_ACC_DT"), "settle_days": lag}, ""


# ---------------------------------------------------------------------------------------------- the txt
def f3(v: float) -> str:
    """Three decimals, a dot (the file's): "100.200", "31.500"."""
    return "%.3f" % v


def txt_line(isin: str, kind: Optional[str], bid_price: Optional[float], ask_price: Optional[float], bid_yield: Optional[float],
             ask_yield: Optional[float]) -> Optional[str]:
    """``ISIN,pricebid,priceask,yieldbid,yieldask``: a bill's or zero coupon's two yields (%, simple) with the prices 0,
    any other bond's two clean prices with the yields 0 ("hangisi yazıldıysa diğerleri 0"); None when the side written
    has no figure."""
    if kind in WRITE_YIELD:
        if bid_yield is None or ask_yield is None:
            return None
        return "%s,0,0,%s,%s" % (isin, f3(bid_yield), f3(ask_yield))
    if bid_price is None or ask_price is None or not (bid_price > 0 and ask_price > 0):
        return None
    return "%s,%s,%s,0,0" % (isin, f3(bid_price), f3(ask_price))


def txt(lines: Sequence[str]) -> str:
    """The file: every line ended with CRLF."""
    return "".join(line + "\r\n" for line in lines)


def file_name(day: _dt.date) -> str:
    return "dibs_fiyat_%s.txt" % day.strftime("%Y%m%d")


# ---------------------------------------------------------------------------------------------- the page
class FiyatYukleme(object):
    """The page's data and actions (``/api/fiyat-yukleme…``): each user's list, the desk's labels and auction values,
    Hesapla in both modes, the edits' conversions and the file."""

    def __init__(self, svc):
        self.svc = svc
        self._lock = threading.Lock()                                   # the store's read-modify-writes
        self._asked: Dict[str, Tuple[float, Dict[str, Any]]] = {}       # BBG answers by security: (when, answer)
        self._closes: Optional[Tuple[Any, Dict[str, Any]]] = None       # (history revision and day, the bonds' closes)
        self._fits: Dict[Any, Optional[qc.Nss]] = {}                     # a past day's bond curve, by what it is made of

    # ------------------------------------------------------------------ what is kept
    def _today(self) -> Tuple[_dt.date, _dt.date, frozenset]:
        """Today (the calculation's: offline the recorded file's), t0 and the TRY holidays (Motor's list)."""
        today = self.svc._bond_day()
        hol = frozenset(self.svc.holiday_dates(("TRY",)))
        return today, t0_of(today, hol), hol

    def _load(self, key: str) -> Dict[str, Any]:
        st = self.svc.store.get(KEY_LIST % key)
        st = st if isinstance(st, dict) else {}
        d = st.get("defaults") if isinstance(st.get("defaults"), dict) else {}
        defaults = {k: float(d[k]) if isinstance(d.get(k), (int, float)) else v for k, v in DEFAULTS.items()}
        bonds = [b for b in (st.get("bonds") or []) if isinstance(b, dict) and b.get("isin")]
        fixed = [f for f in (st.get("fixed") or []) if isinstance(f, dict) and f.get("isin") and isinstance(f.get("bid"), (int, float))
                 and isinstance(f.get("ask"), (int, float))]
        return {"bonds": bonds, "defaults": defaults, "mode": st.get("mode") if st.get("mode") in MODES else "ihale",
                "text": st.get("text") if isinstance(st.get("text"), str) else "", "fixed": fixed}

    def _save(self, key: str, st: Dict[str, Any]) -> None:
        self.svc.store.put(KEY_LIST % key, st)

    def labels(self) -> Dict[str, Dict[str, Any]]:
        got = self.svc.store.get(KEY_LABELS)
        return got if isinstance(got, dict) else {}

    def auctions(self) -> Dict[str, List[Dict[str, Any]]]:
        got = self.svc.store.get(KEY_AUCTIONS)
        return got if isinstance(got, dict) else {}

    def euro_store(self) -> Dict[str, Dict[str, Any]]:
        """The Eurobonds' facts, desk-wide (Bloomberg asked once an ISIN): ISIN -> record (``euro_record``)."""
        got = self.svc.store.get(KEY_EURO)
        return got if isinstance(got, dict) else {}

    def record(self, isin: str) -> Dict[str, Any]:
        """The bond's record: the DİBS catalog's (or the desk's addition; its maturity from the ISIN while Bloomberg has not
        told its kind), else a Eurobond's facts kept here."""
        return bd.by_isin(isin) or self.euro_store().get(isin) or bd.waiting(isin)

    @staticmethod
    def spreads_of(entry: Dict[str, Any], kind: Optional[str], defaults: Dict[str, float]) -> Dict[str, Any]:
        """A row's two spreads: its own, else the defaults of its kind - bp for a DİBS quoted in yield, price points for
        one quoted in price, a Eurobond's own pair in bp of its yield."""
        unit = "bp" if quoted_of(kind) == "yield" else "price"
        pre = "euro_" if kind == EURO else ("yield_" if unit == "bp" else "price_")
        bid, ask = entry.get("bid"), entry.get("ask")
        return {"bid": float(bid) if isinstance(bid, (int, float)) else defaults[pre + "bid"],
                "ask": float(ask) if isinstance(ask, (int, float)) else defaults[pre + "ask"],
                "own_bid": isinstance(bid, (int, float)), "own_ask": isinstance(ask, (int, float)), "unit": unit}

    def _rows(self, st: Dict[str, Any]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """The list's bonds with their records, by kind and maturity."""
        out = [(e, self.record(e["isin"])) for e in st["bonds"]]
        out.sort(key=lambda x: (ORDER.index(x[1]["kind"]) if x[1].get("kind") in ORDER else 9, x[1].get("maturity") or "9999",
                                x[0]["isin"]))
        return out

    def state(self, user: Optional[str]) -> Dict[str, Any]:
        """``GET /api/fiyat-yukleme``: the user's list (each bond's description, maturity, kind, spreads), the mode, the
        defaults, the last pasted text, the desk's labels, today's saved files."""
        key = self.svc.require_user(user)
        st = self._load(key)
        today, t0, _ = self._today()
        rows = []
        for e, rec in self._rows(st):
            rows.append(dict(brief(rec), quoted=quoted_of(rec.get("kind")), write="yield" if rec.get("kind") in WRITE_YIELD else "price",
                             spread=self.spreads_of(e, rec.get("kind"), st["defaults"])))
        return {"mode": st["mode"], "modes": [{"id": m, "text": MODE_TEXT[m]} for m in MODES], "defaults": st["defaults"],
                "text": st["text"], "list": rows, "fixed": self.fixed_rows(st), "labels": self.label_rows(),
                "saved": self.saved_today(key, today), "today": today.isoformat(), "t0": t0.isoformat(),
                "live": self.svc.mode == "live", "limits": LIMITS, "file": file_name(today), "gen": self.svc.gen}

    def fixed_rows(self, st: Dict[str, Any]) -> List[Dict[str, Any]]:
        """The user's fixed bonds as the page's "Sabit fiyatlar" table lists them: the bond (description, maturity), the unit
        its two figures are in (the txt's: a bill's / zero's yields, any other's clean prices), the figures, the file line
        they give, when they were set, in the list too."""
        listed = {b["isin"] for b in st["bonds"]}
        out = []
        for f in st["fixed"]:
            rec = self.fixed_record(f["isin"])
            unit = "yield" if rec.get("kind") in WRITE_YIELD else "price"
            line = txt_line(f["isin"], "bill" if unit == "yield" else None, f["bid"], f["ask"], f["bid"], f["ask"])
            out.append(dict(brief(rec), unit=unit, bid=f["bid"], ask=f["ask"], line=line, at=f.get("at") or "", listed=f["isin"] in listed))
        out.sort(key=lambda r: row_order(r))
        return out

    def fixed_record(self, isin: str) -> Dict[str, Any]:
        """A fixed price's bond, with or without the dashboard knowing it ("No catalog needed for a fixed row"): the DİBS
        catalog's record, else a Eurobond's facts if held, else what its ISIN says - a Turkish one's maturity
        (``bonds.maturity_of``: TR, the type letter, DDMMYY), "TRB…" a bill (its yields), "TRT…F…" an FX-denominated DİBS
        ("döviz DİBS", in price) - and nothing else (no description, in price).  Bloomberg is never asked."""
        rec = bd.by_isin(isin)
        if rec is not None and rec.get("kind"):
            return rec
        euro = self.euro_store().get(isin)
        if euro:
            return euro
        mat = bd.maturity_of(isin)
        kind = "bill" if isin.startswith("TRB") and mat else (FX_DIBS_KIND if _FX_DIBS.match(isin) else None)
        return {"isin": isin, "kind": kind, "maturity": mat.isoformat() if mat else None, "coupon": None, "fixed_only": True,
                "name": "döviz DİBS" if kind == FX_DIBS_KIND else ""}

    def fixed_unit(self, isin: str) -> str:
        """The unit a fixed price is typed and written in: a bill's / zero's yields, any other's clean prices."""
        return "yield" if self.fixed_record(isin).get("kind") in WRITE_YIELD else "price"

    def label_rows(self) -> List[Dict[str, Any]]:
        out = []
        for k, v in sorted(self.labels().items()):
            rec = bd.by_isin(v.get("isin") or "")
            out.append({"key": k, "label": v.get("label") or k, "isin": v.get("isin"), "short": bd.short_label(rec) if rec else "",
                        "name": (rec or {}).get("name") or "", "by": v.get("by") or "", "at": v.get("at") or ""})
        return out

    # ------------------------------------------------------------------ the list
    def add(self, user: Optional[str], text: Any) -> Dict[str, Any]:
        """Bonds onto the user's list: one ISIN or a pasted list (lines, commas).  A bond the desk's catalog has comes in
        at once; a Turkish ISIN it does not have through the desk's route (``Service.bond_list_add``: Bloomberg says what it
        is, and it joins Tüm Kâğıtlar for everyone); any other - and a TR one Bloomberg says is in a foreign currency - as a
        Eurobond, its facts asked of Bloomberg once and kept here (never in the DİBS catalog: "foreign-currency bonds are
        not taken").  Without Bloomberg neither can come in."""
        from .store import now_iso
        svc = self.svc
        key = svc.require_user(user)
        codes = svc._isins([text])
        if not codes:
            raise FiyatError("eklenecek ISIN yok")
        today, _, _ = self._today()
        refused = self._admit(key, codes)
        gone = {r["isin"] for r in refused}
        added, skipped = [], []
        with self._lock:
            st = self._load(key)
            have = {b["isin"] for b in st["bonds"]}
            for c in codes:
                if c in gone:
                    continue
                if c in have:
                    skipped.append(c)
                    continue
                rec = self.record(c)
                if rec.get("maturity") and rec["maturity"] < today.isoformat():
                    refused.append({"isin": c, "text": "vadesi geçmiş"})
                    continue
                if len(st["bonds"]) >= LIST_MAX:
                    refused.append({"isin": c, "text": "liste dolu (%d kâğıt)" % LIST_MAX})
                    continue
                st["bonds"].append({"isin": c, "bid": None, "ask": None, "at": now_iso()})
                have.add(c)
                added.append(c)
            if added:
                self._save(key, st)
        return dict(self.state(key), added=added, skipped=skipped, refused=refused)

    def _admit(self, key: str, codes: List[str]) -> List[Dict[str, Any]]:
        """The ISINs the dashboard does not know yet, made known (the list's and the fixed prices' one route): a Turkish one
        through the desk's (``Service.bond_list_add``), any other - and a TR one Bloomberg says is in a foreign currency -
        as a Eurobond (its facts asked once).  Without Bloomberg neither; the ones refused, with why."""
        svc = self.svc
        refused: List[Dict[str, Any]] = []
        euro = self.euro_store()
        unknown = [c for c in codes if not (bd.by_isin(c) or {}).get("kind") and c not in euro]
        if not unknown:
            return refused
        if svc.mode != "live":
            for c in unknown:
                refused.append({"isin": c, "text": "türü Bloomberg'den bekleniyor: Bloomberg olmadan eklenemez" if bd.by_isin(c)
                                else "kâğıt kataloğunda yok: Bloomberg olmadan eklenemez (kayıtlı veriyle çalışıyor)" if c.startswith("TR")
                                else "Eurobond'un bilgileri (vade, kupon, gün sayımı) Bloomberg'den gelir: kayıtlı veriyle çalışırken "
                                     "eklenemez"})
            return refused
        other = [c for c in unknown if not c.startswith("TR")]
        tr = [c for c in unknown if c.startswith("TR")]
        if tr:
            got = svc.bond_list_add(key, tr)
            for r in got.get("refused") or []:
                if str(r.get("why") or "").startswith("fx:"):
                    other.append(r["isin"])                         # a TR bond in a foreign currency: a Eurobond here
                else:
                    refused.append({"isin": r["isin"], "text": r["text"]})
        if other:
            refused += self._add_eurobonds(key, other)
        return refused

    # ------------------------------------------------------------------ fixed prices ("Sabit fiyat")
    def set_fixed(self, user: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
        """A bond's fixed bid and ask (the desk, 20.11.2026: "Bir de sabit fiyat kısmı açmalıyız, bazı kağıtları direkt bu
        şekilde yüklenecek diye girip bırakabilmeliyim"): ``{"isin", "bid", "ask"}`` in the unit the txt writes it in - a
        bill's / zero's simple yields (%), any other's clean prices -, the page's number reading (a Turkish comma too).  Only
        the ISIN and the two figures are needed: no catalog, no Bloomberg (``fixed_record``).  Set again, its figures
        change; they stay until changed or taken off.  A crossed pair is kept (an edit may pass through one) and said."""
        svc = self.svc
        key = svc.require_user(user)
        body = body if isinstance(body, dict) else {}
        codes = svc._isins([body.get("isin")])
        if len(codes) != 1:
            raise FiyatError("tek bir ISIN girin")
        bid, ask = num(body.get("bid")), num(body.get("ask"))
        if bid is None or ask is None:
            raise FiyatError("bid ve ask'i sayı olarak girin")
        today, _, _ = self._today()
        why = self._fixed_why(codes[0], bid, ask, today)
        if why:
            raise FiyatError(why)
        with self._lock:
            st = self._load(key)
            if self._put_fixed(st, codes[0], bid, ask) is None:
                raise FiyatError("sabit fiyat listesi dolu (%d kâğıt)" % LIST_MAX)
            self._save(key, st)
        crossed = bid < ask if self.fixed_unit(codes[0]) == "yield" else bid > ask
        return dict(self.state(key), fixed_set=codes[0], crossed=crossed)

    def _fixed_why(self, code: str, bid: float, ask: float, today: _dt.date) -> str:
        """Why a fixed price cannot be kept ("" when it can): a bond past its maturity, a figure out of reach for its unit
        (a yield −50 … 500 %, a price 0 … 1000)."""
        rec = self.fixed_record(code)
        if rec.get("maturity") and rec["maturity"] < today.isoformat():
            return "%s: vadesi geçmiş" % code
        in_yield = rec.get("kind") in WRITE_YIELD
        lo, hi = (-50.0, 500.0) if in_yield else (0.0, 1000.0)
        if not all(lo < v < hi for v in (bid, ask)):
            return "%s %s olarak girilir: %s ile %s arasında olmalı" % (code, "getiri (%)" if in_yield else "temiz fiyat", _n(lo, 0), _n(hi, 0))
        return ""

    @staticmethod
    def _put_fixed(st: Dict[str, Any], code: str, bid: float, ask: float) -> Optional[bool]:
        """A fixed price into the user's state (``st``, in place): True when it was new, False when it changed one, None
        when the list is full."""
        from .store import now_iso
        left = [f for f in st["fixed"] if f["isin"] != code]
        new = len(left) == len(st["fixed"])
        if new and len(left) >= LIST_MAX:
            return None
        st["fixed"] = left + [{"isin": code, "bid": round(bid, 6), "ask": round(ask, 6), "at": now_iso()}]
        return new

    def paste_fixed(self, user: Optional[str], text: Any) -> Dict[str, Any]:
        """"Ekle / Güncelle": fixed prices pasted from Excel (``parse_fixed``), a bond already fixed updated.  The state with
        the report: how many were added and updated, the lines that could not be read (and why), the ones ignored."""
        key = self.svc.require_user(user)
        text = str(text or "")
        if not text.strip():
            raise FiyatError("Excel'den ISIN, bid ve offer'ı kopyalayıp yapıştırın")
        if len(text) > TEXT_MAX:
            raise FiyatError("metin çok uzun (en çok %d karakter)" % TEXT_MAX)
        got = parse_fixed(text, self.fixed_unit)
        today, _, _ = self._today()
        added, updated, bad = [], [], list(got["bad"])
        with self._lock:
            st = self._load(key)
            for r in got["rows"]:
                why = self._fixed_why(r["isin"], r["bid"], r["ask"], today)
                new = None if why else self._put_fixed(st, r["isin"], r["bid"], r["ask"])
                if why or new is None:
                    bad.append({"n": r["n"], "text": r["text"], "why": why or "sabit fiyat listesi dolu (%d kâğıt)" % LIST_MAX})
                elif new:
                    added.append(r["isin"])
                elif r["isin"] not in added:
                    updated.append(r["isin"])
            if added or updated:
                self._save(key, st)
        bad.sort(key=lambda x: x["n"])
        return dict(self.state(key), pasted={"added": added, "updated": updated, "bad": bad, "ignored": len(got["ignored"])})

    def remove_fixed(self, user: Optional[str], isin: Any) -> Dict[str, Any]:
        key = self.svc.require_user(user)
        code = "".join(str(isin or "").split()).upper()
        with self._lock:
            st = self._load(key)
            left = [f for f in st["fixed"] if f["isin"] != code]
            if len(left) == len(st["fixed"]):
                raise FiyatError("sabit fiyatı yok: %s" % (code or "(boş)"))
            st["fixed"] = left
            self._save(key, st)
        return dict(self.state(key), fixed_removed=code)

    def _add_eurobonds(self, key: str, codes: List[str]) -> List[Dict[str, Any]]:
        """Eurobonds' facts (``EURO_FACTS``), asked of Bloomberg once - one request for all of them, then kept desk-wide
        (``KEY_EURO``): never asked again for that ISIN.  The ones that cannot be had, with why."""
        from .store import now_iso
        svc = self.svc
        secs = {c: svc._bbg_security(c) for c in codes}
        got = svc.provider.reference(sorted(set(secs.values())), EURO_FACTS, timeout=BBG_WAIT)
        if got is None:
            return [{"isin": c, "text": "Bloomberg yanıt vermedi ya da günlük istek sınırı doldu: Eurobond eklenemedi"} for c in codes]
        refused = []
        with self._lock:
            store = self.euro_store()
            for c, sec in secs.items():
                rec, why = euro_record(c, got.get(sec) or {})
                if rec is None:
                    refused.append({"isin": c, "text": why})
                else:
                    store[c] = dict(rec, by=key, at=now_iso())
            self.svc.store.put(KEY_EURO, store)
        return refused

    def remove(self, user: Optional[str], isin: Any) -> Dict[str, Any]:
        key = self.svc.require_user(user)
        code = "".join(str(isin or "").split()).upper()
        with self._lock:
            st = self._load(key)
            left = [b for b in st["bonds"] if b["isin"] != code]
            if len(left) == len(st["bonds"]):
                raise FiyatError("kâğıt listede değil: %s" % (code or "(boş)"))
            st["bonds"] = left
            self._save(key, st)
        return dict(self.state(key), removed=code)

    def _spread(self, v: Any, unit: str, what: str) -> Optional[float]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        x = num(v)
        lim = LIMITS[unit]
        if x is None or abs(x) > lim:
            raise FiyatError("%s %s: −%s ile %s arasında bir sayı olmalı" % (what, "(bp)" if unit == "bp" else "(fiyat)", _n(lim, 2 if unit == "price" else 0),
                                                                          _n(lim, 2 if unit == "price" else 0)))
        return round(x, 4)

    def set_options(self, user: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
        """The user's settings: ``{"mode"?, "defaults"?: {yield_bid, yield_ask, price_bid, price_ask}, "spreads"?: {isin:
        {"bid", "ask"} - a side left empty uses the default}}``."""
        key = self.svc.require_user(user)
        body = body if isinstance(body, dict) else {}
        with self._lock:
            st = self._load(key)
            if "mode" in body:
                if body["mode"] not in MODES:
                    raise FiyatError("mod BBG ya da İhale olmalı")
                st["mode"] = body["mode"]
            if isinstance(body.get("defaults"), dict):
                for k, v in body["defaults"].items():
                    if k not in DEFAULTS:
                        raise FiyatError("bilinmeyen ayar: %s" % k)
                    x = self._spread(v, "price" if k.startswith("price") else "bp", "varsayılan spread")
                    if x is None:
                        raise FiyatError("varsayılan spread boş olamaz")
                    st["defaults"][k] = x
            if isinstance(body.get("spreads"), dict):
                mine = {b["isin"]: b for b in st["bonds"]}
                for isin, sides in body["spreads"].items():
                    code = "".join(str(isin or "").split()).upper()
                    if code not in mine:
                        raise FiyatError("kâğıt listede değil: %s" % code)
                    unit = "bp" if quoted_of(self.record(code).get("kind")) == "yield" else "price"
                    sides = sides if isinstance(sides, dict) else {"bid": None, "ask": None}
                    for side in ("bid", "ask"):
                        if side in sides:
                            mine[code][side] = self._spread(sides[side], unit, "%s spread'i (%s)" % (side, code))
            self._save(key, st)
        return self.state(key)

    # ------------------------------------------------------------------ the desk's labels
    def name_label(self, user: Optional[str], label: Any, isin: Any) -> Dict[str, Any]:
        """The desk names an auction label's bond, for good (everyone may - as the bond list: "everyone edits it"); an
        empty ISIN forgets it."""
        from .store import now_iso
        key = self.svc.require_user(user)
        text = _TN.sub("", " ".join(str(label or "").split()))
        line = (parse(text + ".t1 1")["lines"] or [{}])[0] if text else {}
        if not line.get("key"):
            raise FiyatError("etiket okunamadı: %s (ör. 10/02/2027zc)" % (text or "(boş)"))
        code = "".join(str(isin or "").split()).upper()
        with self._lock:
            labels = self.labels()
            if not code:
                if labels.pop(line["key"], None) is None:
                    raise FiyatError("bu etiket tanıtılmamış: %s" % line["key"])
            else:
                if not bd.isin_valid(code):
                    raise FiyatError("ISIN değil ya da kontrol hanesi tutmuyor: %s" % code)
                rec = bd.by_isin(code)
                if rec is None:
                    raise FiyatError("kâğıt kataloğunda yok: %s - önce listeye ekleyin (Bloomberg'den türü gelir)" % code)
                labels[line["key"]] = {"isin": code, "label": line.get("label") or line["key"], "by": key, "at": now_iso()}
            self.svc.store.put(KEY_LABELS, labels)
        return {"labels": self.label_rows()}

    # ------------------------------------------------------------------ Hesapla
    def calculate(self, user: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
        """Hesapla: ``{"mode": "ihale" | "bbg", "text"}`` - every bond of the user's list at t0, its bid and ask by its
        spreads; İhale mode reads (and keeps) the pasted auction text."""
        key = self.svc.require_user(user)
        body = body if isinstance(body, dict) else {}
        with self._lock:
            st = self._load(key)
            mode = body.get("mode") or st["mode"]
            if mode not in MODES:
                raise FiyatError("mod BBG ya da İhale olmalı")
            st["mode"] = mode
            if "text" in body:
                text = str(body.get("text") or "")
                if len(text) > TEXT_MAX:
                    raise FiyatError("metin çok uzun (en çok %d karakter)" % TEXT_MAX)
                st["text"] = text
            self._save(key, st)
        today, t0, hol = self._today()
        rows = self._rows(st)
        # fixed bonds: as they are, whatever the mode - not computed, no Bloomberg asked for them (in the list too: fixed wins)
        fixed = {f["isin"]: f for f in st["fixed"]}
        listed = {e["isin"] for e, _ in rows}
        rows = [(e, rec) for e, rec in rows if e["isin"] not in fixed]
        # Eurobonds: Bloomberg's mid whatever the switch says - never an auction or a last trade
        euro = [(e, rec) for e, rec in rows if rec.get("kind") == EURO]
        rows = [(e, rec) for e, rec in rows if rec.get("kind") != EURO]
        if mode == "ihale":
            if not st["text"].strip():
                if rows or not (euro or fixed):
                    raise FiyatError("İhale fiyatlarını yapıştırın")
                res: Dict[str, Any] = {"rows": []}                  # (nothing here needs the auction)
            else:
                res = self._ihale(key, st, rows, today, t0, hol)
        elif rows:
            res = self._bbg(key, st, rows, today, t0, hol)
        else:
            res = {"rows": [], "bbg": {"asked": 0, "hits": 0, "cached": 0, "why": None, "trading": 0, "off": 0}}
        if euro:
            more, res["euro"] = self._euro(st, euro, today)
            res["rows"] = res["rows"] + more
        if fixed:
            res["rows"] = sorted(res["rows"] + [self._fixed_row(f, self.fixed_record(f["isin"]), st, t0, today, f["isin"] in listed)
                                                for f in fixed.values()], key=row_order)
            res["fixed"] = len(fixed)
        res.update(mode=mode, today=today.isoformat(), t0=t0.isoformat(), file=file_name(today), time=_dt.datetime.now().strftime("%H:%M:%S"))
        return res

    def _fixed_row(self, f: Dict[str, Any], rec: Dict[str, Any], st: Dict[str, Any], t0: _dt.date, today: _dt.date,
                   listed: bool) -> Dict[str, Any]:
        """A fixed bond's row as stored: its two figures in the txt's unit, written as they are; the other unit for
        information only, by the page's own conversions - a bill's / zero's price at t0 from the fixed yield, a fixed coupon
        bond's yield at t0 from the fixed price, a Eurobond's by the street convention at its settlement (Bloomberg not
        asked: no anchor); a TLREF / TÜFE / FRN bond has no yield.  No auction, no Bloomberg, no curve."""
        kind = rec.get("kind")
        row = self._row(f, rec, st, t0)
        bid, ask = float(f["bid"]), float(f["ask"])

        def pair(written: float, other: Optional[float], in_yield: bool) -> Dict[str, Optional[float]]:
            return {"yield": written, "price": other} if in_yield else {"price": written, "yield": other}

        if kind in WRITE_YIELD:
            bond = bond_of(rec)
            conv = [price_of(bond, v / 100.0, t0) if bond is not None else None for v in (bid, ask)]
            info = "fiyatlar bilgi için: sabit getiriden t0'da (%s)" % tr_day(t0)
        elif kind == EURO:
            settle, _ = self.euro_settle(rec, today)
            bond = street_of(rec)
            ys = [bond.yield_of(v, settle) for v in (bid, ask)]
            conv = [y * 100.0 if y is not None else None for y in ys]
            row.update(settle=settle.isoformat(), anchor=0.0, value_date=settle.isoformat())
            info = "getiriler bilgi için: sokak kuralıyla valör %s'de (Bloomberg'e sorulmadı, çapasız)" % tr_day(settle)
        elif kind == "fixed":
            bond = bond_of(rec)
            ys = [yield_of(bond, v, t0) if bond is not None else None for v in (bid, ask)]
            conv = [y * 100.0 if y is not None else None for y in ys]
            info = "getiriler bilgi için: sabit fiyattan t0'da (%s)" % tr_day(t0)
        else:
            conv = [None, None]
            info = ("getirisi yok: kâğıt kataloğunda değil (%s)" % (rec.get("name") or "bilinmiyor")) if rec.get("fixed_only") \
                else "fiyatla kote edilir: getirisi yok"
        in_yield = kind in WRITE_YIELD
        row.update(bid=pair(bid, conv[0], in_yield), ask=pair(ask, conv[1], in_yield), priced=True, source="sabit", fixed=True,
                   fixed_at=f.get("at") or "")
        row["how"] = "Sabit fiyat (%s girildi): dosyaya olduğu gibi yazılır; %s" % (str(f.get("at") or "")[:16], info)
        if listed:
            row["note"] = "listede de var: sabit fiyat geçerli (hesaplanmadı)"
        return row

    def _row(self, e: Dict[str, Any], rec: Dict[str, Any], st: Dict[str, Any], t0: _dt.date) -> Dict[str, Any]:
        kind = rec.get("kind")
        return dict(brief(rec), quoted=quoted_of(kind), write="yield" if kind in WRITE_YIELD else "price",
                    spread=self.spreads_of(e, kind, st["defaults"]), value_date=t0.isoformat(), priced=False, source=None,
                    t0={"yield": None, "price": None}, bid={"yield": None, "price": None}, ask={"yield": None, "price": None})

    def _price(self, row: Dict[str, Any], rec: Dict[str, Any], t0: _dt.date, t0_yield: Optional[float],
               t0_price: Optional[float]) -> None:
        """The row's t0 and its two sides (in place)."""
        bond = bond_of(rec)
        if quoted_in_yield(rec.get("kind")) and t0_yield is not None and bond is not None:
            t0_price = price_of(bond, t0_yield, t0)
        row["t0"] = {"yield": t0_yield * 100.0 if t0_yield is not None else None, "price": t0_price}
        sp = row["spread"]
        q = quote(rec["kind"], bond, t0, t0_yield, t0_price, sp["bid"], sp["ask"])
        row["bid"] = {"yield": q["bid_yield"], "price": q["bid_price"]}
        row["ask"] = {"yield": q["ask_yield"], "price": q["ask_price"]}
        row["priced"] = (q["bid_yield"] is not None) if rec["kind"] in WRITE_YIELD else (q["bid_price"] is not None)

    @staticmethod
    def _why_not(rec: Dict[str, Any]) -> Optional[str]:
        kind = rec.get("kind")
        if not kind:
            return "türü Bloomberg'den bekleniyor"
        if kind == "fixed" and bond_of(rec) is None:
            return "kuponu bilinmiyor"
        return None

    def _ihale(self, key: str, st: Dict[str, Any], rows: List[Tuple[Dict[str, Any], Dict[str, Any]]], today: _dt.date, t0: _dt.date,
               hol: frozenset) -> Dict[str, Any]:
        from .store import now_iso
        got = parse(st["text"])
        lines = got["lines"]
        pool = list(bd.catalog()) + [rec for _, rec in rows if not bd.by_isin(rec["isin"])]
        match(lines, self.labels(), pool)
        mine = {e["isin"] for e, _ in rows}
        for ln in lines:
            if ln.get("isin"):
                ln["in_list"] = ln["isin"] in mine
            if "tn" in ln and "value" in ln:
                ln["value_date"] = workday(today, ln["tn"], hol).isoformat()
        used = {ln["isin"]: ln for ln in lines if ln.get("used")}
        # the day's values, desk-wide: each bond's first line of each value date (a .t2 too - "the last auction price"
        # prefers .t1); the same day pasted again replaces them
        firsts: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for ln in lines:
            if ln.get("isin") and not ln.get("why"):
                firsts.setdefault((ln["isin"], ln["tn"]), ln)
        stamp = now_iso()
        with self._lock:
            book = self.auctions()
            for (isin, tn), ln in firsts.items():
                kept = [a for a in book.get(isin) or [] if not (a.get("day") == today.isoformat() and a.get("tn") == tn)]
                kept.append({"day": today.isoformat(), "label": ln["label"], "value": ln["value"], "tn": tn,
                             "value_date": ln["value_date"], "by": key, "at": stamp})
                kept.sort(key=lambda a: (a.get("day") or "", a.get("tn") or 0))
                book[isin] = kept[-AUCTIONS_KEPT:]
            if firsts:
                self.svc.store.put(KEY_AUCTIONS, book)
        out_rows = []
        for e, rec in rows:
            row = self._row(e, rec, st, t0)
            why = self._why_not(rec)
            ln = used.get(rec["isin"])
            if why:
                row["why"] = why
            elif ln is None:
                row["why"] = "bugünkü ihale listesinde yok"
            else:
                vd = _dt.date.fromisoformat(ln["value_date"])
                t0y, t0p, how = self._from_auction(rec, ln["value"], vd)
                if t0y is None and t0p is None:
                    row["why"] = how
                else:
                    self._price(row, rec, t0, t0y, t0p)
                    row["source"] = "ihale"
                    row["how"] = "İhale %s.t%d %s (valör %s) → %s" % (ln["label"], ln["tn"], _n(ln["value"], 3), tr_day(vd), how)
            out_rows.append(row)
        ok = [ln for ln in lines if ln.get("isin") and not ln.get("why")]
        return {"rows": out_rows, "parse": {"lines": lines, "ignored": got["ignored"], "recognised": len(ok),
                                            "unrecognised": sum(1 for ln in lines if ln.get("why")), "stored": len(firsts)}}

    @staticmethod
    def _from_auction(rec: Dict[str, Any], value: float, vd: _dt.date) -> Tuple[Optional[float], Optional[float], str]:
        """An auction value's t0 yield (decimal, simple) and / or price, and how: a bill's or zero's value is its simple
        yield (the same yield at t0), a fixed coupon bond's a clean price at the line's value date (its yield there; the
        same yield at t0), any other's a clean price used as t0's."""
        kind = rec.get("kind")
        if kind in ("bill", "zero"):
            return value / 100.0, None, "basit getiri %%%s, t0'da aynı getiri" % _n(value, 3)
        if kind == "fixed":
            bond = bond_of(rec)
            y = yield_of(bond, value, vd) if bond is not None else None
            if y is None:
                return None, None, "fiyattan getiri bulunamadı"
            return y, None, "temiz fiyat; getirisi %%%s (basit), t0'da aynı getiri" % _n(y * 100.0, 3)
        return None, value, "temiz fiyat, t0 fiyatı olarak (fiyatla kote edilir)"

    # ------------------------------------------------------------------ BBG
    def _read(self, user: str, isins: Sequence[str]) -> Dict[str, Any]:
        """(engine thread) DİBS RV's last trade of the list's bonds that are on it (``AS`` LAST_PRICE, ``I``
        LAST_TRADE_DATE, ``BS`` the source, ``S`` the simple yield in use), the trading list's bonds now for the bond curve
        (quantcurve's ``read_engine``), and how a bond off the list is named to Bloomberg (Tüm Kâğıtlar's sources
        ``EK_EVREN!C2`` / ``E2``, DİBS RV!N2)."""
        from . import extras as ex
        from . import rvfair
        from .xl.model import COLS, parse_a1
        svc = self.svc
        book = svc.books.get("tto")
        out: Dict[str, Any] = {"rv": {}, "quant": [], "live": {}, "src": ("ISL0", "ISL1"), "how": "ISIN"}
        if book is None or "DİBS RV" not in book.model.sheet_index:
            return out
        idx = book.model.sheet_index
        si = idx["DİBS RV"]
        calc = svc._calc(user, book)

        def raw(c: str, r: int, s: int = si) -> Any:
            return calc.get(s, r, parse_a1("%s1" % c) % COLS)

        want = set(isins)
        for r in range(rvfair.FIRST, rvfair.LAST + 1):
            code = rvfair.isin_of(raw("A", r))
            if code and code in want and code not in out["rv"]:
                out["rv"][code] = {"row": r, "last": raw("AS", r), "date": raw("I", r), "source": raw("BS", r), "simple": raw("S", r)}
        eng: Dict[str, Any] = {}

        def reader(sheet: str):
            s = idx[sheet]
            return lambda ref: calc.get(s, *divmod(parse_a1(ref), COLS))

        qc.read_engine(eng, idx, reader, lambda v: v if type(v) is float and math.isfinite(v) else None)
        out["quant"] = eng.get("dibs") or []
        out["live"] = qc.live_values(eng)
        uni = idx.get(ex.UNI_SHEET)
        if uni is not None:
            src = [raw(c, 2, uni) for c in ("C", "E")]
            out["src"] = tuple((s.strip().upper() if isinstance(s, str) and s.strip() else d) for s, d in zip(src, ("ISL0", "ISL1")))
        n2 = raw("N", 2)
        if isinstance(n2, str) and n2.strip():
            out["how"] = n2.strip()
        return out

    @staticmethod
    def security(isin: str, kind: Optional[str], src: Tuple[str, str], how: str) -> str:
        """How Tüm Kâğıtlar names a bond to Bloomberg (``EK_EVREN!U``): its source by kind - a bill's or zero's the
        first, any other's the second - and DİBS RV's identifier style ("TRT150328T24 @ISL1 ISIN", "/isin/…@ISL1")."""
        s = src[0] if kind in ("bill", "zero") else src[1]
        return "/isin/%s@%s" % (isin, s) if how.lower() == "/isin/" else "%s @%s %s" % (isin, s, how)

    def ask_bloomberg(self, secs: Sequence[str], fields: Sequence[str] = BBG_FIELDS
                      ) -> Tuple[Dict[str, Dict[str, Any]], int, Optional[str]]:
        """``fields`` of each security in one one-off request (``Provider.reference``: securities × fields hits, counted by
        ``--max-hits``) - the last trade of bonds off the trading list (LAST_PRICE, LAST_TRADE_DATE), a Eurobond's mid
        (PX_MID, YLD_YTM_MID) or its sides (PX_BID, PX_ASK) -, from an answer of the last ``CACHE_SECONDS`` where there is
        one; ``(answers by security, securities asked now, why none came)``."""
        now = time.time()
        what = tuple(fields)
        out: Dict[str, Dict[str, Any]] = {}
        todo = []
        for s in secs:
            hit = self._asked.get((s, what))
            if hit is not None and now - hit[0] < CACHE_SECONDS:
                out[s] = hit[1]
            else:
                todo.append(s)
        if not todo:
            return out, 0, None
        if self.svc.mode != "live":
            return out, 0, "Bloomberg yok (kayıtlı veriyle çalışıyor)"
        got = self.svc.provider.reference(todo, list(what), timeout=BBG_WAIT)
        if got is None:
            return out, 0, "Bloomberg yanıt vermedi ya da günlük istek sınırı doldu"
        stamp = time.time()
        for s in todo:
            ans = got.get(s) or {}
            self._asked[(s, what)] = (stamp, ans)
            out[s] = ans
        for s, (t, _) in list(self._asked.items()):
            if stamp - t >= CACHE_SECONDS:
                self._asked.pop(s, None)
        return out, len(todo), None

    def _bbg(self, key: str, st: Dict[str, Any], rows: List[Tuple[Dict[str, Any], Dict[str, Any]]], today: _dt.date, t0: _dt.date,
             hol: frozenset) -> Dict[str, Any]:
        svc = self.svc
        isins = [e["isin"] for e, _ in rows]
        got = svc.et.call(self._read, key, isins)
        secs = {rec["isin"]: self.security(rec["isin"], rec.get("kind"), got["src"], got["how"])
                for _, rec in rows if rec["isin"] not in got["rv"] and rec.get("kind")}
        answers, asked, why_none = self.ask_bloomberg(sorted(set(secs.values())), BBG_FIELDS)
        book = self.auctions()
        ctx: Dict[str, Any] = {"got": got, "today": today, "t0": t0, "hol": hol}
        out_rows = []
        for e, rec in rows:
            row = self._row(e, rec, st, t0)
            why = self._why_not(rec)
            if why:
                row["why"] = why
                out_rows.append(row)
                continue
            code = rec["isin"]
            rv = got["rv"].get(code)
            if rv is not None:
                last, day, source, where = rv["last"], date_said(rv["date"]), str(rv["source"] or "").strip().upper(), "DİBS RV"
                ref = rv["simple"] if type(rv["simple"]) is float else None
            else:
                ans = answers.get(secs.get(code, ""), {})
                last, day = ans.get("LAST_PRICE"), date_said(ans.get("LAST_TRADE_DATE"))
                sec = secs.get(code, "")
                source = sec.split("@")[1].split()[0].upper() if "@" in sec else ""
                where = "Bloomberg" if code in secs and sec in answers else ""
                ref = None
            last = last if type(last) is float and last > 0 else None
            notes = []
            if rv is None and why_none:
                notes.append(why_none)
            if last is not None and day == today:
                vd = today if source == "ISL0" else workday(today, 1, hol)
                t0y, t0p, how = self._from_trade(rec, last, vd, ref, book.get(code))
                if t0y is None and t0p is None:
                    row["why"] = how
                else:
                    self._price(row, rec, t0, t0y, t0p)
                    row["source"] = "bbg"
                    row["how"] = "%s son işlem %s %s (valör %s) → %s" % (where, tr_day(day), _n(last, 3), tr_day(vd), how)
            else:
                said = ("son işlem %s" % tr_day(day)) if day else "bugün işlem yok"
                if where == "" and rv is None:
                    said = "son işlem sorulamadı"
                a = last_auction(book.get(code))
                aday = _dt.date.fromisoformat(a["day"]) if a is not None else None
                if last is not None and day is not None and day < today and (aday is None or day > aday):
                    # a last trade newer than any auction kept: it is the reference, moved with the curve since its day
                    self._stale_trade(row, rec, last, day, source, where, ref, book.get(code), ctx)
                else:
                    self._stale(row, rec, book.get(code), ctx, said)
            if notes:
                row["note"] = " · ".join(notes + ([row["note"]] if row.get("note") else []))
            out_rows.append(row)
        return {"rows": out_rows, "bbg": {"asked": asked, "hits": asked * len(BBG_FIELDS), "cached": len(answers) - asked,
                                          "why": why_none, "trading": len(got["rv"]), "off": len(set(secs.values()))}}

    def _from_trade(self, rec: Dict[str, Any], last: float, vd: _dt.date, ref: Optional[float],
                    auctions: Optional[List[Dict[str, Any]]]) -> Tuple[Optional[float], Optional[float], str]:
        """Today's last trade as t0: a coupon bond's clean price at its value date → its yield, the same yield at t0; a
        bill's price (or yield: ``bill_last``) → its simple yield, the same at t0; any other's clean price as t0's."""
        kind = rec.get("kind")
        bond = bond_of(rec)
        if kind in ("bill", "zero") and bond is not None:
            if ref is None:
                a = last_auction(auctions)
                ref = a["value"] / 100.0 if a is not None else None
            y, how = bill_last(last, float((bond.maturity - vd).days), ref)
            if y is None:
                return None, None, how
            return y, None, "%s; basit getiri %%%s, t0'da aynı getiri" % (how, _n(y * 100.0, 3))
        if kind == "fixed" and bond is not None:
            y = yield_of(bond, last, vd)
            if y is None:
                return None, None, "fiyattan getiri bulunamadı"
            return y, None, "temiz fiyat; getirisi %%%s (basit), t0'da aynı getiri" % _n(y * 100.0, 3)
        return None, last, "temiz fiyat, t0 fiyatı olarak (fiyatla kote edilir)"

    def _stale(self, row: Dict[str, Any], rec: Dict[str, Any], auctions: Optional[List[Dict[str, Any]]], ctx: Dict[str, Any],
               said: str) -> None:
        """No trade today: the last auction moved with the curve (``move``); a price-quoted bond keeps the auction's
        price; without an auction, no price and why."""
        a = last_auction(auctions)
        t0 = ctx["t0"]
        if a is None:
            row["why"] = "%s ve kayıtlı ihale fiyatı yok" % said
            return
        aday = _dt.date.fromisoformat(a["day"])
        vd = _dt.date.fromisoformat(a["value_date"])
        t0y, t0p, how = self._from_auction(rec, a["value"], vd)
        if t0y is None and t0p is None:
            row["why"] = how
            return
        head = "%s → son ihale %s %s.t%d %s" % (said, tr_day(aday), a["label"], a["tn"], _n(a["value"], 3))
        if t0y is None:
            self._price(row, rec, t0, None, t0p)
            row["source"] = "ihale"
            row["how"] = head + ": " + how
            row["note"] = "fiyatla kote edilir: son ihale fiyatı"
            return
        bond = bond_of(rec)
        delta, text, warn = self.move(bond, aday, t0y, ctx)
        self._price(row, rec, t0, t0y + (delta or 0.0), None)
        row["source"] = "ihale+eğri"
        row["move_bp"] = delta * BP if delta is not None else None
        row["how"] = "%s (getiri %%%s) %s → t0 getirisi %%%s" % (head, _n(t0y * 100.0, 3), text, _n((t0y + (delta or 0.0)) * 100.0, 3))
        if warn:
            row["note"] = warn

    def _stale_trade(self, row: Dict[str, Any], rec: Dict[str, Any], last: float, day: _dt.date, source: str, where: str,
                     ref: Optional[float], auctions: Optional[List[Dict[str, Any]]], ctx: Dict[str, Any]) -> None:
        """No trade today, but a last trade newer than any auction kept (the desk, 20.11.2026: "dün işlem olmasına rağmen
        son işlem dün diyor ve göstermiyor"): that trade read at its own value date as today's would be
        (``_from_trade``), its yield moved with the bond curve since that day's close (``move``) - before the market
        opens, yesterday's last trade plus the night's move.  A price-quoted bond keeps the trade's price."""
        hol, t0 = ctx["hol"], ctx["t0"]
        vd = day if source == "ISL0" else workday(day, 1, hol)
        t0y, t0p, how = self._from_trade(rec, last, vd, ref, auctions)
        if t0y is None and t0p is None:
            row["why"] = how
            return
        head = "%s son işlem %s %s (valör %s)" % (where or "Bloomberg", tr_day(day), _n(last, 3), tr_day(vd))
        if t0y is None:
            self._price(row, rec, t0, None, t0p)
            row["source"] = "bbg"
            row["how"] = head + " → " + how
            row["note"] = "fiyatla kote edilir: son işlem fiyatı"
            return
        delta, text, warn = self.move(bond_of(rec), day, t0y, ctx, "son işlem getirisi")
        self._price(row, rec, t0, t0y + (delta or 0.0), None)
        row["source"] = "bbg+eğri"
        row["move_bp"] = delta * BP if delta is not None else None
        row["how"] = "%s → %s %s → t0 getirisi %%%s" % (head, how, text, _n((t0y + (delta or 0.0)) * 100.0, 3))
        if warn:
            row["note"] = warn

    # ------------------------------------------------------------------ Eurobonds: Bloomberg's mid, whatever the switch says
    def _euro(self, st: Dict[str, Any], rows: List[Tuple[Dict[str, Any], Dict[str, Any]]], today: _dt.date
              ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Every Eurobond of the list from Bloomberg's mid ("Bunlarda last trade yok direkt midden ve spreadden
        gideceğiz"): PX_MID and YLD_YTM_MID (2 hits a bond), PX_BID / PX_ASK only for a bond whose PX_MID is empty (2 more),
        each kept ``CACHE_SECONDS``; the sides by the yield spreads, their prices by the street convention anchored to the
        mid (``_price_euro``)."""
        svc = self.svc
        secs = {rec["isin"]: svc._bbg_security(rec["isin"]) for _, rec in rows}
        names = sorted(set(secs.values()))
        mids, asked, why = self.ask_bloomberg(names, EURO_MID)
        empty = [s for s in names if s in mids and not (type(mids[s].get("PX_MID")) is float and mids[s]["PX_MID"] > 0)]
        sides, asked2, why2 = self.ask_bloomberg(empty, EURO_SIDES) if empty else ({}, 0, None)
        out = []
        for e, rec in rows:
            row = self._row(e, rec, st, today)
            ans = mids.get(secs[rec["isin"]])
            if ans is None:
                row["why"] = "Eurobond yalnız Bloomberg'in mid'inden fiyatlanır: " + (why or "cevap yok")
            else:
                self._price_euro(row, rec, ans, sides.get(secs[rec["isin"]]) or {}, today)
            out.append(row)
        return out, {"asked": asked, "hits": len(EURO_MID) * asked + len(EURO_SIDES) * asked2, "cached": len(mids) - asked,
                     "sides": len(empty), "why": why or why2}

    def euro_settle(self, rec: Dict[str, Any], today: _dt.date) -> Tuple[_dt.date, str]:
        """The settlement Bloomberg's mid is for: today + the bond's own lag (Bloomberg's DAYS_TO_SETTLE, asked with its
        facts; without it ``EURO_LAG``) business days on its currency's calendar (USD: the Fed's, EUR: TARGET2 - the
        desk's lists, EK_TATIL) - and how."""
        ccy = rec.get("ccy") or ""
        hol = frozenset(self.svc.holiday_dates((ccy,))) if ccy in ("USD", "EUR") else frozenset()
        lag = rec.get("settle_days")
        n = int(lag) if isinstance(lag, int) else EURO_LAG
        day = today
        while n > 0:
            day += _dt.timedelta(days=1)
            if day.weekday() < 5 and day not in hol:
                n -= 1
        how = "T+%d %s takvimiyle (%s)" % (int(lag) if isinstance(lag, int) else EURO_LAG, ccy or "hafta içi",
                                          "Bloomberg DAYS_TO_SETTLE" if isinstance(lag, int) else "varsayılan: Bloomberg DAYS_TO_SETTLE vermedi")
        return day, how

    def _price_euro(self, row: Dict[str, Any], rec: Dict[str, Any], mid: Dict[str, Any], sides: Dict[str, Any], today: _dt.date) -> None:
        """A Eurobond's row (in place): mid = PX_MID (else (PX_BID + PX_ASK)/2, said) and YLD_YTM_MID; bid yield = mid +
        bid bp, ask yield = mid − ask bp; each side's clean price by the street convention at Bloomberg's settlement plus
        the anchor (PX_MID − the convention's price at the mid yield: shown, flagged beyond ``ANCHOR_WARN``)."""
        def px(v: Any) -> Optional[float]:
            return v if type(v) is float and v > 0 else None

        bond = street_of(rec)
        settle, settle_how = self.euro_settle(rec, today)
        price, used = px(mid.get("PX_MID")), "PX_MID"
        if price is None and px(sides.get("PX_BID")) and px(sides.get("PX_ASK")):
            price, used = (sides["PX_BID"] + sides["PX_ASK"]) / 2.0, "(PX_BID + PX_ASK)/2 (PX_MID boş)"
        y = mid.get("YLD_YTM_MID")
        y = y / 100.0 if type(y) is float else None
        notes = []
        if price is None and y is None:
            row["why"] = "Bloomberg'de mid yok (PX_MID, YLD_YTM_MID ve PX_BID / PX_ASK boş)"
            return
        if y is None:
            y = bond.yield_of(price, settle)
            anchor = 0.0
            notes.append("YLD_YTM_MID yok: getiri fiyattan sokak kuralıyla")
        elif price is None:
            price = bond.clean(y, settle)
            anchor = 0.0
            used = "YLD_YTM_MID'den sokak kuralıyla (fiyat yok)"
        else:
            anchor = anchored(bond, settle, price, y)
        if y is None or price is None or anchor is None:
            row["why"] = "vadesi geçmiş ya da Bloomberg'in mid'i sokak kuralıyla okunamadı"
            return
        sp = row["spread"]
        by, ay = y + sp["bid"] / BP, y - sp["ask"] / BP
        pb, pa = bond.clean(by, settle), bond.clean(ay, settle)
        row["t0"] = {"yield": y * 100.0, "price": price}
        row["bid"] = {"yield": by * 100.0, "price": pb + anchor if pb is not None else None}
        row["ask"] = {"yield": ay * 100.0, "price": pa + anchor if pa is not None else None}
        row["priced"] = row["bid"]["price"] is not None and row["ask"]["price"] is not None
        row.update(source="bbg-mid", value_date=settle.isoformat(), settle=settle.isoformat(), anchor=anchor)
        row["how"] = ("Bloomberg mid %s %s, YLD_YTM_MID %%%s (valör %s: %s) → getiriler ± spread; fiyatlar sokak kuralıyla (%s, yılda %d "
                      "kupon), Bloomberg'in mid'ine çapalı: çapa farkı %s fiyat puanı") % (
            used, _n(price, 3), _n(y * 100.0, 3), tr_day(settle), settle_how, rec.get("basis_text") or rec.get("basis"), bond.f,
            ("%+.3f" % anchor).replace(".", ","))
        if abs(anchor) > ANCHOR_WARN:
            notes.append("sokak kuralı Bloomberg'in mid'inden %s fiyat puanı farklı (> 0,05): gün sayımını / kupon takvimini kontrol edin"
                         % _n(abs(anchor), 3))
        if notes:
            row["note"] = " · ".join(notes)

    # ------------------------------------------------------------------ the curve's move since an auction
    def move(self, bond: qc.Bond, aday: _dt.date, level: float, ctx: Dict[str, Any],
             what: str = "son ihale getirisi") -> Tuple[Optional[float], str, Optional[str]]:
        """The bond curve's change at the bond since the reference's day's close - the last auction's, or the last trade's
        (``what``, said when nothing can be measured) - (decimal, the bond's simple yield):
        the Nelson-Siegel fit of the trading list's yields now (DİBS RV · Genel's) − the same fit (its τ held) of that
        day's closes, the bond's cash flows from t0 on both - the curve's move, not the bond's roll-down; an auction of
        today: none.  Without the fit: the TRY OIS Bootstrap zero rate's change at the bond's maturity, as the change of
        the bond's simple yield at t0 from ``level`` (its auction yield).  ``(Δ, the text, a warning for the row)``; Δ
        None when neither can be had."""
        today, t0 = ctx["today"], ctx["t0"]
        if aday >= today:
            return 0.0, "(ihale bugün: eğri hareketi yok)", None
        got = ctx["got"]
        why = ""
        fit = self.svc.dibsgenel.fit(got["quant"], got["live"], today)
        if fit.get("ok"):
            then = self.fit_on(aday, fit["tau"], got, today)
            if then[0] is not None:
                y1, y0 = model_yield(bond, fit["nss"], t0), model_yield(bond, then[0], t0)
                if y1 is not None and y0 is not None:
                    day_text = "" if then[1] == aday else " (en yakın kapanış %s)" % tr_day(then[1])
                    return y1 - y0, "+ eğri hareketi %s bp (Nelson-Siegel, %s kapanışından şimdiye%s)" % (
                        _bp((y1 - y0) * BP), tr_day(aday), day_text), None
                why = "eğride kâğıdın getirisi bulunamadı"
            else:
                why = then[2]
        else:
            why = "eğri şimdi kurulamadı: " + (fit.get("why") or "")
        d = self.ois_move(bond, aday, level, ctx)
        if d is not None:
            return d, "+ TRY OIS sıfır faiz değişimi %s bp (%s kapanışından şimdiye)" % (_bp(d * BP), tr_day(aday)), \
                "Nelson-Siegel eğrisi yok (%s): TRY OIS değişimi kullanıldı" % why
        return None, "(eğri hareketi ölçülemedi)", "eğri hareketi ölçülemedi (%s; OIS de yok): %s olduğu gibi" % (why, what)

    def _bond_closes(self, got: Dict[str, Any], today: _dt.date) -> Dict[str, Any]:
        """The trading list's bonds' closes before today (the history's, from the store's memory) and the convention each
        is read in (``quantcurve.detect_convention``, as Kâğıt Fiyatlama reads them) - kept per history revision."""
        from . import rvfair
        svc = self.svc
        mark = (svc.history.rev, today.isoformat(), tuple(sorted(r["isin"] for r in got["quant"])))
        hit = self._closes
        if hit is not None and hit[0] == mark:
            return hit[1]
        rows = {r["isin"]: r for r in got["quant"]}
        snap = svc.history.snapshot()
        defs = {}
        for d in snap["defs"]:
            if d.group == "dibs" and d.unit == "pct":
                code = rvfair.isin_of(d.info.get("isin") or d.label)
                if code in rows and code not in defs:
                    defs[code] = d
        start = (today - _dt.timedelta(days=kf.HISTORY_DAYS)).isoformat()
        data = svc.store.hist_many([i for d in defs.values() for i in d.ids()], start) if defs else {}
        closes: Dict[str, Dict[str, float]] = {}
        conv: Dict[str, str] = {}
        for code, d in defs.items():
            points = d.pick(data)[1]
            row = rows.get(code) or {}
            last = points[max(points)] if points else None
            conv[code] = qc.detect_convention(last, qc._pct(row.get("simple")), qc._pct(row.get("compound")))
            closes[code] = {k: v for k, v in points.items() if k < today.isoformat()}
        res = {"closes": closes, "conv": conv, "rows": rows}
        self._closes = (mark, res)
        return res

    def fit_on(self, day: _dt.date, nss0: qc.Nss, got: Dict[str, Any], today: _dt.date
               ) -> Tuple[Optional[qc.Nss], Optional[_dt.date], str]:
        """The bond curve on a past day's close: the Nelson-Siegel fit (``nss0``'s model and τ held, the β refitted) of
        the trading list's closes that day - or of the last day before it with enough coupon bonds.  ``(curve, the day,
        why not)``."""
        cl = self._bond_closes(got, today)
        days = sorted({d for s in cl["closes"].values() for d in s if d <= day.isoformat()}, reverse=True)
        if not days:
            return None, None, "kâğıtların %s ya da öncesinde kapanışı yok" % tr_day(day)
        for iso in days[:10]:
            d = _dt.date.fromisoformat(iso)
            items = []
            for code, s in sorted(cl["closes"].items()):
                if iso not in s:
                    continue
                b = qc._bond_of(code, {}, cl["rows"].get(code))
                if b is None or b.maturity <= d:
                    continue
                items.append((b, qc._value_date(d, cl["rows"].get(code)), s[iso] / 100.0, cl["conv"].get(code, "simple")))
            sig = (iso, tuple((b.isin, v.isoformat(), y, c) for b, v, y, c in items), nss0.tau1, nss0.tau2, nss0.k, tuple(nss0.beta))
            if sig in self._fits:
                nss = self._fits[sig]
            else:
                fit_in = qc.BondFit(items)
                nss = qc.refit(fit_in.make, nss0, nss0.beta, iters=8)["nss"] if fit_in.n_fit >= qc.MIN_BONDS else None
                if len(self._fits) > 64:
                    self._fits.clear()
                self._fits[sig] = nss
            if nss is not None:
                return nss, d, ""
        return None, None, "%s kapanışında eğri kurulamadı (en az %d sabit kuponlu kâğıdın kapanışı gerekli)" % (tr_day(day), qc.MIN_BONDS)

    def ois_move(self, bond: qc.Bond, aday: _dt.date, level: float, ctx: Dict[str, Any]) -> Optional[float]:
        """The TRY OIS Bootstrap zero rate's change at the bond's maturity since the auction day's close (Motor's
        bootstrap of that day's closes - ``swaption.day_curve`` - against the workbook's now), both over the same days to
        the maturity; added to the bond's compound yield at t0 (``level``, its simple yield, compounded as Kâğıt
        Fiyatlama compares them) and read back as the change of its simple yield."""
        from . import swaption as sw
        svc = self.svc
        mk, boot = ctx.get("mk"), ctx.get("boot")
        if "mk" not in ctx:
            mk, boot = svc.et.call(self._read_ois)
            ctx["mk"], ctx["boot"] = mk, boot
        if mk is None or boot is None:
            return None
        _, ois, hol, _ = svc._swaption_closes(mk)
        months = tuple(sorted(float(m) for m, _ in mk.ois_quotes))
        nodes = tuple(float(m) for m, _ in mk.nodes)
        cl_day = None
        for back in range(0, 10):
            iso = (aday - _dt.timedelta(days=back)).isoformat()
            if all(iso in ois.get(m, {}) for m in months) and months:
                cl_day = iso
                break
        if cl_day is None:
            return None
        quotes = tuple((m, ois[m][cl_day] / 100.0) for m in months)
        try:
            spot0, curve0 = sw.day_curve(_serial(_dt.date.fromisoformat(cl_day)), quotes, nodes, hol)
        except ValueError:
            return None
        if curve0 is None:
            return None
        days = _serial(bond.maturity) - mk.ois_spot
        z1 = kf.zero_rate(boot, mk.ois_spot, mk.ois_spot + days)
        z0 = kf.zero_rate(curve0, spot0, spot0 + days)
        if z1 is None or z0 is None:
            return None
        t0 = ctx["t0"]
        c = kf.to_compound(bond, level, t0, "simple")
        s1, s0 = simple_of_compound(bond, c + (z1 - z0), t0), simple_of_compound(bond, c, t0)
        return s1 - s0 if s1 is not None and s0 is not None else None

    def _read_ois(self) -> Tuple[Any, Any]:
        """(engine thread) The TRY OIS Bootstrap now: Motor's market (``pricing.read`` on the true Bootstrap) and its
        curve (``Service._try_curves``' ``boot``) - as Kâğıt Fiyatlama reads them."""
        from . import pricing as pr
        svc = self.svc
        book = svc.books.get("tto")
        if book is None or not all(s in book.model.sheet_index for s in ("Motor", "OIS_MAIN", "Forward")):
            return None, None
        index = book.model.sheet_index
        calc = svc._calc(None, book)
        base = svc.interp.boot_of(book, calc)
        try:
            mk = pr.read(lambda sheet, r, c: base.get(index[sheet], r, c))
        except pr.PricingError:
            return None, None
        cv = svc._try_curves(book, calc)
        return mk, (cv or {}).get("boot")

    # ------------------------------------------------------------------ an edit, the file
    def convert(self, user: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
        """An edited cell's other half at t0 (``{"isin", "field": "yield" | "price", "value"}``): a yield-quoted bond's
        price of a yield (%) or yield of a price - BIST's simple yield, quantcurve's cash flows and accrued interest."""
        self.svc.require_user(user)
        body = body if isinstance(body, dict) else {}
        code = "".join(str(body.get("isin") or "").split()).upper()
        rec = self.record(code)
        if not rec.get("kind"):
            raise FiyatError("kâğıt kataloğunda yok: %s" % (code or "(boş)"))
        field = body.get("field")
        v = num(body.get("value"))
        if field not in ("yield", "price"):
            raise FiyatError("alan yield ya da price olmalı")
        if v is None:
            raise FiyatError("bir sayı girin")
        if rec["kind"] == EURO:
            # a Eurobond: the street convention at the settlement of its Hesapla, anchored to Bloomberg's mid as there
            settle = date_said(body.get("settle"))
            anchor = num(body.get("anchor"))
            if settle is None or anchor is None:
                raise FiyatError("önce Hesapla: Eurobond'un valörü ve Bloomberg'in mid'ine çapası Hesapla'dan gelir")
            bond = street_of(rec)
            if field == "yield":
                p = bond.clean(v / 100.0, settle)
                if p is None:
                    raise FiyatError("bu getiriden fiyat bulunamadı")
                return {"isin": code, "yield": v, "price": p + anchor, "value_date": settle.isoformat()}
            y = bond.yield_of(v - anchor, settle) if v > 0 else None
            if y is None:
                raise FiyatError("bu fiyattan getiri bulunamadı")
            return {"isin": code, "price": v, "yield": y * 100.0, "value_date": settle.isoformat()}
        _, t0, _ = self._today()
        if not quoted_in_yield(rec.get("kind")):
            if field == "yield":
                raise FiyatError("%s fiyatla kote edilir: getirisi yok" % bd.short_label(rec))
            return {"isin": code, "price": v, "yield": None, "value_date": t0.isoformat()}
        bond = bond_of(rec)
        if bond is None:
            raise FiyatError("%s: kuponu bilinmiyor" % bd.short_label(rec))
        if field == "yield":
            p = price_of(bond, v / 100.0, t0)
            if p is None:
                raise FiyatError("bu getiriden fiyat bulunamadı")
            return {"isin": code, "yield": v, "price": p, "value_date": t0.isoformat()}
        if not v > 0:
            raise FiyatError("fiyat sıfırdan büyük olmalı")
        y = yield_of(bond, v, t0)
        if y is None:
            raise FiyatError("bu fiyattan getiri bulunamadı")
        return {"isin": code, "price": v, "yield": y * 100.0, "value_date": t0.isoformat()}

    def save_file(self, user: Optional[str], body: Dict[str, Any]) -> Dict[str, Any]:
        """Kaydet: the rows as the page has them (``{"rows": [{"isin", "bid_price", "ask_price", "bid_yield",
        "ask_yield"}]}``) written as the desk's file - a bill's or zero's yields, the others' prices, the rest 0 -,
        kept among the user's saves of the day.  A row without the figures it is written with is left out (and named);
        none at all is a 400."""
        from .store import now_iso
        key = self.svc.require_user(user)
        body = body if isinstance(body, dict) else {}
        given = body.get("rows")
        if not isinstance(given, list) or not given:
            raise FiyatError("kaydedilecek satır yok")
        st = self._load(key)
        fixed = {f["isin"] for f in st["fixed"]}
        mine = {b["isin"] for b in st["bonds"]} | fixed                                     # (the list and the fixed bonds)
        lines, left, crossed = [], [], []
        seen = set()
        for r in given:
            if not isinstance(r, dict):
                continue
            code = "".join(str(r.get("isin") or "").split()).upper()
            if code in seen:
                continue
            seen.add(code)
            if code not in mine:
                raise FiyatError("kâğıt listede değil: %s" % (code or "(boş)"))
            rec = self.fixed_record(code) if code in fixed else self.record(code)       # (a fixed one: its unit without a catalog)
            vals = {k: num(r.get(k)) for k in ("bid_price", "ask_price", "bid_yield", "ask_yield")}
            line = txt_line(code, rec.get("kind"), vals["bid_price"], vals["ask_price"], vals["bid_yield"], vals["ask_yield"])
            if line is None:
                left.append({"isin": code, "label": bd.short_label(rec), "why": "yazılacak %s yok" % ("getiri" if rec.get("kind") in WRITE_YIELD else "fiyat")})
                continue
            if rec.get("kind") in WRITE_YIELD and vals["bid_yield"] < vals["ask_yield"] or \
                    rec.get("kind") not in WRITE_YIELD and vals["bid_price"] > vals["ask_price"]:
                crossed.append(code)
            lines.append(line)
        if not lines:
            raise FiyatError("yazılacak fiyat yok: önce Hesapla")
        today, _, _ = self._today()
        name = file_name(today)
        text = txt(lines)
        with self._lock:
            kept = self.svc.store.get(KEY_SAVED % key)
            kept = kept if isinstance(kept, dict) else {}
            day = today.isoformat()
            kept[day] = ((kept.get(day) or []) + [{"at": now_iso(), "name": name, "text": text, "n": len(lines)}])[-SAVED_PER_DAY:]
            for d in sorted(kept)[:-SAVED_DAYS]:
                del kept[d]
            self.svc.store.put(KEY_SAVED % key, kept)
        return {"name": name, "text": text, "lines": lines, "left_out": left, "crossed": crossed, "saved": self.saved_today(key, today)}

    def saved_today(self, key: str, today: _dt.date) -> List[Dict[str, Any]]:
        kept = self.svc.store.get(KEY_SAVED % key)
        day = (kept or {}).get(today.isoformat()) if isinstance(kept, dict) else None
        return [{"at": x.get("at"), "name": x.get("name"), "n": x.get("n")} for x in day or []]

    def saved_file(self, user: Optional[str], day: Optional[str] = None) -> Tuple[bytes, str]:
        """The user's last saved file of a day (today's when none is named): its bytes (ASCII, CRLF) and its name."""
        key = self.svc.require_user(user)
        today, _, _ = self._today()
        when = str(day or "").strip() or today.isoformat()
        kept = self.svc.store.get(KEY_SAVED % key)
        files = (kept or {}).get(when) if isinstance(kept, dict) else None
        if not files:
            raise FiyatError("%s kaydedilmiş dosya yok" % ("bugün" if when == today.isoformat() else when))
        last = files[-1]
        return last["text"].encode("ascii", "replace"), last["name"]


def last_auction(auctions: Optional[List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """The last auction value kept of a bond: the latest day's, its .t1 before its .t2."""
    if not auctions:
        return None
    day = max(a.get("day") or "" for a in auctions)
    same = [a for a in auctions if a.get("day") == day and a.get("value_date")]
    return min(same, key=lambda a: a.get("tn") or 9) if same else None
