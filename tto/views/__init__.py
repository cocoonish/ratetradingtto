"""Dashboard pages.  Each ``*.json`` file in this folder defines one page:

``{"id", "title", "group", "book", "sheet", "order", "inputs": [...], "panels": [...]}``

* ``inputs``  cells the user may type into: ``{"range": "W33:X47", "scope": "user"|"shared", "group": "...",
  "kind": "auto|number|amount|pct|date|text|list", "label": "..."}`` (ranges without a sheet refer to the page's sheet);
  ``"options": ["B", "S"]`` offers a list (``"kind": "list"``: nothing else is taken) and ``"aliases": {"Sat": "S"}``
  names words that mean one of its items
* ``panels``  ``{"type": "table", "range": "B29:J39", "title": "...", "hidden": false}`` |
              (``"sheet": "VIOP", "borrowed": true``: a few cells of another page's sheet, shown here as well) |
  ``{"type": "chart", "chart": <index of the chart on the sheet>}`` | ``{"type": "notes", "range": ...}`` |
  ``{"type": "custom", "component": "..."}``; a table may show its columns in an order of its own (``"cols": ["K", "O",
  "Z", "P"]``: by letter, one not named is not shown) and take tooltips from the workbook (``"tips": {"W": "AA"}``: the
  text in column AA of a row is the tooltip of the row's cell in column W); ``"ranked": true`` a ranking (the best k trades, the cheapest bonds): a
  launchpad keeps a choice of its rows by their number - the row is a place, whatever fills it today
* ``sections`` (optional)  the page in tabs: ``[{"id": "calc", "title": "Hesaplayıcılar", "note": "...",
  "panels": ["B7", "B8"]}, ...]`` - the panels of a tab in the order they are listed (a panel may be listed in
  more than one tab).  Every panel that is shown belongs to a tab or to ``pinned``; the helper tables that
  are not listed are gathered in a last tab of their own.
* ``pinned`` (optional)  ids of the panels that stay above the tabs whichever tab is open (the value date of
  the Forward page)
* ``admin`` (optional)  ``true``: a page for administrators only (the Motor sheet: the workbook's engine) - not in
  anyone else's menu, search or shortcuts, and refused to them

A table's prices as trades (``"trade"`` on a table panel; :mod:`tto.tradehint`): a right click on a price offers
"İşlem gir", which opens Günlük İşlemler's form filled - the instrument, the dates, the price clicked and the side - and
saves nothing.  The amount and the counterparty are the user's to type.

* ``"cells"``  the price cells: ``{"H": "sp bid", "F173": "fwd"}`` - a column (its prices in the rows ``"first"`` to
  ``"last"``, the sheet's row numbers) or one cell, and what it holds: ``"<what>[ bid|ask]"``.  ``what``:
  ``sp`` / ``fwd`` / ``try`` (an FX forward priced by swap points / the outright / the TRY rate), ``ret`` (a forward on
  the RET curve: RET bid / mid / ask by the side), ``ois`` (an OIS level), ``price`` / ``yield`` (a bond; a yield is
  dealt at the same side's price of its row, ``"yield_price": {"bid": "K", "ask": "L"}``), ``none`` (a price with no form
  in Günlük İşlemler: "İşlem gir" greyed, saying ``"why"``).  The side is the desk's as it quotes: at its bid it buys
  (the currency forward, the bond; an OIS rate: PAY), at its ask it sells; no side (a mid): the user chooses.
* the instrument is read from the clicked row's own cells, never from its place (rows move: the PPK calendar, the
  VİOP roll, the bond lists).  A forward: ``"pair"`` and its value date - ``"date": "B45"`` (one cell for the table,
  ``"MASA!E60"`` on another sheet), ``"date_col": "B"`` (each row's date) or ``"tenor_col": "V"`` (each row's tenor,
  dated from the pair's spot).  An OIS level: ``"strategy"`` ``"outright"`` with ``"tenor_col"``, or ``"mpc"`` with
  ``"start_col"`` / ``"end_col"`` (a meeting swap's two days).  A bond: ``"isin_col"``.
* ``"label"`` / ``"alt"`` / ``"alt_when"`` / ``"bid"`` / ``"ask"`` (a forward table): the "İşlem gir" button in the table's
  header as well - a row and a side picked in a dialog, its swap points filled.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))


def load_views() -> List[Dict[str, Any]]:
    views = []
    for name in sorted(os.listdir(HERE)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(HERE, name), encoding="utf-8") as fh:
            v = json.load(fh)
        v.setdefault("order", 999)
        v.setdefault("inputs", [])
        v.setdefault("panels", [])
        v.setdefault("sections", [])
        v.setdefault("pinned", [])
        views.append(v)
    views.sort(key=lambda v: (v["order"], v["id"]))
    return views


def layout(view: Dict[str, Any], shown: List[str]) -> Dict[str, Any]:
    """The tabs of a page for the panels that are actually sent (``shown``: their ids, in page order).

    Returns ``{"pinned": [...], "sections": [{"id", "title", "note", "panels": [...]}, ...]}``; ``sections`` is
    empty for a page without tabs.  Panels that are sent but listed nowhere (helper tables, a chart or picture
    the page definition does not name) go to a last tab, so that nothing is lost.
    """
    have = set(shown)
    pinned = [p for p in view.get("pinned", []) if p in have]
    sections = []
    placed = set(pinned)
    for sec in view.get("sections", []):
        ids = [p for p in sec.get("panels", []) if p in have]
        placed.update(ids)
        if ids:
            sections.append({"id": sec["id"], "title": sec["title"], "note": sec.get("note"), "panels": ids})
    if not sections:
        return {"pinned": [], "sections": []}
    rest = [p for p in shown if p not in placed]
    if rest:
        sections.append({"id": "aux", "title": "Yardımcı tablolar", "note": None, "panels": rest})
    return {"pinned": pinned, "sections": sections}
