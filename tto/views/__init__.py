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
