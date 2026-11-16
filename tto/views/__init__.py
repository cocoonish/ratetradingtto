"""Dashboard pages.  Each ``*.json`` file in this folder defines one page:

``{"id", "title", "group", "book", "sheet", "order", "inputs": [...], "panels": [...]}``

* ``inputs``  cells the user may type into: ``{"range": "W33:X47", "scope": "user"|"shared", "group": "...",
  "kind": "auto|number|amount|pct|date|text|list", "label": "..."}`` (ranges without a sheet refer to the page's sheet);
  ``"options": ["B", "S"]`` offers a list (``"kind": "list"``: nothing else is taken) and ``"aliases": {"Sat": "S"}``
  names words that mean one of its items.  ``"kind": "amount"`` is what makes a cell take the desk's amounts ("5m",
  "250k", "1,5mn", "2b" / "2mr": tto/inputs.py) - a number format cannot tell an amount from swap points (both
  ``#,##0``), so a size not declared one keeps the plain parsing.
  A date input (``"kind": "date"``, or a cell formatted as a date) takes the desk's date shortcuts as well - "1A" /
  "1M", "3A", "1Y", "2H" / "2W", "ON", "TN", "SN", "ay sonu", "IMM", "+5" (tto/shortcuts.py); the date they stand for
  is stored.  ``"tenor"`` says how they count there: ``{"pair": "USDTRY"}`` - the calendar and the spot convention
  (USDTRY: T+1 on TRY + USD; EURTRY: T+2 on TRY + EUR; EURUSD: T+2 on USD + EUR; "TRY", the default: the workbook's
  SPOTDATE, T+1 on the TRY list) -, ``"pair_col": "A"`` - the pair is the one written in that column of the row - and
  ``"from"`` - the cell's natural start: a cell (``"C167"``, ``"Forward!I2"``), a column of the same row (``"B"``: the
  end date of a row counts from its start date) or a row of the same column (``"40"``); the cell itself, an empty start
  or one that is no date: today's spot of the pair (as the user's own calculation has it).
* ``panels``  ``{"type": "table", "range": "B29:J39", "title": "...", "hidden": false}`` |
              (``"sheet": "VIOP", "borrowed": true``: a few cells of another page's sheet, shown here as well) |
  ``{"type": "chart", "chart": <index of the chart on the sheet>}`` | ``{"type": "notes", "range": ...}`` |
  ``{"type": "custom", "component": "..."}``; a table may show its columns in an order of its own (``"cols": ["K", "O",
  "Z", "P"]``: by letter, one not named is not shown) and take tooltips from the workbook (``"tips": {"W": "AA"}``: the
  text in column AA of a row is the tooltip of the row's cell in column W); ``"ranked": true`` a ranking (the best k trades, the cheapest bonds): a
  launchpad keeps a choice of its rows by their number - the row is a place, whatever fills it today
* ``"copyable": true`` (a table)  a calculator a user may open again as temporary copies ("Geçici kopya aç" in its
  menu; ``tto/copies.py``): "… · kopya 2" right under it, each with inputs of its own, computed for that copy only.  Only
  for a visible table of a sheet's range whose inputs are all personal (``"scope": "user"``) - a table with a shared input
  is refused at the start (the log says so), as a copy of a desk-wide setting would mislead.  Its inputs that go into a
  Bloomberg request (and a cell of a meeting's row or of a holiday list) stay read-only in a copy.  ``"copy_with":
  ["B10D"]``: the tables of the same page shown above it in a copy - the strip of inputs the table is computed from
  when they stand in a row of their own (they are inputs of the copy too, under the same rule)
* ``panels`` (more of a table)  ``"quote"``: "Kota mesajı", the bid / ask of chosen rows as a chat message (quote.js);
  ``"trade"``: "İşlem gir", a row as a trade to enter; ``"client_quote"``: "Kotasyon kopyala", the table's prices as a
  quote to send a client, Turkish or English (tto/quotes.py) - which cells make it::

      "client_quote": {"pair": "USDTRY", "title": "forward", "rows": "5:14", "label": "A", "alt": "B",
                       "alt_when": "serbest", "head": "Vade", "head_en": "Tenor", "start": "G2", "spot": ["F4", "G4"],
                       "end": "B", "days": "C", "points": ["H", "I"], "outright": ["J", "K"], "try": ["M", "N"],
                       "ccy": "O"}

  the fields (each optional, in this order in the quote): ``side`` (B / S - "USD alış" -, LONG / SHORT …), ``start``
  (the value date), ``end`` (the maturity; ``days`` beside it), ``spot``, ``near`` (a forward-forward's near outright),
  ``points``, ``outright``, ``try`` (TRY rate), ``ccy`` (the foreign rate: USD / EUR by the pair), ``on`` (O/N
  equivalent), ``amount`` (with the pair's currency).  A field is a cell (``"G2"``, ``"Forward!I2"``), a column of the
  quoted row (``"B"``), a pair ``[bid, ask]`` of those (two-sided: "34,25 / 34,45"), or ``{"src": …, "label": "…",
  "label_en": "…"}`` for a label of its own.  Each number is written as its cell's format shows it (a rate in per cent
  either way), in the quote's language.  ``pair``: the instrument as text - or ``{"src": "A"}``, read from a cell / the
  row's column; ``title`` / ``title_en``: the word after it.  ``rows`` makes it a table of quotes, one a sheet row
  (sources by column; ``label`` names a row - ``alt`` instead when it is empty or says ``alt_when`` -, ``head`` /
  ``head_en`` is that column's caption): the header button copies every row that has a price, a line each, what is
  the same for all (cells) above them; a right click on a row copies that row's quote.  ``parts``: quotes side by side
  (``[{"pair": "USDTRY", "start": "AH5", …}, {"pair": "EURTRY", …}]``, each with what the spec says for all) - both are
  copied, one from the button's menu.
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
from typing import Any, Dict, List, Optional

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


def layout(view: Dict[str, Any], shown: List[str], copies: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """The tabs of a page for the panels that are actually sent (``shown``: their ids, in page order).

    Returns ``{"pinned": [...], "sections": [{"id", "title", "note", "panels": [...]}, ...]}``; ``sections`` is
    empty for a page without tabs.  Panels that are sent but listed nowhere (helper tables, a chart or picture
    the page definition does not name) go to a last tab, so that nothing is lost.  ``copies``: a table's temporary
    copies (table id -> their panel ids), placed right after it wherever it is listed.
    """
    have = set(shown)
    copies = copies or {}

    def with_copies(ids: List[str]) -> List[str]:
        out: List[str] = []
        for p in ids:
            out.append(p)
            out.extend(c for c in copies.get(p, ()) if c in have)
        return out

    pinned = with_copies([p for p in view.get("pinned", []) if p in have])
    sections = []
    placed = set(pinned)
    for sec in view.get("sections", []):
        ids = with_copies([p for p in sec.get("panels", []) if p in have])
        placed.update(ids)
        if ids:
            sections.append({"id": sec["id"], "title": sec["title"], "note": sec.get("note"), "panels": ids})
    if not sections:
        return {"pinned": [], "sections": []}
    rest = [p for p in shown if p not in placed]
    if rest:
        sections.append({"id": "aux", "title": "Yardımcı tablolar", "note": None, "panels": rest})
    return {"pinned": pinned, "sections": sections}
