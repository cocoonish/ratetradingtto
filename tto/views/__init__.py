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
* ``"copyable": true`` (a table)  a calculator a user may open again as temporary copies ("Geçici kopya aç" in its
  menu; ``tto/copies.py``): "… · kopya 2" right under it, each with inputs of its own, computed for that copy only.  Only
  for a visible table of a sheet's range whose inputs are all personal (``"scope": "user"``) - a table with a shared input
  is refused at the start (the log says so), as a copy of a desk-wide setting would mislead.  Its inputs that go into a
  Bloomberg request (and a cell of a meeting's row or of a holiday list) stay read-only in a copy.  ``"copy_with":
  ["B10D"]``: the tables of the same page shown above it in a copy - the strip of inputs the table is computed from
  when they stand in a row of their own (they are inputs of the copy too, under the same rule)
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
