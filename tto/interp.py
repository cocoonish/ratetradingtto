"""The TRY curves between their quoted tenors, each user's own choice (Ayarlar → Eğri interpolasyonu, 18.11.2026):
**Bootstrap (Murex)** - today's curve, the default - or **PPK basamak** (:mod:`tto.ppkcurve`: TLREF flat between PPK
meetings, every quote repriced).  The workbook side is ``extras.INTERP_SHEET`` (the choice, the PPK cells, Motor's par
rates and the offshore names that follow it; the ASW book's curve of today the same way); this module fills the PPK
cells and keeps them current:

* **the desk's PPK cells** - the PPK curves read off the shared calculation (on Bootstrap: the PPK curve never reads
  itself) are written into the PPK cells as shared inputs, uncounted (``Engine.set_inputs(counted=False)``: a curve made
  of the market is no change of the desk's inputs).  On Bootstrap nothing reads them (nested IFs: a cell's dependency
  mask holds what it read), so writing them recomputes nothing of anybody on Bootstrap - only what a PPK user's
  calculation read of them.  They are made when a PPK user's calculation is asked for (:meth:`Interp.sync`, on the
  calculation thread) and again only when anything they were made of changed (the masks of what making them read:
  quotes, MPC ima, the calendars, the spots) - nobody on PPK, nothing made.
* **a PPK user's own** - a user whose own inputs touch what the PPK curves are made of (an OIS quote typed with
  "Elle değer", TLREF ...) gets PPK cells of their own, made from their own calculation with the curve on Bootstrap (a
  layer over it), on top of their inputs (``Engine.derived``: worked out, never stored or listed as their inputs).  So
  does the ASW book: the user's choice is mirrored into it (its ``B2``) and its PPK cells are the TRY workbook's MPC ima
  calibrated to the ASW book's own quotes and node days.
* :meth:`Interp.boot_view` - a user's calculation with the curve on Bootstrap (Günlük İşlemler's quotes and records: the
  desk's records stay on Bootstrap); :meth:`Interp.desk_view` - the desk's (shared) calculation on either curve (Trades:
  each viewer's curve; the snapshots kept for both).
* **the desk's list of points** (Ayarlar → Eğri noktaları, tto/curvepoints.py) - on the default list nothing of this
  is written (the workbook's own formulas, as before).  A curve whose list differs takes its Bootstrap from the list
  (:meth:`Interp.apply_list`: the list's flags and its tickers, counted: a change of the desk's; :meth:`Interp.refresh_list`:
  Motor's node pars and the offshore node table on the list, made from the desk's calculation - nothing of it reads them
  - whenever what they are made of changed: the market loop, any calculation asked for), and the PPK cells are made from
  the list's points.  A user whose own inputs touch the list's quotes gets list cells of their own, as above.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import aswfx
from . import extras as ex
from . import ppkcurve as pk
from .xl.model import COLS, parse_a1

BOOT, PPK = "boot", "ppk"
#: the choice as the sheet holds it
CHOICE = {BOOT: ex.INTERP_BOOT, PPK: ex.INTERP_PPK}
#: what the settings say of each
ABOUT = {BOOT: "Bugünkü eğri, Murex'in MTM'i: OIS par kotaları aylara göre doğrusal, çeyreklik bootstrap, aralarında ln DF "
               "günlere göre doğrusal; offshore eğri FX swap ima (≤9A) + XCCY bootstrap'ı.",
         PPK: "TLREF PPK toplantıları arasında sabit (PPK çözücüsünün ima patikası, MPC ima), iki kotalı vade arasında sabit bir "
              "O/N kaydırmayla bütün kotalara aynen oturur; offshore'da aynı patika + kotalar arasında sabit baz."}
#: what the badge's tip adds while the user's TLREF normalization is on (OIS · PPK)
NORM_ABOUT = ("TLREF normalleşmesi açık (OIS · PPK): patika modelin normal patikası + normalleşme tarihine kadar fark (bugünkü "
              "TLREF − normal TLREF); kotalara yine aynen oturur.")
#: the engine-level groups of the PPK cells (one dependency bit each: the OIS nodes, the offshore table, the ASW nodes)
GROUP_OIS, GROUP_OFF, GROUP_ASW, GROUP_MIRROR = "interp-ppk-ois", "interp-ppk-off", "interp-ppk-asw", "interp-mode-asw"
#: ... and of the desk's list (Motor's node pars on the list, the offshore table on it, each curve's flag)
GROUP_LIST_OIS, GROUP_LIST_OFF, GROUP_LIST_FLAG = "interp-list-ois", "interp-list-off", "interp-list-on"
#: the offshore table's rows past the curve's last node lie on its last segment, this many days apart
FAR = 36500.0
#: the layers kept: a user's calculation with the curve on Bootstrap, the desk's on PPK
BOOT_LAYER, PPK_LAYER = "interp-boot", "interp-ppk"


def _num(v: Any) -> Optional[float]:
    return float(v) if type(v) in (float, int) and v == v else None


def off_nodes(curve: Any, quotes: Sequence[Any], rows: int) -> Optional[List[Tuple[float, float, float]]]:
    """The offshore curve's node table on PPK: ``(day, ln DF, slope)`` at the spot, every step of the PPK-shaped curve
    (a meeting, the end of a basis stretch) and every quote's coupon day up to its last quote and that quote's day - the
    readers interpolate ln DF linearly between them, which is the step curve's own shape up to the weekend term - then
    the last segment's slope on, the rest of the ``rows`` on that segment far beyond (as the sheet's own curve goes on
    past its last node).  ``None`` without a curve or a quote."""
    if curve is None or not quotes:
        return None
    last = max(q.end for q in quotes)
    # (a quote's coupon days too: on the default list each is an earlier quote's maturity already - a point of the desk's
    # list counted back from its maturity has its own, and the table prices it back exactly with them)
    coupons = {p for q in quotes for p in q.pays if 0.0 < p < last}
    days = sorted({0.0, last} | {d for d, _ in curve.steps() if 0.0 < d < last} | coupons)
    if len(days) > rows:                            # (never with ~80 meetings and 19 quotes: the quotes kept first)
        ends = {q.end for q in quotes}
        keep = sorted(ends | {0.0})
        rest = [d for d in days if d not in ends and d != 0.0][:max(rows - len(keep), 0)]
        days = sorted(set(keep) | set(rest))
    ln = [-curve.lng(d) for d in days]
    if len(days) < 2:
        return None
    return _table(days, ln, rows)


def _table(days: Sequence[float], ln: Sequence[float], rows: int) -> List[Tuple[float, float, float]]:
    """``(day, ln DF, slope)`` rows of a node table as the offshore names read it (``LOOKUP``: the node at or before a day,
    on along its slope): each node's slope to the next, the last one's the slope before it, then rows far beyond on that
    last segment up to ``rows``."""
    slopes = [(ln[i + 1] - ln[i]) / (days[i + 1] - days[i]) for i in range(len(days) - 1)]
    slopes.append(slopes[-1])
    out = list(zip(days, ln, slopes))
    d0, l0, s0 = out[-1]
    k = 1
    while len(out) < rows:
        out.append((d0 + FAR * k, l0 + s0 * FAR * k, s0))
        k += 1
    return out


def boot_nodes(curve: Any, rows: int) -> Optional[List[Tuple[float, float, float]]]:
    """The offshore curve's node table on the desk's list (Bootstrap): a node at every point (:func:`ppkcurve.list_curves`'s
    curve: the spot, then each point's maturity), as the Forward sheet's own table (AK:AN) holds its quotes'.  ``None``
    without a curve (or with more nodes than rows)."""
    if curve is None or len(curve.days) < 2 or len(curve.days) > rows:
        return None
    return _table(list(curve.days), list(curve.lndf), rows)


class Interp(object):
    def __init__(self, svc: Any):
        self.svc = svc
        self.tto = self._book("tto")
        self.asw = self._book("asw") if self.tto is not None else None
        self._lock = threading.RLock()
        self._shared: Dict[str, Dict[str, Any]] = {}             # book -> the desk's PPK cells as last made
        self._own: Dict[Tuple[str, str], Dict[str, Any]] = {}    # (user, book) -> a user's own, as last made
        self._typed: Dict[Tuple[str, str], Tuple[Any, int]] = {}  # (user, book) -> (their inputs, those inputs' bits)
        self.stats: Dict[str, Any] = {"made": 0, "ms": 0.0, "last_ms": None, "own": 0, "own_ms": 0.0, "at": None,
                                      "changed": 0}
        if self.tto is not None:
            m = self.tto.model
            si = m.sheet_index[ex.INTERP_SHEET]
            self.mode_cell = (si, parse_a1(ex.INTERP_MODE))
            self.mode_ref = "%s!%s" % (ex.INTERP_SHEET, ex.INTERP_MODE)
            f, l = ex.INTERP_NODES
            c = parse_a1("C1") % COLS
            self.ois_cells = {r: (si, (r - ex.INTERP_SHIFT) * COLS + c) for r in range(f + 1, l + 1)}
            self.off_cells = [tuple((si, r * COLS + parse_a1(col + "1") % COLS) for col in ("I", "J", "K"))
                              for r in range(ex.INTERP_OFF_FIRST, ex.INTERP_OFF_LAST + 1)]
            self.status_cells = {k: (si, parse_a1(a)) for k, a in (("on", ex.INTERP_ON), ("off", ex.INTERP_OFF_ON),
                                                                       ("text", ex.INTERP_STATUS))}
            # TLREF's normalization (the user's switch on OIS · PPK): its ON cell - on, the PPK path is the normal one +
            # the gap up to the normalization date (ppkcurve.read), and the badge says so
            sheet, row, col = pk.NORM_ON
            self.norm_cell = (m.sheet_index[sheet], row * COLS + col) if sheet in m.sheet_index else None
            # the desk's list of points: each curve's flag, Motor's node pars and the offshore table on the list, the
            # tickers of its ticker points
            pc = parse_a1(ex.LIST_PAR_COL + "1") % COLS
            self.list_flags = {"ois": (si, parse_a1(ex.LIST_OIS_ON)), "off": (si, parse_a1(ex.LIST_OFF_ON))}
            self.list_ois_cells = {r: (si, (r - ex.INTERP_SHIFT) * COLS + pc) for r in range(f + 1, l + 1)}
            self.list_off_cells = [tuple((si, r * COLS + parse_a1(ex.LIST_OFF_COLS[n] + "1") % COLS)
                                         for n in ("OFF_GUN", "OFF_LNDF", "OFF_SL"))
                                   for r in range(ex.INTERP_OFF_FIRST, ex.INTERP_OFF_LAST + 1)]
            tc = parse_a1(ex.LIST_TICKER_COL + "1") % COLS
            self.ticker_cells = [(si, (ex.LIST_TICKER_FIRST + k) * COLS + tc) for k in range(ex.LIST_TICKERS)]
        if self.asw is not None:
            si = self.asw.model.sheet_index[ex.INTERP_SHEET]
            self.asw_mode_cell = (si, parse_a1(ex.INTERP_MODE))
            self.asw_cells = [(si, (ex.INTERP_FIRST + i) * COLS + parse_a1("C1") % COLS) for i in range(1, len(aswfx.NODES))]

    def _book(self, bid: str) -> Any:
        b = getattr(self.svc, "books", {}).get(bid)
        if b is None or ex.INTERP_SHEET not in b.model.sheet_index:
            return None
        if any(x.startswith((ex.INTERP_NAME + ":", ex.INTERP_ASW_NAME + ":")) for x in getattr(b, "left_out", [])):
            return None
        return b

    @property
    def available(self) -> bool:
        return self.tto is not None

    # ------------------------------------------------------------------ setup
    def declare(self) -> None:
        """The cells the service writes, to the engines (not inputs of a page: nobody types into them) - and the choice, a
        personal input of the TRY workbook (Ayarlar; "Girdilerimi sıfırla" takes it back to Bootstrap)."""
        if self.tto is None:
            return
        self.tto.declare(self.mode_ref, scope="user", group="interp", kind="list", options=list(ex.INTERP_CHOICES),
                         aliases={"BOOTSTRAP": ex.INTERP_BOOT, "MUREX": ex.INTERP_BOOT, "PPK": ex.INTERP_PPK},
                         label="Eğri interpolasyonu – kotalı vadeler arası: Bootstrap (Murex) / PPK basamak (Ayarlar)",
                         view="settings")
        eng = self.tto.engine
        eng.declare_inputs(list(self.ois_cells.values()), group=GROUP_OIS)
        eng.declare_inputs([c for row in self.off_cells for c in row], group=GROUP_OFF)
        eng.declare_inputs(list(self.list_ois_cells.values()), group=GROUP_LIST_OIS)
        eng.declare_inputs([c for row in self.list_off_cells for c in row], group=GROUP_LIST_OFF)
        for curve, cell in self.list_flags.items():
            eng.declare_inputs([cell], group="%s-%s" % (GROUP_LIST_FLAG, curve))
        eng.declare_inputs(self.ticker_cells)            # (each its own bit: a new ticker computes its own slot only)
        if self.asw is not None:
            self.asw.engine.declare_inputs([self.asw_mode_cell], group=GROUP_MIRROR)
            self.asw.engine.declare_inputs(self.asw_cells, group=GROUP_ASW)

    # ------------------------------------------------------------------ whose curve
    def mode(self, user: Optional[str]) -> str:
        """The user's choice (``BOOT`` / ``PPK``); nobody (the desk, the service itself): Bootstrap.  Any thread: their
        inputs as the service holds them, else as they are stored (nothing of the engine's is touched)."""
        if not user or self.tto is None:
            return BOOT
        ov = self.svc._overlays.get((user, "tto"))
        if ov is not None:
            return PPK if ov.get(self.mode_cell) == ex.INTERP_PPK else BOOT
        try:
            stored = self.svc.store.user_inputs(user, "tto")
        except Exception:  # noqa: BLE001 - a store that cannot be read: the default
            return BOOT
        return PPK if stored.get(("tto", self.mode_ref)) == ex.INTERP_PPK else BOOT

    def ppk_users(self) -> List[str]:
        """The users on PPK the service holds the inputs of now."""
        if self.tto is None:
            return []
        return sorted(u for (u, bid), ov in list(self.svc._overlays.items())
                      if bid == "tto" and ov.get(self.mode_cell) == ex.INTERP_PPK)

    def _typed_bits(self, user: str, book: Any, skip: Sequence[Tuple[int, int]] = ()) -> int:
        """The dependency bits of the user's own inputs in ``book`` (without ``skip``: the choice itself)."""
        ov = self.svc._overlay(user, book)
        hit = self._typed.get((user, book.id))
        if hit is not None and hit[0] is ov:
            return hit[1]
        bits = 0
        masks = book.engine.input_mask
        for (si, rc) in ov:
            if (si, rc) not in skip:
                bits |= masks[si].get(rc, 0)
        self._typed[(user, book.id)] = (ov, bits)
        return bits

    # ------------------------------------------------------------------ making the PPK cells
    @staticmethod
    def _tracked(calc: Any, fn) -> Tuple[Any, int]:
        """``fn()`` with what it read through ``calc.get`` tracked: (its result, the masks of what it read)."""
        outer, calc.track = calc.track, 0
        try:
            res = fn()
            mask = calc.track
        finally:
            calc.track = None if outer is None else outer | (calc.track or 0)
        return res, mask

    def _tto_values(self, calc: Any) -> Tuple[Dict[Tuple[int, int], Any], Dict[str, Any], int]:
        """The TRY workbook's PPK cells out of ``calc`` (a calculation on Bootstrap): the PPK discount factor at each of
        Motor's node days, the offshore node table - ``None`` where a curve cannot be made (the sheet then stays on
        Bootstrap).  With the curves read (:func:`ppkcurve.read`) and the masks of what was read."""
        idx = self.tto.model.sheet_index
        points = self._points()

        def make():
            get = lambda sheet, r, c: calc.get(idx[sheet], r, c)          # noqa: E731
            curves = pk.read(get, points)
            days = {r: _num(get("Motor", r, pk.BOOT_DAY)) for r in self.ois_cells}
            return curves, days

        (curves, days), mask = self._tracked(calc, make)
        vals: Dict[Tuple[int, int], Any] = {}
        ppk = curves.get("ppk")
        whole = ppk is not None and all(d is not None for d in days.values())
        for r, cell in self.ois_cells.items():
            vals[cell] = ppk.df(days[r]) if whole else None
        table = off_nodes(curves.get("off_ppk"), curves.get("off_quotes") or [], len(self.off_cells))
        for i, cells in enumerate(self.off_cells):
            for j, cell in enumerate(cells):
                vals[cell] = table[i][j] if table is not None else None
        return vals, curves, mask

    def _asw_values(self, curves: Dict[str, Any], tto_calc: Any, calc: Any) -> Tuple[Dict[Tuple[int, int], Any], int]:
        """The ASW book's PPK cells: the TRY workbook's MPC ima (``curves["shape"]``, seen from the ASW book's spot)
        calibrated to the ASW book's own quotes of today at its own node days, its ln DF at each node - ``None`` when it
        cannot be made."""
        si = self.asw.model.sheet_index["ASW"]
        row = aswfx.ROW

        def make():
            q = [calc.get(si, row, aswfx.QUOTE_COL + k) for k in range(len(aswfx.TENORS))]
            d = [calc.get(si, row, aswfx.DAY_COL + i) for i in range(len(aswfx.NODES))]
            spot = calc.get(si, row, parse_a1("T1") % COLS)
            return q, d, spot

        (quotes, days, spot), mask = self._tracked(calc, make)
        ois_spot = _num(tto_calc.get(*self._ref(self.tto, pk.OIS_SPOT)))
        vals: Dict[Tuple[int, int], Any] = {c: None for c in self.asw_cells}
        shape = curves.get("shape") if curves else None
        if shape is None or _num(spot) is None or ois_spot is None:
            return vals, mask
        rates = [(_num(x) / 100.0 if _num(x) is not None else None) for x in quotes]
        q = pk.ois_quotes(aswfx.TENORS, rates, aswfx.NODES, days)
        if not q:
            return vals, mask
        try:
            curve, _ = pk.calibrate(shape.rebased(max(0.0, float(spot) - ois_spot)), q)
        except ValueError:
            return vals, mask
        for i, cell in enumerate(self.asw_cells, 1):
            t = _num(days[i])
            vals[cell] = -curve.lng(t) if t is not None else None
        return vals, mask

    @staticmethod
    def _ref(book: Any, at: Tuple[str, int, int]) -> Tuple[int, int, int]:
        sheet, r, c = at
        return book.model.sheet_index[sheet], r, c

    @staticmethod
    def _fresh(st: Optional[Dict[str, Any]], key: Tuple, calcs: Sequence[Tuple[Any, int, int]]) -> bool:
        """Whether what was made from ``calcs`` (``(calc, epoch, mask)`` each) still stands: the same calculations, and
        nothing they read invalidated since."""
        if st is None or st["key"] != key:
            return False
        for calc, epoch, mask in calcs:
            m = calc.changed_since(epoch)
            if m is None or (m & mask):
                return False
        return True

    def refresh(self) -> Dict[str, Any]:
        """The desk's PPK cells (the TRY workbook's, then the ASW book's) brought up to date - made only when anything
        they were made of changed since.  Calculation thread."""
        with self._lock:
            st = self._refresh_tto()
            if self.asw is not None:
                self._refresh_asw(st)
            return st

    def _refresh_tto(self) -> Dict[str, Any]:
        eng = self.tto.engine
        calc = eng.shared
        key = (eng.layout, calc.serial, self._rev())
        st = self._shared.get("tto")
        if st is not None and self._fresh(st, key, [(calc, st["epoch"], st["mask"])]):
            return st
        t0 = time.perf_counter()
        vals, curves, mask = self._tto_values(calc)
        epoch = calc.epoch
        changed = eng.set_inputs(vals, counted=False)
        ms = (time.perf_counter() - t0) * 1000.0
        st = {"key": key, "epoch": epoch, "mask": mask, "curves": curves, "values": vals, "ms": ms,
              "version": (st["version"] + 1) if st else 1}
        self._shared["tto"] = st
        self.stats.update(made=self.stats["made"] + 1, ms=self.stats["ms"] + ms, last_ms=round(ms, 1),
                          at=time.strftime("%H:%M:%S"), changed=self.stats["changed"] + (1 if changed else 0))
        return st

    def _refresh_asw(self, tto_st: Dict[str, Any]) -> Dict[str, Any]:
        eng = self.asw.engine
        calc = eng.shared
        key = (eng.layout, calc.serial, tto_st["version"])
        st = self._shared.get("asw")
        if st is not None and self._fresh(st, key, [(calc, st["epoch"], st["mask"])]):
            return st
        vals, mask = self._asw_values(tto_st["curves"], self.tto.engine.shared, calc)
        epoch = calc.epoch
        eng.set_inputs(vals, counted=False)
        st = {"key": key, "epoch": epoch, "mask": mask, "values": vals}
        self._shared["asw"] = st
        return st

    # ------------------------------------------------------------------ the desk's list of points (tto/curvepoints.py)
    def _list(self) -> Any:
        return getattr(self.svc, "curvepoints", None)

    def _points(self) -> Optional[Dict[str, Any]]:
        """The points of the curves whose list differs from the default (:func:`ppkcurve.read`'s ``points``)."""
        cp = self._list()
        return cp.specs() if cp is not None else None

    def _rev(self) -> int:
        cp = self._list()
        return cp.rev if cp is not None else 0

    def listed(self) -> bool:
        """Whether any curve's list differs from the default (its Bootstrap then the list's)."""
        cp = self._list()
        return self.tto is not None and cp is not None and cp.custom()

    def apply_list(self) -> None:
        """The desk's list into the workbook - after a change and at the start: each curve's flag (1: its list differs
        from the default) and the tickers of the ticker points (an empty slot asks Bloomberg nothing), a change of the
        desk's inputs; then the list's own cells made again.  On the default list nothing changes.  Calculation thread."""
        cp = self._list()
        if self.tto is None or cp is None:
            return
        vals: Dict[Tuple[int, int], Any] = {cell: (1.0 if cp.custom(curve) else 0.0) for curve, cell in self.list_flags.items()}
        tickers = cp.tickers()
        for k, cell in enumerate(self.ticker_cells):
            vals[cell] = tickers.get(k)
        with self._lock:
            self.tto.engine.set_inputs(vals)
            self.refresh_list()

    def refresh_list(self) -> Optional[Dict[str, Any]]:
        """The desk's list cells - Motor's node pars and the offshore node table on the list - brought up to date: made
        from the desk's calculation (which reads them; making them reads only the points' quotes, Motor's node days, the
        spots and the calendars) when anything they were made of changed; emptied once no curve's list differs from the
        default.  Calculation thread."""
        if self.tto is None:
            return None
        with self._lock:
            eng = self.tto.engine
            st = self._shared.get("list")
            if not self.listed():
                if st is not None:
                    eng.set_inputs({c: None for c in st["values"]}, counted=False)
                    self._shared.pop("list", None)
                return None
            calc = eng.shared
            key = (eng.layout, calc.serial, self._rev())
            if st is not None and self._fresh(st, key, [(calc, st["epoch"], st["mask"])]):
                return st
            t0 = time.perf_counter()
            vals, curves, mask = self._list_values(calc)
            epoch = calc.epoch
            eng.set_inputs(vals, counted=False)
            st = {"key": key, "epoch": epoch, "mask": mask, "values": vals, "curves": curves}
            self._shared["list"] = st
            self.stats.update(list_made=self.stats.get("list_made", 0) + 1,
                              list_ms=round((time.perf_counter() - t0) * 1000.0, 1))
            return st

    def list_errors(self) -> List[str]:
        """Why the desk's list's curves could not be built as last made (the workbook's own curve stands meanwhile)."""
        st = self._shared.get("list") or {}
        return list((st.get("curves") or {}).get("errors") or [])

    def _list_values(self, calc: Any) -> Tuple[Dict[Tuple[int, int], Any], Dict[str, Any], int]:
        """The list cells out of ``calc``: Motor's node pars of the OIS list's Bootstrap, the offshore list's node table -
        ``None`` for a curve on the default list (or one that cannot be built: the workbook's own then).  With the curves
        (:func:`ppkcurve.list_curves`) and the masks of what was read."""
        idx = self.tto.model.sheet_index
        points = self._points() or {}

        def make():
            return pk.list_curves(lambda sheet, r, c: calc.get(idx[sheet], r, c), points)

        curves, mask = self._tracked(calc, make)
        vals: Dict[Tuple[int, int], Any] = {}
        ois = curves.get("ois")
        for r, cell in self.list_ois_cells.items():
            vals[cell] = ois["pars"].get(r) if ois is not None else None
        off = curves.get("off")
        table = boot_nodes(off["boot"], len(self.list_off_cells)) if off is not None else None
        for i, cells in enumerate(self.list_off_cells):
            for j, cell in enumerate(cells):
                vals[cell] = table[i][j] if table is not None else None
        return vals, curves, mask

    def _own_list(self, user: str, lst: Optional[Dict[str, Any]]) -> Optional[Dict[Tuple[int, int], Any]]:
        """The user's own list cells when their own inputs touch what the desk's were made of (a point's quote typed over -
        "Elle değer"): made from their calculation, kept while nothing they were made of changes.  ``None``: the desk's
        stand for them."""
        if lst is None:
            self._own.pop((user, "list"), None)
            return None
        book = self.tto
        if not (self._typed_bits(user, book, (self.mode_cell,)) & lst["mask"]):
            self._own.pop((user, "list"), None)
            return None
        eng = book.engine
        base = eng.users.get(user) or eng.set_user_inputs(user, self.svc._overlay(user, book))
        key = (eng.layout, base.serial, self._rev())
        st = self._own.get((user, "list"))
        if st is not None and self._fresh(st, key, [(base, st["epoch"], st["mask"])]):
            return st["values"]
        vals, curves, mask = self._list_values(base)
        self._own[(user, "list")] = {"key": key, "epoch": base.epoch, "mask": mask, "values": vals, "curves": curves}
        return vals

    # ------------------------------------------------------------------ a user's calculation
    def sync(self, user: Optional[str], book: Any) -> None:
        """Before a user's calculation of ``book`` is used (``Service._calc``): on PPK, the desk's PPK cells current and
        the user's own where their inputs make them their own (and, in the ASW book, their choice mirrored); on Bootstrap
        nothing of theirs worked out."""
        if not user or self.tto is None or book is None or book.id not in ("tto", "asw") or \
                (book.id == "asw" and self.asw is None):
            return
        eng = book.engine
        listed = book.id == "tto" and self.listed()
        if self.mode(user) != PPK:
            if listed:
                with self._lock:
                    own = self._own_list(user, self.refresh_list())
                eng.set_derived(user, own or {}, self.svc._overlay(user, book))
            elif eng.derived.get(user):
                eng.set_derived(user, {}, self.svc._overlay(user, book))
            self._own.pop((user, book.id), None)
            if book.id == "tto" and not listed:
                self._own.pop((user, "list"), None)
            return
        with self._lock:
            lst = self.refresh_list() if listed else None
            tto_st = self.refresh()
            own_tto = self._own_tto(user, tto_st)
            if book.id == "tto":
                vals = dict(own_tto[0]) if own_tto is not None else {}
                vals.update(self._own_list(user, lst) or {})
                eng.set_derived(user, vals, self.svc._overlay(user, book))
                return
            vals: Dict[Tuple[int, int], Any] = {self.asw_mode_cell: ex.INTERP_PPK}
            asw_st = self._shared.get("asw")
            typed = self.svc._overlay(user, book)
            if own_tto is not None or (asw_st is not None and self._typed_bits(user, book) & asw_st["mask"]):
                calc = eng.users.get(user) or eng.set_derived(user, vals, typed) or eng.set_user_inputs(user, typed)
                src = own_tto if own_tto is not None else (None, tto_st["curves"], ("desk", tto_st["version"]))
                vals.update(self._own_asw(user, calc, src[1], src[2]))
            else:
                self._own.pop((user, "asw"), None)
            eng.set_derived(user, vals, typed)

    def _own_tto(self, user: str, tto_st: Dict[str, Any]) -> Optional[Tuple[Dict[Tuple[int, int], Any], Dict[str, Any], Tuple]]:
        """The user's own PPK cells of the TRY workbook when their own inputs touch what the desk's were made of: made
        from their calculation with the curve on Bootstrap - with the curves and a tag of this making.  ``None``: the
        desk's stand for them."""
        book = self.tto
        if not (self._typed_bits(user, book, (self.mode_cell,)) & tto_st["mask"]):
            self._own.pop((user, "tto"), None)
            return None
        eng = book.engine
        base = eng.users.get(user) or eng.set_user_inputs(user, self.svc._overlay(user, book))
        view = eng.layer((user, BOOT_LAYER), base, self.boot_cells(book))
        key = (eng.layout, view.serial, base.serial, self._rev())
        st = self._own.get((user, "tto"))
        if st is not None and self._fresh(st, key, [(view, st["epoch"], st["mask"])]):
            return st["values"], st["curves"], st["tag"]
        t0 = time.perf_counter()
        vals, curves, mask = self._tto_values(view)
        tag = (user, view.serial, view.epoch, time.perf_counter())
        self._own[(user, "tto")] = {"key": key, "epoch": view.epoch, "mask": mask, "values": vals, "curves": curves, "tag": tag}
        self.stats.update(own=self.stats["own"] + 1, own_ms=self.stats["own_ms"] + (time.perf_counter() - t0) * 1000.0)
        return vals, curves, tag

    def _own_asw(self, user: str, base: Any, curves: Dict[str, Any], tag: Tuple) -> Dict[Tuple[int, int], Any]:
        """The user's own PPK cells of the ASW book: MPC ima as they have it (``curves``, made as ``tag`` says),
        calibrated to their ASW book's quotes - made again when either changes."""
        eng = self.asw.engine
        view = eng.layer((user, BOOT_LAYER), base, self.boot_cells(self.asw))
        key = (eng.layout, view.serial, base.serial, tag)
        st = self._own.get((user, "asw"))
        if st is not None and self._fresh(st, key, [(view, st["epoch"], st["mask"])]):
            return st["values"]
        vals, mask = self._asw_values(curves, self.boot_view(user, self.tto, sync=False), view)
        self._own[(user, "asw")] = {"key": key, "epoch": view.epoch, "mask": mask, "values": vals}
        return vals

    # ------------------------------------------------------------------ calculations on a curve
    def boot_cells(self, book: Any) -> Dict[Tuple[int, int], Any]:
        """The input that puts a calculation of ``book`` on Bootstrap whatever its user's choice (a layer's own: a curve
        of its own - the ASW history against the offshore curve - is bootstrapped from its own quotes)."""
        if self.tto is not None and book is self.tto:
            return {self.mode_cell: ex.INTERP_BOOT}
        if self.asw is not None and book is self.asw:
            return {self.asw_mode_cell: ex.INTERP_BOOT}
        return {}

    def boot_of(self, book: Any, calc: Any) -> Any:
        """``calc`` with the curve on Bootstrap - what the "both ways" views (the FRA lists', Günlük İşlemler's and the
        broken-date block's PPK columns, ``Service._try_curves``) read their Bootstrap side from: the true bootstrap,
        whatever its user chose.  Itself when it reads the curve so (the desk's, a Bootstrap user's, a layer put on
        Bootstrap); else a layer over it, kept with its user's (or its copy's) layers."""
        cells = self.boot_cells(book)
        if not cells or calc is None or calc is book.engine.shared:
            return calc
        (si, rc), = cells.keys()
        if calc.get(si, *divmod(rc, COLS)) != ex.INTERP_PPK:
            return calc
        eng = book.engine
        owner = next((u for u, c in eng.users.items() if c is calc), None)
        if owner is not None:
            return eng.layer((owner, BOOT_LAYER), calc, cells)
        key = next((k for k, c in eng.layers.items() if c is calc), None)
        if isinstance(key, tuple) and key and key[-1] != BOOT_LAYER:
            return eng.layer(key + (BOOT_LAYER,), calc, cells)        # (a copy's: dropped with it)
        return calc

    def boot_view(self, user: Optional[str], book: Any, sync: bool = True) -> Any:
        """The user's calculation of ``book`` with the curve on Bootstrap whatever their choice - their own inputs
        otherwise as they are (a layer over it on PPK).  Nobody: the desk's."""
        if not user:
            return book.engine.shared
        calc = self.svc._calc(user, book) if sync else (book.engine.users.get(user) or book.engine.shared)
        cells = self.boot_cells(book)
        if not cells or self.mode(user) != PPK or calc is book.engine.shared:
            return calc
        return book.engine.layer((user, BOOT_LAYER), calc, cells)

    def boot_overlay(self, user: Optional[str], book: Any) -> Dict[Tuple[int, int], Any]:
        """The user's own inputs of ``book`` without their curve choice (what a calculation of its own made over the
        desk's from them - Günlük İşlemler's quotes - takes: Bootstrap)."""
        if not user:
            return {}
        ov = dict(self.svc._overlay(user, book))
        if self.tto is not None and book is self.tto:
            ov.pop(self.mode_cell, None)
        return ov

    def desk_view(self, curve: str = BOOT) -> Tuple[Any, str]:
        """The desk's (shared) calculation of the TRY workbook on ``curve`` - and the curve it is really on: PPK needs its
        cells (made here when they are not current); a PPK curve that cannot be made is Bootstrap."""
        book = self.tto
        if book is None:
            b = self.svc.books.get("tto")
            return (b.engine.shared if b is not None else None), BOOT
        if self.listed():
            self.refresh_list()                         # (the desk's calculation reads the list's cells)
        if curve != PPK:
            return book.engine.shared, BOOT
        with self._lock:
            st = self.refresh()
        if not any(v is not None for v in st["values"].values()):
            return book.engine.shared, BOOT
        eng = book.engine
        return eng.layer(("", PPK_LAYER), eng.shared, {self.mode_cell: ex.INTERP_PPK}), PPK

    # ------------------------------------------------------------------ what the pages show
    def badge(self, user: Optional[str], calc: Any) -> Optional[Dict[str, Any]]:
        """The top bar's mark of a user on PPK (``None`` on Bootstrap): read from their calculation (what the header read
        counts: a change made again)."""
        if self.tto is None or not user or self.mode(user) != PPK:
            return None

        def at(k: str) -> Any:
            si, rc = self.status_cells[k]
            return calc.get(si, *divmod(rc, COLS))

        on = at("on") == 1.0
        text = at("text")
        # (TLREF's normalization on: the curve's path is the normal one + the gap up to the normalization date)
        norm = on and self.norm_cell is not None and calc.get(*self._cell3(self.norm_cell)) == 1.0
        label = ("Eğri: PPK basamak · normalleşme açık" if norm else "Eğri: PPK basamak") if on else "Eğri: PPK (kurulamadı)"
        out = {"mode": PPK, "on": on, "off": at("off") == 1.0, "label": label,
               "tip": (text if isinstance(text, str) else "") + "\n" + ABOUT[PPK] + "\nAyarlar → Eğri interpolasyonu: "
                      "sayfaların, Trades'in MTM'inin bu eğriyle; Günlük İşlemler ve masanın kayıtları (MTM / kapanış "
                      "kayıtlarının Bootstrap'ı, alarmlar, quant, tarihçe) Bootstrap'ta. Sizin ayarınız: başkaları Bootstrap "
                      "görebilir."}
        if norm:
            out["norm"] = True
            out["tip"] += "\n" + NORM_ABOUT
        return out

    def settings(self, user: Optional[str]) -> Dict[str, Any]:
        """Ayarlar → Eğri interpolasyonu: the user's choice, what it is, what follows it and what does not."""
        if self.tto is None:
            return {"available": False}
        mode = self.mode(user)
        out: Dict[str, Any] = {"available": True, "mode": mode, "default": BOOT,
                               "choices": [{"id": k, "label": CHOICE[k], "about": ABOUT[k]} for k in (BOOT, PPK)],
                               "ref": self.mode_ref, "book": "tto"}
        if user:
            calc = self.svc._calc(user, self.tto)
            si, rc = self.status_cells["text"]
            text = calc.get(si, *divmod(rc, COLS))
            out["status"] = text if isinstance(text, str) else ""
            out["on"] = calc.get(*self._cell3(self.status_cells["on"])) == 1.0
        st = self._shared.get("tto")
        out["stats"] = {"made": self.stats["made"], "last_ms": self.stats["last_ms"], "at": self.stats["at"],
                        "users": len(self.ppk_users()), "errors": list((st or {}).get("curves", {}).get("errors") or [])}
        return out

    @staticmethod
    def _cell3(cell: Tuple[int, int]) -> Tuple[int, int, int]:
        si, rc = cell
        r, c = divmod(rc, COLS)
        return si, r, c

    def forget(self, user: str) -> None:
        """A user gone idle (their calculations given back): what was made for them goes too."""
        for bid in ("tto", "asw"):
            self._own.pop((user, bid), None)
            self._typed.pop((user, bid), None)
        self._own.pop((user, "list"), None)
