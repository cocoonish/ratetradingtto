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
#: the engine-level groups of the PPK cells (one dependency bit each: the OIS nodes, the offshore table, the ASW nodes)
GROUP_OIS, GROUP_OFF, GROUP_ASW, GROUP_MIRROR = "interp-ppk-ois", "interp-ppk-off", "interp-ppk-asw", "interp-mode-asw"
#: the offshore table's rows past the curve's last node lie on its last segment, this many days apart
FAR = 36500.0
#: the layers kept: a user's calculation with the curve on Bootstrap, the desk's on PPK
BOOT_LAYER, PPK_LAYER = "interp-boot", "interp-ppk"


def _num(v: Any) -> Optional[float]:
    return float(v) if type(v) in (float, int) and v == v else None


def off_nodes(curve: Any, quotes: Sequence[Any], rows: int) -> Optional[List[Tuple[float, float, float]]]:
    """The offshore curve's node table on PPK: ``(day, ln DF, slope)`` at the spot, every step of the PPK-shaped curve
    (a meeting, the end of a basis stretch) up to its last quote and that quote's day - the readers interpolate ln DF
    linearly between them, which is the step curve's own shape up to the weekend term - then the last segment's slope on,
    the rest of the ``rows`` on that segment far beyond (as the sheet's own curve goes on past its last node).  ``None``
    without a curve or a quote."""
    if curve is None or not quotes:
        return None
    last = max(q.end for q in quotes)
    days = sorted({0.0, last} | {d for d, _ in curve.steps() if 0.0 < d < last})
    if len(days) > rows:                            # (never with ~80 meetings and 19 quotes: the quotes kept first)
        ends = {q.end for q in quotes}
        keep = sorted(ends | {0.0})
        rest = [d for d in days if d not in ends and d != 0.0][:max(rows - len(keep), 0)]
        days = sorted(set(keep) | set(rest))
    ln = [-curve.lng(d) for d in days]
    if len(days) < 2:
        return None
    slopes = [(ln[i + 1] - ln[i]) / (days[i + 1] - days[i]) for i in range(len(days) - 1)]
    slopes.append(slopes[-1])
    out = list(zip(days, ln, slopes))
    d0, l0, s0 = out[-1]
    k = 1
    while len(out) < rows:
        out.append((d0 + FAR * k, l0 + s0 * FAR * k, s0))
        k += 1
    return out


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

        def make():
            get = lambda sheet, r, c: calc.get(idx[sheet], r, c)          # noqa: E731
            curves = pk.read(get)
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
        key = (eng.layout, calc.serial)
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

    # ------------------------------------------------------------------ a user's calculation
    def sync(self, user: Optional[str], book: Any) -> None:
        """Before a user's calculation of ``book`` is used (``Service._calc``): on PPK, the desk's PPK cells current and
        the user's own where their inputs make them their own (and, in the ASW book, their choice mirrored); on Bootstrap
        nothing of theirs worked out."""
        if not user or self.tto is None or book is None or book.id not in ("tto", "asw") or \
                (book.id == "asw" and self.asw is None):
            return
        eng = book.engine
        if self.mode(user) != PPK:
            if eng.derived.get(user):
                eng.set_derived(user, {}, self.svc._overlay(user, book))
            self._own.pop((user, book.id), None)
            return
        with self._lock:
            tto_st = self.refresh()
            own_tto = self._own_tto(user, tto_st)
            if book.id == "tto":
                eng.set_derived(user, own_tto[0] if own_tto else {}, self.svc._overlay(user, book))
                return
            vals: Dict[Tuple[int, int], Any] = {self.asw_mode_cell: ex.INTERP_PPK}
            asw_st = self._shared.get("asw")
            typed = self.svc._overlay(user, book)
            if own_tto is not None or (asw_st is not None and self._typed_bits(user, book) & asw_st["mask"]):
                calc = eng.users.get(user) or eng.set_derived(user, vals, typed) or eng.set_user_inputs(user, typed)
                vals.update(self._own_asw(user, calc, own_tto[1] if own_tto else tto_st["curves"]))
            else:
                self._own.pop((user, "asw"), None)
            eng.set_derived(user, vals, typed)

    def _own_tto(self, user: str, tto_st: Dict[str, Any]) -> Optional[Tuple[Dict[Tuple[int, int], Any], Dict[str, Any]]]:
        """The user's own PPK cells of the TRY workbook when their own inputs touch what the desk's were made of: made
        from their calculation with the curve on Bootstrap.  ``None``: the desk's stand for them."""
        book = self.tto
        if not (self._typed_bits(user, book, (self.mode_cell,)) & tto_st["mask"]):
            self._own.pop((user, "tto"), None)
            return None
        eng = book.engine
        base = eng.users.get(user) or eng.set_user_inputs(user, self.svc._overlay(user, book))
        view = eng.layer((user, BOOT_LAYER), base, {self.mode_cell: ex.INTERP_BOOT})
        key = (eng.layout, view.serial, base.serial)
        st = self._own.get((user, "tto"))
        if st is not None and self._fresh(st, key, [(view, st["epoch"], st["mask"])]):
            return st["values"], st["curves"]
        t0 = time.perf_counter()
        vals, curves, mask = self._tto_values(view)
        self._own[(user, "tto")] = {"key": key, "epoch": view.epoch, "mask": mask, "values": vals, "curves": curves}
        self.stats.update(own=self.stats["own"] + 1, own_ms=self.stats["own_ms"] + (time.perf_counter() - t0) * 1000.0)
        return vals, curves

    def _own_asw(self, user: str, base: Any, curves: Dict[str, Any]) -> Dict[Tuple[int, int], Any]:
        """The user's own PPK cells of the ASW book: MPC ima as they have it, calibrated to their ASW book's quotes."""
        eng = self.asw.engine
        view = eng.layer((user, BOOT_LAYER), base, {self.asw_mode_cell: ex.INTERP_BOOT})
        tto_view = self.boot_view(user, self.tto, sync=False)
        vals, _ = self._asw_values(curves, tto_view, view)
        return vals

    # ------------------------------------------------------------------ calculations on a curve
    def boot_view(self, user: Optional[str], book: Any, sync: bool = True) -> Any:
        """The user's calculation of ``book`` with the curve on Bootstrap whatever their choice - their own inputs
        otherwise as they are (a layer over it on PPK).  Nobody: the desk's."""
        if not user:
            return book.engine.shared
        calc = self.svc._calc(user, book) if sync else (book.engine.users.get(user) or book.engine.shared)
        if self.tto is None or self.mode(user) != PPK or book.id not in ("tto", "asw") or calc is book.engine.shared:
            return calc
        cell = self.mode_cell if book.id == "tto" else getattr(self, "asw_mode_cell", None)
        if cell is None:
            return calc
        return book.engine.layer((user, BOOT_LAYER), calc, {cell: ex.INTERP_BOOT})

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
        return {"mode": PPK, "on": on, "off": at("off") == 1.0, "label": "Eğri: PPK basamak" if on else "Eğri: PPK (kurulamadı)",
                "tip": (text if isinstance(text, str) else "") + "\n" + ABOUT[PPK] + "\nAyarlar → Eğri interpolasyonu: "
                       "sayfaların, Trades'in MTM'inin bu eğriyle; Günlük İşlemler ve masanın kayıtları (MTM / kapanış "
                       "kayıtlarının Bootstrap'ı, alarmlar, quant, tarihçe) Bootstrap'ta. Sizin ayarınız: başkaları Bootstrap "
                       "görebilir."}

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
