"""The top strip's USDTRY spot in the workbooks that cannot read the TRY workbook.

The desk, 28.11.2026 (B4): "Bbg veya manual spot" - every page uses the top strip's spot, ``MASA!H2`` of the TRY workbook:
the mid of the manual spot typed in VIOP!AA9:AA10, else of Bloomberg's USDTRY Curncy BID / ASK.  The TRY workbook's own
pages read it by formula (``extras.SPOT_SOURCES``).  Borsa Swap's workbook is a book of its own: no formula of it can read
another book, so the service writes the strip's spot into it - ``EK_SPOT!B2``, which its spot ``Sheet1!AD18`` reads (blank:
Bloomberg's PX_LAST, as before) - as tto/varrisk.py writes EK_VAR: a shared value of the market, uncounted (no input of the
desk's), one dependency bit.

When: before any calculation of that book (:meth:`tto.service.Service._calc`) - a page, an alarm, a box.  Every write of the
strip's spot (a market tick of USDTRY, the manual spot typed or cleared) moves the service's generation, so the page asks
again and its calculation takes the spot of the moment; a spot that did not change writes nothing.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

from . import extras as ex
from .xl.model import COLS

#: the engine's dependency group of the cell written
GROUP = "strip-spot"
#: where the strip's spot is read (the TRY workbook)
STRIP = "MASA!H2"


class SpotLink(object):
    def __init__(self, svc: Any):
        self.svc = svc
        self.tto = svc.books.get("tto")
        self.borsa = svc.books.get("borsa")
        self.strip: Optional[Tuple[int, int]] = None
        self.cell: Optional[Tuple[int, int]] = None
        if self.tto is None or self.borsa is None or ex.SPOT_SHEET not in self.borsa.model.sheet_index:
            self.borsa = None                     # (the addition left out: Borsa keeps Bloomberg's own spot)
            return
        try:
            self.strip = self.tto.cell(STRIP)
            self.cell = self.borsa.cell("%s!%s" % (ex.SPOT_SHEET, ex.SPOT_CELL))
        except (KeyError, ValueError):
            self.borsa = None

    @property
    def available(self) -> bool:
        return self.borsa is not None and self.cell is not None and self.strip is not None

    def declare(self) -> None:
        """The cell the service writes, to Borsa's engine - before anything is calculated (nobody types into it)."""
        if self.available:
            self.borsa.engine.declare_inputs([self.cell], group=GROUP)

    def spot(self) -> Optional[float]:
        """The strip's spot now (the TRY workbook's shared calculation: the same for everybody), or ``None``."""
        si, rc = self.strip
        v = self.tto.engine.shared.get(si, *divmod(rc, COLS))
        return v if type(v) is float and v > 0 else None

    def refresh(self) -> None:
        """Borsa's copy of the strip's spot, when it changed (the calculation thread)."""
        if not self.available:
            return
        self.borsa.engine.set_inputs({self.cell: self.spot()}, counted=False)
