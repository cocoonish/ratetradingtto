"""Broker chat: what brokers type about TRY rates, understood and kept.

A line of a chat becomes a record - when, who, which instrument, bid and ask, and what happened:

    12:15:38 18m ois 35.03/35.23            an outright, both sides
    12:10:07 18m ois /35.23 offer           ... offered only (the slash says: nothing bid)
    6m OIS 90 bid                           ... the big figure left out: 35.90
    18m ois 10/14                           ... on both sides: 35.10 / 35.14
    6m ois 90/10                            ... across the figure: 35.90 / 36.10
    1yr x 38.60/80                          a cross-currency swap, 38.60 / 38.80
    10:29:57 1y5y ois -64/-60               a spread (5Y − 1Y) in bp - two tenors without a "v" are a spread, not a FRA
    1v5y x 55 offer                         ... written with a "v"
    12:18:04 2y3y4y ois 12/ bid             a fly (2·3Y − 2Y − 4Y) in bp, bid only
    12:11:55 9x12m ois fra 33.80/34.10      a FRA: "AxB" or the word
    18m ois taken at 14                     a trade: the offer was lifted at 35.14
    18m ois sell a bal at 14                the rest is still offered there
    ref 18m ois offer                       the offer is withdrawn
    care offer 6m1y OIS                     an interest without a price
    2yr ois 35.46 , oco with 18m 35.14 offer        two offers, one cancels the other
    18m ois 35.03 bid 35.23 offer           both sides, each with its word
    1y 35.00/35.20 18m 35.03/35.23          a run: several quotes on one line

and a chat becomes messages - the time at the start or the end of a line or (on the phone) on the line below, a
name on its own line, before a colon or in front of the time, a date on its own line.

Nothing here knows about the workbook: the big figure of a shortened level is completed from the level the
caller says the instrument is at (:func:`parse_chat`'s ``ref``) and from the lines before it.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------------------------- words
_PRODUCTS = {"ois": "OIS", "tlref": "OIS", "x": "XCCY", "xccy": "XCCY", "ccs": "XCCY", "ccy": "XCCY", "cross": "XCCY",
             "basis": "XCCY", "irs": "IRS"}
_BID = {"bid", "bids", "bidding", "pay", "pays", "payer", "paying", "buy", "buys", "buyer", "buying", "alıcı", "alici", "alış", "alis"}
_ASK = {"offer", "offers", "offered", "offering", "ofr", "ofrd", "ofd", "ask", "asks", "asked", "rec", "recs", "receive",
        "receiver", "receiving", "sell", "sells", "seller", "selling", "satıcı", "satici", "satış", "satis"}
_LIFT = {"taken", "lifted", "lifts", "paid", "mine"}                # a trade at the offer
_HIT = {"given", "hit", "hits", "sold", "yours"}                    # a trade at the bid
_TRADE = {"trades", "traded", "trade", "trd", "trds", "dealt", "done", "deals"}
_REF = {"ref", "refer", "refs", "referred", "cxl", "cancel", "cancelled", "canceled", "pull", "pulled", "off"}
_CARE = {"care", "cares", "interest", "interested", "looking"}
_FRA = {"fra", "fras", "fwd", "forward", "fwds"}
_FILLER = {"at", "@", "a", "the", "in", "on", "for", "with", "is", "now", "still", "pls", "please", "try", "tl", "tlref", "vs",
           "fly", "flies", "bfly", "butterfly", "spread", "sprd", "spd", "switch", "outright", "swap", "and", "&", "bp", "bps"}
_CHOICE = {"choice", "cho"}                                         # bid and ask at one level

_VOCABULARY = set(_PRODUCTS) | _BID | _ASK | _LIFT | _HIT | _TRADE | _REF | _CARE | _FRA | _FILLER | _CHOICE

_NUM = r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)"
_PIECE = r"(\d+(?:[.,]\d+)?)(d|wks?|w|mths?|mos?|m|yrs?|y|s)?"
_TENORS = re.compile(r"^%s(?:(vs|v|x|-)?%s)?(?:(vs|v|x|-)?%s)?$" % (_PIECE, _PIECE, _PIECE))
_SLASH = re.compile(r"^(%s)?/(%s)?$" % (_NUM, _NUM))
_ONE = re.compile(r"^%s$" % _NUM)
_RANGE = re.compile(r"^(\d+[.,]\d+)-(\d+[.,]\d+)$")                  # "35.00-35.20"
_TIME = re.compile(r"(?<![\d:.])([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?(?!\d|:\d)(?:\s?([AaPp])\.?[Mm]\b\.?)?")
_TIME_BRACKET = re.compile(r"^[\[(]\s*(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[AaPp]\.?[Mm]\.?)?)\s*[\])]\s*")
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
           "oca": 1, "şub": 2, "sub": 2, "nis": 4, "mayıs": 5, "haz": 6, "tem": 7, "ağu": 8, "agu": 8, "eyl": 9, "eki": 10, "kas": 11,
           "ara": 12}
_DATE_NAME = re.compile(r"^(\d{1,2})\s+([A-Za-zÇĞİÖŞÜçğıöşü]{3,9})\.?\s+(\d{4})$")
_DATE_NUM = re.compile(r"^(\d{1,4})[./-](\d{1,2})[./-](\d{1,4})$")
_SENDER = re.compile(r"^([A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜa-zçğıöşü.'\-]*(?:[ ,]+[A-ZÇĞİÖŞÜ(][A-ZÇĞİÖŞÜa-zçğıöşü.'&()\-]*){0,6}?)\s*(?:says)?\s*:\s+(?=\S)")
_NAME_LINE = re.compile(r"^[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ.'\-]+(?: [A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜ.'\-]*){1,4}$")

KINDS = ("outright", "spread", "fly", "fra", "fwd")


def _num(text: str) -> float:
    return float(text.replace(",", ".").replace("−", "-"))


# ---------------------------------------------------------------------------------------------- tenors
def tenor_months(value: float, unit: str) -> float:
    u = unit[0]
    if u == "d":
        return value / 30.4375
    if u == "w":
        return value * 7.0 / 30.4375
    if u == "m":
        return value
    return value * 12.0                       # y, yr, yrs, s ("2s5s")


def tenor_label(value: float, unit: str) -> str:
    u = unit[0]
    if u == "d":
        return "ON" if value == 1 else "%gD" % value
    if u == "w":
        return "%gW" % value
    months = value if u == "m" else value * 12.0
    if abs(months - round(months)) < 1e-9:
        months = int(round(months))
        return "%dY" % (months // 12) if months % 12 == 0 else "%dM" % months
    return "%gM" % months


def _tenor_expression(tokens: List[str], start: int, fra_word: bool) -> Optional[Tuple[int, List[Tuple[float, str]], str]]:
    """The tenors that start at ``tokens[start]``: (tokens used, [(number, unit), ...], separator) - "18m",
    "3y5y", "1v5y", "1y v 5y", "2y3y4y", "9x12m", "9 x 12" ...  The longest reading wins."""
    best = None
    for n in range(min(5, len(tokens) - start), 0, -1):
        part = tokens[start:start + n]
        if any(a and b and a[-1].isdigit() and b[0].isdigit() for a, b in zip(part, part[1:])):
            continue                                        # "35.14 18m": a level and a tenor, not one number
        text = "".join(part)
        m = _TENORS.match(text)
        if not m:
            continue
        n1, u1, s1, n2, u2, s2, n3, u3 = m.groups()
        pieces = [(n1, u1)] + ([(n2, u2)] if n2 else []) + ([(n3, u3)] if n3 else [])
        seps = [s for s in (s1, s2) if s]
        if any(("." in p or "," in p) and (not u or (_num(p) * 2) % 1) for p, u in pieces):
            continue                                        # "40.75" is a level, not a tenor ("1.5y" is one)
        gaps = [s1] + ([s2] if n3 else [])                  # what stands between the pieces
        if any(not u and not ((k > 0 and gaps[k - 1]) or (k < len(gaps) and gaps[k])) for k, (_, u) in enumerate(pieces)) \
                and len(pieces) > 1:
            continue                                        # "18m 14 offer": 18M at 14, not two tenors
        if len(pieces) == 1:
            if not u1 or u1 == "s":
                continue
        else:
            units = [u for _, u in pieces if u]
            x = "x" in seps
            if x:
                # "9x12", "9x12m", "9 x 12 fra": start and end in months; "2yr x 5" is a cross-currency swap at 5
                if len(pieces) != 2 or not (fra_word or (not u1 and (not u2 or u2[0] == "m"))):
                    continue
                if not fra_word and _num(n2) <= _num(n1):
                    continue                                # "50x50", "100x100": a size on either side
            elif not units and not seps:
                continue                                    # "1014" is a number
            elif "-" in seps and len(units) != len(pieces):
                continue                                    # "35-36" is not two tenors
        default = "m" if "x" in seps else "y"
        out: List[Tuple[float, str]] = []
        for k, (p, u) in enumerate(pieces):
            if not u:
                u = next((v for _, v in pieces[k + 1:] if v), None) or next((v for _, v in reversed(pieces[:k]) if v), None) or default
            out.append((_num(p), u))
        if any(v <= 0 or tenor_months(v, u) > 360 or (u[0] == "m" and v > 60) for v, u in out):
            continue                                        # "100m", "500m" are sizes
        best = (n, out, "x" if "x" in seps else ("v" if seps else ""))
        break
    return best


# ---------------------------------------------------------------------------------------------- levels
def _complete(text: str, ref: Optional[float], anchor: Optional[float] = None, above: bool = True) -> Tuple[float, str]:
    """A level as typed -> the level meant.  "90" for a rate that stands at 35.88 is 35.90: the big figure is
    taken from ``anchor`` (the other side of the same quote, which the level may not cross) or from ``ref``
    (where the instrument stands).  Returns (value, flag): "" as typed, "abbr" completed, "ambiguous" completed
    although the number as typed would have been possible too, "no-ref" nothing to complete it with."""
    n = _num(text)
    dotted = "." in text or "," in text
    if not dotted and 1000 <= n < 10000:
        return n / 100.0, ""                                # "3503/3523": the rate without its decimal point
    if (dotted and abs(n) >= 1.0) or n < 0 or n >= 100:
        return n, ""
    base = anchor if anchor is not None else ref
    if base is None:
        return n, ("" if dotted else "no-ref")
    part = n if dotted else n / 100.0                       # ".90" and "90" are both 0.90
    big = int(base // 1)
    cands = [(big + k + part, "abbr") for k in (-1, 0, 1)]
    if not dotted:
        cands.append((n, ""))
    if anchor is not None:
        ok = [c for c in cands if (c[0] >= anchor - 1e-9 if above else c[0] <= anchor + 1e-9)]
        cands = ok or cands
    cands.sort(key=lambda c: abs(c[0] - base))
    value, flag = cands[0]
    if anchor is None and not dotted:
        other = next((c for c in cands[1:] if c[1] != flag), None)
        if other is not None and abs(other[0] - base) < 0.6:
            flag = "ambiguous"                               # "36" at 35.55: 35.36 or 36.00
    return value, flag


def _is_short(text: str) -> bool:
    """A level written without its big figure: "90", "05", ".90" - what :func:`_complete` would complete."""
    n = _num(text)
    dotted = "." in text or "," in text
    return not ((not dotted and 1000 <= n < 10000) or (dotted and abs(n) >= 1.0) or n < 0 or n >= 100)


def _complete_pair(bid: str, ask: str, ref: float) -> Tuple[float, float, str]:
    """Both sides of a quote written without their big figure: "90/10" for a rate near 36 is 35.90 / 36.10.

    The two are completed together: the ask is the first level at or above the bid ("90/10" crosses into the next
    figure, "10/14" does not), and of the figures that leaves the one whose middle is nearest to ``ref`` - where
    the instrument stands - is taken.  Whole numbers may also be meant as typed ("35/36"); that reading competes.
    Returns (bid, ask, flag) like :func:`_complete`."""
    dotted = any("." in t or "," in t for t in (bid, ask))
    nb, na = _num(bid), _num(ask)
    pb = nb if ("." in bid or "," in bid) else nb / 100.0
    pa = na if ("." in ask or "," in ask) else na / 100.0
    cands: List[Tuple[float, float, float, str]] = []
    base = int(ref // 1)
    for big in range(base - 2, base + 3):
        b = big + pb
        a = big + pa if pa >= pb - 1e-12 else big + 1 + pa
        cands.append((abs((a + b) / 2.0 - ref), b, a, "abbr"))
    if not dotted and na >= nb:
        cands.append((abs((na + nb) / 2.0 - ref), nb, na, ""))
    cands.sort(key=lambda c: c[0])
    _, b, a, flag = cands[0]
    # two readings about as far from where the instrument stands: said, so that it is looked at
    if len(cands) > 1 and cands[1][0] - cands[0][0] < 0.15 and (cands[1][1], cands[1][2]) != (b, a):
        flag = "ambiguous"
    elif flag == "abbr" and not dotted and na >= nb and abs((na + nb) / 2.0 - ref) < 0.6:
        flag = "ambiguous"                                   # "35/36" at 35.5 could be meant either way
    return b, a, flag


# ---------------------------------------------------------------------------------------------- one quote
def instrument_key(product: str, kind: str, tenors: List[str]) -> str:
    return "%s:%s:%s" % (product, kind, "/".join(tenors))


def instrument_label(kind: str, tenors: List[str]) -> str:
    if kind == "fra":
        m = [_label_months(t) for t in tenors]
        return "x".join("%d" % x for x in m) if all(x is not None for x in m) else "×".join(tenors)
    if kind == "fwd":
        return "".join(tenors)
    return "–".join(tenors)


def _label_months(label: str) -> Optional[int]:
    if label.endswith("Y") and label[:-1].isdigit():
        return int(label[:-1]) * 12
    if label.endswith("M") and label[:-1].isdigit():
        return int(label[:-1])
    return None


_SIDE_SLASH = re.compile(r"(?i)\b(%s)\s*/\s*(?=[-+]?[\d.,])" % "|".join(sorted(_BID | _ASK, key=len, reverse=True)))
_SLASH_SIDE = re.compile(r"(?i)(\d)\s+/\s+(?=(?:%s)\b)" % "|".join(sorted(_BID | _ASK, key=len, reverse=True)))
_UNIT = r"(?:d|wks?|w|mths?|mos?|m|yrs?|y)"
_TENOR_SLASH = re.compile(r"(?i)(\d%s)\s*/\s*(?=\d+(?:[.,]\d+)?%s(?![a-z]))" % (_UNIT, _UNIT))


def _tokens(text: str) -> List[str]:
    t = text.replace("−", "-").replace("–", "-").replace("—", "-")
    t = re.sub(r"(?i)(?<=\d)\s*(?:%|bps?\b)", "", t)        # "35.03%", "-64bp": the unit goes without saying
    t = _TENOR_SLASH.sub(r"\1v", t)                        # "2y/3y/4y" -> "2yv3yv4y": tenors, not a bid and an ask
    t = _SIDE_SLASH.sub(r"\1 ", t)                         # "35.03 bid / 35.23 offer": the slash only separates
    t = _SLASH_SIDE.sub(r"\1 ", t)                         # "offer 35.23 / bid 35.03" too ("12/ bid" is a bid without an offer)
    t = re.sub(r"(\d)\s+/", r"\1/", t)                      # "35.00 / 35.20" -> "35.00/35.20"; "12/ bid" stays
    t = re.sub(r"/\s+(?=[-+]?\d)", "/", t)
    t = re.sub(r"@\s*", " at ", t)
    return [w for w in re.split(r"\s+", t.strip()) if w]


def parse_quote(text: str, ref: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None,
                instrument: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """One quote ("18m ois 35.03/35.23") as a record, or ``None`` when the text names no instrument.
    ``instrument``: the one spoken of when the text names none ("..., 35.23 offer")."""
    raw = _tokens(text)
    low = [w.lower().strip(",;:()") for w in raw]
    fra_word = any(w in _FRA for w in low)
    found = None
    at = 0
    for i in range(len(low)):
        found = _tenor_expression(low, i, fra_word)
        if found:
            at = i
            break
    if found:
        used, pieces, sep = found
        tenors = [tenor_label(v, u) for v, u in pieces]
        months = [tenor_months(v, u) for v, u in pieces]
        idx = [k for k in range(len(low)) if not at <= k < at + used]       # the words around the tenors
        product = next((_PRODUCTS[low[k]] for k in idx if low[k] in _PRODUCTS), "OIS")
        if len(tenors) == 1:
            kind = "outright"
        elif len(tenors) == 3:
            kind = "fly"
        elif sep == "x" or fra_word:
            kind = "fra"
        elif months[0] >= months[1]:
            kind = "fwd"                                     # "1y1y", "5y5y": a forward, not a spread
        else:
            kind = "spread"                                  # two tenors, with or without a "v": long − short
    elif instrument is not None:
        tenors, months, kind = list(instrument["tenors"]), list(instrument["months"]), instrument["kind"]
        idx = list(range(len(low)))
        product = next((_PRODUCTS[low[k]] for k in idx if low[k] in _PRODUCTS and low[k] != "x"), instrument["product"])
    else:
        return None
    words = {low[k] for k in idx}
    unit = "bp" if kind in ("spread", "fly") else "pct"
    out: Dict[str, Any] = {"product": product, "kind": kind, "tenors": tenors, "months": months,
                           "label": instrument_label(kind, tenors), "key": instrument_key(product, kind, tenors),
                           "unit": unit, "event": "quote", "bid": None, "ask": None, "price": None, "side": None,
                           "clear": [], "flags": [], "note": ""}
    first = {name: min([k for k in idx if low[k] in group] or [10 ** 6]) for name, group in (("bid", _BID), ("ask", _ASK))}
    side = None if first["bid"] == first["ask"] else ("bid" if first["bid"] < first["ask"] else "ask")

    def find(test: Callable[[str], Any]) -> Optional[int]:
        return next((k for k in idx if test(low[k])), None)

    k_slash = find(lambda w: w != "/" and "/" in w and _SLASH.match(w))
    k_range = find(_RANGE.match) if k_slash is None else None
    singles = [k for k in idx if _ONE.match(low[k])]
    k_at = find(lambda w: w == "at")
    after_at = next((k for k in singles if k_at is not None and k_at < k <= k_at + 2), None)
    # "35.03 bid 35.23 offer" / "bid 35.03 offer 35.23": a number for either side, each next to its word
    both = None
    if k_slash is None and k_range is None and len(singles) >= 2 and max(first.values()) < 10 ** 6:
        said = [k for k in idx if low[k] not in _FILLER]
        word_first = min(first.values()) < singles[0]
        got: Dict[str, int] = {}
        for k in singles:
            p = said.index(k)
            near = said[p - 1] if word_first and p > 0 else (said[p + 1] if not word_first and p + 1 < len(said) else None)
            name = None if near is None else ("bid" if low[near] in _BID else ("ask" if low[near] in _ASK else None))
            if name and name not in got:
                got[name] = k
        if len(got) == 2:
            both = (got["bid"], got["ask"])
    if words & _LIFT:
        out["event"], out["side"] = "trade", "ask"
    elif words & _HIT:
        out["event"], out["side"] = "trade", "bid"
    elif words & _TRADE:
        out["event"] = "trade"
    elif words & (_REF - {"off"}) or ("off" in words and k_slash is None and not singles):
        out["event"] = "ref"
    elif words & _CARE:
        out["event"] = "interest"
    level_ref = ref(out) if ref is not None and unit == "pct" else None
    consumed = set()

    def level(tok: str, anchor: Optional[float] = None, above: bool = True) -> float:
        if unit != "pct":
            return _num(tok)
        v, flag = _complete(tok, level_ref, anchor, above)
        if flag and not (anchor is not None and flag == "ambiguous") and flag not in out["flags"]:
            out["flags"].append(flag)
        return v

    def two_sided(b: str, a: str) -> Tuple[float, float]:
        """Bid and ask of one quote.  Written short on both sides ("90/10") they find their big figure together;
        with one side in full the other is completed against it (the bid below the ask, the ask above the bid)."""
        if unit != "pct":
            return _num(b), _num(a)
        short_b, short_a = _is_short(b), _is_short(a)
        if short_b and short_a:
            if level_ref is None:
                out["flags"].append("no-ref")                # nothing to find the figure with: as typed, and said so
                return _num(b), _num(a)
            bid, ask, flag = _complete_pair(b, a, level_ref)
            if flag:
                out["flags"].append(flag)
            return bid, ask
        if short_b:
            ask = level(a)
            return level(b, ask, False), ask                 # "90/36.10": the bid is the 90 below 36.10
        bid = level(b)
        return bid, level(a, bid)                            # the ask does not cross the bid: "35.60/80" is 35.80

    if out["event"] == "trade":
        k = after_at if after_at is not None else (singles[0] if singles else None)
        if k is not None:
            out["price"] = level(low[k])
            consumed.add(k)
        elif k_slash is not None:
            m = _SLASH.match(low[k_slash])
            tok = (m.group(2) or m.group(1)) if out["side"] == "ask" else (m.group(1) or m.group(2))
            out["price"] = level(tok)
            consumed.add(k_slash)
    elif out["event"] in ("ref", "interest"):
        out["side"] = side
    elif both is not None:
        out["bid"], out["ask"] = two_sided(low[both[0]], low[both[1]])    # "90 bid 10 offer" as "90/10"
        consumed.update(both)
    elif singles and words & _CHOICE and k_slash is None and k_range is None:
        k = after_at if after_at is not None else singles[0]
        consumed.add(k)
        out["bid"] = out["ask"] = level(low[k])             # "35.14 choice": bid and offered at the same level
    elif k_slash is not None or k_range is not None:
        k = k_slash if k_slash is not None else k_range
        b, a = _SLASH.match(low[k]).groups() if k_slash is not None else _RANGE.match(low[k]).groups()
        consumed.add(k)
        if b is not None and a is not None:
            out["bid"], out["ask"] = two_sided(b, a)
        elif b is not None:
            out["bid"] = level(b)
        elif a is not None:
            out["ask"] = level(a)
        if b is None:
            out["clear"].append("bid")                      # "/35.23": nothing bid
        if a is None:
            out["clear"].append("ask")
        if (side == "bid" and b is None) or (side == "ask" and a is None):
            out["flags"].append("side?")                     # "12/ offer": the slash and the word disagree
        out["side"] = "bid" if a is None else ("ask" if b is None else None)
    elif singles:
        k = after_at if after_at is not None else singles[0]
        consumed.add(k)
        if side is None:
            out["event"], out["price"] = "level", level(low[k])       # a number without a side
        else:
            out[side] = level(low[k])
        out["side"] = side
    else:
        out["event"] = "interest" if side is not None else "note"
        out["side"] = side
    if out["bid"] is not None and out["ask"] is not None and out["bid"] > out["ask"] + 1e-9:
        out["flags"].append("crossed")
    # ---- what else was said stays as it was typed ("bal", a size, "nl" ...)
    known = _VOCABULARY
    out["note"] = " ".join(raw[k].strip(",;") for k in idx if k not in consumed and low[k] and low[k] not in known)
    return out


# ---------------------------------------------------------------------------------------------- a message
_SPLIT = re.compile(r"(?<!\d)\s*[,;]\s*|\s*[,;]\s*(?!\d)")
_OCO = re.compile(r"\b(?:o\.?c\.?o\.?)(?:\s+(?:with|w/|vs))?\b", re.I)


def _is_level(word: str) -> bool:
    return bool(word != "/" and (_SLASH.match(word) or _ONE.match(word) or _RANGE.match(word)))


def _split_run(text: str) -> List[str]:
    """ "1y 35.00/35.20 18m 35.03/35.23 2y 35.26/35.46": a run on one line - cut before every tenor that comes
    after a level and brings a level of its own.  Anything else stays one piece."""
    raw = _tokens(text)
    low = [w.lower().strip(",;:()") for w in raw]
    fra_word = any(w in _FRA for w in low)
    cuts: List[int] = []
    started = levelled = False
    i = 0
    while i < len(low):
        found = _tenor_expression(low, i, fra_word)
        if found:
            j = i + found[0]
            while j < len(low) and (low[j] in _PRODUCTS or low[j] in _FILLER or low[j] in _FRA):
                j += 1
            if started and levelled and j < len(low) and _is_level(low[j]):
                cuts.append(i)
                levelled = False
            started = True
            i += found[0]
            continue
        if started and _is_level(low[i]):
            levelled = True
        i += 1
    if not cuts:
        return [text]
    edges = [0] + cuts + [len(raw)]
    return [" ".join(raw[a:b]) for a, b in zip(edges, edges[1:])]


def parse_message(text: str, ref: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None) -> List[Dict[str, Any]]:
    """The quotes of one chat message: usually one; several when they are listed with commas, written as a run
    or tied by "oco"."""
    parts = _OCO.split(text)
    linked = len(parts) > 1
    quotes: List[Dict[str, Any]] = []
    loose: List[str] = []
    for part in parts:
        for piece in _SPLIT.split(part):
            for seg in _split_run(piece) if piece and piece.strip() else []:
                seg = seg.strip()
                if not seg:
                    continue
                q = parse_quote(seg, ref)
                if q is not None and q["event"] == "note" and quotes:
                    q = None                                # "..., 50m": a size, not another instrument
                if q is None and quotes:
                    # "18m ois 35.03 bid, 35.23 offer": the other side of what was just quoted
                    more = parse_quote(seg, ref, quotes[-1])
                    prev = quotes[-1]
                    if more is not None and more["event"] == "quote" and prev["event"] == "quote" and \
                            all(more[x] is None or prev[x] is None for x in ("bid", "ask")) and (more["bid"], more["ask"]) != (None, None):
                        for x in ("bid", "ask"):
                            if more[x] is not None:
                                prev[x] = more[x]
                        prev["side"] = None if prev["bid"] is not None and prev["ask"] is not None else prev["side"]
                        prev["clear"] = [x for x in prev["clear"] if prev[x] is None]
                        prev["flags"] = prev["flags"] + [f for f in more["flags"] if f not in prev["flags"]]
                        if prev["bid"] is not None and prev["ask"] is not None and prev["bid"] > prev["ask"] + 1e-9 and "crossed" not in prev["flags"]:
                            prev["flags"].append("crossed")
                        prev["note"] = (prev["note"] + " " + more["note"]).strip()
                        prev["raw_part"] += ", " + seg
                        continue
                if q is None:
                    loose.append(seg)
                else:
                    q["raw_part"] = seg
                    quotes.append(q)
    if not quotes:
        return []
    explicit = [q for q in quotes if any(w.lower().strip(",;") in _PRODUCTS for w in _tokens(q["raw_part"]))]
    for q in quotes:
        if q not in explicit and explicit:
            # "... oco with 18m 35.14 offer": the product is the one named in the message
            if q["product"] != explicit[0]["product"]:
                q["product"] = explicit[0]["product"]
                q["key"] = instrument_key(q["product"], q["kind"], q["tenors"])
        if q["event"] == "level":
            # "2yr ois 35.46 , oco with 18m 35.14 offer": the side said once goes for the numbers without one
            later = next((x["side"] for x in quotes[quotes.index(q) + 1:] if x["event"] == "quote" and x["side"]), None) or \
                next((x["side"] for x in reversed(quotes[:quotes.index(q)]) if x["event"] == "quote" and x["side"]), None)
            if later:
                q["event"], q["side"] = "quote", later
                q[later], q["price"] = q["price"], None
    if linked and len(quotes) > 1:
        for q in quotes:
            q["oco"] = True
    if loose:
        quotes[-1]["note"] = (quotes[-1]["note"] + " " + ", ".join(loose)).strip()
    for q in quotes:
        q.pop("raw_part", None)
    return quotes


# ---------------------------------------------------------------------------------------------- a chat
def _parse_date(text: str, today: Optional[_dt.date] = None) -> Optional[_dt.date]:
    t = text.strip().strip("-–— ")
    m = _DATE_NAME.match(t)
    if m:
        month = _MONTHS.get(m.group(2).lower()[:3]) or _MONTHS.get(m.group(2).lower())
        if month:
            try:
                return _dt.date(int(m.group(3)), month, int(m.group(1)))
            except ValueError:
                return None
    m = _DATE_NUM.match(t)
    if m:
        a, b, c = (int(x) for x in m.groups())
        try:
            if len(m.group(1)) == 4:
                return _dt.date(a, b, c)
            if len(m.group(3)) != 4:
                return None
            if b > 12:                                       # month first (11/13/2026)
                return _dt.date(c, a, b)
            day_first = _dt.date(c, b, a)
            if today is not None and day_first > today and a <= 12:
                month_first = _dt.date(c, a, b)
                if month_first <= today:
                    return month_first
            return day_first
        except ValueError:
            return None
    return None


def _clock(m) -> str:
    """A matched time as HH:MM:SS (a 12-hour time with its AM / PM as it is on a 24-hour clock)."""
    hour = int(m.group(1))
    if m.group(4):
        hour = hour % 12 + (12 if m.group(4).lower() == "p" else 0)
    return "%02d:%s:%s" % (hour, m.group(2), m.group(3) or "00")


def _is_name(text: str) -> bool:
    words = re.findall(r"[^\s,()]+", text)
    return bool(words) and len(words) <= 7 and text[0].isupper() and not re.search(r"\d", text) and \
        not any(w.lower() in _VOCABULARY for w in words)


def split_messages(text: str, today: Optional[_dt.date] = None) -> List[Dict[str, Any]]:
    """The messages of a pasted chat: ``[{"date", "time", "sender", "text"}, ...]`` in the order they were
    written.  Understood: "12:15:38 text", "text" with its time on the next line (the phone's layout), a name on
    a line of its own or before a colon, a date on a line of its own or before the time."""
    out: List[Dict[str, Any]] = []
    date: Optional[_dt.date] = None
    sender = ""
    waiting: List[Dict[str, Any]] = []                     # messages whose time may still come on a later line
    named: Optional[Tuple[str, str]] = None                # (sender before it, text) of the line last taken for a name
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        s = line.strip().strip("•·>*\t ").strip()
        if not s:
            continue
        d = _parse_date(s, today)
        if d is not None:
            date = d
            waiting = []                                    # a new day: nothing above it is still waiting for its time
            continue
        # a date in front of the time: "11/13/2026 12:10:07 ..."
        first = s.split(" ", 1)
        if len(first) == 2 and _parse_date(first[0], today) is not None and _TIME.match(first[1].lstrip()):
            date = _parse_date(first[0], today)
            s = first[1].lstrip()
        time = None
        s = _TIME_BRACKET.sub(r"\1 ", s)                    # "[12:15:38] text"
        m = _TIME.match(s)
        if m and m.start() == 0:
            time = _clock(m)
            s = s[m.end():].strip(" -–\t:")
        else:
            found = list(_TIME.finditer(s))
            m = found[-1] if found else None
            if m is not None and m.end() == len(s):          # "... text 12:15:38"
                time = _clock(m)
                s = s[:m.start()].strip(" -–\t")
            elif found and _is_name(s[:found[0].start()].strip(" -–\t:,")):
                # "MIKE REES 12:15:38 text": the name in front of the time
                time = _clock(found[0])
                sender = " ".join(s[:found[0].start()].strip(" -–\t:,").split())
                s = s[found[0].end():].strip(" -–\t:")
        if not s:
            # a time on a line of its own belongs to what was written above it
            if not waiting and named is not None:
                # ... and when that was a line taken for a name ("THANKS MATE"), it was a message after all
                sender = named[0]
                out.append({"date": date.isoformat() if date else None, "time": time, "sender": sender, "text": named[1]})
            for msg in waiting:
                msg["time"] = time
            waiting = []
            named = None
            continue
        m = _SENDER.match(s)
        if m and not re.search(r"\d", m.group(1)) and not all(w.lower() in _VOCABULARY for w in re.findall(r"[^\s,()]+", m.group(1))):
            sender = " ".join(m.group(1).replace(" says", "").split())
            s = s[m.end():].strip()
        elif time is None and _NAME_LINE.match(s) and not any(w.lower() in _VOCABULARY for w in s.split()):
            named = (sender, s)
            sender = s
            waiting = []                                    # a new bubble
            continue
        if not s:
            continue
        named = None
        msg = {"date": date.isoformat() if date else None, "time": time, "sender": sender, "text": s}
        out.append(msg)
        if time is None:
            waiting.append(msg)
        else:
            waiting = []
    return out


def parse_chat(text: str, ref: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None,
               today: Optional[_dt.date] = None,
               standing: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None) -> List[Dict[str, Any]]:
    """Everything a pasted chat says, line by line.  A line that names an instrument gives one record per quote
    (``event`` quote / trade / ref / interest / level); any other line is kept as it is (``event`` "text").

    ``ref(record)`` is asked where an instrument stands (in the unit it is quoted in) when a level has no big
    figure; a full level earlier in the same chat answers before it.  ``standing(record)`` is asked for the bid
    and ask that stood before the chat (``{"bid", "ask"}``): "18m ois taken" is a trade at the offer that stands.
    Both are given the record with the ``date`` and ``time`` of its message, as far as the chat says them."""
    last: Dict[str, float] = {}
    book: Dict[str, Dict[str, Optional[float]]] = {}
    at: Dict[str, Any] = {}                               # the message being read

    def where(q: Dict[str, Any]) -> Optional[float]:
        if q["key"] in last:
            return last[q["key"]]
        return ref(dict(q, date=at.get("date"), time=at.get("time"))) if ref is not None else None

    def sides(q: Dict[str, Any]) -> Dict[str, Optional[float]]:
        if q["key"] not in book:
            was = (standing(q) if standing is not None else None) or {}
            book[q["key"]] = {"bid": was.get("bid"), "ask": was.get("ask")}
        return book[q["key"]]

    out: List[Dict[str, Any]] = []
    group = 0
    for msg in split_messages(text, today):
        at = msg
        quotes = parse_message(msg["text"], where)
        if not quotes or all(q["event"] == "note" for q in quotes):
            # nothing said about an instrument ("what is 18m" only names one): the line is kept as it is
            out.append({"date": msg["date"], "time": msg["time"], "sender": msg["sender"], "raw": msg["text"], "event": "text",
                        "ok": False})
            continue
        if any(q.get("oco") for q in quotes):
            group += 1
        for q in quotes:
            q.update({"date": msg["date"], "time": msg["time"], "sender": msg["sender"], "raw": msg["text"], "ok": True})
            if q.pop("oco", None):
                q["oco"] = group
            now = sides(q)
            if q["event"] == "quote":
                for side in ("bid", "ask"):
                    if q[side] is not None or side in q["clear"]:
                        now[side] = q[side]
            elif q["event"] == "ref":
                for side in ((q["side"],) if q["side"] else ("bid", "ask")):
                    now[side] = None
            elif q["event"] == "trade" and q["price"] is None and q["side"] and now.get(q["side"]) is not None:
                q["price"] = now[q["side"]]                 # "taken": at the offer that stands; "given": at the bid
                q["flags"].append("standing")
            for v in (q["bid"], q["ask"], q["price"]):
                if v is not None and q["unit"] == "pct":
                    last[q["key"]] = v
            out.append(q)
    return out


# ---------------------------------------------------------------------------------------------- the board
_KIND_ORDER = {k: i for i, k in enumerate(KINDS)}


def sort_key(q: Dict[str, Any]) -> Tuple:
    return (q.get("product") != "OIS", q.get("product") or "", _KIND_ORDER.get(q.get("kind"), 9), tuple(q.get("months") or ()))


def board(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Where every instrument stands after the records (oldest first): the last bid and ask with their times,
    the last trade, and what was said last.  A side that was taken off ("ref", or the empty half of "/35.23")
    is empty; a side nobody has spoken of since keeps its level and its time."""
    rows: Dict[str, Dict[str, Any]] = {}
    for q in records:
        if not q.get("ok"):
            continue
        row = rows.get(q["key"])
        if row is None:
            if q["event"] in ("note", "ref"):
                continue                                    # nothing to show yet: the instrument was only named, or taken off
            row = rows[q["key"]] = {"key": q["key"], "product": q["product"], "kind": q["kind"], "tenors": q["tenors"],
                                    "months": q.get("months") or [], "label": q["label"], "unit": q["unit"],
                                    "bid": None, "bid_time": None, "ask": None, "ask_time": None, "last": None,
                                    "last_time": None, "last_side": None, "level": None, "level_time": None, "said": ""}
        when = ((q.get("date") or "") + " " + (q.get("time") or "")).strip()
        ev = q["event"]
        if ev == "quote":
            for side in ("bid", "ask"):
                if q.get(side) is not None:
                    row[side], row[side + "_time"] = q[side], when
                elif side in (q.get("clear") or []):
                    row[side], row[side + "_time"] = None, when
        elif ev == "trade":
            if q.get("price") is not None:
                row["last"], row["last_time"], row["last_side"] = q["price"], when, q.get("side")
        elif ev == "ref":
            for side in ((q["side"],) if q.get("side") else ("bid", "ask")):
                row[side], row[side + "_time"] = None, when
        elif ev == "level":
            row["level"], row["level_time"] = q.get("price"), when
        row["said"] = q.get("raw") or ""
        row["time"] = when
    return sorted(rows.values(), key=sort_key)


# ---------------------------------------------------------------------------------------------- against a curve
def model_level(q: Dict[str, Any], par: Callable[[str], Optional[float]],
                fra: Optional[Callable[[int, int], Optional[float]]] = None) -> Optional[float]:
    """Where a curve has the instrument, in the unit it is quoted in: ``par(tenor)`` is the curve's par rate (a
    fraction) and ``fra(start, end)`` its forward between two month counts.  Outright and FRA in per cent;
    spread (long − short) and fly (2·body − wings) in bp.  ``None`` where the curve has no answer."""
    t = q["tenors"]
    try:
        if q["kind"] == "outright":
            v = par(t[0])
            return None if v is None else v * 100.0
        if q["kind"] == "spread":
            a, b = par(t[0]), par(t[1])
            return None if a is None or b is None else (b - a) * 10000.0
        if q["kind"] == "fly":
            a, b, c = par(t[0]), par(t[1]), par(t[2])
            return None if a is None or b is None or c is None else (2.0 * b - a - c) * 10000.0
        if q["kind"] in ("fra", "fwd") and fra is not None:
            m = [_label_months(x) for x in t]
            if None in m:
                return None
            start, end = (m[0], m[1]) if q["kind"] == "fra" else (m[0], m[0] + m[1])
            v = fra(start, end)
            return None if v is None else v * 100.0
    except Exception:  # noqa: BLE001 - a curve that cannot answer is no reason to lose the quote
        return None
    return None


def against(row: Dict[str, Any], mid: Optional[float]) -> Dict[str, Any]:
    """A board row next to the curve: the model level and how far bid, ask and the last trade are from it (bp)."""
    k = 100.0 if row["unit"] == "pct" else 1.0
    out = {"mid": mid}
    for name in ("bid", "ask", "last"):
        v = row.get(name)
        out[name + "_diff"] = None if v is None or mid is None else (v - mid) * k
    return out
