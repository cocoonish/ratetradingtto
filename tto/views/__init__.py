"""Dashboard pages.  Each ``*.json`` file in this folder defines one page:

``{"id", "title", "group", "book", "sheet", "order", "inputs": [...], "panels": [...]}``

* ``inputs``  cells the user may type into: ``{"range": "W33:X47", "scope": "user"|"shared", "group": "...",
  "kind": "auto|number|pct|date|text", "label": "..."}`` (ranges without a sheet refer to the page's sheet)
* ``panels``  ``{"type": "table", "range": "B29:J39", "title": "...", "hidden": false}`` |
              (``"sheet": "VIOP", "borrowed": true``: a few cells of another page's sheet, shown here as well) |
  ``{"type": "chart", "chart": <index of the chart on the sheet>}`` | ``{"type": "notes", "range": ...}`` |
  ``{"type": "custom", "component": "..."}``
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
        views.append(v)
    views.sort(key=lambda v: (v["order"], v["id"]))
    return views
