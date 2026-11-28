"""DİBS RV · Genel: the trading list's bonds at a glance - the charts, the zero-coupon curve fitted to them live, the
settings the figures read - and a link to the bond table's one home, DİBS Trading's summary.

**The menu.**  Tahvil → "DİBS RV" is one entry with three tabs: **Genel** (this page), **RV hesap tablosu** (``dibs``, the
DİBS RV sheet) and **ASW hesap tablosu** (``asw``, the DİBS ASW sheet).  The two sheets keep their pages and their
addresses (``#/dibs``, ``#/asw``: launchpad boxes, alarms, watched cells, Ctrl+K and the bond card's links find them as
before); only the menu shows them as tabs (``menu``: the nav's ``menu`` / ``menu_title`` / ``tab``, as quant's entries).

**One home for the bond table** (the desk, 28.11.2026: "kagit kismi cok duzensiz ve her sey her yerde gibi"; the
reorganization's "Genel yalnız grafikler + Trading tablosuna bağlantı").  Genel no longer has a table of its own: its
columns - the clean price in use, the simple yield, each fitted ASW curve's ASW at the bond's years, the zero-coupon
curve's model yield, cheap / rich and fair price, the OIS hedge ratio - are DİBS Trading's summary's now
(``Service._trading_table``; its presets Trading / RV / Risk under "Sütunlar"), and this page links to it.  What the
summary reads of the zero-coupon curve is :meth:`DibsGenel.zero_for` here: the same fit, kept, for the same inputs.

**The zero-coupon curve** - a Nelson-Siegel zero curve fitted now to the trading list's fixed coupon bonds, the bills
priced on it, not fitted (the desk's decision of 18.11.2026; TLREF floaters, FRNs and CPI linkers out, the reason in
the cell): each bond's model yield, cheap / rich (bp, + cheap) and the fair clean price on the curve.  **The fit is
quantcurve's** ("DİBS adil değeri"): the bonds as ``quantcurve.read_engine`` reads DİBS RV (the user's own calculation
of it), their simple yields, ``quantcurve.BondFit`` / ``dibs_search`` / ``refit`` as ``quantcurve.fam_dibs`` runs them
on today's quotes - the model (``quantcurve.DIBS_MODEL``, Nelson-Siegel) and its τ searched on the bonds now, then the β
with them held; a bond's cheap / rich is the fit's residual (its yield − the model yield, bp of the simple yield), the
model yield the yield − it (the quant page's "Model"), the fair price ``quantcurve.quote_bond``'s clean price; the fit's
line says its RMSE and its leave-one-out RMSE (``BondFit.loo``).  The τ are searched again when the bonds (or the day)
change, else only the β follow the yields - as the quant fit does live.

**The charts**: the yield curve (each bond's compound yield at its years, the fitted curve's par yield - the yield of a
bond priced at 100 clean on it - and zero rate, compounded once a year, and DİBS RV's OIS par rate at each bond's
maturity, X, for reference) drawn here; ASW · OIS and ASW · FX swap are DİBS ASW's own charts, as its page draws them.
DİBS RV's SWITCH / PAIR table and DİBS ASW's history are shown as their pages draw them, read-only: their inputs - and
the settings the figures here read (threshold, horizon, price type, repo, source) - are typed in the hesap tablosu tabs;
a click on one opens it there (``MIRRORS``, ``SETTINGS``)."""
from __future__ import annotations

import datetime as _dt
import math
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from . import extras as ex
from . import quantcurve as qc
from . import rvfair
from .xl import numfmt

PAGE_ID = "dibs-genel"
MENU_ID, MENU_TITLE = "tahvil.dibsrv", "DİBS RV"
#: the entry's tabs: (page, tab title) - Genel first, where the entry leads before a tab was opened
TABS = ((PAGE_ID, "Genel"), ("dibs", "RV hesap tablosu"), ("asw", "ASW hesap tablosu"))
PAGE = {"id": PAGE_ID, "title": "DİBS RV · Genel", "group": "Tahvil", "book": "tto", "sheet": None, "custom": True}
#: the panels of the hesap tablosu tabs shown here as their own pages draw them (``/api/panels``): read-only
MIRRORS = ({"key": "asw_ois", "view": "asw", "panel": "chart0", "title": "ASW · OIS"},
           {"key": "asw_fx", "view": "asw", "panel": "chartfx", "title": "ASW · FX swap"},
           {"key": "switch", "view": "dibs", "panel": "B4", "title": "Switch / pair"},
           {"key": "hist_sel", "view": "asw", "panel": "sel", "title": "ASW geçmişi · seçili kâğıtlar"},
           {"key": "hist", "view": "asw", "panel": "chart1", "title": "ASW geçmişi"})
#: the settings of DİBS RV the figures here read: shown here, typed in the RV hesap tablosu ("Ayarlar": two panels since
#: 28.11.2026 - B1 A2:M2, B1b N2:Z2 - the panel each is in)
SETTINGS = (("P2", "Sinyal eşiği (bp)", "B1b"), ("J2", "C+R ufku (ay)", "B1"), ("X2", "Fiyat tipi", "B1b"),
            ("Z2", "Varsayılan repo (%)", "B1b"), ("B2", "Kaynak (genel)", "B1"))
RV_SHEET, RV_SETTINGS_PANEL = "DİBS RV", "B1"
#: the bond table's one home: DİBS Trading's summary (the page links to it, the RV preset of its columns for the RV view)
TRADING = {"view": "dibslive", "panel": "L0", "title": "Trading listesi · özet", "preset": "RV"}
#: the kinds (DİBS RV's types) in their order, as DİBS Trading's summary groups them
KINDS = (("B", "Bono · kuponsuz"), ("S", "Sabit kuponlu"), ("T", "TLREF'e endeksli"), ("F", "FRN"), ("E", "TÜFE'ye endeksli"))
#: why a kind of bond is not measured against the zero-coupon curve
NO_ZERO = {"T": "TLREF'e endeksli: nakit akışları sabit değil, sıfır kupon eğrisine karşı ölçülmez",
           "F": "FRN: değişken kupon, sıfır kupon eğrisine karşı ölçülmez",
           "E": "TÜFE'ye endeksli: reel getiri, nominal sıfır kupon eğrisine karşı ölçülmez"}
#: the zero-coupon curve's group (DİBS Trading's summary): its model named
ZERO_GROUP = "Sıfır kupon eğrisi (%s)" % qc.MODEL_NAMES[qc.DIBS_MODEL]
#: the group's head's tip
GROUP_TIPS = {ZERO_GROUP: "Trading listesinin sabit kuponlularına şimdi uydurulan %s sıfır kupon eğrisi (quant'ın DİBS adil "
                          "değeri hesabı); bonolar eğride fiyatlanır, uydurmaya girmez" % qc.MODEL_TEXT[qc.DIBS_MODEL]}
GRID_STEP = 0.1                          # years between the points of the curve's lines
FIT_KEPT = 8                             # fits kept (users with inputs of their own see their own)


def menu(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The nav's pages with DİBS RV's entry: Genel put before the first of its tabs, every tab naming the entry - when
    the sheets' pages are there (a dashboard without the TRY workbook has neither)."""
    ids = [p["id"] for p in pages]
    if "dibs" not in ids:
        return pages
    tab = dict(TABS)
    out = []
    for p in pages:
        if p["id"] in tab:
            if not any(x["id"] == PAGE_ID for x in out):
                out.append(dict(PAGE, menu=MENU_ID, menu_title=MENU_TITLE, tab=tab[PAGE_ID]))
            p = dict(p, menu=MENU_ID, menu_title=MENU_TITLE, tab=tab[p["id"]])
        out.append(p)
    return out


# ---------------------------------------------------------------------------------------------- the zero-coupon curve
def bond_inputs(rows: List[Dict[str, Any]], live: Dict[str, float], today: _dt.date
                ) -> Tuple[List[Tuple[qc.Bond, _dt.date, float, str]], Dict[str, str]]:
    """The fit's bonds, as ``quantcurve.fam_dibs`` takes them on today's quotes: each bond of ``rows`` (``read_engine``'s)
    with its value date and simple yield (``live``: ``live_values``' per cent) - and why the others are not."""
    items, out = [], {}
    for row in rows:
        isin = row["isin"]
        b = qc._bond_of(isin, {}, row)
        if b is None:
            out[isin] = "vade ya da kupon bilinmiyor"
            continue
        if b.maturity <= today:
            out[isin] = "vadesi geçmiş"
            continue
        y = live.get("DIBSS:" + isin)
        if y is None:
            out[isin] = "getirisi yok (fiyat yok)"
            continue
        items.append((b, qc._value_date(today, row), y / 100.0, "simple"))
    return items, out


def zero_fit(items: List[Tuple[qc.Bond, _dt.date, float, str]], nss0: Optional[qc.Nss] = None) -> Dict[str, Any]:
    """The zero-coupon fit of the bonds (``bond_inputs``): the model and its τ searched (``quantcurve.dibs_search``, unless
    ``nss0``, an earlier search, gives them), then the β with them held, from the search's - ``quantcurve.fam_dibs``'s
    fit of today's quotes - and its leave-one-out RMSE.  ``{"ok", "nss", "in", "fit", "found", "tau", "loo"}`` or
    ``{"ok": False, "why"}``."""
    fit_in = qc.BondFit(items)
    if fit_in.n_fit < qc.MIN_BONDS:
        return {"ok": False, "why": "en az %d sabit kuponlu kâğıdın getirisi gerekli (%d var)" % (qc.MIN_BONDS, fit_in.n_fit)}
    found = None
    if nss0 is None:
        found = qc.dibs_search(fit_in)
        if found is None:
            return {"ok": False, "why": "%s uyumu kurulamadı" % qc.MODEL_NAMES[qc.DIBS_MODEL]}
        nss0 = found["nss"]
    fit = qc.refit(fit_in.make, nss0, nss0.beta, iters=8)
    return {"ok": True, "nss": fit["nss"], "in": fit_in, "fit": fit, "found": found, "tau": nss0, "loo": qc.loo_rmse(fit_in, fit["nss"])}


def fit_rows(res: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Each bond of a fit against the curve, by ISIN: ``yield`` / ``model`` (per cent, simple), ``resid`` (bp, + cheap),
    ``fitted`` (in the fit: a fixed coupon bond; a bill is priced on the curve, not fitted) and its ``weight`` (Huber), the
    fair quote (``fair``: quote_bond's - the yield of Σ CF·DF, its clean and dirty price), the value date and the accrued
    interest."""
    fit_in, fit, nss = res["in"], res["fit"], res["nss"]
    resid = fit_in.evaluate(nss)[0]
    weights = fit.get("weights") or [1.0] * fit_in.n_fit
    w_of = {fit_in.bonds[i].isin: weights[k] for k, i in enumerate(fit_in.fitted)}
    out = {}
    for i, b in enumerate(fit_in.bonds):
        r = resid[i] * 1e4
        q = qc.quote_bond(b, fit_in.value[i], nss, 0.0)
        out[b.isin] = {"yield": fit_in.y[i] * 100.0, "model": fit_in.y[i] * 100.0 - r / 100.0, "resid": r, "fitted": b.isin in w_of,
                       "weight": w_of.get(b.isin), "fair": q["fair"], "value_date": q["value_date"], "accrued": q["accrued"],
                       "kind": b.kind}
    return out


def fit_summary(res: Dict[str, Any]) -> Dict[str, Any]:
    """The fit's quality and parameters: the model ("NS" / "NSS"), RMSE and leave-one-out RMSE (bp, over the bonds fitted),
    how many bonds (``n_fit`` fitted - the fixed coupon bonds -, ``n_bills`` bills priced on the curve, not fitted), β (per
    cent: three of NS, four of NSS) and τ (years: one, two), the curve's zero rates at round maturities."""
    if not res.get("ok"):
        return {"ok": False, "why": res.get("why") or ""}
    fit_in, fit, nss = res["in"], res["fit"], res["nss"]
    info = nss.info(fit_in.longest)
    return {"ok": True, "model": nss.model, "rmse": math.sqrt(fit["sse"] / fit_in.n_fit) * 1e4, "loo": res.get("loo"),
            "n": len(fit_in), "n_fit": fit_in.n_fit, "n_bills": fit_in.n_bills,
            "beta": [info["b%d" % j] for j in range(nss.k)], "tau": [nss.tau1, nss.tau2][:nss.k - 2], "zero": info["zero"],
            "shortest": fit_in.shortest, "longest": fit_in.longest,
            "down": sum(1 for w in (fit.get("weights") or []) if w < 1.0)}


def par_yield(nss: qc.Nss, value: _dt.date, t: float) -> Optional[float]:
    """The yield (decimal, compounded once a year) of a bond priced at par on the curve: maturity ``t`` years after the
    value date, coupons every 182 days back from it (BIST), the coupon at which its clean price is 100; its BIST simple
    yield of that dirty price, compounded."""
    mat = value + _dt.timedelta(days=max(1, int(round(t * qc.YEAR))))
    probe = qc.Bond("", "", "fixed", mat, 1.0, 2)
    flows, frac = probe.flows(value)
    if not flows:
        return None
    s = sum(nss.df((d - value).days / qc.YEAR) for d, _ in flows)
    den = s - (1.0 - frac)
    if not den > 0:
        return None
    c = 200.0 * (1.0 - nss.df((mat - value).days / qc.YEAR)) / den              # % a year
    bond = qc.Bond("", "", "fixed", mat, c, 2)
    y = bond.yield_of(100.0 + c / 2.0 * (1.0 - frac), value, "simple", c / 100.0)
    return (1.0 + y / 2.0) ** 2 - 1.0 if y is not None else None


def curve_lines(res: Dict[str, Any], longest: float) -> Dict[str, List[float]]:
    """The fitted curve's par yield and zero rate (per cent, compounded once a year) every ``GRID_STEP`` years up to
    ``longest``."""
    if not res.get("ok"):
        return {"t": [], "par": [], "zero": []}
    nss = res["nss"]
    value = max(res["in"].value)                       # (the spot: the bonds priced on the next business day)
    ts, par, zero = [], [], []
    k = 1
    while k * GRID_STEP <= longest + 1e-9:
        t = round(k * GRID_STEP, 6)
        p = par_yield(nss, value, t)
        ts.append(t)
        par.append(p * 100.0 if p is not None else None)
        zero.append((math.exp(nss.zero(t)) - 1.0) * 100.0)
        k += 1
    return {"t": ts, "par": par, "zero": zero}


def yield_chart(points: List[Dict[str, Any]], lines: Dict[str, List[float]], ois: List[Tuple[float, float]]) -> Dict[str, Any]:
    """The yield curve as the dashboard's charts draw an XY chart: each bond's compound yield at its years (``points``:
    ``{"t", "y", "label"}``, per cent), the fitted curve's par yield and zero rate, the OIS par rate at the bonds'
    maturities (``ois``: (t, per cent))."""
    pts = sorted(points, key=lambda p: p["t"])
    ois = sorted(ois)
    series = [{"name": "Kâğıtlar (bileşik getiri)", "kind": "scatter", "stacked": False, "x": [p["t"] for p in pts],
               "data": [p["y"] for p in pts], "labels": [p["label"] for p in pts], "noline": 1, "marker": 1, "color": "1F3864"},
              {"name": "Sıfır kupon eğrisi · par getiri", "kind": "scatter", "stacked": False, "x": lines["t"], "data": lines["par"],
               "smooth": 1, "color": "C00000"},
              {"name": "Sıfır kupon eğrisi · zero faiz", "kind": "scatter", "stacked": False, "x": lines["t"], "data": lines["zero"],
               "smooth": 1, "dash": 1, "color": "C55A11"},
              {"name": "OIS par @vade (DİBS RV)", "kind": "scatter", "stacked": False, "x": [t for t, _ in ois], "data": [y for _, y in ois],
               "marker": 1, "color": "548235"}]
    title = "Getiri eğrisi · kâğıtlar ve sıfır kupon eğrisi (yıllık bileşik)"
    return {"title": title, "kind": "scatter", "scatter": 1, "cats": [], "series": series,
            "axis": ["Kalan vade (yıl)", "Getiri (%)"], "decimals": 2, "x_title": "Kalan vade (yıl)", "y_title": "Getiri (%)",
            "aspect": 0.42, "xaxis": {"type": "value", "format": "0", "min": 0.0}}


# ---------------------------------------------------------------------------------------------- the page
class DibsGenel(object):
    """The page's data (``/api/dibs/genel``): what the sheets say read on the calculation thread, the fit beside it."""

    def __init__(self, svc):
        self.svc = svc
        self._lock = threading.Lock()
        self._tau: Optional[Tuple[Any, qc.Nss]] = None                     # (the bonds' key, the search that found the τ)
        self._kept: List[Tuple[Any, Dict[str, Any]]] = []                  # (inputs, fit), the latest last

    # ------------------------------------------------------------------ the fit, kept
    def fit(self, rows: List[Dict[str, Any]], live: Dict[str, float], today: _dt.date) -> Dict[str, Any]:
        """The zero-coupon fit of the bonds now: kept for the same inputs; the τ searched again when the bonds or the day
        change, else held - only the β follow the yields (from the search's, as the quant fit's live refit)."""
        items, why = bond_inputs(rows, live, today)
        bonds = (today.isoformat(),) + tuple(sorted((b.isin, b.kind, b.maturity.isoformat(), b.coupon, b.freq, v.isoformat())
                                                     for b, v, _, _ in items))
        key = (bonds, tuple(sorted((b.isin, y) for b, _, y, _ in items)))
        with self._lock:
            for k, res in self._kept:
                if k == key:
                    return dict(res, skipped=why)
            tau = self._tau if self._tau is not None and self._tau[0] == bonds else None
        res = zero_fit(items, tau[1] if tau else None)
        with self._lock:
            if res.get("ok"):
                self._tau = (bonds, res["tau"])
            self._kept = [x for x in self._kept if x[0] != key][-(FIT_KEPT - 1):] + [(key, res)]
        return dict(res, skipped=why)

    # ------------------------------------------------------------------ the page
    def view(self, user: Optional[str], locale: Optional[str] = None) -> Dict[str, Any]:
        svc = self.svc
        user = svc.require_user(user)
        loc = numfmt.get_locale(locale or svc.settings.locale)
        t0 = time.perf_counter()
        got = svc.et.call(self._read, user, loc)
        if got is None:
            return {"ok": False, "why": "DİBS RV sayfası yok", "gen": svc.gen}
        res = self.fit(got["quant"], got["live"], got["today"])
        lines = curve_lines(res, max([p["t"] for p in got["points"]] + [res["in"].longest if res.get("ok") else 0.0]) + 0.25)
        out = {"ok": True, "trading": dict(TRADING, n=got["n"], kinds=got["kinds"]), "fit": fit_summary(res),
               "chart": yield_chart(got["points"], lines, got["ois"]), "settings": got["settings"],
               "mirrors": [dict(m) for m in MIRRORS], "fx": got["fx"], "gen": got["gen"], "today": got["today"].isoformat(),
               "time": _dt.datetime.now().strftime("%H:%M:%S"), "ms": round((time.perf_counter() - t0) * 1000.0, 1),
               "tabs": [{"id": p, "title": t} for p, t in TABS]}
        return out

    def _read(self, user: str, loc) -> Optional[Dict[str, Any]]:
        """Calculation thread: the fit's inputs (the trading list's bonds as the quant fit reads them, this user's
        calculation), the chart's points, the settings, how many bonds of which kind the summary has."""
        from . import bonds as bd
        from .xl.model import COLS, parse_a1
        svc = self.svc
        book = svc.books.get("tto")
        if book is None or RV_SHEET not in book.model.sheet_index:
            return None
        index = book.model.sheet_index
        si = index[RV_SHEET]
        calc = svc._calc(user, book)
        R = svc.renderers[book.id]
        fx = svc._fx_curve(user)
        fits = rvfair.read_fits(calc, si, fx)

        def raw(c: str, r: int) -> Any:
            return calc.get(si, r, parse_a1("%s1" % c) % COLS)

        def cell(c: str, r: int, s: int = si) -> Dict[str, Any]:
            got = R.cell(calc, s, r, parse_a1("%s1" % c) % COLS, loc)
            return {"t": got.get("t", "")}

        eng: Dict[str, Any] = {}

        def reader(sheet: str):
            s = index[sheet]
            return lambda ref: calc.get(s, *divmod(parse_a1(ref), COLS))

        qc.read_engine(eng, index, reader, lambda v: v if type(v) is float and math.isfinite(v) else None)
        points: List[Dict[str, Any]] = []
        ois: List[Tuple[float, float]] = []
        kinds: Dict[str, int] = {}
        live_sheet = index.get(ex.LIVE_SHEET)
        for r in range(rvfair.FIRST, rvfair.LAST + 1):
            code = rvfair.isin_of(raw("A", r))
            if not code:
                continue
            known = bd.by_isin(code)
            kind = {"bill": "B", "zero": "B", "fixed": "S", "float": "T", "frn": "F", "cpi": "E"}.get((known or {}).get("kind")) or raw("D", r)
            kind = kind if kind in dict(KINDS) else "S"
            kinds[kind] = kinds.get(kind, 0) + 1
            label = cell("B", r, live_sheet)["t"] if live_sheet is not None else ""
            if known and label in ("", code):
                label = bd.short_label(known)
            years, comp = raw("F", r), raw("T", r)
            if kind in ("S", "B") and type(years) is float and type(comp) is float:
                points.append({"t": years, "y": comp * 100.0, "label": label or code, "isin": code})
            x = raw("X", r)
            if type(years) is float and type(x) is float:
                ois.append((years, x * 100.0))
        settings = []
        for ref, name, panel in SETTINGS:
            c = cell(ref[0], int(ref[1:]))
            settings.append({"ref": "%s!%s" % (RV_SHEET, ref), "label": name, "t": c.get("t") or "", "view": "dibs", "panel": panel})
        return {"quant": eng.get("dibs") or [], "live": qc.live_values(eng), "today": svc.history.today(), "points": points,
                "ois": ois, "settings": settings, "gen": svc.gen, "n": sum(kinds.values()),
                "kinds": [{"kind": k, "title": t, "n": kinds[k]} for k, t in KINDS if kinds.get(k)],
                "fx": {"curve": rvfair.FX_CURVE_TEXT, "swapped": fx.swapped if fx is not None else 0, "fit": {
                    k: v for k, v in fits["fx"].items() if k in ("coef", "n", "span", "why")}}}

    def zero_for(self, calc, index: Dict[str, int], today: _dt.date, bonds: List[Tuple[str, str]], loc) -> Dict[str, Dict[str, Any]]:
        """The bonds against the zero-coupon curve fitted now, as DİBS Trading's summary shows them (the bond table's one
        home, 28.11.2026): ``bonds`` (ISIN, DİBS RV's kind) -> each one's model yield, cheap / rich and fair price cells -
        or dashes that say why not.  The fit of ``calc``'s bonds (a user's own calculation: their own fit), kept for the
        same inputs (:meth:`fit`).  On the calculation thread (it reads DİBS RV)."""
        from .xl.model import COLS, parse_a1
        eng: Dict[str, Any] = {}

        def reader(sheet: str):
            s = index[sheet]
            return lambda ref: calc.get(s, *divmod(parse_a1(ref), COLS))

        qc.read_engine(eng, index, reader, lambda v: v if type(v) is float and math.isfinite(v) else None)
        quant = eng.get("dibs") or []
        res = self.fit(quant, qc.live_values(eng), today)
        rows = fit_rows(res) if res.get("ok") else {}
        return {isin: self._zero_cells({"isin": isin, "kind": kind if kind in dict(KINDS) else "S"}, res, rows, quant, loc)
                for isin, kind in bonds}

    @staticmethod
    def _zero_cells(line: Dict[str, Any], res: Dict[str, Any], rows: Dict[str, Dict[str, Any]], quant: List[Dict[str, Any]],
                    loc) -> Dict[str, Dict[str, Any]]:
        """A bond against the zero-coupon curve: its model yield, cheap / rich and fair price - or a dash that says why not."""
        def dash(why: str) -> Dict[str, Dict[str, Any]]:
            d = {"t": "–", "k": "s", "al": "r", "cls": "soft", "tip": "Sıfır kupon eğrisine karşı ölçülmedi: " + why}
            return {"z_model": dict(d), "z_rc": dict(d), "z_fp": dict(d)}

        isin, kind = line["isin"], line["kind"]
        if kind in NO_ZERO:
            return dash(NO_ZERO[kind])
        if not res.get("ok"):
            return dash(res.get("why") or "eğri uydurulamadı")
        x = rows.get(isin)
        if x is None:
            why = (res.get("skipped") or {}).get(isin)
            if why is None:
                listed = any(q["isin"] == isin for q in quant)
                why = ("vadesine %d günden az kaldı" % qc.MIN_DAYS) if listed else "DİBS RV kâğıdı hesaplamıyor (türü / fiyatı yok)"
            return dash(why)

        def n(v: float, fmt: str) -> str:
            return numfmt.format_value(v, fmt, loc)

        fit_in = res["in"]
        role = ("uydurmada (ağırlık %s)" % n(x["weight"], "0.00")) if x["fitted"] and x["weight"] is not None and x["weight"] < 1.0 \
            else ("uydurmada" if x["fitted"] else "uydurmaya girmez, eğriye karşı ölçülür")
        bills = (", %d bono eğriye göre ölçüldü" % fit_in.n_bills) if fit_in.n_bills else ""
        tip = ("%s sıfır kupon eğrisi (%d sabit kuponluya uyduruldu%s) · %s · getiri %s (basit) − model %s = %s bp · "
               "adil fiyat: Σ CF·DF valörde (%s) kirli %s − işlemiş %s = temiz %s · eğride getiri %s (basit)"
               % (res["nss"].model, fit_in.n_fit, bills, role, n(x["yield"] / 100.0, "0.00%"),
                  n(x["model"] / 100.0, "0.00%"), n(x["resid"], "0.0"),
                  x["value_date"], n(x["fair"]["dirty"], "0.000"), n(x["accrued"], "0.000"), n(x["fair"]["clean"], "0.000"),
                  n(x["fair"]["yield"] / 100.0, "0.00%")))
        return {"z_model": {"t": n(x["model"] / 100.0, "0.00%"), "v": x["model"] / 100.0, "k": "n", "tip": tip},
                "z_rc": {"t": n(x["resid"], "0"), "v": x["resid"], "k": "n", "tip": tip},
                "z_fp": {"t": n(x["fair"]["clean"], "0.000"), "v": x["fair"]["clean"], "k": "n", "tip": tip}}
