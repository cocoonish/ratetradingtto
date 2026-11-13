"""Offline quote files for the workbooks that were saved without Bloomberg data.

``BBG_Borsa_Swap`` and ``DIBS_ASW`` hold no market values (they were saved without a connection), so in
recorded-data mode there is nothing to show for them.  This tool derives stand-in quotes from what the TRY
workbook *did* record on its last calculation date and writes them to ``tto/data/replay_*.json``:

* ``replay_asw.json``    bond names, coupons, maturities and prices of the ASW watch-list, taken from the
                         recorded DİBS RV table of the TRY workbook (same bonds, same day), TLREF and the
                         TRY OIS quotes.  Recorded data, re-keyed to the tickers the ASW workbook asks for.
* ``replay_borsa.json``  BIST swap quotes do not exist in any recording: swap points are *derived* from the
                         recorded RET bid / ask curve for a handful of maturities, with made-up sizes.
                         Example data, labelled as such on the page.

    python tools/make_replay_quotes.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from tto.config import Settings  # noqa: E402
from tto.marketdata.base import bdp_key  # noqa: E402
from tto.service import Service  # noqa: E402
from tto.xl.errors import XlError  # noqa: E402
from tto.xl.model import COLS, parse_a1  # noqa: E402

OUT = os.path.join(ROOT, "tto", "data")
# maturities (days) that get an example quote: (days, bid size, ask size) - sizes in the market's own unit
BFX0 = [(1, 250, 300), (2, 100, None), (5, 50, 75), (6, None, 40), (7, 150, 150), (14, 100, 80), (21, 60, 60), (28, 50, None),
        (35, 40, 45), (62, 30, 30), (91, 25, 20)]
BFX1 = [(1, 200, 200), (7, 120, 100), (14, 80, None), (30, 60, 60), (61, None, 35), (92, 25, 25)]


def main() -> int:
    svc = Service(Settings(data_dir=tempfile.mkdtemp(), mode="replay"))
    try:
        tto, borsa, asw = svc.books["tto"], svc.books["borsa"], svc.books["asw"]

        def value(book, ref):
            si, rc = book.cell(ref)
            return svc.et.call(lambda: book.engine.shared.get(si, *divmod(rc, COLS)))

        def num(book, ref):
            v = value(book, ref)
            return v if type(v) is float else None

        snap = svc.provider.snapshot

        # ------------------------------------------------------------------ DİBS ASW
        day = value(tto, "MASA!C94")                                   # the workbook's calculation day
        quotes = {"_comment": "Offline quotes for the DİBS ASW page. Bond names, types, coupons, maturities and prices are the "
                              "values the TRY workbook recorded in its DİBS RV table on its last calculation day; TLREF and the "
                              "TRY OIS quotes likewise. Re-keyed to the tickers the ASW workbook asks for. Not live data."}
        rv = {}
        for r in range(5, 55):
            isin = value(tto, "DİBS RV!A%d" % r)
            if isinstance(isin, str) and isin.strip():
                rv[isin.strip()] = r
        suffix = value(asw, "ASW!E3")
        general = value(asw, "ASW!C3")
        n = 0
        for r in range(7, 57):
            isin = value(asw, "ASW!B%d" % r)
            if not isinstance(isin, str) or isin.strip() not in rv:
                continue
            isin = isin.strip()
            row = rv[isin]
            src = value(asw, "ASW!C%d" % r)
            src = src.strip().upper() if isinstance(src, str) and src.strip() else general
            static, priced = "%s %s" % (isin, suffix), "%s @%s %s" % (isin, src, suffix)
            kind = value(tto, "DİBS RV!D%d" % row)
            name, mat, cpn = value(tto, "DİBS RV!C%d" % row), num(tto, "DİBS RV!E%d" % row), num(tto, "DİBS RV!G%d" % row)
            if not isinstance(name, str) or mat is None:
                continue
            quotes["%s|NAME" % static] = name
            quotes["%s|CPN_TYP" % static] = {"S": "FIXED", "B": "ZERO COUPON", "T": "FLOATING", "E": "FIXED"}.get(kind, "FIXED")
            quotes["%s|CPN" % static] = round(cpn * 100.0, 6) if cpn is not None else 0.0
            quotes["%s|MATURITY" % static] = mat
            quotes["%s|CPN_FREQ" % static] = 2.0
            quotes["%s|INFLATION_LINKED_INDICATOR" % static] = "Y" if kind == "E" else "N"
            for field, col in (("PX_BID", "K"), ("PX_ASK", "L"), ("PX_MID", "M")):
                px = num(tto, "DİBS RV!%s%d" % (col, row))
                if px is not None and px > 0:
                    quotes["%s|%s" % (priced, field)] = px
            n += 1
        tlref = num(tto, "OIS_MAIN!J2")
        if tlref is not None:
            quotes["BISTTREF Index|PX_LAST"] = round(tlref * 100.0, 6)
        # TRY OIS: the ASW sheet asks "<ticker> GFOF Curncy" MID first - the quotes the TRY workbook used
        # for its own OIS curve that day (OIS_MAIN, "PİYASA par")
        par = {}
        for r in range(9, 27):
            tk, q = value(tto, "OIS_MAIN!J%d" % r), num(tto, "OIS_MAIN!B%d" % r)
            if isinstance(tk, str) and q is not None:
                par[tk.strip()] = q
        for c in "CDEFGHIJKLMNOPQR":
            tk = value(asw, "ASW!%s63" % c)
            if isinstance(tk, str) and tk.strip() in par:
                quotes["%s GFOF Curncy|MID" % tk.strip()] = round(par[tk.strip()] * 100.0, 6)
        with open(os.path.join(OUT, "replay_asw.json"), "w", encoding="utf-8") as fh:
            json.dump(quotes, fh, ensure_ascii=False, indent=0, sort_keys=True)
            fh.write("\n")
        print("replay_asw.json: %d bonds of %s, %d keys" % (n, day, len(quotes) - 1))

        # ------------------------------------------------------------------ Borsa swap
        spot = num(tto, "VIOP!M11")                                    # recorded USDTRY mid
        on_points = snap.get(bdp_key("TRYON AKGS Curncy", "MID"))
        on_points = on_points if type(on_points) is float else None
        if on_points is None:                                          # one day of RET O/N carry, in pips
            on_points = round(spot * num(tto, "Forward!W33") / 360.0 * 10000.0, 1)
        out = {"_comment": "EXAMPLE quotes for the Borsa swap page. Borsa İstanbul swap quotes are not in any recording: the swap "
                           "points below are derived from the RET bid / ask curve the TRY workbook recorded on its last calculation "
                           "day (so that the implied TRY rates equal RET), the sizes are made up. Not market data.",
               "USDTRY Curncy|PX_LAST": spot, "TRYON BGN Curncy|MID": on_points}
        svc.provider.update({bdp_key("USDTRY Curncy", "PX_LAST"): spot, bdp_key("TRYON BGN Curncy", "MID"): on_points})
        svc.et.call(lambda: [b.engine.reset() for b in svc.books.values()])
        days = [num(tto, "Forward!U%d" % r) for r in range(33, 48)]
        bids = [num(tto, "Forward!W%d" % r) for r in range(33, 48)]
        asks = [num(tto, "Forward!X%d" % r) for r in range(33, 48)]

        def ret(n, ys):
            if n <= days[0]:
                return ys[0]
            for i in range(1, len(days)):
                if n <= days[i]:
                    return ys[i - 1] + (ys[i] - ys[i - 1]) * (n - days[i - 1]) / (days[i] - days[i - 1])
            return ys[-1]

        for tag, usd_col, spot_ref, items in (("BFX0", "H", "Sheet1!AD19", BFX0), ("BFX1", "T", "Sheet1!AD18", BFX1)):
            s0 = num(borsa, spot_ref)
            for n, bid_size, ask_size in items:
                usd = num(borsa, "Sheet1!%s%d" % (usd_col, n + 3))
                if s0 is None or usd is None:
                    raise SystemExit("cannot derive %s %dD (spot %r, usd %r)" % (tag, n, s0, usd))
                tk = "TYB%dD %s Curncy" % (n, tag)
                for field, rate, size in (("BID", ret(n, bids), bid_size), ("ASK", ret(n, asks), ask_size)):
                    if size is None:
                        continue                                       # a one-sided market
                    out["%s|%s" % (tk, field)] = float(round(s0 * ((1 + rate * n / 360.0) / (1 + usd * n / 360.0) - 1) * 10000.0))
                    out["%s|%s_SIZE" % (tk, field)] = float(size)
        with open(os.path.join(OUT, "replay_borsa.json"), "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=0, sort_keys=True)
            fh.write("\n")
        print("replay_borsa.json: %d keys (spot %.4f, O/N points %s)" % (len(out) - 1, spot, on_points))
    finally:
        svc.stop()
    for name in ("replay_asw.json", "replay_borsa.json"):
        for k, v in json.load(open(os.path.join(OUT, name), encoding="utf-8")).items():
            assert not isinstance(v, XlError), (name, k)
    return 0


if __name__ == "__main__":
    sys.exit(main())
