"""Dashboard pages.  Each ``*.json`` file in this folder defines one page:

``{"id", "title", "group", "book", "sheet", "order", "inputs": [...], "panels": [...]}``

* ``inputs``  cells the user may type into: ``{"range": "W33:X47", "scope": "user"|"shared", "group": "...",
  "kind": "auto|number|amount|pct|date|text|list|check", "label": "..."}`` (ranges without a sheet refer to the page's
  sheet); ``"options": ["B", "S"]`` offers a list (``"kind": "list"``: nothing else is taken) and ``"aliases": {"Sat":
  "S"}`` names words that mean one of its items.  ``"kind": "amount"`` is what makes a cell take the desk's amounts ("5m",
  "250k", "1,5mn", "2b" / "2mr": tto/inputs.py) - a number format cannot tell an amount from swap points (both
  ``#,##0``), so a size not declared one keeps the plain parsing.  ``"kind": "check"`` is a tick box: 1 ticked, 0 not
  (``inputs.parse_check``: "evet" / "hayır", TRUE / FALSE, "x" / "✓" too; nothing else) - the page draws a box a click
  ticks, written as a value typed; give the cell a formula default (``=1`` / ``=0``) so that Delete brings it back, and a
  box that reads nothing (a conditional number format ";;;" hiding it while its block is off) is not offered at all.
  A date input (``"kind": "date"``, or a cell formatted as a date) takes the desk's date shortcuts as well - "1A" /
  "1M", "3A", "1Y", "2H" / "2W", "ON", "TN", "SN", "ay sonu", "IMM", "+5" (tto/shortcuts.py); the date they stand for
  is stored.  ``"tenor"`` says how they count there: ``{"pair": "USDTRY"}`` - the calendar and the spot convention
  (USDTRY: T+1 on TRY + USD; EURTRY: T+2 on TRY + EUR; EURUSD: T+2 on USD + EUR; "TRY", the default: the workbook's
  SPOTDATE, T+1 on the TRY list) -, ``"pair_col": "A"`` - the pair is the one written in that column of the row - and
  ``"from"`` - the cell's natural start: a cell (``"C167"``, ``"Forward!I2"``), a column of the same row (``"B"``: the
  end date of a row counts from its start date) or a row of the same column (``"40"``); the cell itself, an empty start
  or one that is no date: today's spot of the pair (as the user's own calculation has it).  What ``"tenor"`` does not
  say the cell's formulas do (tto/datecells.py): the pair of the dates it is made of (``=+I2``: USDTRY), and - for a
  date input without a ``"tenor"`` (or a cell typed over: "Elle değer") - the start the workbook counts its days from
  (``O35 = O34-O33``: the End counts from the Start).  A date input whose cell is not formatted as a date is shown as
  one (``dd.mm.yyyy``).
* ``twoway`` (optional)  two-way tables (:mod:`tto.twoway`; the desk, 24.11.2026: "hangisine ben girdiysem diğerini
  hesaplasın ... Genel olarak tablolar bu şekilde olmalı")::

      "twoway": [{"id": "ekfwd-quote", "sheet": "EK_FWD", "label": "FORWARD KOTASYON · USDTRY", "note": "İki yönlü: ...",
                  "scope": "user",
                  "members": [{"name": "Spread", "range": "D5:E14"},
                              {"name": "TRY %", "range": "M5:N14", "store": "AN5:AO14", "label": "...", "kind": "number"},
                              {"name": "Puan", "range": "H5:I14", "store": "AP5:AQ14"}, ...]}]

  same-shaped ranges of one sheet (``"sheet"``: the page's unless given), each a way of giving the same value (its
  ``"name"`` says which on the page); the cells at one place of every member are one **row-side** (a value date's bid).
  What is typed into a member is kept in its ``"store"``: a blank range of its shape, declared as an input by the module
  (``"scope"`` the group's, "user" unless given; ``"kind"``, ``"label"`` for "Girdilerim") - never listed in
  ``inputs``; the member's own cells are formulas showing the store, or the value worked out from whichever store holds
  one.  At most one member has no store and keeps what is typed in its own cells: an input of ``inputs`` (the table's
  input from before) whose formula default is the value the other stores give.  The member typed last is the row-side's
  **anchor** (the others' stores emptied in the same write); Delete or a reset of any cell of a row-side takes it back to
  its default; a pasted block gives each row-side its last value; writes, pastes, resets, scenarios, temporary copies,
  input formulas and the page's marks (``an``: the anchor - ✎, bold -, ``ao``: worked out from it) all go through the
  stores.  ``"note"`` is said under every table that shows the group's members.  A declaration that cannot work (shapes
  that differ, a store that is not blank or is an input already, a store-less member that is not an input, two of them,
  a member cell that is no formula, a cell of two groups) is left out with the reason in the log
  (``Service.twoway.problems``).  How a table adopts it, and its limits: :mod:`tto.twoway`.
* ``panels``  ``{"type": "table", "range": "B29:J39", "title": "...", "hidden": false}`` |
              (``"sheet": "VIOP", "borrowed": true``: a few cells of another page's sheet, shown here as well) |
  ``{"type": "chart", "chart": <index of the chart on the sheet>}`` | ``{"type": "notes", "range": ...}`` |
  ``{"type": "custom", "component": "..."}``; a table may show its columns in an order of its own (``"cols": ["K", "O",
  "Z", "P"]``: by letter, one not named is not shown) and take tooltips from the workbook (``"tips": {"W": "AA"}``: the
  text in column AA of a row is the tooltip of the row's cell in column W); ``"ranked": true`` a ranking (the best k trades, the cheapest bonds): a
  launchpad keeps a choice of its rows by their number - the row is a place, whatever fills it today; ``"lift": false``
  keeps the table's first row in it even when it looks like the sheet's caption (one bold text cell: a label whose input
  beside it is empty - the bond carry's "ISIN" - would otherwise become the panel's title, its input gone with it)
* ``{"type": "chart", "ppk": "interp"}``  a chart of the dashboard's own: OIS · PPK's interpolation chart, Bootstrap and
  PPK basamak (``tto/interpchart.py``: every horizon and curve sent at once, the page's selectors pick one);
  ``"full": true`` (any panel): it takes the page's whole width
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
  are not listed are gathered in a last tab of their own.  An element of ``panels`` may be a list of panel ids
  (``["B3", ["B2", "B8"], "B5"]``): those panels one under the other, as one column at that place of the row - small
  panels beside a tall one (the desk, 27.11.2026: proposal 8).  :func:`load_views` flattens it: ``panels`` is the ids in
  order (what every reader of a tab knows), ``stacks`` the columns (``[["B2", "B8"]]``); the page's answer carries
  both (:func:`layout`).
* ``pinned`` (optional)  ids of the panels that stay above the tabs whichever tab is open (the value date of
  the Forward page); a list in it is a column of panels too (``pinned_stacks``)

Layout options of a panel (the desk, 27.11.2026: "Düzen: sayfalar tek tek", ``docs/desk-decisions.md``):

* ``"freeze": n`` (a table)  its first n columns - as the panel shows them, after ``"cols"`` - stay in view while it
  scrolls sideways, in place of the workbook's frozen panes (``0``: none); a table of the dashboard's own
  (``"generated"``) takes it as well.  With the columns Excel hides shown ("Yardımcı tablolar") n counts the others.
* ``"limit": {"rows": n}`` (a table)  only its first n rows under the captions are shown; "Tümü (N)" in its header shows
  the rest (each browser remembers it, as the tabs and the folded panels).
* ``"fit": true``  the panel is as wide as its table, never stretched (``.panel.fit``; in a column of ``sections``, not
  as wide as the column's widest panel).
* ``"rows": [19, 25, 26]`` (a table)  the twin of ``"cols"`` (the desk, 28.11.2026: B15): only these rows of the panel's
  range, by the sheet's row number, in this order - a row not named is not shown (one the table does not have, left out
  as empty, is skipped).  Every cell keeps its row number (an input is typed into its own cell); a cell merged down over
  rows keeps the rows that still follow it; the answer's ``ar`` names every row of the range, so that a block pasted
  lands on the rows on screen.  VİOP's Kontratlar: the rows its four tables repeat (1st / 2nd Date, VKGS, Spot, USD)
  shown once, in VIOP BID.
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
  dated from the pair's spot).  A table of two pairs side by side names a price cell's own pair in ``"pairs"``, keyed
  as ``"cells"`` (``{"P": "EURTRY", "T": "EURTRY"}``: TOPLU FORWARD's EURTRY columns; every other price is the table's
  ``"pair"``) - each key a forward price of ``"cells"``.  An OIS level: ``"strategy"`` ``"mpc"`` with ``"start_col"`` /
  ``"end_col"`` (a meeting swap's two days), or one named in a column of the row, ``"tenor_col"`` - ``"outright"``
  ("2Y"), ``"spread"`` ("1M / 18M"), ``"fly"`` ("2M/3M/6M"), ``"fra"`` ("18M6M", "Spot3M": start and length),
  ``"mpcspread"`` ("MPC1 / MPC2": MPC OIS's periods k and k + 1) or ``"auto"`` (the name says which: Masa's signals); a
  price whose name stands in another column: ``"tenor_cols"``, keyed as ``"cells"`` (:func:`tto.tradehint.ois_name`).
  A bond: ``"isin_col"``.
* ``"label"`` / ``"alt"`` / ``"alt_when"`` / ``"bid"`` / ``"ask"`` (a forward table): the "İşlem gir" button in the table's
  header as well - a row and a side picked in a dialog, its swap points filled.

A button of the dashboard's own in a table's header (``"action"``): ``"ret"`` the RET editor, ``"add-isin"`` a bond
list's "+ ISIN ekle" (with ``"add"``), ``"toplu-islem"`` TOPLU FORWARD's "İşleme al" - every row with a Tutar into
Günlük İşlemler's "Excel'den yapıştır" (FX Forward), its preview and save as they are, the booked rows' Tutar emptied
(``/api/blotter/bulk/toplu-forward``: :func:`tto.entry.bulk_forward_paste`).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from ..xl.model import parse_range

HERE = os.path.dirname(os.path.abspath(__file__))


def flat_ids(items: Any) -> Tuple[List[str], List[List[str]]]:
    """A tab's (or the pinned) panel ids, where an element may be a list - a column of panels stacked at that place:
    the ids in order, and the columns of two panels or more.  Anything else in it (a number, a list in a list) is left
    out here; :func:`check_view` says so (``tests/test_duzen_cekirdek.py`` runs it on every page)."""
    flat: List[str] = []
    stacks: List[List[str]] = []
    for x in items or ():
        if isinstance(x, str):
            flat.append(x)
        elif isinstance(x, (list, tuple)):
            ids = [p for p in x if isinstance(p, str)]
            flat.extend(ids)
            if len(ids) > 1:
                stacks.append(ids)
    return flat, stacks


def normalize(v: Dict[str, Any]) -> Dict[str, Any]:
    """A page's definition as the dashboard reads it (in place; returned): its defaults, and a column of panels in a tab
    (a list among its ids) flat - the ids as every reader of a tab knows them -, the columns beside them (``stacks``,
    ``pinned_stacks``): what the page's answer carries for the browser to lay out (:func:`layout`)."""
    v.setdefault("order", 999)
    v.setdefault("inputs", [])
    v.setdefault("panels", [])
    v.setdefault("sections", [])
    v.setdefault("pinned", [])
    for sec in v["sections"]:
        if isinstance(sec, dict):
            sec["panels"], stacks = flat_ids(sec.get("panels"))
            if stacks:
                sec["stacks"] = stacks
    v["pinned"], stacks = flat_ids(v["pinned"])
    if stacks:
        v["pinned_stacks"] = stacks
    return v


def load_views() -> List[Dict[str, Any]]:
    views = []
    for name in sorted(os.listdir(HERE)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(HERE, name), encoding="utf-8") as fh:
            views.append(normalize(json.load(fh)))
    views.sort(key=lambda v: (v["order"], v["id"]))
    return views


def check_view(view: Dict[str, Any], raw: Optional[Dict[str, Any]] = None) -> List[str]:
    """What is wrong with a page's layout options (empty: nothing) - ``freeze``, ``limit``, ``fit``, ``rows`` and the
    columns of panels in its tabs; ``raw``: the page's JSON as written (the lists in its tabs before :func:`load_views`
    flattened them).  The loader takes what it can; the views' test fails on any of these."""
    out: List[str] = []
    vid = view.get("id")
    ids = {p.get("id") for p in view.get("panels", [])}
    for p in view.get("panels", []):
        pid = "%s/%s" % (vid, p.get("id"))
        if "freeze" in p:
            n = p["freeze"]
            if isinstance(n, bool) or not isinstance(n, int) or n < 0:
                out.append("%s: freeze bir sütun sayısı olur (0 ya da daha büyük): %r" % (pid, n))
            if p.get("type") not in ("table", "generated"):
                out.append("%s: freeze yalnız tabloda" % pid)
        if "limit" in p:
            lim = p["limit"]
            rows = lim.get("rows") if isinstance(lim, dict) else None
            if not isinstance(lim, dict) or set(lim) != {"rows"} or isinstance(rows, bool) or not isinstance(rows, int) \
                    or rows < 1:
                out.append("%s: limit {\"rows\": n} olur (n en az 1): %r" % (pid, lim))
            if p.get("type") not in ("table", "generated"):
                out.append("%s: limit yalnız tabloda" % pid)
        if "fit" in p and not isinstance(p["fit"], bool):
            out.append("%s: fit true ya da false olur: %r" % (pid, p["fit"]))
        if "rows" in p:
            out.extend("%s: %s" % (pid, x) for x in _check_rows(p))
    src = raw if raw is not None else view
    tabs = [("sekme %s" % s.get("id"), s.get("panels") or []) for s in src.get("sections") or [] if isinstance(s, dict)]
    tabs.append(("pinned", src.get("pinned") or []))
    for where, items in tabs:
        seen = set()
        for x in items:
            group = x if isinstance(x, (list, tuple)) else [x]
            if isinstance(x, (list, tuple)) and len(x) < 2:
                out.append("%s/%s: bir sütun en az iki panel olur: %r" % (vid, where, x))
            for q in group:
                if not isinstance(q, str):
                    out.append("%s/%s: panel adı yazı olur (sütun içinde sütun olmaz): %r" % (vid, where, q))
                    continue
                if q not in ids:
                    out.append("%s/%s: böyle bir panel yok: %s" % (vid, where, q))
                if q in seen:
                    out.append("%s/%s: %s iki kez" % (vid, where, q))
                seen.add(q)
    return out


def _check_rows(p: Dict[str, Any]) -> List[str]:
    """What is wrong with a panel's ``"rows"``: a list of the sheet's row numbers inside its range, each once, on a table."""
    rows = p["rows"]
    if p.get("type") != "table":
        return ["rows yalnız tabloda"]
    if not isinstance(rows, list) or not rows:
        return ["rows satır numaralarının listesi olur: %r" % (rows,)]
    out = []
    try:
        r1, _, r2, _ = parse_range(p.get("range") or "")
    except (ValueError, KeyError, IndexError):
        r1, r2 = None, None
    seen = set()
    for r in rows:
        if isinstance(r, bool) or not isinstance(r, int) or r < 1:
            out.append("rows bir satır numarası olur: %r" % (r,))
            continue
        if r1 is not None and not r1 <= r <= r2:
            out.append("rows %d tablonun aralığında değil (%s)" % (r, p.get("range")))
        if r in seen:
            out.append("rows %d iki kez" % r)
        seen.add(r)
    return out


def layout(view: Dict[str, Any], shown: List[str], copies: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """The tabs of a page for the panels that are actually sent (``shown``: their ids, in page order).

    Returns ``{"pinned": [...], "sections": [{"id", "title", "note", "panels": [...]}, ...]}``; ``sections`` is
    empty for a page without tabs.  Panels that are sent but listed nowhere (helper tables, a chart or picture
    the page definition does not name) go to a last tab, so that nothing is lost.  ``copies``: a table's temporary
    copies (table id -> their panel ids), placed right after it wherever it is listed.  A tab with columns of panels
    (``stacks`` of the view, or lists among its ids) has ``"stacks"`` too: each column's panels that are sent (a copy
    with its table), only those of two panels or more; so has the answer (``"pinned_stacks"``) for the pinned ones.
    """
    have = set(shown)
    copies = copies or {}

    def with_copies(ids: List[str]) -> List[str]:
        out: List[str] = []
        for p in ids:
            out.append(p)
            out.extend(c for c in copies.get(p, ()) if c in have)
        return out

    def columns(stacks: List[List[str]]) -> List[List[str]]:
        out = []
        for st in stacks:
            ids = with_copies([p for p in st if p in have])
            if len(ids) > 1:
                out.append(ids)
        return out

    pin_ids, pin_nested = flat_ids(view.get("pinned", []))
    pinned = with_copies([p for p in pin_ids if p in have])
    pin_stacks = columns(view.get("pinned_stacks") or pin_nested)
    sections = []
    placed = set(pinned)
    for sec in view.get("sections", []):
        flat, nested = flat_ids(sec.get("panels", []))
        ids = with_copies([p for p in flat if p in have])
        placed.update(ids)
        if ids:
            out = {"id": sec["id"], "title": sec["title"], "note": sec.get("note"), "panels": ids}
            stacks = columns(sec.get("stacks") or nested)
            if stacks:
                out["stacks"] = stacks
            sections.append(out)
    if not sections:
        return {"pinned": [], "sections": []}
    rest = [p for p in shown if p not in placed]
    if rest:
        sections.append({"id": "aux", "title": "Yardımcı tablolar", "note": None, "panels": rest})
    res = {"pinned": pinned, "sections": sections}
    if pin_stacks:
        res["pinned_stacks"] = pin_stacks
    return res
